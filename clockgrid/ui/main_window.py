"""Main window: a sidebar for navigation and the pages it switches between."""

from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clockgrid.db import Database, Goal
from clockgrid.ui.clock_card import CARD_WIDTH, ClockCard
from clockgrid.ui.dialogs import DEFAULT_COLORS, GoalDialog, SessionsDialog, SettingsDialog
from clockgrid.ui.history_tab import HistoryTab
from clockgrid.ui.leaderboard_tab import LeaderboardTab
from clockgrid.ui.stats_tab import StatsTab
from clockgrid.weeks import format_clock, format_duration, format_week_range

GRID_SPACING = 16
SIDEBAR_WIDTH = 200

SIDEBAR_STYLE = """
QFrame#Sidebar { background: rgba(127, 127, 127, 0.07); border: none; border-right: 1px solid rgba(127, 127, 127, 0.25); }
#Sidebar QPushButton {
    text-align: left; padding: 8px 12px; border: none; border-radius: 8px; background: transparent;
}
#Sidebar QPushButton:hover { background: rgba(127, 127, 127, 0.15); }
#Sidebar QPushButton:checked { background: rgba(127, 127, 127, 0.25); font-weight: bold; }
"""


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.5)
    font.setBold(True)
    label.setFont(font)
    return label


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.goals: list[Goal] = []
        self.cards: dict[int, ClockCard] = {}
        self._columns = 0
        self._week: date | None = None

        self.setWindowTitle("ClockGrid")
        self.resize(1100, 700)

        # ---- This week page
        self.week_label = _heading("")
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
            "No goals yet.\n\nClick “+ New goal” to create your first clock,\n"
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(header)
        layout.addWidget(self.empty_label, 1)
        layout.addWidget(self.scroll, 1)

        # ---- Pages
        self.leaderboard_tab = LeaderboardTab(db)
        self.history_tab = HistoryTab(db)
        self.stats_tab = StatsTab(db)
        self.pages = QStackedWidget()
        for page in (
            clocks_page,
            self._titled("Leaderboard", self.leaderboard_tab),
            self._titled("History", self.history_tab),
            self._titled("Stats", self.stats_tab),
        ):
            self.pages.addWidget(page)
        self.pages.currentChanged.connect(self._refresh_current_tab)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 20, 28, 20)
        content_layout.addWidget(self.pages)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_sidebar())
        row.addWidget(content, 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Ctrl+N"), self, self.add_goal)

        self.reload_goals()
        self.ticker = QTimer(self)
        self.ticker.setInterval(1000)
        self.ticker.timeout.connect(self.refresh)
        self.ticker.start()

    # ------------------------------------------------------------- layout

    @staticmethod
    def _titled(title: str, widget: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_heading(title))
        layout.addWidget(widget, 1)
        return page

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar.setStyleSheet(SIDEBAR_STYLE)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 16, 10, 12)
        layout.setSpacing(2)

        def button(text: str, handler=None) -> QPushButton:
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if handler:
                b.clicked.connect(handler)
            layout.addWidget(b)
            return b

        title = QLabel("ClockGrid")
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.2)
        font.setBold(True)
        title.setFont(font)
        title.setContentsMargins(12, 0, 0, 12)
        layout.addWidget(title)

        button("+  New goal", self.add_goal)
        layout.addSpacing(12)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for index, text in enumerate(["This week", "Leaderboard", "History", "Stats"]):
            b = button(text)
            b.setCheckable(True)
            self.nav.addButton(b, index)
        self.nav.button(0).setChecked(True)
        self.nav.idClicked.connect(self.pages.setCurrentIndex)

        layout.addStretch(1)
        button("Sessions", self.open_sessions)
        self.archived_menu = QMenu(self)
        self.archived_menu.aboutToShow.connect(self._fill_archived_menu)
        archived = button("Archived")
        archived.clicked.connect(
            lambda: self.archived_menu.exec(archived.mapToGlobal(archived.rect().topRight()))
        )
        button("Settings", self.open_settings)
        return sidebar

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
        """Leaderboard, History and Stats are recalculated when shown or after data changes,
        not every second."""
        page = {1: self.leaderboard_tab, 2: self.history_tab, 3: self.stats_tab}.get(self.pages.currentIndex())
        if page:
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
