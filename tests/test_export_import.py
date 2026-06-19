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
