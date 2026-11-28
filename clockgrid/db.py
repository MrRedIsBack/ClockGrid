"""SQLite storage for goals, sessions, tallies and weekly target snapshots.

There are two kinds of goal:

- time goals ("5 hours of AI a week"), tracked with timed sessions;
- count goals ("6 LeetCode problems a week"), tracked with tallies.

For both, the `target_minutes` column holds the weekly target in the goal's
own unit: minutes for a time goal, items for a count goal. Weekly progress
is reported in base units: seconds for time goals, items for count goals.

Sessions and tallies are the raw record; everything else is derived from
them. Each week also stores a snapshot of every goal's target, so that
changing a target later does not rewrite how past weeks are judged.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from clockgrid.weeks import format_duration, overlap_seconds, week_bounds, week_start_for

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL,
    color          TEXT    NOT NULL,
    target_minutes INTEGER NOT NULL CHECK (target_minutes > 0),  -- minutes, or items for count goals
    archived       INTEGER NOT NULL DEFAULT 0,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    kind           TEXT    NOT NULL DEFAULT 'time' CHECK (kind IN ('time', 'count')),
    unit           TEXT    NOT NULL DEFAULT ''   -- e.g. "problems", for count goals
);

CREATE TABLE IF NOT EXISTS tallies (
    id      INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    ts      INTEGER NOT NULL,
    amount  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tallies_ts ON tallies(ts);

CREATE TABLE IF NOT EXISTS sessions (
    id       INTEGER PRIMARY KEY,
    goal_id  INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    start_ts INTEGER NOT NULL,
    end_ts   INTEGER,             -- NULL while the timer is running
    CHECK (end_ts IS NULL OR end_ts >= start_ts)
);
CREATE INDEX IF NOT EXISTS idx_sessions_start ON sessions(start_ts);

CREATE TABLE IF NOT EXISTS weekly_targets (
    goal_id        INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    week_start     TEXT    NOT NULL,  -- ISO date of the week's first day
    target_minutes INTEGER NOT NULL,
    PRIMARY KEY (goal_id, week_start)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


MIN_SESSION_SECONDS = 60
TIME = "time"
COUNT = "count"


def default_db_path() -> Path:
    override = os.environ.get("CLOCKGRID_DB")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "ClockGrid" / "clockgrid.db"


def _now() -> int:
    return int(time.time())


@dataclass(frozen=True)
class Goal:
    id: int
    name: str
    color: str
    target_minutes: int
    archived: bool
    sort_order: int
    created_at: int = 0
    kind: str = TIME
    unit: str = ""

    @property
    def is_count(self) -> bool:
        return self.kind == COUNT


def target_in_base_units(goal: Goal, target: int) -> int:
    """A stored target (minutes, or items) in progress units (seconds, or items)."""
    return target if goal.is_count else target * 60


def format_amount(goal: Goal, value: int) -> str:
    """'3h 20m' for a time goal, '4 problems' for a count goal."""
    if goal.is_count:
        return f"{value} {goal.unit}".strip()
    return format_duration(value)


@dataclass(frozen=True)
class Session:
    id: int
    goal_id: int
    start_ts: int
    end_ts: int | None

    @property
    def running(self) -> bool:
        return self.end_ts is None

    def duration(self, now: int | None = None) -> int:
        end = self.end_ts if self.end_ts is not None else (now if now is not None else _now())
        return max(0, end - self.start_ts)


def _goal(row: sqlite3.Row) -> Goal:
    return Goal(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        target_minutes=row["target_minutes"],
        archived=bool(row["archived"]),
        sort_order=row["sort_order"],
        created_at=row["created_at"],
        kind=row["kind"],
        unit=row["unit"],
    )


def _session(row: sqlite3.Row) -> Session:
    return Session(id=row["id"], goal_id=row["goal_id"], start_ts=row["start_ts"], end_ts=row["end_ts"])


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        self.conn.executescript(SCHEMA)

    def _migrate(self) -> None:
        """Bring databases created by older versions up to date."""
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(goals)")}
        if columns and "kind" not in columns:  # added with count goals
            with self.conn:
                self.conn.execute("ALTER TABLE goals ADD COLUMN kind TEXT NOT NULL DEFAULT 'time'")
                self.conn.execute("ALTER TABLE goals ADD COLUMN unit TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        self.conn.close()

    # ----------------------------------------------------------- settings

    def get_setting(self, key: str, default: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    @property
    def week_start_day(self) -> int:
        """First day of the week: 0 = Monday ... 6 = Sunday."""
        return int(self.get_setting("week_start_day", "0"))

    @week_start_day.setter
    def week_start_day(self, value: int) -> None:
        if not 0 <= value <= 6:
            raise ValueError("week_start_day must be between 0 and 6")
        self.set_setting("week_start_day", str(value))

    def current_week_start(self, today: date | None = None) -> date:
        return week_start_for(today or date.today(), self.week_start_day)

    # -------------------------------------------------------------- goals

    def goals(self, include_archived: bool = False) -> list[Goal]:
        sql = "SELECT * FROM goals"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY sort_order, id"
        return [_goal(r) for r in self.conn.execute(sql)]

    def goal(self, goal_id: int) -> Goal | None:
        row = self.conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return _goal(row) if row else None

    def add_goal(
        self,
        name: str,
        color: str,
        target_minutes: int,
        *,
        kind: str = TIME,
        unit: str = "",
        week_start: date | None = None,
        created_at: int | None = None,
    ) -> Goal:
        """Add a goal. `target_minutes` is in minutes, or in items for a count goal."""
        name = name.strip()
        if not name:
            raise ValueError("Goal name cannot be empty")
        if target_minutes <= 0:
            raise ValueError("Target must be greater than zero")
        if kind not in (TIME, COUNT):
            raise ValueError(f"Unknown goal kind: {kind}")
        week_start = week_start or self.current_week_start()
        with self.conn:
            (next_order,) = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM goals"
            ).fetchone()
            cur = self.conn.execute(
                "INSERT INTO goals (name, color, target_minutes, sort_order, created_at, kind, unit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    color,
                    target_minutes,
                    next_order,
                    created_at if created_at is not None else _now(),
                    kind,
                    unit.strip() if kind == COUNT else "",
                ),
            )
            goal_id = cur.lastrowid
            self._set_week_target(goal_id, week_start, target_minutes)
        return self.goal(goal_id)  # type: ignore[return-value]

    def update_goal(
        self,
        goal_id: int,
        *,
        name: str,
        color: str,
        target_minutes: int,
        unit: str | None = None,
        week_start: date | None = None,
    ) -> None:
        """Update a goal. A new target applies from the current week onwards.
        A goal's kind (time or count) can't be changed once created."""
        name = name.strip()
        if not name:
            raise ValueError("Goal name cannot be empty")
        if target_minutes <= 0:
            raise ValueError("Target must be greater than zero")
        week_start = week_start or self.current_week_start()
        with self.conn:
            self.conn.execute(
                "UPDATE goals SET name = ?, color = ?, target_minutes = ? WHERE id = ?",
                (name, color, target_minutes, goal_id),
            )
            if unit is not None:
                self.conn.execute(
                    "UPDATE goals SET unit = ? WHERE id = ? AND kind = ?", (unit.strip(), goal_id, COUNT)
                )
            self._set_week_target(goal_id, week_start, target_minutes)

    def set_archived(self, goal_id: int, archived: bool, now: int | None = None) -> None:
        with self.conn:
            if archived:
                running = self.running_session()
                if running and running.goal_id == goal_id:
                    self._stop(running, now)
            self.conn.execute(
                "UPDATE goals SET archived = ? WHERE id = ?", (int(archived), goal_id)
            )
            if not archived:
                goal = self.goal(goal_id)
                if goal:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO weekly_targets VALUES (?, ?, ?)",
                        (goal_id, self.current_week_start().isoformat(), goal.target_minutes),
                    )

    def reorder_goals(self, goal_ids: list[int]) -> None:
        """Save a new display order: goal_ids[0] comes first."""
        with self.conn:
            self.conn.executemany(
                "UPDATE goals SET sort_order = ? WHERE id = ?",
                [(order, gid) for order, gid in enumerate(goal_ids)],
            )

    def delete_goal(self, goal_id: int) -> None:
        """Permanently delete a goal and all of its sessions."""
        with self.conn:
            self.conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))

    def session_count(self, goal_id: int) -> int:
        (count,) = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE goal_id = ?", (goal_id,)
        ).fetchone()
        return count

    # ----------------------------------------------------- weekly targets

    def _set_week_target(self, goal_id: int, week_start: date, target_minutes: int) -> None:
        self.conn.execute(
            "INSERT INTO weekly_targets (goal_id, week_start, target_minutes) VALUES (?, ?, ?) "
            "ON CONFLICT(goal_id, week_start) DO UPDATE SET target_minutes = excluded.target_minutes",
            (goal_id, week_start.isoformat(), target_minutes),
        )

    def snapshot_week(self, week_start: date) -> None:
        """Record current targets for this week for any active goal missing one."""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO weekly_targets (goal_id, week_start, target_minutes) "
                "SELECT id, ?, target_minutes FROM goals WHERE archived = 0",
                (week_start.isoformat(),),
            )

    def target_minutes_for_week(self, goal_id: int, week_start: date) -> int:
        """The goal's target as it was during the given week.

        Uses that week's snapshot, or the most recent earlier one if the app
        was not opened that week, falling back to the current target.
        """
        row = self.conn.execute(
            "SELECT target_minutes FROM weekly_targets "
            "WHERE goal_id = ? AND week_start <= ? ORDER BY week_start DESC LIMIT 1",
            (goal_id, week_start.isoformat()),
        ).fetchone()
        if row:
            return row["target_minutes"]
        goal = self.goal(goal_id)
        return goal.target_minutes if goal else 0

    def snapshot_range(self, goal_id: int) -> tuple[date, date] | None:
        """First and last week that have a stored target for the goal."""
        row = self.conn.execute(
            "SELECT MIN(week_start) AS first, MAX(week_start) AS last "
            "FROM weekly_targets WHERE goal_id = ?",
            (goal_id,),
        ).fetchone()
        if row["first"] is None:
            return None
        return date.fromisoformat(row["first"]), date.fromisoformat(row["last"])

    # ----------------------------------------------------------- sessions

    def first_activity_ts(self, goal_id: int) -> int | None:
        """Timestamp of the goal's earliest session or tally."""
        (ts,) = self.conn.execute(
            "SELECT MIN(ts) FROM ("
            "  SELECT MIN(start_ts) AS ts FROM sessions WHERE goal_id = ?"
            "  UNION ALL SELECT MIN(ts) FROM tallies WHERE goal_id = ?"
            ")",
            (goal_id, goal_id),
        ).fetchone()
        return ts

    def running_session(self) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1"
        ).fetchone()
        return _session(row) if row else None

    def _stop(self, session: Session, now: int | None) -> None:
        """End a running session. Ones under a minute are treated as
        accidental clicks and discarded."""
        end = max(now if now is not None else _now(), session.start_ts)
        if end - session.start_ts < MIN_SESSION_SECONDS:
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
        else:
            self.conn.execute("UPDATE sessions SET end_ts = ? WHERE id = ?", (end, session.id))

    def start_timer(self, goal_id: int, now: int | None = None) -> Session:
        """Start timing a goal. Any other running timer is stopped first."""
        now = now if now is not None else _now()
        with self.conn:
            running = self.running_session()
            if running and running.goal_id == goal_id:
                return running
            if running:
                self._stop(running, now)
            cur = self.conn.execute(
                "INSERT INTO sessions (goal_id, start_ts) VALUES (?, ?)", (goal_id, now)
            )
        return Session(id=cur.lastrowid, goal_id=goal_id, start_ts=now, end_ts=None)

    def stop_timer(self, now: int | None = None) -> Session | None:
        """Stop the running timer. Returns the finished session, or None if
        nothing was running or the session was too short to keep."""
        with self.conn:
            running = self.running_session()
            if running is None:
                return None
            self._stop(running, now)
        return self.session(running.id)

    def session(self, session_id: int) -> Session | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return _session(row) if row else None

    def add_session(self, goal_id: int, start_ts: int, end_ts: int) -> Session:
        if end_ts <= start_ts:
            raise ValueError("End time must be after start time")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions (goal_id, start_ts, end_ts) VALUES (?, ?, ?)",
                (goal_id, start_ts, end_ts),
            )
        return Session(id=cur.lastrowid, goal_id=goal_id, start_ts=start_ts, end_ts=end_ts)

    def update_session(
        self, session_id: int, *, goal_id: int, start_ts: int, end_ts: int | None
    ) -> None:
        """Edit a session. Pass end_ts=None only for a session that is still running."""
        if end_ts is not None and end_ts <= start_ts:
            raise ValueError("End time must be after start time")
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET goal_id = ?, start_ts = ?, end_ts = ? WHERE id = ?",
                (goal_id, start_ts, end_ts, session_id),
            )

    def delete_session(self, session_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def sessions_between(self, start_ts: int, end_ts: int, now: int | None = None) -> list[Session]:
        """Sessions overlapping [start_ts, end_ts), newest first."""
        now = now if now is not None else _now()
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE start_ts < ? AND COALESCE(end_ts, ?) > ? "
            "ORDER BY start_ts DESC",
            (end_ts, now, start_ts),
        )
        return [_session(r) for r in rows]

    def week_progress(self, week_start: date, now: int | None = None) -> dict[int, int]:
        """Progress per goal id during the week: seconds for time goals,
        items for count goals.

        Sessions that cross the week boundary only count the part inside the
        week, and a running session counts up to `now`.
        """
        now = now if now is not None else _now()
        ws, we = week_bounds(week_start)
        totals: dict[int, int] = {}
        for s in self.sessions_between(ws, we, now):
            end = s.end_ts if s.end_ts is not None else now
            totals[s.goal_id] = totals.get(s.goal_id, 0) + overlap_seconds(s.start_ts, end, ws, we)
        for row in self.conn.execute(
            "SELECT goal_id, SUM(amount) AS total FROM tallies WHERE ts >= ? AND ts < ? GROUP BY goal_id",
            (ws, we),
        ):
            totals[row["goal_id"]] = totals.get(row["goal_id"], 0) + row["total"]
        return totals

    # ------------------------------------------------------------ tallies

    def add_tally(self, goal_id: int, amount: int = 1, now: int | None = None) -> None:
        """Record finished items for a count goal, e.g. one solved problem."""
        if amount <= 0:
            raise ValueError("Amount must be positive")
        with self.conn:
            self.conn.execute(
                "INSERT INTO tallies (goal_id, ts, amount) VALUES (?, ?, ?)",
                (goal_id, now if now is not None else _now(), amount),
            )

    def undo_tally(self, goal_id: int, week_start: date) -> bool:
        """Remove the most recent tally for the goal in the given week.
        Returns False if there was nothing to undo."""
        ws, we = week_bounds(week_start)
        with self.conn:
            row = self.conn.execute(
                "SELECT id FROM tallies WHERE goal_id = ? AND ts >= ? AND ts < ? "
                "ORDER BY ts DESC, id DESC LIMIT 1",
                (goal_id, ws, we),
            ).fetchone()
            if row is None:
                return False
            self.conn.execute("DELETE FROM tallies WHERE id = ?", (row["id"],))
        return True

    def tally_count(self, goal_id: int) -> int:
        (total,) = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM tallies WHERE goal_id = ?", (goal_id,)
        ).fetchone()
        return total
