"""Versioned deadline budgets on private data, without storage capabilities."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from math import isfinite

from .allocation import apportion_units, hours_for_units, required_units, whole_units
from .credit_caps import credit_cap_limitation, simulate_credit_caps
from .expirations import expiration_rules, synchronize_expirations
from .ledger import calculate_balances
from .payperiods import validate_pay_periods
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
    time_increment,
    validate_scenario,
)
from .transaction_effects import signed_balance_effect, transaction_is_effective

SCHEMA_VERSION = 1
METHOD_VERSION = "deadline-budget-v1"
CATEGORIES = ("annual", "comp", "travel_comp", "restored_annual", "time_off_award", "credit")
STRATEGIES = {
    "even": "Even across pay periods",
    "earliest": "Earliest available",
    "latest": "Latest available",
    "weighted": "Capacity-weighted",
}
STRATEGY_HELP = {
    "even": "Equal period quotas, capped and redistributed; earliest dates within each period.",
    "earliest": "Fill the earliest eligible dates first.",
    "latest": "Fill the latest eligible dates before each deadline first.",
    "weighted": "Period quotas proportional to eligible capacity; earliest dates within each period.",
}


@dataclass(frozen=True)
class BudgetParameters:
    cutoff: str
    horizon: str
    strategy: str = "even"
    eligible_categories: tuple[str, ...] = ()
    reserves: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BudgetResult:
    source: dict
    parameters: BudgetParameters
    assumptions: dict
    deadlines: tuple[dict, ...]
    suggestions: tuple[dict, ...]
    dates: tuple[dict, ...]
    periods: tuple[dict, ...]
    cumulative: tuple[dict, ...]
    audit: tuple[dict, ...]
    before: ProjectionResult
    after: ProjectionResult
    scenario: Scenario
    state: str
    required_hours: float
    allocated_hours: float
    unallocated_hours: float
    first_infeasible_deadline: dict | None
    warnings: tuple[PlanningWarning, ...]
    schema_version: int = SCHEMA_VERSION
    method_version: str = METHOD_VERSION

    def to_dict(self):
        return asdict(self)


def _lot_state(work, category, day):
    private = deepcopy(work)
    private["transactions"] = [tx for tx in private["transactions"] if tx.get("category") == category]
    return synchronize_expirations(
        private, work["snapshot_rules"], as_of=date.fromisoformat(day), include_nonexpiring=True
    )


def _row(key, category, deadline, **values):
    return dict(
        id=key,
        category=category,
        lot_id=None,
        deadline=deadline,
        earned_date="",
        available_from="",
        original_hours=None,
        local_hours=None,
        remaining_at_cutoff=None,
        scheduled_hours=0.0,
        other_disposals=0.0,
        required_hours=None,
        outcome="Unknown",
        status="Unknown/unsupported",
        **values,
    )


def _obligations(snapshot, work, unknown, params, projection, warnings, branch="baseline"):
    rows, audit = [], []
    categories = {row.category: row for row in projection.categories}
    annual = getattr(categories["annual"], branch)
    deadline = snapshot["leave_year_end"]
    row = _row("annual-cap", "annual", deadline)
    row.update(
        remaining_at_cutoff=annual.cutoff_balance,
        outcome="Annual carryover cap",
        cap=work["snapshot_rules"].get("rules", {}).get("annual", {}).get("carryover_limit_hours", 240),
    )
    if params.horizon < deadline:
        row["status"] = "Outside current horizon"
    elif annual.annual_pre_cap_balance is not None:
        row.update(
            required_hours=annual.prospective_forfeiture,
            pre_cap_balance=annual.annual_pre_cap_balance,
            status="Actionable",
        )
    events = [asdict(event) for event in projection.events if event.branch == branch and event.category == "annual"]
    row["scheduled_hours"] = sum(e["hours"] for e in events if e["direction"] == "used" and e["date"] > params.cutoff)
    row["other_disposals"] = sum(
        -e["signed_hours"]
        for e in events
        if e["direction"] != "used" and e["signed_hours"] < 0 and e["date"] > params.cutoff
    )
    audit.append(
        dict(
            section="Annual cap",
            id=row["id"],
            opening=snapshot.get("starting_balances", {}).get("annual", 0),
            cutoff_balance=annual.cutoff_balance,
            recorded_through_cutoff=sum(
                -e["signed_hours"] for e in events if e["direction"] == "used" and e["date"] <= params.cutoff
            ),
            earned_expected=sum(
                e["signed_hours"] for e in events if e["signed_hours"] > 0 and e["date"] > params.cutoff
            ),
            **{
                k: row.get(k)
                for k in ("scheduled_hours", "other_disposals", "pre_cap_balance", "cap", "required_hours")
            },
        )
    )
    rows.append(row)
    for category in CATEGORIES[1:-1]:
        failures = [
            warning
            for warning in warnings
            if warning.category == category
            and warning.code in {"MALFORMED_SOURCE_RECORD", "UNSUPPORTED_CATEGORY_POLICY", "INVALID_OPENING_BALANCE"}
        ]
        if category in unknown and failures:
            row = _row(f"{category}-policy", category, None)
            configured_action = snapshot.get("snapshot_rules", {}).get("rules", {}).get(category, {})
            configured_action = (
                configured_action.get("expiration_action", "Unknown")
                if isinstance(configured_action, dict)
                else "Unknown"
            )
            row["outcome"] = str(configured_action) + ": " + "; ".join(warning.message for warning in failures)
            audit.extend(
                dict(section="Unsupported category source", **deepcopy(tx))
                for tx in snapshot.get("transactions", [])
                if tx.get("category") == category
            )
            rows.append(row)
            continue
        # Preserve known lot diagnostics even when an unproven opening makes the bank unknown.
        lot_work = deepcopy(work)
        if category in unknown:
            lot_work["transactions"] = [
                deepcopy(tx)
                for tx in snapshot.get("transactions", [])
                if tx.get("category") == category
                and tx.get("source") != "expiration-engine"
                and transaction_is_effective(tx)
            ]
        try:
            rule = expiration_rules(snapshot.get("snapshot_rules"))[category]
            state = _lot_state(lot_work, category, snapshot["leave_year_end"])
            cutoff = _lot_state(lot_work, category, params.cutoff)
        except (ValueError, TypeError, KeyError) as exc:
            rows.append(_row(f"{category}-policy", category, None))
            warnings.append(PlanningWarning("UNSUPPORTED_LOT_POLICY", str(exc), category))
            continue
        for warning in state["warnings"]:
            warnings.append(
                PlanningWarning(
                    warning["code"], warning["message"], category, transaction_id=str(warning.get("transaction_id", ""))
                )
            )
        for lot in state["lots"]:
            key = str(lot["id"])
            deadline = lot.get("expiration_date") if rule.get("expires") else None
            row = _row(key, category, deadline)
            row.update(
                lot_id=key,
                earned_date=str(lot.get("original_earned_date") or lot["date"]),
                available_from=lot["date"],
                original_hours=lot.get("origin_earned_hours", float(lot["hours"])),
                local_hours=float(lot["hours"]),
                remaining_at_cutoff=0.0 if deadline and deadline < params.cutoff else cutoff["remaining"].get(key, 0.0),
                outcome=rule.get("expiration_action", "warn") if deadline else "Expiration disabled",
            )
            end = (
                min(deadline or params.horizon, params.horizon)
                if not deadline or deadline >= params.cutoff
                else deadline
            )
            due = _lot_state(lot_work, category, end)
            allocations = [a for a in due["allocations"] if a["lot_id"] == key]
            future = [a for a in allocations if params.cutoff < a["date"]]
            row["scheduled_hours"] = sum(a["hours"] for a in future if a["direction"] == "used")
            row["other_disposals"] = sum(a["hours"] for a in future if a["direction"] != "used")
            row["known_remaining_at_boundary"] = due["remaining"].get(key, 0.0)
            if not deadline:
                row.update(status="No expiration", required_hours=0.0)
            elif deadline < params.cutoff:
                row.update(
                    status="Past disposition" if not cutoff["remaining"].get(key, 0.0) else "Past unresolved warning",
                    past_at_risk_hours=cutoff["remaining"].get(key, 0.0),
                    past_disposed_hours=max(0.0, due["remaining"].get(key, 0.0) - cutoff["remaining"].get(key, 0.0)),
                    required_hours=0.0,
                )
            elif deadline > params.horizon:
                row["status"] = "Outside current horizon"
            else:
                row.update(status="Actionable", required_hours=due["remaining"].get(key, 0.0))
            row["deadline_derivation"] = (
                "Stored extension" if lot.get("expiration_extension_reason") else "Stored/canonical expiration rule"
            )
            audit.append(dict(section="Source lot", **deepcopy(lot)))
            audit.extend(dict(section="Canonical allocation", id=key, **a) for a in allocations)
            rows.append(row)
        opening = float(snapshot.get("starting_balances", {}).get(category, 0))
        if category in unknown or opening:
            row = _row(f"{category}-unknown-opening", category, None)
            row.update(local_hours=opening or None, outcome="Unknown original earning date / bank policy")
            rows.append(row)
    limitation = credit_cap_limitation(snapshot.get("snapshot_rules", {}))
    if limitation or "credit" in unknown:
        limitation = (
            limitation
            or "Credit balance is unknown because source records or policy could not be validated; review projection warnings."
        )
        row = _row("credit-policy", "credit", None)
        row["outcome"] = limitation
        rows.append(row)
        warnings.append(PlanningWarning("UNSUPPORTED_CREDIT_CAP", limitation, "credit"))
    else:
        private = deepcopy(work)
        for cap in simulate_credit_caps(private, params.cutoff, params.horizon):
            row = _row(f"credit-cap:{cap['period_id']}", "credit", cap["deadline"])
            row.update(
                remaining_at_cutoff=categories["credit"].baseline.cutoff_balance,
                required_hours=cap["prospective_loss"],
                outcome="Pay-period rollover forfeiture",
                status="Actionable",
                **cap,
            )
            rows.append(row)
            audit.append(dict(section="Credit cap timeline", id=row["id"], **cap))
    return rows, audit


def _represented(snapshot, warnings):
    periods = sorted(deepcopy(snapshot.get("pay_periods", [])), key=lambda p: str(p.get("start_date", "")))
    try:
        validate_pay_periods(snapshot)
    except (ValueError, TypeError, KeyError) as exc:
        warnings.append(
            PlanningWarning("INCOMPLETE_PAY_PERIODS", f"{exc}. Only valid represented dates can receive suggestions.")
        )
    valid, end, ids = [], "", set()
    for p in periods:
        try:
            start, stop = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
            key = str(p["pay_period_number"])
            if start > stop or p["start_date"] <= end or key in ids:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            warnings.append(
                PlanningWarning("INVALID_PAY_PERIOD", "Overlapping/malformed period excluded from opportunities.")
            )
            continue
        valid.append(p)
        end = p["end_date"]
        ids.add(key)
    return valid


def _period_for(periods, day):
    return next((str(p["pay_period_number"]) for p in periods if p["start_date"] <= day <= p["end_date"]), None)


def _credit_available(work, day, periods):
    rules = work["snapshot_rules"].get("rules", {}).get("credit", {})
    available = calculate_balances(work, until_date=day).get("credit", 0.0)
    for tx in work["transactions"]:
        if tx.get("category") != "credit" or tx.get("direction") not in {"earned", "worked"} or tx["date"] > day:
            continue
        same_day = tx["date"] == day and (
            rules.get("usable_when", "next_day") != "same_day" or not rules.get("same_day_use_allowed", False)
        )
        same_period = _period_for(periods, tx["date"]) == _period_for(periods, day) and (
            rules.get("usable_when") == "next_pay_period" or not rules.get("same_pay_period_use_allowed", True)
        )
        if same_day or same_period:
            available -= max(0.0, signed_balance_effect(tx))
    return available


class _Funding:
    """Validate candidate dated use against canonical balances, including later bookings."""

    def __init__(self, work, unknown, params, periods, baseline):
        self.work, self.unknown, self.params, self.periods = work, unknown, params, periods
        self.base = {(r.category, r.date): r.baseline for r in baseline.daily}
        self.boundaries = {
            r.date
            for r in baseline.daily
            if r.baseline != self.base.get((r.category, (date.fromisoformat(r.date) - timedelta(days=1)).isoformat()))
        }
        self.operations = []
        self.failures = {}
        self.increment = time_increment(work)

    def reject(self, row, day, units, code, message, **detail):
        self.failures[(row["id"], day)] = dict(
            section="Dated funding check",
            id=row["id"],
            date=day,
            code=code,
            message=message,
            candidate_hours=hours_for_units(units, self.increment),
            prior_suggestion_count=len(self.operations),
            **detail,
        )
        return False

    def safe(self, row, day, units):
        if row["category"] in self.unknown:
            return False
        category = row["category"]
        work = deepcopy(self.work)
        work["starting_balances"] = {category: work.get("starting_balances", {}).get(category, 0)}
        work["transactions"] = [tx for tx in work["transactions"] if tx["category"] == category]
        for operation in self.operations:
            if operation.category == category:
                work["transactions"].append(scenario_transaction(operation))
        work["transactions"].append(
            dict(
                id="budget-candidate",
                date=day,
                category=category,
                direction="used",
                hours=hours_for_units(units, self.increment),
                status="planned",
                earned_transaction_id=row["lot_id"],
            )
        )
        if category == "credit":
            simulate_credit_caps(work, self.params.cutoff, self.params.horizon)
            if _credit_available(work, day, self.periods) < -1e-7:
                return self.reject(
                    row,
                    day,
                    units,
                    "CREDIT_NOT_YET_USABLE",
                    "Credit has not become usable under the configured same-day/pay-period rule.",
                )
        critical = (
            {day, self.params.horizon}
            | {d for d in self.boundaries if day <= d <= self.params.horizon}
            | {tx["date"] for tx in work["transactions"] if day <= tx["date"] <= self.params.horizon}
        )
        # Expiration can change available balances on the following day.
        for future in sorted(critical):
            balance = calculate_balances(work, until_date=future).get(category, 0.0)
            original = self.base.get((category, future))
            if original is None:
                return False
            threshold = min(float(self.params.reserves.get(category, 0)), original)
            if future == day:
                threshold = float(self.params.reserves.get(category, 0))
            if balance < threshold - 1e-7:
                return self.reject(
                    row,
                    day,
                    units,
                    "DATED_BALANCE_OR_RESERVE",
                    "Candidate would exceed available balance/reserve or increase a later existing deficit.",
                    check_date=future,
                    candidate_closing_balance=balance,
                    minimum_allowed=threshold,
                    baseline_closing_balance=original,
                )
        return True

    def maximum(self, row, day, cap):
        if not cap or row["available_from"] and day < row["available_from"]:
            return 0
        if self.safe(row, day, cap):
            return cap
        low, high = 0, cap
        while low < high:
            middle = (low + high + 1) // 2
            if self.safe(row, day, middle):
                low = middle
            else:
                high = middle - 1
        return low


def _schedule(rows, work, unknown, params, periods, before, warnings):
    increment = time_increment(work)
    capacities = {
        r.date: whole_units(r.remaining_capacity or 0, increment)
        for r in before.capacity
        if r.date > params.cutoff and _period_for(periods, r.date)
    }
    funding = _Funding(work, unknown, params, periods, before)
    original_capacity = dict(capacities)
    independent_funding = _Funding(work, unknown, params, periods, before)
    edges = {}
    suggestions = []
    for row in rows:
        eligible = [
            day
            for day, capacity in original_capacity.items()
            if capacity
            and day <= (row["deadline"] or "")
            and (not row["available_from"] or day >= row["available_from"])
        ]
        row["periods_remaining"] = len({_period_for(periods, day) for day in eligible})
        row["usable_work_hours"] = sum(hours_for_units(original_capacity[day], increment) for day in eligible)
        if any(
            day.work_hours is None and params.cutoff < day.date <= (row["deadline"] or "") for day in before.capacity
        ):
            row["periods_remaining"] = row["usable_work_hours"] = None
        required = row["required_hours"]
        row["average_hours_per_period"] = (
            required / row["periods_remaining"] if required is not None and row["periods_remaining"] else None
        )
        row["allocated_hours"] = 0.0
        row["shared_capacity_at_priority"] = sum(hours_for_units(capacities[day], increment) for day in eligible)
        if row["status"] != "Actionable" or not required:
            continue
        if row["category"] not in params.eligible_categories:
            row["constraint"] = "Category not selected as eligible for this purpose"
            warnings.append(
                PlanningWarning(
                    "PURPOSE_NOT_SELECTED", row["constraint"], row["category"], row["deadline"], row["lot_id"]
                )
            )
            continue
        if row["category"] in unknown:
            row["constraint"] = "Unknown dated bank balance / reserve availability"
            warnings.append(
                PlanningWarning(
                    "UNKNOWN_DATED_FUNDING", row["constraint"], row["category"], row["deadline"], row["lot_id"]
                )
            )
            continue
        needed = required_units(required, increment)
        if row["lot_id"]:
            needed = whole_units(required, increment)
        remaining = needed
        edges[row["id"]] = {
            day: independent_funding.maximum(row, day, min(original_capacity[day], needed)) for day in eligible
        }
        possible = {day: funding.maximum(row, day, min(capacities[day], remaining)) for day in eligible}
        possible = {day: amount for day, amount in possible.items() if amount}
        while remaining and possible:
            groups = {}
            for day, amount in possible.items():
                groups.setdefault(_period_for(periods, day), []).append(day)
            caps = {key: sum(possible[d] for d in days) for key, days in groups.items()}
            if params.strategy in {"even", "weighted"}:
                chronology = sorted(groups, key=lambda key: min(groups[key]))
                shares = apportion_units(
                    remaining,
                    {
                        index: sum(capacities[day] for day in groups[key]) if params.strategy == "weighted" else 1
                        for index, key in enumerate(chronology)
                    },
                    {index: caps[key] for index, key in enumerate(chronology)},
                )
                quotas = {key: shares[index] for index, key in enumerate(chronology)}
                ordered = sorted(possible)
            else:
                quotas = caps
                ordered = sorted(possible, reverse=params.strategy == "latest")
            progress = 0
            for day in ordered:
                period = _period_for(periods, day)
                amount = funding.maximum(row, day, min(remaining, possible[day], quotas[period], capacities[day]))
                if not amount:
                    continue
                hours = hours_for_units(amount, increment)
                row_id = (
                    "budget:" + fingerprint([METHOD_VERSION, row["id"], day, params.strategy, len(suggestions)])[:24]
                )
                operation = make_operation(
                    work,
                    row_id=row_id,
                    operation="add",
                    date=day,
                    category=row["category"],
                    hours=hours,
                    earned_transaction_id=row["lot_id"],
                    note=f"Leave Budget suggestion; {STRATEGIES[params.strategy]}; obligation {row['id']}; deadline {row['deadline']}",
                )
                funding.operations.append(operation)
                suggestions.append(
                    dict(
                        id=row_id,
                        obligation_id=row["id"],
                        date=day,
                        period_id=period,
                        category=row["category"],
                        lot_id=row["lot_id"],
                        deadline=row["deadline"],
                        hours=hours,
                        strategy=params.strategy,
                        provenance="Estimated planning suggestion, not booked leave",
                    )
                )
                capacities[day] -= amount
                remaining -= amount
                quotas[period] -= amount
                row["allocated_hours"] += hours
                progress += amount
                if not remaining:
                    break
            if not progress:
                break
            possible = {
                day: funding.maximum(row, day, min(capacities[day], remaining)) for day in possible if capacities[day]
            }
            possible = {day: amount for day, amount in possible.items() if amount}
        if row["allocated_hours"] + 1e-7 < required:
            if not needed:
                row["constraint"] = f"Remaining lot hours are below the {increment:g} h increment."
            elif not remaining:
                row["constraint"] = (
                    f"A {required - row['allocated_hours']:g} h residual is below the {increment:g} h increment."
                )
            elif row["shared_capacity_at_priority"] + 1e-7 < required:
                row["constraint"] = (
                    f"Only {row['shared_capacity_at_priority']:g} h of shared work capacity remain for {required:g} h at this deadline priority."
                )
            else:
                row["constraint"] = (
                    "Dated balance/reserve or increment limits prevent the remaining demand; inspect Dated funding check audit rows."
                )
            warnings.append(
                PlanningWarning(
                    "UNALLOCATABLE_DEMAND", row["constraint"], row["category"], row["deadline"], row["lot_id"]
                )
            )
    return suggestions, tuple(funding.operations), edges, original_capacity, list(funding.failures.values())


def _joint_capacity(rows, edges, capacities, increment):
    """Maximum flow of dated obligations into shared workday capacity.

    Individual funding edges exclude unavailable earnings. Shared bank reserves
    and interacting cap policies can reduce this upper bound further; the actual
    schedule is independently checked by the canonical engine.
    """
    graph = {}

    def connect(a, b, capacity):
        graph.setdefault(a, {})[b] = capacity
        graph.setdefault(b, {})[a] = 0

    for row in rows:
        node = "obligation:" + row["id"]
        connect("source", node, required_units(row["required_hours"] or 0, increment))
        for day, capacity in edges.get(row["id"], {}).items():
            if capacity:
                connect(node, day, capacity)
    for day, capacity in capacities.items():
        connect(day, "sink", capacity)
    total = 0
    while True:
        parents, queue = {"source": None}, ["source"]
        for node in queue:
            for neighbor, capacity in graph.get(node, {}).items():
                if capacity and neighbor not in parents:
                    parents[neighbor] = node
                    queue.append(neighbor)
            if "sink" in parents:
                break
        if "sink" not in parents:
            return hours_for_units(total, increment)
        amount, node = float("inf"), "sink"
        while parents[node] is not None:
            prior = parents[node]
            amount, node = min(amount, graph[prior][node]), prior
        node = "sink"
        while parents[node] is not None:
            prior = parents[node]
            graph[prior][node] -= amount
            graph[node][prior] += amount
            node = prior
        total += int(amount)


def budget(snapshot: dict, parameters: BudgetParameters, *, today: date) -> BudgetResult:
    params = deepcopy(parameters)
    if params.strategy not in STRATEGIES:
        raise ValueError("Select a supported scheduling strategy.")
    if len(set(params.eligible_categories)) != len(params.eligible_categories) or set(params.eligible_categories) - set(
        CATEGORIES
    ):
        raise ValueError("Select supported purpose-eligible categories once each.")
    if any(isinstance(v, bool) or not isfinite(float(v)) or float(v) < 0 for v in params.reserves.values()):
        raise ValueError("Reserves must be finite nonnegative hours.")
    definition = new_scenario(
        snapshot, today=today, cutoff=params.cutoff, horizon=params.horizon, name="Leave Budget suggestions"
    )
    definition = validate_scenario(snapshot, replace(definition, reserves=params.reserves))
    credit_supported = credit_cap_limitation(snapshot.get("snapshot_rules", {})) is None
    definition = replace(
        definition,
        assumptions={
            **definition.assumptions,
            "budget_credit_caps": credit_supported,
            "budget_method": METHOD_VERSION,
            "budget_strategy": params.strategy,
        },
    )
    before = project(snapshot, definition, today=today)
    warnings = list(before.warnings)
    work, unknown = prepare_projection_snapshot(snapshot, params.horizon, warnings, set(params.reserves))
    periods = _represented(snapshot, warnings)
    rows, audit = _obligations(snapshot, work, unknown, params, before, warnings)
    rows.sort(key=lambda r: (r["deadline"] or "9999-12-31", r["category"], r["earned_date"], r["id"]))
    suggestions, operations, edges, original_capacity, funding_audit = _schedule(
        rows, work, unknown, params, periods, before, warnings
    )
    audit.extend(funding_audit)
    definition = validate_scenario(snapshot, replace(definition, operations=operations))
    after = project(snapshot, definition, today=today)
    # Recompute exact residuals from the same canonical rules, rather than required minus allocated.
    after_work = deepcopy(work)
    after_work["transactions"].extend(scenario_transaction(op) for op in operations)
    residuals, _ = _obligations(snapshot, after_work, unknown, params, after, list(warnings), branch="scenario")
    residuals = {r["id"]: r for r in residuals}
    for row in rows:
        row["after_required_hours"] = residuals[row["id"]]["required_hours"]
        required = row["required_hours"]
        row["unallocated_hours"] = max(0.0, required - row["allocated_hours"]) if required is not None else None
        if row["status"] == "Actionable":
            row["feasibility"] = (
                "No additional use required"
                if not required
                else (
                    "Feasible"
                    if (row["after_required_hours"] or 0) < 1e-7
                    else "Partially feasible"
                    if row["allocated_hours"]
                    else "Infeasible"
                )
            )
            if row["usable_work_hours"] is None:
                row["feasibility"] = "Unknown/unsupported"
        else:
            row["feasibility"] = row["status"]
    dates = []
    for capacity in before.capacity:
        if capacity.date <= params.cutoff:
            continue
        selected = [r for r in suggestions if r["date"] == capacity.date]
        allocated = sum(r["hours"] for r in selected)
        dates.append(
            dict(
                date=capacity.date,
                period_id=_period_for(periods, capacity.date),
                work_hours=capacity.work_hours,
                scheduled_hours=capacity.baseline_scheduled,
                suggested_hours=allocated,
                remaining_capacity=max(0.0, capacity.remaining_capacity - allocated)
                if capacity.remaining_capacity is not None
                else None,
                reason="Outside represented periods"
                if not _period_for(periods, capacity.date)
                else "Nonworkday / holiday"
                if not capacity.work_hours
                else "Existing bookings consume capacity"
                if not capacity.remaining_capacity
                else "Eligible work capacity",
            )
        )
    period_rows = []
    for period in periods:
        days = [r for r in dates if r["period_id"] == str(period["pay_period_number"])]
        if not days:
            continue
        record = dict(
            period_id=str(period["pay_period_number"]),
            start=period["start_date"],
            end=period["end_date"],
            partial_current=period["start_date"] <= params.cutoff < period["end_date"],
            suggested_hours=sum(d["suggested_hours"] for d in days),
            remaining_capacity=sum(d["remaining_capacity"] or 0 for d in days),
        )
        record.update(
            {
                category: sum(
                    s["hours"]
                    for s in suggestions
                    if s["period_id"] == record["period_id"] and s["category"] == category
                )
                for category in CATEGORIES
            }
        )
        period_rows.append(record)
    cumulative, first = [], None
    for deadline in sorted({r["deadline"] for r in rows if r["status"] == "Actionable"}):
        due = [r for r in rows if r["status"] == "Actionable" and r["deadline"] <= deadline]
        required = sum(r["required_hours"] or 0 for r in due)
        allocated = sum(r["allocated_hours"] for r in due)
        capacity = sum(
            d["work_hours"] and max(0.0, (d["work_hours"] or 0) - d["scheduled_hours"]) or 0
            for d in dates
            if d["date"] <= deadline and d["period_id"]
        )
        upper_bound = min(required, _joint_capacity(due, edges, original_capacity, time_increment(work)))
        point = dict(
            deadline=deadline,
            required_hours=required,
            available_hours=allocated,
            dated_capacity_bound_hours=upper_bound,
            joint_capacity_shortfall_hours=max(0.0, required - upper_bound),
            work_capacity_hours=capacity,
            shortfall_hours=max(0.0, required - allocated),
            capacity_basis="Feasibly allocated under selected strategy, dated balances, purpose eligibility, reserves and shared capacity; not a proof of infeasibility of every possible schedule",
        )
        cumulative.append(point)
        if first is None and point["shortfall_hours"] > 1e-7:
            first = deepcopy(point)
    required = sum(r["required_hours"] or 0 for r in rows if r["status"] == "Actionable")
    allocated = sum(r["hours"] for r in suggestions)
    unknown_result = (
        any(w.code == "INCOMPLETE_PAY_PERIODS" for w in warnings)
        or any(r["status"] == "Unknown/unsupported" for r in rows)
        or any(r.work_hours is None for r in before.capacity)
    )
    residual = sum(r["after_required_hours"] or 0 for r in rows if r["status"] == "Actionable")
    state = (
        "Unknown/unsupported"
        if unknown_result
        else "No additional use required"
        if not required
        else "Feasible"
        if residual < 1e-7
        else "Partially feasible"
        if allocated
        else "Infeasible"
    )
    assumptions = {
        **before.assumptions,
        "strategy": STRATEGIES[params.strategy],
        "strategy_explanation": STRATEGY_HELP[params.strategy],
        "deadline_priority": "Deadline, category, original earned date, lot ID",
        "capacity_basis": "Actual represented pay periods and dates strictly after cutoff; existing absence across all categories",
        "credit_caps": "Opt-in planning-only future pay-period rollover simulation"
        if credit_supported
        else "Unsupported; see warning",
        "eligibility": "Explicit user choice does not establish legal eligibility",
        "reserves": "Each proposed date must be funded above its reserve. Later existing baseline deficits cannot be increased; unchanged pre-existing deficits remain visible in the projection.",
        "suggestions": "Estimated planning suggestions, not booked leave",
        "rules": deepcopy(snapshot.get("snapshot_rules", {}).get("rules", {})),
        "dated_capacity_bound": "Maximum flow across obligation/date funding edges and shared work capacity. This is an upper bound; shared reserves/caps are additionally validated on the actual schedule.",
    }
    audit.extend(dict(section="Projection event", **asdict(e)) for e in before.events if e.branch == "baseline")
    warnings.extend(after.warnings)
    unique = {fingerprint(asdict(w)): w for w in warnings}
    return BudgetResult(
        source_identity(snapshot),
        params,
        assumptions,
        tuple(rows),
        tuple(suggestions),
        tuple(dates),
        tuple(period_rows),
        tuple(cumulative),
        tuple(audit),
        before,
        after,
        definition,
        state,
        required,
        allocated,
        max(0.0, required - allocated),
        first,
        tuple(unique[k] for k in sorted(unique)),
    )
