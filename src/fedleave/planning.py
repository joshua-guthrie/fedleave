"""Versioned, deterministic what-if projections on private accounting snapshots.

This module accepts data, never a repository, path, backend or persistence
callback. The CLI supplies the snapshot; only explicit exports in the companion
write files. All balance directions, accruals and lot rules remain canonical.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Literal

from .categories import CATEGORY_POLICIES, category_policy
from .config import Config
from .cross_year import seed_accruals
from .expirations import EXPIRING_CATEGORIES, expiration_rules, synchronize_expirations
from .ledger import calculate_balances, calculate_use_or_lose
from .transaction_effects import signed_balance_effect, transaction_is_effective, transaction_is_physical_absence

SCHEMA_VERSION = 1
METHOD_VERSION = "daily-closing-canonical-v1"
HISTORICAL_CUTOFF_WARNING = (
    "Historical cutoff projections use presently available leave records. They do not reconstruct "
    "which transactions, statuses, or bookings were known at the selected earlier date."
)
GENERAL_CATEGORIES = ("annual", "credit", "comp", "travel_comp", "restored_annual", "time_off_award")
RESTRICTED_CATEGORIES = (
    "sick",
    "religious_comp",
    "ppl",
    "military",
    "court",
    "admin",
    "excused",
    "lwop",
    "flex",
    "other",
)
PLANNABLE_CATEGORIES = (*GENERAL_CATEGORIES, *RESTRICTED_CATEGORIES)
MATERIAL_FIELDS = (
    "id",
    "date",
    "category",
    "direction",
    "hours",
    "status",
    "void",
    "earned_transaction_id",
    "expiration_date",
    "expiration_extension_reason",
    "original_expiration_date",
    "allocation_source",
    "allocation_event_id",
    "allocation_order",
    "scheduled_weekly_hours",
)


@dataclass(frozen=True)
class PlanningWarning:
    code: str
    message: str
    category: str | None = None
    date: str | None = None
    transaction_id: str | None = None
    row_id: str | None = None
    branch: str | None = None


class PlanningValidationError(ValueError):
    """Invalid input, kept distinct from a valid but infeasible projection."""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{item.get('row_id') or item['field']}: {item['message']}" for item in errors))


def _invalid(field: str, message: str, *, row_id: str = "", code: str = "INVALID_INPUT") -> None:
    raise PlanningValidationError([{"field": field, "message": message, "row_id": row_id, "code": code}])


def _date(value: Any, field: str) -> date:
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except (TypeError, ValueError):
        _invalid(field, "Use an ISO date in YYYY-MM-DD form.")


def _hours(value: Any, field: str, *, positive: bool = False, increment: float | None = None) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = float(value)
        if not isfinite(result) or result < 0 or (positive and result == 0):
            raise ValueError
        if increment is not None and Decimal(str(value)) % Decimal(str(increment)) != 0:
            _invalid(field, f"Hours must be a multiple of the configured {increment:g}-hour increment.")
        return result
    except PlanningValidationError:
        raise
    except (TypeError, ValueError, InvalidOperation, ZeroDivisionError):
        _invalid(field, "Enter finite, positive hours." if positive else "Enter finite, nonnegative hours.")


def fingerprint(value: Any) -> str:
    """Hash JSON data without depending on dictionary order or ledger row order."""

    def canonical(item):
        if isinstance(item, dict):
            result = {key: canonical(val) for key, val in item.items() if key not in {"accounting_warnings"}}
            if isinstance(result.get("transactions"), list):
                result["transactions"].sort(key=lambda tx: (str(tx.get("date")), str(tx.get("id"))))
            return result
        if isinstance(item, (tuple, list)):
            return [canonical(val) for val in item]
        if isinstance(item, float) and not isfinite(item):
            return {"invalid_number": str(item)}
        return item

    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def transaction_fingerprint(transaction: dict) -> str:
    return fingerprint({key: transaction.get(key) for key in MATERIAL_FIELDS})


def source_identity(snapshot: dict) -> dict[str, Any]:
    context = snapshot.get("calculation_context", {})
    return {
        "leave_year": snapshot.get("leave_year", snapshot.get("year")),
        "leave_year_start": snapshot.get("leave_year_start"),
        "leave_year_end": snapshot.get("leave_year_end"),
        "data_store": context.get("data_store"),
        "backend": context.get("backend"),
        "snapshot_fingerprint": fingerprint(snapshot),
    }


@dataclass(frozen=True)
class ScenarioOperation:
    row_id: str
    operation: Literal["add", "replace", "remove"]
    date: str | None = None
    category: str | None = None
    hours: float = 0.0
    note: str = ""
    original_ids: tuple[str, ...] = ()
    original_fingerprints: dict[str, str] = field(default_factory=dict)
    earned_transaction_id: str | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    source: dict[str, Any]
    cutoff: str
    horizon: str
    operations: tuple[ScenarioOperation, ...] = ()
    reserves: dict[str, float] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["operations"] = [asdict(operation) for operation in self.operations]
        return result


def time_increment(snapshot: dict) -> float:
    defaults = snapshot.get("snapshot_rules", {}).get("defaults", {})
    return _hours(defaults.get("time_increment_hours", 0.25), "time_increment_hours", positive=True)


def new_scenario(
    snapshot: dict,
    *,
    today: date,
    cutoff: str | None = None,
    horizon: str | None = None,
    name: str = "What-if scenario",
) -> Scenario:
    start = _date(snapshot.get("leave_year_start"), "leave_year_start")
    end = _date(snapshot.get("leave_year_end"), "leave_year_end")
    selected_cutoff = cutoff or min(max(today, start), end).isoformat()
    return validate_scenario(
        snapshot,
        {
            "schema_version": SCHEMA_VERSION,
            "name": name,
            "source": source_identity(snapshot),
            "cutoff": selected_cutoff,
            "horizon": horizon or end.isoformat(),
            "operations": [],
            "reserves": {},
            "assumptions": {"cutoff_basis": "presently available records", "daily_values": "closing balances"},
        },
    )


def scheduled_transactions(snapshot: dict, cutoff: str, horizon: str) -> list[dict]:
    """Original, effective, future physical absences; never synthetic events."""
    rows = []
    for transaction in snapshot.get("transactions", []):
        try:
            if (
                cutoff < transaction["date"] <= horizon
                and transaction_is_physical_absence(transaction)
                and signed_balance_effect(transaction) < 0
                and transaction.get("source") not in {"expiration-engine", "auto_accrual"}
            ):
                rows.append(deepcopy(transaction))
        except (KeyError, TypeError, ValueError):
            continue  # Projection validation separately reports malformed source rows.
    return sorted(rows, key=lambda tx: (tx["date"], str(tx.get("id"))))


def make_operation(snapshot: dict, **values: Any) -> ScenarioOperation:
    """Capture original identities when the user first creates an operation."""
    original_ids = tuple(values.get("original_ids", ()))
    originals = {str(tx.get("id")): tx for tx in snapshot.get("transactions", [])}
    values["original_ids"] = original_ids
    values["original_fingerprints"] = {
        transaction_id: transaction_fingerprint(originals[transaction_id])
        for transaction_id in original_ids
        if transaction_id in originals
    }
    return ScenarioOperation(**values)


def scenario_transaction(operation: ScenarioOperation) -> dict:
    """One canonical synthetic absence shared by projection and budget checks."""
    return {
        "id": f"scenario:{operation.row_id}",
        "date": operation.date,
        "category": operation.category,
        "direction": "used",
        "hours": operation.hours,
        "status": "planned",
        "source": "what-if-planner",
        "description": operation.note,
        "planning_row_id": operation.row_id,
        "planning_targeted_ids": list(operation.original_ids),
        "earned_transaction_id": operation.earned_transaction_id,
    }


def validate_scenario(snapshot: dict, document: dict | Scenario) -> Scenario:
    """Validate atomically, including material identities and overlapping targets."""
    if isinstance(document, Scenario):
        document = document.to_dict()
    if (
        not isinstance(document, dict)
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != SCHEMA_VERSION
    ):
        _invalid("schema_version", f"Supported scenario schema version is {SCHEMA_VERSION}.", code="UNKNOWN_SCHEMA")
    identity = source_identity(snapshot)
    source = document.get("source")
    if not isinstance(source, dict):
        _invalid("source", "The source leave-year identity is required.")
    source_hash = source.get("snapshot_fingerprint")
    if (
        not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(character not in "0123456789abcdef" for character in source_hash)
    ):
        _invalid("source", "A valid source snapshot fingerprint is required.")
    for key in ("leave_year", "leave_year_start", "leave_year_end", "data_store"):
        if source.get(key) != identity.get(key):
            _invalid("source", f"Scenario {key} does not match the selected snapshot.", code="WRONG_SOURCE")
    start, end = (
        _date(identity["leave_year_start"], "leave_year_start"),
        _date(identity["leave_year_end"], "leave_year_end"),
    )
    cutoff, horizon = _date(document.get("cutoff"), "cutoff"), _date(document.get("horizon"), "horizon")
    if not start <= cutoff <= horizon <= end:
        _invalid(
            "horizon", "Cutoff and horizon must be inside the selected leave year, with horizon on or after cutoff."
        )
    name = document.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        _invalid("name", "Enter a scenario name of 1 to 200 characters.")
    increment = time_increment(snapshot)
    reserves = document.get("reserves", {})
    if not isinstance(reserves, dict):
        _invalid("reserves", "Reserve thresholds must be a category-to-hours object.")
    clean_reserves = {}
    for category, value in reserves.items():
        if category not in PLANNABLE_CATEGORIES:
            _invalid("reserves", f"Unsupported reserve category {category!r}.")
        clean_reserves[category] = _hours(value, "reserves", increment=increment)
    raw_operations = document.get("operations")
    if not isinstance(raw_operations, (list, tuple)):
        _invalid("operations", "Scenario operations must be a list.")
    originals: dict[str, list[dict]] = {}
    for transaction in snapshot.get("transactions", []):
        originals.setdefault(str(transaction.get("id")), []).append(transaction)
    eligible = {str(tx.get("id")) for tx in scheduled_transactions(snapshot, cutoff.isoformat(), horizon.isoformat())}
    row_ids: set[str] = set()
    targets: set[str] = set()
    errors: list[dict[str, str]] = []
    operations = []
    for raw in raw_operations:
        row_id = str(raw.get("row_id", "")) if isinstance(raw, dict) else ""
        try:
            if (
                not isinstance(raw, dict)
                or not isinstance(raw.get("row_id"), str)
                or not row_id.strip()
                or len(row_id) > 200
                or row_id in row_ids
            ):
                _invalid("row_id", "Every operation needs a unique scenario-only row ID.")
            row_ids.add(row_id)
            if row_id in originals:
                _invalid("row_id", "A scenario row ID cannot be a real transaction ID.")
            operation = raw.get("operation")
            if operation not in {"add", "replace", "remove"}:
                _invalid("operation", "Choose add, replace, or remove.")
            ids = raw.get("original_ids", ())
            hashes = raw.get("original_fingerprints", {})
            if (
                not isinstance(ids, (list, tuple))
                or not all(isinstance(item, str) for item in ids)
                or len(ids) != len(set(ids))
            ):
                _invalid("original_ids", "Original IDs must be a list of unique transaction IDs.")
            if not isinstance(hashes, dict):
                _invalid("original_fingerprints", "Original material fingerprints must be an object.")
            if (operation == "add" and ids) or (operation != "add" and not ids):
                _invalid("original_ids", "Replace/remove requires original IDs; add cannot target originals.")
            for transaction_id in ids:
                if transaction_id in targets:
                    _invalid(
                        "original_ids",
                        f"Original {transaction_id} is already targeted by another row.",
                        code="CONFLICTING_TARGET",
                    )
                if transaction_id not in eligible or len(originals.get(transaction_id, [])) != 1:
                    _invalid(
                        "original_ids",
                        f"Original {transaction_id} is missing, ambiguous, or not an effective future absence.",
                        code="STALE_REFERENCE",
                    )
                if hashes.get(transaction_id) != transaction_fingerprint(originals[transaction_id][0]):
                    _invalid(
                        "original_ids",
                        f"Original {transaction_id} changed materially; resolve this reference explicitly.",
                        code="STALE_REFERENCE",
                    )
            category = raw.get("category")
            day = raw.get("date")
            hours = raw.get("hours", 0)
            if operation != "remove":
                if category not in PLANNABLE_CATEGORIES:
                    _invalid(
                        "category",
                        "Choose an available leave category; overtime and FMLA tracking are not absence credits.",
                    )
                if not cutoff < _date(day, "date") <= horizon:
                    _invalid("date", "Tentative use must be after the cutoff and through the selected horizon.")
                hours = _hours(hours, "hours", positive=True, increment=increment)
            else:
                if hours not in (0, None, "", "0"):
                    _invalid("hours", "Removal suppresses originals and must not add hours.")
                hours, day, category = 0.0, None, None
            note = raw.get("note", "")
            if not isinstance(note, str) or len(note) > 4000:
                _invalid("note", "Notes must be text of at most 4000 characters.")
            link = raw.get("earned_transaction_id")
            if link is not None and not isinstance(link, str):
                _invalid("earned_transaction_id", "A lot reference must be an original transaction ID.")
            operations.append(
                ScenarioOperation(row_id, operation, day, category, hours, note, tuple(ids), deepcopy(hashes), link)
            )
            targets.update(ids)
        except PlanningValidationError as exc:
            errors.extend({**item, "row_id": row_id} for item in exc.errors)
    if errors:
        raise PlanningValidationError(errors)
    assumptions = document.get("assumptions", {})
    if not isinstance(assumptions, dict):
        _invalid("assumptions", "Scenario assumptions must be an object.")
    assumptions = deepcopy(assumptions)
    if "budget_credit_caps" in assumptions and not isinstance(assumptions["budget_credit_caps"], bool):
        _invalid("assumptions", "budget_credit_caps must be true or false.")
    assumptions["historical_cutoff_limitation"] = HISTORICAL_CUTOFF_WARNING
    return Scenario(
        name.strip(),
        deepcopy(source),
        cutoff.isoformat(),
        horizon.isoformat(),
        tuple(sorted(operations, key=lambda op: op.row_id)),
        clean_reserves,
        assumptions,
    )


def export_scenario(scenario: Scenario) -> str:
    return json.dumps(scenario.to_dict(), indent=2, sort_keys=True, allow_nan=False) + "\n"


def import_scenario(snapshot: dict, current: Scenario, text: str, *, mode: Literal["replace", "merge"]) -> Scenario:
    """Return a new validated definition; failures never alter active state."""
    if mode not in {"replace", "merge"}:
        _invalid("mode", "Choose explicitly whether to replace or merge the scenario.")
    try:
        document = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError) as exc:
        _invalid("json", f"Invalid scenario JSON: {exc}")
    imported = validate_scenario(snapshot, document)
    if mode == "replace":
        return imported
    if imported.cutoff != current.cutoff or imported.horizon != current.horizon:
        _invalid("horizon", "Merge requires the same cutoff and horizon as the active scenario.")
    merged = current.to_dict()
    merged["operations"] = [asdict(op) for op in (*current.operations, *imported.operations)]
    merged["reserves"] = {**current.reserves, **imported.reserves}
    return validate_scenario(snapshot, merged)


@dataclass(frozen=True)
class CategoryProjection:
    cutoff_balance: float | None
    horizon_balance: float | None
    minimum_balance: float | None
    minimum_date: str | None
    first_reserve_breach: str | None
    reserve_shortfall: float | None
    earliest_negative_date: str | None
    negative_shortfall: float | None
    annual_pre_cap_balance: float | None = None
    annual_carryover: float | None = None
    prospective_forfeiture: float | None = None


@dataclass(frozen=True)
class CategoryComparison:
    category: str
    reserve: float | None
    baseline: CategoryProjection
    scenario: CategoryProjection


@dataclass(frozen=True)
class DailyBalance:
    date: str
    category: str
    baseline: float | None
    scenario: float | None
    delta: float | None


@dataclass(frozen=True)
class CapacityDay:
    date: str
    work_hours: float | None
    baseline_scheduled: float
    scenario_scheduled: float
    tentative_by_category: dict[str, float]
    remaining_capacity: float | None
    total_proposed_absence: float
    excess_hours: float | None


@dataclass(frozen=True)
class ProjectionEvent:
    id: str
    branch: str
    date: str
    category: str
    direction: str
    hours: float
    signed_hours: float
    timing: str
    status: str
    original_transaction_id: str | None
    scenario_row_id: str | None
    targeted_ids: tuple[str, ...]
    earned_transaction_id: str | None
    explanation: str


@dataclass(frozen=True)
class LotEffect:
    branch: str
    transaction_id: str
    category: str
    earned_date: str
    last_eligible_usage_date: str | None
    remaining_hours: float | None
    disposed_hours: float | None


@dataclass(frozen=True)
class ProjectionResult:
    source: dict[str, Any]
    cutoff: str
    horizon: str
    scenario_name: str
    assumptions: dict[str, Any]
    categories: tuple[CategoryComparison, ...]
    daily: tuple[DailyBalance, ...]
    capacity: tuple[CapacityDay, ...]
    events: tuple[ProjectionEvent, ...]
    lots: tuple[LotEffect, ...]
    warnings: tuple[PlanningWarning, ...]
    schema_version: int = SCHEMA_VERSION
    method_version: str = METHOD_VERSION
    operations: tuple[ScenarioOperation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_projection_snapshot(
    snapshot: dict, horizon: str, warnings: list[PlanningWarning], proposed_categories: set[str]
) -> tuple[dict, set[str]]:
    """Canonical accruals and validated policy on a private copy; unknown banks stay isolated."""
    work = deepcopy(dict(snapshot))
    config = deepcopy(work.get("snapshot_rules", getattr(snapshot, "config", {})))
    if not isinstance(config, dict):
        _invalid("snapshot_rules", "The backend must supply a configuration object.")
    work["snapshot_rules"] = config
    work.setdefault("entitlement_history", deepcopy(getattr(snapshot, "entitlement_history", [])))
    unknown: set[str] = set()
    transactions = []
    for transaction in work.get("transactions", []):
        category = str(transaction.get("category", "unknown"))
        try:
            if not transaction_is_effective(transaction):
                continue
            _date(transaction.get("date"), "transaction date")
            signed_balance_effect(transaction)
            if category not in CATEGORY_POLICIES:
                raise ValueError(f"Unsupported category {category!r}")
        except (ValueError, TypeError, KeyError) as exc:
            unknown.add(category)
            warnings.append(
                PlanningWarning(
                    "MALFORMED_SOURCE_RECORD", str(exc), category, transaction.get("date"), str(transaction.get("id"))
                )
            )
            continue
        if transaction.get("source") != "expiration-engine":
            transactions.append(transaction)
    work["transactions"] = transactions
    opening = work.setdefault("starting_balances", {})
    for category, amount in list(opening.items()):
        try:
            if isinstance(amount, bool) or not isfinite(float(amount)):
                raise ValueError
        except (ValueError, TypeError):
            unknown.add(category)
            opening.pop(category)
            warnings.append(
                PlanningWarning("INVALID_OPENING_BALANCE", "Opening balance is not a finite number.", category)
            )
    original_ids = {str(tx.get("id")) for tx in transactions}
    snapshot_accruals = set(snapshot.get("calculation_context", {}).get("synthetic_accrual_ids", []))
    try:
        seed_accruals(work)
    except (TypeError, ValueError, KeyError) as exc:
        _invalid("accruals", f"Cannot resolve canonical accruals: {exc}", code="INVALID_ACCRUAL_CONTEXT")
    for transaction in work["transactions"]:
        if (
            str(transaction.get("id")) not in original_ids or str(transaction.get("id")) in snapshot_accruals
        ) and transaction.get("source") == "auto_accrual":
            transaction["planning_synthetic_accrual"] = True
    configured_rules = config.get("rules", {})
    if not isinstance(configured_rules, dict):
        _invalid("snapshot_rules", "Configured category rules must be an object.")
    active = (
        {tx["category"] for tx in work["transactions"]}
        | {key for key, amount in opening.items() if amount}
        | proposed_categories
    )
    default_rules = Config().model_dump()["rules"]
    clean_rules = deepcopy(configured_rules)
    for category in sorted(set(CATEGORY_POLICIES) | set(configured_rules)):
        supplied = configured_rules.get(category, {})
        try:
            if not isinstance(supplied, dict):
                raise ValueError("Category rules are not an object")
            for flag in ("expires", "allow_extension", "enabled"):
                if flag in supplied and not isinstance(supplied[flag], bool):
                    raise ValueError(f"{flag} must be true or false")
            if category == "annual" and "carryover_limit_hours" in supplied:
                _hours(supplied["carryover_limit_hours"], "annual carryover limit")
            if category in active:
                category_policy(category, configured_rules)
            if category in proposed_categories and CATEGORY_POLICIES.get(category).mode == "usage_tracking":
                unknown.add(category)
                warnings.append(
                    PlanningWarning(
                        "UNMODELED_ENTITLEMENT",
                        "This purpose-restricted category tracks absence, not an available leave bank; entitlement and balance shortfall metrics are N/A.",
                        category,
                    )
                )
            if category in EXPIRING_CATEGORIES:
                rules = expiration_rules({"rules": {category: supplied}})
                rule = rules[category]
                if rule.get("expires") and rule.get("expiration_action", "warn") not in {
                    "warn",
                    "expire",
                    "expired",
                    "forfeit",
                    "forfeited",
                }:
                    raise ValueError("Unsupported expiration action")
                probe = deepcopy(work)
                probe["transactions"] = [tx for tx in probe["transactions"] if tx["category"] == category]
                synchronize_expirations(
                    probe, {**config, "rules": {category: supplied}}, as_of=_date(horizon, "horizon")
                )
                unproven_credit = float(opening.get(category, 0)) or any(
                    tx["category"] == category
                    and tx["direction"] not in {"earned", "restored"}
                    and signed_balance_effect(tx) > 0
                    and not (tx["direction"] == "starting_balance" and category in opening)
                    for tx in work["transactions"]
                )
                if rule.get("expires") and unproven_credit:
                    unknown.add(category)
                    warnings.append(
                        PlanningWarning(
                            "MISSING_LOT_PROVENANCE",
                            "Opening hours have no original earning date or deadline; exact availability and expiration effects are unknown.",
                            category,
                        )
                    )
            elif supplied.get("expires"):
                raise ValueError("Expiration is not modeled for this category")
        except (ValueError, TypeError, KeyError) as exc:
            unknown.add(category)
            clean_rules[category] = deepcopy(default_rules.get(category, {}))
            warnings.append(PlanningWarning("UNSUPPORTED_CATEGORY_POLICY", str(exc), category))
    config["rules"] = clean_rules
    # Only affected metrics become unknown. Other categories can still use the
    # shared calculator without letting unsupported policy corrupt their result.
    work["transactions"] = [tx for tx in work["transactions"] if tx["category"] not in unknown]
    work["starting_balances"] = {category: amount for category, amount in opening.items() if category not in unknown}
    return work, unknown


def _projection_events(
    work: dict, resolved: dict, branch: str, cutoff: str, horizon: str
) -> tuple[ProjectionEvent, ...]:
    original_ids = {
        str(tx.get("id"))
        for tx in work["transactions"]
        if not tx.get("planning_synthetic_accrual") and not tx.get("planning_row_id")
    }
    rows = []
    for transaction in resolved["transactions"]:
        if transaction["date"] > horizon or not transaction_is_effective(transaction):
            continue
        if transaction.get("direction") == "starting_balance" and transaction["category"] in work.get(
            "starting_balances", {}
        ):
            continue
        transaction_id = str(transaction.get("id", ""))
        row_id = transaction.get("planning_row_id")
        source = transaction.get("source")
        original_id = transaction_id if transaction_id in original_ids else transaction.get("allocation_event_id")
        timing = "Recorded Through Cutoff" if transaction["date"] <= cutoff else "Scheduled"
        explanation = str(transaction.get("description", ""))
        event_id = transaction_id
        if row_id:
            timing = "Tentative"
            explanation = f"Scenario {row_id}; {explanation}"
            original_id = None
            event_id = f"scenario:{row_id}:{transaction.get('earned_transaction_id') or 'unlinked'}:{transaction.get('allocation_order', [])}"
        elif source == "credit-cap-engine":
            timing = "Synthetic credit cap"
            original_id = None
            event_id = transaction_id
        elif source == "expiration-engine":
            timing = "Synthetic expiration"
            original_id = None
            event_id = f"synthetic:expiration:{transaction.get('earned_transaction_id')}:{transaction['date']}"
        elif transaction.get("planning_synthetic_accrual"):
            timing = "Synthetic accrual"
            original_id = None
            event_id = f"synthetic:accrual:{transaction['category']}:{transaction['date']}"
        elif transaction_id not in original_ids:
            timing = "Synthetic allocation"
            event_id = f"synthetic:allocation:{original_id}:{transaction.get('allocation_order', [])}"
        rows.append(
            ProjectionEvent(
                event_id,
                branch,
                transaction["date"],
                transaction["category"],
                transaction["direction"],
                float(transaction["hours"]),
                signed_balance_effect(transaction),
                timing,
                str(transaction.get("status", "planned")),
                str(original_id) if original_id else None,
                row_id,
                tuple(transaction.get("planning_targeted_ids", ())),
                transaction.get("earned_transaction_id"),
                explanation,
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.date, row.category, row.id)))


def _branch(
    work: dict, unknown: set[str], scenario: Scenario, branch: str, warnings: list[PlanningWarning]
) -> tuple[dict[str, list[float | None]], tuple[ProjectionEvent, ...], tuple[LotEffect, ...]]:
    if scenario.assumptions.get("budget_credit_caps"):
        from .credit_caps import credit_cap_limitation, simulate_credit_caps

        limitation = credit_cap_limitation(work.get("snapshot_rules", {}))
        if limitation:
            unknown = unknown | {"credit"}
            warnings.append(PlanningWarning("UNSUPPORTED_CREDIT_CAP", limitation, "credit", branch=branch))
        else:
            simulate_credit_caps(work, scenario.cutoff, scenario.horizon)
    categories = sorted(set(CATEGORY_POLICIES) | unknown)
    daily: dict[str, list[float | None]] = {category: [] for category in categories}
    cutoff, horizon = _date(scenario.cutoff, "cutoff"), _date(scenario.horizon, "horizon")
    day = cutoff
    while day <= horizon:
        try:
            totals = calculate_balances(work, until_date=day.isoformat())
        except (ValueError, TypeError, KeyError) as exc:
            _invalid(
                "snapshot", f"Canonical balance calculation failed on {day}: {exc}", code="INVALID_ACCOUNTING_CONTEXT"
            )
        for category in categories:
            value = totals.get(category, 0.0)
            daily[category].append(None if category in unknown or value is None else float(value))
        day += timedelta(days=1)
    resolved = deepcopy(work)
    state = synchronize_expirations(resolved, work["snapshot_rules"], as_of=horizon, include_nonexpiring=True)
    transaction_map = {str(tx.get("id")): tx for tx in resolved["transactions"]}
    for warning in state["warnings"]:
        transaction = transaction_map.get(str(warning.get("transaction_id")), {})
        warnings.append(
            PlanningWarning(
                warning["code"],
                warning["message"],
                warning.get("category", transaction.get("category")),
                transaction.get("date"),
                warning.get("transaction_id"),
                transaction.get("planning_row_id"),
                branch,
            )
        )
    lots = []
    for lot in state["lots"]:
        lot_id = str(lot["id"])
        disposals = [
            tx
            for tx in resolved["transactions"]
            if tx.get("earned_transaction_id") == lot_id and tx.get("source") == "expiration-engine"
        ]
        remaining = state["remaining"].get(lot_id)
        if lot.get("expiration_date") and lot["expiration_date"] < scenario.horizon:
            remaining = 0.0  # Warn-only expired hours are unavailable too.
        lots.append(
            LotEffect(
                branch,
                lot_id,
                lot["category"],
                str(lot.get("original_earned_date") or lot["date"]),
                lot.get("expiration_date"),
                remaining,
                sum(float(tx["hours"]) for tx in disposals),
            )
        )
    for category in sorted(unknown & set(EXPIRING_CATEGORIES)):
        lots.append(LotEffect(branch, "unknown-opening-or-policy", category, "", None, None, None))
    return daily, _projection_events(work, resolved, branch, scenario.cutoff, scenario.horizon), tuple(lots)


def _summary(values: list[float | None], category: str, scenario: Scenario, work: dict) -> CategoryProjection:
    cutoff = _date(scenario.cutoff, "cutoff")
    known = [(cutoff + timedelta(days=index), value) for index, value in enumerate(values) if value is not None]
    complete = len(known) == len(values)
    minimum = min(known, key=lambda item: item[1]) if complete and known else None
    reserve = scenario.reserves.get(category)
    breach = next(((day, value) for day, value in known if reserve is not None and value < reserve), None)
    negative = next(((day, value) for day, value in known if value < 0), None)
    pre_cap = carryover = forfeiture = None
    if category == "annual" and scenario.horizon == work["leave_year_end"] and values[-1] is not None:
        pre_cap = values[-1]
        result = calculate_use_or_lose(work, {"annual": pre_cap}, work["snapshot_rules"])
        carryover, forfeiture = result["annual_carryover"], result["use_or_lose"]
    return CategoryProjection(
        values[0],
        values[-1],
        minimum[1] if minimum else None,
        minimum[0].isoformat() if minimum else None,
        breach[0].isoformat() if breach else None,
        reserve - breach[1] if breach else None,
        negative[0].isoformat() if negative else None,
        -negative[1] if negative else None,
        pre_cap,
        carryover,
        forfeiture,
    )


def _schedule(snapshot: dict, warnings: list[PlanningWarning]) -> tuple[float | None, set[int], dict[str, Any]]:
    config = snapshot.get("snapshot_rules", {})
    context = snapshot.get("calculation_context", {})
    defaults = config.get("defaults", {})
    names = {name: index for index, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
    schedule = {
        key: deepcopy(defaults.get(key))
        for key in ("workday_start", "workday_end", "lunch_start", "lunch_end", "normal_workdays")
    }
    try:
        start, end, lunch_start, lunch_end = [
            datetime.strptime(schedule[key], "%H:%M")
            for key in ("workday_start", "workday_end", "lunch_start", "lunch_end")
        ]
        if not start <= lunch_start <= lunch_end <= end or start == end:
            raise ValueError("Only a same-day work tour with lunch inside the tour is supported.")
        workdays = {names[day.lower()] for day in schedule["normal_workdays"]}
        if not workdays:
            raise ValueError("No configured workdays.")
        hours = ((end - start).total_seconds() - (lunch_end - lunch_start).total_seconds()) / 3600
    except (ValueError, TypeError, KeyError) as exc:
        warnings.append(PlanningWarning("UNKNOWN_WORK_SCHEDULE", f"Working-hour capacity is N/A: {exc}"))
        hours, workdays = None, set()
    schedule.update(
        {
            "daily_work_hours": hours,
            "holiday_coverage": context.get("holiday_coverage", []),
            "hours_are_primary_units": True,
            "roster_assumption": "The same configured tour applies on each configured workday; irregular rosters are not reconstructed.",
        }
    )
    return hours, workdays, schedule


def working_calendar(
    snapshot: dict, start: str, end: str, warnings: list[PlanningWarning]
) -> tuple[dict[str, float | None], dict]:
    """Shared scheduled work exposure, before subtracting physical absences.

    Only backend-supplied settings/cached holidays are used. Missing context
    remains unknown; historical analysis and planning share the same calendar.
    """
    hours, weekdays, assumptions = _schedule(snapshot, warnings)
    config = snapshot.get("snapshot_rules", {})
    context = snapshot.get("calculation_context", {})
    enabled = config.get("holidays", {}).get("enabled", True)
    coverage = set(context.get("holiday_coverage", []))
    holidays = {
        str(row.get("observed_date") or row.get("date") or row.get("display_date"))
        for row in context.get("holidays", snapshot.get("holidays", []))
        if row.get("nonworking", True)
    }
    if enabled and not coverage:
        warnings.append(
            PlanningWarning(
                "MISSING_HOLIDAY_CONTEXT",
                "Cached holiday coverage is unavailable; working-hour capacity is N/A until the backend supplies it.",
            )
        )
    result = {}
    day, last = _date(start, "start"), _date(end, "end")
    while day <= last:
        key = day.isoformat()
        result[key] = (
            None
            if hours is None or (enabled and day.year not in coverage)
            else (hours if day.weekday() in weekdays and (not enabled or key not in holidays) else 0.0)
        )
        day += timedelta(days=1)
    assumptions["holidays_enabled"] = enabled
    return result, assumptions


def _capacity(
    snapshot: dict, baseline: dict, alternate: dict, scenario: Scenario, warnings: list[PlanningWarning]
) -> tuple[tuple[CapacityDay, ...], dict]:
    calendar, assumptions = working_calendar(snapshot, scenario.cutoff, scenario.horizon, warnings)
    original: dict[str, float] = {}
    scheduled: dict[str, float] = {}
    tentative: dict[str, dict[str, float]] = {}
    unknown_absence_dates = set()
    for transaction in snapshot.get("transactions", []):
        if transaction.get("direction") != "used" or transaction.get("category") == "fmla":
            continue
        try:
            signed_balance_effect(transaction)
        except (ValueError, TypeError, KeyError):
            unknown_absence_dates.add(str(transaction.get("date", "")))
    if unknown_absence_dates:
        warnings.append(
            PlanningWarning(
                "UNKNOWN_SCHEDULED_ABSENCE",
                "Malformed absence records make capacity uncertain on their dates; review the source warnings.",
            )
        )
    for branch, totals in ((baseline, original), (alternate, scheduled)):
        for transaction in branch["transactions"]:
            if not scenario.cutoff < transaction["date"] <= scenario.horizon or not transaction_is_physical_absence(
                transaction
            ):
                continue
            if transaction.get("planning_row_id"):
                per_category = tentative.setdefault(transaction["date"], {})
                per_category[transaction["category"]] = per_category.get(transaction["category"], 0.0) + float(
                    transaction["hours"]
                )
            else:
                totals[transaction["date"]] = totals.get(transaction["date"], 0.0) + float(transaction["hours"])
    rows = []
    day, end = _date(scenario.cutoff, "cutoff"), _date(scenario.horizon, "horizon")
    while day <= end:
        key = day.isoformat()
        available = None if key in unknown_absence_dates or "" in unknown_absence_dates else calendar[key]
        planned = sum(tentative.get(key, {}).values())
        scheduled_hours = scheduled.get(key, 0.0)
        total = scheduled_hours + planned
        excess = max(0.0, total - available) if available is not None else None
        rows.append(
            CapacityDay(
                key,
                available,
                original.get(key, 0.0),
                scheduled_hours,
                tentative.get(key, {}),
                max(0.0, available - scheduled_hours) if available is not None else None,
                total,
                excess,
            )
        )
        if excess:
            warnings.append(
                PlanningWarning(
                    "CAPACITY_CONFLICT",
                    f"Proposed absence exceeds this date's {available:g} working hours by {excess:g} hours; entries have not been moved or shortened.",
                    date=key,
                    branch="scenario",
                )
            )
        day += timedelta(days=1)
    return tuple(rows), assumptions


def project(snapshot: dict, scenario: Scenario | dict, *, today: date) -> ProjectionResult:
    """Project independently from one defensive copy; negative results are valid."""
    definition = validate_scenario(snapshot, scenario)
    warnings: list[PlanningWarning] = []
    context = snapshot.get("calculation_context", {})
    for warning in (*snapshot.get("accounting_warnings", ()), *context.get("warnings", ())):
        warnings.append(
            PlanningWarning(
                warning.get("code", "SOURCE_WARNING"),
                warning.get("message", str(warning)),
                warning.get("category"),
                warning.get("date"),
                warning.get("transaction_id"),
            )
        )
    if definition.cutoff < today.isoformat():
        warnings.append(PlanningWarning("HISTORICAL_CUTOFF", HISTORICAL_CUTOFF_WARNING))
    if definition.source["snapshot_fingerprint"] != source_identity(snapshot)["snapshot_fingerprint"]:
        warnings.append(
            PlanningWarning(
                "SNAPSHOT_CHANGED",
                "The snapshot changed; referenced originals were checked individually and unaffected operations remain valid.",
            )
        )
    for transaction in snapshot.get("transactions", []):
        if str(transaction.get("date", "")) <= definition.cutoff and str(
            transaction.get("status", "planned")
        ).strip().lower() in {
            "planned",
            "requested",
        }:
            try:
                if transaction_is_physical_absence(transaction):
                    warnings.append(
                        PlanningWarning(
                            "UNRESOLVED_RECORDED_STATUS",
                            "Recorded Through Cutoff identifies dates, not confirmed attendance; this absence remains planned/requested.",
                            transaction.get("category"),
                            transaction.get("date"),
                            str(transaction.get("id")),
                        )
                    )
            except ValueError:
                pass  # Detailed source validation below reports unsupported statuses.
    proposed_categories = {
        operation.category for operation in definition.operations if operation.category is not None
    } | set(definition.reserves)
    baseline, unknown = prepare_projection_snapshot(snapshot, definition.horizon, warnings, proposed_categories)
    for operation in definition.operations:
        if operation.category in RESTRICTED_CATEGORIES:
            warnings.append(
                PlanningWarning(
                    "PURPOSE_RESTRICTED_CATEGORY",
                    "The category was explicitly selected. Its projected balance does not establish eligibility for this purpose.",
                    operation.category,
                    operation.date,
                    row_id=operation.row_id,
                )
            )
    # Keep valid events from categories with unknown financial policy for capacity;
    # affected financial metrics remain null rather than invented balances.
    capacity_base = deepcopy(baseline)
    for transaction in snapshot.get("transactions", []):
        if transaction.get("category") not in unknown:
            continue
        try:
            _date(transaction.get("date"), "transaction date")
            signed_balance_effect(transaction)
            if transaction_is_physical_absence(transaction):
                capacity_base["transactions"].append(deepcopy(transaction))
        except (ValueError, TypeError, KeyError):
            continue
    alternate = deepcopy(baseline)
    capacity_alternate = deepcopy(capacity_base)
    targeted = {transaction_id for operation in definition.operations for transaction_id in operation.original_ids}
    for branch in (alternate, capacity_alternate):
        branch["transactions"] = [tx for tx in branch["transactions"] if str(tx.get("id")) not in targeted]
    original_ids = {str(tx.get("id")) for tx in snapshot.get("transactions", [])}
    for operation in definition.operations:
        if operation.operation == "remove":
            continue
        event_id = f"scenario:{operation.row_id}"
        if event_id in original_ids:
            _invalid("row_id", "Synthetic ID collides with a real transaction.", row_id=operation.row_id)
        transaction = scenario_transaction(operation)
        capacity_alternate["transactions"].append(deepcopy(transaction))
        if operation.category not in unknown:
            alternate["transactions"].append(transaction)
    base_daily, base_events, base_lots = _branch(baseline, unknown, definition, "baseline", warnings)
    scenario_daily, scenario_events, scenario_lots = _branch(alternate, unknown, definition, "scenario", warnings)
    categories = tuple(
        CategoryComparison(
            category,
            definition.reserves.get(category),
            _summary(base_daily[category], category, definition, baseline),
            _summary(scenario_daily[category], category, definition, alternate),
        )
        for category in sorted(base_daily)
    )
    daily = []
    start = _date(definition.cutoff, "cutoff")
    for category in sorted(base_daily):
        for index, (original, tentative_value) in enumerate(
            zip(base_daily[category], scenario_daily[category], strict=True)
        ):
            daily.append(
                DailyBalance(
                    (start + timedelta(days=index)).isoformat(),
                    category,
                    original,
                    tentative_value,
                    tentative_value - original if original is not None and tentative_value is not None else None,
                )
            )
    capacity, assumptions = _capacity(snapshot, capacity_base, capacity_alternate, definition, warnings)
    assumptions.update(
        {
            "daily_values": "Daily closing balances; same-day event ordering does not imply intraday certainty.",
            "recorded_through_cutoff": "Effective dated rows in the current snapshot, not reconstructed historical knowledge.",
            "accruals": "Canonical automatic accruals, posted once on configured dates with effective rate changes.",
            "time_increment_hours": time_increment(snapshot),
            "scenario_assumptions": deepcopy(definition.assumptions),
        }
    )
    unique_warnings = {json.dumps(asdict(warning), sort_keys=True): warning for warning in warnings}
    return ProjectionResult(
        source_identity(snapshot),
        definition.cutoff,
        definition.horizon,
        definition.name,
        assumptions,
        categories,
        tuple(daily),
        capacity,
        (*base_events, *scenario_events),
        (*base_lots, *scenario_lots),
        tuple(unique_warnings[key] for key in sorted(unique_warnings)),
        operations=definition.operations,
    )
