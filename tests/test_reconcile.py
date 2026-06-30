import json
from pathlib import Path

import pytest
import typer

from fedleave.cli import reconcile
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


def _init_data_dir(data_dir: Path) -> Path:
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 0.0,
            "sick": 0.0,
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


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reconcile_adds_transaction_and_infers_leave_year(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)

    reconcile(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=1.5,
        reason="March clocking report",
        data_dir=data_dir,
    )

    leave_year = _load(year_file)
    transactions = leave_year["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["date"] == "2026-03-10"
    assert transactions[0]["category"] == "credit"
    assert transactions[0]["direction"] == "earned"
    assert transactions[0]["hours"] == 1.5
    assert transactions[0]["status"] == "reconciled"
    assert transactions[0]["source"] == "clocking-report"
    assert transactions[0]["description"] == "March clocking report"

    output = capsys.readouterr().out
    assert "added transaction" in output
    assert "in 2026" in output


def test_reconcile_updates_single_match_and_records_history(tmp_path: Path):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    leave_year = _load(year_file)
    transaction = create_transaction(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=1.0,
        description="Original report",
        status="planned",
        source="manual",
        existing_ids=[],
    )
    add_transaction_to_leave_year(leave_year, transaction)
    write_json(year_file, leave_year)

    reconcile(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=1.5,
        reason="March clocking report",
        data_dir=data_dir,
    )

    updated = _load(year_file)
    transactions = updated["transactions"]
    assert len(transactions) == 1
    assert transactions[0]["id"] == transaction.id
    assert transactions[0]["hours"] == 1.5
    assert transactions[0]["status"] == "reconciled"
    assert transactions[0]["source"] == "clocking-report"
    assert transactions[0]["description"] == "March clocking report"

    history = transactions[0]["reconcile_history"]
    assert len(history) == 1
    assert history[0]["reason"] == "March clocking report"
    assert history[0]["old"]["hours"] == 1.0
    assert history[0]["old"]["status"] == "planned"
    assert history[0]["old"]["source"] == "manual"
    assert history[0]["old"]["description"] == "Original report"
    assert history[0]["new"]["hours"] == 1.5


def test_reconcile_blocks_multiple_active_matches(tmp_path: Path):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    leave_year = _load(year_file)
    first = create_transaction(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=1.0,
        existing_ids=[],
    )
    second = create_transaction(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=2.0,
        existing_ids=[first.id],
    )
    add_transaction_to_leave_year(leave_year, first)
    add_transaction_to_leave_year(leave_year, second)
    write_json(year_file, leave_year)

    with pytest.raises(typer.Exit) as excinfo:
        reconcile(
            date="2026-03-10",
            category="credit",
            direction="earned",
            hours=1.5,
            reason="March clocking report",
            data_dir=data_dir,
        )

    assert excinfo.value.exit_code == 2
    unchanged = _load(year_file)
    assert [transaction["hours"] for transaction in unchanged["transactions"]] == [1.0, 2.0]


def test_reconcile_updates_selected_match_and_can_emit_json(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    capsys.readouterr()
    leave_year = _load(year_file)
    first = create_transaction(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=1.0,
        existing_ids=[],
    )
    second = create_transaction(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=2.0,
        existing_ids=[first.id],
    )
    add_transaction_to_leave_year(leave_year, first)
    add_transaction_to_leave_year(leave_year, second)
    write_json(year_file, leave_year)

    reconcile(
        date="2026-03-10",
        category="credit",
        direction="earned",
        hours=1.5,
        reason="March clocking report",
        id=second.id,
        json_output=True,
        data_dir=data_dir,
    )

    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "updated"
    assert output["transaction_id"] == second.id
    assert output["year"] == 2026

    updated = _load(year_file)
    assert updated["transactions"][0]["hours"] == 1.0
    assert updated["transactions"][1]["hours"] == 1.5
