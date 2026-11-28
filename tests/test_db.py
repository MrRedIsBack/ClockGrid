from datetime import date, timedelta

import pytest

from clockgrid.db import Database
from clockgrid.weeks import week_bounds

WEEK = date(2026, 11, 23)  # a Monday
PREV_WEEK = WEEK - timedelta(days=7)
WS, WE = week_bounds(WEEK)
HOUR = 3600


@pytest.fixture
def db():
    d = Database()
    yield d
    d.close()


def add(db, name="AI", minutes=300):
    return db.add_goal(name, "#4f8cff", minutes, week_start=WEEK)


def test_add_goal_and_order(db):
    a = add(db, "AI")
    b = add(db, "Study")
    assert [g.name for g in db.goals()] == ["AI", "Study"]
    assert a.sort_order < b.sort_order


def test_reorder_goals(db):
    a, b, c = add(db, "A"), add(db, "B"), add(db, "C")
    db.reorder_goals([c.id, a.id, b.id])
    assert [g.name for g in db.goals()] == ["C", "A", "B"]


def test_add_goal_validation(db):
    with pytest.raises(ValueError):
        db.add_goal("  ", "#000", 60, week_start=WEEK)
    with pytest.raises(ValueError):
        db.add_goal("X", "#000", 0, week_start=WEEK)


def test_starting_a_timer_stops_the_other(db):
    a, b = add(db, "AI"), add(db, "Study")
    db.start_timer(a.id, now=WS + HOUR)
    db.start_timer(b.id, now=WS + 2 * HOUR)
    running = db.running_session()
    assert running.goal_id == b.id
    progress = db.week_progress(WEEK, now=WS + 3 * HOUR)
    assert progress == {a.id: HOUR, b.id: HOUR}


def test_starting_same_timer_is_noop(db):
    a = add(db)
    s1 = db.start_timer(a.id, now=WS + 10)
    s2 = db.start_timer(a.id, now=WS + 20)
    assert s1.id == s2.id


def test_stop_timer(db):
    a = add(db)
    db.start_timer(a.id, now=WS + HOUR)
    stopped = db.stop_timer(now=WS + 2 * HOUR)
    assert stopped.end_ts == WS + 2 * HOUR
    assert db.running_session() is None
    assert db.stop_timer() is None


def test_very_short_sessions_are_discarded(db):
    a, b = add(db, "AI"), add(db, "Study")
    db.start_timer(a.id, now=WS)
    db.start_timer(b.id, now=WS + 10)  # switching after 10s drops the AI session
    assert db.stop_timer(now=WS + 40) is None
    assert db.sessions_between(WS, WE, now=WE) == []


def test_running_session_counts_up_to_now(db):
    a = add(db)
    db.start_timer(a.id, now=WS + HOUR)
    assert db.week_progress(WEEK, now=WS + HOUR + 1800) == {a.id: 1800}


def test_sessions_crossing_week_boundary_are_clipped(db):
    a = add(db)
    db.add_session(a.id, WS - HOUR, WS + HOUR)  # starts in the previous week
    db.add_session(a.id, WE - HOUR, WE + 5 * HOUR)  # ends in the next week
    assert db.week_progress(WEEK, now=WE + 10 * HOUR) == {a.id: 2 * HOUR}


def test_add_session_validation(db):
    a = add(db)
    with pytest.raises(ValueError):
        db.add_session(a.id, WS + HOUR, WS + HOUR)


def test_changing_target_keeps_past_weeks(db):
    a = add(db, minutes=300)
    db.snapshot_week(PREV_WEEK)
    db.update_goal(a.id, name="AI", color="#fff", target_minutes=600, week_start=WEEK)
    assert db.target_minutes_for_week(a.id, PREV_WEEK) == 300
    assert db.target_minutes_for_week(a.id, WEEK) == 600
    # a later week the app was never opened in uses the latest known target
    assert db.target_minutes_for_week(a.id, WEEK + timedelta(days=21)) == 600


def test_archiving_stops_its_running_timer(db):
    a = add(db)
    db.start_timer(a.id, now=WS)
    db.set_archived(a.id, True, now=WS + HOUR)
    assert db.running_session() is None
    assert db.goals() == []
    assert len(db.goals(include_archived=True)) == 1


def test_delete_goal_removes_sessions(db):
    a = add(db)
    db.add_session(a.id, WS, WS + HOUR)
    db.delete_goal(a.id)
    assert db.goal(a.id) is None
    assert db.sessions_between(WS, WE, now=WE) == []


def test_week_start_setting(db):
    assert db.week_start_day == 0
    db.week_start_day = 6
    assert db.current_week_start(date(2026, 11, 27)) == date(2026, 11, 22)
    with pytest.raises(ValueError):
        db.week_start_day = 7


# ---------------------------------------------------------------- count goals


def add_count(db, name="LeetCode", target=6, unit="problems"):
    return db.add_goal(name, "#f2994a", target, kind="count", unit=unit, week_start=WEEK)


def test_count_goal_fields(db):
    g = add_count(db)
    assert g.is_count and g.unit == "problems" and g.target_minutes == 6
    t = add(db, "AI")
    assert not t.is_count and t.unit == ""


def test_tallies_count_towards_their_week(db):
    g = add_count(db)
    db.add_tally(g.id, now=WS + HOUR)
    db.add_tally(g.id, amount=2, now=WS + 2 * HOUR)
    db.add_tally(g.id, now=WE + HOUR)  # next week
    db.add_tally(g.id, now=WS - HOUR)  # previous week
    assert db.week_progress(WEEK, now=WE) == {g.id: 3}


def test_time_and_count_progress_together(db):
    t, c = add(db, "AI"), add_count(db)
    db.add_session(t.id, WS, WS + HOUR)
    db.add_tally(c.id, now=WS + 10)
    assert db.week_progress(WEEK, now=WE) == {t.id: HOUR, c.id: 1}


def test_undo_tally_removes_latest_in_week(db):
    g = add_count(db)
    db.add_tally(g.id, now=WS + 10)
    db.add_tally(g.id, amount=2, now=WS + 20)
    assert db.undo_tally(g.id, WEEK) is True
    assert db.week_progress(WEEK, now=WE) == {g.id: 1}
    assert db.undo_tally(g.id, WEEK) is True
    assert db.undo_tally(g.id, WEEK) is False


def test_first_activity_includes_tallies(db):
    g = add_count(db)
    db.add_tally(g.id, now=WS + 500)
    db.add_tally(g.id, now=WS + 100)
    assert db.first_activity_ts(g.id) == WS + 100


def test_update_goal_changes_unit_only_for_count_goals(db):
    c, t = add_count(db), add(db, "AI")
    db.update_goal(c.id, name="LC", color="#000", target_minutes=8, unit="katas", week_start=WEEK)
    db.update_goal(t.id, name="AI", color="#000", target_minutes=60, unit="katas", week_start=WEEK)
    assert db.goal(c.id).unit == "katas" and db.goal(c.id).target_minutes == 8
    assert db.goal(t.id).unit == ""


def test_unknown_kind_rejected(db):
    with pytest.raises(ValueError):
        db.add_goal("X", "#000", 1, kind="distance", week_start=WEEK)


def test_old_database_is_upgraded(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE goals (id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL,"
        " target_minutes INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0,"
        " sort_order INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);"
        "INSERT INTO goals (name, color, target_minutes, created_at) VALUES ('AI', '#fff', 300, 0);"
    )
    old.commit()
    old.close()
    d = Database(path)
    (g,) = d.goals()
    assert g.name == "AI" and g.kind == "time" and not g.is_count
    d.add_tally(add_count(d).id, now=WS)  # new table exists
    d.close()


def test_format_amount():
    from clockgrid.db import Goal, format_amount

    count = Goal(1, "LC", "#000", 6, False, 0, kind="count", unit="problems")
    timed = Goal(2, "AI", "#000", 60, False, 0)
    assert format_amount(count, 4) == "4 problems"
    assert format_amount(timed, 3 * HOUR + 20 * 60) == "3h 20m"
