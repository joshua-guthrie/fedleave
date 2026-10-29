"""Shared, pure historical eligibility and explicit coverage assertions.

Snapshots and confirmation records are data. This module has no filesystem,
backend, preference writer or ledger-storage capability.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .payperiods import validate_pay_periods
from .planning import fingerprint, source_identity, transaction_fingerprint, working_calendar
from .transaction_effects import signed_balance_effect

CONFIRMED_STATUSES = ("worked", "submitted", "certified", "reconciled")
SCHEDULE_ASSUMPTION = (
    "Historical work schedules are unavailable. Forecast calculations apply the currently configured work schedule "
    "to earlier years. Historical exposure estimates may differ from actual past working hours."
)


def days(start: str, end: str):
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    while day <= last:
        yield day.isoformat()
        day += timedelta(days=1)


def coverage_key(snapshot: dict) -> str:
    identity = source_identity(snapshot)
    identity.pop("snapshot_fingerprint")
    return fingerprint(identity)


def represented_periods(snapshot: dict) -> tuple[dict, ...]:
    """Require an exact, nonoverlapping pay-period representation of the year."""
    try:
        validate_pay_periods(snapshot)
        return tuple(
            {"period_id": str(row["pay_period_number"]), "start": row["start_date"], "end": row["end_date"]}
            for row in snapshot["pay_periods"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"Historical bounds/pay-period coverage is invalid (check numbering, gaps and overlaps): {exc}"
        ) from exc


def _period_fingerprint(snapshot, period):
    transactions = []
    for row in snapshot.get("transactions", []):
        if row.get("source") in {"auto_accrual", "expiration-engine"}:
            continue
        day = row.get("date")
        try:
            date.fromisoformat(day)
        except (ValueError, TypeError):
            day = None
        if day is None or period["start"] <= day <= period["end"]:
            transactions.append(transaction_fingerprint(row))
    return fingerprint({**period, "transaction_fingerprints": sorted(transactions)})


def confirm_coverage(snapshot: dict, period_ids=None) -> tuple[dict, ...]:
    """Build explicit assertions for a whole year or selected represented periods."""
    periods = represented_periods(snapshot)
    selected = {str(item) for item in period_ids} if period_ids is not None else {p["period_id"] for p in periods}
    if selected - {p["period_id"] for p in periods}:
        raise ValueError("A confirmation references an unrepresented pay period.")
    return tuple(
        {
            "source_key": coverage_key(snapshot),
            **period,
            "fingerprint": _period_fingerprint(snapshot, period),
            "confirmed": True,
        }
        for period in periods
        if period["period_id"] in selected
    )


def coverage_status(snapshot: dict, confirmations) -> tuple[tuple[dict, ...], frozenset[str]]:
    key = coverage_key(snapshot)
    records = {
        str(row.get("period_id")): row
        for row in confirmations
        if isinstance(row, dict) and row.get("source_key") == key and row.get("confirmed") is True
    }
    rows, covered = [], set()
    for period in represented_periods(snapshot):
        record = records.get(period["period_id"])
        valid = (
            record is not None
            and record.get("start") == period["start"]
            and record.get("end") == period["end"]
            and record.get("fingerprint") == _period_fingerprint(snapshot, period)
        )
        rows.append(
            {**period, "confirmed": valid, "state": "Confirmed" if valid else "Stale" if record else "Unconfirmed"}
        )
        if valid:
            covered.update(days(period["start"], period["end"]))
    return tuple(rows), frozenset(covered)


@dataclass(frozen=True)
class HistoricalYear:
    year: int
    start: str
    end: str
    source_key: str
    periods: tuple[dict, ...]
    covered: frozenset[str]
    calendar: dict[str, float | None]
    transactions: tuple[dict, ...]
    invalid_dates: dict[str, frozenset[str]]
    warnings: tuple[dict, ...]
    schedule_assumption: str

    def observation(self, category: str, month: int | None = None) -> dict:
        selected = [day for day in self.calendar if month is None or date.fromisoformat(day).month == month]
        reason = None
        if not selected:
            reason = "No represented dates in this bucket."
        elif any(day not in self.covered for day in selected):
            reason = "Coverage is unconfirmed or stale for part of this bucket."
        elif any(self.calendar[day] is None for day in selected):
            reason = "Work schedule or cached holiday exposure is unavailable."
        elif "*" in self.invalid_dates.get(category, ()) or any(
            day in self.invalid_dates.get(category, ()) for day in selected
        ):
            reason = "Malformed historical records make usage uncertain."
        exposure = sum(self.calendar[day] or 0 for day in selected)
        if reason is None and exposure <= 0:
            reason = "Zero scheduled work exposure; no rate can be estimated."
        selected_dates = set(selected)
        source_rows = [
            row for row in self.transactions if row["category"] == category and row["date"] in selected_dates
        ]
        hours = sum(row["hours"] for row in source_rows)
        return {
            "year": self.year,
            "category": category,
            "month": month,
            "hours": hours if reason is None else None,
            "exposure": exposure if reason is None else None,
            "rate": hours / exposure if reason is None else None,
            "eligible": reason is None,
            "exclusion_reason": reason,
            "transaction_ids": [row["id"] for row in source_rows],
            "source_key": self.source_key,
        }


def prepare_history(
    snapshot: dict, target: dict, confirmations, *, cutoff: str, status_basis="effective"
) -> HistoricalYear:
    source = deepcopy(snapshot)
    periods, covered = coverage_status(source, confirmations)
    warnings = []
    historical_schedule = source.get("calculation_context", {}).get("historical_work_schedule")
    if isinstance(historical_schedule, dict):
        source["snapshot_rules"]["defaults"].update(historical_schedule)
        assumption = "Explicit backend-supplied historical work schedule."
    else:
        source["snapshot_rules"]["defaults"].update(deepcopy(target["snapshot_rules"]["defaults"]))
        assumption = SCHEDULE_ASSUMPTION
        warnings.append({"code": "HISTORICAL_SCHEDULE_ASSUMPTION", "message": assumption, "year": source["leave_year"]})
    calendar_warnings = []
    calendar, _ = working_calendar(source, source["leave_year_start"], source["leave_year_end"], calendar_warnings)
    warnings.extend({**asdict(w), "year": source["leave_year"]} for w in calendar_warnings)
    transactions, invalid_dates = [], {"annual": set(), "sick": set()}
    for row in source.get("transactions", []):
        if row.get("direction") != "used" or row.get("category") not in {"annual", "sick"}:
            continue
        day = row.get("date")
        try:
            effect = signed_balance_effect(row)
            if effect == 0:
                continue
            if date.fromisoformat(day).isoformat() != day or day not in calendar or day > cutoff:
                raise ValueError("Historical usage has a date outside its represented eligible history.")
            status = str(row.get("status", "planned")).strip().lower() or "planned"
            if status in {"planned", "requested"}:
                warnings.append(
                    {
                        "code": "UNRESOLVED_RECORDED_STATUS",
                        "message": "Recorded Through Cutoff does not confirm attendance; this row remains planned/requested.",
                        "year": source["leave_year"],
                        "transaction_id": row.get("id"),
                    }
                )
            if status_basis == "confirmed" and status not in CONFIRMED_STATUSES:
                continue
            if calendar[day] == 0:
                warnings.append(
                    {
                        "code": "OFF_SCHEDULE_HISTORY",
                        "message": "Historical hours on a nonworking date are included in source usage.",
                        "year": source["leave_year"],
                        "date": day,
                        "transaction_id": row.get("id"),
                    }
                )
            transactions.append(
                {**deepcopy(row), "hours": -effect, "status": status, "timing": "Recorded Through Cutoff"}
            )
        except (ValueError, TypeError, KeyError) as exc:
            invalid_dates[row["category"]].add(day if isinstance(day, str) and day in calendar else "*")
            warnings.append(
                {
                    "code": "INVALID_HISTORICAL_USAGE",
                    "message": str(exc),
                    "year": source["leave_year"],
                    "transaction_id": row.get("id"),
                }
            )
    return HistoricalYear(
        source["leave_year"],
        source["leave_year_start"],
        source["leave_year_end"],
        coverage_key(source),
        periods,
        covered,
        calendar,
        tuple(sorted(transactions, key=lambda row: (row["date"], str(row.get("id"))))),
        {category: frozenset(values) for category, values in invalid_dates.items()},
        tuple(warnings),
        assumption,
    )
