# Changelog

## Unreleased

- Add a session-only What-if Planner under Analysis > Planning, with canonical baseline/scenario daily balances, reserves, lot effects, capacity conflicts, provenance, and atomic JSON/CSV exchange.
- Reuse read-only snapshots with explicit schedule/holiday context; keep canonical leave data unchanged through editing, imports/exports, cancellation, and close.
- Exclude PySide6 6.12 from GUI installs and packages after reproducing native table-rendering reference corruption on Python 3.11; exercise repeated planner rendering and clean process exit in a subprocess regression.

- Keep all monthly report abbreviations and full category names inside their panel in PDF, print, SVG, and PNG output, with room for the marker legend below.

- Fix Linux GLIBC compatibility after the moving Ubuntu runner bundled GLIBC 2.43 dependencies: pin the build baseline, audit every bundled ELF, and gate publication on released CLI/Calendar/Analytics launches in independent Ubuntu/Debian containers.

- Add a second Seasonality selector for per-type usage and genuine earned/restored credits across month, weekday and actual pay-period groupings, with consistent charts, sorted drilldowns and exports.
- Exclude carried lots and uncertain credit copies from new-earning totals, retain zero-activity supported choices, and preserve the existing overtime/net views and other Analytics tabs.

- Add Paid Parental Leave earned/use windows and usage-only FMLA tracking, with one derived FMLA contribution per PPL use and no duplicate physical absence.
- Preserve source grant identity, overlapping event limits, schedule conversions and first-use FMLA periods across existing leave-year files, including source corrections after successor creation.
- Add Calendar PPL Earn/Use with an editable 480-hour suggestion, FMLA Use only, expiration/coverage diagnostics and explicit acknowledgement of potential duplicate same-day tracking.
- Report provisional scheduled usage, confirmed periods and unknown history capacity; reject PPL payout/extension and FMLA grant/force-balance bypasses.

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
