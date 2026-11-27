"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from clockgrid.db import Database, default_db_path
from clockgrid.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ClockGrid")
    db = Database(default_db_path())
    window = MainWindow(db)
    window.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
