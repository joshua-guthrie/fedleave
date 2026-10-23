"""Independent reference equations and metamorphic cross-year invariants."""

import json
from copy import deepcopy
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fedleave.config import Config
from fedleave.cross_year import derive_carryover, fingerprint, manual_ledger
from fedleave.ledger import calculate_balances
from leave_year_support import tx


def source_for(year=2026, annual=0, transactions=None):
    start = date(year, 1, 1)
    start += timedelta(days=(6 - start.weekday()) % 7)
    config = Config().model_dump()
    config["defaults"]["sick_leave_accrual_hours"] = 0
    source = manual_ledger(year, start.isoformat(), 0, {"annual": annual}, config=config)
    source["transactions"].extend(transactions or [])
    return source, config


@given(st.integers(2000, 2090))
def test_PROP_001_020_valid_year_intervals(year):
    source, config = source_for(year)
    target, result = derive_carryover(source, year + 1, config)
    assert date.fromisoformat(source["leave_year_end"]) + timedelta(days=1) == date.fromisoformat(
        target["leave_year_start"]
    )
    assert (
        date.fromisoformat(target["leave_year_end"]) - date.fromisoformat(target["leave_year_start"])
    ).days + 1 == 14 * target["pay_period_count"]
    invalid = deepcopy(source)
    invalid["pay_periods"][0]["start_date"] = "bad"
    with pytest.raises(ValueError):
        derive_carryover(invalid, year + 1, config)


@given(st.integers(0, 2000), st.integers(0, 1000))
def test_PROP_002_003_013_014_opening_conservation(quarters, used_quarters):
    annual = quarters / 4
    used = min(quarters, used_quarters) / 4
    source, config = source_for(annual=annual, transactions=[tx("use", "2026-06-01", "annual", "used", used)])
    target, result = derive_carryover(source, 2027, config)
    expected = min(annual - used, 240)
    assert calculate_balances(target, until_date=target["leave_year_start"])["annual"] == expected
    assert expected + sum(row["hours"] for row in result["adjustments"] if row["category"] == "annual") == annual - used
    target["transactions"].append(
        tx("extra-mirror", target["leave_year_start"], "annual", "starting_balance", expected)
    )
    assert calculate_balances(target, until_date=target["leave_year_start"])["annual"] == expected


@given(st.integers(1, 640), st.integers(0, 640), st.integers(0, 640))
def test_PROP_004_005_017_lot_conservation_across_chain(quarters, before_quarters, after_quarters):
    original = quarters / 4
    before = min(quarters, before_quarters) / 4
    after = min(quarters - int(before * 4), after_quarters) / 4
    source, config = source_for(
        transactions=[
            tx("lot", "2026-06-01", "time_off_award", "earned", original),
            tx("before", "2026-08-01", "time_off_award", "used", before),
        ]
    )
    target, preview = derive_carryover(source, 2027, config)
    assert preview["opening_balances"]["time_off_award"] == original - before
    target["transactions"].append(tx("after", "2027-06-01", "time_off_award", "used", after))
    final, result = derive_carryover(target, 2028, config)
    remaining = result["opening_balances"]["time_off_award"]
    assert remaining >= 0
    assert original == before + after + remaining
    for lot in result["lots"]:
        assert lot["origin_transaction_id"] == "lot" and lot["origin_earned_hours"] == original
    assert calculate_balances(final, until_date=final["leave_year_start"])["time_off_award"] == remaining


@given(st.permutations((0, 1, 2)))
def test_PROP_006_007_iteration_and_key_order_independent(order):
    transactions = [
        tx("b", "2026-06-01", "comp", "earned", 8, expiration_date="2028-01-01"),
        tx("a", "2026-06-01", "comp", "earned", 4, expiration_date="2028-01-01"),
        tx("use", "2026-08-01", "comp", "used", 6),
    ]
    first, config = source_for(transactions=transactions)
    second = json.loads(json.dumps(first, sort_keys=True))
    second["transactions"] = [second["transactions"][index] for index in order]
    assert fingerprint(first) == fingerprint(second)
    assert derive_carryover(first, 2027, config) == derive_carryover(second, 2027, config)


@given(st.integers(-10, 10), st.integers(0, 10))
def test_PROP_015_016_expiration_monotonic(offset, later_days):
    boundary = date(2027, 1, 10)
    deadline = boundary + timedelta(days=offset)
    source, config = source_for(
        transactions=[tx("lot", "2026-06-01", "comp", "earned", 8, expiration_date=deadline.isoformat())]
    )
    _, first = derive_carryover(source, 2027, config)
    source["transactions"][0]["expiration_date"] = (deadline + timedelta(days=later_days)).isoformat()
    _, second = derive_carryover(source, 2027, config)
    assert first["opening_balances"]["comp"] <= second["opening_balances"]["comp"]
