from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "scripts" / "lib" / "common" / "installer_engine.py"
HELPER_PATH = ROOT / "scripts" / "lib" / "common" / "windows_installer_helper.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _engine(module, *, unattended: bool = False):
    engine = module.InstallerEngine.__new__(module.InstallerEngine)
    engine.repo_root = ROOT
    engine.options = SimpleNamespace(platform="windows", unattended=unattended)
    engine.log = lambda message: None
    return engine


def test_windows_install_prompts_and_preserves_dist_when_declined(tmp_path, monkeypatch):
    module = _load_module("windows_prompt_engine", ENGINE_PATH)
    engine = _engine(module)
    dist = tmp_path / "fedleave-Windows"
    dist.mkdir()
    called = False

    def unexpected(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    monkeypatch.setattr(engine, "_run_windows_helper_elevated", unexpected)

    engine._install_from_dist(dist)

    assert called is False
    assert dist.is_dir()


def test_windows_install_requests_elevation_after_user_accepts(tmp_path, monkeypatch):
    module = _load_module("windows_elevation_engine", ENGINE_PATH)
    engine = _engine(module)
    dist = tmp_path / "fedleave-Windows"
    dist.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    monkeypatch.setattr(engine, "_windows_is_admin", lambda: False)
    monkeypatch.setattr(
        engine,
        "_run_windows_helper_elevated",
        lambda helper, args: captured.update(helper=helper, args=args),
    )

    engine._install_from_dist(dist)

    assert captured["helper"] == HELPER_PATH
    assert captured["args"] == ["install-system", str(dist)]


def test_windows_unattended_install_skips_prompt_when_already_elevated(tmp_path, monkeypatch):
    module = _load_module("windows_unattended_engine", ENGINE_PATH)
    engine = _engine(module, unattended=True)
    dist = tmp_path / "fedleave-Windows"
    dist.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("unattended install prompted"))
    monkeypatch.setattr(engine, "_windows_is_admin", lambda: True)
    monkeypatch.setattr(
        engine,
        "_run_helper",
        lambda helper, args, description: captured.update(helper=helper, args=args, description=description),
    )

    engine._install_from_dist(dist)

    assert captured == {
        "helper": HELPER_PATH,
        "args": ["install-system", str(dist)],
        "description": "Windows system-wide install",
    }


def test_windows_helper_installs_bundle_and_creates_both_shortcuts(tmp_path, monkeypatch):
    module = _load_module("windows_install_helper", HELPER_PATH)
    source = tmp_path / "dist" / "fedleave-Windows"
    calendar = source / "FedLeaveCalendar" / "FedLeaveCalendar.exe"
    calendar.parent.mkdir(parents=True)
    calendar.write_bytes(b"calendar")
    (source / "fedleave" / "fedleave.exe").parent.mkdir()
    (source / "fedleave" / "fedleave.exe").write_bytes(b"backend")
    target = tmp_path / "Program Files" / "fedleave"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")
    desktop = tmp_path / "Public" / "Desktop"
    start_menu = tmp_path / "ProgramData" / "Start Menu" / "FedLeave"
    shortcuts: list[tuple[Path, Path, Path]] = []
    monkeypatch.setattr(
        module,
        "_create_shortcut",
        lambda shortcut, executable, working: shortcuts.append((shortcut, executable, working)),
    )

    module.install_system(source, target, desktop, start_menu)

    installed_calendar = target / "FedLeaveCalendar" / "FedLeaveCalendar.exe"
    assert installed_calendar.read_bytes() == b"calendar"
    assert (target / "fedleave" / "fedleave.exe").read_bytes() == b"backend"
    assert not (target / "old.txt").exists()
    assert not target.with_name("fedleave.previous").exists()
    assert shortcuts == [
        (desktop / "FedLeave Calendar.lnk", installed_calendar, installed_calendar.parent),
        (start_menu / "FedLeave Calendar.lnk", installed_calendar, installed_calendar.parent),
    ]


def test_windows_helper_restores_previous_install_if_bundle_is_invalid(tmp_path):
    module = _load_module("windows_restore_helper", HELPER_PATH)
    source = tmp_path / "dist" / "fedleave-Windows"
    source.mkdir(parents=True)
    (source / "not-calendar.txt").write_text("invalid", encoding="utf-8")
    target = tmp_path / "Program Files" / "fedleave"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="calendar executable"):
        module.install_system(source, target, tmp_path / "Desktop", tmp_path / "Start Menu")

    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not target.with_name("fedleave.staging").exists()
    assert not target.with_name("fedleave.previous").exists()


def test_build_publish_succeeds_when_previous_windows_files_remain_locked(tmp_path, monkeypatch):
    module = _load_module("windows_publish_engine", ENGINE_PATH)
    engine = _engine(module)
    messages: list[str] = []
    engine.log = messages.append
    completed = tmp_path / "completed" / "fedleave-Windows"
    completed.mkdir(parents=True)
    (completed / "new.txt").write_text("new build", encoding="utf-8")
    published = tmp_path / "dist" / "fedleave-Windows"
    published.mkdir(parents=True)
    (published / "locked.pyd").write_text("old build", encoding="utf-8")

    def locked_cleanup(path):
        raise PermissionError(5, "Access is denied", str(path / "locked.pyd"))

    monkeypatch.setattr(engine, "_remove_tree_with_retries", locked_cleanup)

    engine._publish_build(completed, published)

    assert (published / "new.txt").read_text(encoding="utf-8") == "new build"
    assert not (published / "locked.pyd").exists()
    abandoned = list(published.parent.glob(".fedleave-Windows.previous-*"))
    assert len(abandoned) == 1
    assert (abandoned[0] / "locked.pyd").read_text(encoding="utf-8") == "old build"
    assert any("WARNING: Previous build remains" in message for message in messages)
