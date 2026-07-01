from pathlib import Path
import os
import sys

from fedleave.config import get_default_data_dir


def test_get_default_data_dir_uses_explicit_data_dir(tmp_path: Path):
    explicit = tmp_path / "fedleave"
    assert get_default_data_dir(explicit) == explicit


def test_get_default_data_dir_uses_localappdata_on_windows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    data_dir = get_default_data_dir(None)
    assert data_dir == tmp_path / "LocalAppData" / "fedleave"


def test_get_default_data_dir_uses_xdg_data_home_on_linux(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data_home"))

    data_dir = get_default_data_dir(None)
    assert data_dir == tmp_path / "xdg_data_home" / "fedleave"


def test_get_default_data_dir_falls_back_to_home(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    data_dir = get_default_data_dir(None)
    assert data_dir == tmp_path / "home" / ".local" / "share" / "fedleave"
