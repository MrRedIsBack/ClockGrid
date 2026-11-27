"""Leaderboard: goals ranked by the average share of their weekly target reached."""

from __future__ import annotations

import html
import time
from datetime import timedelta

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from clockgrid import stats
from clockgrid.db import Database

RANGES = [("Last 4 weeks", 4), ("Last 12 weeks", 12), ("Last 26 weeks", 26), ("All time", None)]
BALANCED_GAP = 0.10  # within 10 percentage points counts as balanced


class CompletionBar(QWidget):
    """A horizontal bar with a tick at 100% of the target."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.value = 0.0
        self.scale = 1.0
        self.color = QColor("#4f8cff")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(300, 22)

    def set_value(self, value: float, scale: float, color: str) -> None:
        self.value, self.scale, self.color = value, scale, QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = 12
        y = (self.height() - h) / 2
        track = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        track.setAlpha(25)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, y, self.width(), h), h / 2, h / 2)
        if self.value > 0:
            width = max(h, self.width() * min(self.value / self.scale, 1.0))
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(0, y, width, h), h / 2, h / 2)
        if self.scale > 1.0:  # mark where 100% is when bars can go past it
            tick = QColor(self.palette().color(QPalette.ColorRole.WindowText))
            tick.setAlpha(120)
            x = self.width() / self.scale
            p.setBrush(tick)
            p.drawRect(QRectF(x - 1, y - 4, 2, h + 8))
        p.end()


class LeaderboardTab(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db

        self.range_combo = QComboBox()
        for label, weeks in RANGES:
            self.range_combo.addItem(label, weeks)
        self.range_combo.setCurrentIndex(1)
        self.range_combo.currentIndexChanged.connect(self.refresh)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Range"))
        filters.addWidget(self.range_combo)
        filters.addStretch(1)

        caption = QLabel("Ranked by the average % of each goal's weekly target you reach, counting finished weeks.")
        caption.setEnabled(False)
        caption.setWordWrap(True)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)

        self.board = QFrame()
        self.board.setObjectName("Board")
        self.board.setStyleSheet(
            "#Board { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }"
        )
        self.rows = QGridLayout(self.board)
        self.rows.setContentsMargins(18, 14, 18, 14)
        self.rows.setHorizontalSpacing(14)
        self.rows.setVerticalSpacing(12)
        self.rows.setColumnStretch(3, 1)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(14)
        body.addWidget(caption)
        body.addWidget(self.board)
        body.addWidget(self.summary)
        body.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(content)

        self.empty_label = QLabel("No goals yet. Add a goal and track some time first.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(filters)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.empty_label, 1)

    def _clear_rows(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh(self) -> None:
        now = int(time.time())
        current = self.db.current_week_start()
        goals = self.db.goals()
        n_weeks = self.range_combo.currentData()
        first_week = current - timedelta(days=7 * (n_weeks - 1)) if n_weeks else None
        results = {
            gid: stats.since(rs, first_week)
            for gid, rs in stats.weekly_results(self.db, goals, current, now).items()
        }
        entries = stats.leaderboard(goals, results)

        self.scroll.setVisible(bool(entries))
        self.empty_label.setVisible(not entries)
        self._clear_rows()
        if not entries:
            return

        scale = max(1.0, max(e.completion for e in entries))
        for row, e in enumerate(entries):
            rank = QLabel(f"{row + 1}" if e.weeks else "–")
            rank_font = rank.font()
            rank_font.setBold(True)
            rank_font.setPointSizeF(rank_font.pointSizeF() * 1.2)
            rank.setFont(rank_font)
            rank.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rank.setMinimumWidth(20)

            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background: {e.goal.color}; border-radius: 6px;")

            name = QLabel(e.goal.name)
            name_font = name.font()
            name_font.setBold(True)
            name.setFont(name_font)
            name.setMinimumWidth(140)

            bar = CompletionBar()
            bar.set_value(e.completion, scale, e.goal.color)

            pct = QLabel(f"{round(e.completion * 100)}%")
            pct.setFont(rank_font)
            pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            pct.setMinimumWidth(56)

            if e.weeks:
                hits = round(e.hit_rate * e.weeks)
                detail_text = f"hit {hits} of {e.weeks} week{'s' if e.weeks != 1 else ''}"
            else:
                detail_text = "this week so far"
            detail = QLabel(detail_text)
            detail.setEnabled(False)
            detail.setMinimumWidth(110)

            for col, widget in enumerate([rank, dot, name, bar, pct, detail]):
                self.rows.addWidget(widget, row, col, Qt.AlignmentFlag.AlignVCenter)

        self.summary.setText(self._balance_text(entries))

    @staticmethod
    def _balance_text(entries: list[stats.LeaderEntry]) -> str:
        ranked = [e for e in entries if e.weeks]
        if len(ranked) < 2:
            return "Rankings fill in once your goals have a finished week."
        top, bottom = ranked[0], ranked[-1]
        gap = top.completion - bottom.completion
        if gap <= BALANCED_GAP:
            return f"Nicely balanced: every goal is within {round(gap * 100)} points of the others."
        return (
            f"Biggest gap: <b>{html.escape(top.goal.name)}</b> is at {round(top.completion * 100)}% "
            f"but <b>{html.escape(bottom.goal.name)}</b> is at {round(bottom.completion * 100)}%. "
            f"Giving {html.escape(bottom.goal.name)} a bit more time would even things out."
        )
