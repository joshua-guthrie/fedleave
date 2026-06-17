from pathlib import Path
import json

from fedleave.config import init_config


def test_init_config_sanitizes_url(tmp_path: Path):
    data_dir = tmp_path / "fedleave_data"
    test_url = "https://example.com/holidays.ics"
    init_config(
        year=2026,
        leave_year_start="2026-01-11",
        annual_accrual=6.0,
        starting_balances={"annual": 0.0, "sick": 0.0, "comp": 0.0, "credit": 0.0, "travel_comp": 0.0, "time_off_award": 0.0, "religious_comp": 0.0, "restored_annual": 0.0},
        data_dir=data_dir,
        holiday_source="python_holidays",
        holiday_ics_url=test_url,
    )

    cfg = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg.get("holidays", {}).get("ics_url") == test_url
