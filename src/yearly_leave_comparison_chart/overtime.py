"""Configure the overtime-worked year-over-year comparison chart."""

from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app

SPEC = ComparisonChartSpec(
    app_name="OvertimeYearlyComparison",
    title="Overtime Yearly Comparison",
    category="overtime",
    product="overtime-yearly-comparison-png",
    value_field="worked_hours",
)


def main() -> None:
    run_comparison_chart_app(SPEC)
