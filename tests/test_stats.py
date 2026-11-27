from datetime import date, datetime, timedelta

import pytest

from clockgrid import stats
from clockgrid.db import Database
from clockgrid.weeks import week_bounds

HOUR = 3600
W0 = date(2026, 11, 2)  # a Monday; the goal is created this week
WEEKS = [W0 + timedelta(days=7 * i) for i in range(4)]  # W0..W3, W3 is "now"
CURRENT = WEEKS[-1]
NOW = week_bounds(CURRENT)[0] + 2 * 86400  # Wednesday of the current week


def ts(day: date, hour: int) -> int:
    return int(datetime(day.year, day.month, day.day, hour).timestamp())


@pytest.fixture
def db():
    d = Database()
    yield d
    d.close()


def make_goal(db, minutes=5 * 60, name="AI"):
    return db.add_goal(name, "#4f8cff", minutes, week_start=W0, created_at=ts(W0, 9))


def log(db, goal, day, hours, start_hour=10):
    db.add_session(goal.id, ts(day, start_hour), ts(day, start_hour) + int(hours * HOUR))


def test_weekly_results_cover_every_tracked_week(db):
    g = make_goal(db)
    log(db, g, WEEKS[0], 5)  # hit
    log(db, g, WEEKS[1], 2)  # miss
    # WEEKS[2]: nothing logged -> a miss, not skipped
    log(db, g, CURRENT, 1)  # in progress
    results = stats.weekly_results(db, [g], CURRENT, NOW)[g.id]
    assert [r.week_start for r in results] == WEEKS
    assert [r.hit for r in results] == [True, False, False, False]
    assert [r.complete for r in results] == [True, True, True, False]
    assert results[1].completion == pytest.approx(0.4)


def test_summary_ignores_the_week_in_progress(db):
    g = make_goal(db)
    log(db, g, WEEKS[0], 5)
    log(db, g, WEEKS[1], 6)
    log(db, g, WEEKS[2], 1)
    log(db, g, CURRENT, 0.5)
    s = stats.summarize(stats.weekly_results(db, [g], CURRENT, NOW)[g.id])
    assert (s.weeks_completed, s.weeks_hit) == (3, 2)
    assert s.hit_rate == pytest.approx(2 / 3)
    assert s.avg_completion == pytest.approx((1.0 + 1.2 + 0.2) / 3)
    assert (s.current_streak, s.best_streak) == (0, 2)
    assert s.total_worked == int(12.5 * HOUR)


def test_streaks():
    assert stats.streaks([True, True, False, True]) == (1, 2)
    assert stats.streaks([True, True, True]) == (3, 3)
    # an already-hit current week extends the streak; an unfinished one doesn't break it
    assert stats.streaks([True, True], in_progress_hit=True) == (3, 3)
    assert stats.streaks([True, True], in_progress_hit=False) == (2, 2)
    assert stats.streaks([]) == (0, 0)


def test_past_targets_are_used(db):
    g = make_goal(db, minutes=5 * 60)
    db.snapshot_week(WEEKS[1])
    db.update_goal(g.id, name="AI", color="#000", target_minutes=10 * 60, week_start=WEEKS[2])
    log(db, g, WEEKS[0], 5)
    log(db, g, WEEKS[2], 5)
    results = stats.weekly_results(db, [g], CURRENT, NOW)[g.id]
    assert [r.target_minutes for r in results] == [300, 300, 600, 600]
    assert [r.hit for r in results[:3]] == [True, False, False]


def test_backdated_session_extends_history(db):
    g = make_goal(db)
    earlier = W0 - timedelta(days=14)
    log(db, g, earlier, 1)
    weeks = stats.tracked_weeks(db, g, CURRENT)
    assert weeks[0] == earlier


def test_archived_goal_stops_at_its_last_week(db):
    g = make_goal(db)
    db.snapshot_week(WEEKS[1])
    db.set_archived(g.id, True)
    g = db.goal(g.id)
    assert stats.tracked_weeks(db, g, CURRENT) == WEEKS[:2]


def test_combine_and_perfect_weeks(db):
    a = make_goal(db, 60, "A")
    b = make_goal(db, 120, "B")
    log(db, a, WEEKS[0], 1)
    log(db, b, WEEKS[0], 2, start_hour=14)  # both hit
    log(db, a, WEEKS[1], 1)  # only A hit
    results = stats.weekly_results(db, [a, b], CURRENT, NOW)
    combined = stats.combine(results)
    assert combined[0].worked == 3 * HOUR and combined[0].target_minutes == 180
    perfect = stats.perfect_weeks(results)
    assert [p[1] for p in perfect[:2]] == [True, False]


def test_patterns_split_sessions_by_hour(db):
    g = make_goal(db)
    monday = WEEKS[0]
    db.add_session(g.id, ts(monday, 20) + 30 * 60, ts(monday, 22))  # 20:30-22:00
    ws, we = week_bounds(monday)
    p = stats.patterns(db, ws, we, NOW)
    assert p.grid[0][20] == 30 * 60
    assert p.grid[0][21] == HOUR
    assert p.total == 90 * 60
    assert p.session_count == 1
    assert p.longest_session == 90 * 60


def test_patterns_goal_filter(db):
    a, b = make_goal(db, name="A"), make_goal(db, name="B")
    log(db, a, WEEKS[0], 1)
    log(db, b, WEEKS[0], 2, start_hour=14)
    ws, we = week_bounds(WEEKS[0])
    assert stats.patterns(db, ws, we, NOW, {b.id}).total == 2 * HOUR


def test_last_two_days_share(db):
    g = make_goal(db)
    log(db, g, WEEKS[0], 1)  # Monday
    log(db, g, WEEKS[0] + timedelta(days=6), 3)  # Sunday
    ws, we = week_bounds(WEEKS[0])
    p = stats.patterns(db, ws, we, NOW)
    assert stats.last_two_days_share(p, week_start_day=0) == pytest.approx(0.75)
    # with weeks starting on Sunday, the last two days are Friday and Saturday
    assert stats.last_two_days_share(p, week_start_day=6) == pytest.approx(0.0)


def test_best_window_wraps_midnight():
    hours = [0] * 24
    hours[23] = hours[0] = hours[1] = 10
    assert stats.best_window(hours) == (23, 30)


def test_insights_mention_best_and_worst_goal(db):
    a = make_goal(db, 60, "Reading")
    b = make_goal(db, 600, "Gym")
    for w in WEEKS[:3]:
        log(db, a, w, 1)
        log(db, b, w, 2, start_hour=18)
    results = stats.weekly_results(db, [a, b], CURRENT, NOW)
    summaries = {g.id: (g, stats.summarize(results[g.id])) for g in (a, b)}
    ws = week_bounds(W0)[0]
    p = stats.patterns(db, ws, NOW, NOW)
    text = " ".join(stats.insights(summaries, stats.combine(results), p, 0))
    assert "<b>Reading</b> most often" in text
    assert "<b>Gym</b> is the hardest" in text
    assert "busiest day" in text


def test_insights_empty_without_data(db):
    p = stats.patterns(db, 0, NOW, NOW)
    assert stats.insights({}, [], p, 0) == []
