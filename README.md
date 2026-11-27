# ClockGrid
Multiple clocks on a grid so you can keep track of your weekly goals.

Set a weekly target for each goal (e.g. AI 5h, Projects 10h, Studying 20h),
start and stop a timer for whatever you're working on, and watch each ring fill up over the week.

## Running

Requires Python 3.11+.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install PySide6 pytest
.venv\Scripts\python -m clockgrid
```

Run the tests with `.venv\Scripts\python -m pytest`.

Your data is stored in `%APPDATA%\ClockGrid\clockgrid.db`
(set the `CLOCKGRID_DB` environment variable to use a different file).

## Features

- A clock per goal showing progress towards its weekly target; going past 100% draws a second, darker lap.
- One timer at a time: starting a goal stops whichever one was running. Timers keep running while the app is closed.
- Add, edit and delete sessions by hand (Sessions), for when you forget to press Start. Sessions under a minute are discarded.
- Archive goals to hide them while keeping their history; restore them from the Archived menu.
- Choose which day your week starts on (Settings).
- Each week's targets are saved, so changing a target doesn't rewrite how past weeks are judged.
