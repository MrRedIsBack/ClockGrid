"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from clockgrid.db import Database, default_db_path
from clockgrid.ui.main_window import MainWindow

ICON_PATH = Path(__file__).resolve().parent / "assets" / "clockgrid.ico"


def _set_windows_app_id() -> None:
    """Give the app its own taskbar identity, so Windows shows the ClockGrid
    icon instead of grouping it under Python."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClockGrid.ClockGrid")


def main() -> int:
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("ClockGrid")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    db = Database(default_db_path())
    window = MainWindow(db)
    window.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
