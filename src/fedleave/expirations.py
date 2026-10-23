"""Date-ordered lot allocation, inclusive deadlines, and auditable disposal."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from math import ceil
from typing import Any

from .categories import CATEGORY_POLICIES
from .config import Config
from .ledger import generate_transaction_id
from .payperiods import leave_year_period_count
from .transaction_effects import transaction_is_effective

EXPIRING_CATEGORIES = tuple(name for name, policy in CATEGORY_POLICIES.items() if policy.mode == "lot_carryover")
LOT_DIRECTIONS = {"earned", "restored"}
DISPOSAL_DIRECTIONS = {"used", "expired", "forfeited", "paid_out", "forced_decrease"}
EPSILON = 0.000001


def expiration_rules(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    defaults = Config().model_dump()["rules"]
    supplied = (config or {}).get("rules", {})
    if not isinstance(supplied, dict):
        raise ValueError("UNSUPPORTED_CATEGORY_POLICY: rules must be an object")
    result = {}
    for category in EXPIRING_CATEGORIES:
        candidate = supplied.get(category, {})
        if not isinstance(candidate, dict):
            raise ValueError(f"UNSUPPORTED_CATEGORY_POLICY: {category}")
        result[category] = {**defaults.get(category, {}), **candidate}
    return result


def _expiration_for(transaction: dict, rule: dict, leave_year: dict) -> tuple[str, int | None]:
    earned = date.fromisoformat(str(transaction.get("original_earned_date") or transaction["date"]))
    category = transaction["category"]
    if category in {"comp", "travel_comp"}:
        periods = int(rule.get("expiration_pay_periods_after_earned", 26))
        if not 1 <= periods <= 2600:
            raise ValueError(f"EXPIRATION_OUTSIDE_POLICY: {category}: invalid period count")
        period_end = earned
        for period in leave_year.get("pay_periods", []):
            if str(period["start_date"]) <= earned.isoformat() <= str(period["end_date"]):
                period_end = date.fromisoformat(period["end_date"])
                break
        # All biweekly periods have 14 days; numbering follows actual year
        # boundaries, including 27-period years, rather than modulo 26.
        expires = period_end + timedelta(days=14 * periods)
        if leave_year.get("leave_year_start"):
            start = date.fromisoformat(leave_year["leave_year_start"])
            year = int(leave_year.get("leave_year", start.year))
            count = int(leave_year.get("pay_period_count", 26))
            for _ in range(101):
                end = start + timedelta(days=count * 14 - 1)
                if start <= expires <= end:
                    return expires.isoformat(), (expires - start).days // 14 + 1
                start, year = end + timedelta(days=1), year + 1
                count = leave_year_period_count(start, year) if start.month == 1 else count
        return expires.isoformat(), None
    if category == "restored_annual":
        years = int(rule.get("expiration_leave_years_after_restored", 2))
        if not 0 <= years <= 100:
            raise ValueError("EXPIRATION_OUTSIDE_POLICY: invalid restored annual duration")
        end = date.fromisoformat(str(leave_year.get("leave_year_end", earned.isoformat())))
        year = int(leave_year.get("leave_year", earned.year))
        for offset in range(1, years + 1):
            start = end + timedelta(days=1)
            count = (
                leave_year_period_count(start, year + offset)
                if start.month == 1
                else int(leave_year.get("pay_period_count", 26))
            )
            end = start + timedelta(days=count * 14 - 1)
        return end.isoformat(), None
    days = rule.get("expiration_days_after_earned")
    if not isinstance(days, int) or days < 1:
        raise ValueError(f"UNSUPPORTED_CATEGORY_POLICY: {category} requires expiration_days_after_earned")
    return (earned + timedelta(days=days)).isoformat(), None


def _active(transaction: dict) -> bool:
    return transaction_is_effective(transaction)


def synchronize_expirations(
    leave_year: dict[str, Any],
    config: dict[str, Any] | None,
    *,
    as_of: date | None = None,
    include_nonexpiring: bool = False,
) -> dict[str, Any]:
    """Resolve in date order on the supplied private or explicitly writable object.

    expiration_date is the inclusive last eligible usage date. The derived
    disposal is effective the following day. Stored dates/extensions prevail.
    A legacy forward rollover link never hides the original historical lot.
    """
    as_of = as_of or date.today()
    before = deepcopy(leave_year)
    rules = expiration_rules(config)
    transactions = leave_year.setdefault("transactions", [])
    transactions[:] = [tx for tx in transactions if tx.get("source") != "expiration-engine"]
    for tx in transactions:
        if tx.get("allocation_source") == "expiration-engine":
            # FIFO links are derived, unlike user/legacy explicit links. A
            # correction to earning dates, hours or extensions may change them.
            tx["earned_transaction_id"] = None
    warnings: list[dict] = []
    lots = []
    for tx in transactions:
        rule = rules.get(str(tx.get("category")))
        if not rule or not _active(tx) or tx.get("direction") not in LOT_DIRECTIONS:
            continue
        if rule.get("expires"):
            if not tx.get("expiration_date"):
                tx["expiration_date"], tx["expiration_pay_period"] = _expiration_for(tx, rule, leave_year)
            if not tx.get("expiration_extension_reason"):
                tx.setdefault("original_expiration_date", tx["expiration_date"])
            expiration = date.fromisoformat(tx["expiration_date"])
            earned = date.fromisoformat(str(tx.get("original_earned_date") or tx["date"]))
            if expiration < earned or (tx.get("expiration_extension_reason") and not rule.get("allow_extension")):
                raise ValueError(f"EXPIRATION_OUTSIDE_POLICY: {tx.get('id')}")
        elif not include_nonexpiring:
            continue
        if str(tx["date"]) <= as_of.isoformat():
            lots.append(tx)
    lots.sort(
        key=lambda tx: (
            str(tx.get("expiration_date") or "9999-12-31"),
            str(tx.get("original_earned_date") or tx["date"]),
            str(tx["id"]),
        )
    )
    remaining = {str(tx["id"]): float(tx["hours"]) for tx in lots}
    if len(remaining) != len(lots):
        raise ValueError("CONFLICTING_CARRYOVER: duplicate local lot IDs")
    existing_ids = [str(tx.get("id", "")) for tx in transactions]
    additions = []
    events = sorted(
        [
            tx
            for tx in transactions
            if _active(tx) and tx.get("direction") in DISPOSAL_DIRECTIONS and str(tx["date"]) <= as_of.isoformat()
        ],
        key=lambda tx: (
            str(tx["date"]),
            str(tx.get("allocation_event_id", tx.get("id", ""))),
            tuple(tx.get("allocation_order", [])),
            str(tx.get("id", "")),
        ),
    )
    for use in events:
        category = str(use.get("category"))
        if category not in rules or (not rules[category].get("expires") and not include_nonexpiring):
            continue
        linked = str(use.get("earned_transaction_id") or "")
        if use["direction"] == "paid_out" and not rules[category].get("allow_payout_tracking"):
            warnings.append(
                {
                    "code": "CONFLICTING_CARRYOVER",
                    "transaction_id": use.get("id"),
                    "message": f"Payout tracking is disabled for {category}",
                }
            )
            continue
        needed = float(use["hours"])
        eligible = [
            lot
            for lot in lots
            if lot["category"] == category
            and str(lot["date"]) <= str(use["date"])
            and (
                use["direction"] != "used"
                or not lot.get("expiration_date")
                or str(use["date"]) <= str(lot["expiration_date"])
            )
            and remaining[str(lot["id"])] > EPSILON
            and (not linked or str(lot["id"]) == linked)
        ]
        if linked and (not eligible or remaining.get(linked, 0) + EPSILON < needed):
            warnings.append(
                {
                    "code": "CONFLICTING_CARRYOVER",
                    "transaction_id": use.get("id"),
                    "lot_id": linked,
                    "message": "Missing, exhausted, or ineligible linked lot",
                }
            )
            continue
        first = True
        part = 0
        event_id = use.get("allocation_event_id", use.get("id"))
        allocation_order = use.get("allocation_order", [])
        for lot in eligible:
            if needed <= EPSILON:
                break
            allocated = min(needed, remaining[str(lot["id"])])
            target = use if first else deepcopy(use)
            if not first:
                target["id"] = generate_transaction_id(str(use["date"]), existing_ids)
                existing_ids.append(target["id"])
                additions.append(target)
            target["hours"] = allocated
            target["earned_transaction_id"] = str(lot["id"])
            if not linked:
                target["allocation_source"] = "expiration-engine"
                target["allocation_event_id"] = event_id
                target["allocation_order"] = allocation_order if first else [*allocation_order, part]
            target["origin_leave_year"] = lot.get("origin_leave_year", leave_year.get("leave_year"))
            target["origin_transaction_id"] = lot.get("origin_transaction_id", lot["id"])
            remaining[str(lot["id"])] -= allocated
            needed -= allocated
            first = False
            part += 1
        if needed > EPSILON and not first:
            remainder = deepcopy(use)
            remainder["id"] = generate_transaction_id(str(use["date"]), existing_ids)
            existing_ids.append(remainder["id"])
            remainder["hours"] = needed
            remainder["earned_transaction_id"] = None
            remainder["allocation_event_id"] = event_id
            remainder["allocation_order"] = [*allocation_order, part]
            additions.append(remainder)
        if needed > EPSILON and use["direction"] == "used":
            warnings.append(
                {
                    "code": "MISSING_LOT_PROVENANCE",
                    "transaction_id": use.get("id"),
                    "category": category,
                    "hours": needed,
                    "message": "Usage has no eligible earned lot",
                }
            )
    transactions.extend(additions)
    for lot in lots:
        lot_id = str(lot["id"])
        deadline = lot.get("expiration_date")
        if not deadline or not rules[lot["category"]].get("expires"):
            continue
        effective = date.fromisoformat(deadline) + timedelta(days=1)
        action = str(rules[lot["category"]].get("expiration_action", "warn")).lower()
        if (
            remaining[lot_id] <= EPSILON
            or effective > as_of
            or action not in {"expire", "expired", "forfeit", "forfeited"}
        ):
            continue
        if leave_year.get("leave_year_end") and effective.isoformat() > leave_year["leave_year_end"]:
            continue
        direction = "forfeited" if action.startswith("forfeit") else "expired"
        tx_id = generate_transaction_id(effective.isoformat(), existing_ids)
        existing_ids.append(tx_id)
        transactions.append(
            {
                "id": tx_id,
                "date": effective.isoformat(),
                "category": lot["category"],
                "direction": direction,
                "hours": remaining[lot_id],
                "status": "reconciled",
                "source": "expiration-engine",
                "description": f"Automatic {direction} from lot {lot_id}",
                "earned_transaction_id": lot_id,
                "created_at": effective.isoformat() + "T00:00:00",
                "updated_at": effective.isoformat() + "T00:00:00",
            }
        )
        remaining[lot_id] = 0.0
    return {"changed": leave_year != before, "rules": rules, "lots": lots, "remaining": remaining, "warnings": warnings}


def expiration_report(
    leave_year: dict[str, Any], config: dict[str, Any] | None, *, as_of: date | None = None
) -> dict[str, Any]:
    as_of = as_of or date.today()
    state = synchronize_expirations(leave_year, config, as_of=as_of)
    rows = []
    for lot in state["lots"]:
        expiration = date.fromisoformat(lot["expiration_date"])
        remaining = state["remaining"][str(lot["id"])]
        periods = max(0, ceil((expiration - as_of).days / 14))
        disposals = [
            tx
            for tx in leave_year["transactions"]
            if _active(tx) and tx.get("earned_transaction_id") == lot["id"] and str(tx["date"]) <= as_of.isoformat()
        ]
        disposal = next((tx["direction"] for tx in disposals if tx.get("source") == "expiration-engine"), None)
        rows.append(
            {
                "transaction_id": lot["id"],
                "category": lot["category"],
                "origin_leave_year": lot.get("origin_leave_year", leave_year.get("leave_year")),
                "origin_transaction_id": lot.get("origin_transaction_id", lot["id"]),
                "origin_key": lot.get("origin_key"),
                "origin_amount_known": lot.get("origin_amount_known", True),
                "earned_date": lot.get("original_earned_date") or lot["date"],
                "earned_hours": float(
                    lot.get("origin_earned_hours") if lot.get("origin_earned_hours") is not None else lot["hours"]
                ),
                "remaining_hours": remaining,
                "available_hours": remaining if expiration >= as_of else 0.0,
                "expiration_date": lot["expiration_date"],
                "last_eligible_usage_date": lot["expiration_date"],
                "expiration_effective_date": (expiration + timedelta(days=1)).isoformat(),
                "expiration_pay_period": lot.get("expiration_pay_period"),
                "expiration_pay_period_year": expiration.year,
                "pay_periods_remaining": periods,
                "hours_per_pay_period_to_use": remaining / periods if periods else remaining,
                "status": disposal
                or ("used" if remaining <= EPSILON else "warning" if expiration < as_of else "active"),
            }
        )
    active = [row for row in rows if row["remaining_hours"] > EPSILON and row["status"] == "active"]
    warnings = [*leave_year.get("accounting_warnings", []), *state["warnings"]]
    for category, hours in leave_year.get("starting_balances", {}).items():
        if category in state["rules"] and state["rules"][category].get("expires") and float(hours):
            warnings.append(
                {
                    "code": "MISSING_LOT_PROVENANCE",
                    "category": category,
                    "hours": hours,
                    "message": "Opening balance has no original earned date or deadline",
                }
            )
    return {
        "as_of": as_of.isoformat(),
        "leave_year": leave_year.get("leave_year"),
        "lots": rows,
        "earliest_expiration_date": min((row["expiration_date"] for row in active), default=None),
        "hours_expiring_within_pay_periods": {
            str(n): sum(row["remaining_hours"] for row in active if row["pay_periods_remaining"] <= n)
            for n in (1, 3, 6, 12)
        },
        "expired_or_forfeited_this_leave_year": sum(
            float(tx["hours"])
            for tx in leave_year["transactions"]
            if _active(tx)
            and tx.get("direction") in {"expired", "forfeited"}
            and str(leave_year.get("leave_year_start", "")) <= str(tx["date"]) <= as_of.isoformat()
        ),
        "enabled_categories": [category for category, rule in state["rules"].items() if rule.get("expires")],
        "changed": state["changed"],
        "warnings": warnings,
    }
