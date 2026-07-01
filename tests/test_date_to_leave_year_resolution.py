import json
from pathlib import Path

from fedleave.cli import add, correct
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


def test_add_inferrs_leave_year_from_date(tmp_path: Path):
    data_dir = tmp_path / "data"
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

    add(
        year=None,
        date="2026-03-10",
        category="credit",
        earned=None,
        used=None,
        worked=None,
        adjusted=1.5,
        description="Clocking import",
        status="planned",
        source="manual",
        authoritative=False,
        json_output=False,
        show_transaction_ids=False,
        data_dir=data_dir,
    )

    leave_year = json.loads((data_dir / "leave_years" / "2026.json").read_text())
    assert len(leave_year["transactions"]) == 1
    assert leave_year["transactions"][0]["date"] == "2026-03-10"
    assert leave_year["transactions"][0]["hours"] == 1.5


def test_correct_infers_leave_year_from_search_date(tmp_path: Path):
    data_dir = tmp_path / "data"
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

    year_file = data_dir / "leave_years" / "2026.json"
    leave_year = json.loads(year_file.read_text())
    tx = create_transaction(date="2026-06-01", category="annual", direction="used", hours=4.0, existing_ids=[])
    add_transaction_to_leave_year(leave_year, tx)
    write_json(year_file, leave_year)

    correct(
        search_date="2026-06-01",
        search_type="annual",
        hours=3.0,
        reason="Adjust",
        preview=True,
        data_dir=data_dir,
    )
