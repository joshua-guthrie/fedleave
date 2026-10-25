"""Independent PPL event-window and first-use FMLA accounting examples."""

from datetime import date

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.ledger import calculate_balances
from leave_year_support import store, tx


def test_ppl_earned_and_used_are_supported(tmp_path):
    store(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "add",
            "--year",
            "2026",
            "--date",
            "2026-10-01",
            "--category",
            "ppl",
            "--earned",
            "480",
            "--json",
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output


def test_fmla_includes_ppl_without_a_second_absence():
    ledger = {
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "transactions": [
            tx("grant", "2026-06-01", "ppl", "earned", 480),
            tx("unpaid", "2026-05-01", "fmla", "used", 40),
            tx("parental", "2026-06-10", "ppl", "used", 16),
        ],
    }
    balances = calculate_balances(ledger, until_date="2026-07-01")
    assert balances["ppl"] == 464
    assert balances["fmla"] == -56


def test_ppl_ends_day_before_anniversary():
    ledger = {"transactions": [tx("grant", "2026-06-01", "ppl", "earned", 480)]}
    assert calculate_balances(ledger, until_date="2027-05-31")["ppl"] == 480
    assert calculate_balances(ledger, until_date="2027-06-01")["ppl"] == 0


def test_fmla_period_starts_with_first_use_and_resets_on_next_use():
    ledger = {
        "transactions": [tx("first", "2026-04-01", "fmla", "used", 80), tx("next", "2027-04-15", "fmla", "used", 8)]
    }
    assert calculate_balances(ledger, until_date="2027-03-31")["fmla"] == -80
    assert calculate_balances(ledger, until_date="2027-04-01")["fmla"] == 0
    assert calculate_balances(ledger, until_date="2027-04-15")["fmla"] == -8


def test_overlapping_grants_are_not_additive_entitlements():
    ledger = {
        "transactions": [
            tx("first", "2026-01-01", "ppl", "earned", 480),
            tx("second", "2026-07-01", "ppl", "earned", 480),
            tx("use", "2026-08-01", "ppl", "used", 40),
        ]
    }
    assert calculate_balances(ledger, until_date="2026-09-01")["ppl"] == 440
    assert calculate_balances(ledger, until_date="2027-02-01")["ppl"] == 440
    assert calculate_balances(ledger, until_date="2026-09-01")["fmla"] == -40


def cli(base, *args, success=True):
    result = CliRunner().invoke(app, [*args, "--json", "--data-dir", str(base)])
    assert (result.exit_code == 0) == success, (result.output, result.exception)
    return result


def test_cross_year_grant_entered_after_successor_creation_is_readonly(tmp_path):
    import json

    from fedleave.cross_year import resolve_snapshot
    from leave_year_support import tree

    store(tmp_path)
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    cli(tmp_path, "add", "--year", "2026", "--date", "2026-10-01", "--category", "ppl", "--earned", "480")
    before = tree(tmp_path)
    assert calculate_balances(resolve_snapshot(tmp_path, 2027), until_date="2027-01-10")["ppl"] == 480
    assert tree(tmp_path) == before
    preview = cli(tmp_path, "carryover-reconcile", "--year", "2027", "--preview")
    token = json.loads(preview.output)["preview_fingerprint"]
    cli(tmp_path, "carryover-reconcile", "--year", "2027", "--expected-fingerprint", token)
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-02-01", "--category", "ppl", "--used", "40")
    result = json.loads(cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-02-01").output)
    assert result["balances"]["ppl"] == 440
    assert result["balances"]["fmla"] == -40
    assert result["parental"]["fmla"]["period"]["start_date"] == "2027-02-01"
    snapshot = resolve_snapshot(tmp_path, 2027)
    assert calculate_balances(snapshot, until_date="2027-10-01")["ppl"] == 0
    assert calculate_balances(snapshot, until_date="2028-02-01")["fmla"] == 0


def test_prior_fmla_usage_keeps_its_first_use_anchor_across_years(tmp_path):
    import json

    from fedleave.cross_year import resolve_snapshot

    store(
        tmp_path,
        transactions=[tx("prior", "2026-03-01", "fmla", "used", 40), tx("grant", "2026-10-01", "ppl", "earned", 480)],
    )
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-02-01", "--category", "ppl", "--used", "16")
    response = json.loads(cli(tmp_path, "balance", "--year", "2027", "--as-of", "2027-02-01").output)
    assert response["balances"]["fmla"] == -56
    assert response["parental"]["fmla"]["period"]["start_date"] == "2026-03-01"
    assert calculate_balances(resolve_snapshot(tmp_path, 2027), until_date="2027-03-01")["fmla"] == 0


@pytest.mark.parametrize(
    "category,direction,hours",
    [("fmla", "earned", "480"), ("fmla", "adjusted", "8"), ("ppl", "earned", "481"), ("ppl", "used", "8")],
)
def test_invalid_parental_mutations_never_change_a_ledger(tmp_path, category, direction, hours):
    store(tmp_path)
    before = (tmp_path / "leave_years/2026.json").read_bytes()
    result = cli(
        tmp_path,
        "add",
        "--year",
        "2026",
        "--date",
        "2026-06-01",
        "--category",
        category,
        "--" + direction,
        hours,
        success=False,
    )
    assert result.exit_code != 0
    assert (tmp_path / "leave_years/2026.json").read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_duplicate_same_day_event_and_extensions_are_rejected(tmp_path):
    import json

    store(tmp_path)
    response = cli(tmp_path, "add", "--year", "2026", "--date", "2026-06-01", "--category", "ppl", "--earned", "480")
    grant_id = json.loads(response.output)["transaction_id"]
    cli(
        tmp_path, "add", "--year", "2026", "--date", "2026-06-01", "--category", "ppl", "--earned", "480", success=False
    )
    cli(
        tmp_path,
        "expiration-extend",
        "--id",
        grant_id,
        "--new-date",
        "2027-08-01",
        "--reason",
        "Request",
        success=False,
    )


def test_fmla_limit_and_alternate_tour_are_weeks_based(tmp_path):
    from fedleave.parental import fmla_report

    ledger = {"transactions": [tx("use", "2026-06-01", "fmla", "used", 600, scheduled_weekly_hours=50)]}
    schedule = {
        "defaults": {"workday_start": "07:00", "workday_end": "17:30"},
        "rules": {"fmla": {"history_complete_from": "2026-01-01"}},
    }
    report = fmla_report(ledger, schedule, date(2026, 7, 1))
    assert report["weekly_hours"] == 50 and report["remaining_hours"] == 0
    with pytest.raises(ValueError, match="FMLA_LIMIT_EXCEEDED"):
        fmla_report({"transactions": [tx("use", "2026-06-01", "fmla", "used", 600)]}, {}, date(2026, 7, 1))


def test_analytics_counts_parental_absence_once_and_fmla_zero():
    from fedleave_analytics.analytics import analyze_leave_year

    ledger = {
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "transactions": [
            tx("grant", "2026-06-01", "ppl", "earned", 480),
            tx("use", "2026-07-01", "ppl", "used", 8),
            tx("tracker", "2026-07-01", "fmla", "used", 4),
        ],
        "pay_periods": [],
    }
    report = analyze_leave_year(ledger, today=date(2026, 8, 1))
    assert report["source"]["absence_transactions"] == 1
    assert sum(row["full_day_total"] for row in report["heatmap"]) == 8
    assert sum(row["full_day_total"] for row in report["heatmap_series"]["fmla:used"]) == 12
    assert sum(row["full_day_total"] for row in report["heatmap_series"]["ppl:used"]) == 8
    assert all(row["category"] != "fmla" for row in report["net_accumulation_categories"])
    assert not any(row["category"] == "fmla" and row["direction"] != "used" for row in report["transactions"])


def test_exhausted_overlapping_window_remains_a_cross_year_constraint(tmp_path):
    from fedleave.cross_year import apply_creation, creation_plan, resolve_snapshot
    from fedleave.parental import parental_report

    store(
        tmp_path,
        rules={"fmla": {"history_complete_from": "2026-01-01"}},
        transactions=[
            tx("first", "2026-03-01", "ppl", "earned", 480, scheduled_weekly_hours=40),
            tx("used", "2026-04-01", "ppl", "used", 480, scheduled_weekly_hours=40),
            tx("second", "2026-10-01", "ppl", "earned", 480, scheduled_weekly_hours=40),
        ],
    )
    target, preview = creation_plan(tmp_path, 2026, 2027)
    assert sorted(row["hours"] for row in preview["lots"]) == [0, 480]
    assert preview["opening_balances"]["ppl"] == 0
    apply_creation(tmp_path, target, preview)
    snapshot = resolve_snapshot(tmp_path, 2027)
    assert calculate_balances(snapshot, until_date="2027-02-01")["ppl"] == 0
    report = parental_report(snapshot, snapshot.config, as_of=date(2027, 3, 1))
    assert report["ppl_available_hours"] == 480
    assert report["ppl_usable_hours"] == 0  # Earlier FMLA clock has not ended.
    assert parental_report(snapshot, snapshot.config, as_of=date(2027, 4, 1))["ppl_usable_hours"] == 480


def test_ppl_grant_and_use_on_same_date_survive_calendar_edits(tmp_path):
    import json

    store(tmp_path)
    cli(tmp_path, "set-day", "--date", "2026-06-01", "--ppl", "480", "--authoritative")
    cli(tmp_path, "set-day", "--date", "2026-06-01", "--ppl", "-8", "--authoritative")
    response = json.loads(cli(tmp_path, "balance", "--year", "2026", "--as-of", "2026-06-01").output)
    assert response["balances"]["ppl"] == 472 and response["balances"]["fmla"] == -8
    cli(tmp_path, "set-day", "--date", "2026-06-01", "--ppl", "0", "--authoritative")
    response = json.loads(cli(tmp_path, "balance", "--year", "2026", "--as-of", "2026-06-01").output)
    assert response["balances"]["ppl"] == 480 and response["balances"]["fmla"] == 0


@pytest.mark.parametrize("day,expected", [("2027-05-31", True), ("2027-06-01", False)])
def test_last_eligible_day_and_first_ineligible_day(tmp_path, day, expected):
    store(tmp_path, transactions=[tx("grant", "2026-06-01", "ppl", "earned", 480)])
    cli(tmp_path, "init", "--from-year", "2026", "--year", "2027")
    before = (tmp_path / "leave_years/2027.json").read_bytes()
    cli(tmp_path, "add", "--year", "2027", "--date", day, "--category", "ppl", "--used", "8", success=expected)
    if not expected:
        assert (tmp_path / "leave_years/2027.json").read_bytes() == before


def test_export_import_and_cross_year_read_surfaces_preserve_provenance(tmp_path):
    import json

    from leave_year_support import tree

    base, imported = tmp_path / "data", tmp_path / "imported"
    store(
        base, transactions=[tx("grant", "2026-10-01", "ppl", "earned", 480), tx("use", "2026-11-01", "ppl", "used", 16)]
    )
    cli(base, "init", "--from-year", "2026", "--year", "2027")
    cli(base, "add", "--year", "2027", "--date", "2027-02-01", "--category", "ppl", "--used", "8")
    before = tree(base)
    for args in [
        ("balance", "--year", "2027", "--as-of", "2027-02-01"),
        ("expirations", "--year", "2027", "--as-of", "2027-02-01"),
        ("month", "--year", "2027", "--month", "2"),
        ("pay-periods", "--year", "2027"),
        ("snapshot", "--year", "2027"),
        ("list", "--year", "2027"),
    ]:
        cli(base, *args)
    assert tree(base) == before
    archive = tmp_path / "backup.json"
    response = CliRunner().invoke(app, ["export-data", "--output", str(archive), "--data-dir", str(base)])
    assert response.exit_code == 0, response.output
    response = CliRunner().invoke(app, ["import-data", "--input", str(archive), "--data-dir", str(imported)])
    assert response.exit_code == 0, response.output
    original = json.loads(cli(base, "balance", "--year", "2027", "--as-of", "2027-02-01").output)
    restored = json.loads(cli(imported, "balance", "--year", "2027", "--as-of", "2027-02-01").output)
    assert restored["balances"] == original["balances"]
    assert restored["parental"] == original["parental"]
    assert restored["balances"]["fmla"] == -24


def test_manual_boundary_does_not_import_unrelated_ppl(tmp_path):
    from fedleave.cross_year import resolve_snapshot

    store(tmp_path, transactions=[tx("grant", "2026-10-01", "ppl", "earned", 480)])
    cli(tmp_path, "init", "--year", "2027", "--leave-year-start", "2027-01-10")
    assert calculate_balances(resolve_snapshot(tmp_path, 2027), until_date="2027-02-01")["ppl"] == 0
    cli(tmp_path, "add", "--year", "2027", "--date", "2027-02-01", "--category", "ppl", "--used", "8", success=False)


def test_four_ten_hour_days_still_provide_480_fmla_hours():
    from fedleave.parental import weekly_hours

    assert (
        weekly_hours(
            {
                "defaults": {
                    "workday_start": "07:00",
                    "workday_end": "17:30",
                    "normal_workdays": ["mon", "tue", "wed", "thu"],
                }
            }
        )
        == 40
    )


@pytest.mark.parametrize("status,void", [("denied", False), ("cancelled", False), ("reconciled", True)])
def test_inactive_usage_does_not_start_a_period(status, void):
    from fedleave.parental import fmla_report

    ledger = {
        "transactions": [
            tx("ignored", "2026-01-01", "fmla", "used", 40, status=status, void=void),
            tx("actual", "2026-06-01", "fmla", "used", 8),
        ]
    }
    report = fmla_report(ledger, {}, date(2026, 7, 1))
    assert report["period"]["start_date"] == "2026-06-01" and report["used_hours"] == 8
