import json
from pathlib import Path

from fedleave.cli import add, month
from fedleave.config import init_config


def _init_data_dir(data_dir: Path) -> None:
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={
            "annual": 10.0,
            "sick": 20.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        data_dir=data_dir,
    )


def _json_output(capsys):
    return json.loads(capsys.readouterr().out)


def test_month_command_emits_calendar_json(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    _init_data_dir(data_dir)
    capsys.readouterr()

    add(
        year=2026,
        date="2026-07-01",
        category="credit",
        earned=3.0,
        used=None,
        worked=None,
        adjusted=None,
        description="Stayed late",
        status="planned",
        source="manual",
        data_dir=data_dir,
    )
    add(
        year=2026,
        date="2026-07-01",
        category="annual",
        earned=None,
        used=2.0,
        worked=None,
        adjusted=None,
        description="Appointment",
        status="planned",
        source="manual",
        data_dir=data_dir,
    )
    capsys.readouterr()

    month(year=2026, month=7, json_output=True, data_dir=data_dir)
    result = _json_output(capsys)

    assert result["year"] == 2026
    assert result["month"] == 7
    assert result["month_start"] == "2026-07-01"
    assert result["month_end"] == "2026-07-31"
    assert result["calendar_start"] == "2026-06-28"
    assert result["calendar_end"] == "2026-08-01"
    assert result["automatic_accruals_posted"] > 0

    july_first = next(day for day in result["days"] if day["date"] == "2026-07-01")
    assert july_first["in_display_month"] is True
    assert "holiday_name" in july_first
    assert july_first["entries"] == [
        {
            "id": "20260701-001",
            "category": "credit",
            "direction": "earned",
            "hours": 3.0,
            "status": "planned",
            "source": "manual",
            "description": "Stayed late",
        },
        {
            "id": "20260701-002",
            "category": "annual",
            "direction": "used",
            "hours": 2.0,
            "status": "planned",
            "source": "manual",
            "description": "Appointment",
        },
    ]
    assert july_first["display_lines"] == ["Cr +3.0", "A -2.0"]

    assert len(result["days"]) == 35
    assert any(day["date"] == "2026-06-28" and not day["in_display_month"] for day in result["days"])
    assert any(period["touches_display_month"] for period in result["pay_periods"])
    assert all({"number", "start", "end", "pay_date", "totals"} <= set(period) for period in result["pay_periods"])
    assert any(period["end"] == "2026-07-11" and period["pay_date"] == "2026-07-17" for period in result["pay_periods"])
