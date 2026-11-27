"""Main window: the week header and a responsive grid of goal clocks."""

from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from clockgrid.db import Database, Goal
from clockgrid.ui.clock_card import CARD_WIDTH, ClockCard
from clockgrid.ui.dialogs import DEFAULT_COLORS, GoalDialog, SessionsDialog, SettingsDialog
from clockgrid.ui.history_tab import HistoryTab
from clockgrid.ui.stats_tab import StatsTab
from clockgrid.weeks import format_clock, format_duration, format_week_range

GRID_SPACING = 16


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.goals: list[Goal] = []
        self.cards: dict[int, ClockCard] = {}
        self._columns = 0
        self._week: date | None = None

        self.setWindowTitle("ClockGrid")
        self.resize(1040, 680)
        self._build_toolbar()

        self.week_label = QLabel()
        week_font = self.week_label.font()
        week_font.setPointSizeF(week_font.pointSizeF() * 1.5)
        week_font.setBold(True)
        self.week_label.setFont(week_font)
        self.total_label = QLabel()

        header = QHBoxLayout()
        header.addWidget(self.week_label)
        header.addStretch(1)
        header.addWidget(self.total_label)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(GRID_SPACING)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.empty_label = QLabel(
            "No goals yet.\n\nClick “+ Add goal” to create your first clock,\n"
            "for example “Studying – 20 hours a week”."
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setEnabled(False)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setWidget(self.grid_host)

        clocks_page = QWidget()
        layout = QVBoxLayout(clocks_page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(self.empty_label, 1)
        layout.addWidget(self.scroll, 1)

        self.history_tab = HistoryTab(db)
        self.stats_tab = StatsTab(db)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(clocks_page, "This week")
        self.tabs.addTab(self.history_tab, "History")
        self.tabs.addTab(self.stats_tab, "Stats")
        self.tabs.currentChanged.connect(self._refresh_current_tab)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(24, 8, 24, 16)
        outer.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.reload_goals()
        self.ticker = QTimer(self)
        self.ticker.setInterval(1000)
        self.ticker.timeout.connect(self.refresh)
        self.ticker.start()

    # ------------------------------------------------------------- layout

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(bar)

        add = QAction("+ Add goal", self)
        add.setShortcut("Ctrl+N")
        add.triggered.connect(self.add_goal)
        bar.addAction(add)

        sessions = QAction("Sessions", self)
        sessions.triggered.connect(self.open_sessions)
        bar.addAction(sessions)

        self.archived_menu = QMenu(self)
        self.archived_menu.aboutToShow.connect(self._fill_archived_menu)
        archived = QToolButton()
        archived.setText("Archived")
        archived.setMenu(self.archived_menu)
        archived.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bar.addWidget(archived)

        settings = QAction("Settings", self)
        settings.triggered.connect(self.open_settings)
        bar.addAction(settings)

    def _fill_archived_menu(self) -> None:
        self.archived_menu.clear()
        archived = [g for g in self.db.goals(include_archived=True) if g.archived]
        if not archived:
            self.archived_menu.addAction("No archived goals").setEnabled(False)
            return
        for g in archived:
            self.archived_menu.addAction(f"Restore “{g.name}”", lambda gid=g.id: self._restore(gid))

    def _relayout(self, force: bool = False) -> None:
        available = self.scroll.viewport().width()
        columns = max(1, (available + GRID_SPACING) // (CARD_WIDTH + GRID_SPACING))
        if columns == self._columns and not force:
            return
        self._columns = columns
        while self.grid.count():
            self.grid.takeAt(0)
        for i, goal in enumerate(self.goals):
            self.grid.addWidget(self.cards[goal.id], i // columns, i % columns)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._relayout(force=True)

    # --------------------------------------------------------------- data

    def reload_goals(self) -> None:
        self.goals = self.db.goals()
        ids = {g.id for g in self.goals}
        for gid in list(self.cards):
            if gid not in ids:
                card = self.cards.pop(gid)
                self.grid.removeWidget(card)
                card.deleteLater()
        for g in self.goals:
            if g.id not in self.cards:
                card = ClockCard(g.id)
                card.toggle_requested.connect(self.toggle_timer)
                card.edit_requested.connect(self.edit_goal)
                card.archive_requested.connect(self.archive_goal)
                card.delete_requested.connect(self.delete_goal)
                self.cards[g.id] = card
        has_goals = bool(self.goals)
        self.empty_label.setVisible(not has_goals)
        self.scroll.setVisible(has_goals)
        self._relayout(force=True)
        self.refresh()
        self._refresh_current_tab()

    def _refresh_current_tab(self) -> None:
        """History and Stats are recalculated when shown or after data changes,
        not every second."""
        page = self.tabs.currentWidget()
        if page in (self.history_tab, self.stats_tab):
            page.refresh()

    def refresh(self) -> None:
        now = int(time.time())
        week = self.db.current_week_start()
        if week != self._week:  # first run, new week, or week-start setting changed
            self.db.snapshot_week(week)
            self._week = week

        progress = self.db.week_progress(week, now)
        running = self.db.running_session()
        total_worked = total_target = 0
        for goal in self.goals:
            target = self.db.target_minutes_for_week(goal.id, week)
            worked = progress.get(goal.id, 0)
            total_worked += worked
            total_target += target * 60
            since = running.start_ts if running and running.goal_id == goal.id else None
            self.cards[goal.id].update_state(goal, worked, target, since, now)

        self.week_label.setText(f"This week · {format_week_range(week)}")
        self.total_label.setText(
            f"Total {format_duration(total_worked)} / {format_duration(total_target)}"
            if self.goals
            else ""
        )

        running_goal = next((g for g in self.goals if running and g.id == running.goal_id), None)
        if running_goal:
            self.setWindowTitle(f"▶ {running_goal.name} {format_clock(now - running.start_ts)} – ClockGrid")
        else:
            self.setWindowTitle("ClockGrid")

    # ------------------------------------------------------------ actions

    def toggle_timer(self, goal_id: int) -> None:
        running = self.db.running_session()
        if running and running.goal_id == goal_id:
            self.db.stop_timer()
        else:
            self.db.start_timer(goal_id)
        self.refresh()

    def add_goal(self) -> None:
        count = len(self.db.goals(include_archived=True))
        dlg = GoalDialog(self, default_color=DEFAULT_COLORS[count % len(DEFAULT_COLORS)])
        if dlg.exec():
            name, color, minutes = dlg.values()
            self.db.add_goal(name, color, minutes)
            self.reload_goals()

    def edit_goal(self, goal_id: int) -> None:
        goal = self.db.goal(goal_id)
        if goal is None:
            return
        dlg = GoalDialog(self, goal=goal)
        if dlg.exec():
            name, color, minutes = dlg.values()
            self.db.update_goal(goal_id, name=name, color=color, target_minutes=minutes)
            self.reload_goals()

    def archive_goal(self, goal_id: int) -> None:
        goal = self.db.goal(goal_id)
        if goal is None:
            return
        answer = QMessageBox.question(
            self,
            "Archive goal",
            f"Archive “{goal.name}”?\n\nIt will be hidden from the grid but its history is kept. "
            "You can restore it from the Archived menu.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.db.set_archived(goal_id, True)
            self.reload_goals()

    def _restore(self, goal_id: int) -> None:
        self.db.set_archived(goal_id, False)
        self.reload_goals()

    def delete_goal(self, goal_id: int) -> None:
        goal = self.db.goal(goal_id)
        if goal is None:
            return
        count = self.db.session_count(goal_id)
        answer = QMessageBox.warning(
            self,
            "Delete goal",
            f"Permanently delete “{goal.name}” and its {count} session(s)?\n\n"
            "This can't be undone. Use Archive instead to keep the history.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.db.delete_goal(goal_id)
            self.reload_goals()

    def open_sessions(self) -> None:
        SessionsDialog(self.db, self).exec()
        self.refresh()
        self._refresh_current_tab()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self, self.db.week_start_day)
        if dlg.exec():
            self.db.week_start_day = dlg.week_start_day()
            self.refresh()
            self._refresh_current_tab()
