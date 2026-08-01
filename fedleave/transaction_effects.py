"""Authoritative transaction eligibility and balance-effect rules."""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Any, Mapping


class BalanceEffect(Enum):
    INCREASE = 1
    DECREASE = -1
    NEUTRAL = 0


TRANSACTION_DIRECTIONS = (
    "earned",
    "used",
    "worked",
    "adjusted",
    "expired",
    "forfeited",
    "starting_balance",
    "restored",
    "corrected",
    "reconciled",
    "forced_increase",
    "forced_decrease",
)
TRANSACTION_STATUSES = (
    "planned",
    "requested",
    "approved",
    "denied",
    "worked",
    "submitted",
    "certified",
    "reconciled",
    "cancelled",
)
INCREASE_DIRECTIONS = frozenset(
    {
        "earned",
        "worked",
        "adjusted",
        "starting_balance",
        "restored",
        "corrected",
        "reconciled",
        "forced_increase",
    }
)
DECREASE_DIRECTIONS = frozenset(
    {"used", "expired", "forfeited", "forced_decrease"}
)
INEFFECTIVE_STATUSES = frozenset({"denied", "cancelled"})


def transaction_is_effective(transaction: Mapping[str, Any]) -> bool:
    """Return whether a transaction is eligible to affect calculations."""
    if transaction.get("void"):
        return False
    status = str(transaction.get("status", "planned")).strip().lower() or "planned"
    if status not in TRANSACTION_STATUSES:
        raise ValueError(f"Unsupported transaction status: {status!r}")
    return status not in INEFFECTIVE_STATUSES


def direction_effect(direction: object) -> BalanceEffect:
    """Return the explicit effect for a direction, rejecting unknown values."""
    if direction in INCREASE_DIRECTIONS:
        return BalanceEffect.INCREASE
    if direction in DECREASE_DIRECTIONS:
        return BalanceEffect.DECREASE
    raise ValueError(f"Unsupported transaction direction: {direction!r}")


def signed_balance_effect(transaction: Mapping[str, Any]) -> float:
    """Return the signed hours contributed by one effective transaction."""
    if not transaction_is_effective(transaction):
        return 0.0

    try:
        hours = float(transaction.get("hours", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid transaction hours: {transaction.get('hours')!r}") from exc
    if not isfinite(hours):
        raise ValueError("Invalid transaction hours: value must be finite")
    if hours < 0:
        raise ValueError("Invalid transaction hours: value must not be negative")

    return hours * direction_effect(transaction.get("direction")).value
