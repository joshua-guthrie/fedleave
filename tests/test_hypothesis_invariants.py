from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings, strategies as st

from fedleave.cli_helpers import normalize_iso_date
from fedleave.ledger import generate_transaction_id
from fedleave.payperiods import generate_pay_periods


@given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
@settings(max_examples=50)
def test_normalize_iso_date_is_idempotent(day: date) -> None:
    compact = f"{day.year}-{day.month}-{day.day}"
    normalized = normalize_iso_date(compact)

    assert normalized == day.isoformat()
    assert normalize_iso_date(normalized) == normalized


@given(
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    st.integers(min_value=1, max_value=25),
)
@settings(max_examples=50)
def test_generated_transaction_ids_are_unique_for_a_day(day: date, count: int) -> None:
    existing: list[str] = []
    generated: list[str] = []

    for _ in range(count):
        transaction_id = generate_transaction_id(day.isoformat(), existing)
        generated.append(transaction_id)
        existing.append(transaction_id)

    assert len(generated) == len(set(generated))
    assert generated[0].endswith("-001")


@given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
@settings(max_examples=25)
def test_generated_pay_periods_are_contiguous(day: date) -> None:
    periods = generate_pay_periods(day, 5)

    for previous, current in zip(periods, periods[1:]):
        previous_end = date.fromisoformat(previous["end_date"])
        current_start = date.fromisoformat(current["start_date"])
        assert previous_end + timedelta(days=1) == current_start
