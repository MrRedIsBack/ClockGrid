"""History tab: one row per week, one column per goal, showing hit or miss."""

from __future__ import annotations

import textwrap
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from clockgrid import stats
from clockgrid.db import Database
from clockgrid.weeks import format_duration, format_week_range

HIT_TINT = QColor(39, 174, 96, 55)
MISS_TINT = QColor(235, 87, 87, 40)


class HistoryTab(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db

        self.caption = QLabel(
            "✓ goal hit · ✗ missed · … week in progress. Hit rates count finished weeks only."
        )
        self.caption.setEnabled(False)

        self.table = QTableWidget()
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(False)

        self.empty_label = QLabel("No history yet. Add a goal and track some time first.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.caption)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_label, 1)

    def refresh(self) -> None:
        now = int(time.time())
        current = self.db.current_week_start()
        goals = self.db.goals(include_archived=True)
        results = stats.weekly_results(self.db, goals, current, now)
        goals = [g for g in goals if results[g.id]]
        weeks = sorted({r.week_start for g in goals for r in results[g.id]}, reverse=True)

        has_data = bool(goals)
        self.table.setVisible(has_data)
        self.caption.setVisible(has_data)
        self.empty_label.setVisible(not has_data)
        if not has_data:
            return

        self.table.clear()
        self.table.setColumnCount(len(goals) + 1)
        self.table.setRowCount(len(weeks))
        headers = ["Week"]
        for g in goals:
            s = stats.summarize(results[g.id])
            rate = (
                f"{s.weeks_hit}/{s.weeks_completed} hit ({round(s.hit_rate * 100)}%)"
                if s.hit_rate is not None
                else "no finished weeks"
            )
            name = g.name + (" (archived)" if g.archived else "")
            headers.append("\n".join(textwrap.wrap(name, 20) or [name]) + f"\n{rate}")
        self.table.setHorizontalHeaderLabels(headers)

        row_of = {w: i for i, w in enumerate(weeks)}
        for week, row in row_of.items():
            label = format_week_range(week) + ("  (this week)" if week == current else "")
            self.table.setItem(row, 0, QTableWidgetItem(label))
            for col in range(1, len(goals) + 1):
                item = QTableWidgetItem("—")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip("Not tracked this week")
                self.table.setItem(row, col, item)

        for col, g in enumerate(goals, start=1):
            for r in results[g.id]:
                mark = "…" if not r.complete else ("✓" if r.hit else "✗")
                item = self.table.item(row_of[r.week_start], col)
                item.setText(
                    f"{mark}  {format_duration(r.worked)} / {format_duration(r.target)}"
                    f"   {round(r.completion * 100)}%"
                )
                item.setToolTip(
                    "In progress" if not r.complete else ("Goal hit" if r.hit else "Goal missed")
                )
                if r.complete:
                    item.setBackground(HIT_TINT if r.hit else MISS_TINT)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, len(goals) + 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            header.setMinimumSectionSize(150)
