from __future__ import annotations

from fedleave.charting import LeaveChartSpec, run_chart_app

SPEC = LeaveChartSpec(
    app_name="CreditHoursChartForTheYear",
    title="Credit Hours",
    category="credit",
    product="credit-hours-chart-png",
)


def main() -> None:
    run_chart_app(SPEC)
