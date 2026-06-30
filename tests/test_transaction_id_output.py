import json
from pathlib import Path

from fedleave.cli import list_transactions
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


def _data_dir_with_transaction(tmp_path: Path) -> tuple[Path, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={"annual": 10.0},
        data_dir=data_dir,
    )

    year_file = data_dir / "leave_years" / "2026.json"
    leave_year = json.loads(year_file.read_text())
    transaction = create_transaction(
        date="2026-06-01",
        category="annual",
        direction="used",
        hours=4.0,
        existing_ids=[],
    )
    add_transaction_to_leave_year(leave_year, transaction)
    write_json(year_file, leave_year)
    return data_dir, transaction.id


def test_list_hides_transaction_id_by_default(tmp_path: Path, capsys):
    data_dir, transaction_id = _data_dir_with_transaction(tmp_path)

    list_transactions(year=2026, data_dir=data_dir)

    output = capsys.readouterr().out
    assert transaction_id not in output
    assert "2026-06-01 annual used 4.0 planned" in output


def test_list_shows_transaction_id_when_requested(tmp_path: Path, capsys):
    data_dir, transaction_id = _data_dir_with_transaction(tmp_path)

    list_transactions(year=2026, show_transaction_ids=True, data_dir=data_dir)

    output = capsys.readouterr().out
    assert transaction_id in output
    assert f"{transaction_id} 2026-06-01 annual used 4.0 planned" in output
