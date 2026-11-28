"""History and statistics derived from sessions and weekly target snapshots.

Only finished weeks count towards hit rates and averages; the current week
is reported separately as "in progress" so a half-done week never reads as
a miss.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from clockgrid.db import Database, Goal, target_in_base_units
from clockgrid.weeks import WEEKDAY_NAMES, format_duration, week_start_for

EVEN_LAST_TWO_DAYS = 2 / 7  # share of time the last two days would get if spread evenly


@dataclass(frozen=True)
class WeekResult:
    """One goal's week. `worked` and `target` are in the goal's base unit:
    seconds for a time goal, items for a count goal."""

    week_start: date
    worked: int
    target: int
    complete: bool  # False for the week still in progress

    @property
    def completion(self) -> float:
        return self.worked / self.target if self.target else 0.0

    @property
    def hit(self) -> bool:
        return self.target > 0 and self.worked >= self.target


@dataclass(frozen=True)
class Summary:
    weeks_completed: int
    weeks_hit: int
    avg_completion: float | None
    current_streak: int
    best_streak: int
    total_worked: int

    @property
    def hit_rate(self) -> float | None:
        return self.weeks_hit / self.weeks_completed if self.weeks_completed else None


# ------------------------------------------------------------ week results


def tracked_weeks(db: Database, goal: Goal, current_week: date) -> list[date]:
    """Weeks a goal was being tracked, oldest first.

    Starts at the earliest of: its first target snapshot, its creation, or
    its first session. Ends at the current week, or for an archived goal at
    the last week it had a target.
    """
    start_day = db.week_start_day
    snapshots = db.snapshot_range(goal.id)
    candidates = [date.fromtimestamp(goal.created_at)] if goal.created_at else []
    if snapshots:
        candidates.append(snapshots[0])
    first_ts = db.first_activity_ts(goal.id)
    if first_ts is not None:
        candidates.append(date.fromtimestamp(first_ts))
    if not candidates:
        return []
    first = week_start_for(min(candidates), start_day)

    last = current_week
    if goal.archived and snapshots:
        last = min(current_week, week_start_for(snapshots[1], start_day))

    weeks = []
    week = first
    while week <= last:
        weeks.append(week)
        week += timedelta(days=7)
    return weeks


def weekly_results(
    db: Database, goals: list[Goal], current_week: date, now: int
) -> dict[int, list[WeekResult]]:
    """Per-goal results for every week the goal was tracked, oldest first."""
    progress_cache: dict[date, dict[int, int]] = {}
    out: dict[int, list[WeekResult]] = {}
    for goal in goals:
        results = []
        for week in tracked_weeks(db, goal, current_week):
            if week not in progress_cache:
                progress_cache[week] = db.week_progress(week, now)
            results.append(
                WeekResult(
                    week_start=week,
                    worked=progress_cache[week].get(goal.id, 0),
                    target=target_in_base_units(goal, db.target_minutes_for_week(goal.id, week)),
                    complete=week < current_week,
                )
            )
        out[goal.id] = results
    return out


def since(results: list[WeekResult], first_week: date | None) -> list[WeekResult]:
    if first_week is None:
        return list(results)
    return [r for r in results if r.week_start >= first_week]


def _by_week(results_by_goal: dict[int, list[WeekResult]]) -> list[tuple[date, list[WeekResult]]]:
    by_week: dict[date, list[WeekResult]] = {}
    for results in results_by_goal.values():
        for r in results:
            by_week.setdefault(r.week_start, []).append(r)
    return sorted(by_week.items())


def combine(results_by_goal: dict[int, list[WeekResult]]) -> list[WeekResult]:
    """Sum goals into one result per week (worked vs total target).

    Only meaningful for goals that share a unit, so pass time goals only.
    """
    return [
        WeekResult(
            week_start=week,
            worked=sum(r.worked for r in rs),
            target=sum(r.target for r in rs),
            complete=all(r.complete for r in rs),
        )
        for week, rs in _by_week(results_by_goal)
    ]


@dataclass(frozen=True)
class WeekCompletion:
    week_start: date
    completion: float  # average across goals, so time and count goals mix fairly
    complete: bool


def weekly_completion(results_by_goal: dict[int, list[WeekResult]]) -> list[WeekCompletion]:
    """Average completion across all goals for each week, oldest first."""
    return [
        WeekCompletion(week, sum(r.completion for r in rs) / len(rs), all(r.complete for r in rs))
        for week, rs in _by_week(results_by_goal)
    ]


# ---------------------------------------------------------------- summary


def streaks(hits: list[bool], in_progress_hit: bool = False) -> tuple[int, int]:
    """(current, best) run of consecutive hits over finished weeks.

    A week still in progress that is already hit extends the current streak;
    one that isn't hit yet doesn't break it.
    """
    best = run = 0
    for hit in hits:
        run = run + 1 if hit else 0
        best = max(best, run)
    if in_progress_hit:
        run += 1
        best = max(best, run)
    return run, best


def summarize(results: list[WeekResult]) -> Summary:
    done = [r for r in results if r.complete]
    live = [r for r in results if not r.complete]
    current, best = streaks([r.hit for r in done], bool(live) and live[-1].hit)
    return Summary(
        weeks_completed=len(done),
        weeks_hit=sum(r.hit for r in done),
        avg_completion=sum(r.completion for r in done) / len(done) if done else None,
        current_streak=current,
        best_streak=best,
        total_worked=sum(r.worked for r in results),
    )


# ------------------------------------------------------------ leaderboard


@dataclass(frozen=True)
class LeaderEntry:
    goal: Goal
    completion: float  # average share of the weekly target reached
    weeks: int  # finished weeks averaged; 0 means only this week so far
    hit_rate: float | None


def leaderboard(goals: list[Goal], results_by_goal: dict[int, list[WeekResult]]) -> list[LeaderEntry]:
    """Goals ranked by average completion of finished weeks, highest first.

    Goals with no finished week yet are ranked after the rest, by how far
    they are through the current week.
    """
    entries = []
    for g in goals:
        results = results_by_goal.get(g.id, [])
        done = [r for r in results if r.complete]
        live = [r for r in results if not r.complete]
        if done:
            s = summarize(results)
            entries.append(LeaderEntry(g, s.avg_completion, len(done), s.hit_rate))
        elif live:
            entries.append(LeaderEntry(g, live[-1].completion, 0, None))
    entries.sort(key=lambda e: (e.weeks == 0, -e.completion))
    return entries


# --------------------------------------------------------------- patterns


@dataclass(frozen=True)
class Patterns:
    grid: list[list[int]]  # seconds by [weekday, Monday = 0][hour]
    session_count: int
    longest_session: int
    total_session_time: int

    @property
    def total(self) -> int:
        return sum(sum(row) for row in self.grid)

    @property
    def avg_session(self) -> int:
        return self.total_session_time // self.session_count if self.session_count else 0

    def weekday_totals(self) -> list[int]:
        return [sum(row) for row in self.grid]

    def hour_totals(self) -> list[int]:
        return [sum(self.grid[d][h] for d in range(7)) for h in range(24)]


def patterns(
    db: Database, start_ts: int, end_ts: int, now: int, goal_ids: set[int] | None = None
) -> Patterns:
    """When time was spent between start_ts and end_ts, split into hourly buckets."""
    grid = [[0] * 24 for _ in range(7)]
    count = longest = total = 0
    end_ts = min(end_ts, now)
    for s in db.sessions_between(start_ts, end_ts, now):
        if goal_ids is not None and s.goal_id not in goal_ids:
            continue
        duration = s.duration(now)
        count += 1
        total += duration
        longest = max(longest, duration)

        cur = max(s.start_ts, start_ts)
        stop = min(s.end_ts if s.end_ts is not None else now, end_ts)
        while cur < stop:
            dt = datetime.fromtimestamp(cur)
            next_hour = int((dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp())
            chunk = min(stop, next_hour) - cur
            if chunk <= 0:  # guard against odd DST transitions
                chunk = stop - cur
            grid[dt.weekday()][dt.hour] += chunk
            cur += chunk
    return Patterns(grid=grid, session_count=count, longest_session=longest, total_session_time=total)


def last_two_days_share(p: Patterns, week_start_day: int) -> float | None:
    total = p.total
    if not total:
        return None
    last_two = [(week_start_day + 5) % 7, (week_start_day + 6) % 7]
    return sum(p.weekday_totals()[d] for d in last_two) / total


def best_window(hour_totals: list[int], width: int = 3) -> tuple[int, int]:
    """(start hour, seconds) of the busiest `width`-hour window, wrapping midnight."""
    best_start, best_sum = 0, -1
    for start in range(24):
        total = sum(hour_totals[(start + i) % 24] for i in range(width))
        if total > best_sum:
            best_start, best_sum = start, total
    return best_start, best_sum


# --------------------------------------------------------------- insights


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _b(text: str) -> str:
    return f"<b>{html.escape(text)}</b>"


def insights(
    summaries: dict[int, tuple[Goal, Summary]],
    trend: list[WeekCompletion],
    pat: Patterns,
    week_start_day: int,
) -> list[str]:
    """Plain-language observations, as short HTML snippets.

    `trend` is from weekly_completion(); `pat` covers time goals only.
    """
    out: list[str] = []

    rated = [(g, s) for g, s in summaries.values() if s.hit_rate is not None]
    if len(rated) == 1:
        g, s = rated[0]
        out.append(
            f"You hit {_b(g.name)} in {s.weeks_hit} of {s.weeks_completed} finished weeks "
            f"({_pct(s.hit_rate)}), reaching {_pct(s.avg_completion)} of the target on average."
        )
    elif len(rated) > 1:
        rated.sort(key=lambda gs: (gs[1].hit_rate, gs[1].avg_completion), reverse=True)
        g, s = rated[0]
        out.append(
            f"You hit {_b(g.name)} most often: {s.weeks_hit} of {s.weeks_completed} weeks ({_pct(s.hit_rate)})."
        )
        g, s = rated[-1]
        if s.hit_rate < rated[0][1].hit_rate:
            out.append(
                f"{_b(g.name)} is the hardest to hit: {s.weeks_hit} of {s.weeks_completed} weeks "
                f"({_pct(s.hit_rate)}), averaging {_pct(s.avg_completion)} of the target."
            )

    done = [r for r in trend if r.complete]
    if len(done) >= 4:
        n = min(4, len(done) // 2)
        recent = sum(r.completion for r in done[-n:]) / n
        before = sum(r.completion for r in done[-2 * n : -n]) / n
        diff = round((recent - before) * 100)
        if abs(diff) >= 5:
            direction = "up" if diff > 0 else "down"
            out.append(
                f"Your last {n} weeks averaged {_pct(recent)} of target, "
                f"{direction} from {_pct(before)} the {n} weeks before."
            )
        else:
            out.append(f"You've been steady: about {_pct(recent)} of target over the last {2 * n} weeks.")

    if pat.total:
        days = pat.weekday_totals()
        busiest = max(range(7), key=lambda d: days[d])
        out.append(
            f"{_b(WEEKDAY_NAMES[busiest])} is your busiest day, with {_pct(days[busiest] / pat.total)} of your time."
        )
        start, secs = best_window(pat.hour_totals())
        out.append(
            f"Your peak hours are {_b(f'{start:02d}:00–{(start + 3) % 24:02d}:00')} "
            f"({_pct(secs / pat.total)} of your time)."
        )
        share = last_two_days_share(pat, week_start_day)
        if share is not None:
            if share >= 0.4:
                out.append(
                    f"You do {_pct(share)} of your work in the last two days of the week, "
                    "which suggests end-of-week catch-up."
                )
            elif share <= 0.15:
                out.append(
                    f"Only {_pct(share)} of your work happens in the last two days of the week; "
                    "you front-load your weeks."
                )
            else:
                out.append("Your time is spread fairly evenly through the week.")
        if pat.session_count:
            out.append(
                f"Your average session is {_b(format_duration(pat.avg_session))}; "
                f"the longest was {format_duration(pat.longest_session)}."
            )
    return out
