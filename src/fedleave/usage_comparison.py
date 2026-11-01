"""Pure cumulative absence comparisons over explicit read-only coverage.

Balances, accrual tiers and prediction are deliberately absent from this model.
All intervals are inclusive. Unknown observations remain None, including inside
curves; callers must not interpolate across missing coverage or alignment.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .categories import CATEGORY_POLICIES
from .history import CONFIRMED_STATUSES, coverage_key, coverage_status, days, represented_periods
from .planning import source_identity, working_calendar
from .transaction_effects import TRANSACTION_DIRECTIONS, signed_balance_effect, transaction_is_effective

ABSENCE_CATEGORIES = tuple(category for category in CATEGORY_POLICIES if category not in {"overtime", "fmla"})
ALIGNMENTS = {"progress": "Leave-year progress", "calendar": "Calendar date"}


@dataclass(frozen=True)
class ComparisonParameters:
    cutoff: str
    categories: tuple[str, ...] = ("annual",)
    reference_years: tuple[int, ...] | None = None
    excluded_years: tuple[int, ...] = ()
    alignment: str = "progress"
    status_basis: str = "effective"
    assume_current_schedule: bool = False


@dataclass(frozen=True)
class UsageComparison:
    parameters: ComparisonParameters
    source: dict
    summary: dict
    points: tuple[dict, ...]
    observations: tuple[dict, ...]
    history: tuple[dict, ...]
    transactions: tuple[dict, ...]
    warnings: tuple[dict, ...]
    schema_version: int = 1
    method_version: str = "cumulative-usage-1"


def aligned_date(target, reference, day, alignment="progress"):
    """Map actual period ordinal/offset, or an exact represented month/day."""
    value = date.fromisoformat(day)
    if alignment == "progress":
        periods = represented_periods(target, strict=False)
        index, period = next((i, p) for i, p in enumerate(periods) if p["start"] <= day <= p["end"])
        references = represented_periods(reference, strict=False)
        if index >= len(references):
            return None
        offset = (value - date.fromisoformat(period["start"])).days
        mapped = date.fromisoformat(references[index]["start"]) + timedelta(days=offset)
        return mapped.isoformat() if mapped.isoformat() <= references[index]["end"] else None
    if alignment != "calendar":
        raise ValueError("Unsupported comparison alignment.")
    start, end = reference["leave_year_start"], reference["leave_year_end"]
    candidates = [candidate for candidate in days(start, end) if candidate[5:] == day[5:]]
    # Prefer the same calendar-year offset when a long year has two Januaries.
    offset = value.year - date.fromisoformat(target["leave_year_start"]).year
    preferred_year = date.fromisoformat(start).year + offset
    preferred = next(
        (candidate for candidate in candidates if date.fromisoformat(candidate).year == preferred_year), None
    )
    return preferred or (candidates[0] if len(candidates) == 1 else None)


def percentile(values, fraction):
    """Linear interpolation at index (n - 1) * p; no rounding."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _schedule(snapshot, target, assume_current):
    private = deepcopy(snapshot)
    historical = private.get("calculation_context", {}).get("historical_work_schedule")
    if assume_current:
        private["snapshot_rules"]["defaults"].update(deepcopy(target["snapshot_rules"]["defaults"]))
        basis = "Explicit analysis assumption: apply the target's current configured schedule to all compared years."
    elif isinstance(historical, dict):
        required = {"normal_workdays", "workday_start", "workday_end", "lunch_start", "lunch_end"}
        if not required <= historical.keys():
            return (
                dict.fromkeys(days(snapshot["leave_year_start"], snapshot["leave_year_end"])),
                ("Backend historical roster is incomplete; normalized usage is N/A."),
                [
                    {
                        "code": "INCOMPLETE_HISTORICAL_ROSTER",
                        "message": "Supply workdays and all tour/lunch times for historical normalization.",
                    }
                ],
            )
        private["snapshot_rules"]["defaults"].update(historical)
        basis = "Explicit backend-supplied historical work schedule."
    else:
        return (
            dict.fromkeys(days(snapshot["leave_year_start"], snapshot["leave_year_end"])),
            (
                "Historical roster unavailable; normalized usage is N/A. Enable the explicit current-schedule assumption if appropriate."
            ),
            [],
        )
    warnings = []
    calendar, _ = working_calendar(private, private["leave_year_start"], private["leave_year_end"], warnings)
    return calendar, basis, [asdict(w) for w in warnings]


def _prepare(snapshot, target, coverage, parameters, cutoff):
    periods, covered = coverage_status(snapshot, coverage, strict=False)
    year, key = snapshot["leave_year"], coverage_key(snapshot)
    calendar, assumption, warnings = _schedule(snapshot, target, parameters.assume_current_schedule)
    rows, invalid = [], set()
    for original in snapshot.get("transactions", []):
        if not isinstance(original, dict):
            invalid.add("*")
            warnings.append({"code": "INVALID_USAGE", "message": "A transaction is not an object."})
            continue
        category, direction = original.get("category"), original.get("direction")
        if category not in ABSENCE_CATEGORIES and category not in ("fmla", "overtime"):
            warnings.append(
                {
                    "code": "UNSUPPORTED_CATEGORY",
                    "message": f"Unsupported absence category: {category!r}.",
                    "transaction_id": original.get("id"),
                }
            )
        if category not in parameters.categories:
            continue
        if direction in TRANSACTION_DIRECTIONS and direction != "used":
            continue
        day = original.get("date")
        try:
            # Canonical status/void handling takes precedence over malformed
            # details on an ineffective record.
            if not transaction_is_effective(original):
                continue
            if direction != "used":
                raise ValueError(f"Unsupported transaction direction: {direction!r}.")
            if not original.get("id") or original.get("hours") is None:
                raise ValueError("Usage needs an original transaction ID and hours.")
            if isinstance(original["hours"], bool):
                raise ValueError("Usage hours must be numeric, not a boolean.")
            effect = signed_balance_effect(original)
            if effect == 0:
                continue
            if date.fromisoformat(day).isoformat() != day or day not in calendar:
                raise ValueError("Usage date is outside the represented year or is not an ISO date.")
            status = str(original.get("status", "planned")).strip().lower() or "planned"
            recorded = cutoff is not None and day <= cutoff
            if recorded and status in {"planned", "requested"}:
                warnings.append(
                    {
                        "code": "UNRESOLVED_RECORDED_STATUS",
                        "message": "Recorded Through Cutoff includes a planned/requested row; its date does not prove leave was taken.",
                        "transaction_id": original["id"],
                        "date": day,
                    }
                )
            if (
                parameters.status_basis == "confirmed"
                and (year != target["leave_year"] or recorded)
                and status not in CONFIRMED_STATUSES
            ):
                continue
            rows.append(
                {
                    **deepcopy(original),
                    "hours": -effect,
                    "status": status,
                    "source_year": year,
                    "source_key": key,
                    "coverage_confirmed": day in covered,
                    "timing": "Recorded Through Cutoff"
                    if recorded
                    else "Scheduled"
                    if year == target["leave_year"]
                    else "Historical context beyond aligned cutoff",
                }
            )
        except (TypeError, ValueError, KeyError) as exc:
            invalid.add(day if isinstance(day, str) and day in calendar else "*")
            warnings.append(
                {"code": "INVALID_USAGE", "message": str(exc), "date": day, "transaction_id": original.get("id")}
            )
    rows.sort(key=lambda row: (row["date"], str(row["id"])))
    by_date = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(row)
    observations, total, exposure, ids = {}, 0.0, 0.0, []
    complete, valid, exposure_known = True, "*" not in invalid, True
    for day in calendar:
        total += sum(row["hours"] for row in by_date.get(day, ()))
        ids.extend(row["id"] for row in by_date.get(day, ()))
        complete = complete and day in covered
        valid = valid and day not in invalid
        exposure_known = exposure_known and calendar[day] is not None
        exposure += calendar[day] or 0
        hours = total if complete and valid else None
        reason = (
            "Malformed usage at/before this point."
            if not valid
            else "Coverage unconfirmed or stale before this point."
            if not complete
            else None
        )
        observations[day] = {
            "year": year,
            "mapped_date": day,
            "hours": hours,
            "known_entered_hours": total,
            "coverage_complete": complete,
            "usage_valid": valid,
            "missing_reason": reason,
            "exposure_hours": exposure if exposure_known else None,
            "hours_per_100": hours * 100 / exposure if hours is not None and exposure_known and exposure > 0 else None,
            "transaction_ids": list(ids),
            "source_key": key,
            "schedule_basis": assumption,
        }
    return observations, rows, periods, assumption, [{**w, "year": year} for w in warnings]


def compare_usage(target, history, coverage, parameters: ComparisonParameters, *, today=None):
    """Compare exact effective usage; input snapshots and confirmations are never mutated."""
    target, history, coverage = deepcopy((target, history, coverage))
    today = today or date.today()
    cutoff = date.fromisoformat(parameters.cutoff)
    if (
        cutoff.isoformat() != parameters.cutoff
        or not target["leave_year_start"] <= parameters.cutoff <= target["leave_year_end"]
    ):
        raise ValueError("Cutoff must be an ISO date inside the target leave year.")
    if cutoff > today:
        raise ValueError("Recorded cutoff cannot be after today; later usage is Scheduled.")
    if (
        not parameters.categories
        or len(set(parameters.categories)) != len(parameters.categories)
        or set(parameters.categories) - set(ABSENCE_CATEGORIES)
    ):
        raise ValueError(
            "Select one or more distinct absence categories; overtime and FMLA tracking are not physical absence."
        )
    if parameters.alignment not in ALIGNMENTS or parameters.status_basis not in {"effective", "confirmed"}:
        raise ValueError("Unsupported alignment or status filter.")
    represented_periods(target, strict=False)
    references = parameters.reference_years
    if references is None:
        references = tuple(
            sorted(y for y, s in history.items() if s["leave_year_end"] < target["leave_year_start"])[-5:]
        )
    if len(set(references)) != len(references) or any(
        type(y) is not int for y in (*references, *parameters.excluded_years)
    ):
        raise ValueError("Reference and excluded years must be integer year labels without duplicate references.")
    if target["leave_year"] in references:
        raise ValueError("The target year cannot also be a reference year.")
    prepared, metadata, transactions, warnings = {}, [], [], []
    for year in (
        target["leave_year"],
        *sorted((set(history) | set(references) | set(parameters.excluded_years)) - {target["leave_year"]}),
    ):
        snapshot = target if year == target["leave_year"] else history.get(year)
        reason = None
        if year != target["leave_year"]:
            if year in parameters.excluded_years:
                reason = "Explicitly excluded by the user."
            elif year not in references:
                reason = "Not selected as a reference."
            elif snapshot is None:
                reason = "Selected reference could not be loaded; no zero usage is assumed."
            elif snapshot["leave_year_end"] >= target["leave_year_start"]:
                reason = "Reference must end before the target leave year starts."
        periods, assumption, mapped_cutoff = (), "Unavailable", None
        if snapshot is not None:
            try:
                if snapshot.get("leave_year") != year:
                    raise ValueError("Snapshot year label disagrees with the selected reference year.")
                mapped_cutoff = (
                    parameters.cutoff
                    if snapshot is target
                    else aligned_date(target, snapshot, parameters.cutoff, parameters.alignment)
                )
                observations, rows, periods, assumption, issues = _prepare(
                    snapshot, target, coverage, parameters, mapped_cutoff
                )
                if reason is None:
                    prepared[year] = observations
                    transactions.extend(rows)
                    warnings.extend(issues)
            except (TypeError, ValueError, KeyError) as exc:
                if snapshot is target:
                    raise ValueError(f"Target context is invalid: {exc}") from exc
                reason = reason or f"Invalid reference context: {exc}"
        metadata.append(
            {
                "year": year,
                "target": year == target["leave_year"],
                "selected": year in references,
                "start": snapshot.get("leave_year_start") if snapshot else None,
                "end": snapshot.get("leave_year_end") if snapshot else None,
                "periods": list(periods),
                "aligned_cutoff": mapped_cutoff,
                "schedule_basis": assumption,
                "exclusion_reason": reason,
            }
        )
    points, details = [], []
    target_year = target["leave_year"]
    target_cutoff = prepared[target_year][parameters.cutoff]
    target_periods = represented_periods(target, strict=False)
    for day in days(target["leave_year_start"], target["leave_year_end"]):
        period = next(p for p in target_periods if p["start"] <= day <= p["end"])
        current = prepared[target_year][day]
        recorded = current["hours"] if day <= parameters.cutoff else None
        future_hours = (
            current["known_entered_hours"] - target_cutoff["known_entered_hours"] if day >= parameters.cutoff else None
        )
        scheduled = (
            target_cutoff["hours"] + future_hours
            if day >= parameters.cutoff and target_cutoff["hours"] is not None and current["usage_valid"]
            else None
        )
        details.append(
            {
                **current,
                "date": day,
                "role": "Target",
                "timing": "Recorded Through Cutoff" if day <= parameters.cutoff else "Scheduled",
                "hours": recorded if day <= parameters.cutoff else scheduled,
                "hours_per_100": current["hours_per_100"] if day <= parameters.cutoff else None,
            }
        )
        values = []
        for year in references:
            source = history.get(year)
            mapped = aligned_date(target, source, day, parameters.alignment) if year in prepared else None
            observation = (
                prepared[year][mapped]
                if mapped
                else {
                    "year": year,
                    "mapped_date": None,
                    "hours": None,
                    "transaction_ids": [],
                    "missing_reason": next(m["exclusion_reason"] for m in metadata if m["year"] == year)
                    or "No exact equivalent period/day or calendar date.",
                }
            )
            details.append(
                {
                    **observation,
                    "date": day,
                    "role": "Reference",
                    "timing": "Recorded Through Cutoff"
                    if day <= parameters.cutoff
                    else "Historical context beyond aligned cutoff",
                }
            )
            if observation["hours"] is not None:
                values.append(observation["hours"])
        median = percentile(values, 0.5)
        difference = recorded - median if recorded is not None and median is not None else None
        points.append(
            {
                "date": day,
                "period_id": period["period_id"],
                "day_offset": (date.fromisoformat(day) - date.fromisoformat(period["start"])).days,
                "recorded": recorded,
                "scheduled": scheduled,
                "future_scheduled_hours": future_hours,
                "observation_count": len(values),
                "median": median,
                "p20": percentile(values, 0.2),
                "p80": percentile(values, 0.8),
                "band_lower": percentile(values, 0.2) if len(values) >= 3 else None,
                "band_upper": percentile(values, 0.8) if len(values) >= 3 else None,
                "difference": difference,
                "percentage_difference": difference * 100 / median if difference is not None and median else None,
                "hours_per_100": current["hours_per_100"] if day <= parameters.cutoff else None,
                **{f"reference_{row['year']}": row["hours"] for row in details[-len(references) :] if references},
            }
        )
    summary = deepcopy(next(point for point in points if point["date"] == parameters.cutoff))
    summary.update(
        target_missing_reason=target_cutoff["missing_reason"],
        target_exposure_hours=target_cutoff["exposure_hours"],
        alignment=ALIGNMENTS[parameters.alignment],
        categories=list(parameters.categories),
        status_basis=parameters.status_basis,
        limited_history=summary["observation_count"] < 3,
        history_label="No eligible history"
        if summary["observation_count"] == 0
        else "Limited history"
        if summary["observation_count"] < 3
        else "Selected historical range (not a confidence interval)",
    )
    return UsageComparison(
        parameters,
        source_identity(target),
        summary,
        tuple(points),
        tuple(details),
        tuple(metadata),
        tuple(transactions),
        tuple(warnings),
    )
