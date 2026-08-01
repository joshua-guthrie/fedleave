from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app


SPEC = ComparisonChartSpec(
    app_name="CompTimeYearlyComparison",
    title="Comp Time Yearly Comparison",
    category="comp",
    product="comp-time-yearly-comparison-png",
    value_field="balance_hours",
)


def main() -> None:
    run_comparison_chart_app(SPEC)
