from datetime import date

from clockgrid.weeks import (
    format_clock,
    format_duration,
    format_week_range,
    overlap_seconds,
    week_bounds,
    week_start_for,
)


def test_week_start_monday():
    # 2026-11-27 is a Friday
    assert week_start_for(date(2026, 11, 27), 0) == date(2026, 11, 23)
    assert week_start_for(date(2026, 11, 23), 0) == date(2026, 11, 23)


def test_week_start_sunday():
    assert week_start_for(date(2026, 11, 27), 6) == date(2026, 11, 22)
    assert week_start_for(date(2026, 11, 22), 6) == date(2026, 11, 22)


def test_week_bounds_span_seven_days():
    start, end = week_bounds(date(2026, 11, 23))
    # 7 days, allowing an hour either way for a DST change
    assert abs((end - start) - 7 * 86400) <= 3600


def test_overlap():
    assert overlap_seconds(0, 100, 50, 200) == 50
    assert overlap_seconds(0, 100, 100, 200) == 0
    assert overlap_seconds(60, 80, 0, 200) == 20


def test_format_duration():
    assert format_duration(0) == "0m"
    assert format_duration(45 * 60) == "45m"
    assert format_duration(5 * 3600) == "5h"
    assert format_duration(3 * 3600 + 20 * 60 + 59) == "3h 20m"


def test_format_clock():
    assert format_clock(3 * 3600 + 5 * 60 + 9) == "3:05:09"


def test_format_week_range():
    assert format_week_range(date(2026, 11, 23)) == "Nov 23 – 29, 2026"
    assert format_week_range(date(2026, 11, 30)) == "Nov 30 – Dec 6, 2026"
    assert format_week_range(date(2026, 12, 28)) == "Dec 28, 2026 – Jan 3, 2027"
