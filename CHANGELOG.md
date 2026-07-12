# Changelog

## Unreleased

- Store only final transaction data: authoritative writes delete superseded rows, corrections update in place, and `void` deletes its target while retaining the legacy command name.
- Automatically remove legacy voided transactions and transaction audit fields when leave-year files are loaded, exported, or imported.

## 0.2.0 - 2026-06-15

- Release: include human-friendly correction lookup (`--search-date`/`--search-type`), ODT reports with embedded charts, date-specific balance and activity queries, rollover and holidays improvements, and related tests.

## Unreleased - 2026-06-15

- Populate report summary from actual balances.
