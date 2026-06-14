# Changelog

## Unreleased - 2026-06-13

- Add `rollover` and `holidays` CLI subcommands (preview & apply).
- Improve `correct` and `void` commands with tests and preview support.
- Add unit tests for corrections, voiding, and rollover preview/apply.
- Harden `rollover`: create starting-balance transactions, generate pay periods, set rollover timestamp, and generate holiday cache for new year.
