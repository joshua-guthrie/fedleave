"""Selected option hours with exact supporting daily data and scope."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from fedleave.chart_style import BACKGROUND, TEXT

from .charts import WIDTH, render_horizontal_bar_chart


def render_holiday_option(result, selected):
    option = result.candidates[selected]
    rows = [dict(r, label=r["date"]) for r in option.days]
    chart = render_horizontal_bar_chart(
        "Holiday and Weekend Planner — proposed option",
        rows,
        "label",
        [
            ("existing_discretionary_hours", "Existing discretionary (h)"),
            ("existing_other_hours", "Other purpose (h)"),
            ("proposed_hours", "Proposed additional (h)"),
        ],
        height=max(900, 240 + 90 * len(rows)),
    )
    image = QPixmap(WIDTH, chart.height() + 210)
    image.fill(QColor(BACKGROUND))
    painter = QPainter(image)
    painter.drawPixmap(0, 0, chart)
    font = QFont(painter.font())
    font.setPointSize(13)
    painter.setFont(font)
    painter.setPen(QColor(TEXT))
    m, p = option.metrics, result.parameters
    caption = (
        f"{m['start']} through {m['end']} | {m['calendar_days']} calendar days away | {m['additional_hours']:g} additional hours | {m['state']} | {m['label']}. "
        f"Cutoff {p.cutoff}; eligible categories: {', '.join(p.eligible_categories) or 'none'}; reserves (h): {p.reserves}; standard day: {m['standard_day_hours']} h. "
        f"{result.assumptions['roster_assumption']} Search-boundary truncation: {m['boundary_truncated']}. "
        f"Cached holiday years: {result.assumptions['holiday_coverage']}; holidays enabled: {result.assumptions['holidays_enabled']}. "
        "Existing rows are Scheduled; proposed funding is a scenario, not booked leave. See exact daily and balance tables."
    )
    painter.drawText(45, chart.height() + 5, WIDTH - 90, 195, Qt.AlignCenter | Qt.TextWordWrap, caption)
    painter.end()
    return image
