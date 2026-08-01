import json
from pathlib import Path

from fedleave.config import init_config
from fedleave.storage import write_json


def test_init_creates_config_and_leave_year(tmp_path: Path):
    data_dir = tmp_path / "fedleave_data"
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

    assert (data_dir / "config.json").exists()
    assert (data_dir / "leave_years" / "2026.json").exists()
    assert (data_dir / "holiday_cache" / "federal_holidays_2026.json").exists()


def test_init_repairs_missing_files_without_overwriting_existing_config(tmp_path: Path):
    data_dir = tmp_path / "fedleave_data"
    (data_dir / "leave_years").mkdir(parents=True)
    (data_dir / "holiday_cache").mkdir(parents=True)
    existing_config = {"schema_version": 1, "user": {"display_name": "Existing User", "timezone": "UTC"}}
    write_json(data_dir / "config.json", existing_config)

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

    cfg = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg["user"]["display_name"] == "Existing User"
    assert (data_dir / "leave_years" / "2026.json").exists()
    assert (data_dir / "holiday_cache" / "federal_holidays_2026.json").exists()
