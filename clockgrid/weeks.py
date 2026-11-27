"""Week boundaries and duration formatting.

All timestamps are Unix epoch seconds. Weeks are computed in local time,
so a week always runs from midnight on the start day to midnight seven days
later, even across daylight-saving changes.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def week_start_for(day: date, start_weekday: int = 0) -> date:
    """Return the first day of the week containing `day`.

    `start_weekday` uses Python's convention: Monday is 0, Sunday is 6.
    """
    return day - timedelta(days=(day.weekday() - start_weekday) % 7)


def week_bounds(week_start: date) -> tuple[int, int]:
    """Return (start, end) epoch seconds for the week, end exclusive."""
    start = datetime.combine(week_start, time.min)
    end = datetime.combine(week_start + timedelta(days=7), time.min)
    return int(start.timestamp()), int(end.timestamp())


def overlap_seconds(start: int, end: int, range_start: int, range_end: int) -> int:
    """Seconds of [start, end) that fall inside [range_start, range_end)."""
    return max(0, min(end, range_end) - max(start, range_start))


def format_duration(seconds: int) -> str:
    """Format as '3h 20m', '45m' or '0m'."""
    minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def format_clock(seconds: int) -> str:
    """Format as 'H:MM:SS' for a live running timer."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_week_range(week_start: date) -> str:
    end = week_start + timedelta(days=6)
    if week_start.month == end.month:
        return f"{week_start:%b} {week_start.day} – {end.day}, {end.year}"
    if week_start.year == end.year:
        return f"{week_start:%b} {week_start.day} – {end:%b} {end.day}, {end.year}"
    return f"{week_start:%b} {week_start.day}, {week_start.year} – {end:%b} {end.day}, {end.year}"
