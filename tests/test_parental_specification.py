"""Acceptance cases from the complete PPL/FMLA specification supplied for #132."""

import json
from datetime import date

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.cross_year import resolve_snapshot
from fedleave.ledger import calculate_balances
from fedleave.parental import anniversary, fmla_report, parental_report
from leave_year_support import store as create_store
from leave_year_support import tree, tx


def store(base, **kwargs):
    result = create_store(base, **kwargs)
    # Real initialized stores already have the permanent writer-lock inode.
    (base / ".fedleave.lock").touch()
    return result


def cli(base, *args, success=True):
    json_args = [] if args[0] == "import-data" else ["--json"]
    result = CliRunner().invoke(app, [*args, *json_args, "--data-dir", str(base)])
    assert (result.exit_code == 0) == success, (result.output, result.exception)
    return json.loads(result.output) if success else result


def test_use_after_late_source_entry_requires_no_reconciliation(tmp_path):
    store(tmp_path)
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    cli(tmp_path, "add", "--year", "2026", "--date", "2026-10-01", "--category", "ppl", "--used", "120")
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-03-01", "--category", "ppl", "--used", "80")
    response = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01")
    assert response["balances"]["ppl"] == 280
    assert response["balances"]["fmla"] == -200
    assert len(response["parental"]["ppl_windows"]) == 1


def test_tour_change_preserves_weeks_origin_hours_and_debits(tmp_path):
    store(tmp_path, rules={"fmla": {"history_complete_from": "2026-01-01"}})
    grant = cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    cli(
        tmp_path,
        "add",
        "--year",
        "2026",
        "--date",
        "2026-10-01",
        "--category",
        "ppl",
        "--used",
        "120",
        "--status",
        "reconciled",
    )
    config_path = tmp_path / "config.json"
    config = json.loads(config_path.read_text())
    config["rules"]["fmla"]["weekly_hours"] = 20
    config_path.write_text(json.dumps(config))
    report = cli(tmp_path, "balance", "--year", "2026", "--as-of", "2026-11-01")["parental"]
    assert report["ppl_available_hours"] == 180
    assert report["fmla"]["remaining_hours"] == 180
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    snapshot = resolve_snapshot(tmp_path, 2027)
    carried = next(row for row in snapshot["transactions"] if row.get("category") == "ppl")
    assert carried["origin_transaction_id"] == grant["transaction_id"]
    assert carried["hours"] == 180
    assert carried["origin_earned_hours"] == 480
    assert carried["previously_consumed_hours"] == 120
    assert carried["origin_dispositions"] == {"used": 120}
    assert carried["scheduled_weekly_hours"] == 20
    assert carried["origin_scheduled_weekly_hours"] == 40
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-02-01", "--category", "ppl", "--used", "20")
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-02-01")["parental"]
    assert report["ppl_available_hours"] == 160
    assert report["fmla"]["remaining_hours"] == 160
    assert report["fmla"]["used_hours"] == 140


def test_unverified_history_is_unknown_and_never_claims_full_capacity():
    ledger = {"transactions": [tx("grant", "2026-09-01", "ppl", "earned", 480)]}
    report = parental_report(ledger, {}, as_of=date(2026, 10, 1))
    assert report["ppl_available_hours"] == 480
    assert report["ppl_usable_hours"] is None
    assert report["fmla"]["remaining_hours"] is None
    assert report["fmla"]["history_status"] == "incomplete"
    assert report["fmla"]["period"] is None
    assert any(row["code"] == "INCOMPLETE_FMLA_HISTORY" for row in report["warnings"])


def test_future_and_unresolved_usage_does_not_set_confirmed_period():
    ledger = {
        "transactions": [
            tx("unresolved", "2026-01-01", "fmla", "used", 8, status="planned"),
            tx("actual", "2026-06-01", "fmla", "used", 8),
            tx("future", "2026-12-01", "fmla", "used", 8),
        ]
    }
    report = fmla_report(ledger, {}, date(2026, 12, 31), today=date(2026, 10, 1))
    assert report["period"]["start_date"] == "2026-01-01"
    assert report["period"]["provisional"] is True
    assert report["confirmed_period"]["start_date"] == "2026-06-01"
    assert report["confirmed_balance"] == -8
    assert [row["transaction_id"] for row in report["scheduled_contributions"]] == ["future"]


def test_new_ambiguous_overlap_requires_explicit_acknowledgement(tmp_path):
    store(
        tmp_path,
        transactions=[tx("grant", "2026-06-01", "ppl", "earned", 480), tx("use", "2026-07-01", "ppl", "used", 8)],
    )
    before = tree(tmp_path)
    rejected = cli(
        tmp_path, "add", "--year", "2026", "--date", "2026-07-01", "--category", "fmla", "--used", "8", success=False
    )
    assert "POSSIBLE_DUPLICATE_FMLA" in str(rejected.exception) + rejected.output
    assert tree(tmp_path) == before
    cli(
        tmp_path,
        "add",
        "--year",
        "2026",
        "--date",
        "2026-07-01",
        "--category",
        "fmla",
        "--used",
        "4",
        "--acknowledge-fmla-overlap",
    )
    report = cli(tmp_path, "balance", "--year", "2026", "--as-of", "2026-07-01")
    assert report["balances"]["fmla"] == -12
    assert report["parental"]["fmla"]["ppl_derived_hours"] == 8
    assert report["parental"]["fmla"]["explicit_used_hours"] == 4
    assert any(row["code"] == "POSSIBLE_DUPLICATE_FMLA" for row in report["parental"]["warnings"])
    saved = json.loads((tmp_path / "leave_years/2026.json").read_text())
    assert "_fmla_overlap_acknowledged" not in saved
    assert next(row for row in saved["transactions"] if row["category"] == "fmla")["fmla_overlap_acknowledged"] is True


@pytest.mark.parametrize("category", ["ppl", "fmla"])
def test_force_balance_cannot_bypass_category_policy(tmp_path, category):
    store(tmp_path)
    before = tree(tmp_path)
    cli(
        tmp_path,
        "force-balance",
        "--date",
        "2026-06-01",
        "--category",
        category,
        "--hours",
        "8",
        "--comment",
        "test",
        success=False,
    )
    assert tree(tmp_path) == before


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2026-09-01", "2027-09-01"),
        ("2026-11-15", "2027-11-15"),
        ("2028-02-29", "2029-02-28"),
        ("2027-02-28", "2028-02-28"),
    ],
)
def test_calendar_anniversary_policy(day, expected):
    assert anniversary(date.fromisoformat(day)).isoformat() == expected


def test_windows_report_recorded_scheduled_protected_and_expired_hours():
    ledger = {
        "transactions": [
            tx("grant", "2026-09-01", "ppl", "earned", 480),
            tx("used", "2026-10-01", "ppl", "used", 120),
            tx("scheduled", "2027-03-01", "ppl", "used", 80, status="planned"),
        ]
    }
    report = parental_report(ledger, {}, as_of=date(2026, 10, 15), today=date(2026, 10, 15))
    window = report["ppl_windows"][0]
    assert window["recorded_used_hours"] == 120
    assert window["scheduled_used_hours"] == window["protected_scheduled_hours"] == 80
    assert window["potential_unused_loss_hours"] == 280
    assert window["expiration_effective_date"] == "2027-09-01"
    expired = parental_report(ledger, {}, as_of=date(2027, 9, 1))["ppl_windows"][0]
    assert expired["expired_unused_hours"] == 280
    assert expired["available_hours"] == 0


def test_source_correction_and_void_recompute_without_writing_descendant(tmp_path):
    store(
        tmp_path,
        transactions=[tx("grant", "2026-09-01", "ppl", "earned", 480), tx("use", "2026-10-01", "ppl", "used", 120)],
    )
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    target_path = tmp_path / "leave_years/2027.json"
    before = target_path.read_bytes()
    cli(tmp_path, "correct", "--id", "use", "--hours", "80", "--reason", "actual usage")
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01")
    assert report["balances"]["ppl"] == 400
    assert report["balances"]["fmla"] == -80
    cli(tmp_path, "void", "--id", "use", "--reason", "not taken")
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01")
    assert report["balances"]["ppl"] == 480
    assert report["balances"]["fmla"] == 0
    assert target_path.read_bytes() == before


def test_corrected_earned_date_moves_window_from_sole_anchor(tmp_path):
    store(tmp_path)
    grant = cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    cli(
        tmp_path,
        "correct",
        "--id",
        grant["transaction_id"],
        "--date",
        "2026-08-01",
        "--hours",
        "480",
        "--reason",
        "correct event date",
    )
    report = cli(tmp_path, "expirations", "--year", "2026", "--category", "ppl", "--as-of", "2026-10-01")
    assert report["lots"][0]["expiration_effective_date"] == "2027-08-01"


def test_missing_source_never_reports_full_capacity(tmp_path):
    store(tmp_path, transactions=[tx("grant", "2026-09-01", "ppl", "earned", 480)])
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    (tmp_path / "leave_years/2026.json").unlink()
    before = tree(tmp_path)
    response = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01", success=False)
    assert "MISSING_SOURCE_YEAR" in response.output + str(response.exception)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("category,direction", [("fmla", "earned"), ("ppl", "paid_out")])
def test_validate_reports_legacy_restriction_without_mutation(tmp_path, category, direction):
    store(tmp_path, transactions=[tx("bad", "2026-06-01", category, direction, 8)])
    before = tree(tmp_path)
    result = cli(tmp_path, "validate", success=False)
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["results"][0]["issues"][0]["type"] == "direction"
    assert tree(tmp_path) == before


def test_ppl_expiry_cannot_be_disabled_or_converted_to_payout(tmp_path):
    for rule in ({"expires": False}, {"expiration_action": "paid_out"}, {"allow_extension": True}):
        store(tmp_path, rules={"ppl": rule})
        before = tree(tmp_path)
        cli(
            tmp_path,
            "add",
            "--year",
            "2026",
            "--date",
            "2026-06-01",
            "--category",
            "ppl",
            "--earned",
            "480",
            success=False,
        )
        assert tree(tmp_path) == before


def test_ppl_in_27_period_year_retains_december_boundary(tmp_path):
    store(
        tmp_path,
        start="2025-12-28",
        count=27,
        transactions=[tx("grant", "2026-12-01", "ppl", "earned", 480), tx("use", "2026-12-02", "ppl", "used", 8)],
    )
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    snapshot = resolve_snapshot(tmp_path, 2027)
    assert snapshot["leave_year_start"] == "2027-01-10"
    assert calculate_balances(snapshot, until_date="2027-11-30")["ppl"] == 472
    assert calculate_balances(snapshot, until_date="2027-12-01")["ppl"] == 0


def test_import_rejects_fmla_opening_before_any_store_files_are_created(tmp_path):
    source, config = store(tmp_path / "source")
    source["starting_balances"]["fmla"] = 480
    archive = tmp_path / "archive.json"
    archive.write_text(json.dumps({"schema_version": 1, "config": config, "leave_years": {"2026": source}}))
    destination = tmp_path / "destination"
    rejected = cli(destination, "import-data", "--input", str(archive), success=False)
    assert "INVALID_PARENTAL_OPENING" in rejected.output + str(rejected.exception)
    assert not list(destination.rglob("*.json"))


def test_saved_grant_and_add_response_expose_same_fixed_deadline(tmp_path):
    store(tmp_path)
    added = cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    persisted = json.loads((tmp_path / "leave_years/2026.json").read_text())["transactions"]
    grant = next(row for row in persisted if row["id"] == added["transaction_id"])
    assert added["transaction"] == grant
    assert grant["expiration_date"] == "2027-08-31"
    assert grant["scheduled_weekly_hours"] == 40


def test_missing_historical_tour_has_unknown_capacity_even_with_coverage():
    ledger = {"transactions": [tx("old", "2026-06-01", "fmla", "used", 8)]}
    report = fmla_report(ledger, {"rules": {"fmla": {"history_complete_from": "2026-01-01"}}}, date(2026, 7, 1))
    assert report["remaining_hours"] is None
    assert report["schedule_status"] == "unverified"
    assert any(row["code"] == "UNVERIFIED_HISTORICAL_TOUR" for row in report["warnings"])


def test_voiding_source_grant_flags_orphaned_successor_use_as_unknown(tmp_path):
    store(tmp_path)
    grant = cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-03-01", "--category", "ppl", "--used", "8")
    cli(tmp_path, "void", "--id", grant["transaction_id"])
    before = tree(tmp_path)
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01")
    assert report["balances"]["ppl"] is None
    assert report["parental"]["ppl_usable_hours"] is None
    assert any(row["code"] == "INVALID_PARENTAL_HISTORY" for row in report["warnings"])
    assert tree(tmp_path) == before


@pytest.mark.parametrize("hours", ["0", "0.1", "nan", "inf"])
def test_parental_hours_follow_positive_finite_configured_increments(tmp_path, hours):
    store(tmp_path)
    before = tree(tmp_path)
    cli(
        tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", hours, success=False
    )
    assert tree(tmp_path) == before


def test_parental_reconciliation_recovers_interrupted_chain_and_is_idempotent(tmp_path, monkeypatch):
    import fedleave.cross_year as service

    store(tmp_path)
    grant = cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    cli(tmp_path, "add", "--year", "2026", "--date", "2026-10-01", "--category", "ppl", "--used", "120")
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-03-01", "--category", "ppl", "--used", "80")
    cli(tmp_path, "init", "--from-year", "2027", "--year", "2028")
    cli(tmp_path, "correct", "--id", grant["transaction_id"], "--hours", "400", "--reason", "agency confirmed amount")
    changes, preview = service.reconciliation_plan(tmp_path, 2027)
    assert set(changes) == {2027, 2028}
    originals = {year: json.loads((tmp_path / f"leave_years/{year}.json").read_text()) for year in changes}
    real_write = service.atomic_write_json

    def interrupted(path, payload, overwrite=True):
        if path.name == "2028.json":
            raise KeyboardInterrupt("power loss")
        return real_write(path, payload, overwrite=overwrite)

    monkeypatch.setattr(service, "atomic_write_json", interrupted)
    with pytest.raises(KeyboardInterrupt):
        service.apply_reconciliation(tmp_path, changes, preview)
    assert (tmp_path / "carryover-reconciliation.json").exists()
    monkeypatch.setattr(service, "atomic_write_json", real_write)
    assert service.recover_reconciliation(tmp_path)["recovered_years"] == [2027, 2028]
    assert all(
        json.loads((tmp_path / f"leave_years/{year}.json").read_text()) == original
        for year, original in originals.items()
    )
    changes, preview = service.reconciliation_plan(tmp_path, 2027)
    service.apply_reconciliation(tmp_path, changes, preview)
    before = tree(tmp_path)
    assert service.reconciliation_plan(tmp_path, 2027)[0] == {}
    assert tree(tmp_path) == before
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01")
    assert report["balances"]["ppl"] == 200 and report["balances"]["fmla"] == -200
    target = json.loads((tmp_path / "leave_years/2027.json").read_text())
    assert len([row for row in target["transactions"] if row["category"] == "ppl" and row["direction"] == "used"]) == 1
    assert not any(row["category"] == "fmla" for row in target["transactions"])


def test_projected_balance_and_parental_diagnostics_use_same_target_date(tmp_path):
    store(tmp_path)
    cli(tmp_path, "add", "--year", "2026", "--date", "2026-09-01", "--category", "ppl", "--earned", "480")
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01", "--project-to", "2027-09-01")
    assert report["balances"]["ppl"] == 0
    assert report["parental"]["ppl_available_hours"] == 0
    assert report["parental"]["as_of"] == "2027-09-01"


@pytest.mark.parametrize(
    "row",
    [
        tx("fake", "2026-06-01", "ppl", "earned", 480, carryover_generated=True),
        tx("fake", "2026-06-01", "fmla", "used", 8, carryover_generated=True),
    ],
)
def test_import_rejects_generated_parental_entries_without_provenance(tmp_path, row):
    source, config = store(tmp_path / "source", transactions=[row])
    archive = tmp_path / "archive.json"
    archive.write_text(json.dumps({"schema_version": 1, "config": config, "leave_years": {"2026": source}}))
    destination = tmp_path / "destination"
    rejected = cli(destination, "import-data", "--input", str(archive), success=False)
    assert "PROVENANCE" in rejected.output or "FMLA_USAGE_ONLY" in rejected.output
    assert not list(destination.rglob("*.json"))


def test_explicit_year_cannot_place_parental_event_outside_actual_bounds(tmp_path):
    store(tmp_path)
    before = tree(tmp_path)
    rejected = cli(
        tmp_path, "add", "--year", "2026", "--date", "2027-10-01", "--category", "ppl", "--earned", "480", success=False
    )
    assert "INVALID_PARENTAL_DATE" in rejected.output + str(rejected.exception)
    assert tree(tmp_path) == before


def test_activity_and_pay_period_separate_entitlement_from_physical_absence(tmp_path):
    store(tmp_path)
    cli(tmp_path, "add", "--year", "2026", "--date", "2026-06-01", "--category", "ppl", "--earned", "480")
    cli(
        tmp_path,
        "set-day",
        "--date",
        "2026-07-01",
        "--authoritative",
        "--ppl",
        "-8",
        "--fmla",
        "-4",
        "--acknowledge-fmla-overlap",
    )
    activity = cli(tmp_path, "activity", "--year", "2026", "--date", "2026-07-01")
    assert activity["activity"]["used"]["ppl"] == 8
    assert activity["activity"]["used"]["fmla"] == 12
    assert activity["physical_absence_hours"] == 8
    pp = cli(tmp_path, "pay-period", "--year", "2026", "--date", "2026-07-01")
    assert pp["activity"]["used"]["fmla"] == 12
    assert pp["physical_absence_hours"] == 8
    assert pp["ending_balances"]["fmla"] == -12


def test_original_ids_are_scoped_by_source_year_in_window_audit(tmp_path):
    store(tmp_path, transactions=[tx("shared-legacy-id", "2026-09-01", "ppl", "earned", 480)])
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    target_path = tmp_path / "leave_years/2027.json"
    target = json.loads(target_path.read_text())
    target["transactions"].extend(
        [tx("shared-legacy-id", "2027-02-01", "ppl", "earned", 480), tx("use", "2027-03-01", "ppl", "used", 8)]
    )
    target_path.write_text(json.dumps(target))
    before = tree(tmp_path)
    report = cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-03-01")
    assert report["balances"]["ppl"] == 472
    assert report["balances"]["fmla"] == -8
    windows = report["parental"]["ppl_windows"]
    assert {(row["source_leave_year"], row["transaction_id"]) for row in windows} == {
        (2026, "shared-legacy-id"),
        (2027, "shared-legacy-id"),
    }
    assert tree(tmp_path) == before
