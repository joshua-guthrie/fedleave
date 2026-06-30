import json
from pathlib import Path

import pytest
import typer

from fedleave.cli import starting_balance_set
from fedleave.config import init_config


def _init_data_dir(data_dir: Path) -> Path:
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
    return data_dir / "leave_years" / "2026.json"


def test_starting_balance_set_updates_balance_carryover_and_history(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)

    starting_balance_set(
        year=2026,
        category="annual",
        hours=193.6,
        reason="Corrected imported starting balance",
        data_dir=data_dir,
    )

    leave_year = json.loads(year_file.read_text(encoding="utf-8"))
    assert leave_year["starting_balances"]["annual"] == 193.6
    assert leave_year["carryover_from_previous_year"]["annual"] == 193.6

    history = leave_year["starting_balance_history"]
    assert len(history) == 1
    assert history[0]["category"] == "annual"
    assert history[0]["old_hours"] == 120.0
    assert history[0]["new_hours"] == 193.6
    assert history[0]["reason"] == "Corrected imported starting balance"
    assert history[0]["carryover_updated"] is True

    output = capsys.readouterr().out
    assert "Set annual starting balance for 2026: 120.00 -> 193.60" in output
    assert "Recorded starting balance audit history entry" in output


def test_starting_balance_set_preserves_manual_carryover_override(tmp_path: Path):
    data_dir = tmp_path / "data"
    year_file = _init_data_dir(data_dir)
    leave_year = json.loads(year_file.read_text(encoding="utf-8"))
    leave_year["carryover_from_previous_year"]["annual"] = 100.0
    year_file.write_text(json.dumps(leave_year), encoding="utf-8")

    starting_balance_set(
        year=2026,
        category="annual",
        hours=193.6,
        reason="Corrected imported starting balance",
        data_dir=data_dir,
    )

    updated = json.loads(year_file.read_text(encoding="utf-8"))
    assert updated["starting_balances"]["annual"] == 193.6
    assert updated["carryover_from_previous_year"]["annual"] == 100.0
    assert updated["starting_balance_history"][0]["carryover_updated"] is False


def test_starting_balance_set_rejects_invalid_category(tmp_path: Path):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)

    with pytest.raises(typer.Exit) as excinfo:
        starting_balance_set(
            year=2026,
            category="bogus",
            hours=1.0,
            reason="Invalid category",
            data_dir=data_dir,
        )

    assert excinfo.value.exit_code == 2
