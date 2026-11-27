"""A single goal's clock: a progress ring, its time, and a start/stop button."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
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
        self.center_text: str | None = None  # shown instead of the percentage when set
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
        if self.center_text is not None:
            label = self.center_text
        else:
            label = f"{round(self._progress * 100)}%"
            if self._progress >= 1.0:
                label += " ✓"
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.end()


def _icon(kind: str, color: QColor, size: int = 16) -> QIcon:
    """Small crisp icons drawn in code: play, stop, edit (pencil) and more (dots)."""
    scale = 2
    pix = QPixmap(size * scale, size * scale)
    pix.setDevicePixelRatio(scale)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    if kind == "play":
        pen = QPen(color, s * 0.1)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolygon(QPolygonF([QPointF(s * 0.3, s * 0.2), QPointF(s * 0.3, s * 0.8), QPointF(s * 0.8, s * 0.5)]))
    elif kind == "stop":
        p.drawRoundedRect(QRectF(s * 0.24, s * 0.24, s * 0.52, s * 0.52), s * 0.1, s * 0.1)
    elif kind == "edit":
        pen = QPen(color, s * 0.13)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(s * 0.36, s * 0.64), QPointF(s * 0.78, s * 0.22))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(s * 0.16, s * 0.84), QPointF(s * 0.22, s * 0.6), QPointF(s * 0.4, s * 0.78)]))
    elif kind == "more":
        for x in (0.25, 0.5, 0.75):
            p.drawEllipse(QPointF(s * x, s * 0.5), s * 0.08, s * 0.08)
    p.end()
    return QIcon(pix)


def _text_on(color: QColor) -> str:
    """Black or white, whichever reads better on the given background."""
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#1a1a1a" if luminance > 165 else "#ffffff"


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

        ink = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        ink.setAlpha(190)
        edit_button = self._icon_button(_icon("edit", ink), "Edit goal")
        edit_button.clicked.connect(lambda: self.edit_requested.emit(self.goal_id))
        more_button = self._icon_button(_icon("more", ink), "More")
        more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_button.setMenu(self._build_menu())

        header = QHBoxLayout()
        header.setSpacing(2)
        header.addWidget(self.name_label, 1)
        header.addWidget(edit_button, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(more_button, 0, Qt.AlignmentFlag.AlignTop)

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
        self.button.setObjectName("Toggle")
        self.button.setFixedHeight(36)
        self.button.setIconSize(QSize(14, 14))
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: self.toggle_requested.emit(self.goal_id))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.ring)
        layout.addWidget(self.time_label)
        layout.addWidget(self.detail_label)
        layout.addSpacing(4)
        layout.addWidget(self.button)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self._build_menu().exec(self.mapToGlobal(pos))
        )

    @staticmethod
    def _icon_button(icon: QIcon, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(28, 28)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

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

        self._apply_style(goal.color, running)

    def _apply_style(self, color: str, running: bool) -> None:
        key = (color, running)
        if key == self._style_key:
            return
        self._style_key = key
        c = QColor(color)
        r, g, b = c.red(), c.green(), c.blue()
        if running:
            text = _text_on(c)
            self.button.setText(" Stop")
            self.button.setIcon(_icon("stop", QColor(text)))
            toggle = (
                f"QPushButton#Toggle {{ background: {color}; color: {text}; border: 1px solid {color};"
                " border-radius: 18px; font-weight: bold; }"
                f"QPushButton#Toggle:hover {{ background: {c.darker(112).name()}; }}"
            )
        else:
            self.button.setText(" Start")
            self.button.setIcon(_icon("play", c))
            toggle = (
                f"QPushButton#Toggle {{ background: rgba({r}, {g}, {b}, 0.14); color: palette(text);"
                f" border: 1px solid rgba({r}, {g}, {b}, 0.55); border-radius: 18px; font-weight: bold; }}"
                f"QPushButton#Toggle:hover {{ background: rgba({r}, {g}, {b}, 0.26); }}"
                f"QPushButton#Toggle:pressed {{ background: rgba({r}, {g}, {b}, 0.36); }}"
            )
        border = f"2px solid {color}" if running else "1px solid rgba(127, 127, 127, 0.25)"
        self.setStyleSheet(
            f"#ClockCard {{ background: palette(base); border: {border}; border-radius: 12px; }}"
            + toggle
            + "QToolButton { border: none; border-radius: 6px; background: transparent; }"
            "QToolButton:hover { background: rgba(127, 127, 127, 0.22); }"
            "QToolButton::menu-indicator { image: none; width: 0; }"
        )
