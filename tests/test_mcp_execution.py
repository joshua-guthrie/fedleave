from __future__ import annotations

import asyncio
import json
import os
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
    assert result["error"] == "permission_denied" and "noninteractive" in result["message"]


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
