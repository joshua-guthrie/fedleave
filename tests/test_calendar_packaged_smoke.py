"""Exercise the Calendar entry point against a real CLI and isolated datastore."""

import hashlib
import os
import subprocess
import sysconfig
from datetime import date
from pathlib import Path

from fedleave_gui.app import main


def test_calendar_smoke_renders_real_cli_snapshot_without_writing(qapp, tmp_path, monkeypatch):
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    data = tmp_path / "isolated data"
    year = date.today().year
    subprocess.run(
        [
            str(backend),
            "init",
            "--year",
            str(year),
            "--leave-year-start",
            f"{year}-01-01",
            "--pay-periods",
            "27",
            "--data-dir",
            str(data),
            "--json",
        ],
        check=True,
        capture_output=True,
    )

    def hashes():
        return {
            str(path.relative_to(data)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in data.rglob("*")
            if path.is_file()
        }

    before = hashes()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert main(["--smoke-test", "--backend", str(backend), "--data-dir", str(data)]) == 0
    assert hashes() == before
