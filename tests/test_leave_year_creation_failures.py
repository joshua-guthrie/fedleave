"""Filesystem immutability, stale plans, concurrency, and injected failures."""

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import fedleave.cross_year as service
import fedleave.storage as storage
from fedleave.cli import app
from fedleave.cross_year import apply_creation, apply_reconciliation, creation_plan, reconciliation_plan
from leave_year_support import save, store, tree, tx


@pytest.mark.parametrize(
    "command",
    [
        ["init", "--year", "2027", "--from-year", "2026", "--preview"],
        ["rollover", "--from-year", "2026", "--to-year", "2027", "--preview"],
        ["years"],
        ["balance", "--year", "2026", "--as-of", "2026-06-01"],
        ["expirations", "--year", "2026"],
        ["month", "--year", "2026", "--month", "6"],
        ["pay-periods", "--year", "2026"],
        ["list", "--year", "2026"],
        ["snapshot", "--year", "2026"],
    ],
    ids=[
        "CLI-007-008-009",
        "CLI-013",
        "CLI-015-FS-023",
        "FS-003",
        "FS-004",
        "INT-009",
        "INT-017",
        "INT-008",
        "INT-013",
    ],
)
def test_readonly_commands_preserve_exact_tree(tmp_path, command):
    source, _ = store(
        tmp_path,
        transactions=[
            tx("lot", "2026-02-01", "travel_comp", "earned", 8),
            tx("void", "2026-03-01", "annual", "used", 2, void=True),
        ],
    )
    source["starting_balance_history"] = [{"legacy": "retained on disk"}]
    save(tmp_path, 2026, source)
    before = tree(tmp_path)
    result = CliRunner().invoke(app, [*command, "--json", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, (result.output, result.exception)
    assert isinstance(json.loads(result.output), dict)
    assert tree(tmp_path) == before


def test_FS_005_006_manual_preview_nonexistent_store_never_creates_directory(tmp_path):
    selected = tmp_path / "absent"
    result = CliRunner().invoke(
        app,
        [
            "init",
            "--year",
            "2027",
            "--leave-year-start",
            "2027-01-10",
            "--preview",
            "--json",
            "--data-dir",
            str(selected),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["initialization_mode"] == "manual"
    assert not selected.exists()


@pytest.mark.parametrize(
    "problem",
    ["missing", "corrupt", "metadata", "same-year", "later-year", "gap", "overlap"],
    ids=["MOD-006", "MOD-015-corrupt", "MOD-007", "MOD-008", "MOD-009", "MOD-012", "MOD-013"],
)
def test_invalid_source_preview_has_structured_error_and_no_writes(tmp_path, problem):
    source, _ = store(tmp_path)
    source_year, target_year = 2026, 2027
    extra = []
    if problem == "missing":
        (tmp_path / "leave_years/2026.json").unlink()
    elif problem == "corrupt":
        (tmp_path / "leave_years/2026.json").write_text("{")
    elif problem == "metadata":
        source["leave_year"] = 1999
        save(tmp_path, 2026, source)
    elif problem == "same-year":
        target_year = 2026
    elif problem == "later-year":
        target_year = 2025
    elif problem == "gap":
        extra = ["--leave-year-start", "2027-01-11"]
    elif problem == "overlap":
        extra = ["--leave-year-start", "2027-01-09"]
    before = tree(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "init",
            "--from-year",
            str(source_year),
            "--year",
            str(target_year),
            "--preview",
            "--json",
            "--data-dir",
            str(tmp_path),
            *extra,
        ],
    )
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["code"]
    assert tree(tmp_path) == before


@pytest.mark.parametrize("changed", ["source", "config"], ids=["EDGE-017", "FS-019-policy"])
def test_changed_source_rejects_reviewed_creation(tmp_path, changed):
    source, config = store(tmp_path, balances={"annual": 100})
    target, preview = creation_plan(tmp_path, 2026, 2027)
    if changed == "source":
        source["transactions"].append(tx("late", "2026-12-01", "annual", "used", 8))
        save(tmp_path, 2026, source)
    else:
        config["rules"]["annual"]["carryover_limit_hours"] = 80
        (tmp_path / "config.json").write_text(json.dumps(config))
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="STALE_PREVIEW"):
        apply_creation(tmp_path, target, preview, preview["preview_fingerprint"])
    assert tree(tmp_path) == before


def test_FS_021_changed_target_rejects_reviewed_reconciliation(tmp_path):
    source, _ = store(tmp_path, balances={"annual": 100})
    target, preview = creation_plan(tmp_path, 2026, 2027)
    apply_creation(tmp_path, target, preview)
    source["starting_balances"]["annual"] = 80
    save(tmp_path, 2026, source)
    changes, reconciliation = reconciliation_plan(tmp_path, 2027)
    target["transactions"].append(tx("concurrent", "2027-06-01", "annual", "used", 4))
    save(tmp_path, 2027, target)
    before = tree(tmp_path)
    with pytest.raises(ValueError, match="STALE_PREVIEW"):
        apply_reconciliation(tmp_path, changes, reconciliation, reconciliation["preview_fingerprint"])
    assert tree(tmp_path) == before


@pytest.mark.parametrize("failure", ["serialization", "publish"], ids=["FS-009", "FS-010"])
def test_failed_creation_has_no_partial_target(tmp_path, monkeypatch, failure):
    store(tmp_path)
    target, preview = creation_plan(tmp_path, 2026, 2027)
    before = tree(tmp_path)
    if failure == "serialization":

        def fail(*args, **kwargs):
            raise TypeError("serialization failure")

        monkeypatch.setattr(storage.json, "dump", fail)
    else:

        def fail(*args, **kwargs):
            raise OSError("publish failure")

        monkeypatch.setattr(storage.os, "link", fail)
    with pytest.raises((TypeError, OSError)):
        apply_creation(tmp_path, target, preview)
    assert tree(tmp_path) == before


def test_FS_012_backup_failure_keeps_existing_target(tmp_path, monkeypatch):
    source, _ = store(tmp_path, balances={"annual": 100})
    target, preview = creation_plan(tmp_path, 2026, 2027)
    apply_creation(tmp_path, target, preview)
    source["starting_balances"]["annual"] = 80
    save(tmp_path, 2026, source)
    changes, preview = reconciliation_plan(tmp_path, 2027)
    before = tree(tmp_path)

    def fail(path):
        raise OSError("backup failure")

    monkeypatch.setattr(service, "backup_file", fail)
    with pytest.raises(OSError, match="backup failure"):
        apply_reconciliation(tmp_path, changes, preview)
    assert tree(tmp_path) == before


def test_FS_017_two_concurrent_cli_creators_one_destination(tmp_path):
    store(tmp_path, balances={"annual": 100})
    command = [
        sys.executable,
        "-m",
        "fedleave",
        "init",
        "--from-year",
        "2026",
        "--year",
        "2027",
        "--json",
        "--data-dir",
        str(tmp_path),
    ]
    workers = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        outputs = [worker.communicate(timeout=20) for worker in workers]
        assert sorted(worker.returncode for worker in workers)[0] == 0
        assert sum(worker.returncode == 0 for worker in workers) == 1, outputs
        assert json.loads((tmp_path / "leave_years/2027.json").read_text())["starting_balances"]["annual"] == 100
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate()


def test_FS_020_symlink_target_cannot_escape_store(tmp_path):
    base, outside = tmp_path / "data", tmp_path / "outside"
    store(base)
    outside.mkdir()
    try:
        (base / "leave_years/2027.json").symlink_to(outside / "2027.json")
    except OSError:
        pytest.skip("Symlink privilege unavailable")
    before = tree(outside)
    with pytest.raises(ValueError, match="DESTINATION_EXISTS"):
        creation_plan(base, 2026, 2027)
    assert tree(outside) == before


def test_CLI_010_FS_008_readonly_source_filesystem(tmp_path):
    source, _ = store(tmp_path, balances={"annual": 100})
    files = [tmp_path / "config.json", tmp_path / "leave_years/2026.json"]
    for path in files:
        path.chmod(0o444)
    (tmp_path / "leave_years").chmod(0o555)
    tmp_path.chmod(0o555)
    try:
        before = tree(tmp_path)
        result = CliRunner().invoke(
            app, ["init", "--from-year", "2026", "--year", "2027", "--preview", "--json", "--data-dir", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["opening_balances"]["annual"] == 100
        assert tree(tmp_path) == before
    finally:
        tmp_path.chmod(0o755)
        (tmp_path / "leave_years").chmod(0o755)
        for path in files:
            path.chmod(0o644)


def test_FS_011_creation_never_requests_a_source_write(tmp_path, monkeypatch):
    store(tmp_path, balances={"annual": 100})
    target, preview = creation_plan(tmp_path, 2026, 2027)
    original = service.atomic_write_json
    writes = []

    def destination_only(path, data, overwrite=True):
        writes.append(path.name)
        assert path.name == "2027.json", "Creation attempted a source/metadata write"
        return original(path, data, overwrite=overwrite)

    monkeypatch.setattr(service, "atomic_write_json", destination_only)
    apply_creation(tmp_path, target, preview)
    assert writes == ["2027.json"]


def test_FS_013_014_015_interrupt_after_atomic_create_is_complete_and_not_duplicated(tmp_path, monkeypatch):
    store(tmp_path, balances={"annual": 100})
    target, preview = creation_plan(tmp_path, 2026, 2027)
    original = service.atomic_write_json

    def interrupted_after_publish(path, data, overwrite=True):
        original(path, data, overwrite=overwrite)
        raise KeyboardInterrupt("Simulated interruption immediately after complete publication")

    monkeypatch.setattr(service, "atomic_write_json", interrupted_after_publish)
    with pytest.raises(KeyboardInterrupt):
        apply_creation(tmp_path, target, preview)
    created = json.loads((tmp_path / "leave_years/2027.json").read_text())
    assert created == target
    assert created["initialization"]["source_fingerprint"] == preview["source_fingerprint"]
    with pytest.raises(ValueError, match="DESTINATION_EXISTS"):
        creation_plan(tmp_path, 2026, 2027)
    assert not list((tmp_path / "leave_years").glob("*.tmp"))


def test_FS_018_concurrent_manual_creators_different_destinations(tmp_path):
    commands = [
        [
            sys.executable,
            "-m",
            "fedleave",
            "init",
            "--year",
            str(year),
            "--leave-year-start",
            f"{year}-01-10",
            "--json",
            "--data-dir",
            str(tmp_path),
        ]
        for year in (2026, 2027)
    ]
    workers = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in commands
    ]
    try:
        outputs = [worker.communicate(timeout=20) for worker in workers]
        assert all(worker.returncode == 0 for worker in workers), outputs
        assert json.loads((tmp_path / "leave_years/2026.json").read_text())["initialization"]["mode"] == "manual"
        assert json.loads((tmp_path / "leave_years/2027.json").read_text())["initialization"]["mode"] == "manual"
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate()


@pytest.mark.parametrize(
    "metadata",
    [
        {"mode": "manual", "source_leave_year": 2026},
        {"mode": "carryover", "source_leave_year": None},
        {"source_leave_year": 2026},
        {"mode": "manual", "method": "carryover", "source_leave_year": None},
    ],
    ids=["EDGE-024", "PROP-018-missing", "PROP-018-unknown", "PROP-018-contradiction"],
)
def test_invalid_lineage_never_claims_verified_carryover(tmp_path, metadata):
    source, _ = store(tmp_path)
    source["initialization"] = metadata
    save(tmp_path, 2026, source)
    result = CliRunner().invoke(
        app, ["balance", "--year", "2026", "--as-of", "2026-06-01", "--json", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code != 0 and "CONFLICTING_CARRYOVER" in result.output
    assert "balances" not in json.loads(result.output)
