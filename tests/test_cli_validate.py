from pathlib import Path
import json
import pytest

from fedleave.cli import validate


def test_validate_applies_fixes(tmp_path: Path):
    data_dir = tmp_path / "data"
    ly_dir = data_dir / "leave_years"
    ly_dir.mkdir(parents=True)
    bad = {
        "starting_balances": {"annual": 10.0},
        "transactions": [{"date": "2026-1-11", "category": "annual", "direction": "used", "hours": 4.0}],
    }
    (ly_dir / "2026.json").write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(SystemExit):
        # calling CLI command function directly; validate raises Typer Exit
        validate(data_dir=data_dir, apply=True)

    # file should be updated with normalized date
    updated = json.loads((ly_dir / "2026.json").read_text(encoding="utf-8"))
    assert updated["transactions"][0]["date"] == "2026-01-11"
