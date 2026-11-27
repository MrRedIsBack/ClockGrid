"""Generate the README screenshots from a demo database.

Run from the project root:  .venv\\Scripts\\python tools\\make_screenshots.py

Uses a temporary database filled with 12 weeks of made-up sessions; your
real data is never read or changed. Windows are rendered without being
shown on screen.
"""

from __future__ import annotations

import random
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clockgrid.db import Database  # noqa: E402
from clockgrid.ui.main_window import MainWindow  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
WEEKS = 12

# name, colour, weekly target (hours), how much of the target is usually reached,
# preferred start hours, preferred weekdays (Mon = 0)
GOALS = [
    ("C++ (learncpp.com)", "#4f8cff", 6, 1.05, [7, 19, 20], [0, 1, 2, 3, 4]),
    ("Community moderation", "#27ae60", 4, 0.95, [12, 21], [0, 2, 4, 5, 6]),
    ("Side project: ClockGrid", "#bb6bd9", 8, 0.82, [10, 14, 20], [5, 6, 6, 2]),
    ("Algorithms & data structures", "#f2994a", 5, 0.78, [18, 19], [1, 3, 5, 6]),
    ("Reading: CS:APP", "#eb5757", 3, 0.55, [8, 22], [0, 6, 6]),
]


def ts(day: date, hour: int, minute: int = 0) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute).timestamp())


def seed(db: Database, rng: random.Random) -> None:
    current = db.current_week_start()
    first = current - timedelta(days=7 * (WEEKS - 1))
    created = ts(first, 9)
    goals = [
        (db.add_goal(name, color, hours * 60, week_start=first, created_at=created), hours, rate, hrs, days)
        for name, color, hours, rate, hrs, days in GOALS
    ]
    now = int(time.time())
    week_fraction = min(1.0, (now - ts(current, 0)) / (7 * 86400))
    busy: set[tuple[date, int]] = set()  # (day, hour) slots already used, to avoid overlaps

    for i in range(WEEKS):
        week = first + timedelta(days=7 * i)
        db.snapshot_week(week)
        is_current = week == current
        for goal, hours, rate, start_hours, days in goals:
            planned = hours * 3600 * rate * rng.uniform(0.7, 1.35)
            if is_current:
                planned *= week_fraction
            attempts = 0
            while planned > 600 and attempts < 60:
                attempts += 1
                day = week + timedelta(days=rng.choice(days))
                hour = rng.choice(start_hours)
                length = int(min(planned, rng.choice([2700, 3600, 5400, 7200])))
                slots = {(day, hour + k) for k in range(-(-length // 3600))}
                start = ts(day, hour, rng.choice([0, 5, 10, 15]))
                if slots & busy or start + length > now:
                    continue
                busy |= slots
                db.add_session(goal.id, start, start + length)
                planned -= length

    # A timer running right now, to show the live state.
    db.start_timer(goals[0][0].id, now=now - 47 * 60 - 12)


def capture(app: QApplication, window: MainWindow, page: int, name: str, height: int) -> None:
    window.resize(1240, height)
    window.nav.button(page).click()
    for _ in range(10):
        app.processEvents()
    path = OUT / f"{name}.png"
    window.grab().save(str(path))
    print(f"Wrote {path.relative_to(ROOT)}")


def main() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(str(ROOT / "clockgrid" / "assets" / "clockgrid.ico")))
    OUT.mkdir(parents=True, exist_ok=True)

    db = Database(Path(tempfile.mkdtemp()) / "demo.db")
    seed(db, random.Random(7))

    window = MainWindow(db)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    capture(app, window, 0, "this-week", 980)
    capture(app, window, 1, "leaderboard", 520)
    capture(app, window, 2, "history", 700)
    capture(app, window, 3, "stats", 1380)
    window.close()
    db.close()


if __name__ == "__main__":
    main()
