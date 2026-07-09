from pathlib import Path
import json

from fedleave.cli import accrual_change, balance, pay_period_summary, pay_periods_summary
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


def _init_four_hour_annual_data_dir(data_dir: Path) -> dict:
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=4.0,
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

    assert ensure_automatic_accruals(leave_year, "2026-01-24") == 0
    assert ensure_automatic_accruals(leave_year, "2026-01-24") == 0

    balances = calculate_balances(leave_year, until_date="2026-01-24")
    assert balances["annual"] == 16.0
    assert balances["sick"] == 24.0


def test_init_posts_full_year_automatic_annual_and_sick_accruals(tmp_path: Path):
    leave_year = _init_data_dir(tmp_path / "data")

    auto_accruals = [tx for tx in leave_year["transactions"] if tx.get("source") == "auto_accrual"]
    assert len(auto_accruals) == 52
    assert sum(1 for tx in auto_accruals if tx["category"] == "annual") == 26
    assert sum(1 for tx in auto_accruals if tx["category"] == "sick") == 26
    assert auto_accruals[0]["date"] == "2026-01-24"
    assert auto_accruals[-1]["date"] == "2027-01-09"


def test_accrual_change_updates_future_automatic_annual_accruals(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_four_hour_annual_data_dir(data_dir)
    capsys.readouterr()

    accrual_change(
        year=2026,
        as_of="2026-07-12",
        category="annual",
        hours=6.0,
        reason="15-year service accrual",
        json_output=True,
        data_dir=data_dir,
    )
    result = json.loads(capsys.readouterr().out)
    assert result["action"] == "accrual_changed"
    assert result["previous_hours_per_pay_period"] == 4.0
    assert result["new_hours_per_pay_period"] == 6.0
    assert result["updated_auto_accrual_transactions"] == 13

    leave_year = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    assert leave_year["accrual_rate_changes"] == [
        {
            "category": "annual",
            "effective_date": "2026-07-12",
            "hours_per_pay_period": 6.0,
            "reason": "15-year service accrual",
        }
    ]
    annual_accruals = {
        tx["date"]: tx["hours"]
        for tx in leave_year["transactions"]
        if tx.get("source") == "auto_accrual" and tx.get("category") == "annual"
    }
    assert annual_accruals["2026-07-11"] == 4.0
    assert annual_accruals["2026-07-25"] == 6.0
    assert annual_accruals["2027-01-09"] == 6.0
    assert calculate_balances(leave_year, until_date="2027-01-09")["annual"] == 140.0


def test_accrual_change_backfills_missing_future_rows_with_changed_rate(tmp_path: Path):
    leave_year = _init_four_hour_annual_data_dir(tmp_path / "data")
    leave_year["accrual_rate_changes"] = [
        {
            "category": "annual",
            "effective_date": "2026-07-12",
            "hours_per_pay_period": 6.0,
            "reason": "15-year service accrual",
        }
    ]
    leave_year["transactions"] = [
        tx
        for tx in leave_year["transactions"]
        if not (
            tx.get("source") == "auto_accrual"
            and tx.get("category") == "annual"
            and tx.get("date") >= "2026-07-12"
        )
    ]

    added = ensure_automatic_accruals(leave_year, "2027-01-09")

    assert added == 13
    annual_accruals = [
        tx
        for tx in leave_year["transactions"]
        if tx.get("source") == "auto_accrual" and tx.get("category") == "annual" and tx.get("date") >= "2026-07-12"
    ]
    assert len(annual_accruals) == 13
    assert {tx["hours"] for tx in annual_accruals} == {6.0}


def test_projected_balance_counts_future_seeded_accruals_from_query_date(tmp_path: Path):
    leave_year = _init_data_dir(tmp_path / "data")

    current_balances = calculate_balances(leave_year, until_date="2026-01-24")
    projected_balances = calculate_balances(
        leave_year,
        until_date="2026-01-24",
        include_projected=True,
        project_until=leave_year["leave_year_end"],
    )

    assert current_balances["annual"] == 16.0
    assert current_balances["sick"] == 24.0
    assert projected_balances["annual"] == 166.0
    assert projected_balances["sick"] == 124.0


def test_projected_balance_respects_custom_projection_date_with_seeded_accruals(tmp_path: Path):
    leave_year = _init_data_dir(tmp_path / "data")

    projected_balances = calculate_balances(
        leave_year,
        include_projected=True,
        project_until="2026-12-15",
    )

    assert projected_balances["annual"] == 154.0
    assert projected_balances["sick"] == 116.0


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
    assert len(auto_accruals) == 52


def test_balance_command_reports_projected_use_or_lose(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)

    balance(year=2026, project=True, use_or_lose=True, data_dir=data_dir)

    output = capsys.readouterr().out
    assert "Projected balances for 2026 as of 2027-01-09:" in output
    assert "Carryover limit: 240.00" in output
    assert "Projected annual carryover: 166.00" in output
    assert "Projected use-or-lose: 0.00" in output


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
    assert len(auto_accruals) == 52


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
