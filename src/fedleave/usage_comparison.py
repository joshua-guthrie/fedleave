"""Pure cumulative used-hours curve for one leave year.

Balances, accrual tiers, cross-year comparisons and prediction are deliberately
absent from this model. The curve is the running total of effective ``used``
rows for the selected absence categories across the whole represented leave
year. Unknown categories and non-usage directions are simply not usage.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date

from .categories import CATEGORY_POLICIES
from .history import days
from .planning import source_identity
from .transaction_effects import TRANSACTION_DIRECTIONS, signed_balance_effect, transaction_is_effective

ABSENCE_CATEGORIES = tuple(category for category in CATEGORY_POLICIES if category not in {"overtime", "fmla"})


@dataclass(frozen=True)
class CumulativeParameters:
    categories: tuple[str, ...] = ("annual",)


@dataclass(frozen=True)
class CumulativeUsage:
    parameters: CumulativeParameters
    source: dict
    summary: dict
    points: tuple[dict, ...]
    transactions: tuple[dict, ...]
    warnings: tuple[dict, ...]
    schema_version: int = 1
    method_version: str = "cumulative-usage-2"


def cumulative_usage(snapshot, categories):
    """Compute cumulative effective used hours per day for one leave year.

    Input snapshots are never mutated. Each point is the running total of
    effective used hours from the year start through that date, inclusive.
    """
    snapshot = deepcopy(snapshot)
    if not categories or len(set(categories)) != len(categories) or set(categories) - set(ABSENCE_CATEGORIES):
        raise ValueError(
            "Select one or more distinct absence categories; overtime and FMLA tracking are not physical absence."
        )
    try:
        start = snapshot["leave_year_start"]
        end = snapshot["leave_year_end"]
        if date.fromisoformat(start).isoformat() != start or date.fromisoformat(end).isoformat() != end or end < start:
            raise ValueError("Leave-year bounds must be valid ISO dates in order.")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Leave-year bounds are invalid: {exc}") from exc

    year = snapshot["leave_year"]
    rows, warnings, malformed = [], [], 0
    for original in snapshot.get("transactions", []):
        if not isinstance(original, dict):
            malformed += 1
            warnings.append({"code": "INVALID_USAGE", "message": "A transaction is not an object."})
            continue
        category = original.get("category")
        if category not in categories:
            continue
        day = original.get("date")
        try:
            direction = original.get("direction")
            if direction != "used":
                if direction in TRANSACTION_DIRECTIONS:
                    continue
                raise ValueError(f"Unsupported transaction direction: {direction!r}.")
            if not transaction_is_effective(original):
                continue
            if not original.get("id") or original.get("hours") is None:
                raise ValueError("Usage needs an original transaction ID and hours.")
            if isinstance(original["hours"], bool):
                raise ValueError("Usage hours must be numeric, not a boolean.")
            effect = signed_balance_effect(original)
            if effect == 0:
                continue
            if date.fromisoformat(day).isoformat() != day or not start <= day <= end:
                raise ValueError("Usage date is outside the represented year or is not an ISO date.")
            status = str(original.get("status", "planned")).strip().lower() or "planned"
            if status in {"planned", "requested"}:
                warnings.append(
                    {
                        "code": "UNRESOLVED_RECORDED_STATUS",
                        "message": "The curve includes a planned/requested row; its date does not prove leave was taken.",
                        "transaction_id": original["id"],
                        "date": day,
                    }
                )
            rows.append(
                {
                    **deepcopy(original),
                    "hours": -effect,
                    "status": status,
                    "source_year": year,
                }
            )
        except (TypeError, ValueError, KeyError) as exc:
            malformed += 1
            warnings.append(
                {"code": "INVALID_USAGE", "message": str(exc), "date": day, "transaction_id": original.get("id")}
            )

    rows.sort(key=lambda row: (row["date"], str(row["id"])))
    by_date = {}
    for row in rows:
        by_date.setdefault(row["date"], []).append(row)
    points, total = [], 0.0
    for day in days(start, end):
        total += sum(row["hours"] for row in by_date.get(day, ()))
        points.append({"date": day, "hours": total})

    return CumulativeUsage(
        CumulativeParameters(categories),
        source_identity(snapshot),
        {
            "total_hours": total,
            "categories": list(categories),
            "source_year": year,
            "start": start,
            "end": end,
            "transaction_count": len(rows),
            "excluded_malformed": malformed,
        },
        tuple(points),
        tuple(rows),
        tuple(warnings),
    )
