"""Configure the time-off-award year-over-year comparison chart."""

from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app

SPEC = ComparisonChartSpec(
    app_name="TimeOffAwardYearlyComparison",
    title="Time Off Award Yearly Comparison",
    category="time_off_award",
    product="time-off-award-yearly-comparison-png",
    value_field="balance_hours",
)


def main() -> None:
    run_comparison_chart_app(SPEC)
