from pathlib import Path

from fedleave.config import init_config
from fedleave.ledger import create_transaction, add_transaction_to_leave_year
from fedleave.storage import write_json
from fedleave.cli import void


def test_void_marks_transaction(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 120.0,
            "sick": 180.0,
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
    leave_year = __import__('json').loads(year_file.read_text())
    t = create_transaction(date="2026-04-01", category="annual", direction="used", hours=2.0, existing_ids=[])
    add_transaction_to_leave_year(leave_year, t)
    write_json(year_file, leave_year)

    # void it
    void(id=t.id, reason="test void", data_dir=data_dir)

    ly2 = __import__('json').loads(year_file.read_text())
    found = next(x for x in ly2['transactions'] if x['id'] == t.id)
    assert found['void'] is True
    assert 'test void' in (found.get('void_reason') or '')
