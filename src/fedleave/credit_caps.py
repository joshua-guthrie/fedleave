"""Explicit, read-only planning simulation of future credit rollover caps.

This opt-in projection assumption does not change CLI ledger/default balances.
Only supplied private copies are changed; no storage capability is accepted.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import isfinite

from .ledger import calculate_balances
from .transaction_effects import transaction_is_effective


def credit_cap_limitation(config: dict) -> str | None:
    rules = config.get("rules", {}).get("credit", {})
    if not isinstance(rules, dict):
        return "Credit rules must be an object."
    if rules.get("expires") or rules.get("carryover_mode", "balance_carryover") != "balance_carryover":
        return "Credit expiry/custom carryover is not supported by the pay-period cap simulation."
    for flag in (
        "enabled",
        "forfeit_excess_at_pay_period_rollover",
        "same_day_use_allowed",
        "same_pay_period_use_allowed",
    ):
        if flag in rules and not isinstance(rules[flag], bool):
            return f"Credit {flag} must be true or false."
    try:
        cap = rules.get("max_carryover_hours", 24)
        if isinstance(cap, bool) or not isfinite(float(cap)) or float(cap) < 0:
            raise ValueError
    except (ValueError, TypeError):
        return "Credit rollover cap must be finite nonnegative hours."
    if rules.get("usable_when", "next_day") not in {"next_day", "same_day", "next_pay_period"}:
        return "Unsupported credit usable_when policy."
    return None


def simulate_credit_caps(work: dict, cutoff: str, horizon: str) -> tuple[dict, ...]:
    """Replay future boundaries once; earlier use/loss changes later excess.

    The deadline is period end (inclusive); simulated loss is next day. The
    final year's prospective loss is reported without inventing a later period.
    """
    config = work.get("snapshot_rules", {})
    limitation = credit_cap_limitation(config)
    if limitation:
        raise ValueError(limitation)
    rules = config.get("rules", {}).get("credit", {})
    work["transactions"] = [row for row in work.get("transactions", []) if row.get("source") != "credit-cap-engine"]
    if not rules.get("enabled", True) or not rules.get("forfeit_excess_at_pay_period_rollover", True):
        return ()
    cap, rows = float(rules.get("max_carryover_hours", 24)), []
    for period in sorted(work.get("pay_periods", []), key=lambda row: row["end_date"]):
        deadline = period["end_date"]
        if not cutoff <= deadline <= horizon:
            continue
        before = calculate_balances(work, until_date=deadline).get("credit", 0)
        effective = (date.fromisoformat(deadline) + timedelta(days=1)).isoformat()
        known_disposal = sum(
            float(tx["hours"])
            for tx in work["transactions"]
            if tx.get("category") == "credit"
            and tx.get("date") == effective
            and tx.get("direction") in {"forfeited", "expired"}
            and transaction_is_effective(tx)
        )
        excess = max(0, before - cap - known_disposal)
        rows.append(
            {
                "period_id": str(period["pay_period_number"]),
                "deadline": deadline,
                "effective_date": effective,
                "pre_cap_balance": before,
                "cap": cap,
                "prospective_loss": excess,
                "known_disposal": known_disposal,
            }
        )
        if excess and effective <= horizon:
            work["transactions"].append(
                {
                    "id": f"planning-credit-cap:{period['pay_period_number']}:{deadline}",
                    "date": effective,
                    "category": "credit",
                    "direction": "forfeited",
                    "hours": excess,
                    "status": "reconciled",
                    "source": "credit-cap-engine",
                    "description": f"Planning-only credit rollover above {cap:g} h; deadline {deadline}",
                }
            )
    return tuple(rows)
