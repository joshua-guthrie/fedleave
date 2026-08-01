"""Configure the annual-leave year-over-year comparison chart."""

from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app

SPEC = ComparisonChartSpec(
    app_name="AnnualLeaveYearlyComparison",
    title="Annual Leave Yearly Comparison",
    category="annual",
    product="annual-leave-yearly-comparison-png",
    value_field="balance_hours",
    y_rounding=50,
)


def main() -> None:
    run_comparison_chart_app(SPEC)
