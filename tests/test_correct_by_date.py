"""Verify human-friendly correction lookup can be previewed without writing."""

import json
from pathlib import Path

from fedleave.cli import correct
from fedleave.config import init_config
from fedleave.ledger import add_transaction_to_leave_year, create_transaction
from fedleave.storage import write_json


def test_correct_by_date_preview(tmp_path: Path):
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
    ly = json.loads(year_file.read_text())

    tx = create_transaction(date="2026-06-01", category="annual", direction="used", hours=4.0, existing_ids=[])
    add_transaction_to_leave_year(ly, tx)
    write_json(year_file, ly)

    correct(search_date="2026-06-01", search_type="annual", hours=3.0, reason="Adjust", preview=True, data_dir=data_dir)
