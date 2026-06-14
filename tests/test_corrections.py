from pathlib import Path
import tempfile

from fedleave.config import init_config
from fedleave.ledger import create_transaction, add_transaction_to_leave_year
from fedleave.storage import write_json
from fedleave.cli import correct, list_transactions


def test_correct_creates_replacement(tmp_path: Path):
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
    ly = year_file.read_text()

    # add a transaction
    leave_year = __import__('json').loads(year_file.read_text())
    t = create_transaction(date="2026-03-10", category="annual", direction="used", hours=4.0, existing_ids=[])
    add_transaction_to_leave_year(leave_year, t)
    write_json(year_file, leave_year)

    # perform correction
    correct(id=t.id, hours=3.0, reason="Only used 3 hours", data_dir=data_dir)

    ly2 = __import__('json').loads(year_file.read_text())
    # original should be void
    orig = next(x for x in ly2['transactions'] if x['id'] == t.id)
    assert orig['void'] is True
    # replacement exists
    repls = [x for x in ly2['transactions'] if x.get('replaces_transaction_id') == t.id]
    assert len(repls) == 1
    assert abs(repls[0]['hours'] - 3.0) < 1e-6
