from __future__ import annotations

import json
from pathlib import Path

from fedleave.commands.forced_balance import force_balance
from fedleave.config import init_config
from fedleave.ledger import calculate_balances


def _init(data_dir: Path) -> None:
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=0,
        starting_balances={
            "annual": 20.0,
            "sick": 0.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        data_dir=data_dir,
    )


def test_force_balance_records_auditable_decrease_and_applies_forward(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _init(data_dir)

    force_balance(
        date="2026-02-01",
        category="annual",
        hours=5.0,
        comment="Corrected to official payroll balance",
        json_output=False,
        data_dir=data_dir,
    )

    payload = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    forced = [tx for tx in payload["transactions"] if tx.get("source") == "forced-balance"]
    assert len(forced) == 1
    assert forced[0]["direction"] == "forced_decrease"
    assert forced[0]["hours"] == 15.0
    assert forced[0]["description"] == "Corrected to official payroll balance"
    assert calculate_balances(payload, until_date="2026-02-01")["annual"] == 5.0
    assert calculate_balances(payload, until_date="2026-12-01")["annual"] == 5.0


def test_reapplying_force_balance_replaces_same_day_adjustment(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _init(data_dir)
    force_balance(date="2026-02-01", category="annual", hours=5, comment="first", data_dir=data_dir)
    force_balance(date="2026-02-01", category="annual", hours=8, comment="revised", data_dir=data_dir)

    payload = json.loads((data_dir / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    forced = [tx for tx in payload["transactions"] if tx.get("source") == "forced-balance"]
    assert len(forced) == 1
    assert forced[0]["description"] == "revised"
    assert calculate_balances(payload, until_date="2026-02-01")["annual"] == 8.0
