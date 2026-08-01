"""Configure and launch the shared renderer for compensatory time."""

from __future__ import annotations

from fedleave.charting import LeaveChartSpec, run_chart_app

SPEC = LeaveChartSpec(
    app_name="CompTimeChartForTheYear",
    title="Comp Time",
    category="comp",
    product="comp-time-chart-png",
)


def main() -> None:
    run_chart_app(SPEC)
