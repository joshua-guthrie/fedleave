"""Break timeline and length distribution over exact, already-calculated rows."""

from datetime import date

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from fedleave.chart_style import BACKGROUND, BLUE, BORDER, GRID_MAJOR, RED, TEXT

from .break_model import group_label
from .charts import WIDTH, render_horizontal_bar_chart
from .seasonality import LABELS


def _caption(result):
    holidays = "; ".join(
        f"{row['year']}: "
        + (
            "disabled"
            if not row.get("holidays_enabled", True)
            else "cached " + (", ".join(str(year) for year in row.get("holiday_coverage", [])) or "none")
        )
        for row in result.coverage
        if row["selected"]
    )
    return (
        f"Selected: {', '.join(LABELS.get(category, category) for category in result.categories)}. "
        f"Substantial: at least {result.parameters.substantial_workdays} fully absent scheduled workdays; an analysis threshold, not an employment rule. "
        f"Covered / unknown recorded dates: {result.summary['covered_recorded_days']} / {result.summary['unknown_recorded_days']}. Holiday context: {holidays}. "
        "Provisional lengths are ongoing/truncated observed lower bounds. Recorded dates do not establish attendance. "
        + (
            "Current regular schedule is assumed where historical rosters are unavailable; see exact source ranges in Coverage."
            if result.parameters.assume_current_schedule
            else "Backend historical rosters only; missing schedule/holiday context stays N/A."
        )
    )


def render_break_distribution(result):
    if result.summary["covered_recorded_days"]:
        graphic = render_horizontal_bar_chart(
            f"Break lengths — {group_label(result.parameters)} — cutoff {result.parameters.cutoff}",
            list(result.distribution),
            "label",
            [
                ("completed_count", "Completed (bounded)"),
                ("incomplete_count", "Provisional lengths"),
            ],
        )
        image = QPixmap(WIDTH, graphic.height() + 180)
        image.fill(QColor(BACKGROUND))
        painter = QPainter(image)
        painter.drawPixmap(0, 0, graphic)
        font = QFont(painter.font())
        font.setPointSize(13)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        painter.drawText(50, graphic.height() + 5, WIDTH - 100, 165, Qt.AlignCenter | Qt.TextWordWrap, _caption(result))
        painter.end()
        return image
    image = QPixmap(WIDTH, 550)
    image.fill(QColor(BACKGROUND))
    painter = QPainter(image)
    painter.setPen(QColor(TEXT))
    font = QFont(painter.font())
    font.setPointSize(20)
    painter.setFont(font)
    painter.drawText(
        80,
        80,
        WIDTH - 160,
        380,
        Qt.AlignCenter | Qt.TextWordWrap,
        "Break-length distribution: N/A\nConfirm usage coverage and review schedule/holiday context. Unknown history is missing, not zero.\n"
        + _caption(result),
    )
    painter.end()
    return image


def render_break_timeline(result):
    recorded, upcoming = list(result.recorded), list(result.upcoming)
    height = max(680, 370 + 34 * (len(recorded) + len(upcoming) + 4))
    image = QPixmap(WIDTH, height)
    image.fill(QColor(BACKGROUND))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    first, last = date.fromisoformat(result.daily[0]["date"]), date.fromisoformat(result.daily[-1]["date"])
    left, right = 290, WIDTH - 50

    def x(day):
        return left + (date.fromisoformat(day) - first).days / max(1, (last - first).days) * (right - left)

    try:
        font = QFont(painter.font())
        font.setPointSize(21)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        painter.drawText(30, 15, WIDTH - 60, 45, Qt.AlignCenter, "Break timeline — " + group_label(result.parameters))
        font.setPointSize(13)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(
            40,
            65,
            WIDTH - 80,
            85,
            Qt.AlignCenter | Qt.TextWordWrap,
            f"Cutoff {result.parameters.cutoff} | Substantial: at least {result.parameters.substantial_workdays} fully absent scheduled workdays | Selected: {', '.join(LABELS.get(category, category) for category in result.categories)}",
        )
        y = 170
        for label, rows, color, style, prefix in (
            ("Recorded Through Cutoff", recorded, BLUE, Qt.SolidLine, "R"),
            ("Upcoming — Scheduled", upcoming, RED, Qt.DashLine, "S"),
        ):
            painter.setPen(QColor(TEXT))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(35, y, WIDTH - 70, 30, Qt.AlignLeft, label)
            font.setBold(False)
            painter.setFont(font)
            y += 35
            if not rows:
                painter.drawText(
                    45,
                    y,
                    WIDTH - 90,
                    28,
                    Qt.AlignLeft,
                    "No entered full-day scheduled intervals"
                    if prefix == "S"
                    else "No full-day intervals in covered history"
                    if result.summary["covered_recorded_days"]
                    else "N/A: no covered recorded history",
                )
                y += 34
            for i, row in enumerate(rows, 1):
                painter.setPen(QColor(TEXT))
                marker = "*" if row["substantial"] else ""
                boundary = " [boundary]" if row["incomplete_start"] or row["incomplete_end"] else ""
                label_font = QFont(font)
                label_font.setPointSize(11)
                painter.setFont(label_font)
                label = f"{prefix}{i}{marker}{boundary}: {row['fully_absent_workdays']} workdays, {row['selected_hours']:g} h"
                if row.get("continuation_of"):
                    label = f"{prefix}{i}{marker}: {row['scheduled_workdays']} scheduled + {row['recorded_workdays']} recorded"
                painter.drawText(
                    35,
                    y - 4,
                    250,
                    30,
                    Qt.AlignLeft | Qt.AlignVCenter,
                    label,
                )
                painter.setFont(font)
                painter.setPen(QPen(QColor(color), 2, style))
                fill = QColor(color)
                fill.setAlpha(140 if row["substantial"] else 65)
                painter.setBrush(fill)
                painter.drawRect(round(x(row["start"])), y, max(3, round(x(row["end"]) - x(row["start"]))), 20)
                painter.setPen(QPen(QColor(GRID_MAJOR), 1, Qt.DotLine))
                painter.drawLine(QPointF(left, y + 28), QPointF(right, y + 28))
                y += 34
            y += 15
        painter.setPen(QPen(QColor(BORDER), 2))
        painter.drawLine(left, y, right, y)
        painter.setPen(QColor(TEXT))
        for i in range(6):
            from datetime import timedelta

            stamp = first + timedelta(days=round((last - first).days * i / 5))
            painter.drawText(
                round(left + (right - left) * i / 5) - 80, y + 10, 160, 28, Qt.AlignCenter, stamp.isoformat()
            )
        painter.setPen(QPen(QColor(TEXT), 2, Qt.DotLine))
        painter.drawLine(QPointF(x(result.parameters.cutoff), 160), QPointF(x(result.parameters.cutoff), y))
        painter.setPen(QColor(TEXT))
        painter.drawText(
            45,
            height - 170,
            WIDTH - 90,
            160,
            Qt.AlignCenter | Qt.TextWordWrap,
            "* Meets the selected threshold, including the linked recorded portion of a Scheduled continuation. Dashed red bars are Scheduled. Exact dates, hours and IDs are in the data table. "
            + _caption(result),
        )
    finally:
        painter.end()
    return image
