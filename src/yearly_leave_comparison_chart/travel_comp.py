from __future__ import annotations

from fedleave.charting import ComparisonChartSpec, run_comparison_chart_app

SPEC = ComparisonChartSpec(
    app_name="TravelCompYearlyComparison",
    title="Travel Comp Yearly Comparison",
    category="travel_comp",
    product="travel-comp-yearly-comparison-png",
    value_field="balance_hours",
)


def main() -> None:
    run_comparison_chart_app(SPEC)
