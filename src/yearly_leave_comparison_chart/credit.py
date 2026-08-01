from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app

SPEC = ComparisonChartSpec(
    app_name="CreditHoursYearlyComparison",
    title="Credit Hours Yearly Comparison",
    category="credit",
    product="credit-hours-yearly-comparison-png",
    value_field="balance_hours",
)


def main() -> None:
    run_comparison_chart_app(SPEC)
