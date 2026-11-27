"""Dialogs: add/edit goal, add/edit session, the sessions list and settings."""

from __future__ import annotations

import time
from datetime import timedelta

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from clockgrid.db import Database, Goal, Session
from clockgrid.ui.clock_card import ProgressRing
from clockgrid.weeks import WEEKDAY_NAMES, format_duration, format_week_range, week_bounds

DEFAULT_COLORS = ["#4f8cff", "#f2994a", "#27ae60", "#bb6bd9", "#eb5757", "#2d9cdb", "#f2c94c", "#6fcf97"]
DATETIME_FORMAT = "ddd d MMM yyyy   HH:mm"


def _buttons(dialog: QDialog, ok_handler) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(ok_handler)
    box.rejected.connect(dialog.reject)
    return box


TARGET_PRESETS = [1, 3, 5, 10, 20]

GOAL_DIALOG_STYLE = """
QPushButton#Chip {
    border: 1px solid rgba(127, 127, 127, 0.35); border-radius: 12px;
    padding: 3px 12px; background: transparent;
}
QPushButton#Chip:hover { background: rgba(127, 127, 127, 0.18); }
"""


def _section(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class GoalDialog(QDialog):
    """Create or edit a goal, with a live preview of its clock."""

    def __init__(
        self, parent: QWidget | None = None, goal: Goal | None = None, default_color: str = DEFAULT_COLORS[0]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit goal" if goal else "New goal")
        self.setMinimumWidth(560)
        self.setStyleSheet(GOAL_DIALOG_STYLE)
        self.color = QColor(goal.color if goal else default_color)

        title = QLabel("Edit goal" if goal else "New goal")
        title_font = title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QLabel("How much time do you want to spend on this each week?")
        subtitle.setEnabled(False)

        # Live preview of the clock
        self.preview = ProgressRing()
        self.preview.setFixedSize(160, 160)
        self.preview_name = QLabel()
        self.preview_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_name.setWordWrap(True)
        self.preview_name.setFixedWidth(160)
        preview_font = self.preview_name.font()
        preview_font.setBold(True)
        self.preview_name.setFont(preview_font)
        preview = QVBoxLayout()
        preview.addWidget(self.preview)
        preview.addWidget(self.preview_name)
        preview.addStretch(1)

        # Name
        self.name_edit = QLineEdit(goal.name if goal else "")
        self.name_edit.setPlaceholderText("e.g. C++ (learncpp.com)")
        self.name_edit.setMaxLength(60)
        self.name_edit.setMinimumHeight(32)

        # Weekly target, with one-click presets
        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setRange(0.25, 168)
        self.hours_spin.setSingleStep(0.5)
        self.hours_spin.setDecimals(2)
        self.hours_spin.setSuffix(" h")
        self.hours_spin.setMinimumHeight(32)
        self.hours_spin.setMinimumWidth(110)
        self.hours_spin.setValue(goal.target_minutes / 60 if goal else 5)
        self.per_day = QLabel()
        self.per_day.setEnabled(False)
        target_row = QHBoxLayout()
        target_row.addWidget(self.hours_spin)
        target_row.addWidget(self.per_day)
        target_row.addStretch(1)
        presets = QHBoxLayout()
        presets.setSpacing(6)
        for hours in TARGET_PRESETS:
            chip = QPushButton(f"{hours}h")
            chip.setObjectName("Chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, h=hours: self.hours_spin.setValue(h))
            presets.addWidget(chip)
        presets.addStretch(1)

        # Colour swatches, plus a custom colour picker
        self.swatches = QButtonGroup(self)
        self.swatches.setExclusive(True)
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(8)
        for color in DEFAULT_COLORS:
            swatch = self._swatch(color)
            swatch.clicked.connect(lambda _=False, c=color: self._set_color(QColor(c)))
            self.swatches.addButton(swatch)
            swatch_row.addWidget(swatch)
        self.custom_swatch = self._swatch(None)
        self.custom_swatch.setText("…")
        self.custom_swatch.setToolTip("Pick a custom colour")
        self.custom_swatch.clicked.connect(self._pick_custom)
        self.swatches.addButton(self.custom_swatch)
        swatch_row.addWidget(self.custom_swatch)
        swatch_row.addStretch(1)
        self._check_current_swatch()

        fields = QVBoxLayout()
        fields.setSpacing(6)
        fields.addWidget(_section("Name"))
        fields.addWidget(self.name_edit)
        fields.addSpacing(10)
        fields.addWidget(_section("Weekly target"))
        fields.addLayout(target_row)
        fields.addLayout(presets)
        fields.addSpacing(10)
        fields.addWidget(_section("Colour"))
        fields.addLayout(swatch_row)
        fields.addStretch(1)

        body = QHBoxLayout()
        body.setSpacing(24)
        body.addLayout(preview)
        body.addLayout(fields, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.addButton(
            "Save changes" if goal else "Create goal", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.ok_button.setDefault(True)
        self.ok_button.setMinimumHeight(32)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(14)
        layout.addLayout(body)
        if goal:
            note = QLabel("A new target applies from this week on; past weeks keep their old target.")
            note.setWordWrap(True)
            note.setEnabled(False)
            layout.addWidget(note)
        layout.addSpacing(10)
        layout.addWidget(buttons)

        self.name_edit.textChanged.connect(self._update)
        self.hours_spin.valueChanged.connect(self._update)
        self.name_edit.setFocus()
        self._update()

    @staticmethod
    def _swatch(color: str | None) -> QPushButton:
        button = QPushButton()
        button.setCheckable(True)
        button.setFixedSize(28, 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        GoalDialog._paint_swatch(button, color)
        return button

    @staticmethod
    def _paint_swatch(button: QPushButton, color: str | None) -> None:
        fill = color or "transparent"
        border = "rgba(127, 127, 127, 0.5)" if color is None else fill
        button.setStyleSheet(
            f"QPushButton {{ background: {fill}; border: 2px solid {border}; border-radius: 14px; }}"
            "QPushButton:checked { border: 3px solid palette(text); }"
        )

    def _check_current_swatch(self) -> None:
        for button, color in zip(self.swatches.buttons(), DEFAULT_COLORS):
            if QColor(color) == self.color:
                button.setChecked(True)
                return
        self._paint_swatch(self.custom_swatch, self.color.name())
        self.custom_swatch.setText("")
        self.custom_swatch.setChecked(True)

    def _set_color(self, color: QColor) -> None:
        self.color = color
        self._update()

    def _pick_custom(self) -> None:
        color = QColorDialog.getColor(self.color, self, "Goal colour")
        if color.isValid():
            self._paint_swatch(self.custom_swatch, color.name())
            self.custom_swatch.setText("")
            self._set_color(color)
        self._check_current_swatch()

    def _update(self) -> None:
        name = self.name_edit.text().strip()
        hours = self.hours_spin.value()
        self.preview_name.setText(name or "Your goal")
        self.preview.center_text = format_duration(round(hours * 3600))
        self.preview.set_values(0.65, self.color.name())
        self.per_day.setText(f"≈ {format_duration(round(hours * 3600 / 7))} a day")
        self.ok_button.setEnabled(bool(name))
        self.ok_button.setStyleSheet(
            f"QPushButton {{ background: {self.color.name()}; color: white; border: none;"
            " border-radius: 6px; padding: 6px 18px; font-weight: bold; }"
            "QPushButton:disabled { background: rgba(127, 127, 127, 0.3); color: rgba(255, 255, 255, 0.6); }"
        )

    def values(self) -> tuple[str, str, int]:
        return self.name_edit.text().strip(), self.color.name(), round(self.hours_spin.value() * 60)


class SessionDialog(QDialog):
    """Add a session by hand, or edit an existing one."""

    def __init__(
        self,
        parent: QWidget | None,
        goals: list[Goal],
        session: Session | None = None,
        default_start: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit session" if session else "Add session")
        self.setMinimumWidth(380)
        self.running = session is not None and session.running

        self.goal_combo = QComboBox()
        for g in goals:
            self.goal_combo.addItem(g.name + ("  (archived)" if g.archived else ""), g.id)
        if session:
            self.goal_combo.setCurrentIndex(max(0, self.goal_combo.findData(session.goal_id)))

        now = int(time.time()) // 60 * 60
        if session:
            start, end = session.start_ts, session.end_ts or now
        else:
            start = default_start if default_start is not None else now - 3600
            end = start + 3600

        self.start_edit = self._datetime_edit(start)
        self.end_edit = self._datetime_edit(end)

        form = QFormLayout()
        form.addRow("Goal", self.goal_combo)
        form.addRow("Start", self.start_edit)
        if self.running:
            form.addRow("End", QLabel("Still running – stop the timer to set an end time."))
        else:
            form.addRow("End", self.end_edit)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept))

    @staticmethod
    def _datetime_edit(ts: int) -> QDateTimeEdit:
        edit = QDateTimeEdit(QDateTime.fromSecsSinceEpoch(ts))
        edit.setCalendarPopup(True)
        edit.setDisplayFormat(DATETIME_FORMAT)
        return edit

    def _accept(self) -> None:
        if self.goal_combo.currentData() is None:
            QMessageBox.warning(self, "No goal", "Create a goal first.")
            return
        start, end = self._timestamps()
        if end is not None and end <= start:
            QMessageBox.warning(self, "Invalid times", "The end time must be after the start time.")
            return
        if end is None and start > time.time():
            QMessageBox.warning(self, "Invalid time", "A running session can't start in the future.")
            return
        self.accept()

    def _timestamps(self) -> tuple[int, int | None]:
        start = self.start_edit.dateTime().toSecsSinceEpoch()
        end = None if self.running else self.end_edit.dateTime().toSecsSinceEpoch()
        return start, end

    def values(self) -> tuple[int, int, int | None]:
        start, end = self._timestamps()
        return self.goal_combo.currentData(), start, end


class SessionsDialog(QDialog):
    """Browse, add, edit and delete sessions, one week at a time."""

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.week = db.current_week_start()
        self.setWindowTitle("Sessions")
        self.resize(640, 460)

        prev_btn = QPushButton("◀")
        next_btn = QPushButton("▶")
        this_btn = QPushButton("This week")
        for b in (prev_btn, next_btn):
            b.setFixedWidth(36)
        prev_btn.clicked.connect(lambda: self._shift(-7))
        next_btn.clicked.connect(lambda: self._shift(7))
        this_btn.clicked.connect(self._this_week)
        self.week_label = QLabel()
        self.week_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.week_label.font()
        font.setBold(True)
        self.week_label.setFont(font)

        nav = QHBoxLayout()
        nav.addWidget(prev_btn)
        nav.addWidget(self.week_label, 1)
        nav.addWidget(next_btn)
        nav.addWidget(this_btn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Goal", "Start", "End", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)

        add_btn = QPushButton("Add…")
        edit_btn = QPushButton("Edit…")
        delete_btn = QPushButton("Delete")
        close_btn = QPushButton("Close")
        add_btn.clicked.connect(self._add)
        edit_btn.clicked.connect(self._edit)
        delete_btn.clicked.connect(self._delete)
        close_btn.clicked.connect(self.accept)
        self.total_label = QLabel()

        buttons = QHBoxLayout()
        buttons.addWidget(add_btn)
        buttons.addWidget(edit_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.total_label)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(nav)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self._load()

    def _shift(self, days: int) -> None:
        self.week += timedelta(days=days)
        self._load()

    def _this_week(self) -> None:
        self.week = self.db.current_week_start()
        self._load()

    def _load(self) -> None:
        now = int(time.time())
        self.week_label.setText(format_week_range(self.week))
        names = {g.id: g.name for g in self.db.goals(include_archived=True)}
        ws, we = week_bounds(self.week)
        sessions = self.db.sessions_between(ws, we, now)
        self.table.setRowCount(len(sessions))
        total = 0
        for row, s in enumerate(sessions):
            duration = s.duration(now)
            total += duration
            start = QDateTime.fromSecsSinceEpoch(s.start_ts).toString(DATETIME_FORMAT)
            end = "running" if s.running else QDateTime.fromSecsSinceEpoch(s.end_ts).toString(DATETIME_FORMAT)
            cells = [names.get(s.goal_id, "?"), start, end, format_duration(duration)]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, s.id)
                self.table.setItem(row, col, item)
        self.total_label.setText(f"{len(sessions)} sessions · {format_duration(total)}")

    def _selected(self) -> Session | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return self.db.session(items[0].data(Qt.ItemDataRole.UserRole))

    def _goals_for(self, session: Session | None) -> list[Goal]:
        goals = self.db.goals()
        if session and all(g.id != session.goal_id for g in goals):
            archived = self.db.goal(session.goal_id)
            if archived:
                goals.append(archived)
        return goals

    def _add(self) -> None:
        goals = self._goals_for(None)
        if not goals:
            QMessageBox.information(self, "No goals", "Create a goal first.")
            return
        # Default to an hour ending now if viewing this week, otherwise noon of the week's first day.
        ws, we = week_bounds(self.week)
        now = int(time.time()) // 60 * 60
        default_start = now - 3600 if ws <= now < we else ws + 12 * 3600
        dlg = SessionDialog(self, goals, default_start=default_start)
        if dlg.exec():
            goal_id, start, end = dlg.values()
            self.db.add_session(goal_id, start, end)
            self._load()

    def _edit(self) -> None:
        session = self._selected()
        if session is None:
            return
        dlg = SessionDialog(self, self._goals_for(session), session=session)
        if dlg.exec():
            goal_id, start, end = dlg.values()
            self.db.update_session(session.id, goal_id=goal_id, start_ts=start, end_ts=end)
            self._load()

    def _delete(self) -> None:
        session = self._selected()
        if session is None:
            return
        answer = QMessageBox.question(self, "Delete session", "Delete this session? This can't be undone.")
        if answer == QMessageBox.StandardButton.Yes:
            self.db.delete_session(session.id)
            self._load()


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None, week_start_day: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(320)
        self.week_combo = QComboBox()
        self.week_combo.addItems(WEEKDAY_NAMES)
        self.week_combo.setCurrentIndex(week_start_day)

        form = QFormLayout()
        form.addRow("Week starts on", self.week_combo)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self.accept))

    def week_start_day(self) -> int:
        return self.week_combo.currentIndex()
