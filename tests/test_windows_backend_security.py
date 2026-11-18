import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from fedleave.executable_search import is_executable, validate_backend
from fedleave_analytics.app import load_analytics_data
from fedleave_analytics.snapshots import ReadOnlySnapshotSource
from fedleave_gui.backend import BackendOptions, FedleaveBackend
from fedleave_month_report_graphic.report import run_fedleave


@pytest.mark.parametrize("suffix", [".bat", ".cmd", ".BAT", ".CmD"])
@pytest.mark.parametrize("caller", ["calendar", "snapshot", "analytics", "report"])
def test_windows_batch_backend_rejected_before_process_creation(tmp_path, monkeypatch, suffix, caller):
    backend = tmp_path / ("backend" + suffix)
    backend.write_text("@echo off\n")
    backend.chmod(0o755)
    monkeypatch.setattr(sys, "platform", "win32")

    def forbidden(*args, **kwargs):
        raise AssertionError("Batch backend reached process creation")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises((RuntimeError, ValueError, OSError)):
        if caller == "calendar":
            FedleaveBackend(BackendOptions(fedleave_path=str(backend))).run_text(["--version"])
        elif caller == "snapshot":
            ReadOnlySnapshotSource(backend, None)._run(["types"])
        elif caller == "analytics":
            load_analytics_data(backend, None, 2026)
        else:
            run_fedleave(backend, ["types"])


def test_windows_discovery_does_not_accept_batch_fallback(tmp_path, monkeypatch):
    import fedleave_gui.backend as backend_module

    backend = tmp_path / "fedleave.cmd"
    backend.write_text("@echo off\n")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(backend_module, "iter_executable_candidates", lambda name: iter(()))
    monkeypatch.setattr(backend_module.shutil, "which", lambda name: str(backend))
    with pytest.raises(RuntimeError):
        backend_module.find_fedleave()
    assert not is_executable(backend)


@pytest.mark.parametrize("suffix", [".exe", ".EXE"])
def test_windows_native_backend_validation_preserves_explicit_and_bare_paths(tmp_path, monkeypatch, suffix):
    import fedleave.executable_search as search

    executable = tmp_path / ("native backend" + suffix)
    executable.write_bytes(b"native test fixture; validation only")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(search.shutil, "which", lambda name: str(executable) if name == "fedleave.exe" else None)
    assert validate_backend(executable) == executable
    assert validate_backend("fedleave") == executable
    assert is_executable(executable)


def test_windows_validation_checks_the_resolved_executable_suffix(tmp_path, monkeypatch):
    batch = tmp_path / "backend.cmd"
    batch.touch()
    alias = tmp_path / "backend.exe"
    try:
        alias.symlink_to(batch)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this system")
    monkeypatch.setattr(sys, "platform", "win32")
    assert not is_executable(alias)
    with pytest.raises(ValueError, match="existing native"):
        validate_backend(alias)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows exe/argument integration runs in Windows CI")
def test_native_windows_cli_keeps_hostile_comments_literal(tmp_path, monkeypatch):
    executable = Path(sysconfig.get_path("scripts")) / "fedleave.exe"
    assert executable.is_file()
    data = tmp_path / "store"
    subprocess.run(
        [str(executable), "init", "--year", "2026", "--leave-year-start", "2026-01-11", "--data-dir", str(data)],
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(tmp_path)
    backend = FedleaveBackend(BackendOptions(fedleave_path=str(executable), data_dir=str(data)))
    comment = 'quote " & echo SENTINEL > SHOULD_NOT_EXIST & | %VALUE% !VALUE! ^ Unicode café'
    backend.force_balance(date="2026-07-01", category="annual", hours=10, comment=comment)
    backend.set_day("2026-07-02", {"sick": -2}, comments={"sick": comment})
    import json

    ledger = json.loads((data / "leave_years" / "2026.json").read_text(encoding="utf-8"))
    assert sum(row.get("description") == comment for row in ledger["transactions"]) == 2
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
