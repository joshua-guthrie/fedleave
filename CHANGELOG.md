# Changelog

## Unreleased - 2026-06-13

- Add `rollover` and `holidays` CLI subcommands (preview & apply).
- Improve `correct` and `void` commands with tests and preview support.
- Add unit tests for corrections, voiding, and rollover preview/apply.
- Harden `rollover`: create starting-balance transactions, generate pay periods, set rollover timestamp, and generate holiday cache for new year.
- Add `reports` command and ODT template-based report generation with embedded leave summary and chart support.
- Add `balance --as-of` and `activity --date` for date-specific leave balances and daily earned/used activity.
