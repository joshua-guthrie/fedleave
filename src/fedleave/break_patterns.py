"""Pure, descriptive break intervals over dated usage and explicit coverage.

Scheduled workdays are exposure, never evidence of actual attendance. Future
bookings do not complete or reset recorded-history metrics. All ranges include
both endpoints; unknown coverage always interrupts a recorded interval.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from .history import CONFIRMED_STATUSES, analysis_calendar, coverage_key, coverage_status, days
from .planning import source_identity
from .transaction_effects import TRANSACTION_DIRECTIONS, signed_balance_effect, transaction_is_effective
from .usage_comparison import ABSENCE_CATEGORIES

DISCRETIONARY_CATEGORIES = ("annual", "restored_annual", "comp", "travel_comp", "credit", "time_off_award")
GROUPS = {
    "discretionary": ("Discretionary time off", DISCRETIONARY_CATEGORIES),
    "sick": ("Sick leave only", ("sick",)),
    "all": ("All physical absence", ABSENCE_CATEGORIES),
}
TOLERANCE = 1e-9


@dataclass(frozen=True)
class BreakParameters:
    cutoff: str
    years: tuple[int, ...] | None = None
    grouping: str = "discretionary"
    categories: tuple[str, ...] = ()
    substantial_workdays: int = 3
    assume_current_schedule: bool = True
    status_basis: str = "effective"


@dataclass(frozen=True)
class BreakAnalysis:
    parameters: BreakParameters
    categories: tuple[str, ...]
    source: dict
    summary: dict
    daily: tuple[dict, ...]
    recorded: tuple[dict, ...]
    upcoming: tuple[dict, ...]
    gaps: tuple[dict, ...]
    distribution: tuple[dict, ...]
    day_distribution: tuple[dict, ...]
    timing: tuple[dict, ...]
    coverage: tuple[dict, ...]
    transactions: tuple[dict, ...]
    warnings: tuple[dict, ...]
    schema_version: int = 1
    method_version: str = "covered-break-patterns-1"


def _usage(snapshot, selected, parameters):
    rows, warnings, invalid_selected, invalid_other, seen = [], [], set(), set(), set()
    first, last = snapshot["leave_year_start"], snapshot["leave_year_end"]
    key = coverage_key(snapshot)
    for original in snapshot.get("transactions", []):
        if not isinstance(original, dict):
            invalid_selected.add("*")
            warnings.append({"code": "INVALID_USAGE", "message": "A transaction is not an object."})
            continue
        category, direction, day = original.get("category"), original.get("direction"), original.get("date")
        if direction in TRANSACTION_DIRECTIONS and direction != "used":
            continue
        if category in ("fmla", "overtime"):
            continue
        invalid = invalid_selected if category in selected else invalid_other
        try:
            if not transaction_is_effective(original):
                continue
            if direction != "used" or category not in ABSENCE_CATEGORIES:
                invalid = invalid_selected
                raise ValueError(f"Unsupported absence category/direction: {category!r}/{direction!r}.")
            if not original.get("id") or original.get("hours") is None or isinstance(original["hours"], bool):
                raise ValueError("Usage needs an original ID and numeric hours.")
            effect = signed_balance_effect(original)
            if date.fromisoformat(day).isoformat() != day or not first <= day <= last:
                raise ValueError("Usage date must be an ISO date inside its source year.")
            if effect == 0:
                continue
            identity = str(original["id"])
            if identity in seen:
                invalid.add("*")
                raise ValueError("Duplicate usage ID makes transaction provenance uncertain.")
            seen.add(identity)
            status = str(original.get("status", "planned")).strip().lower() or "planned"
            recorded = day <= parameters.cutoff
            if recorded and status in {"planned", "requested"}:
                warnings.append(
                    {
                        "code": "UNRESOLVED_RECORDED_STATUS",
                        "message": "Recorded Through Cutoff includes a planned/requested row; its date does not confirm leave was taken.",
                        "date": day,
                        "transaction_id": identity,
                    }
                )
            if recorded and parameters.status_basis == "confirmed" and status not in CONFIRMED_STATUSES:
                continue
            rows.append(
                {
                    **deepcopy(original),
                    "hours": -effect,
                    "status": status,
                    "selected": category in selected,
                    "timing": "Recorded Through Cutoff" if recorded else "Scheduled",
                    "source_year": snapshot["leave_year"],
                    "source_key": key,
                }
            )
        except (ValueError, TypeError, KeyError) as exc:
            invalid.add(day if isinstance(day, str) and first <= day <= last else "*")
            warnings.append(
                {"code": "INVALID_USAGE", "message": str(exc), "date": day, "transaction_id": original.get("id")}
            )
    return rows, invalid_selected, invalid_other, warnings


def _classify(snapshot, anchor, coverage, selected, parameters):
    periods, covered = coverage_status(snapshot, coverage, strict=False)
    key = coverage_key(snapshot)
    historical = snapshot.get("calculation_context", {}).get("historical_work_schedule")
    use_current = parameters.assume_current_schedule and not isinstance(historical, dict)
    calendar, assumption, warnings = analysis_calendar(snapshot, anchor, use_current)
    warnings.extend(deepcopy(snapshot.get("calculation_context", {}).get("warnings", [])))
    warnings.extend(deepcopy(snapshot.get("accounting_warnings", [])))
    rows, invalid, invalid_other, issues = _usage(snapshot, selected, parameters)
    warnings.extend(issues)
    by_date = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(row)
    result = []
    for day, scheduled in calendar.items():
        recorded = day <= parameters.cutoff
        entries = by_date.get(day, [])
        selected_rows = [row for row in entries if row["selected"]]
        others = [row for row in entries if not row["selected"]]
        selected_hours, other_hours = sum(row["hours"] for row in selected_rows), sum(row["hours"] for row in others)
        usage_known = (not recorded or day in covered) and "*" not in invalid and day not in invalid
        other_known = (not recorded or day in covered) and "*" not in invalid_other and day not in invalid_other
        reasons = []
        if recorded and day not in covered:
            reasons.append("Usage coverage is unconfirmed or stale.")
        if scheduled is None:
            reasons.append("Work schedule or cached holiday context is unavailable.")
        if "*" in invalid or day in invalid:
            reasons.append("Malformed selected usage makes this date uncertain.")
        if "*" in invalid_other or day in invalid_other:
            reasons.append("Malformed other-category usage makes contextual hours uncertain.")
        classification = "Unknown"
        if usage_known and scheduled is not None:
            classification = (
                "Nonworking"
                if scheduled == 0
                else "Full"
                if selected_hours + TOLERANCE >= scheduled
                else "Partial"
                if selected_hours > 0
                else "No selected absence"
            )
        overbooked = scheduled is not None and selected_hours > scheduled + TOLERANCE
        if overbooked:
            warnings.append(
                {
                    "code": "HOURS_ABOVE_SCHEDULE",
                    "date": day,
                    "message": "Raw selected hours exceed scheduled hours; only the coverage ratio is capped at 100%.",
                }
            )
        result.append(
            {
                "date": day,
                "source_year": snapshot["leave_year"],
                "source_key": key,
                "timing": "Recorded Through Cutoff" if recorded else "Scheduled",
                "scheduled_hours": scheduled,
                "selected_hours": selected_hours if usage_known else None,
                "other_hours": other_hours if other_known else None,
                "known_selected_hours": selected_hours,
                "known_other_hours": other_hours,
                "classification": classification,
                "coverage_confirmed": day in covered if recorded else None,
                "absence_ratio": min(1.0, selected_hours / scheduled) if usage_known and scheduled else None,
                "combined_absence_ratio": min(1.0, (selected_hours + other_hours) / scheduled)
                if usage_known and other_known and scheduled
                else None,
                "overbooked": overbooked,
                "unknown_reasons": reasons,
                "schedule_basis": assumption,
                "selected_transaction_ids": [row["id"] for row in selected_rows],
                "other_transaction_ids": [row["id"] for row in others],
            }
        )
    return (
        result,
        rows,
        {
            "year": snapshot["leave_year"],
            "start": snapshot["leave_year_start"],
            "end": snapshot["leave_year_end"],
            "periods": list(periods),
            "schedule_basis": assumption,
            "source": source_identity(snapshot),
            "work_schedule": {
                name: deepcopy(
                    (
                        historical
                        if isinstance(historical, dict)
                        else anchor["snapshot_rules"]["defaults"]
                        if use_current
                        else {}
                    ).get(name)
                )
                for name in ("normal_workdays", "workday_start", "workday_end", "lunch_start", "lunch_end")
            },
            "holidays_enabled": snapshot.get("snapshot_rules", {}).get("holidays", {}).get("enabled", True),
            "holiday_coverage": deepcopy(snapshot.get("calculation_context", {}).get("holiday_coverage", [])),
        },
        warnings,
    )


def _total(rows, key):
    return sum(row[key] for row in rows) if all(row.get(key) is not None for row in rows) else None


def _intervals(rows, threshold, timing):
    result, candidate = [], []

    def finish(terminator, boundary):
        nonlocal candidate
        if candidate and any(row["classification"] == "Full" for row in candidate):
            first, last = candidate[0]["date"], candidate[-1]["date"]
            full = sum(row["classification"] == "Full" for row in candidate)
            incomplete_end = terminator is None or terminator["classification"] == "Unknown"
            result.append(
                {
                    "id": f"{timing}:{first}",
                    "start": first,
                    "end": last,
                    "calendar_days": len(candidate),
                    "fully_absent_workdays": full,
                    "selected_hours": _total(candidate, "selected_hours"),
                    "other_hours": _total(candidate, "other_hours"),
                    "substantial": full >= threshold,
                    "completed": timing == "Recorded Through Cutoff" and not incomplete_end,
                    "incomplete_start": boundary,
                    "incomplete_end": incomplete_end,
                    "at_cutoff": timing == "Recorded Through Cutoff" and terminator is None,
                    "timing": timing,
                    "source_years": sorted({row["source_year"] for row in candidate}),
                    "schedule_bases": sorted({row["schedule_basis"] for row in candidate}),
                    "transaction_refs": [
                        {"source_year": row["source_year"], "id": identity}
                        for row in candidate
                        for identity in (*row["selected_transaction_ids"], *row["other_transaction_ids"])
                    ],
                    "recorded_workdays": full if timing == "Recorded Through Cutoff" else 0,
                    "scheduled_workdays": full if timing == "Scheduled" else 0,
                    "combined_fully_absent_workdays": full,
                    "continuation_of": None,
                }
            )
        candidate = []

    boundary, previous = True, None
    for row in rows:
        if row["classification"] in {"Full", "Nonworking"}:
            if not candidate:
                boundary = previous is None or previous["classification"] == "Unknown"
            candidate.append(row)
        else:
            finish(row, boundary)
        previous = row
    finish(None, boundary)
    return result


def _gaps(rows, intervals):
    substantial = {day for item in intervals if item["substantial"] for day in days(item["start"], item["end"])}
    result, current = [], []

    def finish():
        nonlocal current
        if current:
            first, last = current[0]["date"], current[-1]["date"]
            before = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
            after = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
            result.append(
                {
                    "start": first,
                    "end": last,
                    "calendar_days": len(current),
                    "scheduled_workdays": sum(row["scheduled_hours"] > 0 for row in current),
                    "selected_absence_hours": _total(current, "selected_hours"),
                    "other_absence_hours": _total(current, "other_hours"),
                    "partial_history": before not in substantial or after not in substantial,
                    "basis": "Scheduled workdays between substantial breaks; not confirmed attendance.",
                    "transaction_refs": [
                        {"source_year": row["source_year"], "id": identity}
                        for row in current
                        for identity in (*row["selected_transaction_ids"], *row["other_transaction_ids"])
                    ],
                }
            )
        current = []

    for row in rows:
        if row["classification"] == "Unknown" or row["date"] in substantial:
            finish()
        else:
            current.append(row)
    finish()
    return result


def analyze_breaks(anchor, snapshots, confirmations, parameters: BreakParameters, *, today=None):
    """Analyze selected years on private copies; no store or preference writer."""
    anchor, snapshots, confirmations = deepcopy((anchor, snapshots, confirmations))
    snapshots = {**snapshots, anchor["leave_year"]: anchor}
    cutoff = date.fromisoformat(parameters.cutoff)
    if cutoff.isoformat() != parameters.cutoff or cutoff > (today or date.today()):
        raise ValueError("Cutoff must be an ISO date no later than today.")
    if type(parameters.substantial_workdays) is not int or parameters.substantial_workdays < 1:
        raise ValueError("A substantial break needs at least one fully absent scheduled workday.")
    if parameters.status_basis not in {"effective", "confirmed"}:
        raise ValueError("Unsupported recorded status basis.")
    if parameters.grouping == "custom":
        selected = tuple(parameters.categories)
    elif parameters.grouping in GROUPS:
        selected = GROUPS[parameters.grouping][1]
        if parameters.categories and tuple(parameters.categories) != selected:
            raise ValueError("A preset grouping cannot silently change its category selection.")
    else:
        raise ValueError("Unsupported category grouping.")
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(ABSENCE_CATEGORIES):
        raise ValueError("Select distinct physical absence categories; overtime and FMLA tracking are excluded.")
    years = parameters.years if parameters.years is not None else (anchor["leave_year"],)
    if not years or any(type(y) is not int or y not in snapshots for y in years) or len(set(years)) != len(years):
        raise ValueError("Select one or more distinct, loaded leave years.")
    daily, transactions, metadata, warnings = [], [], [], []
    for year, snapshot in sorted(snapshots.items()):
        if snapshot.get("leave_year") != year:
            raise ValueError(f"Snapshot identity does not match leave year {year}.")
        for key in ("backend", "data_store"):
            if snapshot.get("calculation_context", {}).get(key) != anchor.get("calculation_context", {}).get(key):
                raise ValueError("Selected snapshots must use the same backend and datastore.")
        if year not in years:
            metadata.append(
                {
                    "year": year,
                    "selected": False,
                    "start": snapshot["leave_year_start"],
                    "end": snapshot["leave_year_end"],
                    "periods": [],
                    "schedule_basis": "Not selected",
                }
            )
            continue
        rows, entries, context, issues = _classify(snapshot, anchor, confirmations, selected, parameters)
        daily.extend(rows)
        transactions.extend(entries)
        metadata.append({**context, "selected": True})
        warnings.extend({**w, "year": year} for w in issues)
    daily.sort(key=lambda row: row["date"])
    if len({row["date"] for row in daily}) != len(daily):
        raise ValueError("Selected leave years overlap; dates cannot be counted twice.")
    if not daily[0]["date"] <= parameters.cutoff <= daily[-1]["date"]:
        raise ValueError("Cutoff must lie within the selected years' overall bounds.")
    indexed = {row["date"]: row for row in daily}
    for day in days(daily[0]["date"], daily[-1]["date"]):
        if day not in indexed:
            indexed[day] = {
                "date": day,
                "source_year": None,
                "source_key": None,
                "timing": "Recorded Through Cutoff" if day <= parameters.cutoff else "Scheduled",
                "classification": "Unknown",
                "scheduled_hours": None,
                "selected_hours": None,
                "other_hours": None,
                "known_selected_hours": None,
                "known_other_hours": None,
                "coverage_confirmed": False,
                "unknown_reasons": ["No selected leave-year coverage for this date."],
                "schedule_basis": "Unknown",
                "selected_transaction_ids": [],
                "other_transaction_ids": [],
                "absence_ratio": None,
                "combined_absence_ratio": None,
                "overbooked": False,
            }
    daily = [indexed[day] for day in sorted(indexed)]
    recorded_days = [row for row in daily if row["date"] <= parameters.cutoff]
    future_days = [row for row in daily if row["date"] > parameters.cutoff]
    recorded = _intervals(recorded_days, parameters.substantial_workdays, "Recorded Through Cutoff")
    upcoming = _intervals(future_days, parameters.substantial_workdays, "Scheduled")
    if (
        recorded
        and upcoming
        and recorded[-1]["at_cutoff"]
        and upcoming[0]["start"] == (cutoff + timedelta(days=1)).isoformat()
    ):
        upcoming[0].update(
            continuation_of=recorded[-1]["id"],
            recorded_workdays=recorded[-1]["fully_absent_workdays"],
            combined_fully_absent_workdays=upcoming[0]["fully_absent_workdays"] + recorded[-1]["fully_absent_workdays"],
        )
        upcoming[0]["substantial"] = upcoming[0]["combined_fully_absent_workdays"] >= parameters.substantial_workdays
    gaps = _gaps(recorded_days, recorded)
    qualifying = [item for item in recorded if item["substantial"]]
    completed = [item for item in qualifying if item["completed"]]
    bounded = [item for item in recorded if item["completed"] and not item["incomplete_start"]]
    last = max(completed, key=lambda row: row["end"], default=None)
    ongoing = next((item for item in qualifying if item["at_cutoff"]), None)
    since = [row for row in recorded_days if last is not None and row["date"] > last["end"]]
    since_known = last is not None and all(row["classification"] != "Unknown" for row in since)
    known = [row for row in recorded_days if row["classification"] != "Unknown"]
    usage_days = [row for row in recorded_days if row["selected_hours"] is not None]
    longest = max(
        gaps,
        key=lambda row: (
            row["scheduled_workdays"],
            row["calendar_days"],
            -date.fromisoformat(row["start"]).toordinal(),
        ),
        default=None,
    )
    summary = {
        "cutoff": parameters.cutoff,
        "covered_recorded_days": len(known),
        "unknown_recorded_days": len(recorded_days) - len(known),
        "fully_absent_workdays": sum(row["classification"] == "Full" for row in known) if known else None,
        "partially_absent_workdays": sum(row["classification"] == "Partial" for row in known) if known else None,
        "qualifying_break_count": len(qualifying) if known else None,
        "median_completed_workdays": median([item["fully_absent_workdays"] for item in bounded]) if bounded else None,
        "completed_length_sample_count": len(bounded),
        "selected_recorded_hours": _total(usage_days, "selected_hours") if usage_days else None,
        "other_recorded_hours": _total(usage_days, "other_hours") if usage_days else None,
        "known_usage_recorded_days": len(usage_days),
        "time_since_status": "Break in progress"
        if ongoing
        else "Coverage incomplete since the last observed qualifying break"
        if last and not since_known
        else "Since last completed substantial break"
        if last
        else "Substantial break observed; completion is unknown at a coverage boundary"
        if qualifying
        else "No covered recorded history"
        if not known
        else "No qualifying break in covered history",
        "last_completed_break_end": last["end"] if since_known and not ongoing else None,
        "calendar_days_since": (cutoff - date.fromisoformat(last["end"])).days if since_known and not ongoing else None,
        "scheduled_workdays_since": sum(row["scheduled_hours"] > 0 for row in since)
        if since_known and not ongoing
        else None,
        "contextual_other_hours_since": _total(since, "other_hours") if since_known and not ongoing else None,
        "longest_gap_workdays": longest["scheduled_workdays"] if longest else None,
        "longest_gap_start": longest["start"] if longest else None,
        "longest_gap_end": longest["end"] if longest else None,
        "longest_gap_calendar_days": longest["calendar_days"] if longest else None,
        "longest_gap_partial_history": longest["partial_history"] if longest else None,
        "longest_gap_other_hours": longest["other_absence_hours"] if longest else None,
    }
    distribution = []
    for label, lower, upper in (
        ("One workday", 1, 1),
        ("Two workdays", 2, 2),
        ("Three to four workdays", 3, 4),
        ("Five or more workdays", 5, None),
    ):

        def in_bucket(item):
            return item["fully_absent_workdays"] >= lower and (upper is None or item["fully_absent_workdays"] <= upper)

        distribution.append(
            {
                "label": label,
                "completed_count": sum(in_bucket(item) for item in bounded) if known else None,
                "incomplete_count": sum(
                    in_bucket(item) for item in recorded if not item["completed"] or item["incomplete_start"]
                )
                if known
                else None,
                "basis": "Completed, fully bounded intervals; ongoing/truncated observed lengths are separate lower bounds.",
            }
        )
    day_distribution = [
        {
            "classification": value,
            "days": sum(row["classification"] == value for row in recorded_days)
            if known or value == "Unknown"
            else None,
        }
        for value in ("Full", "Partial", "No selected absence", "Nonworking", "Unknown")
    ]
    timing = []
    for basis in ("Month", "Quarter"):
        buckets = {}
        for row in recorded_days:
            stamp = date.fromisoformat(row["date"])
            label = row["date"][:7] if basis == "Month" else f"{stamp.year}-Q{(stamp.month - 1) // 3 + 1}"
            buckets.setdefault(label, []).append(row)
        for label, rows in sorted(buckets.items()):
            covered_rows = [row for row in rows if row["classification"] != "Unknown"]
            usage_rows = [row for row in rows if row["selected_hours"] is not None]
            timing.append(
                {
                    "basis": basis,
                    "period": label,
                    "start": rows[0]["date"],
                    "end": rows[-1]["date"],
                    "full_days": sum(row["classification"] == "Full" for row in rows) if covered_rows else None,
                    "partial_days": sum(row["classification"] == "Partial" for row in rows) if covered_rows else None,
                    "selected_hours": _total(usage_rows, "selected_hours") if usage_rows else None,
                    "other_hours": _total(usage_rows, "other_hours") if usage_rows else None,
                    "unknown_days": len(rows) - len(covered_rows),
                    "usage_covered_days": len(usage_rows),
                }
            )
    return BreakAnalysis(
        parameters,
        tuple(selected),
        source_identity(anchor),
        summary,
        tuple(daily),
        tuple(recorded),
        tuple(upcoming),
        tuple(gaps),
        tuple(distribution),
        tuple(day_distribution),
        tuple(timing),
        tuple(metadata),
        tuple(sorted(transactions, key=lambda row: (row["date"], row["source_year"], str(row["id"])))),
        tuple(warnings),
    )
