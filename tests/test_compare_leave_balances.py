from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import date
from pathlib import Path


def _install_chart_import_stubs(monkeypatch) -> None:
    pil_module = types.ModuleType("PIL")
    image_module = types.ModuleType("PIL.Image")
    image_draw_module = types.ModuleType("PIL.ImageDraw")
    image_font_module = types.ModuleType("PIL.ImageFont")

    class _DummyFont:
        pass

    def _truetype(*args, **kwargs):
        return _DummyFont()

    image_font_module.FreeTypeFont = _DummyFont
    image_font_module.ImageFont = _DummyFont
    image_font_module.truetype = _truetype

    pil_module.Image = image_module
    pil_module.ImageDraw = image_draw_module
    pil_module.ImageFont = image_font_module

    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", image_draw_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageFont", image_font_module)


def _compare_leave_balances(monkeypatch):
    _install_chart_import_stubs(monkeypatch)
    from fedleave.cli import compare_leave_balances

    return compare_leave_balances


def _write_leave_year(path: Path, *, year: int, annual_start: float, annual_transactions: list[dict], overtime_transactions: list[dict]) -> None:
    data = {
        "schema_version": 1,
        "leave_year": year,
        "leave_year_start": f"{year}-01-11",
        "leave_year_end": f"{year + 1}-01-09",
        "starting_balances": {
            "annual": annual_start,
            "sick": 0.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
            "overtime": 0.0,
        },
        "carryover_from_previous_year": {"annual": annual_start},
        "transactions": [*annual_transactions, *overtime_transactions],
        "pay_periods": [],
        "holidays": [],
        "rollover_status": {
            "rolled_from_previous_year": False,
            "rolled_to_next_year": False,
            "rollover_completed_at": None,
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_compare_leave_balances_outputs_json_for_multiple_years(tmp_path: Path, capsys, monkeypatch):
    compare_leave_balances = _compare_leave_balances(monkeypatch)
    data_dir = tmp_path / "data"
    year_dir = data_dir / "leave_years"
    year_dir.mkdir(parents=True)
    _write_leave_year(
        year_dir / "2025.json",
        year=2025,
        annual_start=100.0,
        annual_transactions=[
            {"date": "2025-06-01", "category": "annual", "direction": "used", "hours": 4.0},
            {"date": "2025-10-01", "category": "annual", "direction": "earned", "hours": 10.0},
        ],
        overtime_transactions=[{"date": "2025-06-01", "category": "overtime", "direction": "worked", "hours": 6.0}],
    )
    _write_leave_year(
        year_dir / "2026.json",
        year=2026,
        annual_start=120.0,
        annual_transactions=[{"date": "2026-06-01", "category": "annual", "direction": "earned", "hours": 6.0}],
        overtime_transactions=[{"date": "2026-06-01", "category": "overtime", "direction": "worked", "hours": 9.5}],
    )

    compare_leave_balances(category="annual", as_of="2026-07-14", json_output=True, data_dir=data_dir)

    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "annual"
    assert payload["as_of"] == "2026-07-14"
    assert payload["years"] == [2025, 2026]
    assert [point["year"] for point in payload["points"]] == [2025, 2026]
    assert payload["points"][0]["value"] == 96.0
    assert payload["points"][1]["value"] == 126.0


def test_comparison_date_for_year_clamps_february_29_on_non_leap_year(monkeypatch):
    _install_chart_import_stubs(monkeypatch)
    charting = importlib.import_module("fedleave.charting")

    assert charting.comparison_date_for_year(date(2024, 2, 29), 2025).isoformat() == "2025-02-28"


def test_compare_leave_balances_includes_overtime_worked(tmp_path: Path, capsys, monkeypatch):
    compare_leave_balances = _compare_leave_balances(monkeypatch)
    data_dir = tmp_path / "data"
    year_dir = data_dir / "leave_years"
    year_dir.mkdir(parents=True)
    _write_leave_year(
        year_dir / "2025.json",
        year=2025,
        annual_start=100.0,
        annual_transactions=[],
        overtime_transactions=[{"date": "2025-03-01", "category": "overtime", "direction": "worked", "hours": 6.0}],
    )
    _write_leave_year(
        year_dir / "2026.json",
        year=2026,
        annual_start=120.0,
        annual_transactions=[],
        overtime_transactions=[{"date": "2026-03-01", "category": "overtime", "direction": "worked", "hours": 9.5}],
    )

    compare_leave_balances(category="overtime", as_of="2026-07-14", json_output=True, data_dir=data_dir)

    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "overtime"
    assert [point["value"] for point in payload["points"]] == [6.0, 9.5]
