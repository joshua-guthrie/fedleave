from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client

from fedleave.mcp.catalog import discover
from fedleave.mcp.policy import Policy
from fedleave.mcp.server import create_server

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("restricted", [False, True])
def test_official_sdk_subprocess_stdio_round_trip(restricted):
    spec = importlib.util.spec_from_file_location("mcp_smoke", ROOT / "scripts/lib/common/mcp_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    asyncio.run(module.smoke(sys.executable, ["-m", "fedleave.mcp"], discover(), restricted=restricted))


def test_analytics_smoke_resolves_source_scripts_and_installed_siblings(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mcp_smoke", ROOT / "scripts/lib/common/mcp_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scripts = tmp_path / "Python" / "Scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(module.sysconfig, "get_path", lambda name: str(scripts))
    assert module.application_directory(str(tmp_path / "Python/python.exe"), ["-m", "fedleave.mcp"]) == scripts
    installed = tmp_path / "Installed FedLeave"
    assert module.application_directory(str(installed / "fedleave-mcp.exe"), []) == installed


def test_sdk_read_only_full_catalog_and_typed_errors(tmp_path):
    async def run():
        server = create_server(Policy(mode="read_only", data_dir=tmp_path / "data"))
        async with Client(server, raise_exceptions=True) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == set(discover())
            result = await client.call_tool("fedleave_add", {"date": "2026-07-01", "category": "annual", "used": 1})
            assert result.is_error and result.structured_content["error"] == "permission_denied"
            result = await client.call_tool("fedleave_add", {"date": "2026-07-01", "category": "annual", "used": "bad"})
            assert result.is_error and result.structured_content["error"] == "invalid_arguments"
            version = await client.call_tool("fedleave_version", {})
            assert not version.is_error

    asyncio.run(run())


def test_stdio_eof_exits_cleanly_and_imports_no_gui():
    result = subprocess.run(
        [sys.executable, "-m", "fedleave.mcp"], input="", capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fedleave.mcp.server import create_server; from fedleave.mcp.policy import Policy; create_server(Policy()); import sys; assert not any(n.startswith('PySide6') for n in sys.modules)",
        ],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_two_sdk_clients_retain_concurrent_transactions(tmp_path):
    async def run():
        policy = Policy(mode="unattended", data_dir=tmp_path / "data")
        async with Client(create_server(policy), read_timeout_seconds=30) as first:
            async with Client(create_server(policy), read_timeout_seconds=30) as second:
                initialized = await first.call_tool("fedleave_init", {"year": 2026, "leave_year_start": "2026-01-11"})
                assert not initialized.is_error
                results = await asyncio.gather(
                    *[
                        client.call_tool(
                            "fedleave_add",
                            {"date": "2026-07-01", "category": "annual", "used": 1, "description": f"agent-{i}"},
                        )
                        for i, client in enumerate([first, second])
                    ]
                )
                assert all(not result.is_error for result in results), results
                listed = await first.call_tool("fedleave_list", {"year": 2026})
                descriptions = {t.get("description") for t in listed.structured_content["data"]["transactions"]}
                assert {"agent-0", "agent-1"} <= descriptions

    asyncio.run(run())


@pytest.mark.parametrize("source", ["argument", "environment"])
@pytest.mark.parametrize("content", [None, "{", '{"mode":"unknown"}', '{"mode":"full_access","denied_tools":[]}'])
def test_invalid_explicit_configuration_fails_startup_without_escalation(tmp_path, source, content):
    path = tmp_path / "policy.json"
    if content is not None:
        path.write_text(content)
    env = {k: v for k, v in os.environ.items() if not k.startswith("FEDLEAVE_MCP_")}
    args = [sys.executable, "-m", "fedleave.mcp"]
    if source == "argument":
        args.extend(["--config", str(path)])
    else:
        env["FEDLEAVE_MCP_CONFIG"] = str(path)
    result = subprocess.run(args, env=env, input="", capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert result.stdout == "" and "startup failed" in result.stderr


def test_tool_annotations_account_for_maintenance_and_conditional_writes(tmp_path):
    async def run():
        for policy in [Policy(), Policy(mode="read_only", data_dir=tmp_path)]:
            async with Client(create_server(policy)) as client:
                tools = {t.name: t for t in (await client.list_tools()).tools}
                assert tools["fedleave_version"].annotations.read_only_hint
                assert not tools["fedleave_add"].annotations.read_only_hint
                assert tools["fedleave_balance"].annotations.read_only_hint
                assert tools["fedleave_rollover"].annotations.destructive_hint
                assert tools["fedleave_validate"].annotations.destructive_hint
                assert tools["fedleave_check_for_updates"].annotations.open_world_hint

    asyncio.run(run())
