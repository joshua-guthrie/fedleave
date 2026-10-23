from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys

import pytest

from fedleave.mcp.catalog import discover
from fedleave.mcp.execution import Executor, run_cli
from fedleave.mcp.policy import Policy


@pytest.fixture
def executor(tmp_path):
    return Executor(discover(), Policy(mode="unattended", data_dir=tmp_path / "data"))


def call(executor, tool, arguments=None):
    return asyncio.run(executor.call(f"fedleave_{tool}", arguments or {}))


def initialize(executor):
    result = call(executor, "init", {"year": 2026, "leave_year_start": "2026-01-11"})
    assert result["ok"], result


def test_unattended_read_add_reconcile_correct_and_nested_command(executor):
    initialize(executor)
    assert call(executor, "balance", {"year": 2026})["ok"]
    created = call(executor, "add", {"date": "2026-07-01", "category": "annual", "used": 2})
    assert created["ok"], created
    assert created["format"] == "json"
    transaction_id = created["data"]["transaction_id"]
    reconciled = call(
        executor,
        "reconcile",
        {"date": "2026-07-01", "category": "annual", "direction": "used", "hours": 3, "reason": "report"},
    )
    assert reconciled["ok"], reconciled
    corrected = call(executor, "correct", {"id": transaction_id, "hours": 1, "reason": "correction"})
    assert corrected["ok"], corrected
    nested = call(
        executor, "starting_balance_set", {"year": 2026, "category": "annual", "hours": 100, "reason": "opening"}
    )
    assert nested["ok"] and nested["format"] == "text", nested
    denied = call(executor, "void", {"id": transaction_id})
    assert denied["error"] == "permission_denied"
    records = call(executor, "list", {"year": 2026})["data"]
    assert any(t["id"] == transaction_id and t["hours"] == 1 for t in records["transactions"])


@pytest.mark.parametrize(
    "payload",
    [
        "; touch SHOULD_NOT_EXIST",
        "`touch SHOULD_NOT_EXIST`",
        "$(touch SHOULD_NOT_EXIST)",
        "a | echo injected",
        "first line\nsecond line; touch SHOULD_NOT_EXIST",
        "'quoted' \"double quoted\" ",
        "--data-dir=/forbidden --overwrite",
        "Unicode café 雪",
        "a" * 1000,
    ],
)
def test_hostile_descriptions_remain_literal_cli_data(executor, payload, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initialize(executor)
    result = call(executor, "add", {"date": "2026-07-01", "category": "annual", "used": 1, "description": payload})
    assert result["ok"], result
    # The existing CLI intentionally trims surrounding whitespace.
    assert result["data"]["transaction"]["description"] == payload.strip()
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


def test_leading_dash_is_value_and_invalid_cli_inputs_preserve_exit_code(executor):
    initialize(executor)
    result = call(executor, "add", {"date": "2026-07-01", "category": "--data-dir=/forbidden", "used": 1})
    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert result["error"] == "cli_error"
    result = call(executor, "add", {"date": "2026-07-01", "category": "annual", "used": 1, "earned": 1})
    assert result["exit_code"] == 2
    assert (
        call(executor, "add", {"date": "2026-07-01", "category": "annual", "used": "2"})["error"] == "invalid_arguments"
    )
    assert (
        call(executor, "add", {"date": "2026-07-01", "category": "annual", "used": 2, "argv": ["--overwrite"]})["error"]
        == "invalid_arguments"
    )


def test_text_json_false_missing_binary_and_unknown_tool(executor, tmp_path):
    initialize(executor)
    result = call(executor, "balance", {"year": 2026, "json_output": False})
    assert result["ok"] and result["format"] == "text" and "data" not in result
    assert asyncio.run(executor.call("arbitrary-shell", {}))["error"] == "unknown_tool"
    executor.policy = executor.policy.model_copy(update={"executable": tmp_path / "missing"})
    assert call(executor, "version")["error"] == "execution_error"


def test_validation_is_noninteractive_and_honors_explicit_json_false(executor):
    initialize(executor)
    assert call(executor, "validate")["ok"]
    result = call(executor, "validate", {"json_output": False})
    assert result["ok"] and result["format"] == "text"


def test_timeout_output_limit_and_cancellation_reap_children(tmp_path):
    env = os.environ.copy()
    result = asyncio.run(run_cli(sys.executable, ["-c", "import time; time.sleep(10)"], env, 0.1, 1024))
    assert result["error"] == "timeout" and result["exit_code"] is not None
    result = asyncio.run(run_cli(sys.executable, ["-c", "print('x'*100000)"], env, 5, 1024))
    assert result["error"] == "output_limit" and result["truncated"]
    assert len(result["stdout"].encode()) + len(result["stderr"].encode()) <= 1024

    async def cancelled():
        marker = tmp_path / "late-side-effect"
        code = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()"
        task = asyncio.create_task(run_cli(sys.executable, ["-c", code], env, 10, 1024))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(1)
        assert not marker.exists()

    asyncio.run(cancelled())


def test_child_stdin_is_noninteractive_and_immediately_at_eof():
    result = asyncio.run(
        run_cli(
            sys.executable,
            ["-c", "import json, sys; print(json.dumps({'tty': sys.stdin.isatty(), 'input': sys.stdin.read()}))"],
            os.environ.copy(),
            10,
            1024,
        )
    )
    assert result["ok"], result
    assert json.loads(result["stdout"]) == {"tty": False, "input": ""}


@pytest.mark.parametrize("output", ["not json", '{"hours": NaN}', '{"hours": Infinity}'])
def test_malformed_json_and_nonzero_stderr_are_not_success(executor, monkeypatch, output):
    async def fake(*args):
        return {"ok": True, "exit_code": 0, "stdout": output, "stderr": "warning"}

    monkeypatch.setattr("fedleave.mcp.execution.run_cli", fake)
    result = call(executor, "balance", {"year": 2026})
    assert result["error"] == "malformed_json" and result["stderr"] == "warning"


def test_audit_contains_outcome_not_leave_details(executor, tmp_path):
    audit = tmp_path / "audit.jsonl"
    executor.policy = executor.policy.model_copy(update={"audit_log": audit})
    initialize(executor)
    assert call(
        executor, "add", {"date": "2026-07-01", "category": "annual", "used": 1, "description": "sensitive appointment"}
    )["ok"]
    text = audit.read_text()
    assert "sensitive appointment" not in text
    assert json.loads(text.splitlines()[-1])["tool"] == "fedleave_add"
    result = call(
        executor,
        "set_day",
        {"date": "2026-07-02", "authoritative": True, "annual": -2, "annual_comment": "private leave details"},
    )
    assert result["ok"], result
    record = json.loads(audit.read_text().splitlines()[-1])
    assert record["record_ids"] == result["data"]["created_transaction_ids"]
    assert "private leave details" not in audit.read_text()


@pytest.fixture
def full_access(tmp_path, monkeypatch):
    # Isolate both platform defaults, including the CLI's eager migration, from
    # real user records. No MCP-only pinning is used by the full-access child.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local data"))
    for key in tuple(os.environ):
        if key.startswith("FEDLEAVE_MCP_"):
            monkeypatch.delenv(key)
    return Executor(discover(), Policy())


@pytest.mark.parametrize("explicit", [False, True])
def test_full_access_high_impact_files_backups_and_alternate_stores(full_access, tmp_path, explicit):
    if explicit:
        path = tmp_path / "policy.json"
        path.write_text('{"mode":"full_access"}')
        full_access.policy = Policy.load(path)
        full_access.config_path = path
    initialize(full_access)
    base = full_access.policy.data_dir
    assert (base / "leave_years" / "2026.json").exists()
    created = call(full_access, "add", {"date": "2026-07-01", "category": "annual", "used": 2})
    assert created["ok"], created
    transaction_id = created["data"]["transaction_id"]
    deleted = call(full_access, "void", {"id": transaction_id})
    assert deleted["ok"], deleted
    assert all(t["id"] != transaction_id for t in call(full_access, "list", {"year": 2026})["data"]["transactions"])
    forced = call(
        full_access,
        "force_balance",
        {
            "date": "2026-07-01",
            "category": "annual",
            "hours": 80,
            "comment": "test adjustment",
        },
    )
    assert forced["ok"], forced
    balance = call(full_access, "balance", {"year": 2026, "as_of": "2026-07-01"})
    assert balance["ok"] and balance["data"]["balances"]["annual"] == 80
    archive = tmp_path / "files with spaces" / "backup.json"
    exported = call(full_access, "export_data", {"output": str(archive)})
    assert exported["ok"] and archive.exists(), exported
    other = tmp_path / "alternate store"
    imported = call(full_access, "import_data", {"input": str(archive), "data_dir": str(other)})
    assert imported["ok"], imported
    assert json.loads((other / "leave_years" / "2026.json").read_text()) == json.loads(
        (base / "leave_years" / "2026.json").read_text()
    )
    # Ordinary CLI validation still controls replacement; no MCP import gate.
    refused = call(full_access, "import_data", {"input": str(archive), "data_dir": str(other)})
    assert refused["error"] == "cli_error" and refused["exit_code"] == 2
    overwritten = call(full_access, "import_data", {"input": str(archive), "data_dir": str(other), "overwrite": True})
    assert overwritten["ok"], overwritten
    assert list((other / "backups").glob("2026.json.*.bak"))
    rolled = call(
        full_access,
        "rollover",
        {
            "from_year": 2026,
            "to_year": 2027,
            "preview": False,
            "data_dir": str(other),
            "_cli_aliases": {"preview": "--no-preview"},
        },
    )
    assert rolled["ok"] and rolled["data"]["action"] == "applied", rolled
    assert (other / "leave_years" / "2027.json").exists()
    assert not (base / "leave_years" / "2027.json").exists()


def test_full_access_migrations_match_direct_cli_even_with_inherited_guards(full_access, tmp_path, monkeypatch):
    initialize(full_access)
    base = full_access.policy.data_dir
    year_path = base / "leave_years" / "2026.json"
    legacy = json.loads(year_path.read_text())
    legacy["starting_balance_history"] = [{"old": "private"}]
    year_path.write_text(json.dumps(legacy))
    direct = tmp_path / "direct-default" / "fedleave"
    shutil.copytree(base, direct)
    # Simulate inheriting a restricted launch. Full access clears these in its
    # child, preserving the actual OS-user defaults and normal maintenance.
    monkeypatch.setenv("FEDLEAVE_MCP_READ_ONLY", "1")
    monkeypatch.setenv("FEDLEAVE_MCP_WRITE_ROOTS", "[]")
    monkeypatch.setenv("FEDLEAVE_MCP_PROTECTED_PATHS", json.dumps([str(year_path)]))
    monkeypatch.setenv("FEDLEAVE_MCP_DATA_DIR", str(tmp_path / "unrelated"))
    result = call(full_access, "years")
    assert result["ok"], result
    direct_env = {k: v for k, v in os.environ.items() if not k.startswith("FEDLEAVE_MCP_")}
    direct_env.update(XDG_DATA_HOME=str(direct.parent), LOCALAPPDATA=str(direct.parent))
    direct_result = subprocess.run(
        [str(full_access_executable()), "years", "--json"],
        env=direct_env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert direct_result.returncode == result["exit_code"] == 0
    assert json.loads(direct_result.stdout) == result["data"]
    assert json.loads(year_path.read_text())["starting_balance_history"] == [{"old": "private"}]
    assert json.loads(year_path.read_text()) == json.loads((direct / "leave_years" / "2026.json").read_text())


def full_access_executable():
    from fedleave.mcp.execution import find_executable

    return find_executable()


def test_full_access_matches_direct_cli_transactions_json_and_exit_codes(full_access, tmp_path):
    def without_creation_times(value):
        # Separate real CLI invocations necessarily generate different creation
        # times; all other transaction/state/response fields must match exactly.
        if isinstance(value, dict):
            return {
                key: without_creation_times(item)
                for key, item in value.items()
                if key not in {"created_at", "updated_at"}
            }
        if isinstance(value, list):
            return [without_creation_times(item) for item in value]
        return value

    initialize(full_access)
    direct = tmp_path / "direct"
    shutil.copytree(full_access.policy.data_dir, direct)
    for tool, arguments in [
        ("add", {"date": "2026-07-01", "category": "annual", "used": 2, "authoritative": False}),
        ("balance", {"year": 2026, "as_of": "2026-07-01"}),
        ("add", {"date": "2026-07-01", "category": "annual", "used": 1, "earned": 1}),
    ]:
        result = call(full_access, tool, arguments)
        direct_result = subprocess.run(
            [
                str(full_access_executable()),
                *full_access.catalog[f"fedleave_{tool}"].argv(
                    {**arguments, "json_output": True, "data_dir": str(direct)}
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert direct_result.returncode == result["exit_code"]
        if result["ok"]:
            assert without_creation_times(json.loads(direct_result.stdout)) == without_creation_times(result["data"])
        else:
            assert result["error"] == "cli_error"
    assert without_creation_times(
        json.loads((direct / "leave_years" / "2026.json").read_text())
    ) == without_creation_times(json.loads((full_access.policy.data_dir / "leave_years" / "2026.json").read_text()))


def test_full_access_imports_ics_and_wms_files_without_roots(full_access, tmp_path):
    from test_wms_http_import import _data_row, _wms_html

    initialize(full_access)
    ics = tmp_path / "holidays with spaces.ics"
    ics.write_text(
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:test@example.com\n"
        "DTSTAMP:20260101T000000Z\nDTSTART;VALUE=DATE:20260101\nSUMMARY:Test Holiday\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    result = call(full_access, "holidays", {"action": "import-ics", "year": 2026, "file": str(ics)})
    assert result["ok"], result
    html = tmp_path / "WMS report.html"
    html.write_text(_wms_html([_data_row(date="13-Jan-2026", code="LA", start_time="7.00", hours="3.00")]))
    result = call(full_access, "import_wms_http", {"input": str(html)})
    assert result["ok"], result
    assert any(t.get("source") == "wms-http" for t in call(full_access, "list", {"year": 2026})["data"]["transactions"])


def test_full_access_network_commands_run_registered_cli_with_stubbed_services(full_access, monkeypatch):
    from typer.testing import CliRunner

    from fedleave.cli import app

    requested = []

    def update_check():
        requested.append("updates")
        return {"status": "ok", "update_available": False}

    def download_ics(url):
        requested.append(url)
        return (
            b"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:network@example.test\n"
            b"DTSTAMP:20260101T000000Z\nDTSTART;VALUE=DATE:20260101\nSUMMARY:Test\nEND:VEVENT\nEND:VCALENDAR\n"
        )

    monkeypatch.setattr("fedleave.commands.updates.check_for_updates", update_check)
    monkeypatch.setattr("fedleave.holidays.download_ics", download_ics)

    async def registered_cli(executable, argv, env, timeout, max_output):
        result = CliRunner().invoke(app, argv)
        return {
            "ok": result.exit_code == 0,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    monkeypatch.setattr("fedleave.mcp.execution.run_cli", registered_cli)
    result = call(full_access, "check_for_updates")
    assert result["ok"] and result["data"]["status"] == "ok", result
    result = call(
        full_access,
        "init",
        {
            "year": 2026,
            "leave_year_start": "2026-01-11",
            "holiday_source": "opm_ics",
            "holiday_ics_url": "https://example.test/holidays.ics",
        },
    )
    assert result["ok"], result
    assert requested == ["updates", "https://example.test/holidays.ics"]


def test_full_access_text_validation_reports_and_applies_without_prompting(full_access):
    initialize(full_access)
    path = full_access.policy.data_dir / "leave_years" / "2026.json"
    data = json.loads(path.read_text())
    data["transactions"].append(
        {"id": "test", "date": "2026-7-1", "category": "annual", "direction": "used", "hours": 1}
    )
    path.write_text(json.dumps(data))
    result = call(full_access, "validate", {"json_output": False})
    assert result["exit_code"] == 2 and result["error"] == "cli_error", result
    assert "Apply suggested fixes" not in result["stdout"] + result["stderr"]
    assert json.loads(path.read_text())["transactions"][-1]["date"] == "2026-7-1"
    result = call(full_access, "validate", {"json_output": False, "apply": True})
    # Validation retains CLI exit 2 for the issues it found, even after fixing.
    assert result["exit_code"] == 2
    assert json.loads(path.read_text())["transactions"][-1]["date"] == "2026-07-01"


def test_full_access_lock_contention_reports_cli_exit_75(full_access):
    from fedleave.locking import datastore_lock

    full_access.policy = Policy(lock_timeout_seconds=0.1)
    with datastore_lock(full_access.policy.data_dir):
        result = call(full_access, "types")
    assert result["error"] == "datastore_busy" and result["exit_code"] == 75 and result["retryable"]


def test_runtime_failures_warn_that_a_write_may_have_committed(tmp_path):
    marker = tmp_path / "committed"
    code = f"from pathlib import Path; Path({str(marker)!r}).touch(); print('x'*100000)"
    result = asyncio.run(run_cli(sys.executable, ["-c", code], os.environ.copy(), 10, 1024))
    assert marker.exists() and result["error"] == "output_limit"
    assert "inspect the ledger before retrying a write" in result["message"]


def test_tool_arguments_cannot_change_policy_executable_or_environment(full_access):
    for field, value in [("mode", "read_only"), ("executable", "/bin/sh"), ("env", {}), ("policy", {})]:
        result = call(full_access, "years", {field: value})
        assert result["error"] == "invalid_arguments"
