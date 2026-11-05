"""Independent, read-only break options funded by the shared dated engine."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from math import isfinite

from .allocation import hours_for_units, required_units, whole_units
from .budget import BudgetParameters, DatedFunding, _lot_state, _period_for, _represented
from .credit_caps import credit_cap_limitation
from .expirations import EXPIRING_CATEGORIES, expiration_rules
from .planning import (
    PlanningWarning,
    ProjectionResult,
    Scenario,
    fingerprint,
    make_operation,
    new_scenario,
    prepare_projection_snapshot,
    project,
    scenario_transaction,
    source_identity,
    validate_scenario,
)
from .transaction_effects import signed_balance_effect, transaction_is_physical_absence

DISCRETIONARY_CATEGORIES = ("annual", "restored_annual", "comp", "travel_comp", "credit", "time_off_award")

RANKINGS = {
    "efficiency": "Leave efficiency",
    "least": "Least additional leave",
    "longest": "Longest break",
    "expiring": "Use expiring leave first",
}
METHOD_VERSION = "holiday-options-1"


@dataclass(frozen=True)
class HolidayParameters:
    cutoff: str
    start: str
    end: str
    minimum_days: int = 4
    maximum_hours: float = 40
    maximum_days: int = 21
    eligible_categories: tuple[str, ...] = DISCRETIONARY_CATEGORIES
    reserves: dict[str, float] = field(default_factory=dict)
    ranking: str = "efficiency"
    include_mixed: bool = False
    include_infeasible: bool = False
    limit: int = 20


@dataclass(frozen=True)
class HolidayOption:
    metrics: dict
    days: tuple[dict, ...]
    funding: tuple[dict, ...]
    scenario: Scenario
    after: ProjectionResult

    @property
    def source(self):
        return self.scenario.source


@dataclass(frozen=True)
class HolidayResult:
    source: dict
    parameters: HolidayParameters
    assumptions: dict
    candidates: tuple[HolidayOption, ...]
    no_leave: tuple[dict, ...]
    daily: tuple[dict, ...]
    before: ProjectionResult
    warnings: tuple[PlanningWarning, ...]
    enumerated_count: int
    evaluated_count: int
    schema_version: int = 1
    method_version: str = METHOD_VERSION


def _stamp(value):
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("Use inclusive ISO dates in YYYY-MM-DD form.")
    return result


def _check(parameters, snapshot):
    p = parameters
    cutoff, start, end = map(_stamp, (p.cutoff, p.start, p.end))
    if not snapshot["leave_year_start"] <= p.cutoff < p.start <= p.end <= snapshot["leave_year_end"]:
        raise ValueError("Search dates must be strictly after cutoff and inside the selected initialized leave year.")
    if (end - start).days >= 366:
        raise ValueError("Search at most 366 calendar dates at once.")
    if any(type(v) is not int or v < 1 for v in (p.minimum_days, p.maximum_days, p.limit)):
        raise ValueError("Day limits and result count must be positive integers.")
    if not p.minimum_days <= p.maximum_days <= 366 or p.limit > 100:
        raise ValueError("Minimum days must not exceed maximum days (up to 366); return at most 100 options.")
    if isinstance(p.maximum_hours, bool) or not isfinite(float(p.maximum_hours)) or p.maximum_hours < 0:
        raise ValueError("Maximum additional hours must be finite and nonnegative.")
    if p.ranking not in RANKINGS:
        raise ValueError("Choose a supported ranking mode.")
    if len(set(p.eligible_categories)) != len(p.eligible_categories) or set(p.eligible_categories) - set(
        DISCRETIONARY_CATEGORIES
    ):
        raise ValueError("Only distinct discretionary categories can fund proposed breaks.")
    if set(p.reserves) - set(DISCRETIONARY_CATEGORIES):
        raise ValueError("Reserve floors must use discretionary categories.")
    return cutoff


def _daily(snapshot, baseline, p, periods):
    existing = {}
    invalid = set()
    for tx in snapshot.get("transactions", []):
        try:
            if tx.get("category") == "overtime":
                continue
            if transaction_is_physical_absence(tx) and signed_balance_effect(tx) < 0:
                existing.setdefault(tx["date"], []).append(tx)
        except (ValueError, TypeError, KeyError):
            invalid.add(str(tx.get("date", "")))
    context = snapshot.get("calculation_context", {})
    holidays = {}
    for holiday in context.get("holidays", snapshot.get("holidays", [])):
        if holiday.get("nonworking", True):
            holidays.setdefault(
                holiday.get("observed_date") or holiday.get("date") or holiday.get("display_date"), []
            ).append(holiday.get("name", holiday.get("label", "Observed nonworking holiday")))
    rows = []
    for capacity in baseline.capacity:
        day = capacity.date
        if not p.start <= day <= p.end:
            continue
        entries = existing.get(day, [])
        discretionary = sum(float(tx["hours"]) for tx in entries if tx["category"] in DISCRETIONARY_CATEGORIES)
        other = sum(float(tx["hours"]) for tx in entries if tx["category"] not in DISCRETIONARY_CATEGORIES)
        hours = capacity.work_hours
        if day in invalid or "" in invalid or not _period_for(periods, day):
            hours = None
        rows.append(
            dict(
                date=day,
                scheduled_hours=hours,
                existing_discretionary_hours=discretionary,
                existing_other_hours=other,
                existing_hours=discretionary + other,
                additional_hours=max(0.0, hours - discretionary - other) if hours is not None else None,
                holiday=holidays.get(day, []) if baseline.assumptions.get("holidays_enabled") else [],
                reason="Unknown schedule / absence / pay-period context"
                if hours is None
                else "Nonworking holiday"
                if not hours and holidays.get(day)
                else "Configured day off"
                if not hours
                else "Scheduled workday",
                transaction_ids=[tx["id"] for tx in entries],
                overbooked=hours is not None and discretionary + other > hours + 1e-9,
            )
        )
    return rows


def _ranges(daily, p):
    """Workday boundary intervals, extended by connected already-away dates."""
    natural = [r["scheduled_hours"] is not None and r["additional_hours"] == 0 for r in daily]
    result, no_leave = {}, []
    n = len(daily)
    for i in range(n):
        if daily[i]["scheduled_hours"] != 0:
            continue
        if i and daily[i - 1]["scheduled_hours"] == 0:
            continue
        end = i
        while end + 1 < n and daily[end + 1]["scheduled_hours"] == 0:
            end += 1
        if end - i + 1 >= p.minimum_days:
            no_leave.append(
                dict(
                    start=daily[i]["date"],
                    end=daily[end]["date"],
                    calendar_days=end - i + 1,
                    label="No leave required",
                    boundary_truncated=i == 0 or end == n - 1,
                )
            )
    for i, first in enumerate(daily):
        if first["scheduled_hours"] is None or not first["scheduled_hours"]:
            continue
        for j in range(i, min(n, i + p.maximum_days)):
            if daily[j]["scheduled_hours"] is None:
                break
            if not daily[j]["scheduled_hours"]:
                continue
            left, right = i, j
            while left and natural[left - 1]:
                left -= 1
            while right + 1 < n and natural[right + 1]:
                right += 1
            if not p.minimum_days <= right - left + 1 <= p.maximum_days:
                continue
            rows = daily[left : right + 1]
            additional = sum(row["additional_hours"] for row in rows)
            mixed = any(row["existing_other_hours"] > 0 for row in rows)
            if additional > p.maximum_hours + 1e-9 or (mixed and not p.include_mixed):
                continue
            if not any(
                row["scheduled_hours"] and (row["existing_discretionary_hours"] or row["additional_hours"])
                for row in rows
            ):
                continue
            result[(left, right)] = dict(
                start=rows[0]["date"],
                end=rows[-1]["date"],
                calendar_days=len(rows),
                workdays=sum(row["scheduled_hours"] > 0 for row in rows),
                existing_hours=sum(row["existing_hours"] for row in rows),
                existing_discretionary_hours=sum(row["existing_discretionary_hours"] for row in rows),
                existing_other_hours=sum(row["existing_other_hours"] for row in rows),
                additional_hours=additional,
                mixed_purpose=mixed,
                boundary_truncated=left == 0 or right == n - 1,
                label="Already scheduled"
                if additional == 0
                else "Mixed-purpose dependency"
                if mixed
                else "Proposed discretionary break",
            )
    return result, no_leave


def _order(row, mode):
    efficiency = row["calendar_days"] / row["additional_hours"] if row["additional_hours"] else None
    tail = (-row["calendar_days"], row["additional_hours"], row["start"], row["end"])
    return (
        (row["additional_hours"], *tail)
        if mode == "least"
        else tail
        if mode == "longest"
        else (-row.get("expiring_hours", 0), efficiency is None, -(efficiency or 0), *tail)
        if mode == "expiring"
        else (efficiency is None, -(efficiency or 0), *tail)
    )


def _fund(rows, work, unknown, params, baseline, cancel, funding_context):
    p = params
    funding = funding_context.independent()
    increment = funding.increment
    allocations, missing, reasons = [], 0.0, []
    for day in rows:
        if cancel():
            raise ValueError("Canceled Holiday and Weekend Planner calculation.")
        needed = required_units(day["additional_hours"], increment)
        if abs(hours_for_units(needed, increment) - day["additional_hours"]) > 1e-7:
            reasons.append("Required hours do not fit the configured time increment.")
            missing += day["additional_hours"]
            continue
        if not needed:
            continue
        available = []
        for category in p.eligible_categories:
            if category in unknown or not work["snapshot_rules"].get("rules", {}).get(category, {}).get(
                "enabled", True
            ):
                continue
            if category in EXPIRING_CATEGORIES:
                private = deepcopy(work)
                private["transactions"].extend(scenario_transaction(op) for op in funding.operations)
                state = _lot_state(private, category, day["date"])
                expires = expiration_rules(work["snapshot_rules"])[category].get("expires")
                for lot in state["lots"]:
                    deadline = lot.get("expiration_date") if expires else None
                    if deadline and day["date"] > deadline:
                        continue
                    cap = whole_units(state["remaining"].get(str(lot["id"]), 0), increment)
                    if cap:
                        available.append(
                            dict(
                                id=str(lot["id"]),
                                category=category,
                                lot_id=str(lot["id"]),
                                deadline=deadline,
                                earned_date=lot.get("original_earned_date") or lot["date"],
                                available_from=lot["date"],
                                cap=cap,
                            )
                        )
            else:
                balance = funding.base.get((category, day["date"]))
                if balance is not None and balance > float(p.reserves.get(category, 0)):
                    available.append(
                        dict(
                            id=category,
                            category=category,
                            lot_id=None,
                            deadline=None,
                            earned_date="",
                            available_from=None,
                            cap=needed,
                        )
                    )
        available.sort(
            key=lambda r: (
                r["deadline"] or "9999-12-31",
                r["category"] == "annual",
                r["category"],
                r["earned_date"],
                r["id"],
            )
        )
        for bank in available:
            amount = funding.maximum(bank, day["date"], min(needed, bank["cap"]))
            if not amount:
                continue
            hours = hours_for_units(amount, increment)
            key = (
                "holiday:"
                + fingerprint([rows[0]["date"], rows[-1]["date"], day["date"], bank["id"], len(allocations)])[:24]
            )
            funding.operations.append(
                make_operation(
                    work,
                    row_id=key,
                    operation="add",
                    date=day["date"],
                    category=bank["category"],
                    hours=hours,
                    earned_transaction_id=bank["lot_id"],
                    note="Holiday and Weekend Planner option; not booked leave",
                )
            )
            allocations.append(
                dict(
                    date=day["date"],
                    category=bank["category"],
                    hours=hours,
                    lot_id=bank["lot_id"],
                    deadline=bank["deadline"],
                    row_id=key,
                )
            )
            needed -= amount
            if not needed:
                break
        missing += hours_for_units(needed, increment)
    if missing:
        reasons.extend(sorted({r["message"] for r in funding.failures.values()}))
        reasons.append("Insufficient supported eligible hours on the required dates; options are independent.")
    used = {row["category"] for row in allocations} | set(p.reserves)
    for row in baseline.categories:
        if row.category in used and (
            row.baseline.minimum_balance is None
            or row.baseline.minimum_balance < float(p.reserves.get(row.category, 0)) - 1e-7
        ):
            reasons.append(
                f"{row.category}: baseline already has an unknown balance or reserve shortfall; inspect dated balances."
            )
    state = (
        "Incomplete funding"
        if missing and set(p.eligible_categories) & unknown
        else "Infeasible"
        if missing or reasons
        else "Feasible"
    )
    return tuple(funding.operations), allocations, missing, reasons, state


def plan_holidays(snapshot, parameters: HolidayParameters, *, today=None, canceled=None, progress=None):
    """Enumerate bounded alternatives; each uses the same immutable baseline."""
    snapshot, p = deepcopy((snapshot, parameters))
    today, canceled = today or date.today(), canceled or (lambda: False)
    _check(p, snapshot)
    definition = new_scenario(
        snapshot,
        today=today,
        cutoff=p.cutoff,
        horizon=snapshot["leave_year_end"],
        name="Holiday and Weekend Planner option",
    )
    credit_supported = credit_cap_limitation(snapshot["snapshot_rules"]) is None
    definition = validate_scenario(
        snapshot,
        replace(
            definition,
            reserves=p.reserves,
            assumptions={
                **definition.assumptions,
                "budget_credit_caps": credit_supported,
                "holiday_planner_method": METHOD_VERSION,
            },
        ),
    )
    before = project(snapshot, definition, today=today)
    warnings = list(before.warnings)
    work, unknown = prepare_projection_snapshot(
        snapshot, definition.horizon, warnings, set(p.eligible_categories) | set(p.reserves)
    )
    if not credit_supported:
        unknown.add("credit")
        warnings.append(
            PlanningWarning("UNSUPPORTED_CREDIT_USABILITY", credit_cap_limitation(snapshot["snapshot_rules"]), "credit")
        )
    periods = _represented(snapshot, warnings)
    daily = _daily(snapshot, before, p, periods)
    ranges, no_leave = _ranges(daily, p)
    funding_context = DatedFunding(
        work, unknown, BudgetParameters(p.cutoff, definition.horizon, reserves=p.reserves), periods, before
    )
    standard = before.assumptions.get("daily_work_hours")
    evaluated, options = 0, []
    # Raw ranking is independent of funding except the explicit expiring mode.
    # Once a full top set is feasible, later raw-ranked options cannot displace it.
    for (left, right), original in sorted(ranges.items(), key=lambda item: _order(item[1], p.ranking)):
        if canceled():
            raise ValueError("Canceled Holiday and Weekend Planner calculation.")
        rows, metrics = daily[left : right + 1], deepcopy(original)
        operations, allocations, missing, reasons, state = _fund(
            rows, work, unknown, p, before, canceled, funding_context
        )
        evaluated += 1
        if progress:
            progress(evaluated, len(ranges))
        metrics.update(
            id=f"{metrics['start']}/{metrics['end']}",
            state=state,
            unfunded_hours=missing,
            reasons=reasons,
            funding_by_category={
                category: sum(r["hours"] for r in allocations if r["category"] == category)
                for category in p.eligible_categories
            },
            expiring_hours=sum(r["hours"] for r in allocations if r["deadline"]),
            standard_day_hours=standard,
            efficiency=metrics["calendar_days"] * standard / metrics["additional_hours"]
            if standard and metrics["additional_hours"]
            else None,
        )
        if state == "Feasible" or p.include_infeasible:
            options.append((metrics, rows, allocations, operations))
        if p.ranking != "expiring" and sum(m[0]["state"] == "Feasible" for m in options) >= p.limit:
            break
    options.sort(key=lambda item: (item[0]["state"] != "Feasible", _order(item[0], p.ranking)))
    result = []
    for metrics, rows, allocations, operations in options[: p.limit]:
        if canceled():
            raise ValueError("Canceled Holiday and Weekend Planner calculation.")
        candidate = replace(
            definition, operations=operations, name=f"Break option {metrics['start']} to {metrics['end']}"
        )
        after = project(snapshot, candidate, today=today)
        relevant = set(p.eligible_categories) | set(p.reserves)
        metrics["minimum_balances"] = {
            row.category: {
                "baseline": row.baseline.minimum_balance,
                "baseline_date": row.baseline.minimum_date,
                "scenario": row.scenario.minimum_balance,
                "scenario_date": row.scenario.minimum_date,
            }
            for row in after.categories
            if row.category in relevant
        }
        metrics["ending_balances"] = {
            row.category: {"baseline": row.baseline.horizon_balance, "scenario": row.scenario.horizon_balance}
            for row in after.categories
            if row.category in relevant
        }
        metrics["reserve_flags"] = {
            row.category: row.scenario.first_reserve_breach for row in after.categories if row.category in relevant
        }
        annual = next(row for row in after.categories if row.category == "annual")
        metrics["annual_forfeiture_reduction"] = (
            annual.baseline.prospective_forfeiture - annual.scenario.prospective_forfeiture
            if annual.baseline.prospective_forfeiture is not None and annual.scenario.prospective_forfeiture is not None
            else None
        )
        details = tuple(
            {
                **row,
                "proposed_hours": sum(a["hours"] for a in allocations if a["date"] == row["date"]),
                "funding": [a for a in allocations if a["date"] == row["date"]],
            }
            for row in rows
        )
        result.append(HolidayOption(metrics, details, tuple(allocations), candidate, after))
    unique = {fingerprint(asdict(w)): w for w in warnings}
    assumptions = {
        **before.assumptions,
        "eligible_categories": p.eligible_categories,
        "eligibility": "Discretionary categories only; projected availability does not establish agency approval or purpose eligibility.",
        "ranking": RANKINGS[p.ranking],
        "normalization": "Maximal connected away intervals within search bounds; boundary truncation is explicit.",
        "funding_priority": "Known expiration deadline, category, original earned date, lot ID; nonexpiring banks then annual.",
        "alternatives": "Each option independently uses the same baseline; proposed rows are not calendar bookings.",
        "efficiency": "Calendar days away per additional standard-workday-equivalent; zero additional hours is Already scheduled with N/A efficiency.",
        "units": "Hours; inclusive ISO date ranges",
        "reserves": p.reserves,
    }
    return HolidayResult(
        source_identity(snapshot),
        p,
        assumptions,
        tuple(result),
        tuple(no_leave),
        tuple(daily),
        before,
        tuple(unique[k] for k in sorted(unique)),
        len(ranges),
        evaluated,
    )
