from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app

SPEC = ComparisonChartSpec(
    app_name="SickLeaveYearlyComparison",
    title="Sick Leave Yearly Comparison",
    category="sick",
    product="sick-leave-yearly-comparison-png",
    value_field="balance_hours",
    y_rounding=50,
)


def main() -> None:
    run_comparison_chart_app(SPEC)
