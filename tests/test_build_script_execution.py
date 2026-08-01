"""Smoke-test both platform launch paths without building full binaries."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "lib" / "common" / "installer_engine.py"
WINDOWS_INSTALLER = ROOT / "scripts" / "WindowsInstall.bat"


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"No JSON result in output:\n{stdout}")


@pytest.mark.skipif(os.name == "nt", reason="The Linux shell launcher is executable only on POSIX hosts")
def test_linux_build_script_executes_smoke_test_without_error(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["FEDLEAVE_BUILD_ROOT"] = str(tmp_path / "build")
    env["FEDLEAVE_BUILD_VERSION"] = "0.2.1.dev0+g12345678"
    env["FEDLEAVE_SOURCE_COMMIT"] = "1234567890abcdef1234567890abcdef12345678"
    result = subprocess.run(
        [str(ROOT / "scripts" / "LinuxInstall.sh"), "--unattended", "--smoke-test", "--keep-build"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = _last_json(result.stdout)
    assert payload["status"] == "ok"
    assert payload["operation"] == "smoke-test"
    assert payload["platform"] == "linux"
    bootstrap = (tmp_path / "build" / "linux" / "smoke-test" / "entries" / "fedleave_bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "os.environ['FEDLEAVE_BUILD_VERSION'] = '0.2.1.dev0+g12345678'" in bootstrap
    assert "os.environ['FEDLEAVE_SOURCE_COMMIT'] = '1234567890abcdef1234567890abcdef12345678'" in bootstrap


def test_windows_build_script_executes_smoke_test_without_error(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["FEDLEAVE_BUILD_ROOT"] = str(tmp_path / "build")
    if os.name == "nt":
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            str(WINDOWS_INSTALLER),
            "--unattended",
            "--smoke-test",
        ]
    else:
        command = [sys.executable, str(ENGINE), "--platform", "windows", "--unattended", "--smoke-test"]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = _last_json(result.stdout)
    assert payload["status"] == "ok"
    assert payload["operation"] == "smoke-test"
    assert payload["platform"] == "windows"
