from pathlib import Path
import json

from fedleave.cli import add
from fedleave.config import init_config


def test_authoritative_add_voids_matching_transaction(tmp_path: Path):
    data_dir = tmp_path / "data"
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={"annual": 0.0, "sick": 0.0},
        data_dir=data_dir,
    )

    add(
        year=2026,
        date="2026-03-10",
        category="annual",
        earned=None,
        used=8.0,
        worked=None,
        adjusted=None,
        description="Planned leave",
        status="planned",
        source="manual",
        authoritative=False,
        data_dir=data_dir,
    )
    add(
        year=2026,
        date="2026-03-10",
        category="annual",
        earned=None,
        used=6.0,
        worked=None,
        adjusted=None,
        description="Actual leave",
        status="reconciled",
        source="manual",
        authoritative=True,
        data_dir=data_dir,
    )

    leave_year = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    annual_used = [
        tx for tx in leave_year["transactions"]
        if tx["date"] == "2026-03-10" and tx["category"] == "annual" and tx["direction"] == "used"
    ]

    assert len(annual_used) == 2
    assert annual_used[0]["void"] is True
    assert "Replaced by authoritative transaction" in annual_used[0]["void_reason"]
    assert annual_used[1]["void"] is False
    assert annual_used[1]["hours"] == 6.0
