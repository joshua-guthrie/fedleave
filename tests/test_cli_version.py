import json
import sys

from typer.testing import CliRunner

from fedleave import __version__
from fedleave.cli import app


def test_version_option_reports_package_version():
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"fedleave {__version__}"


def test_cli_startup_removes_legacy_history_from_default_store(tmp_path, monkeypatch):
    data_dir = tmp_path / "xdg" / "fedleave"
    year_dir = data_dir / "leave_years"
    year_dir.mkdir(parents=True)
    year_file = year_dir / "2026.json"
    year_file.write_text(
        json.dumps(
            {
                "starting_balance_history": [{"old_hours": 1.0}],
                "transactions": [
                    {"id": "active", "void": False, "void_reason": None},
                    {"id": "obsolete", "void": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    if sys.platform.startswith("win"):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "xdg"))
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    result = CliRunner().invoke(app, ["types"])

    assert result.exit_code == 0
    migrated = json.loads(year_file.read_text(encoding="utf-8"))
    assert migrated["transactions"] == [{"id": "active"}]
    assert "starting_balance_history" not in migrated
