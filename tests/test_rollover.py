from pathlib import Path

from fedleave.cli import rollover
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


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
    leave_year = __import__("json").loads(year_file.read_text())
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
    new_ly = __import__("json").loads(new_file.read_text())
    # carried annual includes init-seeded accruals and remains capped by the carryover limit
    assert abs(new_ly["starting_balances"]["annual"] - 236.0) < 1e-6
    assert abs(new_ly["starting_balances"]["sick"] - 154.0) < 1e-6


def test_rollover_preserves_expiring_leave_as_individual_lots(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=0,
        starting_balances={
            "annual": 0,
            "sick": 0,
            "comp": 0,
            "credit": 0,
            "travel_comp": 0,
            "time_off_award": 0,
            "religious_comp": 0,
            "restored_annual": 0,
        },
        data_dir=data_dir,
    )
    source_path = data_dir / "leave_years" / "2026.json"
    source = __import__("json").loads(source_path.read_text())
    lot = create_transaction(
        date="2026-09-01",
        category="travel_comp",
        direction="earned",
        hours=8,
        status="reconciled",
        existing_ids=[tx["id"] for tx in source["transactions"]],
    )
    add_transaction_to_leave_year(source, lot)
    write_json(source_path, source)

    rollover(from_year=2026, to_year=2027, preview=False, data_dir=data_dir)

    target = __import__("json").loads((data_dir / "leave_years" / "2027.json").read_text())
    carried = [tx for tx in target["transactions"] if tx.get("source") == "expiration-rollover"]
    assert len(carried) == 1
    assert carried[0]["hours"] == 8
    assert carried[0]["expiration_date"]
    assert carried[0]["original_earned_date"] == "2026-09-01"
    source_after = __import__("json").loads(source_path.read_text())
    original = next(tx for tx in source_after["transactions"] if tx["id"] == lot.id)
    assert original["rolled_over_to_transaction_id"] == carried[0]["id"]
