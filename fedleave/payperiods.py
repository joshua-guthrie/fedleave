from __future__ import annotations

from datetime import date, timedelta


DEFAULT_PAYDAY_OFFSET_DAYS = 6


def calculate_pay_date(end_date: date, payday_offset_days: int = DEFAULT_PAYDAY_OFFSET_DAYS) -> date:
    """Return the default payday for a pay period ending on ``end_date``."""
    return end_date + timedelta(days=payday_offset_days)


def pay_period_pay_date(pay_period: dict, payday_offset_days: int = DEFAULT_PAYDAY_OFFSET_DAYS) -> str | None:
    """Return explicit or backward-compatible inferred pay date for a pay period."""
    explicit = pay_period.get("pay_date")
    if explicit:
        return str(explicit)
    end_date = pay_period.get("end_date") or pay_period.get("end")
    if not end_date:
        return None
    return calculate_pay_date(date.fromisoformat(str(end_date)), payday_offset_days).isoformat()


def normalize_pay_period(pay_period: dict, payday_offset_days: int = DEFAULT_PAYDAY_OFFSET_DAYS) -> dict:
    normalized = dict(pay_period)
    pay_date = pay_period_pay_date(normalized, payday_offset_days)
    if pay_date:
        normalized["pay_date"] = pay_date
    return normalized


def generate_pay_periods(start_date: date, count: int = 26) -> list[dict[str, str]]:
    pay_periods: list[dict[str, str]] = []
    current_start = start_date
    for number in range(1, count + 1):
        current_end = current_start + timedelta(days=13)
        pay_date = calculate_pay_date(current_end)
        pay_periods.append(
            {
                "pay_period_number": number,
                "start_date": current_start.isoformat(),
                "end_date": current_end.isoformat(),
                "pay_date": pay_date.isoformat(),
                "accrual_date": current_end.isoformat(),
            }
        )
        current_start = current_end + timedelta(days=1)
    return pay_periods
