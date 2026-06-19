from pathlib import Path
import json

from fedleave.cli import balance, pay_period_summary, pay_periods_summary
from fedleave.config import init_config
from fedleave.ledger import calculate_balances, calculate_pay_period_activity, ensure_automatic_accruals
from fedleave.storage import write_json


def _init_data_dir(data_dir: Path) -> dict:
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 10.0,
            "sick": 20.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        data_dir=data_dir,
    )
    return json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))


def test_ensure_automatic_accruals_adds_annual_and_sick_once(tmp_path: Path):
    leave_year = _init_data_dir(tmp_path / "data")

    assert ensure_automatic_accruals(leave_year, "2026-01-24") == 2
    assert ensure_automatic_accruals(leave_year, "2026-01-24") == 0

    balances = calculate_balances(leave_year, until_date="2026-01-24")
    assert balances["annual"] == 16.0
    assert balances["sick"] == 24.0


def test_pay_period_activity_includes_accruals_usage_and_overtime(tmp_path: Path):
    leave_year = _init_data_dir(tmp_path / "data")
    ensure_automatic_accruals(leave_year, "2026-01-24")
    leave_year["transactions"].extend(
        [
            {
                "id": "20260113-001",
                "date": "2026-01-13",
                "category": "annual",
                "direction": "used",
                "hours": 2.0,
                "status": "approved",
                "source": "manual",
            },
            {
                "id": "20260114-001",
                "date": "2026-01-14",
                "category": "overtime",
                "direction": "worked",
                "hours": 3.5,
                "status": "worked",
                "source": "manual",
            },
        ]
    )

    activity = calculate_pay_period_activity(leave_year, "2026-01-15")
    assert activity["pay_period"]["pay_period_number"] == 1
    assert activity["earned"]["annual"] == 6.0
    assert activity["used"]["annual"] == 2.0
    assert activity["earned"]["sick"] == 4.0
    assert activity["worked"]["overtime"] == 3.5


def test_balance_command_posts_accruals_as_of_date(tmp_path: Path):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)

    balance(year=2026, as_of="2026-01-24", data_dir=data_dir)

    leave_year = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    auto_accruals = [tx for tx in leave_year["transactions"] if tx.get("source") == "auto_accrual"]
    assert len(auto_accruals) == 2


def test_pay_period_command_posts_and_reports_period(tmp_path: Path):
    data_dir = tmp_path / "data"
    leave_year = _init_data_dir(data_dir)
    leave_year["transactions"].append(
        {
            "id": "20260114-001",
            "date": "2026-01-14",
            "category": "overtime",
            "direction": "worked",
            "hours": 2.0,
            "status": "worked",
            "source": "manual",
        }
    )
    write_json(data_dir / "leave_years" / "2026.json", leave_year)

    pay_period_summary(year=2026, date="2026-01-20", data_dir=data_dir)

    updated = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    auto_accruals = [tx for tx in updated["transactions"] if tx.get("source") == "auto_accrual"]
    assert len(auto_accruals) == 2


def test_pay_period_command_with_daily_keeps_accruals_and_daily_activity(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    leave_year = _init_data_dir(data_dir)
    leave_year["transactions"].append(
        {
            "id": "20260113-001",
            "date": "2026-01-13",
            "category": "annual",
            "direction": "used",
            "hours": 2.0,
            "status": "approved",
            "source": "manual",
        }
    )
    write_json(data_dir / "leave_years" / "2026.json", leave_year)

    pay_period_summary(year=2026, date="2026-01-20", daily=True, data_dir=data_dir)

    output = capsys.readouterr().out
    assert "Daily activity:" in output
    assert "2026-01-13:" in output
    assert "Balances at end of pay period 1:" in output


def test_pay_periods_summary_posts_accruals_for_all_periods(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)

    pay_periods_summary(year=2026, data_dir=data_dir)

    output = capsys.readouterr().out
    assert "Pay period summary for 2026:" in output
    assert "Pay period 1" in output
    assert "Pay period 26" in output

    updated = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    auto_accruals = [tx for tx in updated["transactions"] if tx.get("source") == "auto_accrual"]
    assert len(auto_accruals) == 52
