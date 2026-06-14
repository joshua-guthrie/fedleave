from pathlib import Path
import tempfile

from fedleave.config import init_config, get_default_data_dir


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
