"""Per-origin conservation, inclusive expiration and chronological lot usage."""

from copy import deepcopy
from datetime import date

import pytest

from fedleave.cross_year import apply_creation, creation_plan, derive_carryover, resolve_snapshot
from fedleave.expirations import expiration_report, synchronize_expirations
from fedleave.ledger import calculate_balances
from leave_year_support import save, store, tree, tx


@pytest.mark.parametrize(
    "category,rule",
    [
        ("comp", {}),
        ("travel_comp", {}),
        ("restored_annual", {}),
        ("time_off_award", {"expires": True, "expiration_days_after_earned": 1200}),
        ("time_off_award", {"expires": False}),
    ],
    ids=["LOT-031-comp", "LOT-031-travel", "BAL-014-restored", "LOT-031-award", "BAL-012-nonexpiring"],
)
def test_partial_lot_carries_provenance_and_extension(tmp_path, category, rule):
    source, config = store(
        tmp_path,
        rules={category: rule},
        transactions=[
            tx(
                "original",
                "2026-06-01",
                category,
                "restored" if category == "restored_annual" else "earned",
                40,
                expiration_date="2029-06-01",
                expiration_extension_reason="Approved agency extension",
                expiration_extended_at="2026-12-01T00:00:00",
                custom_additive={"kept": True},
            ),
            tx("use", "2026-08-01", category, "used", 16),
        ],
    )
    before = deepcopy(source)
    target, result = derive_carryover(source, 2027, config)
    carried = result["lots"][0]
    assert carried["hours"] == 24
    assert carried["origin_leave_year"] == 2026 and carried["origin_transaction_id"] == "original"
    assert carried["origin_earned_hours"] == 40
    assert carried["original_earned_date"] == "2026-06-01"
    assert carried["expiration_date"] == "2029-06-01"
    assert carried["expiration_extension_reason"] == "Approved agency extension"
    assert carried["custom_additive"] == {"kept": True}
    assert calculate_balances(target, until_date="2027-01-10")[category] == 24
    assert source == before


@pytest.mark.parametrize(
    "earned_status,void",
    [("denied", False), ("cancelled", False), ("approved", True)],
    ids=["LOT-019-denied", "LOT-019-cancelled", "LOT-018"],
)
def test_inactive_lot_not_carried(tmp_path, earned_status, void):
    source, config = store(
        tmp_path, transactions=[tx("lot", "2026-06-01", "travel_comp", "earned", 40, status=earned_status, void=void)]
    )
    _, result = derive_carryover(source, 2027, config)
    assert result["lots"] == []
    assert result["opening_balances"]["travel_comp"] == 0


@pytest.mark.parametrize(
    "used,deadline,expected",
    [(40, "2028-01-01", 0), (16, "2028-01-01", 24), (0, "2027-01-09", 0), (0, "2027-01-10", 40), (0, "2027-01-11", 40)],
    ids=["LOT-005", "LOT-006", "LOT-008-EDGE-011", "LOT-009-EDGE-012", "LOT-007"],
)
def test_lot_boundary_and_exhaustion(tmp_path, used, deadline, expected):
    transactions = [tx("lot", "2026-06-01", "comp", "earned", 40, expiration_date=deadline)]
    if used:
        transactions.append(tx("use", "2026-08-01", "comp", "used", used))
    source, config = store(tmp_path, transactions=transactions)
    _, result = derive_carryover(source, 2027, config)
    assert sum(lot["hours"] for lot in result["lots"]) == expected
    assert result["opening_balances"]["comp"] == expected


@pytest.mark.parametrize(
    "use_date,expected",
    [("2026-05-31", None), ("2026-06-01", "lot"), ("2026-07-01", "lot"), ("2026-07-02", None)],
    ids=["LOT-027", "LOT-001", "LOT-021", "LOT-022-028"],
)
def test_usage_eligibility_dates(tmp_path, use_date, expected):
    source, config = store(
        tmp_path,
        transactions=[
            tx("lot", "2026-06-01", "comp", "earned", 8, expiration_date="2026-07-01"),
            tx("use", use_date, "comp", "used", 4),
        ],
    )
    state = synchronize_expirations(source, config, as_of=date(2026, 8, 1))
    use = next(row for row in source["transactions"] if row["id"] == "use")
    assert use.get("earned_transaction_id") == expected
    assert state["remaining"]["lot"] == (4 if expected else 8)


@pytest.mark.parametrize(
    "action,expected", [("warn", 8), ("forfeit", 0), ("expire", 0)], ids=["LOT-034-warn", "LOT-017", "LOT-033"]
)
def test_inclusive_deadline_and_disposition(tmp_path, action, expected):
    source, config = store(
        tmp_path,
        transactions=[tx("lot", "2026-06-01", "comp", "earned", 8, expiration_date="2026-07-01")],
        rules={"comp": {"expiration_action": action}},
    )
    before = expiration_report(deepcopy(source), config, as_of=date(2026, 7, 1))
    assert before["lots"][0]["remaining_hours"] == 8 and before["lots"][0]["status"] == "active"
    after = expiration_report(source, config, as_of=date(2026, 7, 2))
    assert after["lots"][0]["remaining_hours"] == expected
    assert after["lots"][0]["last_eligible_usage_date"] == "2026-07-01"
    assert after["lots"][0]["expiration_effective_date"] == "2026-07-02"
    generated = [row for row in source["transactions"] if row.get("source") == "expiration-engine"]
    assert len(generated) == (0 if action == "warn" else 1)
    if generated:
        assert generated[0]["date"] == "2026-07-02"
    assert expiration_report(source, config, as_of=date(2026, 7, 2))["changed"] is False
    historical = expiration_report(source, config, as_of=date(2026, 7, 1))
    assert historical["lots"][0]["remaining_hours"] == 8


def test_LOT_002_003_024_025_026_multiple_lots_allocate_once(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx("b", "2026-06-01", "comp", "earned", 5, expiration_date="2028-01-01"),
            tx("a", "2026-06-01", "comp", "earned", 4, expiration_date="2028-01-01"),
            tx("use", "2026-07-01", "comp", "used", 6),
        ],
    )
    state = synchronize_expirations(source, config, as_of=date(2026, 8, 1))
    assert state["remaining"] == {"a": 0, "b": 3}
    uses = [row for row in source["transactions"] if row["direction"] == "used"]
    assert [(row["earned_transaction_id"], row["hours"]) for row in uses] == [("a", 4), ("b", 2)]
    assert synchronize_expirations(source, config, as_of=date(2026, 8, 1))["changed"] is False
    assert sum(row["hours"] for row in uses) == 6


def test_LOT_010_011_012_023_035_three_year_origin_conservation(tmp_path):
    source, _ = store(
        tmp_path,
        transactions=[
            tx(
                "original",
                "2026-06-01",
                "travel_comp",
                "earned",
                40,
                expiration_date="2030-06-01",
                expiration_extension_reason="Approved",
            ),
            tx("use-2026", "2026-08-01", "travel_comp", "used", 16),
        ],
    )
    initial = tree(tmp_path)["leave_years/2026.json"]
    for source_year, expected, used in [(2026, 24, 8), (2027, 16, 4), (2028, 12, 0)]:
        target, preview = creation_plan(tmp_path, source_year, source_year + 1)
        assert len(preview["lots"]) == 1
        lot = preview["lots"][0]
        assert lot["origin_leave_year"] == 2026 and lot["origin_transaction_id"] == "original"
        assert lot["origin_earned_hours"] == 40 and lot["hours"] == expected
        assert lot["expiration_date"] == "2030-06-01"
        apply_creation(tmp_path, target, preview)
        if used:
            target["transactions"].append(
                tx(f"use-{source_year + 1}", f"{source_year + 1}-06-01", "travel_comp", "used", used)
            )
            save(tmp_path, source_year + 1, target)
    assert calculate_balances(resolve_snapshot(tmp_path, 2029), until_date="2029-06-01")["travel_comp"] == 12
    assert tree(tmp_path)["leave_years/2026.json"] == initial
    historical = expiration_report(resolve_snapshot(tmp_path, 2026), {}, as_of=date(2026, 7, 1))
    assert historical["lots"][0]["remaining_hours"] == 40


def test_LOT_020_historical_future_usage_does_not_consume(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[tx("lot", "2026-02-01", "comp", "earned", 8), tx("use", "2026-12-01", "comp", "used", 6)],
    )
    report = expiration_report(source, config, as_of=date(2026, 3, 1))
    assert report["lots"][0]["remaining_hours"] == 8


def test_LOT_030_031_restored_real_leave_year_deadline(tmp_path):
    source, config = store(
        tmp_path,
        year=2022,
        start="2022-01-02",
        count=26,
        transactions=[tx("restored", "2022-06-01", "restored_annual", "restored", 40)],
    )
    report = expiration_report(source, config, as_of=date(2022, 12, 1))
    assert report["lots"][0]["expiration_date"] == "2025-01-11"


def test_LOT_004_034_distinct_origins_with_same_local_id(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx(
                "a",
                "2026-06-01",
                "comp",
                "earned",
                4,
                expiration_date="2029-01-01",
                origin_leave_year=2025,
                origin_transaction_id="same-local-id",
            ),
            tx(
                "b",
                "2026-07-01",
                "comp",
                "earned",
                8,
                expiration_date="2029-01-01",
                origin_leave_year=2026,
                origin_transaction_id="same-local-id",
            ),
        ],
    )
    target, result = derive_carryover(source, 2027, config)
    assert len({lot["id"] for lot in result["lots"]}) == 2
    assert {(lot["origin_leave_year"], lot["origin_transaction_id"]) for lot in result["lots"]} == {
        (2025, "same-local-id"),
        (2026, "same-local-id"),
    }
    assert calculate_balances(target, until_date="2027-01-10")["comp"] == 12


def test_LOT_015_016_036_invalid_expiration_policy_is_explicit(tmp_path):
    source, config = store(
        tmp_path,
        rules={"time_off_award": {"expires": True}},
        transactions=[tx("award", "2026-06-01", "time_off_award", "earned", 8)],
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_CATEGORY_POLICY"):
        derive_carryover(source, 2027, config)
    source["transactions"][0]["expiration_date"] = "2029-01-01"
    source["transactions"][0]["expiration_extension_reason"] = "Unauthorized"
    config["rules"]["time_off_award"]["allow_extension"] = False
    with pytest.raises(ValueError, match="EXPIRATION_OUTSIDE_POLICY"):
        derive_carryover(source, 2027, config)


def test_LOT_017_partial_disposals_are_not_recreated(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx("lot", "2026-06-01", "comp", "earned", 40, expiration_date="2028-01-01"),
            tx("payout", "2026-07-01", "comp", "paid_out", 8, earned_transaction_id="lot"),
            tx("forfeit", "2026-08-01", "comp", "forfeited", 4, earned_transaction_id="lot"),
            tx("expired", "2026-09-01", "comp", "expired", 4, earned_transaction_id="lot"),
            tx("use", "2026-10-01", "comp", "used", 8, earned_transaction_id="lot"),
        ],
    )
    target, result = derive_carryover(source, 2027, config)
    lot = result["lots"][0]
    assert lot["hours"] == 16
    assert lot["origin_dispositions"] == {"paid_out": 8, "forfeited": 4, "expired": 4, "used": 8}
    assert lot["origin_earned_hours"] == 40
    assert not [row for row in target["transactions"] if row["direction"] in {"paid_out", "expired", "forfeited"}]
    assert sum(lot["origin_dispositions"].values()) + lot["hours"] == 40


def test_LOT_030_EDGE_015_016_expiry_number_after_27_period_year(tmp_path):
    source, config = store(
        tmp_path,
        year=2023,
        start="2023-01-01",
        count=27,
        transactions=[tx("late-lot", "2024-01-01", "travel_comp", "earned", 8)],
    )
    report = expiration_report(source, config, as_of=date(2024, 1, 13))
    lot = report["lots"][0]
    assert lot["last_eligible_usage_date"] == "2025-01-11"
    assert lot["expiration_pay_period"] == 26
    target, result = derive_carryover(source, 2024, config)
    assert target["leave_year_start"] == "2024-01-14"
    assert result["lots"][0]["expiration_date"] == "2025-01-11"


def test_LOT_024_reallocation_is_stable_after_earlier_lot_changes(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx("first", "2026-06-01", "comp", "earned", 4, expiration_date="2028-01-01"),
            tx("second", "2026-06-02", "comp", "earned", 8, expiration_date="2028-01-01"),
            tx("use", "2026-07-01", "comp", "used", 6),
        ],
    )
    synchronize_expirations(source, config, as_of=date(2026, 8, 1))
    source["transactions"][0]["hours"] = 8
    state = synchronize_expirations(source, config, as_of=date(2026, 8, 1))
    assert state["remaining"] == {"first": 2, "second": 8}
    assert sum(row["hours"] for row in source["transactions"] if row["direction"] == "used") == 6
    assert synchronize_expirations(source, config, as_of=date(2026, 8, 1))["changed"] is False


def test_INT_014_legacy_carried_origin_stays_stable_with_unknown_grant(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx(
                "legacy-copy",
                "2026-01-11",
                "time_off_award",
                "earned",
                8,
                source="expiration-rollover",
                carried_from_transaction_id="old-original",
                original_earned_date="2025-06-01",
            )
        ],
    )
    target, preview = derive_carryover(source, 2027, config)
    lot = preview["lots"][0]
    assert lot["origin_transaction_id"] == "old-original"
    assert lot["origin_leave_year"] is None
    assert lot["origin_earned_hours"] is None
    assert lot["origin_amount_known"] is False
    assert any(w["code"] == "MISSING_LOT_PROVENANCE" for w in preview["warnings"])
    final, again = derive_carryover(target, 2028, config)
    assert again["lots"][0]["origin_key"] == lot["origin_key"]
    assert again["lots"][0]["original_earned_date"] == "2025-06-01"
    assert calculate_balances(final, until_date="2028-01-09")["time_off_award"] == 8


def test_DATE_017_EDGE_013_leap_day_origin_and_deadline(tmp_path):
    source, config = store(
        tmp_path,
        year=2024,
        start="2024-01-14",
        transactions=[tx("leap-lot", "2024-02-29", "comp", "earned", 8, expiration_date="2028-02-29")],
    )
    target, preview = derive_carryover(source, 2025, config)
    assert preview["lots"][0]["original_earned_date"] == "2024-02-29"
    assert preview["lots"][0]["expiration_date"] == "2028-02-29"
    assert calculate_balances(target, until_date="2025-01-12")["comp"] == 8


def test_EDGE_022_mixed_expired_and_live_lots(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx("expired", "2026-02-01", "comp", "earned", 40, expiration_date="2026-10-01"),
            tx("live", "2026-06-01", "comp", "earned", 16, expiration_date="2028-01-01"),
        ],
    )
    _, result = derive_carryover(source, 2027, config)
    assert result["opening_balances"]["comp"] == 16
    assert result["categories"]["comp"]["source_balance"] == 16
    assert result["categories"]["comp"]["retained_expired_hours"] == 40
    assert len(result["lots"]) == 1 and result["lots"][0]["origin_transaction_id"] == "live"
