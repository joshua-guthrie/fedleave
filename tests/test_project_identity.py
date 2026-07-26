from __future__ import annotations

import tomllib
from pathlib import Path

from fedleave.cli_app import HELP_TEXT
from fedleave.project_info import OFFICIAL_PROJECT_URL, PROJECT_AUTHOR


ROOT = Path(__file__).resolve().parents[1]


def test_cli_help_identifies_official_website_and_author() -> None:
    assert OFFICIAL_PROJECT_URL in HELP_TEXT
    assert PROJECT_AUTHOR in HELP_TEXT


def test_package_metadata_identifies_official_website_and_author_without_email() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert metadata["authors"] == [{"name": PROJECT_AUTHOR}]
    assert metadata["urls"]["Homepage"] == OFFICIAL_PROJECT_URL
    assert metadata["urls"]["Documentation"] == OFFICIAL_PROJECT_URL
    assert metadata["urls"]["Support"] == OFFICIAL_PROJECT_URL
