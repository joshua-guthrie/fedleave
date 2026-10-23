"""Boundary arithmetic, policy caps, complete categories and mode separation."""

import json
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.cross_year import apply_creation, creation_plan, derive_carryover
from fedleave.ledger import calculate_balances
from fedleave.payperiods import validate_pay_periods
from leave_year_support import store, tree, tx


@pytest.mark.parametrize(
    "year,start,count,next_start,next_count",
    [
        (2022, "2022-01-02", 26, "2023-01-01", 27),
        (2023, "2023-01-01", 27, "2024-01-14", 26),
        (2024, "2024-01-14", 26, "2025-01-12", 26),
        (2026, "2026-01-11", 26, "2027-01-10", 26),
    ],
    ids=["DATE-008-009-013", "DATE-003-005-012", "DATE-010-011", "DATE-001-002-018"],
)
def test_real_leave_year_boundaries(tmp_path, year, start, count, next_start, next_count):
    source, config = store(tmp_path, year, start, count)
    source["annual_leave_accrual_hours"] = 6
    source["sick_leave_accrual_hours"] = 4
    target, preview = derive_carryover(source, year + 1, config)
    assert target["leave_year_start"] == next_start
    assert target["pay_period_count"] == next_count
    assert preview["opening_balances"]["annual"] == 6 * count
    assert preview["opening_balances"]["sick"] == 4 * count
    periods = target["pay_periods"]
    assert [p["pay_period_number"] for p in periods] == list(range(1, next_count + 1))
    for first, second in zip(periods, periods[1:]):
        assert date.fromisoformat(first["end_date"]) + timedelta(days=1) == date.fromisoformat(second["start_date"])
    assert len([tx for tx in target["transactions"] if tx.get("source") == "auto_accrual"]) == next_count * 2
    assert calculate_balances(target, until_date=next_start)["annual"] == 6 * count


@pytest.mark.parametrize(
    "field",
    ["start", "end", "number", "count", "accrual", "missing"],
    ids=["MOD-014-gap", "MOD-014-overlap", "DATE-006", "DATE-016", "DATE-007", "MOD-015"],
)
def test_invalid_schedule_rejected(tmp_path, field):
    source, config = store(tmp_path)
    if field == "start":
        source["pay_periods"][1]["start_date"] = "2026-01-26"
    if field == "end":
        source["leave_year_end"] = "2027-01-08"
    if field == "number":
        source["pay_periods"][1]["pay_period_number"] = 1
    if field == "count":
        source["pay_period_count"] = 27
    if field == "accrual":
        source["pay_periods"][0]["accrual_date"] = "2026-01-25"
    if field == "missing":
        source["pay_periods"] = []
    with pytest.raises(ValueError):
        derive_carryover(source, 2027, config)


@pytest.mark.parametrize("start", ["2027-01-09", "2027-01-11"], ids=["MOD-013", "MOD-012"])
def test_mismatched_target_start(tmp_path, start):
    source, config = store(tmp_path)
    with pytest.raises(ValueError, match="SOURCE_NOT_CONTIGUOUS"):
        derive_carryover(source, 2027, config, start=start)


def test_DATE_008_015_agency_december_schedule(tmp_path):
    source, config = store(tmp_path, 2026, "2025-12-28", 26)
    target, _ = derive_carryover(source, 2027, config, pay_periods=26)
    assert target["leave_year_start"] == "2026-12-27"
    assert target["leave_year"] == 2027
    validate_pay_periods(target)


@pytest.mark.parametrize(
    "category,amount,rule,expected",
    [
        ("annual", 0, {}, 0),
        ("annual", 100, {}, 100),
        ("annual", 240, {}, 240),
        ("annual", 280, {}, 240),
        ("annual", 280, {"carryover_limit_hours": 80}, 80),
        ("annual", 400, {"carryover_limit_hours": 360}, 360),
        ("sick", 600, {}, 600),
        ("annual", -8, {}, -8),
        ("credit", 24, {}, 24),
        ("credit", 30, {}, 24),
        ("credit", 12.25, {}, 12.25),
        ("religious_comp", 16, {"carryover_mode": "balance_carryover"}, 16),
    ],
    ids=[
        "BAL-001",
        "BAL-002",
        "BAL-003",
        "BAL-004",
        "BAL-005",
        "BAL-006",
        "BAL-007",
        "BAL-008",
        "BAL-009",
        "BAL-010",
        "BAL-011",
        "BAL-013",
    ],
)
def test_category_balances_and_caps(tmp_path, category, amount, rule, expected):
    source, config = store(tmp_path, balances={category: amount}, rules={category: rule})
    target, result = derive_carryover(source, 2027, config)
    assert result["opening_balances"][category] == expected
    assert calculate_balances(target, until_date="2027-01-10")[category] == expected
    assert sum(row["hours"] for row in result["adjustments"] if row["category"] == category) == amount - expected
    assert source["starting_balances"][category] == amount


@pytest.mark.parametrize("category", ["religious_comp", "unrecognized"], ids=["BAL-013-unsupported", "BAL-018"])
def test_unknown_policy_blocks_nonzero(tmp_path, category):
    source, config = store(tmp_path, balances={category: 8})
    with pytest.raises(ValueError, match="UNSUPPORTED_CATEGORY_POLICY"):
        derive_carryover(source, 2027, config)


@pytest.mark.parametrize(
    "category",
    ["overtime", "admin", "lwop", "military", "court", "excused", "holiday", "flex", "other"],
    ids=lambda cat: "BAL-017-" + cat,
)
def test_activity_not_credited(tmp_path, category):
    source, config = store(tmp_path, transactions=[tx("activity", "2026-06-01", category, "used", 8)])
    target, result = derive_carryover(source, 2027, config)
    assert result["categories"][category]["opening"] == 0
    assert calculate_balances(target, until_date="2027-01-10")[category] == 0
    assert source["transactions"][0]["hours"] == 8


@pytest.mark.parametrize(
    "flag",
    [
        "annual-start",
        "sick-start",
        "comp-start",
        "credit-start",
        "travel-comp-start",
        "time-off-award-start",
        "religious-comp-start",
        "restored-annual-start",
        "annual-accrual",
    ],
    ids=lambda f: "MOD-003-004-CLI-021-" + f,
)
@pytest.mark.parametrize("value", ["0", "10"])
def test_mixed_manual_flags_rejected(tmp_path, flag, value):
    store(tmp_path)
    before = tree(tmp_path)
    result = CliRunner().invoke(
        app,
        ["init", "--year", "2027", "--from-year", "2026", "--" + flag, value, "--json", "--data-dir", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["code"] == "MIXED_INITIALIZATION_MODES"
    assert tree(tmp_path) == before


def test_MOD_005_manual_and_carryover_rejected(tmp_path):
    store(tmp_path)
    result = CliRunner().invoke(
        app, ["init", "--year", "2027", "--from-year", "2026", "--manual", "--json", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code != 0 and "MIXED_INITIALIZATION_MODES" in result.output


@pytest.mark.parametrize(
    "source_year,target_year", [(2026, 2026), (2026, 2025), (2026, 2028)], ids=["MOD-008", "MOD-009", "MOD-010"]
)
def test_nonadjacent_year_identifiers(tmp_path, source_year, target_year):
    source, config = store(tmp_path)
    with pytest.raises(ValueError, match="SOURCE_NOT_CONTIGUOUS"):
        derive_carryover(source, target_year, config)


def test_MOD_020_CLI_006_018_preview_apply_alias_and_source_unchanged(tmp_path):
    store(
        tmp_path,
        balances={"annual": 280, "credit": 30, "sick": 600},
        transactions=[tx("lot", "2026-06-01", "time_off_award", "earned", 8)],
    )
    before = tree(tmp_path)
    target, first = creation_plan(tmp_path, 2026, 2027)
    target2, second = creation_plan(tmp_path, 2026, 2027)
    assert target == target2 and first == second
    assert tree(tmp_path) == before
    output = apply_creation(tmp_path, target, first, first["preview_fingerprint"])
    assert output["opening_balances"] == first["opening_balances"]
    assert tree(tmp_path)["leave_years/2026.json"] == before["leave_years/2026.json"]
    assert (
        json.loads((tmp_path / "leave_years/2027.json").read_text())["initialization"]["source_fingerprint"]
        == first["source_fingerprint"]
    )
    with pytest.raises(ValueError, match="DESTINATION_EXISTS"):
        creation_plan(tmp_path, 2026, 2027)
