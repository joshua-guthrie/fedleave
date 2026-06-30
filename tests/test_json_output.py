import json
from pathlib import Path

import pytest

from fedleave.cli import (
    add,
    balance,
    correct,
    daily_activity,
    pay_period_summary,
    pay_periods_summary,
    rollover,
    validate,
    void,
)
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


def _init_data_dir(data_dir: Path) -> Path:
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
    return data_dir / "leave_years" / "2026.json"


def _json_output(capsys):
    return json.loads(capsys.readouterr().out)


def test_add_balance_and_activity_emit_json(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)
    capsys.readouterr()

    add(
        year=2026,
        date="2026-03-10",
        category="annual",
        earned=None,
        used=4.0,
        worked=None,
        adjusted=None,
        description="Medical appointment",
        json_output=True,
        data_dir=data_dir,
    )
    added = _json_output(capsys)
    assert added["action"] == "added"
    assert added["transaction_id"] == "20260310-001"
    assert added["replaced_transaction_ids"] == []

    balance(year=2026, as_of="2026-03-10", json_output=True, data_dir=data_dir)
    balances = _json_output(capsys)
    assert balances["year"] == 2026
    assert balances["balances"]["annual"] == 30.0
    assert balances["automatic_accruals_posted"] == 8

    daily_activity(year=2026, date="2026-03-10", json_output=True, data_dir=data_dir)
    activity = _json_output(capsys)
    assert activity["has_activity"] is True
    assert activity["activity"]["used"]["annual"] == 4.0


def test_correct_and_void_emit_json(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    leave_year = json.loads(year_file.read_text(encoding="utf-8"))
    transaction = create_transaction(
        date="2026-03-10",
        category="annual",
        direction="used",
        hours=4.0,
        existing_ids=[],
    )
    add_transaction_to_leave_year(leave_year, transaction)
    write_json(year_file, leave_year)
    capsys.readouterr()

    correct(id=transaction.id, hours=3.0, reason="Actual use", json_output=True, data_dir=data_dir)
    corrected = _json_output(capsys)
    assert corrected["action"] == "corrected"
    assert corrected["voided_transaction_ids"] == [transaction.id]
    replacement_id = corrected["replacement_transaction_id"]

    void(id=replacement_id, reason="Entered in error", json_output=True, data_dir=data_dir)
    voided = _json_output(capsys)
    assert voided["action"] == "voided"
    assert voided["voided_transaction_ids"] == [replacement_id]


def test_pay_period_commands_emit_json(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)
    capsys.readouterr()

    pay_period_summary(year=2026, date="2026-01-20", daily=True, json_output=True, data_dir=data_dir)
    period = _json_output(capsys)
    assert period["pay_period"]["pay_period_number"] == 1
    assert period["automatic_accruals_posted"] == 2
    assert period["daily_activity"] is not None

    pay_periods_summary(year=2026, json_output=True, data_dir=data_dir)
    periods = _json_output(capsys)
    assert periods["year"] == 2026
    assert len(periods["pay_periods"]) == 26
    assert periods["automatic_accruals_posted"] == 50


def test_validate_and_rollover_emit_json(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)
    capsys.readouterr()

    validate(json_output=True, data_dir=data_dir)
    validation = _json_output(capsys)
    assert validation["ok"] is True
    assert validation["results"][0]["ok"] is True

    rollover(from_year=2026, to_year=2027, preview=True, json_output=True, data_dir=data_dir)
    preview = _json_output(capsys)
    assert preview["action"] == "preview"
    assert preview["from_year"] == 2026
    assert preview["to_year"] == 2027


def test_validate_json_reports_issues_without_prompting(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    leave_year = json.loads(year_file.read_text(encoding="utf-8"))
    leave_year["transactions"].append(
        {
            "id": "bad-001",
            "date": "2026-3-10",
            "category": "annual",
            "direction": "used",
            "hours": 1.0,
        }
    )
    year_file.write_text(json.dumps(leave_year), encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as excinfo:
        validate(json_output=True, data_dir=data_dir)

    assert excinfo.value.code == 2
    validation = _json_output(capsys)
    assert validation["ok"] is False
    assert validation["results"][0]["issues"]
