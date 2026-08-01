from __future__ import annotations

from fedleave.charting import LeaveChartSpec, run_chart_app

SPEC = LeaveChartSpec(
    app_name="TravelCompChartForTheYear",
    title="Travel Comp",
    category="travel_comp",
    product="travel-comp-chart-png",
)


def main() -> None:
    run_chart_app(SPEC)
