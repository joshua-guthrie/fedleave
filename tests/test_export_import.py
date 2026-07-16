from pathlib import Path
import json

import pytest
import typer

from fedleave.cli import export_data, import_data
from fedleave.config import init_config


def _init_data_dir(data_dir: Path) -> None:
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


def test_export_import_round_trip(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    archive = tmp_path / "backup.json"
    _init_data_dir(source)

    export_data(output=archive, data_dir=source)
    import_data(input=archive, data_dir=target)

    assert json.loads((target / "config.json").read_text(encoding="utf-8")) == json.loads(
        (source / "config.json").read_text(encoding="utf-8")
    )
    assert json.loads((target / "leave_years" / "2026.json").read_text(encoding="utf-8")) == json.loads(
        (source / "leave_years" / "2026.json").read_text(encoding="utf-8")
    )
    assert (target / "holiday_cache" / "federal_holidays_2026.json").exists()


def test_import_refuses_overwrite_without_flag(tmp_path: Path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    archive = tmp_path / "backup.json"
    _init_data_dir(source)
    _init_data_dir(target)
    export_data(output=archive, data_dir=source)

    with pytest.raises(typer.Exit):
        import_data(input=archive, data_dir=target)


def test_import_accepts_single_leave_year_backup(tmp_path: Path):
    target = tmp_path / "target"
    archive = tmp_path / "single-leave-year-backup.json"
    legacy_leave_year = {
        "schema_version": 1,
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "pay_period_count": 1,
        "annual_leave_accrual_hours": 6.0,
        "sick_leave_accrual_hours": 4.0,
        "starting_balances": {"annual": 120.0, "sick": 180.0},
        "carryover_from_previous_year": {"annual": 120.0, "sick": 180.0},
        "transactions": [
            {
                "id": "20260124-001",
                "date": "2026-01-24",
                "category": "annual",
                "direction": "earned",
                "hours": 6.0,
                "description": "Automatic annual leave accrual",
                "status": "reconciled",
                "source": "auto_accrual",
            }
        ],
        "pay_periods": [
            {
                "pay_period_number": 1,
                "start_date": "2026-01-11",
                "end_date": "2026-01-24",
                "accrual_date": "2026-01-24",
            }
        ],
        "holidays": [],
    }
    archive.write_text(json.dumps(legacy_leave_year), encoding="utf-8")

    import_data(input=archive, data_dir=target)

    imported = json.loads((target / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    assert imported == legacy_leave_year
    assert not (target / "config.json").exists()


def test_import_removes_legacy_transaction_history(tmp_path: Path):
    target = tmp_path / "target"
    archive = tmp_path / "legacy.json"
    legacy = {
        "schema_version": 1,
        "leave_year": 2026,
        "transactions": [
            {"id": "active", "void": False, "void_reason": None, "reconcile_history": []},
            {"id": "obsolete", "void": True, "void_reason": "replaced"},
        ],
        "starting_balance_history": [{"old_hours": 100.0, "new_hours": 120.0}],
        "pay_periods": [],
    }
    archive.write_text(json.dumps(legacy), encoding="utf-8")

    import_data(input=archive, data_dir=target)

    imported = json.loads((target / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    assert imported["transactions"] == [{"id": "active"}]
    assert "starting_balance_history" not in imported


def test_import_preserves_existing_current_year_file(tmp_path: Path):
    target = tmp_path / "target"
    archive = tmp_path / "previous-year.json"
    current_year = {
        "schema_version": 1,
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "pay_period_count": 1,
        "annual_leave_accrual_hours": 6.0,
        "sick_leave_accrual_hours": 4.0,
        "starting_balances": {"annual": 120.0, "sick": 180.0},
        "carryover_from_previous_year": {"annual": 120.0, "sick": 180.0},
        "transactions": [],
        "pay_periods": [],
        "holidays": [],
    }
    previous_year = {
        "schema_version": 1,
        "leave_year": 2025,
        "leave_year_start": "2025-01-12",
        "leave_year_end": "2026-01-10",
        "pay_period_count": 1,
        "annual_leave_accrual_hours": 6.0,
        "sick_leave_accrual_hours": 4.0,
        "starting_balances": {"annual": 100.0, "sick": 160.0},
        "carryover_from_previous_year": {"annual": 100.0, "sick": 160.0},
        "transactions": [],
        "pay_periods": [],
        "holidays": [],
    }
    target_years = target / "leave_years"
    target_years.mkdir(parents=True)
    (target_years / "2026.json").write_text(json.dumps(current_year), encoding="utf-8")
    archive.write_text(json.dumps({"schema_version": 1, "leave_years": {"2025": previous_year}, "holiday_cache": {}}), encoding="utf-8")

    import_data(input=archive, data_dir=target)

    assert json.loads((target / "leave_years" / "2026.json").read_text(encoding="utf-8")) == current_year
    assert json.loads((target / "leave_years" / "2025.json").read_text(encoding="utf-8")) == previous_year


def test_import_validates_the_entire_archive_before_writing(tmp_path: Path):
    target = tmp_path / "target"
    archive = tmp_path / "invalid.json"
    archive.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "config": {"schema_version": 1, "user": {"display_name": "Imported"}},
                "leave_years": {
                    "2026": {
                        "schema_version": 1,
                        "leave_year": 2026,
                        "leave_year_start": "2026-01-11",
                        "leave_year_end": "2027-01-09",
                        "pay_period_count": 1,
                        "annual_leave_accrual_hours": 6.0,
                        "sick_leave_accrual_hours": 4.0,
                        "starting_balances": {"annual": 0.0, "sick": 0.0},
                        "carryover_from_previous_year": {"annual": 0.0, "sick": 0.0},
                        "transactions": [],
                        "pay_periods": [],
                        "holidays": [],
                    }
                },
                "holiday_cache": {
                    "bad/name": {"year": 2026}
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(typer.Exit) as excinfo:
        import_data(input=archive, data_dir=target)

    assert excinfo.value.exit_code == 2
    assert not target.exists()
