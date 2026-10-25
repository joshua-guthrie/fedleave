"""Read-only linked snapshots and CLI-owned creation/reconciliation plans.

Manual metadata is an authoritative ancestry boundary. Only explicit carryover
links are traversed, once per operation. Plans are deterministic and bound to
canonical source, target, and policy fingerprints, never modification times.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, timedelta
from math import isfinite
from pathlib import Path
from typing import Any

from .categories import CATEGORY_POLICIES, category_policy
from .config import Config
from .expirations import EPSILON, synchronize_expirations
from .ledger import accrual_hours_for_date, calculate_balances, ensure_automatic_accruals
from .payperiods import generate_pay_periods, leave_year_period_count, validate_pay_periods
from .storage import atomic_write_json, backup_file, load_json, remove_legacy_transaction_history
from .transaction_effects import signed_balance_effect, transaction_is_effective


class AccountingError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class Snapshot(dict):
    """JSON-compatible state with operation-only configuration and warnings."""

    config: dict
    warnings: list[dict]
    entitlement_history: list[dict]


def seed_accruals(ledger: dict) -> None:
    """Generate reproducible preview records independent of the wall clock."""
    ensure_automatic_accruals(ledger, str(ledger["leave_year_end"]))
    for tx in ledger["transactions"]:
        if tx.get("source") == "auto_accrual":
            tx["created_at"] = tx["date"] + "T00:00:00"
            tx["updated_at"] = tx["date"] + "T00:00:00"


def fingerprint(value: Any) -> str:
    def canonical(item):
        if isinstance(item, dict):
            result = {key: canonical(val) for key, val in item.items() if key != "accounting_warnings"}
            if isinstance(result.get("transactions"), list):
                result["transactions"].sort(key=lambda tx: (str(tx.get("date", "")), str(tx.get("id", ""))))
            return result
        if isinstance(item, list):
            return [canonical(val) for val in item]
        return item

    value = canonical(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def effective_rules(config: dict | None) -> dict:
    defaults = Config().model_dump()["rules"]
    supplied = (config or {}).get("rules", {})
    if not isinstance(supplied, dict):
        raise AccountingError("UNSUPPORTED_CATEGORY_POLICY", "rules must be an object")
    for category, rule in supplied.items():
        if not isinstance(rule, dict):
            raise AccountingError("UNSUPPORTED_CATEGORY_POLICY", f"Malformed rule for {category}")
        defaults[category] = {**defaults.get(category, {}), **rule}
        for flag in ("expires", "allow_extension", "enabled"):
            if flag in rule and not isinstance(rule[flag], bool):
                raise AccountingError("UNSUPPORTED_CATEGORY_POLICY", f"{category}.{flag} must be true or false")
    return defaults


def source_fingerprint(source: dict, config: dict) -> str:
    return fingerprint({"ledger": fingerprint(source), "rules": effective_rules(config)})


def read_raw(base: Path, year: int) -> dict:
    if not 1 <= year <= 9998:
        raise AccountingError("INVALID_YEAR", "Leave-year identifier must be between 1 and 9998")
    path = base / "leave_years" / f"{year}.json"
    try:
        payload = load_json(path)
    except FileNotFoundError as exc:
        raise AccountingError("MISSING_SOURCE_YEAR", f"Leave year {year} is missing from {base}") from exc
    except (ValueError, OSError) as exc:
        raise AccountingError("INVALID_LEDGER", f"Cannot load {year}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("leave_year") != year:
        raise AccountingError("INVALID_LEDGER", f"Year metadata does not match {path.name}")
    if not isinstance(payload.get("transactions", []), list):
        raise AccountingError("INVALID_LEDGER", f"Transactions in {year} must be a list")
    if any(not isinstance(tx, dict) for tx in payload.get("transactions", [])):
        raise AccountingError("INVALID_LEDGER", f"Transactions in {year} must be objects")
    for field in ("starting_balances", "carryover_from_previous_year"):
        values = payload.get(field, {})
        if not isinstance(values, dict):
            raise AccountingError("INVALID_LEDGER", f"{field} in {year} must be an object")
        for category, amount in values.items():
            _number(amount, f"{year}.{field}.{category}")
    return payload


def opening_warnings(ledger: dict) -> list[dict]:
    mirrored = {}
    for tx in ledger.get("transactions", []):
        if (
            tx.get("direction") == "starting_balance"
            and not tx.get("carryover_generated")
            and transaction_is_effective(tx)
        ):
            category = tx.get("category")
            mirrored[category] = mirrored.get(category, 0) + float(tx["hours"])
    return [
        {
            "code": "DUPLICATE_OPENING_BALANCE",
            "category": category,
            "metadata_hours": ledger["starting_balances"][category],
            "transaction_hours": amount,
            "message": "Opening metadata counted once; use carryover-reconcile --repair-openings to remove mirrors",
        }
        for category, amount in sorted(mirrored.items())
        if category in ledger.get("starting_balances", {})
    ]


def _initialization(ledger: dict) -> dict:
    metadata = ledger.get("initialization", {})
    if not isinstance(metadata, dict):
        raise AccountingError("CONFLICTING_CARRYOVER", "Malformed initialization metadata")
    mode = metadata.get("mode", metadata.get("method"))
    if metadata.get("mode") and metadata.get("method") and metadata["mode"] != metadata["method"]:
        raise AccountingError("CONFLICTING_CARRYOVER", "Initialization mode and method disagree")
    if mode is None and metadata.get("source_leave_year") is not None:
        raise AccountingError("CONFLICTING_CARRYOVER", "Source linkage has no verified initialization mode")
    if mode == "manual" and metadata.get("source_leave_year") is not None:
        raise AccountingError("CONFLICTING_CARRYOVER", "Manual year cannot have a predecessor")
    if mode not in {None, "manual", "carryover"}:
        raise AccountingError("CONFLICTING_CARRYOVER", f"Unknown initialization mode {mode}")
    if mode == "carryover" and not isinstance(metadata.get("source_leave_year"), int):
        raise AccountingError("CONFLICTING_CARRYOVER", "Carryover source year is missing")
    return metadata


def resolve_snapshot(
    base: Path, year: int, config: dict | None = None, *, cache: dict[int, Snapshot] | None = None
) -> Snapshot:
    """Resolve only this explicit ancestry chain, without writing any file."""
    if (base / "carryover-reconciliation.json").exists():
        raise AccountingError("RECOVERY_REQUIRED", "Interrupted reconciliation; run carryover-reconcile --recover")
    config = config or (load_json(base / "config.json") if (base / "config.json").exists() else {})
    cache = {} if cache is None else cache
    if year in cache:
        return deepcopy(cache[year])
    raw = read_raw(base, year)
    rules = effective_rules(config)
    ledger = deepcopy(raw)
    remove_legacy_transaction_history(ledger)
    metadata = _initialization(ledger)
    warnings = []
    entitlement_history = []
    if metadata.get("mode", metadata.get("method")) == "carryover":
        source_year = metadata["source_leave_year"]
        if source_year != year - 1:
            raise AccountingError("SOURCE_NOT_CONTIGUOUS", f"Invalid predecessor {source_year} for {year}")
        try:
            source = resolve_snapshot(base, source_year, config, cache=cache)
        except AccountingError as exc:
            if exc.code == "MISSING_SOURCE_YEAR":
                raise AccountingError(
                    exc.code, "History incomplete: PPL/FMLA availability cannot be verified. " + str(exc)
                ) from exc
            raise
        from .parental import history

        entitlement_history = history(source)
        warnings.extend(source.warnings)
        if metadata.get("source_fingerprint") != source_fingerprint(source, config):
            derived, _ = derive_carryover(source, year, config, pay_periods=ledger.get("pay_period_count"))
            ledger = replace_generated(ledger, derived, config, allow_parental_conflicts=True)
            warnings.append(
                {
                    "code": "STALE_CARRYOVER",
                    "leave_year": year,
                    "source_leave_year": source_year,
                    "message": "Source changed; balances recomputed in memory. Run carryover-reconcile.",
                }
            )
    warnings.extend(opening_warnings(ledger))
    for category, hours in ledger.get("starting_balances", {}).items():
        if float(hours) and rules.get(category, {}).get("expires"):
            warnings.append(
                {
                    "code": "MISSING_LOT_PROVENANCE",
                    "category": category,
                    "hours": hours,
                    "message": "Opening balance has no original earning date or expiration",
                }
            )
    snapshot = Snapshot(ledger)
    snapshot.config = config
    snapshot.warnings = warnings
    snapshot.entitlement_history = entitlement_history
    from .parental import validate_parental_state

    try:
        validate_parental_state(snapshot, config)
    except ValueError as exc:
        snapshot.warnings.append({"code": "INVALID_PARENTAL_HISTORY", "message": str(exc)})
    cache[year] = deepcopy(snapshot)
    return snapshot


def _number(value: Any, description: str) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise AccountingError("INVALID_LEDGER", f"Invalid {description}") from exc
    if not isfinite(number):
        raise AccountingError("INVALID_LEDGER", f"Nonfinite {description}")
    return number


def derive_carryover(
    source: dict, year: int, config: dict, *, start: str | None = None, pay_periods: int | None = None
) -> tuple[dict, dict]:
    validate_pay_periods(source)
    if year != int(source["leave_year"]) + 1:
        raise AccountingError("SOURCE_NOT_CONTIGUOUS", "Select the immediately previous leave year")
    boundary = date.fromisoformat(source["leave_year_end"]) + timedelta(days=1)
    if start is not None and start != boundary.isoformat():
        raise AccountingError("SOURCE_NOT_CONTIGUOUS", f"Destination must start {boundary.isoformat()}")
    count = pay_periods if pay_periods is not None else leave_year_period_count(boundary, year)
    if count not in {26, 27}:
        raise AccountingError("UNSUPPORTED_PAY_PERIODS", "Choose 26 or 27 pay periods")
    periods = generate_pay_periods(boundary, count)
    cutoff = date.fromisoformat(source["leave_year_end"])
    work = deepcopy(dict(source))
    work["entitlement_history"] = deepcopy(
        getattr(source, "entitlement_history", source.get("entitlement_history", []))
    )
    remove_legacy_transaction_history(work)
    ids = []
    for tx in work.get("transactions", []):
        if not isinstance(tx, dict) or not tx.get("id") or tx["id"] in ids:
            raise AccountingError("INVALID_LEDGER", "Transactions require unique IDs")
        ids.append(tx["id"])
        signed_balance_effect(tx)
        tx_date = date.fromisoformat(tx["date"])
        if not date.fromisoformat(source["leave_year_start"]) <= tx_date <= cutoff:
            if tx.get("source") != "expiration-engine":
                raise AccountingError("INVALID_LEDGER", f"Transaction {tx['id']} is outside the leave year")
    ensure_automatic_accruals(work, cutoff.isoformat())
    state = synchronize_expirations(work, config, as_of=cutoff, include_nonexpiring=True)
    conflicts = [w for w in state["warnings"] if w["code"] == "CONFLICTING_CARRYOVER"]
    if conflicts:
        raise AccountingError("CONFLICTING_CARRYOVER", str(conflicts))
    balances = calculate_balances(work, until_date=cutoff.isoformat())
    rules = effective_rules(config)
    openings = {category: 0.0 for category in CATEGORY_POLICIES if category_policy_safe(category, rules)}
    transactions = []
    adjustments = []
    warnings = [*opening_warnings(work), *state["warnings"]]
    category_results = {}
    for category in sorted(set(balances) | set(work.get("starting_balances", {}))):
        balance = _number(balances.get(category, 0), f"{category} balance")
        retained_expired = sum(
            state["remaining"][str(lot["id"])]
            for lot in state["lots"]
            if lot["category"] == category
            and lot.get("expiration_date")
            and lot["expiration_date"] < cutoff.isoformat()
        )
        if category == "ppl":
            retained_expired = 0.0  # PPL balance already resolves its event window.
        available_balance = balance - retained_expired
        try:
            policy = category_policy(category, rules)
        except ValueError:
            if abs(balance) <= EPSILON:
                continue
            raise
        if policy.mode in {"usage_tracking", "noncarryable"}:
            category_results[category] = {"mode": policy.mode, "source_balance": balance, "opening": 0.0}
            continue
        cap = rules.get(category, {}).get(policy.cap_key) if policy.cap_key else None
        if cap is not None:
            cap = _number(cap, f"{category} carryover cap")
            if cap < 0:
                raise AccountingError("UNSUPPORTED_CATEGORY_POLICY", f"Negative {category} cap")
        opening = balance if cap is None else min(balance, cap)
        if policy.mode == "lot_carryover":
            category_lots = [lot for lot in state["lots"] if lot["category"] == category]
            known = sum(state["remaining"][str(lot["id"])] for lot in category_lots)
            unresolved = balance - known
            if category == "ppl":
                unresolved = float(work.get("starting_balances", {}).get("ppl", 0.0))
            if abs(unresolved) < EPSILON:
                unresolved = 0.0
            openings[category] = unresolved
            if unresolved:
                warnings.append(
                    {
                        "code": "MISSING_LOT_PROVENANCE",
                        "category": category,
                        "hours": unresolved,
                        "message": "Undated opening retained numerically; expiration unknown",
                    }
                )
            carried = 0.0
            origins = set()
            for lot in category_lots:
                hours = state["remaining"][str(lot["id"])]
                if (hours <= EPSILON and category != "ppl") or (
                    lot.get("expiration_date") and lot["expiration_date"] < boundary.isoformat()
                ):
                    continue
                legacy = lot.get("source") == "expiration-rollover" and not lot.get("origin_key")
                origin_year = lot.get("origin_leave_year", None if legacy else source["leave_year"])
                origin_id = str(
                    lot.get("origin_transaction_id")
                    or (lot.get("carried_from_transaction_id") if legacy else None)
                    or lot["id"]
                )
                earned_date = (
                    lot.get("original_earned_date")
                    if lot.get("source") == "expiration-rollover"
                    else lot.get("original_earned_date") or lot["date"]
                )
                origin_key = lot.get("origin_key") or (
                    "legacy:" + fingerprint({"id": origin_id, "earned": earned_date, "category": category})
                    if legacy
                    else f"{origin_year}:{origin_id}"
                )
                origin_amount = lot.get("origin_earned_hours", None if legacy else lot["hours"])
                origin_remaining = hours
                if category == "ppl":
                    from .parental import weekly_hours

                    current_week = weekly_hours(config)
                    origin_week = float(
                        lot.get("origin_scheduled_weekly_hours", lot.get("scheduled_weekly_hours", current_week))
                    )
                    origin_remaining = hours * origin_week / current_week
                if origin_year is not None and (not isinstance(origin_year, int) or origin_year > source["leave_year"]):
                    raise AccountingError("CONFLICTING_CARRYOVER", f"Invalid origin year for lot {lot['id']}")
                if (
                    origin_amount is not None
                    and _number(origin_amount, "origin earned amount") + EPSILON < origin_remaining
                ):
                    raise AccountingError("CONFLICTING_CARRYOVER", f"Lot {lot['id']} exceeds its original entitlement")
                origin = origin_key
                if legacy:
                    warnings.append(
                        {
                            "code": "MISSING_LOT_PROVENANCE",
                            "transaction_id": lot["id"],
                            "message": "Legacy carryover original grant/year is unverified; retained stable legacy origin",
                        }
                    )
                if origin in origins:
                    raise AccountingError("CONFLICTING_CARRYOVER", f"Duplicate origin {origin}")
                origins.add(origin)
                dispositions = dict(lot.get("origin_dispositions", {}))
                for event in work["transactions"]:
                    if (
                        (
                            event.get("earned_transaction_id") == lot["id"]
                            or any(
                                allocation.get("transaction_id") == lot["id"]
                                for allocation in event.get("ppl_allocations", [])
                            )
                        )
                        and transaction_is_effective(event)
                        and event.get("direction") in {"used", "paid_out", "forfeited", "expired", "forced_decrease"}
                        and str(event["date"]) <= cutoff.isoformat()
                    ):
                        direction = event["direction"]
                        allocated = next(
                            (
                                allocation["hours"]
                                for allocation in event.get("ppl_allocations", [])
                                if allocation["transaction_id"] == lot["id"]
                            ),
                            event["hours"],
                        )
                        dispositions[direction] = dispositions.get(direction, 0.0) + float(allocated)
                row = deepcopy(lot)
                local_id = f"carry-{origin_year}-{fingerprint(origin_key)[:20]}"
                row.update(
                    {
                        "id": local_id,
                        "date": boundary.isoformat(),
                        "hours": hours,
                        "source": "expiration-rollover",
                        "status": "reconciled",
                        "carryover_generated": True,
                        "original_earned_date": earned_date,
                        "origin_key": origin_key,
                        "origin_dispositions": dispositions,
                        "origin_leave_year": origin_year,
                        "origin_transaction_id": origin_id,
                        "origin_earned_hours": origin_amount,
                        "origin_amount_known": origin_amount is not None,
                        "previously_consumed_hours": None
                        if origin_amount is None
                        else float(origin_amount) - origin_remaining,
                        "carried_from_leave_year": source["leave_year"],
                        "carried_from_transaction_id": lot["id"],
                        "carryover_chain": [*lot.get("carryover_chain", []), source["leave_year"]],
                        "created_at": boundary.isoformat() + "T00:00:00",
                        "updated_at": boundary.isoformat() + "T00:00:00",
                    }
                )
                if category == "ppl":
                    row.update(scheduled_weekly_hours=current_week, origin_scheduled_weekly_hours=origin_week)
                row.pop("rolled_over_to_transaction_id", None)
                transactions.append(row)
                carried += hours
            opening = unresolved + carried
            if category == "ppl":
                opening = unresolved + min(
                    (row["hours"] for row in transactions if row["category"] == "ppl"), default=0.0
                )
        else:
            openings[category] = opening
            if opening > EPSILON:
                transactions.append(
                    {
                        "id": f"opening-{year}-{category}",
                        "date": boundary.isoformat(),
                        "category": category,
                        "direction": "starting_balance",
                        "hours": opening,
                        "status": "reconciled",
                        "source": "carryover",
                        "carryover_generated": True,
                    }
                )
        if abs(available_balance - opening) > EPSILON:
            adjustments.append(
                {
                    "category": category,
                    "hours": available_balance - opening,
                    "reason": "cap" if cap is not None else "expired_at_boundary",
                    "disposition": "reported_reduction",
                    "posted_transaction": False,
                }
            )
        category_results[category] = {
            "mode": policy.mode,
            "source_balance": available_balance,
            "source_ledger_balance": balance,
            "retained_expired_hours": retained_expired,
            "opening": opening,
            "cap": cap,
        }
    metadata = {
        "mode": "carryover",
        "method": "carryover",
        "source_leave_year": source["leave_year"],
        "source_cutoff": source["leave_year_end"],
        "source_fingerprint": source_fingerprint(source, config),
    }
    target = {
        "schema_version": 1,
        "leave_year": year,
        "leave_year_start": boundary.isoformat(),
        "leave_year_end": periods[-1]["end_date"],
        "pay_period_count": count,
        "pay_periods": periods,
        "annual_leave_accrual_hours": accrual_hours_for_date(source, "annual", source["leave_year_end"]),
        "sick_leave_accrual_hours": accrual_hours_for_date(source, "sick", source["leave_year_end"]),
        "starting_balances": openings,
        "carryover_from_previous_year": {
            category: row["opening"]
            for category, row in category_results.items()
            if row["mode"] not in {"usage_tracking", "noncarryable"}
        },
        "transactions": transactions,
        "holidays": [],
        "initialization": metadata,
        "rollover_status": {
            "rolled_from_previous_year": True,
            "rolled_to_next_year": False,
            "rollover_completed_at": None,
        },
    }
    seed_accruals(target)
    summary = {
        "initialization_mode": "carryover",
        "source_leave_year": source["leave_year"],
        "from_year": source["leave_year"],
        "to_year": year,
        "source_start": source["leave_year_start"],
        "source_end": source["leave_year_end"],
        "leave_year_start": target["leave_year_start"],
        "leave_year_end": target["leave_year_end"],
        "pay_period_count": count,
        "categories": category_results,
        "opening_balances": target["carryover_from_previous_year"],
        "adjustments": adjustments,
        "lots": [tx for tx in transactions if tx.get("source") == "expiration-rollover"],
        "source_fingerprint": metadata["source_fingerprint"],
        "warnings": warnings,
        "annual_balance": balances.get("annual", 0),
        "sick_balance": balances.get("sick", 0),
        "carryover_limit": rules["annual"].get("carryover_limit_hours", 240),
        "carry_forward": openings.get("annual", 0),
        "forfeiture": max(0, balances.get("annual", 0) - openings.get("annual", 0)),
        "carried_expiring_lots": len([tx for tx in transactions if tx.get("source") == "expiration-rollover"]),
    }
    return target, summary


def category_policy_safe(category: str, rules: dict) -> bool:
    try:
        return category_policy(category, rules).mode in {"balance_carryover", "lot_carryover"}
    except ValueError:
        return False


def replace_generated(target: dict, derived: dict, config: dict, *, allow_parental_conflicts: bool = False) -> dict:
    """Replace only marked derived records; reject orphan links and deficits."""
    result = deepcopy(target)
    genuine = [
        deepcopy(tx)
        for tx in target.get("transactions", [])
        if not tx.get("carryover_generated") and tx.get("source") != "expiration-engine"
    ]
    generated = [deepcopy(tx) for tx in derived["transactions"] if tx.get("carryover_generated")]
    old_by_id = {tx.get("id"): tx for tx in target.get("transactions", [])}
    for row in generated:
        old = old_by_id.get(row["id"], {})
        if old.get("extension_approved_in_leave_year") == target.get("leave_year"):
            rule = effective_rules(config).get(row["category"], {})
            if not rule.get("allow_extension"):
                raise AccountingError("EXPIRATION_OUTSIDE_POLICY", f"Extension disabled for {row['category']}")
            if str(old.get("expiration_date", "")) > str(row.get("expiration_date", "")):
                for field in (
                    "original_expiration_date",
                    "expiration_date",
                    "expiration_pay_period",
                    "expiration_extension_reason",
                    "expiration_extended_at",
                    "expiration_extensions",
                    "extension_approved_in_leave_year",
                ):
                    if field in old:
                        row[field] = deepcopy(old[field])
    if not any(tx.get("carryover_generated") for tx in target.get("transactions", [])) and any(
        tx.get("source") == "expiration-rollover" for tx in genuine
    ):
        raise AccountingError("CONFLICTING_CARRYOVER", "Legacy rollover requires explicit opening repair")
    ids = {tx["id"] for tx in generated}
    if any(tx.get("id") in ids for tx in genuine):
        raise AccountingError("CONFLICTING_CARRYOVER", "Generated ID collides with genuine activity")
    for key in ("starting_balances", "carryover_from_previous_year", "initialization"):
        result[key] = deepcopy(derived[key])
    result["transactions"] = [*generated, *genuine]
    work = deepcopy(result)
    state = synchronize_expirations(
        work, config, as_of=date.fromisoformat(result["leave_year_end"]), include_nonexpiring=True
    )
    conflicts = [w for w in state["warnings"] if w["code"] == "CONFLICTING_CARRYOVER"]
    conflicts.extend(
        w
        for w in state["warnings"]
        if w["code"] == "MISSING_LOT_PROVENANCE"
        and not float(result.get("starting_balances", {}).get(w.get("category"), 0))
    )
    if allow_parental_conflicts:
        # Reads preserve orphaned historical PPL usage for diagnostics. Explicit
        # reconciliation/mutations must still reject an invalid proposed state.
        conflicts = [row for row in conflicts if row.get("category") != "ppl"]
    if conflicts:
        raise AccountingError("CONFLICTING_CARRYOVER", str(conflicts))
    return result


def creation_plan(
    base: Path, from_year: int, to_year: int, *, start: str | None = None, pay_periods: int | None = None
) -> tuple[dict, dict]:
    path = base / "leave_years" / f"{to_year}.json"
    if path.exists() or path.is_symlink():
        raise AccountingError("DESTINATION_EXISTS", f"{path}; use carryover-reconcile for an existing linked year")
    config = load_json(base / "config.json") if (base / "config.json").exists() else {}
    source = resolve_snapshot(base, from_year, config)
    target, summary = derive_carryover(source, to_year, config, start=start, pay_periods=pay_periods)
    summary["warnings"].extend(source.warnings)
    summary.update(
        {
            "preview_fingerprint": fingerprint(
                {"target": target, "source": read_raw(base, from_year), "config": config}
            ),
            "created_file": None,
            "created_transaction_ids": [],
        }
    )
    return target, summary


def apply_creation(base: Path, target: dict, summary: dict, expected: str | None = None) -> dict:
    current_target, current_summary = creation_plan(
        base,
        target["initialization"]["source_leave_year"],
        target["leave_year"],
        start=target["leave_year_start"],
        pay_periods=target["pay_period_count"],
    )
    if current_summary["preview_fingerprint"] != summary["preview_fingerprint"]:
        raise AccountingError("STALE_PREVIEW", "Source or policy changed; regenerate the preview")
    target = current_target
    if expected is not None and expected != summary["preview_fingerprint"]:
        raise AccountingError("STALE_PREVIEW", "Source or policy changed; regenerate the preview")
    path = base / "leave_years" / f"{target['leave_year']}.json"
    if path.parent.is_symlink() or path.is_symlink():
        raise AccountingError("INVALID_PATH", "Leave-year paths must not be symbolic links")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, target, overwrite=False)
    return {
        **summary,
        "action": "applied",
        "created_file": str(path),
        "created_transaction_ids": [tx["id"] for tx in target["transactions"] if tx.get("carryover_generated")],
    }


def reconciliation_plan(base: Path, year: int, *, repair_openings: bool = False) -> tuple[dict[int, dict], dict]:
    journal = base / "carryover-reconciliation.json"
    if journal.exists():
        raise AccountingError("RECOVERY_REQUIRED", "Run carryover-reconcile --recover before another apply")
    config = load_json(base / "config.json") if (base / "config.json").exists() else {}
    changes = {}
    originals = {}
    rows = []
    cache: dict[int, Snapshot] = {}
    current = year
    while (base / "leave_years" / f"{current}.json").exists():
        raw = read_raw(base, current)
        originals[current] = raw
        metadata = _initialization(raw)
        mode = metadata.get("mode", metadata.get("method"))
        year_warnings = []
        if mode != "carryover":
            if current != year:
                break
            if not repair_openings:
                raise AccountingError(
                    "MANUAL_BOUNDARY",
                    "Only linked carryover years can be reconciled; manual ancestry remains independent",
                )
            updated = deepcopy(raw)
        else:
            source_year = metadata["source_leave_year"]
            source = cache.get(source_year) or resolve_snapshot(base, source_year, config, cache=cache)
            if source_year != current - 1:
                raise AccountingError("SOURCE_NOT_CONTIGUOUS", f"Invalid predecessor for {current}")
            derived, derivation = derive_carryover(
                source, current, config, start=raw["leave_year_start"], pay_periods=raw["pay_period_count"]
            )
            year_warnings = derivation["warnings"]
            updated = replace_generated(raw, derived, config)
        if repair_openings:
            updated["transactions"] = [
                tx
                for tx in updated.get("transactions", [])
                if not (
                    tx.get("direction") == "starting_balance"
                    and not tx.get("carryover_generated")
                    and tx.get("category") in updated.get("starting_balances", {})
                )
            ]
        snapshot = Snapshot(updated)
        snapshot.config, snapshot.warnings = config, []
        from .parental import history, validate_parental_state

        snapshot.entitlement_history = history(source) if mode == "carryover" else []
        validate_parental_state(snapshot, config)
        cache[current] = snapshot
        old_lots = [tx for tx in raw.get("transactions", []) if tx.get("source") == "expiration-rollover"]
        new_lots = [tx for tx in updated.get("transactions", []) if tx.get("source") == "expiration-rollover"]
        changed = fingerprint(raw) != fingerprint(updated)
        rows.append(
            {
                "leave_year": current,
                "warnings": year_warnings,
                "changed": changed,
                "old_openings": raw.get("carryover_from_previous_year", raw.get("starting_balances", {})),
                "new_openings": updated.get("carryover_from_previous_year", updated.get("starting_balances", {})),
                "old_lots": old_lots,
                "new_lots": new_lots,
                "removed_lot_ids": sorted({tx["id"] for tx in old_lots} - {tx["id"] for tx in new_lots}),
            }
        )
        if changed:
            changes[current] = updated
        current += 1
        next_path = base / "leave_years" / f"{current}.json"
        if next_path.exists():
            next_raw = read_raw(base, current)
            if _initialization(next_raw).get("source_leave_year") != current - 1:
                break
    if not rows:
        raise AccountingError("MISSING_SOURCE_YEAR", f"Leave year {year} does not exist")
    summary = {
        "action": "preview",
        "repair_openings": repair_openings,
        "years": rows,
        "affected_years": sorted(changes),
        "warnings": [warning for row in rows for warning in row.get("warnings", [])],
        "preview_fingerprint": fingerprint({"originals": originals, "changes": changes, "config": config}),
    }
    return changes, summary


def apply_reconciliation(base: Path, changes: dict[int, dict], summary: dict, expected: str | None = None) -> dict:
    # Recheck the original files even for direct service callers. CLI callers
    # also hold the datastore lock across planning and all writes.
    if summary.get("years"):
        _, current_summary = reconciliation_plan(
            base, summary["years"][0]["leave_year"], repair_openings=summary.get("repair_openings", False)
        )
        if current_summary["preview_fingerprint"] != summary["preview_fingerprint"]:
            raise AccountingError("STALE_PREVIEW", "Source, destination, or policy changed; regenerate preview")
    if expected is not None and summary["preview_fingerprint"] != expected:
        raise AccountingError("STALE_PREVIEW", "Source, destination, or policy changed; regenerate the preview")
    if not changes:
        return {**summary, "action": "unchanged", "backups": []}
    paths = {year: base / "leave_years" / f"{year}.json" for year in changes}
    if any(path.is_symlink() or path.parent.is_symlink() for path in paths.values()):
        raise AccountingError("INVALID_PATH", "Leave-year paths must not be symbolic links")
    originals = {str(year): load_json(path) for year, path in paths.items()}
    backups = [str(backup_file(path)) for path in paths.values()]
    journal = base / "carryover-reconciliation.json"
    atomic_write_json(journal, {"state": "pending", "originals": originals, "backups": backups}, overwrite=False)
    try:
        for year, updated in changes.items():
            atomic_write_json(paths[year], updated)
    except Exception as exc:
        try:
            recover_reconciliation(base)
        except Exception as recovery:
            raise AccountingError(
                "INCOMPLETE_RECONCILIATION", f"Apply failed: {exc}; recovery required: {recovery}; backups: {backups}"
            ) from exc
        raise AccountingError(
            "RECONCILIATION_ROLLED_BACK", f"Apply failed and all original ledgers restored: {exc}"
        ) from exc
    journal.unlink()
    return {**summary, "action": "applied", "backups": backups}


def recover_reconciliation(base: Path) -> dict:
    journal = base / "carryover-reconciliation.json"
    if not journal.exists():
        return {"action": "unchanged", "recovered_years": []}
    state = load_json(journal)
    for year, original in state["originals"].items():
        if not str(year).isdigit() or int(year) != original.get("leave_year"):
            raise AccountingError("INVALID_LEDGER", "Invalid recovery journal year")
        path = base / "leave_years" / f"{int(year)}.json"
        if path.is_symlink() or path.parent.is_symlink():
            raise AccountingError("INVALID_PATH", "Invalid recovery target")
        atomic_write_json(path, original)
    journal.unlink()
    return {"action": "recovered", "recovered_years": sorted(int(year) for year in state["originals"])}


def manual_ledger(
    year: int,
    start: str,
    annual_accrual: float,
    balances: dict,
    *,
    pay_periods: int | None = None,
    config: dict | None = None,
) -> dict:
    """Independent manual baseline; never discovers or imports older years."""
    if any(float(balances.get(category, 0.0)) for category in ("ppl", "fmla")):
        raise AccountingError("INVALID_PARENTAL_OPENING", "PPL needs a dated earned entitlement; FMLA is usage only")
    if not 1 <= year <= 9998:
        raise AccountingError("INVALID_YEAR", "Leave-year identifier must be between 1 and 9998")
    increment = _number((config or {}).get("defaults", {}).get("time_increment_hours", 0.25), "time increment")
    if increment <= 0:
        raise AccountingError("INVALID_HOURS", "Time increment must be positive")
    for category, value in {**balances, "annual_accrual": annual_accrual}.items():
        hours = _number(value, category)
        if hours < 0 or abs(hours / increment - round(hours / increment)) > EPSILON:
            raise AccountingError("INVALID_HOURS", f"{category} must be nonnegative in increments of {increment}")
    first = date.fromisoformat(start)
    count = (
        pay_periods
        if pay_periods is not None
        else (
            leave_year_period_count(first, year) if first.month == 1 and first.year == year and first.day <= 14 else 26
        )
    )
    if count not in {26, 27}:
        raise AccountingError("UNSUPPORTED_PAY_PERIODS", "Choose 26 or 27 periods")
    periods = generate_pay_periods(first, count)
    ledger = {
        "schema_version": 1,
        "leave_year": year,
        "leave_year_start": start,
        "leave_year_end": periods[-1]["end_date"],
        "pay_period_count": count,
        "pay_periods": periods,
        "annual_leave_accrual_hours": annual_accrual,
        "sick_leave_accrual_hours": (config or {}).get("defaults", {}).get("sick_leave_accrual_hours", 4.0),
        "starting_balances": deepcopy(balances),
        "carryover_from_previous_year": deepcopy(balances),
        "transactions": [],
        "holidays": [],
        "initialization": {"mode": "manual", "method": "manual", "source_leave_year": None},
        "rollover_status": {
            "rolled_from_previous_year": False,
            "rolled_to_next_year": False,
            "rollover_completed_at": None,
        },
    }
    seed_accruals(ledger)
    return ledger


def preflight_creation(base: Path, command: str, parameters: dict) -> None:
    """Validate creation before even creating a datastore lock file.

    Planning is repeated under the writer lock before apply; this first pass
    ensures rejected modes, existing destinations, and stale previews are inert.
    """
    year = parameters.get("year", parameters.get("to_year"))
    source_year = parameters.get("from_year")
    if command == "init" and source_year is not None:
        manual_values = [
            value for name, value in parameters.items() if name.endswith("_start") and name != "leave_year_start"
        ]
        if (
            parameters.get("manual")
            or any(value is not None for value in manual_values)
            or parameters.get("annual_accrual") is not None
        ):
            raise AccountingError(
                "MIXED_INITIALIZATION_MODES", "--from-year cannot include manual options, even zero-valued flags"
            )
    path = base / "leave_years" / f"{year}.json"
    if path.exists() or path.is_symlink():
        raise AccountingError("DESTINATION_EXISTS", str(path))
    expected = parameters.get("expected_fingerprint")
    if source_year is not None:
        from .cli_helpers import parse_iso_date

        start = parameters.get("leave_year_start")
        _, summary = creation_plan(
            base,
            source_year,
            year,
            start=parse_iso_date(start).isoformat() if start else None,
            pay_periods=parameters.get("pay_periods"),
        )
        token = summary["preview_fingerprint"]
    else:
        from .cli_helpers import parse_iso_date

        start = parameters.get("leave_year_start")
        if not start:
            raise AccountingError("MISSING_START_DATE", "Manual mode requires --leave-year-start")
        config = load_json(base / "config.json") if (base / "config.json").exists() else {}
        balances = {
            name[:-6]: 0 if value is None else value
            for name, value in parameters.items()
            if name.endswith("_start") and name != "leave_year_start"
        }
        ledger = manual_ledger(
            year,
            parse_iso_date(start).isoformat(),
            6 if parameters.get("annual_accrual") is None else parameters["annual_accrual"],
            balances,
            pay_periods=parameters.get("pay_periods"),
            config=config,
        )
        token = fingerprint({"ledger": ledger, "config": config})
    if expected is not None and expected != token:
        raise AccountingError("STALE_PREVIEW", "Source, inputs or policy changed; regenerate preview")
