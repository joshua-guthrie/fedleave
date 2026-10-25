"""Serialized CLI contracts, report parity, export/import and preview tokens."""

import json
import os
import subprocess
import sys
from datetime import date

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.cross_year import apply_creation, creation_plan, resolve_snapshot
from fedleave.ledger import calculate_balances, calculate_daily_activity
from leave_year_support import save, store, tree, tx


def call(base, *arguments, ok=True):
    result = CliRunner().invoke(app, [*arguments, "--json", "--data-dir", str(base)])
    assert (result.exit_code == 0) == ok, (result.output, result.exception)
    return json.loads(result.output)


def test_CLI_001_002_003_004_005_006_019_full_round_trip(tmp_path):
    source, _ = store(
        tmp_path,
        balances={"annual": 280, "sick": 600, "credit": 30},
        transactions=[
            tx("lot", "2026-06-01", "travel_comp", "earned", 40, expiration_date="2027-09-01"),
            tx("used", "2026-07-01", "travel_comp", "used", 16),
        ],
    )
    before = tree(tmp_path)
    preview = call(tmp_path, "init", "--year", "2027", "--from-year", "2026", "--preview")
    alias = call(tmp_path, "rollover", "--from-year", "2026", "--to-year", "2027", "--preview")
    assert alias == preview
    assert preview["opening_balances"] == {
        "annual": 240,
        "sick": 600,
        "credit": 24,
        "comp": 0,
        "travel_comp": 24,
        "time_off_award": 0,
        "restored_annual": 0,
        "ppl": 0,
    }
    assert preview["source_start"] == "2026-01-11" and preview["source_end"] == "2027-01-09"
    assert [(row["category"], row["hours"]) for row in preview["adjustments"]] == [("annual", 40), ("credit", 6)]
    assert preview["lots"][0]["origin_transaction_id"] == "lot"
    assert preview["lots"][0]["expiration_date"] == "2027-09-01"
    assert tree(tmp_path) == before
    applied = call(
        tmp_path,
        "init",
        "--year",
        "2027",
        "--from-year",
        "2026",
        "--expected-fingerprint",
        preview["preview_fingerprint"],
    )
    assert applied["action"] == "applied" and applied["created_file"].endswith("2027.json")
    for key in ("opening_balances", "categories", "adjustments", "lots", "source_fingerprint", "preview_fingerprint"):
        assert applied[key] == preview[key]
    balance = call(tmp_path, "balance", "--year", "2027", "--as-of", "2027-01-10")
    assert {category: balance["balances"][category] for category in preview["opening_balances"]} == preview[
        "opening_balances"
    ]
    years = call(tmp_path, "years")["years"]
    assert [record["leave_year"] for record in years] == [2026, 2027]
    assert tree(tmp_path)["leave_years/2026.json"] == before["leave_years/2026.json"]


def test_INT_008_openings_are_not_new_earnings(tmp_path):
    store(tmp_path, balances={"annual": 100}, transactions=[tx("lot", "2026-06-01", "time_off_award", "earned", 8)])
    target, preview = creation_plan(tmp_path, 2026, 2027)
    assert calculate_daily_activity(target, "2027-01-10")["earned"] == {}
    apply_creation(tmp_path, target, preview)
    activity = call(tmp_path, "activity", "--year", "2027", "--date", "2027-01-10")
    assert activity["activity"]["earned"] == {}


def test_INT_004_005_boundary_transactions_are_owned_once(tmp_path):
    store(tmp_path, balances={"annual": 100}, transactions=[tx("last-day", "2027-01-09", "annual", "used", 8)])
    call(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    call(tmp_path, "add", "--date", "2027-01-10", "--category", "annual", "--used", "4")
    result = call(tmp_path, "balance", "--year", "2027", "--as-of", "2027-01-10")
    assert result["balances"]["annual"] == 88
    assert call(tmp_path, "balance", "--year", "2026", "--as-of", "leave-year-end")["balances"]["annual"] == 92


def test_INT_011_export_import_preserves_lineage_and_extensions(tmp_path):
    base, imported = tmp_path / "source", tmp_path / "imported"
    store(
        base,
        transactions=[
            tx(
                "origin",
                "2026-06-01",
                "travel_comp",
                "earned",
                40,
                expiration_date="2029-01-01",
                expiration_extension_reason="Approved",
                expiration_extended_at="2026-12-01T00:00:00",
            )
        ],
    )
    call(base, "init", "--from-year", "2026", "--year", "2027")
    archive = tmp_path / "portable.json"
    exported = CliRunner().invoke(app, ["export-data", "--output", str(archive), "--data-dir", str(base)])
    assert exported.exit_code == 0, exported.output
    restored = CliRunner().invoke(app, ["import-data", "--input", str(archive), "--data-dir", str(imported)])
    assert restored.exit_code == 0, restored.output
    for year in (2026, 2027):
        assert json.loads((base / f"leave_years/{year}.json").read_text()) == json.loads(
            (imported / f"leave_years/{year}.json").read_text()
        )
    assert calculate_balances(resolve_snapshot(imported, 2027), until_date="2027-01-10")["travel_comp"] == 40


def test_CLI_017_INT_007_expiration_report_uses_original_identity(tmp_path):
    store(
        tmp_path, transactions=[tx("origin", "2026-06-01", "travel_comp", "earned", 40, expiration_date="2029-01-01")]
    )
    call(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    # Report takes an injectable as-of date through the domain; CLI default is
    # today, so source history is independently checked without changing clocks.
    from fedleave.expirations import expiration_report

    snapshot = resolve_snapshot(tmp_path, 2027)
    report = expiration_report(snapshot, snapshot.config, as_of=date(2027, 6, 1))
    assert report["lots"][0]["origin_leave_year"] == 2026
    assert report["lots"][0]["origin_transaction_id"] == "origin"
    assert report["lots"][0]["earned_date"] == "2026-06-01"


def test_CLI_016_REC_010_read_stale_recomputes_but_does_not_persist(tmp_path):
    source, _ = store(tmp_path, balances={"annual": 100})
    call(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    source["transactions"].append(tx("late", "2026-12-01", "annual", "used", 8))
    save(tmp_path, 2026, source)
    before = tree(tmp_path)
    balance = call(tmp_path, "balance", "--year", "2027", "--as-of", "2027-01-10")
    assert balance["balances"]["annual"] == 92
    assert any(row["code"] == "STALE_CARRYOVER" for row in balance["warnings"])
    preview = call(tmp_path, "carryover-reconcile", "--year", "2027", "--preview")
    assert preview["affected_years"] == [2027]
    assert tree(tmp_path) == before
    result = call(
        tmp_path, "carryover-reconcile", "--year", "2027", "--expected-fingerprint", preview["preview_fingerprint"]
    )
    assert result["action"] == "applied"
    assert not call(tmp_path, "balance", "--year", "2027", "--as-of", "2027-01-10")["warnings"]


def test_INT_014_legacy_forward_link_keeps_historical_lot(tmp_path):
    source, config = store(
        tmp_path,
        transactions=[
            tx(
                "origin",
                "2026-06-01",
                "comp",
                "earned",
                8,
                expiration_date="2028-01-01",
                rolled_over_to_transaction_id="legacy-copy",
            )
        ],
    )
    from fedleave.expirations import expiration_report

    report = expiration_report(source, config, as_of=date(2026, 8, 1))
    assert report["lots"][0]["remaining_hours"] == 8
    target, preview = creation_plan(tmp_path, 2026, 2027)
    assert preview["lots"][0]["origin_transaction_id"] == "origin"


@pytest.mark.parametrize("seed", ["1", "123", "random"], ids=lambda seed: "PROP-019-" + seed)
def test_hash_seed_determinism(tmp_path, seed):
    store(tmp_path, balances={"annual": 100}, transactions=[tx("lot", "2026-06-01", "time_off_award", "earned", 8)])
    expected = call(tmp_path, "rollover", "--from-year", "2026", "--to-year", "2027", "--preview")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "fedleave",
            "rollover",
            "--from-year",
            "2026",
            "--to-year",
            "2027",
            "--preview",
            "--json",
            "--data-dir",
            str(tmp_path),
        ],
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == expected


def test_INT_006_009_019_warning_expiry_chart_month_and_balance_agree(tmp_path):
    from decimal import Decimal

    from fedleave.charting import snapshot_balance_points

    store(tmp_path, transactions=[tx("origin", "2026-06-01", "comp", "earned", 8, expiration_date="2027-02-01")])
    call(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    snapshot = call(tmp_path, "snapshot", "--year", "2027")
    points = snapshot_balance_points(snapshot, "comp")
    assert points[0][1] == Decimal(8)
    assert points[1][1] == Decimal(0)
    balance = call(tmp_path, "balance", "--year", "2027", "--as-of", "2027-02-06")
    assert balance["balances"]["comp"] == 0
    report = call(tmp_path, "expirations", "--year", "2027", "--as-of", "2027-02-06")
    assert report["lots"][0]["remaining_hours"] == 8
    assert report["lots"][0]["available_hours"] == 0
    assert report["lots"][0]["status"] == "warning"
    month = call(tmp_path, "month", "--year", "2027", "--month", "2")
    period = next(row for row in month["pay_periods"] if row["end"] == "2027-02-06")
    assert period["ending_balances"]["comp"] == 0
    _, preview = creation_plan(tmp_path, 2027, 2028)
    assert preview["categories"]["comp"]["source_balance"] == 0
    assert preview["categories"]["comp"]["retained_expired_hours"] == 8
    assert preview["opening_balances"]["comp"] == 0


def test_generated_carryovers_survive_authoritative_day_edits(tmp_path):
    store(
        tmp_path,
        balances={"annual": 100},
        transactions=[tx("origin", "2026-06-01", "comp", "earned", 8, expiration_date="2029-01-01")],
    )
    call(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    target = json.loads((tmp_path / "leave_years/2027.json").read_text())
    generated = [row for row in target["transactions"] if row.get("carryover_generated")]
    call(tmp_path, "set-day", "--date", "2027-01-10", "--comp", "-2", "--authoritative")
    updated = json.loads((tmp_path / "leave_years/2027.json").read_text())
    assert [row for row in updated["transactions"] if row.get("carryover_generated")] == generated
    balance = call(tmp_path, "balance", "--year", "2027", "--as-of", "2027-01-10")
    assert balance["balances"]["comp"] == 6
    period = call(tmp_path, "pay-period", "--year", "2027", "--date", "2027-01-10")
    assert period["activity"]["earned"].get("comp", 0) == 0
    assert period["activity"]["used"]["comp"] == 2
