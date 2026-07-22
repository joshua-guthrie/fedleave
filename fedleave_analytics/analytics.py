from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from math import ceil
from typing import Any

ACTIVE_STATUSES = {"planned", "requested", "approved", "reconciled", "completed", "active"}
EXCLUDED_STATUSES = {"denied", "cancelled", "voided", "deleted"}
EPSILON = 1e-9


def _hours(transaction: dict[str, Any]) -> float:
    try:
        return abs(float(transaction.get("hours", 0)))
    except (TypeError, ValueError):
        return 0.0


def _date(transaction: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(transaction.get("date", "")))
    except ValueError:
        return None


def _included(transaction: dict[str, Any]) -> bool:
    if transaction.get("void") or _hours(transaction) <= EPSILON:
        return False
    return str(transaction.get("status", "")).lower() not in EXCLUDED_STATUSES


def _split(rows: list[dict[str, Any]], today: date) -> tuple[float, float]:
    past = sum(_hours(row) for row in rows if (_date(row) or today) <= today)
    return past, sum(_hours(row) for row in rows) - past


def analyze_leave_year(payload: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Return normalized, read-only analytics for one ``list --json`` payload.

    The result intentionally contains plain JSON-compatible values so it can be
    used by both the Qt application and tests without importing Qt.
    """
    today = today or date.today()
    start = date.fromisoformat(str(payload["leave_year_start"]))
    end = date.fromisoformat(str(payload["leave_year_end"]))
    transactions = [t for t in payload.get("transactions", []) if isinstance(t, dict) and _included(t)]
    transactions = [t for t in transactions if start <= (_date(t) or start) <= end]
    absence = [t for t in transactions if t.get("direction") == "used"]
    categories = sorted({str(t.get("category", "")) for t in transactions if _hours(t) > EPSILON})

    def period_rows(key: Any) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in absence:
            grouped[str(key(row))].append(row)
        return {name: {"through_today": _split(rows, today)[0], "future_scheduled": _split(rows, today)[1],
                       "full_leave_year": sum(_hours(r) for r in rows)} for name, rows in grouped.items()}

    months = []
    cursor = start.replace(day=1)
    while cursor <= end:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        rows = [r for r in absence if cursor <= (_date(r) or cursor) <= min(month_end, end)]
        past, future = _split(rows, today)
        months.append({"month": cursor.isoformat()[:7], "through_today": past, "future_scheduled": future,
                       "full_leave_year": past + future})
        cursor = (month_end + timedelta(days=1)).replace(day=1)

    weekdays = {calendar.day_name[i]: {"through_today": 0.0, "future_scheduled": 0.0, "full_leave_year": 0.0} for i in range(7)}
    for name, values in period_rows(lambda r: (_date(r) or start).weekday()).items():
        weekdays[calendar.day_name[int(name)]] = values
    pay_periods = payload.get("pay_periods", [])
    pay_period_rows = []
    for index, period in enumerate(pay_periods, 1):
        period_start = date.fromisoformat(str(period.get("start_date", period.get("start"))))
        period_end = date.fromisoformat(str(period.get("end_date", period.get("end"))))
        rows = [r for r in absence if period_start <= (_date(r) or period_start) <= period_end]
        past, future = _split(rows, today)
        pay_period_rows.append({"pay_period": int(period.get("pay_period_number", index)), "start_date": period_start.isoformat(),
                                "end_date": period_end.isoformat(), "through_today": past, "future_scheduled": future,
                                "full_leave_year": past + future})

    daily = []
    current = start
    while current <= end:
        rows = [r for r in absence if _date(r) == current]
        past, future = _split(rows, today)
        daily.append({"date": current.isoformat(), "weekday": current.strftime("%A"), "through_today": past,
                      "future_scheduled": future, "full_day_total": past + future,
                      "categories": ", ".join(sorted({str(r.get("category", "")) for r in rows}))})
        current += timedelta(days=1)

    lifecycle = {}
    for category in ("overtime", "comp"):
        lifecycle[category] = {}
        for direction in ("worked", "earned", "used", "paid_out", "forfeited", "expired"):
            rows = [r for r in transactions if r.get("category") == category and r.get("direction") == direction]
            past, future = _split(rows, today)
            lifecycle[category][direction] = {"through_today": past, "future_scheduled": future, "full_leave_year": past + future}
    total_absence = sum(_hours(r) for r in absence)
    final_days = ceil(((end - start).days + 1) / 4)
    final_start = end - timedelta(days=final_days - 1)
    final_hours = sum(_hours(r) for r in absence if (_date(r) or start) >= final_start)
    return {"year": payload.get("year", payload.get("leave_year")), "leave_year_start": start.isoformat(),
            "leave_year_end": end.isoformat(), "visible_categories": categories, "months": months,
            "weekdays": weekdays, "pay_periods": pay_period_rows, "heatmap": daily,
            "lifecycle": lifecycle, "final_quarter": {"start_date": final_start.isoformat(), "end_date": end.isoformat(),
            "hours": final_hours, "percentage": None if total_absence <= EPSILON else final_hours / total_absence * 100,
            "total_hours": total_absence}}
