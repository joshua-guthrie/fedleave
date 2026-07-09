import json
from pathlib import Path

from fedleave.cli import set_day
from fedleave.config import init_config
from fedleave.storage import load_json


def _init_data_dir(data_dir: Path) -> Path:
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={"annual": 120.0, "sick": 180.0},
        data_dir=data_dir,
    )
    return data_dir / "leave_years" / "2026.json"


def _json_output(capsys):
    return json.loads(capsys.readouterr().out)


def test_set_day_authoritatively_replaces_supplied_categories(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    capsys.readouterr()

    set_day(
        date="2026-07-08",
        authoritative=True,
        json_output=True,
        annual=-5.0,
        credit=2.0,
        data_dir=data_dir,
    )
    first = _json_output(capsys)
    assert first["action"] == "set-day"
    assert len(first["created_transaction_ids"]) == 2

    set_day(
        date="2026-07-08",
        authoritative=True,
        json_output=True,
        annual=-3.0,
        credit=0.0,
        data_dir=data_dir,
    )
    second = _json_output(capsys)
    assert len(second["voided_transaction_ids"]) == 2
    assert len(second["created_transaction_ids"]) == 1

    leave_year = load_json(year_file)
    active = [transaction for transaction in leave_year["transactions"] if not transaction.get("void")]
    manual = [transaction for transaction in active if transaction.get("source") == "set-day"]
    assert len(manual) == 1
    assert manual[0]["category"] == "annual"
    assert manual[0]["direction"] == "used"
    assert manual[0]["hours"] == 3.0
