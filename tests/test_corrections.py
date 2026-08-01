import json
from pathlib import Path

from fedleave.cli import correct
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


def test_correct_updates_transaction_in_place(tmp_path: Path):
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
    # add a transaction
    leave_year = json.loads(year_file.read_text())
    t = create_transaction(date="2026-03-10", category="annual", direction="used", hours=4.0, existing_ids=[])
    t.expiration_date = "2026-12-31"
    t.earned_transaction_id = "20260101-001"
    add_transaction_to_leave_year(leave_year, t)
    write_json(year_file, leave_year)

    # perform correction
    correct(id=t.id, hours=3.0, reason="Only used 3 hours", data_dir=data_dir)

    ly2 = json.loads(year_file.read_text())
    matches = [x for x in ly2["transactions"] if x["id"] == t.id]
    assert len(matches) == 1
    assert abs(matches[0]["hours"] - 3.0) < 1e-6
    assert matches[0]["description"] == "Only used 3 hours"
    assert matches[0]["expiration_date"] == "2026-12-31"
    assert matches[0]["earned_transaction_id"] == "20260101-001"
    assert "void" not in matches[0]
    assert "replaces_transaction_id" not in matches[0]
