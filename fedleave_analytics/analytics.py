from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from math import ceil
from typing import Any, Callable


EXCLUDED_STATUSES = {"denied", "cancelled", "voided", "deleted"}
BALANCE_INCREASING_DIRECTIONS = {"earned", "restored", "adjusted", "corrected", "reconciled"}
BALANCE_DECREASING_DIRECTIONS = {"used", "paid_out", "forfeited", "expired"}
COMP_DISPOSAL_DIRECTIONS = {"used", "paid_out", "forfeited", "expired"}
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
    through_today = sum(_hours(row) for row in rows if (_date(row) or today) <= today)
    return through_today, sum(_hours(row) for row in rows) - through_today


def _time_values(rows: list[dict[str, Any]], today: date) -> dict[str, float]:
    through_today, future = _split(rows, today)
    return {
        "through_today": through_today,
        "future_scheduled": future,
        "full_leave_year": through_today + future,
    }


def _month_starts(start: date, end: date) -> list[date]:
    result: list[date] = []
    cursor = start.replace(day=1)
    while cursor <= end:
        result.append(cursor)
        cursor = (date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1]) + timedelta(days=1))
    return result


def _month_label(month: date) -> str:
    return month.strftime("%b %Y")


def _transaction_detail(row: dict[str, Any], today: date) -> dict[str, Any]:
    transaction_date = _date(row)
    return {
        "date": transaction_date.isoformat() if transaction_date else "",
        "category": str(row.get("category", "")),
        "direction": str(row.get("direction", "")),
        "hours": _hours(row),
        "status": str(row.get("status", "")),
        "timing": "Future Scheduled" if transaction_date and transaction_date > today else "Through Today",
        "description": str(row.get("description", "")),
        "source": str(row.get("source", "")),
        "transaction_id": str(row.get("id", "")),
        "earned_transaction_id": str(row.get("earned_transaction_id") or ""),
    }


def _group_rows(
    rows: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _visible_categories(payload: dict[str, Any], transactions: list[dict[str, Any]]) -> list[str]:
    supplied = payload.get("visible_categories")
    if isinstance(supplied, list):
        return sorted({str(category) for category in supplied if str(category)})

    visible: set[str] = set()
    for field in ("starting_balances", "carryover_from_previous_year"):
        values = payload.get(field, {})
        if isinstance(values, dict):
            for category, value in values.items():
                try:
                    if abs(float(value)) > EPSILON:
                        visible.add(str(category))
                except (TypeError, ValueError):
                    continue
    visible.update(str(row.get("category", "")) for row in transactions if _hours(row) > EPSILON)
    return sorted(category for category in visible if category)


def _comp_lots(
    transactions: list[dict[str, Any]],
    today: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    earned = [
        row for row in transactions
        if row.get("category") == "comp" and row.get("direction") == "earned"
    ]
    linked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    allocations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for row in transactions:
        if row.get("category") != "comp" or row.get("direction") not in COMP_DISPOSAL_DIRECTIONS:
            continue
        earned_id = str(row.get("earned_transaction_id") or "")
        if earned_id:
            linked[earned_id].append(row)
            earned_row = next((candidate for candidate in earned if str(candidate.get("id")) == earned_id), None)
            allocations.append({
                "event_date": str(row.get("date", "")),
                "event_type": str(row.get("direction", "")),
                "hours": _hours(row),
                "earned_lot_date": str(earned_row.get("date", "")) if earned_row else "N/A",
                "expiration_date": str((earned_row or row).get("expiration_date") or "N/A"),
                "allocation_method": str(row.get("allocation_method") or "Explicit"),
                "transaction_id": str(row.get("id", "")),
            })
            if earned_row is None:
                warnings.append({
                    "severity": "Warning",
                    "area": "Comp allocation",
                    "date_or_lot": earned_id,
                    "message": "Referenced earned comp lot was not found.",
                })
        elif row.get("direction") == "used":
            warnings.append({
                "severity": "Information",
                "area": "Comp allocation",
                "date_or_lot": str(row.get("date", "")),
                "message": "Historical comp use is not linked to an earned lot.",
            })

    lots: list[dict[str, Any]] = []
    for lot in earned:
        lot_id = str(lot.get("id", ""))
        lot_date = _date(lot)
        original = _hours(lot)
        events = linked.get(lot_id, [])
        totals = {
            direction: sum(_hours(event) for event in events if event.get("direction") == direction)
            for direction in COMP_DISPOSAL_DIRECTIONS
        }
        today_events = [event for event in events if (_date(event) or today) <= today]
        today_disposed = sum(_hours(event) for event in today_events)
        projected_disposed = sum(totals.values())
        remaining_today = max(0.0, original - today_disposed)
        projected_remaining = max(0.0, original - projected_disposed)
        expiration_text = str(lot.get("expiration_date") or "N/A")
        expiration = None
        if expiration_text != "N/A":
            try:
                expiration = date.fromisoformat(expiration_text)
            except ValueError:
                warnings.append({
                    "severity": "Warning",
                    "area": "Comp lot",
                    "date_or_lot": lot_id,
                    "message": f"Invalid expiration date: {expiration_text}.",
                })
        if remaining_today <= EPSILON:
            status = "Closed"
        elif expiration:
            days_remaining = (expiration - today).days
            status = "Expired" if days_remaining < 0 else f"Expires in {days_remaining} days"
        else:
            status = "Open; expiration unavailable"
        if projected_disposed - original > EPSILON:
            warnings.append({
                "severity": "Error",
                "area": "Comp lot",
                "date_or_lot": lot_id,
                "message": "Lot is over-allocated.",
            })
        lots.append({
            "earned_date": lot_date.isoformat() if lot_date else "N/A",
            "original": original,
            "used": totals["used"],
            "paid_out": totals["paid_out"],
            "forfeited": totals["forfeited"],
            "expired": totals["expired"],
            "remaining_today": remaining_today,
            "projected_remaining": projected_remaining,
            "expiration": expiration_text,
            "age": (today - lot_date).days if lot_date and lot_date <= today else "N/A",
            "status": status,
            "description": str(lot.get("description", "")),
            "source": str(lot.get("source", "")),
            "lot_id": lot_id,
        })

    lots.sort(key=lambda row: (
        row["remaining_today"] <= EPSILON,
        row["expiration"] == "N/A",
        row["expiration"],
        row["earned_date"],
    ))
    allocations.sort(key=lambda row: (row["event_date"], row["transaction_id"]))
    return lots, allocations, warnings


def analyze_leave_year(payload: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Build all read-only analytics tables for one normalized leave-year payload."""
    today = today or date.today()
    start = date.fromisoformat(str(payload["leave_year_start"]))
    end = date.fromisoformat(str(payload["leave_year_end"]))
    all_payload_transactions = [row for row in payload.get("transactions", []) if isinstance(row, dict)]
    transactions = [row for row in all_payload_transactions if _included(row)]
    transactions = [row for row in transactions if (transaction_date := _date(row)) and start <= transaction_date <= end]
    absence = [row for row in transactions if row.get("direction") == "used"]
    visible_categories = _visible_categories(payload, transactions)
    detail_transactions = [_transaction_detail(row, today) for row in transactions]

    month_starts = _month_starts(start, end)
    absence_by_month = _group_rows(absence, lambda row: (_date(row) or start).isoformat()[:7])
    months: list[dict[str, Any]] = []
    month_category_rows: list[dict[str, Any]] = []
    for month in month_starts:
        month_key = month.isoformat()[:7]
        rows = absence_by_month.get(month_key, [])
        values = _time_values(rows, today)
        months.append({"month": _month_label(month), "month_key": month_key, **values})
        grouped = _group_rows(rows, lambda row: str(row.get("category", "")))
        for category in sorted(grouped):
            month_category_rows.append({
                "month": _month_label(month),
                "month_key": month_key,
                "category": category,
                **_time_values(grouped[category], today),
            })

    weekdays: list[dict[str, Any]] = []
    for weekday_index, weekday in enumerate(calendar.day_name):
        rows = [row for row in absence if (_date(row) or start).weekday() == weekday_index]
        weekdays.append({"weekday": weekday, **_time_values(rows, today)})

    pay_period_rows: list[dict[str, Any]] = []
    for index, period in enumerate(payload.get("pay_periods", []), 1):
        if not isinstance(period, dict):
            continue
        period_start = date.fromisoformat(str(period.get("start_date", period.get("start"))))
        period_end = date.fromisoformat(str(period.get("end_date", period.get("end"))))
        rows = [row for row in absence if period_start <= (_date(row) or period_start) <= period_end]
        pay_period_rows.append({
            "pay_period": int(period.get("pay_period_number", index)),
            "start_date": period_start.isoformat(),
            "end_date": period_end.isoformat(),
            **_time_values(rows, today),
        })

    heatmap: list[dict[str, Any]] = []
    current = start
    while current <= end:
        rows = [row for row in absence if _date(row) == current]
        values = _time_values(rows, today)
        heatmap.append({
            "date": current.isoformat(),
            "weekday": current.strftime("%A"),
            **values,
            "full_day_total": values["full_leave_year"],
            "categories": ", ".join(sorted({str(row.get("category", "")) for row in rows})),
        })
        current += timedelta(days=1)

    heatmap_series: dict[str, list[dict[str, Any]]] = {"all-used": heatmap}
    heatmap_options: list[dict[str, Any]] = [{
        "key": "all-used",
        "label": "All Leave Used",
        "category": "all",
        "direction": "used",
        "total_hours": sum(_hours(row) for row in absence),
    }]
    for category in visible_categories:
        for direction in ("earned", "used"):
            selected_rows = [
                row for row in transactions
                if row.get("category") == category and row.get("direction") == direction
            ]
            total = sum(_hours(row) for row in selected_rows)
            if total <= EPSILON:
                continue
            key = f"{category}:{direction}"
            series_rows: list[dict[str, Any]] = []
            current = start
            while current <= end:
                day_rows = [row for row in selected_rows if _date(row) == current]
                values = _time_values(day_rows, today)
                series_rows.append({
                    "date": current.isoformat(),
                    "weekday": current.strftime("%A"),
                    **values,
                    "full_day_total": values["full_leave_year"],
                    "categories": category if day_rows else "",
                })
                current += timedelta(days=1)
            heatmap_series[key] = series_rows
            heatmap_options.append({
                "key": key,
                "label": f"{category.replace('_', ' ').title()} — {direction.title()}",
                "category": category,
                "direction": direction,
                "total_hours": total,
            })

    overtime_months: list[dict[str, Any]] = []
    net_accumulation: list[dict[str, Any]] = []
    net_accumulation_categories: list[dict[str, Any]] = []
    overtime_vs_comp: list[dict[str, Any]] = []
    comp_monthly: list[dict[str, Any]] = []
    credit_monthly: list[dict[str, Any]] = []
    for month in month_starts:
        month_key = month.isoformat()[:7]
        month_rows = [row for row in transactions if (_date(row) or start).isoformat()[:7] == month_key]
        overtime_rows = [row for row in month_rows if row.get("category") == "overtime" and row.get("direction") == "worked"]
        overtime_months.append({"month": _month_label(month), "month_key": month_key, **_time_values(overtime_rows, today)})

        earned_or_added = sum(_hours(row) for row in month_rows if row.get("direction") in BALANCE_INCREASING_DIRECTIONS)
        used = sum(_hours(row) for row in month_rows if row.get("direction") == "used")
        paid_out = sum(_hours(row) for row in month_rows if row.get("direction") == "paid_out")
        forfeited = sum(_hours(row) for row in month_rows if row.get("direction") == "forfeited")
        expired = sum(_hours(row) for row in month_rows if row.get("direction") == "expired")
        net_accumulation.append({
            "month": _month_label(month), "month_key": month_key,
            "earned_or_added": earned_or_added, "used": used, "paid_out": paid_out,
            "forfeited": forfeited, "expired": expired,
            "net_change": earned_or_added - used - paid_out - forfeited - expired,
        })
        for category in visible_categories:
            category_rows = [row for row in month_rows if row.get("category") == category]
            if not category_rows:
                continue
            increase = sum(_hours(row) for row in category_rows if row.get("direction") in BALANCE_INCREASING_DIRECTIONS)
            decrease = sum(_hours(row) for row in category_rows if row.get("direction") in BALANCE_DECREASING_DIRECTIONS)
            net_accumulation_categories.append({
                "month": _month_label(month), "category": category,
                "earned_or_added": increase, "decreased": decrease, "net_change": increase - decrease,
            })

        comp_earned = sum(_hours(row) for row in month_rows if row.get("category") == "comp" and row.get("direction") == "earned")
        credit_earned = sum(
            _hours(row) for row in month_rows
            if row.get("category") == "credit" and row.get("direction") in {"earned", "worked"}
        )
        overtime_worked = sum(_hours(row) for row in overtime_rows)
        overtime_vs_comp.append({
            "month": _month_label(month), "overtime_worked": overtime_worked,
            "comp_earned": comp_earned, "credit_earned": credit_earned,
            "combined_additional_work": overtime_worked + comp_earned + credit_earned,
        })
        comp_monthly.append({
            "month": _month_label(month),
            **{
                direction: sum(_hours(row) for row in month_rows if row.get("category") == "comp" and row.get("direction") == direction)
                for direction in ("earned", "used", "paid_out", "forfeited", "expired")
            },
        })
        credit_monthly.append({
            "month": _month_label(month),
            **{
                direction: sum(
                    _hours(row) for row in month_rows
                    if row.get("category") == "credit" and row.get("direction") == direction
                )
                for direction in ("earned", "worked", "used", "forfeited", "expired")
            },
        })

    final_days = ceil(((end - start).days + 1) / 4)
    final_start = end - timedelta(days=final_days - 1)
    final_rows = [row for row in absence if (_date(row) or start) >= final_start]
    rest_rows = [row for row in absence if (_date(row) or start) < final_start]
    total_absence = sum(_hours(row) for row in absence)
    final_hours = sum(_hours(row) for row in final_rows)
    final_percentage = None if total_absence <= EPSILON else final_hours / total_absence * 100
    final_quarter_rows = [
        {"period": "Final Quarter", "start_date": final_start.isoformat(), "end_date": end.isoformat(),
         "leave_hours": final_hours, "percentage": final_percentage},
        {"period": "Rest of Leave Year", "start_date": start.isoformat(), "end_date": (final_start - timedelta(days=1)).isoformat(),
         "leave_hours": sum(_hours(row) for row in rest_rows),
         "percentage": None if total_absence <= EPSILON else 100 - float(final_percentage)},
        {"period": "Full Leave Year", "start_date": start.isoformat(), "end_date": end.isoformat(),
         "leave_hours": total_absence, "percentage": None if total_absence <= EPSILON else 100.0},
    ]

    lifecycle_rows: list[dict[str, Any]] = []
    lifecycle_lookup: dict[tuple[str, str], dict[str, float]] = {}
    for category, direction, label in (
        ("overtime", "worked", "Overtime Worked"),
        ("comp", "earned", "Comp Earned"),
        ("comp", "used", "Comp Used"),
        ("comp", "paid_out", "Comp Paid Out"),
        ("comp", "forfeited", "Comp Forfeited"),
        ("comp", "expired", "Comp Expired"),
    ):
        values = _time_values([row for row in transactions if row.get("category") == category and row.get("direction") == direction], today)
        lifecycle_lookup[(category, direction)] = values
        lifecycle_rows.append({"metric": label, **values, "units": "hours"})

    starting_comp = float(payload.get("starting_balances", {}).get("comp", 0.0) or 0.0)
    comp_earned = lifecycle_lookup[("comp", "earned")]
    comp_increases = _time_values([
        row for row in transactions
        if row.get("category") == "comp" and row.get("direction") in BALANCE_INCREASING_DIRECTIONS
    ], today)
    disposal_keys = (("comp", "used"), ("comp", "paid_out"), ("comp", "forfeited"), ("comp", "expired"))
    disposed_today = sum(lifecycle_lookup[key]["through_today"] for key in disposal_keys)
    disposed_full = sum(lifecycle_lookup[key]["full_leave_year"] for key in disposal_keys)
    net_today = comp_increases["through_today"] - disposed_today
    net_future = comp_increases["future_scheduled"] - sum(lifecycle_lookup[key]["future_scheduled"] for key in disposal_keys)
    lifecycle_rows.extend([
        {"metric": "Net Comp Change", "through_today": net_today, "future_scheduled": net_future,
         "full_leave_year": net_today + net_future, "units": "hours"},
        {"metric": "Outstanding Comp", "through_today": starting_comp + net_today,
         "future_scheduled": net_future, "full_leave_year": starting_comp + net_today + net_future, "units": "hours"},
    ])

    credit_starting = float(payload.get("starting_balances", {}).get("credit", 0.0) or 0.0)
    credit_values: dict[str, dict[str, float]] = {}
    for direction, label in (
        ("earned", "Credit Hours Earned"),
        ("worked", "Credit Hours Worked"),
        ("used", "Credit Hours Used"),
        ("forfeited", "Credit Hours Forfeited"),
        ("expired", "Credit Hours Expired"),
    ):
        values = _time_values([
            row for row in transactions
            if row.get("category") == "credit" and row.get("direction") == direction
        ], today)
        credit_values[direction] = values
        lifecycle_rows.append({"metric": label, **values, "units": "hours"})
    credit_added_today = credit_values["earned"]["through_today"] + credit_values["worked"]["through_today"]
    credit_added_future = credit_values["earned"]["future_scheduled"] + credit_values["worked"]["future_scheduled"]
    credit_removed_today = sum(credit_values[key]["through_today"] for key in ("used", "forfeited", "expired"))
    credit_removed_future = sum(credit_values[key]["future_scheduled"] for key in ("used", "forfeited", "expired"))
    credit_net_today = credit_added_today - credit_removed_today
    credit_net_future = credit_added_future - credit_removed_future
    lifecycle_rows.extend([
        {"metric": "Net Credit Hours Change", "through_today": credit_net_today,
         "future_scheduled": credit_net_future, "full_leave_year": credit_net_today + credit_net_future, "units": "hours"},
        {"metric": "Outstanding Credit Hours", "through_today": credit_starting + credit_net_today,
         "future_scheduled": credit_net_future,
         "full_leave_year": credit_starting + credit_net_today + credit_net_future, "units": "hours"},
    ])

    lots, allocations, warnings = _comp_lots(transactions, today)
    allocated_uses = []
    earned_by_id = {str(row.get("id")): row for row in transactions if row.get("category") == "comp" and row.get("direction") == "earned"}
    for row in transactions:
        earned_id = str(row.get("earned_transaction_id") or "")
        if row.get("category") == "comp" and row.get("direction") == "used" and earned_id in earned_by_id:
            used_date = _date(row)
            earned_date = _date(earned_by_id[earned_id])
            if used_date and earned_date:
                allocated_uses.append((_hours(row), (used_date - earned_date).days))
    allocated_hours = sum(hours for hours, _days in allocated_uses)
    average_days = None if allocated_hours <= EPSILON else sum(hours * days for hours, days in allocated_uses) / allocated_hours
    open_lots = [row for row in lots if isinstance(row["remaining_today"], (int, float)) and row["remaining_today"] > EPSILON]
    oldest_lot = min(open_lots, key=lambda row: row["earned_date"]) if open_lots else None

    matured_lots = []
    for lot in lots:
        try:
            expiration = date.fromisoformat(str(lot["expiration"]))
        except ValueError:
            continue
        if expiration <= today:
            matured_lots.append(lot)
    matured_earned = sum(float(row["original"]) for row in matured_lots)
    matured_lot_ids = {str(row["lot_id"]): date.fromisoformat(str(row["expiration"])) for row in matured_lots}
    matured_used = sum(
        _hours(row)
        for row in transactions
        if row.get("category") == "comp"
        and row.get("direction") == "used"
        and str(row.get("earned_transaction_id") or "") in matured_lot_ids
        and (_date(row) or today) <= matured_lot_ids[str(row.get("earned_transaction_id"))]
    )
    consumed_percentage = None if matured_earned <= EPSILON else matured_used / matured_earned * 100
    matured_summary = [{
        "matured_lots": len(matured_lots), "earned_hours": matured_earned,
        "used_before_expiration": matured_used,
        "paid_out": sum(float(row["paid_out"]) for row in matured_lots),
        "forfeited": sum(float(row["forfeited"]) for row in matured_lots),
        "expired": sum(float(row["expired"]) for row in matured_lots),
        "percentage_consumed": consumed_percentage,
    }]

    highest_month = max(months, key=lambda row: row["full_leave_year"], default=None)
    if highest_month and highest_month["full_leave_year"] <= EPSILON:
        highest_month = None
    highest_period = max(pay_period_rows, key=lambda row: row["full_leave_year"], default=None)
    if highest_period and highest_period["full_leave_year"] <= EPSILON:
        highest_period = None
    summary = [
        {"metric": "Total Leave Used or Scheduled", "value": total_absence, "units": "hours",
         "period_or_date": f"{start.isoformat()} to {end.isoformat()}", "basis": "Used transactions, including future scheduled leave"},
        {"metric": "Highest Leave-Use Month", "value": highest_month["full_leave_year"] if highest_month else None,
         "units": "hours", "period_or_date": highest_month["month"] if highest_month else "N/A",
         "basis": "Full leave year, including future scheduled leave"},
        {"metric": "Highest Leave-Use Pay Period", "value": highest_period["full_leave_year"] if highest_period else None,
         "units": "hours", "period_or_date": f"PP {highest_period['pay_period']}" if highest_period else "N/A",
         "basis": "Full leave year, including future scheduled leave"},
        {"metric": "Final-Quarter Leave Concentration", "value": final_percentage, "units": "percent",
         "period_or_date": f"{final_start.isoformat()} to {end.isoformat()}", "basis": "Leave hours used or scheduled"},
        {"metric": "Overtime Worked", "value": lifecycle_lookup[("overtime", "worked")]["full_leave_year"], "units": "hours",
         "period_or_date": "Full leave year", "basis": "Overtime worked transactions"},
        {"metric": "Comp Earned Instead of Paid Overtime", "value": comp_earned["full_leave_year"], "units": "hours",
         "period_or_date": "Full leave year", "basis": "Comp earned transactions"},
        {"metric": "Comp Used", "value": lifecycle_lookup[("comp", "used")]["full_leave_year"], "units": "hours",
         "period_or_date": "Full leave year", "basis": "Comp used transactions"},
        {"metric": "Comp Paid Out", "value": lifecycle_lookup[("comp", "paid_out")]["full_leave_year"], "units": "hours",
         "period_or_date": "Full leave year", "basis": "Comp paid-out transactions"},
        {"metric": "Comp Forfeited", "value": lifecycle_lookup[("comp", "forfeited")]["full_leave_year"], "units": "hours",
         "period_or_date": "Full leave year", "basis": "Comp forfeited transactions"},
        {"metric": "Current Outstanding Comp", "value": starting_comp + net_today, "units": "hours",
         "period_or_date": today.isoformat(), "basis": "Opening balance plus earned, less dispositions through today"},
        {"metric": "Average Days Between Earning and Using Comp", "value": average_days, "units": "days",
         "period_or_date": "Through today", "basis": "Hour-weighted allocated comp usage"},
        {"metric": "Oldest Outstanding Comp Lot", "value": oldest_lot["remaining_today"] if oldest_lot else None, "units": "hours",
         "period_or_date": f"Earned {oldest_lot['earned_date']}" if oldest_lot else "N/A",
         "basis": f"{oldest_lot['age']} days old as of today" if oldest_lot else "No open dated comp lot"},
        {"metric": "Percentage Consumed Before Expiration", "value": consumed_percentage, "units": "percent",
         "period_or_date": "Matured lots", "basis": "Allocated use on or before expiration"},
        {"metric": "Credit Hours Earned or Worked", "value": credit_values["earned"]["full_leave_year"] + credit_values["worked"]["full_leave_year"],
         "units": "hours", "period_or_date": "Full leave year", "basis": "Credit earned and worked transactions"},
        {"metric": "Credit Hours Used", "value": credit_values["used"]["full_leave_year"], "units": "hours",
         "period_or_date": "Full leave year", "basis": "Credit used transactions"},
        {"metric": "Current Outstanding Credit Hours", "value": credit_starting + credit_net_today, "units": "hours",
         "period_or_date": today.isoformat(), "basis": "Opening balance plus earned or worked, less dispositions through today"},
    ]

    if starting_comp > EPSILON and not lots:
        warnings.append({
            "severity": "Information", "area": "Comp opening balance", "date_or_lot": start.isoformat(),
            "message": "Opening comp balance has no earned-date metadata and is excluded from age statistics.",
        })

    return {
        "year": payload.get("year", payload.get("leave_year")),
        "leave_year_start": start.isoformat(),
        "leave_year_end": end.isoformat(),
        "available_leave_years": payload.get("available_leave_years", [payload.get("year", payload.get("leave_year"))]),
        "visible_categories": visible_categories,
        "source": {
            "transactions_received": len(all_payload_transactions),
            "transactions_included": len(transactions),
            "absence_transactions": len(absence),
        },
        "summary": summary,
        "months": months,
        "month_categories": month_category_rows,
        "weekdays": weekdays,
        "pay_periods": pay_period_rows,
        "heatmap": heatmap,
        "heatmap_options": heatmap_options,
        "heatmap_series": heatmap_series,
        "overtime_months": overtime_months,
        "net_accumulation": net_accumulation,
        "net_accumulation_categories": net_accumulation_categories,
        "final_quarter": {
            "start_date": final_start.isoformat(), "end_date": end.isoformat(), "hours": final_hours,
            "percentage": final_percentage, "total_hours": total_absence, "rows": final_quarter_rows,
        },
        "lifecycle": {
            "summary": lifecycle_rows,
            "lots": lots,
            "allocations": allocations,
            "matured_lots": matured_summary,
            "monthly_overtime_vs_comp": overtime_vs_comp,
            "monthly_comp": comp_monthly,
            "monthly_credit": credit_monthly,
        },
        "warnings": warnings,
        "transactions": detail_transactions,
    }
