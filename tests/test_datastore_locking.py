"""Real processes exercise the same lock used by CLI and GUI backend calls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fedleave.config import init_config
from fedleave.locking import datastore_lock

ROOT = Path(__file__).resolve().parents[1]


def environment(base):
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "FEDLEAVE_MCP_DATA_DIR": str(base),
        "FEDLEAVE_LOCK_TIMEOUT": "5",
    }


def wait_for(path, process):
    deadline = time.monotonic() + 15
    while not path.exists():
        if process.poll() is not None:
            pytest.fail(f"Worker exited before readiness: {process.communicate()}")
        if time.monotonic() > deadline:
            pytest.fail("Worker did not become ready")
        time.sleep(0.02)


def test_contending_cli_writers_retain_both_updates(tmp_path):
    base = tmp_path / "data"
    init_config(2026, "2026-01-11", 6, {"annual": 100}, data_dir=base)
    workers = []
    try:
        with datastore_lock(base):
            for i in range(2):
                ready = tmp_path / f"ready-{i}"
                code = f"from pathlib import Path; from fedleave.cli import app; Path({str(ready)!r}).touch(); app()"
                argv = [
                    sys.executable,
                    "-c",
                    code,
                    "add",
                    "--date=2026-07-01",
                    "--category=annual",
                    "--used=1",
                    f"--description=writer-{i}",
                    "--json",
                    f"--data-dir={base}",
                ]
                worker = subprocess.Popen(
                    argv, env=environment(base), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                workers.append(worker)
                wait_for(ready, worker)
            # Both processes have imported/registered the CLI, and must now wait
            # for the external lock before startup migration or transaction reads.
            time.sleep(0.3)
            assert all(worker.poll() is None for worker in workers)
            before = json.loads((base / "leave_years" / "2026.json").read_text())
            assert not any(t.get("description", "").startswith("writer-") for t in before["transactions"])
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=20)
            assert worker.returncode == 0, (stdout, stderr)
        after = json.loads((base / "leave_years" / "2026.json").read_text())
        added = [t for t in after["transactions"] if t.get("description", "").startswith("writer-")]
        assert {t["description"] for t in added} == {"writer-0", "writer-1"}
        assert len({t["id"] for t in added}) == 2
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate()


def test_cli_lock_timeout_is_retriable_and_stores_are_independent(tmp_path):
    base = tmp_path / "busy"
    with datastore_lock(base):
        env = {**environment(base), "FEDLEAVE_LOCK_TIMEOUT": ".1"}
        result = subprocess.run(
            [sys.executable, "-m", "fedleave", "types"], env=env, capture_output=True, text=True, timeout=15
        )
        assert result.returncode == 75
        assert "Datastore busy" in result.stderr
        with datastore_lock(tmp_path / "independent", timeout=0.1):
            pass


def test_process_crash_releases_os_lock_without_removing_lock_file(tmp_path):
    base = tmp_path / "data"
    ready = tmp_path / "ready"
    code = (
        "import time; from pathlib import Path; from fedleave.locking import datastore_lock; "
        f"lock = datastore_lock(Path({str(base)!r})); lock.__enter__(); "
        f"Path({str(ready)!r}).touch(); time.sleep(60)"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", code], env=environment(base), stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        wait_for(ready, worker)
        worker.kill()
        worker.communicate(timeout=10)
        assert (base / ".fedleave.lock").exists()
        with datastore_lock(base, timeout=0.2):
            pass
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate()
