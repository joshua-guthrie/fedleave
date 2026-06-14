from __future__ import annotations

from datetime import date, timedelta


def generate_pay_periods(start_date: date, count: int = 26) -> list[dict[str, str]]:
    pay_periods: list[dict[str, str]] = []
    current_start = start_date
    for number in range(1, count + 1):
        current_end = current_start + timedelta(days=13)
        pay_periods.append(
            {
                "pay_period_number": number,
                "start_date": current_start.isoformat(),
                "end_date": current_end.isoformat(),
                "accrual_date": current_end.isoformat(),
            }
        )
        current_start = current_end + timedelta(days=1)
    return pay_periods
