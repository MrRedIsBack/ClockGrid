"""Charts for the Stats tab: weekly target-vs-actual and a when-you-work heatmap."""

from __future__ import annotations

from datetime import timedelta

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from clockgrid.stats import WeekResult
from clockgrid.weeks import WEEKDAY_NAMES, format_duration


def _ink(widget: QWidget, muted: bool = False) -> QColor:
    color = QColor(widget.palette().color(QPalette.ColorRole.WindowText))
    if muted:
        color.setAlpha(150)
    return color


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


class WeeklyChart(QChartView):
    """Bars for time worked each week, with the target as a dashed line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(260)
        self.setStyleSheet("background: transparent;")
        self._results: list[WeekResult] = []

    def set_data(self, results: list[WeekResult], color: str) -> None:
        self._results = results
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(4, 4, 4, 4))
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

        bars = QBarSet("Worked")
        bars.setColor(QColor(color))
        bars.setBorderColor(QColor(color))
        target_line = QLineSeries()
        target_line.setName("Target")
        pen = QPen(_ink(self, muted=True), 2, Qt.PenStyle.DashLine)
        target_line.setPen(pen)

        labels = []
        top = 1.0
        for i, r in enumerate(results):
            hours = r.worked / 3600
            target = r.target / 3600
            bars.append(hours)
            target_line.append(QPointF(i, target))
            top = max(top, hours, target)
            label = f"{r.week_start:%b} {r.week_start.day}"
            labels.append(label + ("*" if not r.complete else ""))
        # A one-week target line would be a single invisible point; widen it across the bar.
        if len(results) == 1:
            target_line.clear()
            t = results[0].target / 3600
            target_line.append(QPointF(-0.4, t))
            target_line.append(QPointF(0.4, t))

        series = QBarSeries()
        series.setBarWidth(0.6)
        series.append(bars)
        chart.addSeries(series)
        chart.addSeries(target_line)

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        axis_y = QValueAxis()
        axis_y.setRange(0, top * 1.1)
        axis_y.setTickCount(5)
        axis_y.applyNiceNumbers()  # round ticks to e.g. 0, 10, 20, 30
        axis_y.setLabelFormat("%.0f h" if axis_y.max() >= 4 else "%.1f h")
        for axis in (axis_x, axis_y):
            axis.setLabelsColor(_ink(self, muted=True))
            axis.setLinePen(QPen(Qt.PenStyle.NoPen))
            grid = QColor(_ink(self))
            grid.setAlpha(30)
            axis.setGridLinePen(QPen(grid, 1))
        axis_x.setGridLineVisible(False)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        for s in (series, target_line):
            s.attachAxis(axis_x)
            s.attachAxis(axis_y)

        legend = chart.legend()
        legend.setAlignment(Qt.AlignmentFlag.AlignTop)
        legend.setLabelColor(_ink(self))

        bars.hovered.connect(self._show_tooltip)
        self.setChart(chart)

    def _show_tooltip(self, status: bool, index: int) -> None:
        if not status or not 0 <= index < len(self._results):
            QToolTip.hideText()
            return
        r = self._results[index]
        end = r.week_start + timedelta(days=6)
        state = "in progress" if not r.complete else ("✓ hit" if r.hit else "✗ missed")
        QToolTip.showText(
            QCursor.pos(),
            f"<b>{r.week_start:%b} {r.week_start.day} – {end:%b} {end.day}</b><br>"
            f"{format_duration(r.worked)} of {format_duration(r.target)} "
            f"({round(r.completion * 100)}%)<br>{state}",
            self,
        )


class Heatmap(QWidget):
    """Time spent per weekday and hour; darker cells mean more time."""

    LEFT = 40
    TOP = 20
    GAP = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid = [[0] * 24 for _ in range(7)]
        self.start_day = 0
        self.color = QColor("#4f8cff")
        self.setMouseTracking(True)
        self.setMinimumHeight(7 * 22 + self.TOP + 4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(640, 7 * 24 + self.TOP + 4)

    def set_data(self, grid: list[list[int]], start_day: int, color: str) -> None:
        self.grid = grid
        self.start_day = start_day
        self.color = QColor(color)
        self.update()

    def _cell_size(self) -> tuple[float, float]:
        w = (self.width() - self.LEFT) / 24
        h = (self.height() - self.TOP) / 7
        return w, h

    def _day_for_row(self, row: int) -> int:
        return (self.start_day + row) % 7

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw, ch = self._cell_size()
        peak = max((v for row in self.grid for v in row), default=0)
        surface = self.palette().color(QPalette.ColorRole.Base)
        empty = QColor(_ink(self))
        empty.setAlpha(18)

        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * 0.85)
        p.setFont(font)
        p.setPen(_ink(self, muted=True))
        for h in range(0, 24, 3):
            p.drawText(
                QRectF(self.LEFT + h * cw, 0, cw * 3, self.TOP - 4),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                f"{h:02d}",
            )
        for row in range(7):
            p.setPen(_ink(self, muted=True))
            p.drawText(
                QRectF(0, self.TOP + row * ch, self.LEFT - 6, ch),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                WEEKDAY_NAMES[self._day_for_row(row)][:3],
            )
            day = self._day_for_row(row)
            for h in range(24):
                value = self.grid[day][h]
                rect = QRectF(
                    self.LEFT + h * cw + self.GAP / 2,
                    self.TOP + row * ch + self.GAP / 2,
                    cw - self.GAP,
                    ch - self.GAP,
                )
                if value and peak:
                    t = 0.18 + 0.82 * (value / peak)  # keep the faintest non-zero cell visible
                    fill = QColor(
                        round(surface.red() + (self.color.red() - surface.red()) * t),
                        round(surface.green() + (self.color.green() - surface.green()) * t),
                        round(surface.blue() + (self.color.blue() - surface.blue()) * t),
                    )
                else:
                    fill = empty
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawRoundedRect(rect, 3, 3)
        p.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        cw, ch = self._cell_size()
        pos = event.position()
        col = int((pos.x() - self.LEFT) // cw)
        row = int((pos.y() - self.TOP) // ch)
        if 0 <= col < 24 and 0 <= row < 7:
            day = self._day_for_row(row)
            value = self.grid[day][col]
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"<b>{WEEKDAY_NAMES[day]} {col:02d}:00–{(col + 1) % 24:02d}:00</b><br>"
                f"{format_duration(value) if value else 'No time logged'}",
                self,
            )
        else:
            QToolTip.hideText()
