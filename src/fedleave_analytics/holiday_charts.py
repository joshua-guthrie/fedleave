"""Yearly calendar heatmaps for one selected Holiday Planner option.

The chart shows the whole leave year twice: existing Scheduled absence planned
after the cutoff, then the additional funded leave suggested by the selected
option. Observed nonworking holidays are highlighted in both panels.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import ceil
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from fedleave.chart_style import BACKGROUND, BLUE, BORDER, TEXT

from .charts import WIDTH

SUGGESTED = "#70AD47"
HOLIDAY = "#BF9000"
LEFT = RIGHT = 60
COLUMNS = 4
CELL = 22
GAP_X = 40
GAP_Y = 28
PANEL_GAP = 46
MONTH_TITLE_HEIGHT = 24
WEEKDAY_HEIGHT = 16
WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


def _holiday_dates(snapshot: dict[str, Any]) -> dict[date, str]:
    context = snapshot.get("calculation_context", {}) if isinstance(snapshot, dict) else {}
    entries = context.get("holidays", snapshot.get("holidays", [])) or []
    holidays: dict[date, str] = {}
    for holiday in entries:
        if not isinstance(holiday, dict) or not holiday.get("nonworking", True):
            continue
        raw = holiday.get("observed_date") or holiday.get("date") or holiday.get("display_date")
        try:
            day = date.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        holidays.setdefault(day, str(holiday.get("name") or holiday.get("label") or "Observed holiday"))
    return holidays


def _planned_values(result) -> dict[date, float]:
    values: dict[date, float] = {}
    for capacity in result.before.capacity:
        hours = float(capacity.baseline_scheduled or 0)
        if hours > 0:
            values[date.fromisoformat(capacity.date)] = hours
    return values


def _suggested_values(option) -> dict[date, float]:
    values: dict[date, float] = {}
    for capacity in option.after.capacity:
        hours = sum(float(value) for value in capacity.tentative_by_category.values())
        if hours > 0:
            values[date.fromisoformat(capacity.date)] = hours
    return values


def _months(start: date, end: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append((current.year, current.month))
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months


def _draw_legend(painter: QPainter, y: int) -> None:
    font = QFont(painter.font())
    font.setPointSize(10)
    font.setBold(False)
    painter.setFont(font)
    items = (
        (BLUE, "Planned future leave"),
        (SUGGESTED, "Suggested leave"),
        (HOLIDAY, "Observed holiday"),
    )
    x = LEFT
    for color, label in items:
        painter.fillRect(x, y, 14, 14, QColor(color))
        painter.setPen(QColor(TEXT))
        painter.drawText(x + 20, y - 3, 220, 22, Qt.AlignLeft | Qt.AlignVCenter, label)
        x += 245


def _draw_panel(
    painter: QPainter,
    *,
    top: int,
    label: str,
    values: dict[date, float],
    color: str,
    holidays: dict[date, str],
    maximum: float,
    start: date,
    end: date,
) -> int:
    font = QFont(painter.font())
    font.setPointSize(14)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(TEXT))
    painter.drawText(LEFT, top, WIDTH - 2 * LEFT, 24, Qt.AlignLeft | Qt.AlignVCenter, label)
    painter.setPen(QPen(QColor(BORDER), 1))
    painter.drawLine(LEFT, top + 28, WIDTH - RIGHT, top + 28)

    months = _months(start, end)
    grid_rows = max(1, ceil(len(months) / COLUMNS))
    month_width = CELL * 7
    slot_width = (WIDTH - LEFT - RIGHT - (COLUMNS - 1) * GAP_X) / COLUMNS
    month_height = MONTH_TITLE_HEIGHT + WEEKDAY_HEIGHT + 6 * CELL
    grid_top = top + 38

    month_font = QFont(painter.font())
    month_font.setPointSize(11)
    month_font.setBold(True)
    weekday_font = QFont(painter.font())
    weekday_font.setPointSize(7)
    weekday_font.setBold(False)
    day_font = QFont(painter.font())
    day_font.setPointSize(7)
    day_font.setBold(False)

    for index, (year, month) in enumerate(months):
        column, row_index = index % COLUMNS, index // COLUMNS
        block_x = LEFT + column * (slot_width + GAP_X) + (slot_width - month_width) / 2
        block_y = grid_top + row_index * (month_height + GAP_Y)
        month_start = date(year, month, 1)
        month_end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        grid_start = month_start - timedelta(days=month_start.weekday())

        painter.setFont(month_font)
        painter.setPen(QColor(TEXT))
        painter.drawText(
            int(block_x),
            int(block_y),
            int(month_width),
            20,
            Qt.AlignLeft | Qt.AlignVCenter,
            month_start.strftime("%b %Y"),
        )
        painter.setFont(weekday_font)
        for weekday_index, weekday in enumerate(WEEKDAYS):
            painter.drawText(
                int(block_x + weekday_index * CELL),
                int(block_y + MONTH_TITLE_HEIGHT - 4),
                CELL,
                WEEKDAY_HEIGHT,
                Qt.AlignCenter,
                weekday,
            )

        painter.setFont(day_font)
        for day_in_month in range(1, month_end.day + 1):
            day = date(year, month, day_in_month)
            if not start <= day <= end:
                continue
            x = int(block_x + day.weekday() * CELL)
            y = int(block_y + MONTH_TITLE_HEIGHT + WEEKDAY_HEIGHT + ((day - grid_start).days // 7) * CELL)
            value = values.get(day, 0.0)
            holiday = day in holidays
            if value > 0:
                fill = QColor(color)
                fill.setAlphaF(0.2 + 0.8 * min(1.0, value / maximum))
            elif holiday:
                fill = QColor(HOLIDAY)
                fill.setAlphaF(0.3)
            else:
                fill = QColor(BACKGROUND)
            painter.fillRect(x, y, CELL - 2, CELL - 2, fill)
            painter.setPen(QPen(QColor(HOLIDAY if holiday else BORDER), 2 if holiday else 1))
            painter.drawRect(x, y, CELL - 2, CELL - 2)

    return grid_top + grid_rows * month_height + max(0, grid_rows - 1) * GAP_Y


def render_holiday_option(snapshot, result, selected):
    """Render planned and suggested absence as separate yearly heatmaps."""
    option = result.candidates[selected]
    start = date.fromisoformat(str(snapshot["leave_year_start"]))
    end = date.fromisoformat(str(snapshot["leave_year_end"]))
    holidays = _holiday_dates(snapshot)
    planned = _planned_values(result)
    suggested = _suggested_values(option)
    maximum = max([1.0, *planned.values(), *suggested.values()])

    header_top, panel_one_top = 0, 148
    months = _months(start, end)
    grid_rows = max(1, ceil(len(months) / COLUMNS))
    month_height = MONTH_TITLE_HEIGHT + WEEKDAY_HEIGHT + 6 * CELL
    panel_height = 38 + grid_rows * month_height + max(0, grid_rows - 1) * GAP_Y
    caption_height = 160
    height = panel_one_top + 2 * panel_height + PANEL_GAP + caption_height + 20

    image = QPixmap(WIDTH, height)
    image.fill(QColor(BACKGROUND))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        font = QFont(painter.font())
        font.setPointSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        painter.drawText(
            40,
            header_top + 18,
            WIDTH - 80,
            44,
            Qt.AlignCenter,
            "Holiday and Weekend Planner — planned and suggested leave",
        )
        font.setPointSize(12)
        font.setBold(False)
        painter.setFont(font)
        metrics = option.metrics
        painter.drawText(
            40,
            header_top + 70,
            WIDTH - 80,
            28,
            Qt.AlignCenter,
            f"{metrics['start']} through {metrics['end']} | {metrics['calendar_days']} calendar days away | "
            f"{metrics['additional_hours']:g} additional hours | {metrics['state']} | {metrics['label']}",
        )
        _draw_legend(painter, header_top + 108)

        panel_one_bottom = _draw_panel(
            painter,
            top=panel_one_top,
            label="Planned future leave (existing Scheduled after cutoff)",
            values=planned,
            color=BLUE,
            holidays=holidays,
            maximum=maximum,
            start=start,
            end=end,
        )
        panel_two_top = panel_one_bottom + PANEL_GAP
        panel_two_bottom = _draw_panel(
            painter,
            top=panel_two_top,
            label="Suggested leave (selected option; not booked)",
            values=suggested,
            color=SUGGESTED,
            holidays=holidays,
            maximum=maximum,
            start=start,
            end=end,
        )

        font.setPointSize(11)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        parameters = result.parameters
        caption = (
            f"Cutoff {parameters.cutoff}; eligible categories: "
            f"{', '.join(parameters.eligible_categories) or 'none'}; reserves (h): {parameters.reserves}; "
            f"standard day: {metrics['standard_day_hours']} h. {result.assumptions['roster_assumption']} "
            f"Search-boundary truncation: {metrics['boundary_truncated']}. "
            f"Cached holiday years: {result.assumptions['holiday_coverage']}; "
            f"holidays enabled: {result.assumptions['holidays_enabled']}. "
            "Cell darkness is hours on that date; holiday cells have a gold border. "
            "Existing rows are Scheduled; suggested funding is a scenario, not booked leave. "
            "See exact daily and balance tables."
        )
        painter.drawText(
            LEFT,
            panel_two_bottom + 18,
            WIDTH - 2 * LEFT,
            caption_height - 20,
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            caption,
        )
    finally:
        painter.end()
    return image
