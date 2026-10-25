"""Pure, read-only activity selection for the Seasonality tab (#135)."""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite
from typing import Literal

from fedleave.categories import CATEGORY_POLICIES
from fedleave.transaction_effects import transaction_is_effective

LABELS = {
    "annual": "Annual Leave",
    "sick": "Sick Leave",
    "comp": "Comp Time",
    "travel_comp": "Travel Comp",
    "credit": "Credit Hours",
    "time_off_award": "Time-Off Award",
    "restored_annual": "Restored Annual Leave",
    "religious_comp": "Religious Comp",
    "ppl": "Paid Parental Leave (PPL)",
    "fmla": "FMLA Tracking",
    "admin": "Admin Leave",
    "lwop": "LWOP",
    "military": "Military Leave",
    "court": "Court Leave",
    "excused": "Excused Leave",
    "holiday": "Holiday",
    "flex": "Flex",
    "other": "Other Leave",
}
GROUPINGS = {"month": "Month", "weekday": "Day of Week", "pay_period": "Pay Period"}


@dataclass(frozen=True)
class SeasonalitySelection:
    grouping: Literal["month", "weekday", "pay_period"]
    category: str = "all"
    activity: Literal["used", "earned"] = "used"

    def __post_init__(self):
        if self.grouping not in GROUPINGS or self.activity not in {"used", "earned"}:
            raise ValueError("Unsupported seasonality grouping/activity")
        if self.category == "all" and self.activity != "used":
            raise ValueError("All Leave is supported for Used only")

    @property
    def key(self):
        return "all-used" if self.category == "all" else f"{self.category}:{self.activity}"


def seasonality_options(payload: dict) -> list[dict]:
    """Honor the backend registry, keeping supported zero-activity options."""
    definitions = payload.get("category_definitions")
    if isinstance(definitions, dict):
        supported = set(definitions)
    else:
        # Old backends lack registry metadata. Offer established categories,
        # and discover later additions only when the supplied data proves them.
        supported = set(CATEGORY_POLICIES) - {"ppl", "fmla"}
        supported.update(row.get("category") for row in payload.get("transactions", []) if isinstance(row, dict))
        definitions = {}
    result = [
        {
            "key": "all-used",
            "category": "all",
            "activity": "used",
            "label": "All Leave Used",
            "name": "All Leave",
            "verb": "Used",
        }
    ]
    for category in sorted(value for value in supported if isinstance(value, str) and value != "overtime"):
        metadata = definitions.get(category, {})
        label = metadata.get("label") or LABELS.get(category, category.replace("_", " ").title())
        if category in LABELS and label == category.replace("_", " ").title():
            label = LABELS[category]
        if category == "fmla":
            label = "FMLA Tracking"
        policy = CATEGORY_POLICIES.get(category)
        activities = ["used"]
        if (
            category not in {"annual", "sick", "fmla"}
            and policy
            and policy.mode in {"lot_carryover", "balance_carryover"}
        ):
            activities.append("earned")
        for activity in activities:
            verb = "Restored" if category == "restored_annual" and activity == "earned" else activity.title()
            result.append(
                {
                    "key": f"{category}:{activity}",
                    "category": category,
                    "activity": activity,
                    "label": f"{label} — {verb}",
                    "name": label,
                    "verb": verb,
                }
            )
    return result


def _earning_origin(row: dict, year: int, start: str) -> str:
    """Return new/carried/unknown without interpreting a balance as earnings."""
    source = str(row.get("source", "")).lower()
    if row.get("carryover_generated") or source in {"carryover", "rollover", "expiration-rollover"}:
        return "carried"
    if any(
        row.get(key)
        for key in (
            "carried_from_transaction_id",
            "carried_from_leave_year",
            "carryover_chain",
            "rolled_over_from_transaction_id",
        )
    ):
        return "carried"
    origin_year = row.get("origin_leave_year")
    if isinstance(origin_year, int) and origin_year < year:
        return "carried"
    original = row.get("original_earned_date")
    if original and str(original) < start:
        return "carried"
    if "rollover" in source or "carry" in source or (original and original != row["date"]):
        return "unknown"
    if row.get("origin_transaction_id") and row["origin_transaction_id"] != row.get("id"):
        return "unknown"
    if row.get("origin_key") and not (origin_year == year and row.get("origin_transaction_id") == row.get("id")):
        return "unknown"
    return "new"


def seasonality_series(
    payload: dict, *, grouping: str, category: str | None = None, activity: str = "used", cutoff: date
) -> dict:
    selection = SeasonalitySelection(grouping, category or "all", activity)
    option = next((row for row in seasonality_options(payload) if row["key"] == selection.key), None)
    if option is None:
        raise ValueError(f"Unsupported seasonality selection: {selection.key}")
    start, end = date.fromisoformat(payload["leave_year_start"]), date.fromisoformat(payload["leave_year_end"])
    if start > end:
        raise ValueError("Leave-year bounds are reversed")
    year = int(payload.get("leave_year", payload.get("year", start.year)))
    warnings, selected = [], []

    def warn(code, message, row=None):
        warnings.append({"code": code, "message": message, "transaction_id": str((row or {}).get("id", ""))})

    if "transactions" not in payload:
        warn("MISSING_TRANSACTIONS", "Source transactions were not supplied; totals cannot be verified.")
    directions = (
        {"used"}
        if activity == "used"
        else (
            {"earned", "worked"}
            if category == "credit"
            else {"earned", "restored"}
            if category == "restored_annual"
            else {"earned"}
        )
    )
    for row in payload.get("transactions", []):
        if not isinstance(row, dict):
            warn("INVALID_TRANSACTION", "Source transaction is not an object.")
            continue
        source_category = row.get("category")
        if selection.category == "all":
            matches = source_category != "fmla"
        else:
            matches = source_category == selection.category or (
                selection.category == "fmla" and source_category == "ppl"
            )
        if not matches or row.get("direction") not in directions:
            continue
        try:
            day = date.fromisoformat(row["date"])
            if not start <= day <= end or not transaction_is_effective(row):
                continue
            hours = float(row["hours"])
            if not isfinite(hours) or hours < 0:
                raise ValueError("Hours must be finite and nonnegative")
            if hours == 0:
                continue
        except (ValueError, KeyError, TypeError) as exc:
            warn("INVALID_TRANSACTION", str(exc), row)
            continue
        if activity == "earned":
            origin = _earning_origin(row, year, start.isoformat())
            if origin != "new":
                if origin == "unknown":
                    warn(
                        "UNVERIFIED_EARNING_ORIGIN",
                        "Possible carried credit excluded from newly earned totals; verify original grant provenance.",
                        row,
                    )
                continue
        derived = selection.category == "fmla" and source_category == "ppl"
        selected.append(
            {
                **row,
                "hours": hours,
                "category": "fmla" if derived else source_category,
                "transaction_id": str(row.get("id", "")),
                "source_transaction_id": str(row.get("id", "")),
                "source_leave_year": row.get("source_leave_year", year),
                "derived": derived,
                "timing": "Recorded Through Cutoff"
                if day <= cutoff
                else "Future Dated"
                if activity == "earned"
                else "Future Scheduled",
                "source": "derived-ppl-fmla" if derived else row.get("source", ""),
                "description": f"FMLA consumption from PPL {row.get('id', '')}: {row.get('description', '')}"
                if derived
                else row.get("description", ""),
            }
        )
    duplicates = {key for key, count in Counter(row["transaction_id"] for row in selected).items() if count > 1}
    for key in sorted(duplicates):
        warn("DUPLICATE_TRANSACTION_ID", f"Duplicate source ID {key}; excluded until corrected.", {"id": key})
    selected = [row for row in selected if row["transaction_id"] not in duplicates]
    if category == "credit" and activity == "earned":
        earned = [row for row in selected if row["direction"] == "earned"]
        filtered = []
        for row in selected:
            linked = next((other for other in earned if row.get("earned_transaction_id") == other.get("id")), None)
            ambiguous = [other for other in earned if other["date"] == row["date"] and other["hours"] == row["hours"]]
            if row["direction"] == "worked" and (linked or ambiguous):
                if not linked:
                    warn(
                        "POSSIBLE_DUPLICATE_CREDIT",
                        "Matching worked/earned credit rows: uncertain worked row excluded; verify whether it is an independent credit.",
                        row,
                    )
                continue
            filtered.append(row)
        selected = filtered
    selected.sort(key=lambda row: (row["date"], row["transaction_id"]))
    buckets = []
    if grouping == "month":
        cursor = start.replace(day=1)
        while cursor <= end:
            last = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
            buckets.append(({"month": cursor.strftime("%b %Y"), "month_key": cursor.isoformat()[:7]}, cursor, last))
            cursor = last + timedelta(days=1)
        label_key = "month"
        columns = [("month", "Month")]
    elif grouping == "weekday":
        buckets = [({"weekday": name}, index, index) for index, name in enumerate(calendar.day_name)]
        label_key = "weekday"
        columns = [("weekday", "Weekday")]
    else:
        label_key = "pay_period"
        columns = [("pay_period", "Pay Period"), ("start_date", "Start Date"), ("end_date", "End Date")]
        for index, period in enumerate(payload.get("pay_periods", []), 1):
            try:
                first = date.fromisoformat(period.get("start_date", period.get("start")))
                last = date.fromisoformat(period.get("end_date", period.get("end")))
                if first > last:
                    raise ValueError("Pay-period bounds are reversed")
                buckets.append(
                    (
                        {
                            "pay_period": int(period.get("pay_period_number", index)),
                            "start_date": first.isoformat(),
                            "end_date": last.isoformat(),
                        },
                        first,
                        last,
                    )
                )
            except (ValueError, TypeError, AttributeError) as exc:
                warn("INVALID_PAY_PERIOD", str(exc))
        buckets.sort(key=lambda row: row[1])
        if any(left[2] >= right[1] for left, right in zip(buckets, buckets[1:])):
            raise ValueError("Pay-period date ranges overlap")
        if any(
            not any(first <= date.fromisoformat(row["date"]) <= last for _, first, last in buckets) for row in selected
        ):
            warn(
                "INCOMPLETE_PAY_PERIODS",
                "Some selected transactions have no supplied pay period; period totals are incomplete.",
            )
        if not buckets:
            warn("MISSING_PAY_PERIODS", "Actual pay periods were not supplied; period totals cannot be verified.")
        elif (
            buckets[0][1] > start
            or buckets[-1][2] < end
            or any(left[2] + timedelta(days=1) != right[1] for left, right in zip(buckets, buckets[1:]))
        ):
            warn("INCOMPLETE_PAY_PERIODS", "Supplied pay periods do not cover the complete leave year continuously.")
    rows, bucket_transactions = [], []
    for labels, first, last in buckets:
        matches = [
            row
            for row in selected
            if (
                date.fromisoformat(row["date"]).weekday() == first
                if grouping == "weekday"
                else first <= date.fromisoformat(row["date"]) <= last
            )
        ]
        through = sum(row["hours"] for row in matches if row["date"] <= cutoff.isoformat())
        future = sum(row["hours"] for row in matches if row["date"] > cutoff.isoformat())
        rows.append(
            {**labels, "through_today": through, "future_scheduled": future, "full_leave_year": through + future}
        )
        bucket_transactions.append(matches)
    future_label = "Future Dated" if activity == "earned" else "Future Scheduled"
    columns += [
        ("through_today", "Recorded Through Cutoff"),
        ("future_scheduled", future_label),
        ("full_leave_year", "Full Leave Year"),
    ]
    title = f"{option['name']} {option['verb']} by {GROUPINGS[grouping]} — {year}"
    measure = (
        "absence"
        if selection.category == "all"
        else "entitlement tracking"
        if selection.category == "fmla"
        else "new credits"
        if activity == "earned"
        else "usage"
    )
    group_text = {
        "month": "calendar month",
        "weekday": "weekday (Monday through Sunday)",
        "pay_period": "actual pay-period dates",
    }[grouping]
    description = f"Recorded and scheduled {measure} grouped by {group_text}. Recorded Through Cutoff includes effective dated entries, including unresolved planned/requested leave; it does not confirm attendance. {future_label} includes dates after {cutoff.isoformat()}."
    if activity == "earned":
        description += " Genuine new credits only; openings, carryover copies and balance adjustments are excluded."
    if not selected and not warnings:
        description += " No matching transactions."
    warnings.sort(key=lambda row: (row["code"], row["transaction_id"], row["message"]))
    if warnings:
        description += " Total: N/A; rows show known recorded subtotals. Incomplete/unverified totals: " + "; ".join(
            f"{row['code']} {row['transaction_id']}: {row['message']}" for row in warnings
        )
    total = sum(row["hours"] for row in selected)
    return {
        "selection": {"grouping": grouping, "category": selection.category, "activity": activity, "key": selection.key},
        "year": year,
        "cutoff": cutoff.isoformat(),
        "units": "hours",
        "title": title,
        "description": description,
        "columns": columns,
        "label_key": label_key,
        "series": [("through_today", "Recorded Through Cutoff"), ("future_scheduled", future_label)],
        "rows": rows,
        "transactions": selected,
        "bucket_transactions": bucket_transactions,
        "source_transaction_ids": [row["transaction_id"] for row in selected],
        "total_hours": total if not warnings else None,
        "known_total_hours": total,
        "warnings": warnings,
        "metadata": [
            ("Leave Year", year),
            ("Time Grouping", grouping),
            ("Category", selection.category),
            ("Activity", activity),
            ("Cutoff", cutoff.isoformat()),
            ("Units", "hours"),
            ("Through Cutoff Meaning", "Recorded effective entries; unresolved statuses do not confirm attendance"),
            ("Future Meaning", future_label),
            (
                "Classification Caveats",
                "New credits exclude carryover and adjustments"
                if activity == "earned"
                else "FMLA is tracking only; All Leave Used counts physical absence once",
            ),
            (
                "Warnings",
                "; ".join(row["code"] + ": " + row["transaction_id"] + " " + row["message"] for row in warnings),
            ),
        ],
    }
