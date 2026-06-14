from pathlib import Path

from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction, calculate_balances
from fedleave.storage import write_json
from fedleave.cli import rollover


def test_rollover_preview_and_apply(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 100.0,
            "sick": 50.0,
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
    # add a transaction to change annual balance
    t = create_transaction(date="2026-06-01", category="annual", direction="used", hours=20.0, existing_ids=[])
    add_transaction_to_leave_year(leave_year, t)
    write_json(year_file, leave_year)

    # preview
    rollover(from_year=2026, to_year=2027, preview=True, data_dir=data_dir)

    # apply
    rollover(from_year=2026, to_year=2027, preview=False, data_dir=data_dir)

    new_file = data_dir / "leave_years" / "2027.json"
    assert new_file.exists()
    new_ly = __import__('json').loads(new_file.read_text())
    # carried annual should be <= 240 and equal to remaining annual (100-20)
    assert abs(new_ly['starting_balances']['annual'] - 80.0) < 1e-6
