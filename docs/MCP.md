# FedLeave MCP integration

`fedleave-mcp` exposes the installed FedLeave CLI to compatible assistants,
IDEs, automation programs, and agents through the Model Context Protocol.
It uses the official Python MCP SDK **2.3.0**, pinned in `pyproject.toml`.
The SDK negotiates MCP 2026-07-28 and its supported legacy protocol versions.
The server advertises tools only; it adds no custom resources, prompts, approval
handshake, or client-specific extensions. Protocol negotiation and stdio framing
belong to the SDK, including compatibility with its supported legacy clients.

Your client launches the executable, discovers tools, calls them, and closes
the stdio connection when finished. There is no permanent background service,
HTTP/SSE listener, browser requirement, LLM subscription, or OpenClaw dependency.
Ordinary diagnostics go to stderr; stdout carries MCP messages exclusively.
The installed server and CLI contain their Python runtimes. Python and Node are
needed only if you choose the example developer clients below.

## Install and connect

Install the normal [Windows or Linux package](../README.md#installation).
The server is a sibling of `fedleave`:

| Platform | Command | Default leave data |
| --- | --- | --- |
| Windows | `C:\Program Files\FedLeave\fedleave-mcp.exe` | `%LOCALAPPDATA%\fedleave` |
| Linux | `/usr/local/bin/fedleave-mcp` | `$XDG_DATA_HOME/fedleave`, otherwise `~/.local/share/fedleave` |

Linux command links point through `/opt/fedleave/current` to the active release.
Run the connector under the leave-data owner's normal user account. It needs
no administrator account or service identity. Absolute command and policy paths
allow it to run from any working directory.

The following are **conceptual, client-neutral configuration illustrations**;
each client chooses its own surrounding configuration format. Substitute your
username and real paths. The same `mcpServers` shape is also usable with the
Inspector example below.

Linux:

```json
{
  "mcpServers": {
    "fedleave": {
      "command": "/usr/local/bin/fedleave-mcp",
      "args": ["--config", "/home/alex/.config/fedleave/mcp-policy.json"],
      "env": {},
      "cwd": "/home/alex"
    }
  }
}
```

Windows:

```json
{
  "mcpServers": {
    "fedleave": {
      "command": "C:\\Program Files\\FedLeave\\fedleave-mcp.exe",
      "args": ["--config", "C:\\Users\\Alex\\AppData\\Local\\FedLeaveMCP\\policy.json"],
      "env": {},
      "cwd": "C:\\Users\\Alex"
    }
  }
}
```

Alternatively, configure the trusted launch environment variable
`FEDLEAVE_MCP_CONFIG` with the policy file's absolute path and leave `args`
empty. `--config` takes precedence. Missing/invalid policy files and unknown
configuration keys fail startup; they do not enable a more permissive mode.
Without either setting, the default is read-only access to the user's default
datastore. `fedleave-mcp --version` prints the build version and exits;
`fedleave-mcp --inventory` prints a strict parity report and exits. These are
diagnostic invocations, separate from normal protocol traffic.

## Trusted permissions and unattended agents

Keep the policy outside your leave-data directory and outside model-writable
directories. Protect it using your operating system's file permissions. Tool
arguments cannot change the mode, executable, permissions, or environment.
The catalog always contains all tools; permission checks occur at invocation.
No filtering mode is currently implemented.

For a new read-only connector, a policy can be as small as:

```json
{
  "mode": "read_only",
  "data_dir": "/home/alex/.local/share/fedleave"
}
```

To authorize ordinary agent writes indefinitely, make this **one local change**:

```json
{
  "mode": "unattended",
  "data_dir": "/home/alex/.local/share/fedleave"
}
```

Authorized add, set-day, reconcile, correction, initialization, starting-balance,
accrual-change, and expiration-extension operations then run immediately.
There are no per-call approvals, PINs, browser actions, or active human-session
requirements. Unattended mode never falls back to requesting confirmation.

Additional permissions are independent and default to false:

| Setting | Authority it grants |
| --- | --- |
| `allow_high_impact` | Deletion (`void`), force-balance, rollover application, and `import-data --overwrite` |
| `allow_imports` | JSON archives, single-year backups, WMS HTML reports, and holiday ICS imports |
| `allow_file_output` | Exporting archives to permitted output paths |
| `allow_network` | Update checks and initialization with the OPM ICS network source |
| `allowed_tools` | Optional list of exact generated tool names; omitted means all otherwise permitted tools |
| `denied_tools` | Tool names to deny even when otherwise allowed |

For example, a restricted agent that can read balances, add leave, reconcile,
correct, and import approved reports:

```json
{
  "mode": "unattended",
  "data_dir": "/home/alex/.local/share/fedleave",
  "allowed_tools": [
    "fedleave_balance", "fedleave_list", "fedleave_years", "fedleave_add",
    "fedleave_reconcile", "fedleave_correct", "fedleave_import_wms_http"
  ],
  "allow_imports": true,
  "file_read_roots": ["/home/alex/FedLeaveReports/incoming"],
  "audit_log": "/home/alex/.config/fedleave/mcp-audit.jsonl"
}
```

Enable high-impact operations locally with `"allow_high_impact": true` if your
agent is authorized to perform them. They still need to pass the tool allowlist
and any applicable import permission. Previewing rollover is classified
separately from applying it; validation with `apply: true` is a write.
`holidays` currently uses an `action` field: `list`, `generate`, or `import-ics`.
It is not a nested CLI command in the current application.

`confirm_writes` is an optional denial mode: reads work, but writes return a
clear error because the server has no verified universal client approval
handshake. A model's statement that a human approved something grants no
authority. Use `unattended` for authorized autonomous work.

### Data directories and file access

`data_dir` fixes the selected datastore. The CLI's `--data-dir` remains in each
applicable schema, but a caller can select only that directory or an exact
canonical directory in `allowed_data_dirs`. Alternate spellings resolve to the
same path. The selected directory also becomes the child CLI's startup default,
so its eager migration cannot touch an unrelated default store.

File inputs require a location under `file_read_roots`; exports require
`file_write_roots` and `allow_file_output`. Empty root lists deny file access.
For example, add `"file_write_roots": ["/home/alex/FedLeaveReports/exported"]`
and `"allow_file_output": true` to permit archive exports. Existing output
files can be replaced: use a dedicated export directory.

Paths are expanded/resolved immediately before execution. Escaping symlinks,
datastores containing protected policy/executable/audit files, and export paths
targeting those files are rejected. Exporting over files inside an authorized
datastore is also denied. Do not authorize filesystem roots, your installation
directory, or folders containing security configuration as report roots.

The storage layer checks write boundaries again in restricted CLI children.
Path checks reduce traversal/symlink attacks but are not an OS sandbox: a
separate process with the same filesystem privileges can race path checks or
edit source, executables, or policy directly. Use OS permissions and isolated
accounts for stronger boundaries, and do not give an agent other file-editing
tools that can rewrite its own policy or installed application.

### Reads that require maintenance

Existing CLI reads may remove legacy history, synchronize expirations, or post
missing accruals. In read-only and confirm-writes modes, a storage write guard
refuses those writes and reports that maintenance is required. It does not
silently persist them or calculate balances using a second implementation.
Perform the maintenance through the normal CLI or an authorized unattended
connector, then retry the read. Unattended reads retain normal CLI maintenance
behavior. Lock files/directories are coordination metadata, separate from
leave-record writes.

### Remaining trust boundary

Descriptions, notes, reports, ICS content, CLI output, and tool arguments are
untrusted data. Subprocess argv uses registered metadata and argument arrays;
there is no shell, free-form command input, model-selected executable, or
model-provided environment override. Leading dashes in option values are
encoded as `--option=value`; positional values use Click's `--` separator.

These protections prevent shell/option injection. They cannot determine why an
LLM requested a permitted operation: prompt injection in an imported report can
still persuade an agent to misuse authority it already has. Bound that authority
with tool permissions, exact data stores, file roots, and separate high-impact
permissions. Authentication and authorization for any remotely reachable agent
belong to its external bridge; FedLeave opens no remote endpoint.

## Discovery, arguments, and results

`tools/list` is generated from the real Typer/Click registry at startup.
There is one stable tool per executable command path, plus `fedleave_version`.
The current inventory has **31 tools and 273 parameter entries**, including
inherited parameters and automatically registered help options. The 30 CLI
command paths include the compatibility alias `use-or-loose`.

Tool names normalize the full path: `starting-balance set` becomes
`fedleave_starting_balance_set`. Collisions receive deterministic hash suffixes.
Types, required fields, defaults, help, repeated values, tuple arity, ranges,
choices, flags, and inverted flags come from CLI metadata. String options whose
valid values are checked inside CLI business code remain strings in JSON
Schema; the CLI remains responsible for those validations and cross-field rules.
Unsupported parameter types fail discovery rather than silently disappearing.

Logical input names follow the CLI Python parameter names, such as `as_of`,
`json_output`, `annual_comment`, and `data_dir`. The schema records original
spellings in `x-cli-options` and `x-cli-secondary-options`. To select a particular
registered alias, use the generated `_cli_aliases` object, for example:

```json
{
  "year": 2026,
  "show_transaction_ids": true,
  "_cli_aliases": {"show_transaction_ids": "--ShowTransactionIDs"}
}
```

Only registered aliases are accepted. For a negative alias such as
`--no-authoritative`, its logical boolean must be false. Duplicate parameter
names at different command scopes are qualified with `__`; help fields such as
`root__help` and `add__help` distinguish root help from command help. The schema
allows eager help/version requests without normally required command arguments.

Example `tools/call` parameter objects (SDKs provide the protocol envelope):

```json
{"name":"fedleave_balance","arguments":{"year":2026,"as_of":"2026-07-01"}}
```

```json
{"name":"fedleave_add","arguments":{"date":"2026-07-01","category":"annual","used":2,"description":"Appointment"}}
```

```json
{"name":"fedleave_set_day","arguments":{"date":"2026-07-02","authoritative":true,"annual":-4,"annual_comment":"Leave","sick":0}}
```

```json
{"name":"fedleave_starting_balance_set","arguments":{"year":2026,"category":"annual","hours":120,"reason":"Opening balance"}}
```

For commands that register `--json`, omission of `json_output` automatically
requests JSON. Explicit `json_output: false` preserves text output. Validation
without `apply: true` requires JSON mode to avoid its interactive remediation
prompt. Stdin is never forwarded and no prompt is automatically answered.

Results contain the same envelope in MCP text content and `structuredContent`:
`ok`, `exit_code`, `stdout`, `stderr`, and `format`. JSON-capable responses also
contain parsed `data`. Text is labeled `format: "text"`; human tables are never
guessed to be JSON. Nonzero CLI exits, invalid JSON on a successful JSON call,
permission failures, and unknown tools return MCP `isError: true`.
CLI warnings and meaningful return codes remain available in the envelope.

## Standard Python SDK client

Install the SDK in your **client development environment** with
`python -m pip install "mcp==2.3.0"`. This is not needed to use an installed
FedLeave package with an existing MCP client.

```python
import asyncio
from mcp import Client, StdioServerParameters

async def main():
    parameters = StdioServerParameters(
        command="/usr/local/bin/fedleave-mcp",
        args=["--config", "/home/alex/.config/fedleave/mcp-policy.json"],
        cwd="/home/alex",
    )
    async with Client(parameters, read_timeout_seconds=90) as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools.tools])
        result = await client.call_tool(
            "fedleave_balance", {"year": 2026, "as_of": "2026-07-01"}
        )
        if result.is_error:
            raise RuntimeError(result.structured_content)
        print(result.structured_content["data"])

asyncio.run(main())
```

On Windows, substitute the executable and policy paths using Python raw strings.
Downstream developers use the same lifecycle and standard methods; no agent
framework or model provider is required. Refresh `tools/list` after upgrading
FedLeave instead of caching schemas indefinitely.

## MCP Inspector

The independent [MCP Inspector CLI](https://github.com/modelcontextprotocol/inspector/tree/main/clients/cli)
can use a configuration file with the `mcpServers` example above. With a suitable
Node runtime installed, run:

```bash
npx -y @modelcontextprotocol/inspector@2.12.0 --cli \
  --config client.json --server fedleave --method tools/list

npx -y @modelcontextprotocol/inspector@2.12.0 --cli \
  --config client.json --server fedleave --method tools/call \
  --tool-name fedleave_balance --tool-args-json '{"year":2026}'
```

`client.json` is the Inspector's connection configuration. Its `args` points to
the **separate FedLeave policy**. Inspector CLI mode connects over stdio and
does not require opening its web UI. The Python SDK test client is mandatory in
CI; Inspector is a separate interoperability check, not a server dependency.

### Optional OpenClaw bridge

OpenClaw is not required or imported. No OpenClaw installation/version is
available in the test environment, so this project does not claim a tested
OpenClaw adapter or prescribe unverified OpenClaw commands. If your particular
OpenClaw version needs an external MCP bridge, configure that bridge according
to its own versioned documentation with the executable, argument list, and
policy shown above. The bridge owns client authentication and tool routing;
FedLeave remains the same standard stdio server used by other clients.

## Synchronization, limits, and operations

Every CLI leaf command holds an OS-backed `.fedleave.lock` in its canonical
data directory for the entire command invocation. Startup migrations also
acquire that lock. The MCP parent does not acquire a competing lock, avoiding
parent/child deadlocks. Existing GUI ledger writes use CLI subprocesses and
therefore participate. GUI preference files are separate from ledger writes.

The pinned `portalocker==3.2.0` dependency provides Windows and POSIX locking.
Process exit, crash, timeout termination, or cancellation releases ownership.
The lock file remains and must not be deleted during use. Different data
directories have independent locks. These are advisory locks on local
filesystems; old FedLeave binaries and third-party direct storage writers do
not participate. Upgrade all writers and do not share a writable store with
older uncoordinated processes. Custom Python storage users must hold
`fedleave.locking.datastore_lock` around their entire read/modify/write operation.
Network filesystem locking semantics are outside the validated deployment.

The policy accepts `timeout_seconds` (default 60, maximum 3600),
`lock_timeout_seconds` (default 30), and `max_output_bytes` (default 1 MiB,
maximum 16 MiB). Both output streams share the byte budget. MCP envelope/JSON
encoding adds bounded overhead to that CLI capture budget.

| Failure | Meaning and response |
| --- | --- |
| `datastore_busy`, CLI exit 75 | Lock wait expired; retry after the active command completes |
| `permission_denied` | Change trusted local policy only if the operation should be authorized |
| `invalid_arguments` | Correct types, required fields, aliases, or unknown inputs using the discovered schema |
| `cli_error` | Inspect preserved CLI exit code/stdout/stderr; business validation remains authoritative |
| `malformed_json` | CLI promised JSON but emitted invalid JSON; preserved streams help diagnose it |
| `timeout` | Child was killed; inspect ledger state before retrying a write |
| `output_limit` | Output is incomplete and marked truncated; narrow the report or increase the configured budget |
| `execution_error` | Check installation, filesystem permissions, or the administrator-set `executable` override |

Timeouts and output limits can occur after a command committed a write; the
server does not promise rollback. Client cancellation kills/reaps the child.
Set client timeouts longer than the server's configured command timeout.
For development, `executable` may specify an absolute CLI path in the trusted
policy; tools cannot select one. Normal discovery prefers the sibling CLI and
then `PATH`. Keep the server and CLI from the same installation.
Windows overrides must identify an `.exe`, since batch files can introduce
implicit shell parsing even when subprocess shell mode is disabled.

Optional `audit_log` appends JSON lines with UTC time, tool, PID, outcome, exit
code, and affected transaction IDs when available. Default stderr diagnostics
also contain concise outcome metadata, never complete descriptions, reports,
or argument lists. Returned results do contain leave data: protect client logs.
Audit files are not immutable transaction history, and a process ID is not an
authenticated agent identity. Keep audit paths outside data stores and rotate
files using local administration if needed.

## Design and verification

Discovery walks `typer.main.get_command(app)` recursively, including executable
groups and inherited parameters. It does not scrape help or duplicate command
signatures. `catalog.py` owns metadata/schema/argv conversion; `policy.py`
layers reviewed side-effect classifications and launch-time authority over that
catalog; `execution.py` runs bounded subprocesses; `server.py` supplies the SDK
list/call handlers. The CLI remains the only application behavior interface.

The machine-readable inventory includes command paths, tool names, aliases,
types, defaults, arity, requiredness, callbacks, prompts, schemas, classifications,
JSON capability, version/build identity, and a deterministic fingerprint. CI
runs strict discovery and uploads `mcp-inventory.json` for both platforms.
Unknown commands remain visible but fail execution until reviewed. Unsupported
types stop discovery. A reviewed fingerprint in `tests/fixtures/mcp-parity.json`
detects metadata drift; changing it requires reviewing CLI behavior and policy.
Adding a command or parameter requires no new MCP tool functions.

Run the checks from an editable developer installation:

```bash
python -m fedleave.mcp --inventory > mcp-inventory.json
pytest -q tests/test_mcp_catalog.py tests/test_mcp_execution.py \
  tests/test_mcp_policy.py tests/test_mcp_protocol.py tests/test_datastore_locking.py
python scripts/lib/common/mcp_smoke.py --server /absolute/path/to/fedleave-mcp
```

The smoke client initializes a temporary store, checks complete discovery,
reads balances, adds/reconciles/corrects leave, calls nested and set-day tools,
verifies policy denials, and closes the connection. Distribution CI runs it
against the **installed** Windows and Linux executables before publication,
alongside existing package integrity and user-data-preservation checks.
Routine tests use local fixtures and need no network calls. Sandboxes that
restrict the SDK's asynchronous pipe/thread notifications may require running
stdio integration tests outside those restrictions; the server itself binds
no network socket.

The official MCP SDK and its `mcp-types` package use the MIT license;
Portalocker uses BSD-3-Clause. They permit redistribution in the existing
self-contained installers; the package metadata/license files are collected
with those dependencies. Other bundled runtime dependencies retain their own
upstream license notices.
