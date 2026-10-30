"""Deterministic historical usage scenarios on the shared pure projection engine.

Only data enters this module. Neither forecasts nor retrospective checks have
access to a datastore, backend, filesystem, preference writer or persistence.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from math import floor, isfinite

from .allocation import apportion_units as _apportion
from .allocation import hours_for_units as _hours
from .allocation import whole_units as _units
from .history import CONFIRMED_STATUSES, HistoricalYear, prepare_history
from .planning import (
    ProjectionResult,
    make_operation,
    new_scenario,
    project,
    scheduled_transactions,
    source_identity,
    time_increment,
    working_calendar,
)
from .transaction_effects import INEFFECTIVE_STATUSES, TRANSACTION_STATUSES

SCHEMA_VERSION = 1
METHOD_VERSION = "month-exposure-median-p80-v1"
RETROSPECTIVE_LIMITATION = (
    "Retrospective results use presently available historical records. They do not reconstruct which transactions "
    "were scheduled, approved, or known at the evaluated historical cutoff. These checks validate historical usage "
    "estimation rather than the operational accuracy of forecasts issued at that time."
)


@dataclass(frozen=True)
class ForecastParameters:
    cutoff: str
    horizon: str
    categories: tuple[str, ...] = ("annual",)
    reference_years: tuple[int, ...] | None = None
    excluded_years: tuple[int, ...] = ()
    status_basis: str = "effective"
    reserves: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ForecastScenario:
    name: str
    projection: ProjectionResult | None
    monthly: tuple[dict, ...]
    summaries: tuple[dict, ...]
    allocations: tuple[dict, ...]


@dataclass(frozen=True)
class ForecastResult:
    source: dict
    parameters: ForecastParameters
    scenarios: dict[str, ForecastScenario]
    history: tuple[dict, ...]
    source_transactions: tuple[dict, ...]
    assumptions: dict
    warnings: tuple[dict, ...]
    schema_version: int = SCHEMA_VERSION
    method_version: str = METHOD_VERSION

    def to_dict(self):
        return asdict(self)


def percentile(values, quantile):
    """Linear interpolation at (n - 1) * q, retaining unrounded values."""
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * quantile
    lower = floor(index)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (index - lower)


def month_segments(cutoff, horizon):
    day, last = date.fromisoformat(cutoff) + timedelta(days=1), date.fromisoformat(horizon)
    result = []
    while day <= last:
        following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
        end = min(last, following - timedelta(days=1))
        result.append((day.isoformat(), end.isoformat(), day.month))
        day = end + timedelta(days=1)
    return tuple(result)


def allocate_demand(demand: dict[str, float], capacity: dict[str, float | None], increment: float):
    """Share date capacity proportionally; balance availability never caps use."""
    date_units = {day: _units(hours or 0, increment) for day, hours in sorted(capacity.items())}
    category_caps = {category: _units(hours, increment) for category, hours in demand.items()}
    category_units = _apportion(sum(date_units.values()), demand, category_caps)
    rows = []
    # Quotas are fixed before date placement: no category receives priority for
    # scarce total capacity. Each category then uses proportional remaining dates.
    for category in sorted(demand):
        allocation = _apportion(category_units[category], date_units, date_units)
        for day, units in sorted(allocation.items()):
            if units:
                rows.append({"date": day, "category": category, "hours": _hours(units, increment)})
                date_units[day] -= units
    return tuple(rows)


def _validate(parameters):
    if (
        not parameters.categories
        or len(set(parameters.categories)) != len(parameters.categories)
        or set(parameters.categories) - {"annual", "sick"}
    ):
        raise ValueError("Select annual, sick, or combined annual/sick forecasting.")
    if parameters.status_basis not in {"effective", "confirmed"}:
        raise ValueError("Choose effective or confirmed historical status filtering.")
    if any(type(year) is not int for year in (*(parameters.reference_years or ()), *parameters.excluded_years)):
        raise ValueError("Historical year selections must be integer leave-year identities.")
    if set(parameters.reserves) - set(parameters.categories):
        raise ValueError("Reserves must belong to selected forecast categories.")
    for value in parameters.reserves.values():
        if isinstance(value, bool) or not isfinite(float(value)) or float(value) < 0:
            raise ValueError("Reserves must be finite nonnegative hours.")


def _history(target, snapshots, confirmations, parameters, warnings):
    candidates, reasons = {}, {}
    for year, snapshot in sorted(snapshots.items()):
        try:
            if snapshot["leave_year"] != year:
                raise ValueError("Historical snapshot identity does not match its requested leave year.")
            for key in ("data_store", "backend"):
                if snapshot.get("calculation_context", {}).get(key) != target.get("calculation_context", {}).get(key):
                    raise ValueError("Historical snapshots must come from the same selected backend and datastore.")
            if year == target["leave_year"] or snapshot["leave_year_end"] >= target["leave_year_start"]:
                raise ValueError("Current/future/overlapping leave years cannot train this forecast.")
            candidates[year] = prepare_history(
                snapshot, target, confirmations, cutoff=parameters.cutoff, status_basis=parameters.status_basis
            )
        except (ValueError, TypeError, KeyError) as exc:
            reasons[year] = str(exc)
    selected = (
        set(parameters.reference_years)
        if parameters.reference_years is not None
        else set(sorted(candidates, key=lambda year: (candidates[year].end, year))[-5:])
    )
    rows, eligible = [], []
    for year in sorted(set(snapshots) | selected):
        reason = reasons.get(year)
        if year not in selected:
            reason = reason or "Not selected as a reference year."
        elif year in parameters.excluded_years:
            reason = "Manually excluded by the user."
        elif year not in candidates:
            reason = reason or "Historical snapshot is unavailable."
        candidate = candidates.get(year)
        if candidate is not None:
            warnings.extend(deepcopy(candidate.warnings))
        rows.append(
            {
                "year": year,
                "selected": year in selected,
                "excluded": year in parameters.excluded_years,
                "eligible": reason is None,
                "exclusion_reason": reason,
                "source": source_identity(snapshots[year]) if year in snapshots else None,
                "periods": deepcopy(candidate.periods) if candidate else (),
                "schedule_assumption": candidate.schedule_assumption if candidate else None,
            }
        )
        if reason is None:
            eligible.append(candidate)
    return tuple(eligible), tuple(rows)


def _explanation(histories: tuple[HistoricalYear, ...], category, month, exposure):
    seasonal = [year.observation(category, month) for year in histories]
    fallback = [year.observation(category) for year in histories]
    seasonal_eligible = [row for row in seasonal if row["eligible"]]
    fallback_eligible = [row for row in fallback if row["eligible"]]
    chosen = seasonal_eligible if len(seasonal_eligible) >= 3 else fallback_eligible
    method = "Calendar-month seasonal" if len(seasonal_eligible) >= 3 else "Whole-year fallback"
    if not chosen or exposure is None:
        method = "Scheduled only — unavailable history/exposure"
    estimates = [row["rate"] * exposure for row in chosen] if exposure is not None else []
    typical, higher = percentile(estimates, 0.5), percentile(estimates, 0.8)
    return {
        "seasonal_observations": seasonal,
        "fallback_observations": fallback,
        "eligible_seasonal_years": [r["year"] for r in seasonal_eligible],
        "eligible_fallback_years": [r["year"] for r in fallback_eligible],
        "source_years": [r["year"] for r in chosen],
        "per_year_rates": chosen,
        "observation_count": len(chosen),
        "estimator": method,
        "limited_history": 0 < len(chosen) < 3,
        "typical": typical,
        "higher": max(typical, higher) if typical is not None else None,
    }


def _full_demand(snapshot, category, horizon, balance, unallocated):
    if balance is None or unallocated is None:
        return None, "The category balance or estimated demand is unknown."
    if unallocated <= 1e-8:
        return balance, None
    rules = snapshot.get("snapshot_rules", {}).get("rules", {}).get(category, {})
    if rules.get("expires") or (category == "annual" and horizon == snapshot["leave_year_end"]):
        return (
            None,
            "Undated demand has timing-dependent expiration or year-end carryover effects; full-demand balance is N/A.",
        )
    return (
        balance - unallocated,
        "Hypothetical sensitivity only; unallocated demand has no invented dates or daily path.",
    )


def forecast(
    target: dict, snapshots: dict[int, dict], confirmations, parameters: ForecastParameters, *, today: date
) -> ForecastResult:
    """Scheduled baseline plus independent Typical/Higher historical scenarios."""
    parameters = deepcopy(parameters)
    _validate(parameters)
    target, snapshots, confirmations = deepcopy((target, snapshots, confirmations))
    definition = replace(
        new_scenario(target, today=today, cutoff=parameters.cutoff, horizon=parameters.horizon, name="Scheduled"),
        reserves=deepcopy(parameters.reserves),
    )
    baseline = project(target, definition, today=today)
    warnings = [asdict(w) for w in baseline.warnings]
    histories, history_rows = _history(target, snapshots, confirmations, parameters, warnings)
    calendar_warnings = []
    calendar, schedule = working_calendar(target, parameters.cutoff, parameters.horizon, calendar_warnings)
    warnings.extend(asdict(w) for w in calendar_warnings)
    scheduled = scheduled_transactions(target, parameters.cutoff, parameters.horizon)
    segments = month_segments(parameters.cutoff, parameters.horizon)
    explanations = []
    for start, end, month in segments:
        values = [value for day, value in calendar.items() if start <= day <= end]
        exposure = sum(values) if all(value is not None for value in values) else None
        for category in sorted(parameters.categories):
            explanation = _explanation(histories, category, month, exposure)
            row = {
                "category": category,
                "start": start,
                "end": end,
                "month": month,
                "exposure": exposure,
                **explanation,
                "scheduled_hours": sum(
                    float(tx["hours"]) for tx in scheduled if tx["category"] == category and start <= tx["date"] <= end
                ),
            }
            explanations.append(row)
            if explanation["limited_history"]:
                warnings.append(
                    {
                        "code": "LIMITED_HISTORY",
                        "message": "Limited history: fewer than three eligible whole-year observations.",
                        "category": category,
                        "date": start,
                    }
                )
            if explanation["typical"] is None:
                warnings.append(
                    {
                        "code": "UNAVAILABLE_HISTORICAL_ESTIMATE",
                        "message": "No eligible confirmed history or known exposure for this month segment; retain Scheduled only.",
                        "category": category,
                        "date": start,
                    }
                )
    scenarios = {}
    increment = time_increment(target)
    baseline_capacity = {row.date: row.remaining_capacity for row in baseline.capacity if row.date > parameters.cutoff}
    for name in ("scheduled", "typical", "higher"):
        rows, allocations = [], []
        for start, end, _ in segments:
            segment_rows = [row for row in explanations if row["start"] == start]
            demand = {
                row["category"]: max(0, row[name] - row["scheduled_hours"])
                for row in segment_rows
                if name != "scheduled" and row[name] is not None
            }
            placed = allocate_demand(
                demand, {day: hours for day, hours in baseline_capacity.items() if start <= day <= end}, increment
            )
            allocations.extend(
                {
                    **row,
                    "scenario": name,
                    "timing": "Estimated",
                    "source_id": f"forecast:{name}:{row['category']}:{row['date']}",
                }
                for row in placed
            )
            for explanation in segment_rows:
                category = explanation["category"]
                estimate = explanation.get(name)
                additional = demand.get(category) if name != "scheduled" else 0.0
                allocated = sum(row["hours"] for row in placed if row["category"] == category)
                unallocated = max(0, additional - allocated) if additional is not None else None
                rows.append(
                    {
                        **deepcopy(explanation),
                        "scenario": name,
                        "estimated_total_hours": estimate,
                        "additional_estimated_hours": additional,
                        "allocated_hours": allocated,
                        "unallocated_hours": unallocated,
                        "allocation_complete": unallocated is not None and unallocated < 1e-8,
                    }
                )
        available = name == "scheduled" or not segments or any(row["estimated_total_hours"] is not None for row in rows)
        projection = None
        if available:
            operations = tuple(
                make_operation(
                    target,
                    row_id=row["source_id"],
                    operation="add",
                    date=row["date"],
                    category=row["category"],
                    hours=row["hours"],
                    note=f"{name.title()} historical usage estimate; {METHOD_VERSION}",
                )
                for row in allocations
            )
            projection = (
                baseline
                if name == "scheduled"
                else project(
                    target,
                    replace(definition, name=f"{name.title()} Usage — allocated", operations=operations),
                    today=today,
                )
            )
            if name != "scheduled":
                projection = replace(
                    projection,
                    events=tuple(
                        replace(
                            event, timing="Estimated", explanation=f"Estimated historical usage. {event.explanation}"
                        )
                        if event.scenario_row_id
                        else event
                        for event in projection.events
                    ),
                )
                warnings.extend({**asdict(w), "forecast_scenario": name} for w in projection.warnings)
        summaries = []
        for category in sorted(parameters.categories):
            category_rows = [row for row in rows if row["category"] == category]
            known = (
                name == "scheduled"
                or not segments
                or any(row["estimated_total_hours"] is not None for row in category_rows)
            )
            complete = all(row["allocation_complete"] for row in category_rows)
            unknown = any(row["unallocated_hours"] is None for row in category_rows)
            unallocated = None if unknown else sum(row["unallocated_hours"] for row in category_rows)
            summary = (
                next((row.scenario for row in projection.categories if row.category == category), None)
                if projection and known
                else None
            )
            balance = summary.horizon_balance if summary else None
            hypothetical, reason = _full_demand(target, category, parameters.horizon, balance, unallocated)
            summaries.append(
                {
                    "category": category,
                    "scenario": name,
                    "available": known,
                    "allocation_complete": complete,
                    "estimated_total_hours": None
                    if unknown
                    else sum(row["estimated_total_hours"] or 0 for row in category_rows),
                    "scheduled_hours": sum(row["scheduled_hours"] for row in category_rows),
                    "additional_estimated_hours": None
                    if unknown
                    else sum(row["additional_estimated_hours"] for row in category_rows),
                    "allocated_hours": sum(row["allocated_hours"] for row in category_rows),
                    "unallocated_hours": unallocated,
                    "allocated_horizon_balance": balance,
                    "hypothetical_full_demand_balance": hypothetical,
                    "full_demand_explanation": reason,
                    **(asdict(summary) if summary else {"horizon_balance": None}),
                }
            )
            if name != "scheduled" and not complete:
                warnings.append(
                    {
                        "code": "INCOMPLETE_ALLOCATION",
                        "message": "The daily curve includes allocated estimates only; missing history and unallocated demand are not assigned fictional dates.",
                        "category": category,
                        "forecast_scenario": name,
                        "unallocated_hours": unallocated,
                    }
                )
            if unallocated and name != "scheduled":
                warnings.append(
                    {
                        "code": "INSUFFICIENT_WORK_CAPACITY",
                        "message": "Demand exceeds usable work-date capacity or leaves a residual below the configured time increment.",
                        "category": category,
                        "forecast_scenario": name,
                        "unallocated_hours": unallocated,
                    }
                )
        # A monthly balance is the exact closing value from the same projection.
        daily = {(row.category, row.date): row.scenario for row in projection.daily} if projection else {}
        available_categories = {row["category"] for row in summaries if row["available"]}
        rows = [
            {
                **row,
                "allocated_closing_balance": daily.get((row["category"], row["end"]))
                if row["category"] in available_categories
                else None,
            }
            for row in rows
        ]
        scenarios[name] = ForecastScenario(name, projection, tuple(rows), tuple(summaries), tuple(allocations))
    source_rows = tuple(
        {
            **deepcopy(tx),
            "source_year": year.year,
            "source_key": year.source_key,
            "coverage_confirmed": tx["date"] in year.covered,
        }
        for year in histories
        for tx in year.transactions
    )
    return ForecastResult(
        source_identity(target),
        parameters,
        scenarios,
        history_rows,
        source_rows,
        {
            "units": "hours",
            "daily_values": "Daily closing balances; no intraday certainty.",
            "schedule": schedule,
            "historical_schedules": {year.year: year.schedule_assumption for year in histories},
            "historical_basis": parameters.status_basis,
            "historical_statuses": CONFIRMED_STATUSES
            if parameters.status_basis == "confirmed"
            else tuple(status for status in TRANSACTION_STATUSES if status not in INEFFECTIVE_STATUSES),
            "percentile": "Linear interpolation: index = (n - 1) * 0.8; Higher is at least Typical.",
            "time_increment_hours": increment,
            "allocation": "Proportional category quotas, largest remainders; stable category/date ordering. Sub-increment residuals remain explicit unallocated demand.",
            "historical_coverage": deepcopy(confirmations),
            "retrospective_limitation": RETROSPECTIVE_LIMITATION,
            "retrospective_error_definition": "Estimated minus later recorded hours; positive error means overestimated usage.",
            "scenario_range": "Historical planning scenarios, not confidence intervals or calibrated probabilities.",
        },
        tuple(warnings),
    )


@dataclass(frozen=True)
class RetrospectiveResult:
    rows: tuple[dict, ...]
    summaries: tuple[dict, ...]
    warnings: tuple[dict, ...]
    limitation: str = RETROSPECTIVE_LIMITATION
    schema_version: int = SCHEMA_VERSION
    method_version: str = METHOD_VERSION

    def to_dict(self):
        return asdict(self)


def retrospective_check(
    snapshots: dict[int, dict],
    confirmations,
    evaluation_year: int,
    *,
    today: date,
    categories=("annual",),
    status_basis="effective",
    excluded_years=(),
    reference_years=None,
    cutoffs=None,
) -> RetrospectiveResult:
    """Validate future *usage estimation*, never reconstructed past bookings.

    Forecast totals are compared with later recorded use in a completed year.
    The present target ledger's scheduled rows are neither treated as known at
    an earlier cutoff nor subtracted from the estimates being evaluated.
    """
    snapshots, confirmations = deepcopy((snapshots, confirmations))
    target = snapshots[evaluation_year]
    if target["leave_year_end"] >= today.isoformat():
        raise ValueError("Select a completed historical year for a retrospective usage check.")
    actual = prepare_history(target, target, confirmations, cutoff=target["leave_year_end"], status_basis=status_basis)
    valid_cutoffs = {period["end"] for period in actual.periods if period["end"] < actual.end}
    selected = sorted(valid_cutoffs if cutoffs is None else set(cutoffs))
    if not set(selected) <= valid_cutoffs:
        raise ValueError("Retrospective cutoffs must be represented pay-period-end dates before year end.")
    warnings, rows = list(deepcopy(actual.warnings)), []
    for cutoff in selected:
        parameters = ForecastParameters(
            cutoff,
            actual.end,
            tuple(categories),
            excluded_years=tuple(excluded_years),
            status_basis=status_basis,
            reference_years=tuple(reference_years) if reference_years is not None else None,
        )
        _validate(parameters)
        histories, _ = _history(target, snapshots, confirmations, parameters, warnings)
        for category in sorted(categories):
            future = [day for day in actual.calendar if cutoff < day <= actual.end]
            usable_actual = (
                all(day in actual.covered for day in future)
                and "*" not in actual.invalid_dates.get(category, ())
                and not any(day in actual.invalid_dates.get(category, ()) for day in future)
            )
            actual_hours = (
                sum(tx["hours"] for tx in actual.transactions if tx["category"] == category and tx["date"] > cutoff)
                if usable_actual
                else None
            )
            explanations, whole_estimates = [], []
            for start, end, month in month_segments(cutoff, actual.end):
                exposure_values = [value for day, value in actual.calendar.items() if start <= day <= end]
                exposure = sum(exposure_values) if all(value is not None for value in exposure_values) else None
                explanation = _explanation(histories, category, month, exposure)
                explanations.append({"start": start, "end": end, **explanation})
                fallback = [row for row in explanation["fallback_observations"] if row["eligible"]]
                whole_estimates.append([row["rate"] * exposure for row in fallback] if exposure is not None else [])
            source_years = sorted({year for explanation in explanations for year in explanation["source_years"]})
            for scenario, quantile in (("typical", 0.5), ("higher", 0.8)):
                values = [explanation[scenario] for explanation in explanations]
                estimate = sum(values) if all(value is not None for value in values) else None
                whole_values = [percentile(values, quantile) for values in whole_estimates]
                whole = sum(whole_values) if all(value is not None for value in whole_values) else None
                error = estimate - actual_hours if estimate is not None and actual_hours is not None else None
                whole_error = whole - actual_hours if whole is not None and actual_hours is not None else None
                rows.append(
                    {
                        "evaluation_year": evaluation_year,
                        "cutoff": cutoff,
                        "horizon": actual.end,
                        "category": category,
                        "scenario": scenario,
                        "source_years": source_years,
                        "actual_hours": actual_hours,
                        "estimated_future_hours": estimate,
                        "error_hours": error,
                        "absolute_error": abs(error) if error is not None else None,
                        "whole_year_estimate": whole,
                        "whole_year_error": whole_error,
                        "whole_year_absolute_error": abs(whole_error) if whole_error is not None else None,
                        "monthly_explanations": explanations,
                        "whole_year_source_years": sorted(
                            {
                                row["year"]
                                for explanation in explanations
                                for row in explanation["fallback_observations"]
                                if row["eligible"]
                            }
                        ),
                        "training_population_note": "Seasonal and whole-year comparison populations are listed separately; incomplete coverage can make them differ.",
                        "actual_coverage_complete": usable_actual,
                    }
                )
    summaries = []
    for category in sorted(categories):
        for scenario in ("typical", "higher"):
            selected = [row for row in rows if row["category"] == category and row["scenario"] == scenario]
            errors = [row["absolute_error"] for row in selected if row["absolute_error"] is not None]
            whole_errors = [
                row["whole_year_absolute_error"] for row in selected if row["whole_year_absolute_error"] is not None
            ]
            summaries.append(
                {
                    "evaluation_year": evaluation_year,
                    "horizon": actual.end,
                    "category": category,
                    "scenario": scenario,
                    "sample_count": len(errors),
                    "mean_absolute_error": sum(errors) / len(errors) if errors else None,
                    "whole_year_sample_count": len(whole_errors),
                    "whole_year_mean_absolute_error": sum(whole_errors) / len(whole_errors) if whole_errors else None,
                }
            )
    return RetrospectiveResult(tuple(rows), tuple(summaries), tuple(warnings))
