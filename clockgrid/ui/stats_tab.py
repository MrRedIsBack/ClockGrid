"""Stats page: summary tiles, insights, a weekly chart and a when-you-work heatmap."""

from __future__ import annotations

import time
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from clockgrid import stats
from clockgrid.db import Database, Goal
from clockgrid.ui.charts import Heatmap, WeeklyChart
from clockgrid.weeks import format_duration, week_bounds

ALL_GOALS_COLOR = "#4f8cff"
RANGES = [("Last 4 weeks", 4), ("Last 12 weeks", 12), ("Last 26 weeks", 26), ("All time", None)]


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{round(x * 100)}%"


def _weeks(n: int) -> str:
    return f"{n} week" if n == 1 else f"{n} weeks"


def _swatch(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(QColor(color))
    return QIcon(pix)


class Card(QFrame):
    """A titled, bordered section."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet("#Card { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 12, 16, 14)
        self.title = QLabel(title)
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.1)
        self.title.setFont(font)
        self.body.addWidget(self.title)


class StatTile(Card):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.title.setEnabled(False)
        font = self.title.font()
        font.setBold(False)
        self.title.setFont(font)
        self.value = QLabel("–")
        vfont = self.value.font()
        vfont.setPointSizeF(vfont.pointSizeF() * 2)
        vfont.setBold(True)
        self.value.setFont(vfont)
        self.caption = QLabel()
        self.caption.setEnabled(False)
        self.body.addWidget(self.value)
        self.body.addWidget(self.caption)

    def set(self, title: str, value: str, caption: str) -> None:
        self.title.setText(title)
        self.value.setText(value)
        self.caption.setText(caption)


class StatsTab(QWidget):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db

        self.goal_combo = QComboBox()
        self.goal_combo.setMinimumWidth(180)
        self.range_combo = QComboBox()
        for label, weeks in RANGES:
            self.range_combo.addItem(label, weeks)
        self.range_combo.setCurrentIndex(1)
        self.goal_combo.currentIndexChanged.connect(self.refresh)
        self.range_combo.currentIndexChanged.connect(self.refresh)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Goal"))
        filters.addWidget(self.goal_combo)
        filters.addSpacing(16)
        filters.addWidget(QLabel("Range"))
        filters.addWidget(self.range_combo)
        filters.addStretch(1)

        self.tiles = [StatTile("") for _ in range(6)]
        tiles = QGridLayout()
        tiles.setSpacing(12)
        for i, tile in enumerate(self.tiles):
            tiles.addWidget(tile, i // 3, i % 3)

        self.insights_card = Card("Insights")
        self.insights_label = QLabel()
        self.insights_label.setWordWrap(True)
        self.insights_label.setTextFormat(Qt.TextFormat.RichText)
        self.insights_card.body.addWidget(self.insights_label)

        self.chart_card = Card("Week by week")
        self.chart = WeeklyChart()
        chart_note = QLabel("* week in progress. Hover a bar for details.")
        chart_note.setEnabled(False)
        self.chart_card.body.addWidget(self.chart)
        self.chart_card.body.addWidget(chart_note)

        self.heatmap_card = Card("When you work")
        self.heatmap = Heatmap()
        heat_note = QLabel("Stronger colour means more time. Hover a cell for details.")
        heat_note.setEnabled(False)
        self.heatmap_card.body.addWidget(self.heatmap)
        self.heatmap_card.body.addWidget(heat_note)

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(14)
        body.addLayout(tiles)
        body.addWidget(self.insights_card)
        body.addWidget(self.chart_card)
        body.addWidget(self.heatmap_card)
        body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        self.empty_label = QLabel("No stats yet. Add a goal and track some time first.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(filters)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.empty_label, 1)
        self._scroll = scroll

    # ------------------------------------------------------------ filters

    def _sync_goal_combo(self, goals: list[Goal]) -> None:
        selected = self.goal_combo.currentData()
        self.goal_combo.blockSignals(True)
        self.goal_combo.clear()
        self.goal_combo.addItem("All goals", None)
        for g in goals:
            self.goal_combo.addItem(_swatch(g.color), g.name + ("  (archived)" if g.archived else ""), g.id)
        index = self.goal_combo.findData(selected)
        self.goal_combo.setCurrentIndex(index if index >= 0 else 0)
        self.goal_combo.blockSignals(False)

    # ------------------------------------------------------------ refresh

    def refresh(self) -> None:
        now = int(time.time())
        current = self.db.current_week_start()
        all_goals = self.db.goals(include_archived=True)
        self._sync_goal_combo(all_goals)

        has_data = bool(all_goals)
        self._scroll.setVisible(has_data)
        self.empty_label.setVisible(not has_data)
        if not has_data:
            return

        n_weeks = self.range_combo.currentData()
        first_week: date | None = current - timedelta(days=7 * (n_weeks - 1)) if n_weeks else None

        goal_id = self.goal_combo.currentData()
        goals = [g for g in all_goals if goal_id is None or g.id == goal_id]
        results = {
            gid: stats.since(rs, first_week)
            for gid, rs in stats.weekly_results(self.db, goals, current, now).items()
        }
        results = {gid: rs for gid, rs in results.items() if rs}
        goals = [g for g in goals if g.id in results]
        summaries = {g.id: (g, stats.summarize(results[g.id])) for g in goals}
        combined = stats.combine(results)

        start_ts = week_bounds(first_week)[0] if first_week else 0
        end_ts = week_bounds(current)[1]
        pattern = stats.patterns(self.db, start_ts, end_ts, now, {g.id for g in goals})

        color = goals[0].color if goal_id is not None and goals else ALL_GOALS_COLOR
        if goal_id is not None and goals:
            self._fill_goal_tiles(summaries[goal_id][1], results[goal_id], pattern)
        else:
            self._fill_all_tiles(results, combined, pattern)

        lines = stats.insights(summaries, combined, pattern, self.db.week_start_day)
        if not any(r.complete for r in combined):
            lines.insert(0, "Hit rates and averages appear once your first week is finished.")
        self.insights_label.setText(
            "<ul style='margin-left:-24px'>" + "".join(f"<li style='margin-bottom:4px'>{l}</li>" for l in lines) + "</ul>"
            if lines
            else "Track some time to see insights here."
        )

        self.chart_card.title.setText("Week by week" + (" (all goals combined)" if goal_id is None else ""))
        self.chart.set_data(combined, color)

        self.heatmap.set_data(pattern.grid, self.db.week_start_day, color)

    def _fill_goal_tiles(self, s: stats.Summary, results: list[stats.WeekResult], p: stats.Patterns) -> None:
        this_week = next((r for r in results if not r.complete), None)
        t = self.tiles
        t[0].set("Hit rate", _pct(s.hit_rate), f"{s.weeks_hit} of {_weeks(s.weeks_completed)} hit")
        t[1].set("Average completion", _pct(s.avg_completion), "of the weekly target")
        t[2].set("Current streak", _weeks(s.current_streak), f"best: {_weeks(s.best_streak)}")
        if this_week:
            t[3].set(
                "This week",
                _pct(this_week.completion),
                f"{format_duration(this_week.worked)} of {format_duration(this_week.target)}",
            )
        else:
            t[3].set("This week", "–", "not tracked this week")
        t[4].set("Total time", format_duration(s.total_worked), "in this range")
        t[5].set(
            "Average session",
            format_duration(p.avg_session) if p.session_count else "–",
            f"{p.session_count} sessions · longest {format_duration(p.longest_session)}",
        )

    def _fill_all_tiles(
        self,
        results: dict[int, list[stats.WeekResult]],
        combined: list[stats.WeekResult],
        p: stats.Patterns,
    ) -> None:
        flat = [r for rs in results.values() for r in rs]
        overall = stats.summarize(flat)  # hit rate and average across all goal-weeks
        this_week = next((r for r in combined if not r.complete), None)
        t = self.tiles
        t[0].set("Hit rate", _pct(overall.hit_rate), f"{overall.weeks_hit} of {overall.weeks_completed} goal-weeks hit")
        t[1].set("Average completion", _pct(overall.avg_completion), "of each goal's target")
        if this_week:
            t[2].set(
                "This week",
                _pct(this_week.completion),
                f"{format_duration(this_week.worked)} of {format_duration(this_week.target)}",
            )
        else:
            t[2].set("This week", "–", "no goals this week")
        t[3].set("Total time", format_duration(overall.total_worked), "in this range")
        t[4].set("Sessions", str(p.session_count), "in this range")
        t[5].set(
            "Average session",
            format_duration(p.avg_session) if p.session_count else "–",
            f"longest {format_duration(p.longest_session)}",
        )
