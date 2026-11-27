"""A single goal's clock: a progress ring, its time, and a start/stop button."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from clockgrid.db import Goal
from clockgrid.weeks import format_clock, format_duration

CARD_WIDTH = 240


class ProgressRing(QWidget):
    """A ring that fills clockwise from the top. Past 100% a second, darker
    lap is drawn over the first so overshooting is visible."""

    THICKNESS = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._color = QColor("#4f8cff")
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(170, 170)

    def set_values(self, progress: float, color: str) -> None:
        self._progress = max(0.0, progress)
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.THICKNESS
        side = min(self.width(), self.height()) - t - 2
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        pen = QPen(QColor(self._color), t)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        track = QColor(self._color)
        track.setAlpha(45)
        pen.setColor(track)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)

        first = min(self._progress, 1.0)
        if first > 0:
            pen.setColor(self._color)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -round(first * 360 * 16))
        if self._progress > 1.0:
            pen.setColor(self._color.darker(160))
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -round(min(self._progress - 1.0, 1.0) * 360 * 16))

        p.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        font = QFont(self.font())
        font.setPixelSize(max(12, int(side / 6)))
        font.setBold(True)
        p.setFont(font)
        label = f"{round(self._progress * 100)}%"
        if self._progress >= 1.0:
            label += " ✓"
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


class ClockCard(QFrame):
    toggle_requested = Signal(int)
    edit_requested = Signal(int)
    archive_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, goal_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.goal_id = goal_id
        self._style_key: tuple | None = None
        self.setObjectName("ClockCard")
        self.setFixedWidth(CARD_WIDTH)

        self.name_label = QLabel()
        self.name_label.setWordWrap(True)
        name_font = self.name_label.font()
        name_font.setPointSizeF(name_font.pointSizeF() * 1.25)
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        # Room for two lines, so rings line up whether or not a name wraps.
        self.name_label.setFixedHeight(self.name_label.fontMetrics().lineSpacing() * 2 + 2)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        menu_button = QToolButton()
        menu_button.setText("⋯")
        menu_button.setAutoRaise(True)
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_button.setMenu(self._build_menu())
        menu_button.setStyleSheet("QToolButton::menu-indicator { image: none; }")

        header = QHBoxLayout()
        header.addWidget(self.name_label, 1)
        header.addWidget(menu_button, 0, Qt.AlignmentFlag.AlignTop)

        self.ring = ProgressRing()

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_font = self.time_label.font()
        time_font.setPointSizeF(time_font.pointSizeF() * 1.15)
        self.time_label.setFont(time_font)

        self.detail_label = QLabel()
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setEnabled(False)  # greyed-out secondary text

        self.button = QPushButton("Start")
        self.button.setMinimumHeight(34)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: self.toggle_requested.emit(self.goal_id))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.ring)
        layout.addWidget(self.time_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.button)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self._build_menu().exec(self.mapToGlobal(pos))
        )

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Edit goal…", lambda: self.edit_requested.emit(self.goal_id))
        menu.addAction("Archive", lambda: self.archive_requested.emit(self.goal_id))
        menu.addSeparator()
        menu.addAction("Delete…", lambda: self.delete_requested.emit(self.goal_id))
        return menu

    def update_state(
        self, goal: Goal, worked: int, target_minutes: int, running_since: int | None, now: int
    ) -> None:
        target = target_minutes * 60
        progress = worked / target if target else 0.0
        running = running_since is not None

        self.name_label.setText(goal.name)
        self.ring.set_values(progress, goal.color)
        self.time_label.setText(f"{format_duration(worked)} / {format_duration(target)}")

        if running:
            self.detail_label.setText(f"● Running  {format_clock(now - running_since)}")
        elif worked >= target:
            over = worked - target
            self.detail_label.setText(f"Goal hit · {format_duration(over)} over" if over >= 60 else "Goal hit")
        else:
            self.detail_label.setText(f"{format_duration(target - worked)} to go")

        self.button.setText("Stop" if running else "Start")
        self._apply_style(goal.color, running)

    def _apply_style(self, color: str, running: bool) -> None:
        key = (color, running)
        if key == self._style_key:
            return
        self._style_key = key
        border = f"2px solid {color}" if running else "1px solid palette(mid)"
        button = (
            f"background: {color}; color: white; border: none; border-radius: 6px; font-weight: bold;"
            if running
            else "border-radius: 6px;"
        )
        self.setStyleSheet(
            f"#ClockCard {{ background: palette(base); border: {border}; border-radius: 12px; }}"
            f"#ClockCard QPushButton {{ {button} }}"
        )
