"""Regression checks for source-only repository hygiene."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked_ignored_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_generated_and_environment_files_are_not_tracked() -> None:
    assert _tracked_ignored_files() == []
