"""Standard-SDK stdio smoke test for source and frozen/installed MCP servers.

Run with the official SDK installed in the *test client* Python environment.
The packaged server and sibling CLI use their own bundled Python runtimes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters


async def smoke(command: str, args: list[str], expected_names=None, *, restricted=False):
    with tempfile.TemporaryDirectory(prefix="fedleave-mcp-smoke-") as folder:
        root = Path(folder)
        policy = root / "policy.json"
        if restricted:
            policy.write_text(json.dumps({"mode": "unattended", "data_dir": str(root / "data")}), encoding="utf-8")
        # Isolate both ordinary platform defaults. Full-access package tests
        # launch with no --config and no MCP-only datastore environment override.
        env = {k: v for k, v in os.environ.items() if not k.startswith("FEDLEAVE_MCP_")}
        env.update(XDG_DATA_HOME=str(root / "xdg"), LOCALAPPDATA=str(root / "local"), PYTHONIOENCODING="utf-8")
        params = StdioServerParameters(
            command=command,
            args=[*args, *(["--config", str(policy)] if restricted else [])],
            cwd=root,
            env=env,
        )
        async with Client(params, read_timeout_seconds=60) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert len(names) == len(listed.tools)
            if expected_names is not None:
                assert names == set(expected_names), (names, expected_names)
            assert "fedleave_starting_balance_set" in names
            assert (
                "restored_annual_comment"
                in next(t for t in listed.tools if t.name == "fedleave_set_day").input_schema["properties"]
            )

            async def call(name, arguments):
                result = await client.call_tool(name, arguments)
                assert not result.is_error, result
                payload = result.structured_content
                assert payload["ok"] and payload["exit_code"] == 0, payload
                return payload

            await call("fedleave_init", {"year": 2026, "leave_year_start": "2026-01-11"})
            balance = await call("fedleave_balance", {"year": 2026, "as_of": "2026-07-01"})
            assert balance["format"] == "json" and "balances" in balance["data"]
            added = await call(
                "fedleave_add", {"date": "2026-07-01", "category": "annual", "used": 2, "description": "MCP smoke"}
            )
            transaction_id = added["data"]["transaction_id"]
            await call(
                "fedleave_reconcile",
                {
                    "date": "2026-07-01",
                    "category": "annual",
                    "direction": "used",
                    "hours": 3,
                    "reason": "smoke reconcile",
                },
            )
            await call("fedleave_correct", {"id": transaction_id, "hours": 1, "reason": "smoke correction"})
            await call(
                "fedleave_starting_balance_set", {"year": 2026, "category": "annual", "hours": 100, "reason": "opening"}
            )
            await call(
                "fedleave_set_day", {"date": "2026-07-02", "authoritative": True, "sick": -2, "sick_comment": "smoke"}
            )
            await call("fedleave_holidays", {"action": "list", "year": 2026})
            # Two independent stdio server processes must coordinate through
            # their installed CLI children, including in the frozen packages.
            async with Client(params, read_timeout_seconds=60) as second:
                results = await asyncio.gather(
                    *[
                        connection.call_tool(
                            "fedleave_add",
                            {
                                "date": "2026-07-03",
                                "category": "annual",
                                "used": 1,
                                "description": f"packaged-agent-{i}",
                            },
                        )
                        for i, connection in enumerate((client, second))
                    ]
                )
                assert all(not result.is_error for result in results), results
            listed = await call("fedleave_list", {"year": 2026})
            descriptions = {t.get("description") for t in listed["data"]["transactions"]}
            assert {"packaged-agent-0", "packaged-agent-1"} <= descriptions
            if restricted:
                denied = await client.call_tool("fedleave_void", {"id": transaction_id})
                assert denied.is_error and denied.structured_content["error"] == "permission_denied"
            else:
                await call("fedleave_void", {"id": transaction_id})
                await call(
                    "fedleave_force_balance",
                    {
                        "date": "2026-07-01",
                        "category": "annual",
                        "hours": 80,
                        "comment": "smoke",
                    },
                )
                archive = root / "reports with spaces" / "backup.json"
                await call("fedleave_export_data", {"output": str(archive)})
                other = root / "alternate datastore"
                await call("fedleave_import_data", {"input": str(archive), "data_dir": str(other)})
                await call("fedleave_import_data", {"input": str(archive), "data_dir": str(other), "overwrite": True})
                await call(
                    "fedleave_rollover",
                    {
                        "from_year": 2026,
                        "to_year": 2027,
                        "preview": False,
                        "data_dir": str(other),
                        "_cli_aliases": {"preview": "--no-preview"},
                    },
                )
                assert (other / "leave_years" / "2027.json").exists()
            unknown = await client.call_tool("arbitrary_shell", {"command": "echo unsafe"})
            assert unknown.is_error
        print(
            json.dumps(
                {
                    "ok": True,
                    "transport": "stdio",
                    "tools": len(names),
                    "mode": "unattended" if restricted else "full_access",
                }
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    options = parser.parse_args()
    server = str(options.server.resolve())
    inventory = subprocess.run([server, "--inventory"], check=True, text=True, capture_output=True, timeout=60)
    report = json.loads(inventory.stdout)
    asyncio.run(smoke(server, [], [tool["tool"] for tool in report["tools"]]))
    asyncio.run(smoke(server, [], [tool["tool"] for tool in report["tools"]], restricted=True))


if __name__ == "__main__":
    main()
