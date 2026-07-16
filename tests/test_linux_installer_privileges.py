from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "scripts" / "lib" / "common" / "installer_engine.py"
HELPER_PATH = ROOT / "scripts" / "lib" / "common" / "linux_installer_helper.py"


def _load_engine_module():
    spec = importlib.util.spec_from_file_location("installer_engine", ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_options(module):
    return module.Options(
        platform="linux",
        unattended=False,
        build_only=False,
        install_only=None,
        repair=False,
        rollback=False,
        activate_version=None,
        uninstall=False,
        clean=False,
        keep_build=False,
        keep_versions=2,
        desktop=False,
        allow_downgrade=False,
        python_installer=None,
        offline=False,
        verbose=False,
    )


def test_linux_install_prompts_for_sudo_instead_of_failing(tmp_path, monkeypatch):
    module = _load_engine_module()
    options = _make_options(module)
    monkeypatch.setattr(module.InstallerEngine, "_build_workspace_needs_repair", lambda self: False)
    engine = module.InstallerEngine(ROOT, options)
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(module.InstallerEngine, "_project_version", lambda self: "9.9.9")

    dist_dir = tmp_path / "dist" / "fedleave-Ubuntu"
    dist_dir.mkdir(parents=True)

    captured: dict[str, object] = {}

    def fake_run(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    engine._install_from_dist(dist_dir)
    engine._log_handle.close()

    assert captured["cmd"][0] == "sudo"
    assert captured["cmd"][1] == module.sys.executable
    assert captured["cmd"][2] == str(HELPER_PATH)
    assert captured["cmd"][3] == "install-system"
    assert captured["cmd"][4] == str(ROOT)
    assert captured["cmd"][5] == str(dist_dir)
    assert captured["cmd"][6] == "9.9.9"
    assert captured["cmd"][7] == "2"
    assert captured["cwd"] == str(ROOT)


def test_linux_install_requires_privilege_in_unattended_mode(tmp_path, monkeypatch):
    module = _load_engine_module()
    options = _make_options(module)
    options.unattended = True
    monkeypatch.setattr(module.InstallerEngine, "_build_workspace_needs_repair", lambda self: False)
    engine = module.InstallerEngine(ROOT, options)
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)

    dist_dir = tmp_path / "dist" / "fedleave-Ubuntu"
    dist_dir.mkdir(parents=True)

    with pytest.raises(module.InstallerError, match="unattended mode") as exc_info:
        engine._install_from_dist(dist_dir)

    engine._log_handle.close()
    assert exc_info.value.code == module.EXIT_PERMISSION


def test_linux_install_repairs_existing_build_workspace_ownership(tmp_path, monkeypatch):
    module = _load_engine_module()
    options = _make_options(module)
    engine = module.InstallerEngine.__new__(module.InstallerEngine)
    engine.repo_root = ROOT
    engine.options = options
    engine.build_root = tmp_path / ".build" / "linux"
    engine._log_handle = SimpleNamespace(write=lambda *args, **kwargs: None, flush=lambda: None)
    engine.log = lambda message: None

    engine.build_root.mkdir(parents=True)
    stale_entry = engine.build_root / "entries" / "fedleave.py"
    stale_entry.parent.mkdir(parents=True)
    stale_entry.write_text("print('stale')\n")

    captured: dict[str, object] = {}

    def fake_access(path, mode):
        if Path(path) in {engine.build_root, stale_entry}:
            return False
        return True

    def fake_run(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.os, "access", fake_access)
    monkeypatch.setattr(module.os, "getuid", lambda: 1000)
    monkeypatch.setattr(module.os, "getgid", lambda: 1000)
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    engine._ensure_build_workspace_access()

    assert captured["cmd"][0] == "sudo"
    assert captured["cmd"][1] == module.sys.executable
    assert captured["cmd"][2] == str(HELPER_PATH)
    assert captured["cmd"][3] == "repair-build-workspace"
    assert captured["cmd"][4] == str(engine.build_root)
    assert captured["cmd"][5] == "1000"
    assert captured["cmd"][6] == "1000"