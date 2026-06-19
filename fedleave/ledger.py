from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator


TRANSACTION_CATEGORIES = [
    "annual",
    "sick",
    "overtime",
    "comp",
    "credit",
    "travel_comp",
    "admin",
    "lwop",
    "military",
    "court",
    "religious_comp",
    "time_off_award",
    "excused",
    "holiday",
    "flex",
    "other",
    "restored_annual",
]

TRANSACTION_DIRECTIONS = [
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
    "voided",
]

TRANSACTION_STATUSES = [
    "planned",
    "requested",
    "approved",
    "denied",
    "worked",
    "submitted",
    "certified",
    "reconciled",
    "cancelled",
]


EARNED_DIRECTIONS = {"earned", "restored", "adjusted", "corrected", "reconciled"}
USED_DIRECTIONS = {"used", "expired", "forfeited", "voided"}
WORKED_DIRECTIONS = {"worked"}


class Transaction(BaseModel):
    id: str
    date: str
    category: str
    direction: str
    hours: float
    description: str = ""
    status: str = "planned"
    source: str = "manual"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    void: bool = False
    void_reason: str | None = None
    replaces_transaction_id: str | None = None
    correction_reason: str | None = None
    expiration_date: str | None = None
    expiration_pay_period: int | None = None
    earned_transaction_id: str | None = None

    @field_validator("category")
    def validate_category(cls, value: str) -> str:
        if value not in TRANSACTION_CATEGORIES:
            raise ValueError(
                f"Invalid category: {value}. Valid categories: {', '.join(TRANSACTION_CATEGORIES)}."
            )
        return value

    @field_validator("direction")
    def validate_direction(cls, value: str) -> str:
        if value not in TRANSACTION_DIRECTIONS:
            raise ValueError(
                f"Invalid direction: {value}. Valid directions: {', '.join(TRANSACTION_DIRECTIONS)}."
            )
        return value

    @field_validator("status")
    def validate_status(cls, value: str) -> str:
        if value not in TRANSACTION_STATUSES:
            raise ValueError(
                f"Invalid status: {value}. Valid statuses: {', '.join(TRANSACTION_STATUSES)}."
            )
        return value

    @field_validator("hours")
    def validate_hours(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Invalid hours: must be zero or positive. Example: --used 4.0")
        return value

    @field_validator("date")
    def validate_date(cls, value: str) -> str:
        try:
            normalized = _parse_iso_date(value).isoformat()
        except ValueError:
            raise ValueError(
                f"Invalid date: {value}. Use YYYY-MM-DD, for example 2026-01-11."
            )
        return normalized


def generate_transaction_id(date_str: str, existing_ids: list[str]) -> str:
    base = date_str.replace("-", "")
    sequence = 1
    used = {transaction_id.split("-")[-1] for transaction_id in existing_ids if transaction_id.startswith(base)}
    while f"{sequence:03d}" in used:
        sequence += 1
    return f"{base}-{sequence:03d}"


def normalize_direction(
    earned: float | None,
    used: float | None,
    worked: float | None,
    adjusted: float | None,
) -> tuple[str, float]:
    values = {
        "earned": earned,
        "used": used,
        "worked": worked,
        "adjusted": adjusted,
    }
    provided = {k: v for k, v in values.items() if v is not None}
    if len(provided) != 1:
        raise ValueError("Exactly one of --earned, --used, --worked, or --adjusted must be provided")
    direction, hours = next(iter(provided.items()))
    return direction, hours


def create_transaction(
    date: str,
    category: str,
    direction: str,
    hours: float,
    description: str = "",
    status: str = "planned",
    source: str = "manual",
    existing_ids: list[str] = None,
) -> Transaction:
    existing_ids = existing_ids or []
    transaction_id = generate_transaction_id(date, existing_ids)
    try:
        return Transaction(
            id=transaction_id,
            date=date,
            category=category,
            direction=direction,
            hours=hours,
            description=description,
            status=status,
            source=source,
        )
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", []))
            msg = err.get("msg", "Invalid value")
            errors.append(f"{loc}: {msg}" if loc else msg)
        raise ValueError("; ".join(errors)) from exc


def _parse_iso_date(date_str: str) -> date:
    normalized = _normalize_iso_date(date_str)
    try:
        return date.fromisoformat(normalized)
    except Exception as exc:
        raise ValueError(
            f"Invalid date: {date_str}. Use YYYY-MM-DD, for example 2026-01-11."
        ) from exc


def _normalize_iso_date(date_str: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if not match:
        return date_str
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def calculate_balances(
    leave_year: dict[str, Any],
    until_date: str | None = None,
    include_projected: bool = False,
    project_until: str | None = None,
) -> dict[str, float]:
    totals: dict[str, float] = {category: 0.0 for category in TRANSACTION_CATEGORIES}
    starting_balances = leave_year.get("starting_balances", {})
    for category, amount in starting_balances.items():
        totals[category] = float(amount)

    cutoff = _parse_iso_date(until_date) if until_date is not None else None
    for transaction in leave_year.get("transactions", []):
        tx_date = _parse_iso_date(transaction.get("date", ""))
        if cutoff is not None and tx_date > cutoff:
            continue

        category = transaction["category"]
        direction = transaction["direction"]
        hours = float(transaction.get("hours", 0.0))
        if category not in totals:
            totals[category] = 0.0

        if direction in EARNED_DIRECTIONS or direction in WORKED_DIRECTIONS or direction == "starting_balance":
            totals[category] += hours
        elif direction in USED_DIRECTIONS:
            totals[category] -= hours
        else:
            totals[category] += hours

    if include_projected:
        if project_until is not None:
            projection_end = _parse_iso_date(project_until)
        else:
            projection_end = _parse_iso_date(leave_year.get("leave_year_end", ""))

        pay_periods = leave_year.get("pay_periods", [])
        annual_accrual = float(leave_year.get("annual_leave_accrual_hours", 0.0))
        sick_accrual = float(leave_year.get("sick_leave_accrual_hours", 0.0))

        for pay_period in pay_periods:
            accrual_date_str = pay_period.get("accrual_date") or pay_period.get("end_date")
            if not accrual_date_str:
                continue
            accrual_date = _parse_iso_date(accrual_date_str)
            if cutoff is not None and accrual_date <= cutoff:
                continue
            if accrual_date > projection_end:
                continue

            if not _has_auto_accrual(leave_year, "annual", accrual_date.isoformat()):
                totals["annual"] += annual_accrual
            if not _has_auto_accrual(leave_year, "sick", accrual_date.isoformat()):
                totals["sick"] += sick_accrual

    return totals


def calculate_use_or_lose(leave_year: dict[str, Any], balances: dict[str, float], config: dict[str, Any] | None = None) -> dict[str, float]:
    carryover_limit = 240.0
    if config is not None:
        carryover_limit = float(
            config.get("rules", {}).get("annual", {}).get("carryover_limit_hours", carryover_limit)
        )
    annual_balance = balances.get("annual", 0.0)
    carryover_amount = min(annual_balance, carryover_limit)
    use_or_lose_amount = max(0.0, annual_balance - carryover_limit)
    return {
        "carryover_limit": carryover_limit,
        "annual_carryover": carryover_amount,
        "use_or_lose": use_or_lose_amount,
    }


def calculate_daily_activity(leave_year: dict[str, Any], day: str) -> dict[str, dict[str, float]]:
    target = _parse_iso_date(day)
    earned: dict[str, float] = {}
    used: dict[str, float] = {}
    net: dict[str, float] = {}

    for transaction in leave_year.get("transactions", []):
        if transaction.get("void"):
            continue
        tx_date = _parse_iso_date(transaction.get("date", ""))
        if tx_date != target:
            continue

        category = transaction["category"]
        direction = transaction["direction"]
        hours = float(transaction.get("hours", 0.0))

        if category not in earned:
            earned[category] = 0.0
            used[category] = 0.0
            net[category] = 0.0

        if direction in EARNED_DIRECTIONS or direction in WORKED_DIRECTIONS or direction == "starting_balance":
            earned[category] += hours
            net[category] += hours
        elif direction in USED_DIRECTIONS:
            used[category] += hours
            net[category] -= hours
        else:
            earned[category] += hours
            net[category] += hours

    return {"earned": earned, "used": used, "net": net}


def find_pay_period(leave_year: dict[str, Any], day: str) -> dict[str, Any]:
    target = _parse_iso_date(day)
    for pay_period in leave_year.get("pay_periods", []):
        start = _parse_iso_date(pay_period["start_date"])
        end = _parse_iso_date(pay_period["end_date"])
        if start <= target <= end:
            return pay_period
    raise ValueError(f"No pay period contains {day}")


def _has_auto_accrual(leave_year: dict[str, Any], category: str, accrual_date: str) -> bool:
    return any(
        transaction.get("source") == "auto_accrual"
        and transaction.get("category") == category
        and transaction.get("direction") == "earned"
        and transaction.get("date") == accrual_date
        and not transaction.get("void")
        for transaction in leave_year.get("transactions", [])
    )


def ensure_automatic_accruals(leave_year: dict[str, Any], through_date: str) -> int:
    """Add missing automatic annual/sick accrual transactions through a date."""
    cutoff = _parse_iso_date(through_date)
    existing_ids = [transaction.get("id", "") for transaction in leave_year.get("transactions", [])]
    annual_accrual = float(leave_year.get("annual_leave_accrual_hours", 0.0))
    sick_accrual = float(leave_year.get("sick_leave_accrual_hours", 4.0))
    added = 0

    for pay_period in leave_year.get("pay_periods", []):
        period_number = pay_period.get("pay_period_number")
        accrual_date = pay_period.get("accrual_date") or pay_period.get("end_date")
        if not accrual_date or _parse_iso_date(accrual_date) > cutoff:
            continue

        for category, hours in (("annual", annual_accrual), ("sick", sick_accrual)):
            if hours <= 0 or _has_auto_accrual(leave_year, category, accrual_date):
                continue
            transaction = create_transaction(
                date=accrual_date,
                category=category,
                direction="earned",
                hours=hours,
                description=f"Automatic {category} leave accrual for pay period {period_number}",
                status="reconciled",
                source="auto_accrual",
                existing_ids=existing_ids,
            )
            add_transaction_to_leave_year(leave_year, transaction)
            existing_ids.append(transaction.id)
            added += 1

    return added


def calculate_pay_period_activity(leave_year: dict[str, Any], day: str) -> dict[str, Any]:
    pay_period = find_pay_period(leave_year, day)
    start = _parse_iso_date(pay_period["start_date"])
    end = _parse_iso_date(pay_period["end_date"])
    earned: dict[str, float] = {}
    used: dict[str, float] = {}
    worked: dict[str, float] = {}
    net: dict[str, float] = {}

    for transaction in leave_year.get("transactions", []):
        if transaction.get("void"):
            continue
        tx_date = _parse_iso_date(transaction.get("date", ""))
        if not (start <= tx_date <= end):
            continue

        category = transaction["category"]
        direction = transaction["direction"]
        hours = float(transaction.get("hours", 0.0))
        earned.setdefault(category, 0.0)
        used.setdefault(category, 0.0)
        worked.setdefault(category, 0.0)
        net.setdefault(category, 0.0)

        if direction in WORKED_DIRECTIONS:
            worked[category] += hours
            earned[category] += hours
            net[category] += hours
        elif direction in EARNED_DIRECTIONS:
            earned[category] += hours
            net[category] += hours
        elif direction in USED_DIRECTIONS:
            used[category] += hours
            net[category] -= hours
        elif direction == "starting_balance":
            continue
        else:
            earned[category] += hours
            net[category] += hours

    return {
        "pay_period": pay_period,
        "earned": earned,
        "used": used,
        "worked": worked,
        "net": net,
    }


def add_transaction_to_leave_year(leave_year: dict[str, Any], transaction: Transaction) -> None:
    if "transactions" not in leave_year:
        leave_year["transactions"] = []
    leave_year["transactions"].append(transaction.model_dump())


def validate_leave_year(leave_year: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of issues found in a leave_year dict.

    Each issue is a dict with keys: 'type', 'path', 'message', and optional 'fix'.
    """
    issues: list[dict[str, Any]] = []
    # check starting balances
    sb = leave_year.get("starting_balances", {})
    if not isinstance(sb, dict):
        issues.append({"type": "starting_balances", "path": "starting_balances", "message": "starting_balances must be a mapping"})

    # check transactions
    for idx, tx in enumerate(leave_year.get("transactions", [])):
        path = f"transactions[{idx}]"
        # date
        date_str = tx.get("date", "")
        try:
            d = _parse_iso_date(date_str)
            normalized = d.isoformat()
            if normalized != date_str:
                issues.append({"type": "date", "path": path + ".date", "message": f"Non-canonical date: {date_str}", "fix": {"date": normalized}})
        except ValueError:
            # try to normalize; if normalization succeeds, suggest fix
            normalized = _normalize_iso_date(date_str)
            try:
                _ = date.fromisoformat(normalized)
                issues.append({"type": "date", "path": path + ".date", "message": f"Non-canonical date: {date_str}", "fix": {"date": normalized}})
            except Exception:
                issues.append({"type": "date", "path": path + ".date", "message": f"Invalid date: {date_str}"})

        # category
        cat = tx.get("category")
        if cat not in TRANSACTION_CATEGORIES:
            issues.append({"type": "category", "path": path + ".category", "message": f"Invalid category: {cat}"})

        # direction
        dirn = tx.get("direction")
        if dirn not in TRANSACTION_DIRECTIONS:
            issues.append({"type": "direction", "path": path + ".direction", "message": f"Invalid direction: {dirn}"})

        # status
        st = tx.get("status")
        if st not in TRANSACTION_STATUSES:
            issues.append({"type": "status", "path": path + ".status", "message": f"Invalid status: {st}"})

        # hours
        try:
            h = float(tx.get("hours", 0.0))
            if h < 0:
                issues.append({"type": "hours", "path": path + ".hours", "message": f"Negative hours: {h}"})
        except Exception:
            issues.append({"type": "hours", "path": path + ".hours", "message": f"Invalid hours value: {tx.get('hours')}"})

    return issues


def apply_fixes_to_leave_year(leave_year: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply automatic fixes suggested in issues and return new leave_year dict."""
    new = dict(leave_year)
    txs = [dict(t) for t in new.get("transactions", [])]
    for issue in issues:
        if issue.get("type") == "date" and issue.get("fix"):
            # path like transactions[3].date
            path = issue["path"]
            m = re.fullmatch(r"transactions\[(\d+)\]\.date", path)
            if m:
                idx = int(m.group(1))
                txs[idx]["date"] = issue["fix"]["date"]

    new["transactions"] = txs
    return new
