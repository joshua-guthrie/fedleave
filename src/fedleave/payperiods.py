"""Generate federal biweekly pay periods and their associated pay dates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

DEFAULT_PAYDAY_OFFSET_DAYS = 6


def calculate_pay_date(end_date: date, payday_offset_days: int = DEFAULT_PAYDAY_OFFSET_DAYS) -> date:
    """Return the default payday for a pay period ending on ``end_date``."""
    return end_date + timedelta(days=payday_offset_days)


def pay_period_pay_date(
    pay_period: Mapping[str, object],
    payday_offset_days: int = DEFAULT_PAYDAY_OFFSET_DAYS,
) -> str | None:
    """Return explicit or backward-compatible inferred pay date for a pay period."""
    explicit = pay_period.get("pay_date")
    if explicit:
        return str(explicit)
    end_date = pay_period.get("end_date") or pay_period.get("end")
    if not end_date:
        return None
    return calculate_pay_date(date.fromisoformat(str(end_date)), payday_offset_days).isoformat()


def normalize_pay_period(
    pay_period: Mapping[str, object],
    payday_offset_days: int = DEFAULT_PAYDAY_OFFSET_DAYS,
) -> dict[str, object]:
    """Copy a pay-period record and add a backward-compatible pay date."""
    normalized = dict(pay_period)
    pay_date = pay_period_pay_date(normalized, payday_offset_days)
    if pay_date:
        normalized["pay_date"] = pay_date
    return normalized


def generate_pay_periods(start_date: date, count: int = 26) -> list[dict[str, str | int]]:
    """Generate consecutive 14-day pay periods beginning at ``start_date``."""
    pay_periods: list[dict[str, str | int]] = []
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


def leave_year_period_count(start: date, year: int) -> int:
    """Count biweekly starts before the next calendar year on this schedule.

    January schedules naturally include the occasional 27-period leave year.
    Agencies with a December boundary can explicitly select 26/27 periods.
    """
    if start.year != year:
        raise ValueError("UNSUPPORTED_PAY_PERIODS: specify --pay-periods for a non-January schedule")
    count = ((date(year + 1, 1, 1) - start).days + 13) // 14
    if count not in {26, 27}:
        raise ValueError("UNSUPPORTED_PAY_PERIODS: schedule must contain 26 or 27 periods")
    return count


def validate_pay_periods(leave_year: dict[str, Any]) -> None:
    """Reject inconsistent numbering, boundaries, gaps and overlaps."""
    periods = leave_year.get("pay_periods", [])
    count = leave_year.get("pay_period_count", len(periods))
    if count not in {26, 27} or len(periods) != count:
        raise ValueError("UNSUPPORTED_PAY_PERIODS: expected 26 or 27 complete pay periods")
    expected = date.fromisoformat(leave_year["leave_year_start"])
    for number, period in enumerate(periods, 1):
        end = expected + timedelta(days=13)
        if (
            period.get("start_date") != expected.isoformat()
            or period.get("end_date") != end.isoformat()
            or period.get("pay_period_number") != number
        ):
            raise ValueError(f"SOURCE_NOT_CONTIGUOUS: invalid pay period {number}")
        accrual = date.fromisoformat(str(period.get("accrual_date") or end.isoformat()))
        if not expected <= accrual <= end:
            raise ValueError(f"UNSUPPORTED_PAY_PERIODS: accrual outside period {number}")
        expected = end + timedelta(days=1)
    if leave_year["leave_year_end"] != (expected - timedelta(days=1)).isoformat():
        raise ValueError("SOURCE_NOT_CONTIGUOUS: leave-year end disagrees with pay periods")
