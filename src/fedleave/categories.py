"""Canonical category registry and extensible carryover policy resolution."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CategoryPolicy:
    mode: str
    cap_key: str | None = None
    requires_policy: bool = False


CATEGORY_POLICIES = {
    "annual": CategoryPolicy("balance_carryover", "carryover_limit_hours"),
    "sick": CategoryPolicy("balance_carryover", "carryover_limit_hours"),
    "credit": CategoryPolicy("balance_carryover", "max_carryover_hours"),
    "comp": CategoryPolicy("lot_carryover"),
    "travel_comp": CategoryPolicy("lot_carryover"),
    "restored_annual": CategoryPolicy("lot_carryover"),
    "time_off_award": CategoryPolicy("lot_carryover"),
    "religious_comp": CategoryPolicy("balance_carryover", requires_policy=True),
    **{
        name: CategoryPolicy("usage_tracking")
        for name in ("overtime", "admin", "lwop", "military", "court", "excused", "holiday", "flex", "other")
    },
}


def category_policy(category: str, rules: dict[str, Any]) -> CategoryPolicy:
    """Require an explicit decision for unknown or agency-specific policy."""
    default = CATEGORY_POLICIES.get(category)
    rule = rules.get(category, {})
    if not isinstance(rule, dict):
        raise ValueError(f"UNSUPPORTED_CATEGORY_POLICY: malformed rules for {category}")
    mode = rule.get("carryover_mode")
    if default is None and mode is None:
        raise ValueError(f"UNSUPPORTED_CATEGORY_POLICY: {category}")
    if mode is not None and mode not in {"balance_carryover", "lot_carryover", "usage_tracking", "noncarryable"}:
        raise ValueError(f"UNSUPPORTED_CATEGORY_POLICY: {category}: {mode}")
    if default and default.requires_policy and mode is None:
        raise ValueError(f"UNSUPPORTED_CATEGORY_POLICY: configure rules.{category}.carryover_mode")
    return CategoryPolicy(mode or default.mode, rule.get("carryover_cap_key", default.cap_key if default else None))
