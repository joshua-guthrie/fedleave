"""Bounded, cancellable CLI subprocess execution. No shell or agent argv."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import anyio

from .catalog import CatalogError
from .policy import Policy, PolicyError, canonical, effects

logger = logging.getLogger(__name__)


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def find_executable(explicit: Path | None = None) -> Path:
    if explicit is not None:
        candidates = [explicit]
    else:
        name = "fedleave.exe" if os.name == "nt" else "fedleave"
        candidates = [Path(sys.executable).parent / name, Path(sys.argv[0]).resolve().parent / name]
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    for path in candidates:
        # Windows may route batch files through cmd.exe even with shell=False.
        if os.name == "nt" and path.suffix.lower() != ".exe":
            continue
        if path.is_file() and os.access(path, os.X_OK):
            return canonical(path)
    raise FileNotFoundError("fedleave executable missing; install the complete bundle or configure executable locally")


def failure(code, message, **fields):
    return {
        "ok": False,
        "error": code,
        "message": message,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "format": "text",
        **fields,
    }


async def run_cli(executable, argv, env, timeout, max_output):
    process = await asyncio.create_subprocess_exec(
        str(executable),
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **({"creationflags": 0x08000000} if os.name == "nt" else {}),
    )
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    size = 0
    exceeded = False

    async def drain(stream, name):
        nonlocal size, exceeded
        while block := await stream.read(16384):
            available = max(0, max_output - size)
            chunks[name].extend(block[:available])
            size += len(block)
            if size > max_output:
                exceeded = True
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass

    readers = [
        asyncio.create_task(drain(process.stdout, "stdout")),
        asyncio.create_task(drain(process.stderr, "stderr")),
    ]
    timed_out = False
    try:
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            timed_out = True
    finally:
        # SDK cancellation, timeout, or disconnect must not leave a writer alive.
        with anyio.CancelScope(shield=True):
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
            await asyncio.gather(*readers)
    output = {key: bytes(value).decode("utf-8", errors="replace") for key, value in chunks.items()}
    output["exit_code"] = process.returncode
    if timed_out:
        return failure(
            "timeout", "CLI timed out and was terminated; inspect the ledger before retrying a write.", **output
        )
    if exceeded:
        return failure(
            "output_limit",
            "Incomplete output: CLI terminated at output limit; inspect the ledger before retrying a write. "
            "Narrow the report or increase max_output_bytes locally.",
            truncated=True,
            **output,
        )
    return {"ok": process.returncode == 0, **output}


class Executor:
    def __init__(self, catalog, policy: Policy, config_path: Path | None = None):
        self.catalog = catalog
        self.policy = policy
        self.config_path = config_path

    async def call(self, name, arguments):
        command = self.catalog.get(name)
        if command is None:
            return failure("unknown_tool", "Tool is not in the generated CLI catalog")
        effect = None
        result = None
        try:
            command.values(arguments)
            arguments = dict(arguments)
            # JSON is normalized only for commands that actually register --json.
            # Explicit false is honored; noninteractive validation reports issues
            # without prompting, and --apply explicitly selects remediation.
            for p in command.parameters:
                if "--json" in p.click.opts and p.key not in arguments:
                    arguments[p.key] = True
            effect = effects(command, command.values(arguments))
            executable = find_executable(self.policy.executable)
            arguments, base, effect = self.policy.authorize(
                command,
                arguments,
                protected=(self.config_path, self.policy.audit_log, executable, Path(sys.executable)),
            )
            env = self.policy.child_environment(base, effect)
            if self.policy.mode != "full_access":
                env["FEDLEAVE_MCP_PROTECTED_PATHS"] = json.dumps(
                    [
                        str(canonical(p))
                        for p in (self.config_path, self.policy.audit_log, executable, Path(sys.executable))
                        if p is not None
                    ]
                )
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            result = await run_cli(
                executable, command.argv(arguments), env, self.policy.timeout_seconds, self.policy.max_output_bytes
            )
            result["format"] = "text"
            json_requested = any("--json" in p.click.opts and arguments.get(p.key) for p in command.parameters)
            eager = command.special or any(p.click.is_eager and arguments.get(p.key) for p in command.parameters)
            if json_requested and not eager and result.get("error") is None:
                try:
                    result["data"] = json.loads(result["stdout"], parse_constant=_reject_constant)
                    result["format"] = "json"
                except (ValueError, TypeError):
                    if result["ok"]:
                        result.update(
                            ok=False,
                            error="malformed_json",
                            message="CLI --json output was not valid JSON; stdout and stderr are preserved",
                        )
            if not result["ok"] and "error" not in result:
                result.update(
                    error="datastore_busy" if result["exit_code"] == 75 else "cli_error",
                    message="CLI returned a failure; inspect stdout/stderr and exit_code",
                    retryable=result["exit_code"] == 75,
                )
            return result
        except (PolicyError, CatalogError) as exc:
            result = failure("permission_denied" if isinstance(exc, PolicyError) else "invalid_arguments", str(exc))
            return result
        except (OSError, ValueError) as exc:
            result = failure("execution_error", f"{type(exc).__name__}: {exc}")
            return result
        finally:
            if effect is not None and (effect["write"] or self.policy.mode in {"unattended", "full_access"}):
                self.audit(name, result)

    def audit(self, name, result):
        """Concise outcome metadata, never descriptions or complete responses."""
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "tool": name,
            "pid": os.getpid(),
            "ok": result.get("ok") if result else False,
            "exit_code": result.get("exit_code") if result else None,
            "error": result.get("error") if result else "cancelled",
        }
        data = result.get("data") if result else None
        if isinstance(data, dict):
            record_ids = []
            for key, value in data.items():
                if key == "transaction_id" and isinstance(value, str):
                    record_ids.append(value)
                elif key.endswith("_transaction_ids") and isinstance(value, list):
                    record_ids.extend(item for item in value if isinstance(item, str))
            record["record_ids"] = list(dict.fromkeys(record_ids))
        logger.info("CLI tool outcome: %s", json.dumps(record))
        if self.policy.audit_log is not None:
            try:
                with self.policy.audit_log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record) + "\n")
            except OSError:
                logger.error("Could not append configured audit log")
