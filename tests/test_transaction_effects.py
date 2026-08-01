from __future__ import annotations

import pytest

from fedleave.ledger import (
    TRANSACTION_DIRECTIONS,
    Transaction,
    calculate_balances,
    calculate_daily_activity,
    calculate_pay_period_activity,
)
from fedleave.transaction_effects import (
    DECREASE_DIRECTIONS,
    INCREASE_DIRECTIONS,
    signed_balance_effect,
)


def _transaction(
    direction: str,
    *,
    status: str = "approved",
    hours: float = 2.0,
) -> dict[str, object]:
    return {
        "id": f"tx-{direction}-{status}",
        "date": "2026-01-12",
        "category": "annual",
        "direction": direction,
        "hours": hours,
        "status": status,
        "source": "test",
    }


def _leave_year(transactions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "starting_balances": {"annual": 10.0},
        "transactions": transactions,
        "pay_periods": [
            {
                "pay_period": 1,
                "start_date": "2026-01-11",
                "end_date": "2026-01-24",
            }
        ],
    }


def test_every_supported_direction_has_one_effect_definition() -> None:
    assert set(TRANSACTION_DIRECTIONS) == INCREASE_DIRECTIONS | DECREASE_DIRECTIONS


@pytest.mark.parametrize("direction", sorted(INCREASE_DIRECTIONS))
def test_every_increase_direction_has_an_explicit_positive_effect(direction: str) -> None:
    assert signed_balance_effect(_transaction(direction)) == 2.0


@pytest.mark.parametrize("direction", sorted(DECREASE_DIRECTIONS))
def test_every_decrease_direction_has_an_explicit_negative_effect(direction: str) -> None:
    assert signed_balance_effect(_transaction(direction)) == -2.0


@pytest.mark.parametrize("status", ["denied", "cancelled"])
def test_ineffective_statuses_are_excluded_from_all_activity(status: str) -> None:
    leave_year = _leave_year(
        [
            _transaction("earned", status=status),
            _transaction("used", status=status),
            _transaction("worked", status=status),
        ]
    )

    assert calculate_balances(leave_year)["annual"] == 10.0
    assert calculate_daily_activity(leave_year, "2026-01-12") == {
        "earned": {},
        "used": {},
        "net": {},
    }
    activity = calculate_pay_period_activity(leave_year, "2026-01-12")
    assert activity["earned"] == {}
    assert activity["used"] == {}
    assert activity["worked"] == {}
    assert activity["net"] == {}


def test_void_transaction_is_excluded_even_with_an_effective_status() -> None:
    transaction = _transaction("earned")
    transaction["void"] = True

    assert signed_balance_effect(transaction) == 0.0
    assert calculate_balances(_leave_year([transaction]))["annual"] == 10.0


def test_unknown_direction_fails_closed_instead_of_increasing_balance() -> None:
    transaction = _transaction("future_direction")

    with pytest.raises(ValueError, match="Unsupported transaction direction"):
        signed_balance_effect(transaction)
    with pytest.raises(ValueError, match="Unsupported transaction direction"):
        calculate_balances(_leave_year([transaction]))


def test_unknown_status_fails_closed_instead_of_affecting_balance() -> None:
    transaction = _transaction("earned", status="future_status")

    with pytest.raises(ValueError, match="Unsupported transaction status"):
        calculate_balances(_leave_year([transaction]))


def test_negative_raw_hours_fail_closed() -> None:
    transaction = _transaction("used", hours=-2.0)

    with pytest.raises(ValueError, match="must not be negative"):
        calculate_balances(_leave_year([transaction]))


@pytest.mark.parametrize("hours", [float("nan"), float("inf"), float("-inf")])
def test_transaction_model_rejects_nonfinite_hours(hours: float) -> None:
    with pytest.raises(ValueError, match="finite number"):
        Transaction(
            id="20260112-001",
            date="2026-01-12",
            category="annual",
            direction="earned",
            hours=hours,
        )
