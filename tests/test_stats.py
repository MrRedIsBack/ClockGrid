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
    assert [r.target for r in results] == [300 * 60, 300 * 60, 600 * 60, 600 * 60]
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


def test_combine(db):
    a = make_goal(db, 60, "A")
    b = make_goal(db, 120, "B")
    log(db, a, WEEKS[0], 1)
    log(db, b, WEEKS[0], 2, start_hour=14)
    results = stats.weekly_results(db, [a, b], CURRENT, NOW)
    combined = stats.combine(results)
    assert combined[0].worked == 3 * HOUR and combined[0].target == 180 * 60
    assert [r.complete for r in combined] == [True, True, True, False]


def test_leaderboard_ranks_by_average_completion(db):
    cpp = make_goal(db, 60, "learncpp.com")
    other = make_goal(db, 120, "Other")
    for w in WEEKS[:3]:
        log(db, cpp, w, 1)  # 100% every week
        log(db, other, w, 1, start_hour=14)  # 50% every week
    results = stats.weekly_results(db, [cpp, other], CURRENT, NOW)
    board = stats.leaderboard([other, cpp], results)
    assert [e.goal.name for e in board] == ["learncpp.com", "Other"]
    assert board[0].completion == pytest.approx(1.0)
    assert board[1].completion == pytest.approx(0.5)
    assert board[0].weeks == 3 and board[0].hit_rate == 1.0


def test_leaderboard_puts_new_goals_last(db):
    old = make_goal(db, 60, "Old")
    log(db, old, WEEKS[0], 0.5)  # 50%
    new = db.add_goal("New", "#000", 60, week_start=CURRENT, created_at=NOW)
    log(db, new, CURRENT, 1)  # 100% so far, but no finished week yet
    results = stats.weekly_results(db, [old, new], CURRENT, NOW)
    board = stats.leaderboard([old, new], results)
    assert [(e.goal.name, e.weeks) for e in board] == [("Old", 3), ("New", 0)]


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
    text = " ".join(stats.insights(summaries, stats.weekly_completion(results), p, 0))
    assert "<b>Reading</b> most often" in text
    assert "<b>Gym</b> is the hardest" in text
    assert "busiest day" in text


def test_insights_empty_without_data(db):
    p = stats.patterns(db, 0, NOW, NOW)
    assert stats.insights({}, [], p, 0) == []


# ---------------------------------------------------------------- count goals


def make_count_goal(db, target=6, name="LeetCode"):
    return db.add_goal(name, "#f2994a", target, kind="count", unit="problems", week_start=W0, created_at=ts(W0, 9))


def tally(db, goal, day, n, hour=12):
    for i in range(n):
        db.add_tally(goal.id, now=ts(day, hour) + i)


def test_count_goal_weekly_results(db):
    g = make_count_goal(db, target=6)
    tally(db, g, WEEKS[0], 6)  # hit
    tally(db, g, WEEKS[1], 3)  # 50%
    tally(db, g, CURRENT, 2)
    results = stats.weekly_results(db, [g], CURRENT, NOW)[g.id]
    assert [(r.worked, r.target) for r in results] == [(6, 6), (3, 6), (0, 6), (2, 6)]
    assert [r.hit for r in results[:3]] == [True, False, False]
    s = stats.summarize(results)
    assert s.avg_completion == pytest.approx((1.0 + 0.5 + 0.0) / 3)


def test_leaderboard_mixes_time_and_count_goals(db):
    timed = make_goal(db, 60, "Reading")
    counted = make_count_goal(db, 6)
    for w in WEEKS[:3]:
        log(db, timed, w, 0.5)  # 50%
        tally(db, counted, w, 6)  # 100%
    results = stats.weekly_results(db, [timed, counted], CURRENT, NOW)
    board = stats.leaderboard([timed, counted], results)
    assert [e.goal.name for e in board] == ["LeetCode", "Reading"]
    assert [round(e.completion, 2) for e in board] == [1.0, 0.5]


def test_weekly_completion_averages_across_units(db):
    timed = make_goal(db, 60, "Reading")
    counted = make_count_goal(db, 4)
    log(db, timed, WEEKS[0], 1)  # 100%
    tally(db, counted, WEEKS[0], 1)  # 25%
    results = stats.weekly_results(db, [timed, counted], CURRENT, NOW)
    trend = stats.weekly_completion(results)
    assert trend[0].completion == pytest.approx(0.625)
    assert trend[0].complete and not trend[-1].complete


def test_patterns_ignore_tallies(db):
    g = make_count_goal(db)
    tally(db, g, WEEKS[0], 5)
    ws, we = week_bounds(WEEKS[0])
    assert stats.patterns(db, ws, we, NOW).total == 0
