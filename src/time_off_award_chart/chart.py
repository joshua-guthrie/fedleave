from __future__ import annotations

from fedleave.charting import LeaveChartSpec, run_chart_app

SPEC = LeaveChartSpec(
    app_name="TimeOffAwardChartForTheYear",
    title="Time Off Award",
    category="time_off_award",
    product="time-off-award-chart-png",
)


def main() -> None:
    run_chart_app(SPEC)
