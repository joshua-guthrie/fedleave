from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, validator


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

    @validator("category")
    def validate_category(cls, value: str) -> str:
        if value not in TRANSACTION_CATEGORIES:
            raise ValueError(f"Invalid category: {value}")
        return value

    @validator("direction")
    def validate_direction(cls, value: str) -> str:
        if value not in TRANSACTION_DIRECTIONS:
            raise ValueError(f"Invalid direction: {value}")
        return value

    @validator("status")
    def validate_status(cls, value: str) -> str:
        if value not in TRANSACTION_STATUSES:
            raise ValueError(f"Invalid status: {value}")
        return value

    @validator("hours")
    def validate_hours(cls, value: float) -> float:
        if value < 0:
            raise ValueError("hours must be non-negative")
        return value


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
        raise ValueError(exc)


def calculate_balances(leave_year: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = {category: 0.0 for category in TRANSACTION_CATEGORIES}
    starting_balances = leave_year.get("starting_balances", {})
    for category, amount in starting_balances.items():
        totals[category] = float(amount)

    for transaction in leave_year.get("transactions", []):
        category = transaction["category"]
        direction = transaction["direction"]
        hours = float(transaction.get("hours", 0.0))
        if category not in totals:
            totals[category] = 0.0

        if direction in ("earned", "starting_balance", "restored", "worked", "adjusted", "corrected", "reconciled"):
            totals[category] += hours
        elif direction in ("used", "expired", "forfeited", "voided"):
            totals[category] -= hours
        else:
            totals[category] += hours
    return totals


def add_transaction_to_leave_year(leave_year: dict[str, Any], transaction: Transaction) -> None:
    if "transactions" not in leave_year:
        leave_year["transactions"] = []
    leave_year["transactions"].append(transaction.model_dump())
