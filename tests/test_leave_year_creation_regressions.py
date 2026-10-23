"""Independent regression examples for issue #134's accounting defects."""

import json
from datetime import date

from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.config import Config
from fedleave.expirations import synchronize_expirations
from fedleave.ledger import calculate_balances
from fedleave.payperiods import generate_pay_periods


def source_store(tmp_path):
    periods = generate_pay_periods(date(2026, 1, 11))
    source = {
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "pay_period_count": 26,
        "pay_periods": periods,
        "annual_leave_accrual_hours": 0,
        "sick_leave_accrual_hours": 0,
        "starting_balances": {"annual": 280, "sick": 600, "credit": 30},
        "transactions": [
            {
                "id": "award",
                "date": "2026-06-01",
                "category": "time_off_award",
                "direction": "earned",
                "hours": 8,
                "status": "reconciled",
            }
        ],
    }
    (tmp_path / "leave_years").mkdir()
    (tmp_path / "config.json").write_text(json.dumps(Config().model_dump()))
    (tmp_path / "leave_years/2026.json").write_text(json.dumps(source))
    return source


def test_BAL_019_legacy_mirrored_opening_counts_once():
    ledger = {
        "starting_balances": {"annual": 240},
        "transactions": [
            {"id": "opening", "date": "2027-01-10", "category": "annual", "direction": "starting_balance", "hours": 240}
        ],
    }
    assert calculate_balances(ledger)["annual"] == 240


def test_DATE_001_BAL_010_BAL_012_rollover_boundary_and_categories(tmp_path):
    source_store(tmp_path)
    result = CliRunner().invoke(
        app, ["rollover", "--from-year", "2026", "--to-year", "2027", "--json", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    target = json.loads((tmp_path / "leave_years/2027.json").read_text())
    assert target["leave_year_start"] == "2027-01-10"
    balances = calculate_balances(target, until_date="2027-01-10")
    assert {key: balances[key] for key in ("annual", "sick", "credit", "time_off_award")} == {
        "annual": 240,
        "sick": 600,
        "credit": 24,
        "time_off_award": 8,
    }


def test_LOT_022_usage_cannot_draw_from_expired_lot():
    lot = {
        "id": "lot",
        "date": "2026-02-01",
        "category": "comp",
        "direction": "earned",
        "hours": 8,
        "expiration_date": "2026-03-01",
    }
    use = {"id": "use", "date": "2026-03-02", "category": "comp", "direction": "used", "hours": 4}
    ledger = {"transactions": [lot, use]}
    synchronize_expirations(ledger, Config().model_dump(), as_of=date(2026, 3, 2))
    assert not use.get("earned_transaction_id")


def test_MAN_009_MOD_001_cli_exposes_both_modes(tmp_path):
    source_store(tmp_path)
    result = CliRunner().invoke(
        app, ["init", "--year", "2027", "--from-year", "2026", "--preview", "--json", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["initialization_mode"] == "carryover"
    assert not (tmp_path / "leave_years/2027.json").exists()
