"""Verify CLI validation applies safe canonicalization fixes to stored data."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
        # Direct command-function calls expose Typer's requested exit as the
        # ``SystemExit`` raised by its public exception boundary.
        validate(data_dir=data_dir, apply=True)

    updated = json.loads((ly_dir / "2026.json").read_text(encoding="utf-8"))
    assert updated["transactions"][0]["date"] == "2026-01-11"


@pytest.mark.parametrize("interactive", [False, True])
def test_validate_prompts_only_with_interactive_input(tmp_path, monkeypatch, interactive):
    year_dir = tmp_path / "leave_years"
    year_dir.mkdir()
    path = year_dir / "2026.json"
    path.write_text(
        json.dumps(
            {
                "starting_balances": {"annual": 10},
                "transactions": [{"date": "2026-1-11", "category": "annual", "direction": "used", "hours": 4}],
            }
        )
    )
    prompts = []
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: interactive))

    def confirm(message):
        prompts.append(message)
        return True

    monkeypatch.setattr("typer.confirm", confirm)
    with pytest.raises(SystemExit) as result:
        validate(data_dir=tmp_path, apply=False, json_output=False)
    assert result.value.code == 2
    assert bool(prompts) == interactive
    assert json.loads(path.read_text())["transactions"][0]["date"] == ("2026-01-11" if interactive else "2026-1-11")
