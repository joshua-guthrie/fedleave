"""Pure deterministic quantization and capped proportional allocation."""

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from math import floor


def whole_units(hours, increment):
    return int(
        (Decimal(str(max(0, hours))) / Decimal(str(increment)) + Decimal("1e-9")).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )


def required_units(hours, increment):
    return int(
        (Decimal(str(max(0, hours))) / Decimal(str(increment)) - Decimal("1e-9")).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def hours_for_units(units, increment):
    return float(Decimal(str(increment)) * units)


def apportion_units(total, weights, caps):
    """Capped largest remainders; exact ties follow stable key order."""
    keys = sorted(weights)
    assigned = {key: 0 for key in keys}
    remaining = min(total, sum(caps.values()))
    while remaining:
        eligible = [key for key in keys if caps[key] > assigned[key] and weights[key] > 0]
        weight = sum(weights[key] for key in eligible)
        if not weight:
            break
        quotas = {key: remaining * weights[key] / weight for key in eligible}
        added = {key: min(caps[key] - assigned[key], floor(quotas[key])) for key in eligible}
        for key, amount in added.items():
            assigned[key] += amount
        remaining -= sum(added.values())
        if not remaining:
            break
        for key in sorted(eligible, key=lambda key: (-(quotas[key] - floor(quotas[key])), key)):
            if remaining and assigned[key] < caps[key]:
                assigned[key] += 1
                remaining -= 1
    return assigned
