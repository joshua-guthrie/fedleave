"""Stale source detection, genuine-activity preservation and chain recovery."""

import json

import pytest

import fedleave.cross_year as service
from fedleave.cross_year import (
    apply_creation,
    apply_reconciliation,
    creation_plan,
    reconciliation_plan,
    recover_reconciliation,
    resolve_snapshot,
)
from fedleave.ledger import calculate_balances
from leave_year_support import save, store, tree, tx


def linked(base, last=2027, lot=False):
    source, config = store(
        base,
        balances={"annual": 100, "sick": 600},
        transactions=[
            tx(
                "lot",
                "2026-06-01",
                "travel_comp",
                "earned",
                40,
                expiration_date="2030-06-01",
                expiration_extension_reason="Approved",
            )
        ]
        if lot
        else [],
    )
    for source_year in range(2026, last):
        ledger, preview = creation_plan(base, source_year, source_year + 1)
        apply_creation(base, ledger, preview)
    return source, config


@pytest.mark.parametrize(
    "change",
    ["earned", "used", "void", "hours", "date", "extension", "annual_cap", "credit_cap", "accrual"],
    ids=[f"REC-{i:03}" for i in range(1, 10)],
)
def test_material_source_changes_detected_readonly(tmp_path, change):
    source, config = linked(tmp_path, lot=True)
    if change in {"earned", "used"}:
        source["transactions"].append(tx("revision", "2026-09-01", "annual", change, 8))
    if change == "void":
        source["transactions"][0]["void"] = True
    if change == "hours":
        source["transactions"][0]["hours"] = 24
    if change == "date":
        source["transactions"][0]["date"] = "2026-07-01"
    if change == "extension":
        source["transactions"][0]["expiration_date"] = "2031-01-01"
    if change in {"annual_cap", "credit_cap"}:
        category, key = (
            ("annual", "carryover_limit_hours") if change == "annual_cap" else ("credit", "max_carryover_hours")
        )
        config["rules"][category][key] = 80
        (tmp_path / "config.json").write_text(json.dumps(config))
    if change == "accrual":
        source["annual_leave_accrual_hours"] = 1
    save(tmp_path, 2026, source)
    before = tree(tmp_path)
    snapshot = resolve_snapshot(tmp_path, 2027)
    assert any(w["code"] == "STALE_CARRYOVER" for w in snapshot.warnings)
    if change == "used":
        assert calculate_balances(snapshot, until_date="2027-01-10")["annual"] == 92
    if change == "earned":
        assert calculate_balances(snapshot, until_date="2027-01-10")["annual"] == 108
    assert tree(tmp_path) == before


def test_REC_010_011_012_013_014_preserves_genuine_and_is_idempotent(tmp_path):
    source, _ = linked(tmp_path, lot=True)
    destination = json.loads((tmp_path / "leave_years/2027.json").read_text())
    genuine = tx("genuine", "2027-06-01", "annual", "used", 4, custom={"preserved": 1})
    destination["transactions"].append(genuine)
    destination["custom_top_level"] = {"preserved": True}
    save(tmp_path, 2027, destination)
    source["transactions"].append(tx("late", "2026-12-01", "annual", "used", 8))
    save(tmp_path, 2026, source)
    before = tree(tmp_path)
    changes, preview = reconciliation_plan(tmp_path, 2027)
    assert preview["affected_years"] == [2027]
    assert preview["years"][0]["old_openings"]["annual"] == 100
    assert preview["years"][0]["new_openings"]["annual"] == 92
    assert tree(tmp_path) == before
    result = apply_reconciliation(tmp_path, changes, preview, preview["preview_fingerprint"])
    assert result["action"] == "applied" and len(result["backups"]) == 1
    updated = json.loads((tmp_path / "leave_years/2027.json").read_text())
    assert next(row for row in updated["transactions"] if row["id"] == "genuine") == genuine
    assert updated["custom_top_level"] == {"preserved": True}
    assert calculate_balances(updated, until_date="2027-06-01")["annual"] == 88
    assert tree(tmp_path)["leave_years/2026.json"] == before["leave_years/2026.json"]
    changes2, preview2 = reconciliation_plan(tmp_path, 2027)
    assert changes2 == {} and preview2["affected_years"] == []
    before_repeat = tree(tmp_path)
    assert apply_reconciliation(tmp_path, changes2, preview2)["action"] == "unchanged"
    assert tree(tmp_path) == before_repeat


def test_REC_015_016_full_descendant_chain(tmp_path):
    source, _ = linked(tmp_path, last=2029)
    source["transactions"].append(tx("late", "2026-12-01", "annual", "used", 8))
    save(tmp_path, 2026, source)
    changes, preview = reconciliation_plan(tmp_path, 2027)
    assert preview["affected_years"] == [2027, 2028, 2029]
    assert [preview["years"][i]["new_openings"]["annual"] for i in range(3)] == [92, 92, 92]
    apply_reconciliation(tmp_path, changes, preview)
    assert not resolve_snapshot(tmp_path, 2029).warnings
    assert calculate_balances(resolve_snapshot(tmp_path, 2029), until_date="2029-01-07")["annual"] == 92
    middle = json.loads((tmp_path / "leave_years/2027.json").read_text())
    middle["transactions"].append(tx("middle-change", "2027-06-01", "annual", "used", 4))
    save(tmp_path, 2027, middle)
    assert any(w["code"] == "STALE_CARRYOVER" for w in resolve_snapshot(tmp_path, 2029).warnings)


def test_REC_017_023_source_reduction_conflicts_with_linked_usage(tmp_path):
    source, _ = linked(tmp_path, lot=True)
    target = json.loads((tmp_path / "leave_years/2027.json").read_text())
    lot = next(row for row in target["transactions"] if row.get("source") == "expiration-rollover")
    target["transactions"].append(
        tx("used-carried", "2027-06-01", "travel_comp", "used", 32, earned_transaction_id=lot["id"])
    )
    save(tmp_path, 2027, target)
    source["transactions"][0]["hours"] = 16
    save(tmp_path, 2026, source)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="CONFLICTING_CARRYOVER.*used-carried"):
        reconciliation_plan(tmp_path, 2027)
    assert tree(tmp_path) == before


def test_REC_018_missing_linked_source_is_explicit_error(tmp_path):
    linked(tmp_path)
    (tmp_path / "leave_years/2026.json").unlink()
    with pytest.raises(ValueError, match="MISSING_SOURCE_YEAR"):
        resolve_snapshot(tmp_path, 2027)


def test_REC_019_020_manual_boundary_never_converted(tmp_path):
    source, _ = store(tmp_path, year=2027, start="2027-01-10", balances={"annual": 10})
    store(tmp_path, year=2026, balances={"annual": 999})
    with pytest.raises(ValueError, match="MANUAL_BOUNDARY"):
        reconciliation_plan(tmp_path, 2027)
    target, preview = creation_plan(tmp_path, 2027, 2028)
    assert preview["opening_balances"]["annual"] == 10
    assert target["initialization"]["source_leave_year"] == 2027


def test_REC_024_key_order_does_not_change_fingerprint(tmp_path):
    source, _ = linked(tmp_path)
    (tmp_path / "leave_years/2026.json").write_text(json.dumps(source, sort_keys=True, separators=(",", ":")))
    assert not resolve_snapshot(tmp_path, 2027).warnings


def test_REC_022_failed_chain_apply_rolls_back(tmp_path, monkeypatch):
    source, _ = linked(tmp_path, last=2028)
    source["starting_balances"]["annual"] = 80
    save(tmp_path, 2026, source)
    before = {year: (tmp_path / f"leave_years/{year}.json").read_bytes() for year in (2027, 2028)}
    changes, preview = reconciliation_plan(tmp_path, 2027)
    real_write = service.atomic_write_json
    failed = False

    def injected(path, data, overwrite=True):
        nonlocal failed
        if path.name == "2028.json" and not failed:
            failed = True
            raise OSError("injected disk failure")
        return real_write(path, data, overwrite=overwrite)

    monkeypatch.setattr(service, "atomic_write_json", injected)
    with pytest.raises(ValueError, match="RECONCILIATION_ROLLED_BACK"):
        apply_reconciliation(tmp_path, changes, preview)
    assert {year: json.loads((tmp_path / f"leave_years/{year}.json").read_text()) for year in before} == {
        year: json.loads(data) for year, data in before.items()
    }
    assert not (tmp_path / "carryover-reconciliation.json").exists()
    assert len(list((tmp_path / "backups").glob("*.bak"))) == 2


def test_REC_022_FS_024_interruption_journal_requires_recovery(tmp_path, monkeypatch):
    source, _ = linked(tmp_path, last=2028)
    source["starting_balances"]["annual"] = 80
    save(tmp_path, 2026, source)
    changes, preview = reconciliation_plan(tmp_path, 2027)
    originals = {year: json.loads((tmp_path / f"leave_years/{year}.json").read_text()) for year in changes}
    real_write = service.atomic_write_json

    def interrupted(path, data, overwrite=True):
        if path.name == "2028.json":
            raise KeyboardInterrupt("power loss")
        return real_write(path, data, overwrite=overwrite)

    monkeypatch.setattr(service, "atomic_write_json", interrupted)
    with pytest.raises(KeyboardInterrupt):
        apply_reconciliation(tmp_path, changes, preview)
    assert (tmp_path / "carryover-reconciliation.json").exists()
    with pytest.raises(ValueError, match="RECOVERY_REQUIRED"):
        reconciliation_plan(tmp_path, 2027)
    monkeypatch.setattr(service, "atomic_write_json", real_write)
    result = recover_reconciliation(tmp_path)
    assert result["recovered_years"] == [2027, 2028]
    assert all(
        json.loads((tmp_path / f"leave_years/{year}.json").read_text()) == original
        for year, original in originals.items()
    )
    assert recover_reconciliation(tmp_path)["action"] == "unchanged"


def test_EDGE_023_unlinked_consumption_conflict_is_not_hidden(tmp_path):
    source, _ = linked(tmp_path, lot=True)
    target = json.loads((tmp_path / "leave_years/2027.json").read_text())
    target["transactions"].append(tx("unlinked-use", "2027-06-01", "travel_comp", "used", 32))
    save(tmp_path, 2027, target)
    source["transactions"][0]["hours"] = 16
    save(tmp_path, 2026, source)
    with pytest.raises(ValueError, match="CONFLICTING_CARRYOVER.*unlinked-use"):
        reconciliation_plan(tmp_path, 2027)


def test_REC_021_legacy_unknown_opening_is_reported(tmp_path):
    source, _ = store(tmp_path, balances={"travel_comp": 40})
    target, preview = creation_plan(tmp_path, 2026, 2027)
    assert preview["opening_balances"]["travel_comp"] == 40
    assert preview["lots"] == []
    assert any(row["code"] == "MISSING_LOT_PROVENANCE" for row in preview["warnings"])
    apply_creation(tmp_path, target, preview)
    source["starting_balances"]["travel_comp"] = 32
    save(tmp_path, 2026, source)
    changes, report = reconciliation_plan(tmp_path, 2027)
    # Undated hours can be retained numerically but are disclosed as unresolved;
    # reconciliation never invents an original earning lot or deadline.
    assert report["years"][0]["new_openings"]["travel_comp"] == 32
    assert changes[2027]["transactions"] == []


def test_BAL_019_020_explicit_legacy_opening_repair_is_idempotent(tmp_path):
    source, _ = store(
        tmp_path,
        balances={"annual": 40},
        transactions=[tx("old-opening", "2026-01-11", "annual", "starting_balance", 40)],
    )
    source.pop("initialization")
    save(tmp_path, 2026, source)
    assert calculate_balances(resolve_snapshot(tmp_path, 2026), until_date="2026-01-11")["annual"] == 40
    changes, preview = reconciliation_plan(tmp_path, 2026, repair_openings=True)
    assert changes[2026]["transactions"] == []
    apply_reconciliation(tmp_path, changes, preview)
    fixed = json.loads((tmp_path / "leave_years/2026.json").read_text())
    assert "initialization" not in fixed
    assert fixed["starting_balances"]["annual"] == 40
    changes, preview = reconciliation_plan(tmp_path, 2026, repair_openings=True)
    assert changes == {}


def test_approved_destination_extension_survives_source_reconciliation(tmp_path):
    from typer.testing import CliRunner

    from fedleave.cli import app

    source, _ = linked(tmp_path, lot=True)
    target = json.loads((tmp_path / "leave_years/2027.json").read_text())
    carried = next(row for row in target["transactions"] if row.get("source") == "expiration-rollover")
    extended = CliRunner().invoke(
        app,
        [
            "expiration-extend",
            "--id",
            carried["id"],
            "--new-date",
            "2031-06-01",
            "--reason",
            "Approved deployment",
            "--json",
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert extended.exit_code == 0, extended.output
    source["transactions"][0]["hours"] = 32
    save(tmp_path, 2026, source)
    changes, preview = reconciliation_plan(tmp_path, 2027)
    lot = next(row for row in changes[2027]["transactions"] if row.get("source") == "expiration-rollover")
    assert lot["hours"] == 32 and lot["expiration_date"] == "2031-06-01"
    assert lot["original_expiration_date"] == "2030-06-01"
    assert lot["expiration_extension_reason"] == "Approved deployment"
    apply_reconciliation(tmp_path, changes, preview)
    assert reconciliation_plan(tmp_path, 2027)[0] == {}
