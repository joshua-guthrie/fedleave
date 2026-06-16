from pathlib import Path

from fedleave.config import init_config
from fedleave.ledger import create_transaction, add_transaction_to_leave_year
from fedleave.storage import write_json
from fedleave.cli import rollover


def test_rollover_respects_carryover_limit(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 50.0,
            "sick": 10.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        data_dir=data_dir,
    )

    # reduce balance slightly
    year_file = data_dir / "leave_years" / "2026.json"
    ly = __import__("json").loads(year_file.read_text())
    t = create_transaction(date="2026-06-01", category="annual", direction="used", hours=5.0, existing_ids=[])
    add_transaction_to_leave_year(ly, t)
    write_json(year_file, ly)

    # set carryover limit in config
    cfg = __import__("json").loads((data_dir / "config.json").read_text())
    cfg.setdefault("rules", {}).setdefault("annual", {})["carryover_limit_hours"] = 10.0
    write_json(data_dir / "config.json", cfg)

    rollover(from_year=2026, to_year=2027, preview=False, data_dir=data_dir)

    new_file = data_dir / "leave_years" / "2027.json"
    assert new_file.exists()
    new_ly = __import__("json").loads(new_file.read_text())
    assert abs(new_ly["starting_balances"]["annual"] - 10.0) < 1e-6
    # verify starting-balance transaction created
    txs = new_ly.get("transactions", [])
    assert any(tx.get("category") == "annual" and tx.get("direction") == "starting_balance" and abs(tx.get("hours", 0) - 10.0) < 1e-6 for tx in txs)
