# FedLeave MCP integration

`fedleave-mcp` is an efficient, typed, discoverable interface to the **full
FedLeave CLI** for authorized autonomous agents, assistants, IDEs, and automation
programs. The CLI remains authoritative for application behavior. MCP adapts
that interface; it does not add a separate application approval authority.

**No policy file is required. A policy-free launch selects `full_access`: the
same CLI authority as the launching OS user, including modifying/deleting data,
force-balance, rollover application, import overwrite, file inputs/exports,
network operations, and alternate datastores. There are no MCP approval prompts,
opt-in permission switches, or mandatory backups in this mode.** Optional
restricted profiles are described below. Full access grants neither OS
administrative privileges nor arbitrary shell execution.

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
no administrator account or service identity. Absolute executable paths
allow it to run from any working directory.

These minimal configurations work with clients that accept `mcpServers`,
including the Inspector example below. Other clients may use a different
surrounding format; the command and empty argument list stay the same.
Do not set `FEDLEAVE_MCP_CONFIG` for a policy-free launch.

Linux:

```json
{
  "mcpServers": {
    "fedleave": {
      "command": "/usr/local/bin/fedleave-mcp",
      "args": []
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
      "args": []
    }
  }
}
```

The ordinary CLI datastore default applies exactly, including platform
environment variables. No MCP-only directory is selected. A tool's `data_dir`
argument can select any datastore accepted by the CLI under the same OS account.
Startup performs no datastore migration. Each command uses its selected store exclusively.

For an optional policy, add `"args": ["--config", "/absolute/path/policy.json"]`
(escape Windows backslashes in JSON), or configure the trusted launch environment
variable `FEDLEAVE_MCP_CONFIG`. `--config` takes precedence. Explicitly supplied
missing/invalid files, invalid field types, and unknown configuration keys fail
startup on stderr; they never fall back to full access.
`fedleave-mcp --version` prints the build version and exits;
`fedleave-mcp --inventory` prints a strict parity report and exits. These are
diagnostic invocations, separate from normal protocol traffic.

## Full access and optional restricted profiles

An explicit policy containing only `{"mode":"full_access"}` grants the same
authority as no policy. Execution limits, an optional audit log, and a trusted
executable override can be configured in this mode. Restrictive fields are
incompatible and rejected, even when explicitly false or empty: `data_dir`,
`allowed_data_dirs`, `file_read_roots`, `file_write_roots`, `allowed_tools`,
`denied_tools`, `allow_high_impact`, `allow_imports`, `allow_file_output`, and
`allow_network`. Select a restricted mode when you want those controls.

Existing policy files retain their profiles: `read_only`, `unattended`, and
`confirm_writes` do not become full access. **An explicit policy file with no
`mode`, including `{}`, retains its historical `read_only` default.** Users who
previously launched without a policy must add a read-only policy to retain that
restriction after upgrading. `unattended` still means the restricted profile
with independent permission switches; it is not an alias for full access.

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

For a restricted connector that authorizes ordinary writes:

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

In restricted modes, additional permissions are independent and default to false:

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

In restricted modes, `data_dir` fixes the selected datastore. The CLI's `--data-dir` remains in each
applicable schema, but a caller can select only that directory or an exact
canonical directory in `allowed_data_dirs`. Alternate spellings resolve to the
same path. The selected directory also becomes the child CLI's startup default,
so every operation stays within the selected store.

File inputs require a location under `file_read_roots`; exports require
`file_write_roots` and `allow_file_output`. Empty root lists deny file access.
For example, add `"file_write_roots": ["/home/alex/FedLeaveReports/exported"]`
and `"allow_file_output": true` to permit archive exports. Existing output
files can be replaced: use a dedicated export directory. To permit a second
datastore, add `"allowed_data_dirs": ["/home/alex/FedLeaveTestData"]`.

In these restricted profiles, paths are expanded/resolved immediately before execution. Escaping symlinks,
datastores containing protected policy/executable/audit files, and export paths
targeting those files are rejected. Exporting over files inside an authorized
datastore is also denied. Do not authorize filesystem roots, your installation
directory, or folders containing security configuration as report roots.
Protected-file checks also compare file identity to reject hard-link aliases,
including before creating backups.

In `full_access`, none of those MCP filesystem authorization checks or child
write guards apply. Inputs, outputs, backups, overwrite behavior, and datastore
selection have ordinary CLI semantics under OS permissions. Existing CLI
validation and storage protections still apply. File paths are passed as literal
argv values rather than expanded or rewritten by an MCP sandbox.

The storage layer checks write boundaries again in restricted CLI children.
Path checks reduce traversal/symlink attacks but are not an OS sandbox: a
separate process with the same filesystem privileges can race path checks or
edit source, executables, or policy directly. Use OS permissions and isolated
accounts for stronger boundaries, and do not give an agent other file-editing
tools that can rewrite its own policy or installed application.

### Read-only accounting

Reports, discovery and previews resolve legacy history, missing accruals,
expiration events and linked carryovers on private snapshots. They never persist
maintenance changes or create missing lock files/directories. Existing shared
locks coordinate with CLI writers. Read-only connectors can inspect legacy data
without a separate maintenance pass. `fedleave_snapshot` exposes the same
canonical state to chart/analytics consumers. Creation and reconciliation preview
flags are side-effect-free; explicit apply remains governed by launch policy.
Full-access children clear inherited MCP datastore pins/write guards;
restricted children receive their own trusted boundaries.

### Remaining trust boundary

Descriptions, notes, reports, ICS content, CLI output, and tool arguments are
untrusted data. Subprocess argv uses registered metadata and argument arrays;
there is no shell, free-form command input, model-selected executable, or
model-provided environment override. Leading dashes in option values are
encoded as `--option=value`; positional values use Click's `--` separator.

These protections prevent shell/option injection. They cannot determine why an
LLM requested a permitted operation: prompt injection in an imported report can
still persuade an agent to misuse authority it already has. Bound that authority
with optional restricted tool permissions, exact data stores, file roots, and
separate high-impact permissions when appropriate. Tool descriptions are also
untrusted data, and annotations are guidance rather than authorization controls.
Authentication and authorization for any remotely reachable agent
belong to its external bridge; FedLeave opens no remote endpoint.

An agent that can already execute `fedleave` directly under the same account
can bypass MCP-only restrictions. A client without shell access may receive
substantial authority solely through MCP, so optional profiles are meaningful
for that deployment. The trusted boundary is the OS user/process configuration
that launches the connector, never an LLM's arguments or statements of approval.
A full-access agent or another OS tool may be able to overwrite policy, audit,
or application files using the account's filesystem permissions; MCP policy is
not an OS sandbox. Tools cannot supply a new policy or executable/environment
override as command arguments.

Backups remain the user's or agent's responsibility. `fedleave_export_data`
creates a portable backup; `fedleave_import_data` restores/imports archives and
single-year backups, including overwrite when requested. Consider exporting a
backup before high-impact work. MCP never inserts an automatic backup, restore,
or confirmation workflow; the CLI's existing storage backups remain unchanged.

## Discovery, arguments, and results

`tools/list` is generated from the real Typer/Click registry at startup.
There is one stable tool per executable command path, plus `fedleave_version`.
The current inventory has **33 tools and 298 parameter entries**, including
inherited parameters and automatically registered help options. The 32 CLI
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

Full-access examples, without any permission switches or file roots:

```json
{"name":"fedleave_export_data","arguments":{"output":"/home/alex/Backups/leave backup.json"}}
```

```json
{"name":"fedleave_import_data","arguments":{"input":"C:\\Users\\Alex\\Backups\\leave.json","overwrite":true,"data_dir":"C:\\Users\\Alex\\FedLeaveTest"}}
```

```json
{"name":"fedleave_void","arguments":{"id":"20260701-001","reason":"Entered in error"}}
```

```json
{"name":"fedleave_rollover","arguments":{"from_year":2026,"to_year":2027,"preview":false}}
```

For commands that register `--json`, omission of `json_output` automatically
requests JSON. Explicit `json_output: false` preserves text output. Noninteractive
validation reports issues without prompting in either format; `apply: true`
explicitly requests fixes. Interactive CLI terminals retain per-file confirmation.
CLI stdin is a closed pipe, providing noninteractive EOF on Windows and Linux.
Stdin is never forwarded and no prompt is automatically answered. Validation
retains CLI exit 2 when issues were found, even if requested fixes were applied.

Annotations describe the CLI's effects: reports use read-only snapshots, while
conditional tools such as rollover, reconciliation, correction and validation
can write when explicitly applied. Static annotations cannot change per
invocation; creation/reconciliation `preview: true` performs no datastore
maintenance or writes. Restricted child guards also enforce filesystem policy.

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
        args=[],  # No policy: full CLI authority for this OS user.
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

On Windows, substitute the executable path using a Python raw string.
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

`client.json` is the Inspector's connection configuration. Its `args` can be
empty for full access or point to an optional separate FedLeave policy.
Inspector CLI mode connects over stdio and
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
| `permission_denied` | An optional restricted profile denied the call; change trusted local policy only if appropriate |
| `invalid_arguments` | Correct types, required fields, aliases, or unknown inputs using the discovered schema |
| `cli_error` | Inspect preserved CLI exit code/stdout/stderr; business validation remains authoritative |
| `malformed_json` | CLI promised JSON but emitted invalid JSON; preserved streams help diagnose it |
| `timeout` | Child was killed; inspect ledger state before retrying a write |
| `output_limit` | Output is incomplete and marked truncated; narrow the report or increase the configured budget |
| `execution_error` | Check installation, filesystem permissions, or the administrator-set `executable` override |

Timeouts, output limits, and cancellation can occur after a command committed a
write; inspect ledger state before retrying. The server neither retries writes
automatically nor promises rollback. Client cancellation kills/reaps the child.
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
layers optional side-effect restrictions and launch-time authority over that
catalog; `execution.py` runs bounded subprocesses; `server.py` supplies the SDK
list/call handlers. The CLI remains the only application behavior interface.

The machine-readable inventory includes command paths, tool names, aliases,
types, defaults, arity, requiredness, callbacks, prompts, schemas, classifications,
JSON capability, version/build identity, and a deterministic fingerprint. CI
runs strict discovery and uploads `mcp-inventory.json` for both platforms.
New registered commands execute automatically in full access without a manual
classification. In restricted profiles, unknown commands remain visible but
fail execution until reviewed. The inventory reports that classification;
it does not prevent full-access startup or execution. Unsupported
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
checks concurrent writes from two independent stdio servers, and exercises
policy-free deletion, force-balance, export/import overwrite, and rollover to an
alternate datastore. A second run verifies restricted unattended behavior and
policy denials. Both runs check noninteractive text validation and explicit fixes
on a temporary malformed date, then close the connections. Distribution CI runs them
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
