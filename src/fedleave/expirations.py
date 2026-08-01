"""Track expiring leave as earned lots and allocate later use in FIFO order."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from math import ceil
from typing import Any

from .config import Config
from .ledger import generate_transaction_id

EXPIRING_CATEGORIES = ("comp", "travel_comp", "restored_annual", "time_off_award")
LOT_DIRECTIONS = {"earned", "restored"}
DISPOSAL_DIRECTIONS = {"used", "expired", "forfeited"}
EPSILON = 0.000001


def expiration_rules(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Merge configured expiration policies over defaults by leave category."""
    defaults = Config().model_dump()["rules"]
    supplied = (config or {}).get("rules", {})
    result: dict[str, dict[str, Any]] = {}
    for category in EXPIRING_CATEGORIES:
        rule = dict(defaults.get(category, {}))
        candidate = supplied.get(category, {}) if isinstance(supplied, dict) else {}
        if isinstance(candidate, dict):
            rule.update(candidate)
        result[category] = rule
    return result


def _expiration_for(
    transaction: dict[str, Any], rule: dict[str, Any], leave_year: dict[str, Any]
) -> tuple[str, int | None]:
    earned = date.fromisoformat(str(transaction["date"]))
    if transaction["category"] in {"comp", "travel_comp"}:
        periods = int(rule.get("expiration_pay_periods_after_earned", 26))
        earned_period = None
        period_end = earned
        for pay_period in leave_year.get("pay_periods", []):
            start = date.fromisoformat(str(pay_period["start_date"]))
            end = date.fromisoformat(str(pay_period["end_date"]))
            if start <= earned <= end:
                earned_period = int(pay_period.get("pay_period_number", 1))
                period_end = end
                break
        expires = period_end + timedelta(days=periods * 14)
        expiration_period = ((earned_period - 1 + periods) % 26) + 1 if earned_period else None
        return expires.isoformat(), expiration_period
    if transaction["category"] == "restored_annual":
        leave_years = int(rule.get("expiration_leave_years_after_restored", 2))
        leave_year_end = date.fromisoformat(str(leave_year.get("leave_year_end", earned.isoformat())))
        return (leave_year_end + timedelta(days=leave_years * 364)).isoformat(), None
    else:
        days = int(rule.get("expiration_days_after_earned") or 0)
    return (earned + timedelta(days=days)).isoformat(), None


def _active(transaction: dict[str, Any]) -> bool:
    return not transaction.get("void") and str(transaction.get("status", "")).lower() not in {
        "denied",
        "cancelled",
        "voided",
        "deleted",
    }


def synchronize_expirations(
    leave_year: dict[str, Any],
    config: dict[str, Any] | None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Assign expiration dates, FIFO-link uses, and post configured expirations.

    A use that spans earned lots is split into linked transactions so each lot's
    remaining balance and eventual disposal remain auditable.
    """
    as_of = as_of or date.today()
    rules = expiration_rules(config)
    transactions = leave_year.setdefault("transactions", [])
    changed = False

    lots: list[dict[str, Any]] = []
    for transaction in transactions:
        category = str(transaction.get("category", ""))
        rule = rules.get(category)
        if not rule or not rule.get("expires") or not _active(transaction):
            continue
        if transaction.get("direction") not in LOT_DIRECTIONS:
            continue
        if transaction.get("rolled_over_to_transaction_id"):
            continue
        if not transaction.get("expiration_date"):
            expiration_date, expiration_pp = _expiration_for(transaction, rule, leave_year)
            transaction["expiration_date"] = expiration_date
            transaction["expiration_pay_period"] = expiration_pp
            changed = True
        lots.append(transaction)

    lots.sort(key=lambda tx: (str(tx.get("expiration_date", "")), str(tx.get("date", "")), str(tx.get("id", ""))))
    remaining = {str(lot["id"]): float(lot.get("hours", 0.0)) for lot in lots}
    for transaction in transactions:
        earned_id = str(transaction.get("earned_transaction_id") or "")
        if _active(transaction) and earned_id in remaining and transaction.get("direction") in DISPOSAL_DIRECTIONS:
            remaining[earned_id] = max(0.0, remaining[earned_id] - float(transaction.get("hours", 0.0)))

    existing_ids = [str(tx.get("id", "")) for tx in transactions]
    additions: list[dict[str, Any]] = []
    uses = sorted(
        [
            tx
            for tx in transactions
            if _active(tx) and tx.get("direction") == "used" and not tx.get("earned_transaction_id")
        ],
        key=lambda tx: (str(tx.get("date", "")), str(tx.get("id", ""))),
    )
    for use in uses:
        category = str(use.get("category", ""))
        if category not in rules or not rules[category].get("expires"):
            continue
        needed = float(use.get("hours", 0.0))
        eligible = [
            lot
            for lot in lots
            if lot.get("category") == category
            and str(lot.get("date", "")) <= str(use.get("date", ""))
            and remaining.get(str(lot.get("id", "")), 0.0) > EPSILON
        ]
        first = True
        original_hours = needed
        for lot in eligible:
            if needed <= EPSILON:
                break
            lot_id = str(lot["id"])
            allocated = min(needed, remaining[lot_id])
            target = use if first else deepcopy(use)
            if not first:
                target["id"] = generate_transaction_id(str(use["date"]), existing_ids)
                existing_ids.append(str(target["id"]))
                additions.append(target)
            target["hours"] = allocated
            target["earned_transaction_id"] = lot_id
            remaining[lot_id] -= allocated
            needed -= allocated
            first = False
            changed = True
        if needed > EPSILON and not first:
            remainder = deepcopy(use)
            remainder["id"] = generate_transaction_id(str(use["date"]), existing_ids)
            existing_ids.append(str(remainder["id"]))
            remainder["hours"] = needed
            remainder["earned_transaction_id"] = None
            additions.append(remainder)
        elif first:
            use["hours"] = original_hours
    transactions.extend(additions)

    for lot in lots:
        lot_id = str(lot["id"])
        hours = remaining.get(lot_id, 0.0)
        expiration_date = date.fromisoformat(str(lot["expiration_date"]))
        rule = rules[str(lot["category"])]
        action = str(rule.get("expiration_action", "warn")).lower()
        if hours <= EPSILON or expiration_date > as_of or action not in {"expire", "expired", "forfeit", "forfeited"}:
            continue
        if any(
            _active(tx) and tx.get("earned_transaction_id") == lot_id and tx.get("source") == "expiration-engine"
            for tx in transactions
        ):
            continue
        direction = "forfeited" if action.startswith("forfeit") else "expired"
        tx_id = generate_transaction_id(expiration_date.isoformat(), existing_ids)
        existing_ids.append(tx_id)
        transactions.append(
            {
                "id": tx_id,
                "date": expiration_date.isoformat(),
                "category": lot["category"],
                "direction": direction,
                "hours": hours,
                "description": f"Automatic {direction} balance from earned lot {lot_id}",
                "status": "reconciled",
                "source": "expiration-engine",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "expiration_date": None,
                "expiration_pay_period": None,
                "earned_transaction_id": lot_id,
            }
        )
        remaining[lot_id] = 0.0
        changed = True

    return {"changed": changed, "rules": rules, "lots": lots, "remaining": remaining}


def expiration_report(
    leave_year: dict[str, Any],
    config: dict[str, Any] | None,
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Return lot status, reminder thresholds, and disposal totals as of a date."""
    as_of = as_of or date.today()
    state = synchronize_expirations(leave_year, config, as_of=as_of)
    rows = []
    for lot in state["lots"]:
        expiration = date.fromisoformat(str(lot["expiration_date"]))
        remaining_hours = state["remaining"].get(str(lot["id"]), 0.0)
        periods = max(0, ceil((expiration - as_of).days / 14))
        linked_disposals = [
            tx
            for tx in leave_year.get("transactions", [])
            if _active(tx)
            and tx.get("earned_transaction_id") == lot.get("id")
            and tx.get("direction") in DISPOSAL_DIRECTIONS
        ]
        automatic_disposal = next(
            (str(tx.get("direction")) for tx in linked_disposals if tx.get("source") == "expiration-engine"),
            None,
        )
        if automatic_disposal:
            status = automatic_disposal
        elif remaining_hours <= EPSILON:
            status = "used"
        elif expiration <= as_of:
            status = "warning"
        else:
            status = "active"
        rows.append(
            {
                "transaction_id": lot["id"],
                "category": lot["category"],
                "earned_date": lot.get("original_earned_date") or lot["date"],
                "earned_hours": float(lot.get("hours", 0.0)),
                "remaining_hours": remaining_hours,
                "expiration_date": lot["expiration_date"],
                "expiration_pay_period": lot.get("expiration_pay_period"),
                "expiration_pay_period_year": expiration.year,
                "pay_periods_remaining": periods,
                "hours_per_pay_period_to_use": remaining_hours / periods if periods else remaining_hours,
                "status": status,
            }
        )
    active = [row for row in rows if row["remaining_hours"] > EPSILON]
    thresholds = {
        str(n): sum(row["remaining_hours"] for row in active if row["pay_periods_remaining"] <= n)
        for n in (1, 3, 6, 12)
    }
    disposals = [
        tx
        for tx in leave_year.get("transactions", [])
        if _active(tx) and tx.get("direction") in {"expired", "forfeited"}
    ]
    return {
        "as_of": as_of.isoformat(),
        "leave_year": leave_year.get("leave_year"),
        "lots": rows,
        "earliest_expiration_date": min((row["expiration_date"] for row in active), default=None),
        "hours_expiring_within_pay_periods": thresholds,
        "expired_or_forfeited_this_leave_year": sum(
            float(tx.get("hours", 0.0))
            for tx in disposals
            if date.fromisoformat(str(tx.get("date"))).year == as_of.year
        ),
        "enabled_categories": [category for category, rule in state["rules"].items() if rule.get("expires")],
        "changed": state["changed"],
    }
