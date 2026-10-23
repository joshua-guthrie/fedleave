# Changelog

## Unreleased

- Support independent manual creation and explicit CLI-previewed prior-year carryover in CLI and Calendar, with create-only destinations and GUI-only manual confirmation.
- Correct adjacent 26/27-period boundaries, single-count openings, credit caps, nonexpiring award carryover, stable lot origins and inclusive expiration deadlines.
- Resolve reports/charts on read-only linked snapshots; legacy migrations and missing accruals are computed in memory during queries.
- Detect stale carryovers and explicitly reconcile complete successor chains with genuine activity preserved, backups, preview fingerprints and interruption recovery.

- Default policy-free MCP launches to full CLI access for authorized agents, including destructive operations, imports/exports, network calls, and alternate datastores. Keep existing restricted policy files and add explicit `full_access` configuration.
- Execute newly registered CLI commands automatically in full-access MCP sessions while retaining typed arguments, subprocess limits, locking, and optional restricted permissions.
- Report validation issues without prompting on noninteractive CLI/MCP input; `--apply` explicitly requests fixes.

## 0.2.1 - 2026-07-27

- Guide first-time GUI users into the new-leave-year workflow instead of showing a missing-year backend error.
- Keep the backend, GUI, analytics, charts, reports, build metadata, and installers on one application version.
- Store only final transaction data: authoritative writes delete superseded rows, corrections update in place, and `void` deletes its target while retaining the legacy command name.
- Automatically remove legacy voided transactions and transaction audit fields when leave-year files are loaded, exported, or imported.

## 0.2.0 - 2026-06-15

- Release: include human-friendly correction lookup (`--search-date`/`--search-type`), ODT reports with embedded charts, date-specific balance and activity queries, rollover and holidays improvements, and related tests.

## Unreleased - 2026-06-15

- Populate report summary from actual balances.
