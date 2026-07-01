# fedleave

Federal leave and time tracker.

This project is a command-line application for tracking federal-style leave balances and generating pay period calendars.

The hope is that it is not only useful at the CLI, but could become the basis of larger leave tracking applications (web apps or GUIs).

Note:  In-case you're wondering... it was a 100% at home project.  None of it was done on company time!   It was also my first experiemnt into vibe coding.  So far, I'm impressed.

It's a little program I'm using to serve as a back end to an AI agent and a dashboard and figured it may be useful to someone else.

## Limitations
I'm making no effort to track expiring leave, such as travel comp time, award leave, etc.  I've never had the problem in my personal life of having to worry about leave expiring ! :)

The program is entirely single user.  I suppose it could be made into a multiple user system with seperate data files for each user, but that has never been my use case.  At your own peril.

I would not be using this application for any thing critical.  For me, it's a fun little experiement.

## Setup

Linux / macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

## Commands

Run `fedleave --help` after installation.

## Typical workflow

Initialize a leave year. The leave year start date should be the first day of pay period 1 for that leave year. Annual leave accrual is configured per pay period; sick leave accrues at 4 hours per pay period.

```bash
fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-accrual 6 --annual-start 120 --sick-start 180
```

Record leave usage and overtime as it happens:

```bash
fedleave add --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
fedleave add --date 2026-03-12 --category overtime --worked 3 --description "Release support"
fedleave add --year 2026 --date 2026-03-10 --category annual --used 3 --status reconciled --authoritative --description "Actual leave used"
```

Check balances. Missing automatic annual and sick accrual transactions are posted through the balance date.

```bash
fedleave balance --year 2026 --as-of 2026-06-01
```

Check what was earned, used, and worked during the pay period containing a date:

```bash
fedleave pay-period --year 2026 --date 2026-06-01
fedleave pay-period --year 2026 --date 2026-06-01 --daily
fedleave pay-periods --year 2026
```

Export or restore data:

```bash
fedleave export-data --output fedleave_backup.json
fedleave import-data --input fedleave_backup.json --data-dir /path/to/new_data
```

Validate and normalize stored JSON data:

```bash
fedleave validate --data-dir ~/.local/share/fedleave --apply
```

## CLI Detailed Help

This section provides complete usage examples and command syntax for the `fedleave` CLI.

Usage:

	fedleave COMMAND [OPTIONS]

Commands and common options:

	init
		Initialize the data directory and create a leave year JSON file.

		Syntax:
			fedleave init --year YEAR --leave-year-start YYYY-MM-DD [--annual-accrual FLOAT] [--annual-start FLOAT] [--sick-start FLOAT] [--comp-start FLOAT] [--credit-start FLOAT] [--travel-comp-start FLOAT] [--holiday-source python_holidays|opm_ics] [--holiday-ics-url URL] [--data-dir PATH]

		Defaults:
			--annual-accrual 6.0
			--annual-start 0.0
			--sick-start 0.0
			--comp-start 0.0
			--credit-start 0.0
			--travel-comp-start 0.0
			--time-off-award-start 0.0
			--religious-comp-start 0.0
			--restored-annual-start 0.0
			--holiday-source python_holidays
			--holiday-ics-url https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/holidays.ics
			--data-dir ~/.local/share/fedleave

		Example:
			fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-accrual 6 --annual-start 120 --sick-start 180 --data-dir ~/.local/share/fedleave

		Optional OPM ICS holiday import:
			fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-accrual 6 --annual-start 120 --sick-start 180 --holiday-source opm_ics --holiday-ics-url https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/holidays.ics --data-dir ~/.local/share/fedleave

	add
		Add a transaction to a leave year ledger.

		Syntax:
			fedleave add [--year YEAR] --date YYYY-MM-DD --category CATEGORY (--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS) [--description TEXT] [--status STATUS] [--source SOURCE] [--authoritative] [--json] [--show-transaction-ids] [--data-dir PATH]

		Defaults:
			--status planned
			--source manual
			--data-dir ~/.local/share/fedleave

		Notes:
			- `--year` is optional; if omitted, the leave year is inferred from the transaction date using each leave-year file's `leave_year_start` and `leave_year_end`.
			- Exactly one of `--earned`, `--used`, `--worked`, or `--adjusted` must be provided.
			- `--authoritative` voids active transactions with the same date, category, and direction before adding the new transaction.
			- `--json` emits the created transaction ID and any replaced transaction IDs.
			- Transaction IDs are hidden by default in human-readable output. Use `--show-transaction-ids` or `--ShowTransactionIDs` when needed.
			- Valid categories include: annual, sick, overtime, comp, credit, travel_comp, admin, lwop, military, court, religious_comp, time_off_award, excused, holiday, flex, other, restored_annual.

		Examples:
			fedleave add --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
			fedleave add --date 2026-03-12 --category overtime --worked 3
			fedleave add --year 2026 --date 2026-03-10 --category annual --used 3 --status reconciled --authoritative --description "Actual leave used"

	reconcile
		Add or update a transaction from a payroll, clocking, or recurring reconciliation source.

		Syntax:
			fedleave reconcile --date YYYY-MM-DD --category CATEGORY --direction DIRECTION --hours HOURS --reason TEXT [--status STATUS] [--source SOURCE] [--id TRANSACTION_ID] [--json] [--data-dir PATH]

		Defaults:
			--status reconciled
			--source clocking-report

		Notes:
			- The leave year is inferred from the transaction date using each leave-year file's `leave_year_start` and `leave_year_end`.
			- If no active transaction exists for the same date, category, and direction, a new transaction is added.
			- If exactly one active match exists, it is updated in place and a `reconcile_history` entry records the previous hours, status, source, and description.
			- If multiple active matches exist, the command exits without writing and prints the matching IDs; rerun with `--id TRANSACTION_ID` to choose one.
			- `--json` emits a machine-readable result for automation.

		Example:
			fedleave reconcile --date 2026-03-10 --category credit --direction earned --hours 1.5 --status reconciled --source clocking-report --reason "March clocking report"

	starting-balance
		Set a leave year's starting balance for one category and keep audit history.

		Syntax:
			fedleave starting-balance set --year YEAR --category CATEGORY --hours HOURS --reason TEXT [--data-dir PATH]

		Notes:
			- The command updates `starting_balances[CATEGORY]` in the leave-year JSON.
			- Each change appends a dated entry to `starting_balance_history` with the old value, new value, reason, and carryover decision.
			- If `carryover_from_previous_year[CATEGORY]` still equals the old starting balance, it is updated to the new value too.
			- Existing JSON backups are created before the leave-year file is rewritten.

		Example:
			fedleave starting-balance set --year 2026 --category annual --hours 193.6 --reason "Corrected imported starting balance"

	export-data
		Export config, leave year files, and holiday cache to a portable JSON archive.

		Syntax:
			fedleave export-data --output PATH [--data-dir PATH]

	import-data
		Import an archive created by `export-data`.

		Syntax:
			fedleave import-data --input PATH [--overwrite] [--data-dir PATH]

		Notes:
			- Existing files are preserved by default.
			- Use `--overwrite` to replace existing files; overwritten files are backed up first.

	list
		List transactions for a leave year.

		Syntax:
			fedleave list --year YEAR [--show-transaction-ids] [--data-dir PATH]

		Notes:
			- Transaction IDs are hidden by default in human-readable output. Use `--show-transaction-ids` or `--ShowTransactionIDs` when you need them for correction, voiding, or audit work.

	balance
	Show leave balances for a year, optionally as of a given date, projected to year end, and/or with use-or-lose calculations.

	Syntax:
		fedleave balance --year YEAR [--as-of YYYY-MM-DD] [--project] [--project-to YYYY-MM-DD] [--use-or-lose] [--json] [--data-dir PATH]

	Notes:
		- `--year YEAR` reads the leave year file and computes balances from all recorded transactions.
		- `--as-of YYYY-MM-DD` computes balances using only transactions on or before that date.
		- Missing automatic annual and sick leave accrual transactions are posted through `--as-of`, or through today when `--as-of` is omitted.
		- `--project` adds projected automatic annual and sick accruals for future pay periods through the leave year end (or via `--project-to`).
		- `--project-to YYYY-MM-DD` projects accruals only through the specified date instead of year end.
		- `--use-or-lose` prints projected annual carryover and the amount that would be lost at year end based on the configured carryover limit; it enables year-end projection even when `--project` is not passed.
		- `--json` emits balances, use-or-lose values, and automatic accrual posting details.
		- Federal employees earn annual and sick leave automatically each pay period; this tool posts or projects that accrual based on the leave year pay periods and configured accrual rates.

	pay-period
		Show earned, used, net leave, overtime worked, optional daily activity, and ending balances for the pay period containing a date.

		Syntax:
			fedleave pay-period --year YEAR --date YYYY-MM-DD [--daily] [--json] [--data-dir PATH]

		Notes:
			- Missing automatic annual and sick accrual transactions for the containing pay period are posted before totals are calculated.
			- Overtime is shown as `worked`, which is the amount expected for that pay period's paycheck.
			- `--daily` prints one row for every day in the pay period, including days with no activity.
			- `--json` emits pay period metadata, activity totals, ending balances, and automatic accrual posting details.

	pay-periods
		Show earned, used, worked totals, and ending balances for every pay period in the leave year.

		Syntax:
			fedleave pay-periods --year YEAR [--json] [--data-dir PATH]

		Notes:
			- Missing automatic annual and sick accrual transactions are posted through the final pay period accrual date before totals are calculated.
			- `--json` emits one structured summary per pay period.

activity
	Show earned, used, and net leave activity for one day.

	Syntax:
		fedleave activity --year YEAR --date YYYY-MM-DD [--json] [--data-dir PATH]

	Notes:
		- `--json` emits earned, used, and net activity mappings for the date.
Global notes:

	Data directory:
	Default: `~/.local/share/fedleave` on Linux/macOS, or `%LOCALAPPDATA%\\fedleave` on Windows.
		- The application creates timestamped backups of JSON files before modifying them.
		- All writes are atomic using temporary file replacement.

	Exit codes:
		0   Success
		1   General error
		2   Syntax or usage error
		3   JSON validation error
		4   File read/write error

For the full project specification and rules, see the project documentation or the repository spec.

## JSON Output Reference

This chapter documents the machine-readable output produced by commands that accept `--json`.
It is intended as a programming reference for scripts, agents, dashboards, and import/reconciliation workflows.

General rules:

- JSON is written to standard output as a single JSON document.
- JSON mode uses plain output rather than Rich formatting, so output can be parsed directly by tools such as `jq` or Python's `json` module.
- Diagnostic errors are still written as human-readable messages unless otherwise noted.
- A successful JSON command exits with code `0`.
- Validation failures, ambiguous commands, missing files, and usage errors keep the same exit codes documented elsewhere in this README.
- Commands that modify data still create backups and perform atomic writes exactly as they do in human-readable mode.
- Field names are stable for automation. New fields may be added in later versions, so consumers should ignore unknown fields.
- Hour values are JSON numbers and represent decimal hours.
- Date values are ISO `YYYY-MM-DD` strings. Timestamps are ISO date-time strings as produced by Python.
- Category and direction values use the same names as the CLI: for example `annual`, `sick`, `credit`, `earned`, `used`, `worked`, and `starting_balance`.

Commands with native JSON output:

- `add`
- `reconcile`
- `correct`
- `void`
- `balance`
- `pay-period`
- `pay-periods`
- `activity`
- `validate`
- `rollover`

Commands without `--json`:

- `init`
- `list`
- `starting-balance set`
- `export-data`
- `import-data`
- `types`
- `holidays`
- `help`

### Shared Objects

Transaction object:

```json
{
  "id": "20260310-001",
  "date": "2026-03-10",
  "category": "annual",
  "direction": "used",
  "hours": 4.0,
  "description": "Medical appointment",
  "status": "planned",
  "source": "manual",
  "created_at": "2026-06-30T01:00:00.000000",
  "updated_at": "2026-06-30T01:00:00.000000",
  "void": false,
  "void_reason": null,
  "replaces_transaction_id": null,
  "correction_reason": null,
  "expiration_date": null,
  "expiration_pay_period": null,
  "earned_transaction_id": null
}
```

Transaction fields:

- `id`: Unique transaction ID, generated from transaction date plus a sequence number.
- `date`: Transaction date.
- `category`: Leave category.
- `direction`: Transaction direction.
- `hours`: Decimal hours.
- `description`: Free-text description.
- `status`: Transaction status.
- `source`: Transaction source, such as `manual`, `clocking-report`, or `correction`.
- `created_at`: Creation timestamp.
- `updated_at`: Last update timestamp.
- `void`: Boolean flag for audit-preserved voided transactions.
- `void_reason`: Reason a transaction was voided, or `null`.
- `replaces_transaction_id`: Original transaction ID replaced by a correction transaction, or `null`.
- `correction_reason`: Reason for a correction, or `null`.
- `expiration_date`: Expiration date for expiring leave categories, or `null`.
- `expiration_pay_period`: Expiration pay period number, or `null`.
- `earned_transaction_id`: Linked earned transaction ID for expiration workflows, or `null`.
- `reconcile_history`: Present only on transactions updated by `reconcile`. It is a list of prior values and the reconciliation reason.

Balance map:

```json
{
  "admin": 0.0,
  "annual": 30.0,
  "comp": 0.0,
  "credit": 0.0,
  "sick": 36.0
}
```

Balance maps use category names as keys and decimal hour values as values. They may include all known categories, even when values are zero.

Activity object:

```json
{
  "earned": {
    "annual": 6.0,
    "sick": 4.0
  },
  "used": {
    "annual": 4.0
  },
  "worked": {},
  "net": {
    "annual": 2.0,
    "sick": 4.0
  }
}
```

Activity maps use category names as keys and decimal hour totals as values.

Pay period object:

```json
{
  "pay_period_number": 1,
  "start_date": "2026-01-11",
  "end_date": "2026-01-24",
  "accrual_date": "2026-01-24"
}
```

The pay period object comes from the leave-year file's `pay_periods` list.

### `add --json`

Command:

```bash
fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment" --json
```

Success output:

```json
{
  "action": "added",
  "year": 2026,
  "transaction_id": "20260310-001",
  "transaction": {
    "id": "20260310-001",
    "date": "2026-03-10",
    "category": "annual",
    "direction": "used",
    "hours": 4.0,
    "description": "Medical appointment",
    "status": "planned",
    "source": "manual",
    "created_at": "2026-06-30T01:00:00.000000",
    "updated_at": "2026-06-30T01:00:00.000000",
    "void": false,
    "void_reason": null,
    "replaces_transaction_id": null,
    "correction_reason": null,
    "expiration_date": null,
    "expiration_pay_period": null,
    "earned_transaction_id": null
  },
  "replaced_transaction_ids": [],
  "automatic_accruals_posted": 0
}
```

Fields:

- `action`: Always `added`.
- `year`: Leave year file written.
- `transaction_id`: ID of the created transaction.
- `transaction`: Full created transaction object.
- `replaced_transaction_ids`: IDs voided by `--authoritative`. Empty when `--authoritative` does not replace anything.
- `automatic_accruals_posted`: Always `0` for `add`; included for consistency with workflow consumers.

### `reconcile --json`

Command:

```bash
fedleave reconcile --date 2026-03-10 --category credit --direction earned --hours 1.5 --reason "March clocking report" --json
```

Success output when a transaction is added:

```json
{
  "action": "added",
  "year": 2026,
  "transaction_id": "20260310-001",
  "date": "2026-03-10",
  "category": "credit",
  "direction": "earned",
  "hours": 1.5,
  "status": "reconciled",
  "source": "clocking-report",
  "reason": "March clocking report"
}
```

Success output when exactly one matching active transaction is updated:

```json
{
  "action": "updated",
  "year": 2026,
  "transaction_id": "20260310-001",
  "date": "2026-03-10",
  "category": "credit",
  "direction": "earned",
  "hours": 1.5,
  "status": "reconciled",
  "source": "clocking-report",
  "reason": "March clocking report"
}
```

Ambiguous output:

```json
{
  "action": "ambiguous",
  "year": 2026,
  "date": "2026-03-10",
  "category": "credit",
  "direction": "earned",
  "matching_transaction_ids": [
    "20260310-001",
    "20260310-002"
  ],
  "message": "Multiple active matching transactions found; rerun with --id."
}
```

Ambiguous output exits with code `2`. No data is written. Rerun with `--id TRANSACTION_ID` to update a specific matching transaction.

Fields:

- `action`: `added`, `updated`, or `ambiguous`.
- `year`: Leave year inferred from `date`.
- `transaction_id`: Added or updated transaction ID. Not present for `ambiguous`.
- `matching_transaction_ids`: Candidate IDs for ambiguous matches.
- `date`, `category`, `direction`, `hours`, `status`, `source`, `reason`: Reconciled transaction values.
- `message`: Human-readable explanation for ambiguous JSON results.

When `action` is `updated`, the transaction in the leave-year JSON also receives or appends a `reconcile_history` list:

```json
[
  {
    "updated_at": "2026-06-30T01:00:00.000000",
    "reason": "March clocking report",
    "old": {
      "hours": 1.0,
      "status": "planned",
      "source": "manual",
      "description": "Original report"
    },
    "new": {
      "hours": 1.5,
      "status": "reconciled",
      "source": "clocking-report",
      "description": "March clocking report"
    }
  }
]
```

### `correct --json`

Command:

```bash
fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours" --json
```

Success output:

```json
{
  "action": "corrected",
  "year": 2026,
  "original_transaction_id": "20260310-001",
  "voided_transaction_ids": [
    "20260310-001"
  ],
  "replacement_transaction_id": "20260310-002",
  "replacement_transaction": {
    "id": "20260310-002",
    "date": "2026-03-10",
    "category": "annual",
    "direction": "used",
    "hours": 3.0,
    "description": "Correction of 20260310-001: Only used 3 hours",
    "status": "reconciled",
    "source": "correction",
    "created_at": "2026-06-30T01:00:00.000000",
    "updated_at": "2026-06-30T01:00:00.000000",
    "void": false,
    "void_reason": null,
    "replaces_transaction_id": "20260310-001",
    "correction_reason": "Only used 3 hours",
    "expiration_date": null,
    "expiration_pay_period": null,
    "earned_transaction_id": null
  },
  "reason": "Only used 3 hours"
}
```

Preview command:

```bash
fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours" --preview --json
```

Preview output:

```json
{
  "action": "preview",
  "original_transaction_id": "20260310-001",
  "replacement": {
    "date": "2026-03-10",
    "category": "annual",
    "direction": "used",
    "hours": 3.0
  },
  "would_void_transaction_ids": [
    "20260310-001"
  ],
  "would_create_replacement": true
}
```

Fields:

- `action`: `corrected` or `preview`.
- `year`: Leave year written. Present for applied corrections.
- `original_transaction_id`: Corrected transaction ID.
- `voided_transaction_ids`: Transactions voided by the correction.
- `replacement_transaction_id`: New replacement transaction ID.
- `replacement_transaction`: Full replacement transaction object.
- `replacement`: Preview replacement values.
- `would_void_transaction_ids`: Preview of IDs that would be voided.
- `would_create_replacement`: Boolean preview flag.
- `reason`: Sanitized correction reason.

### `void --json`

Command:

```bash
fedleave void --id 20260310-002 --reason "Entered in error" --json
```

Success output:

```json
{
  "action": "voided",
  "year": 2026,
  "transaction_id": "20260310-002",
  "voided_transaction_ids": [
    "20260310-002"
  ],
  "reason": "Entered in error",
  "file": "/home/user/.local/share/fedleave/leave_years/2026.json"
}
```

Fields:

- `action`: Always `voided`.
- `year`: Leave year file containing the transaction.
- `transaction_id`: Voided transaction ID.
- `voided_transaction_ids`: List containing the voided ID.
- `reason`: Void reason recorded in the transaction. Defaults to `Voided by user` when `--reason` is omitted.
- `file`: Leave-year JSON file path that was written.

### `balance --json`

Command:

```bash
fedleave balance --year 2026 --as-of 2026-03-10 --json
```

Success output:

```json
{
  "year": 2026,
  "as_of": "2026-03-10",
  "projected": false,
  "project_to": null,
  "balances": {
    "admin": 0.0,
    "annual": 30.0,
    "comp": 0.0,
    "credit": 0.0,
    "sick": 36.0
  },
  "automatic_accruals_posted": 8,
  "automatic_accruals_posted_through": "2026-03-10",
  "use_or_lose": null
}
```

Use-or-lose command:

```bash
fedleave balance --year 2026 --project --use-or-lose --json
```

Use-or-lose fields:

```json
{
  "use_or_lose": {
    "carryover_limit": 240.0,
    "annual_carryover": 166.0,
    "use_or_lose": 0.0
  }
}
```

Fields:

- `year`: Requested leave year.
- `as_of`: Cutoff date, or `null` when omitted.
- `projected`: `true` when `--project` or `--use-or-lose` is active.
- `project_to`: Projection end date when projected; otherwise `null`.
- `balances`: Balance map by category.
- `automatic_accruals_posted`: Number of automatic annual/sick accrual transactions posted before calculating balances.
- `automatic_accruals_posted_through`: Date through which automatic accrual posting was attempted.
- `use_or_lose`: Use-or-lose object when `--use-or-lose` is passed; otherwise `null`.

### `pay-period --json`

Command:

```bash
fedleave pay-period --year 2026 --date 2026-01-20 --daily --json
```

Success output:

```json
{
  "year": 2026,
  "date": "2026-01-20",
  "pay_period": {
    "pay_period_number": 1,
    "start_date": "2026-01-11",
    "end_date": "2026-01-24",
    "accrual_date": "2026-01-24"
  },
  "activity": {
    "pay_period": {
      "pay_period_number": 1,
      "start_date": "2026-01-11",
      "end_date": "2026-01-24",
      "accrual_date": "2026-01-24"
    },
    "earned": {
      "annual": 6.0,
      "sick": 4.0
    },
    "used": {},
    "worked": {},
    "net": {
      "annual": 6.0,
      "sick": 4.0
    }
  },
  "daily_activity": [
    {
      "date": "2026-01-11",
      "earned": {},
      "used": {},
      "net": {}
    }
  ],
  "ending_balances": {
    "annual": 16.0,
    "sick": 24.0
  },
  "automatic_accruals_posted": 2,
  "automatic_accruals_posted_through": "2026-01-24"
}
```

Fields:

- `year`: Requested leave year.
- `date`: Date used to select the pay period.
- `pay_period`: Pay period containing `date`.
- `activity`: Activity object for the whole pay period. This object also includes `pay_period`.
- `daily_activity`: List of per-day activity objects when `--daily` is passed; otherwise `null`.
- `ending_balances`: Balance map through the pay period end date.
- `automatic_accruals_posted`: Number of automatic annual/sick accrual transactions posted for the period.
- `automatic_accruals_posted_through`: Period accrual date or end date used for automatic accrual posting.

### `pay-periods --json`

Command:

```bash
fedleave pay-periods --year 2026 --json
```

Success output:

```json
{
  "year": 2026,
  "pay_periods": [
    {
      "pay_period": {
        "pay_period_number": 1,
        "start_date": "2026-01-11",
        "end_date": "2026-01-24",
        "accrual_date": "2026-01-24"
      },
      "activity": {
        "pay_period": {
          "pay_period_number": 1,
          "start_date": "2026-01-11",
          "end_date": "2026-01-24",
          "accrual_date": "2026-01-24"
        },
        "earned": {
          "annual": 6.0,
          "sick": 4.0
        },
        "used": {},
        "worked": {},
        "net": {
          "annual": 6.0,
          "sick": 4.0
        }
      },
      "ending_balances": {
        "annual": 16.0,
        "sick": 24.0
      }
    }
  ],
  "automatic_accruals_posted": 52,
  "automatic_accruals_posted_through": "2027-01-09"
}
```

Fields:

- `year`: Requested leave year.
- `pay_periods`: List of pay period summaries in leave-year order.
- `pay_periods[].pay_period`: Pay period object.
- `pay_periods[].activity`: Activity object for that pay period.
- `pay_periods[].ending_balances`: Balance map through that pay period's end date.
- `automatic_accruals_posted`: Number of automatic annual/sick accrual transactions posted before producing the summary.
- `automatic_accruals_posted_through`: Final pay period accrual date or end date.

### `activity --json`

Command:

```bash
fedleave activity --year 2026 --date 2026-03-10 --json
```

Success output when activity exists:

```json
{
  "year": 2026,
  "date": "2026-03-10",
  "activity": {
    "earned": {},
    "used": {
      "annual": 4.0
    },
    "net": {
      "annual": -4.0
    }
  },
  "has_activity": true
}
```

Success output when no activity exists:

```json
{
  "year": 2026,
  "date": "2026-03-11",
  "activity": {
    "earned": {},
    "used": {},
    "net": {}
  },
  "has_activity": false
}
```

In JSON mode, no-activity results exit with code `0`. In human-readable mode, the command prints a no-activity message and exits with code `0`.

Fields:

- `year`: Requested leave year.
- `date`: Requested date.
- `activity`: Daily activity object. Daily activity includes `earned`, `used`, and `net`.
- `has_activity`: Boolean flag indicating whether any activity map has entries.

### `validate --json`

Command:

```bash
fedleave validate --json
```

Success output with no issues:

```json
{
  "ok": true,
  "results": [
    {
      "file": "2026.json",
      "year": 2026,
      "ok": true,
      "issues": [],
      "applied": false
    }
  ]
}
```

Output with issues:

```json
{
  "ok": false,
  "results": [
    {
      "file": "2026.json",
      "year": 2026,
      "ok": false,
      "issues": [
        {
          "type": "date",
          "path": "transactions[0].date",
          "message": "Non-canonical date: 2026-3-10",
          "fix": {
            "date": "2026-03-10"
          }
        }
      ],
      "applied": false
    }
  ]
}
```

Fields:

- `ok`: `true` only when all checked leave-year files have no issues.
- `results`: One object per leave-year JSON file.
- `results[].file`: File name.
- `results[].year`: Leave year from the file name.
- `results[].ok`: `true` when that file has no issues.
- `results[].issues`: List of validation issues.
- `results[].issues[].type`: Issue category, such as `date`, `category`, `direction`, or `starting_balances`.
- `results[].issues[].path`: JSON path-like location of the issue.
- `results[].issues[].message`: Human-readable issue message.
- `results[].issues[].fix`: Suggested automatic fix when available.
- `results[].applied`: `true` when `--apply --json` wrote automatic fixes for that file.
- `results[].write_error`: Present only when applying fixes failed.

Exit behavior:

- Exits `0` when `ok` is `true`.
- Exits `2` when `ok` is `false`.
- In JSON mode, the command never prompts interactively. It applies fixes only when `--apply` is passed.

### `rollover --json`

Preview command:

```bash
fedleave rollover --from-year 2026 --to-year 2027 --preview --json
```

Preview output:

```json
{
  "action": "preview",
  "from_year": 2026,
  "to_year": 2027,
  "annual_balance": 120.0,
  "carryover_limit": 240.0,
  "carry_forward": 120.0,
  "forfeiture": 0.0,
  "sick_balance": 180.0,
  "created_file": null,
  "created_transaction_ids": []
}
```

Apply command:

```bash
fedleave rollover --from-year 2026 --to-year 2027 --json
```

Apply output:

```json
{
  "action": "applied",
  "from_year": 2026,
  "to_year": 2027,
  "annual_balance": 120.0,
  "carryover_limit": 240.0,
  "carry_forward": 120.0,
  "forfeiture": 0.0,
  "sick_balance": 180.0,
  "created_file": "/home/user/.local/share/fedleave/leave_years/2027.json",
  "created_transaction_ids": [
    "20270111-001",
    "20270111-002"
  ]
}
```

Fields:

- `action`: `preview` or `applied`.
- `from_year`: Source leave year.
- `to_year`: Destination leave year.
- `annual_balance`: Source annual leave balance before carryover cap.
- `carryover_limit`: Annual carryover limit used.
- `carry_forward`: Annual leave carried into the new leave year.
- `forfeiture`: Annual leave lost above the carryover limit.
- `sick_balance`: Sick leave carried into the new leave year.
- `created_file`: New leave-year JSON file path when applied; `null` for preview.
- `created_transaction_ids`: Starting-balance transaction IDs created in the new leave year when applied.

### Parsing Examples

Python example:

```python
import json
import subprocess

result = subprocess.run(
    [
        "fedleave",
        "balance",
        "--year",
        "2026",
        "--as-of",
        "2026-03-10",
        "--json",
    ],
    check=True,
    capture_output=True,
    text=True,
)

payload = json.loads(result.stdout)
annual_balance = payload["balances"]["annual"]
posted = payload["automatic_accruals_posted"]
```

Shell example:

```bash
fedleave balance --year 2026 --as-of 2026-03-10 --json | jq '.balances.annual'
```

Error-handling example:

```python
import json
import subprocess

result = subprocess.run(
    ["fedleave", "validate", "--json"],
    capture_output=True,
    text=True,
)

if result.stdout:
    payload = json.loads(result.stdout)
else:
    payload = None

if result.returncode == 0:
    print("valid")
elif result.returncode == 2 and payload is not None:
    for file_result in payload["results"]:
        for issue in file_result["issues"]:
            print(file_result["file"], issue["path"], issue["message"])
else:
    raise RuntimeError(result.stderr or result.stdout)
```

## Additional Command Examples

Correction (audit-safe):

	fedleave correct --id TRANSACTION_ID --hours HOURS --reason "TEXT" [--json] [--show-transaction-ids] --data-dir /path/to/data

	Example:
		fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours"

Alternatively, you can correct by transaction date and type (more human-friendly):

	fedleave correct --search-date YYYY-MM-DD --search-type CATEGORY --hours HOURS --reason "TEXT" [--show-transaction-ids] --data-dir /path/to/data

	Example:
		fedleave correct --search-date 2026-06-01 --search-type annual --hours 3 --reason "Adjust entry" --data-dir ./.data

Void a transaction:

	fedleave void --id TRANSACTION_ID --reason "TEXT" [--json] [--show-transaction-ids] --data-dir /path/to/data

	Example:
		fedleave void --id 20260310-002 --reason "Entered in error"

Rollover preview/apply:

	fedleave rollover --from-year 2026 --to-year 2027 --preview [--json] --data-dir /path/to/data

Validation:

	fedleave validate [--apply] [--json] --data-dir /path/to/data

Holiday commands:

	fedleave holidays generate --year 2026 [--source python_holidays|opm_ics] --data-dir /path/to/data
	fedleave holidays import-ics --year 2026 --file opm-holidays.ics --data-dir /path/to/data
	fedleave holidays list --year 2026 --data-dir /path/to/data

Export/import:

	fedleave export-data --output fedleave_backup.json --data-dir /path/to/data
	fedleave import-data --input fedleave_backup.json --data-dir /path/to/new_data
	fedleave import-data --input fedleave_backup.json --overwrite --data-dir /path/to/data

Daily and as-of queries:

	# Current ledger balance through all recorded transactions
	fedleave balance --year 2026 --data-dir /path/to/data

	# Balance as of a specific date
	fedleave balance --year 2026 --as-of 2026-06-01 --data-dir /path/to/data

	# Leave earned/used and overtime worked for the pay period containing a date
	fedleave pay-period --year 2026 --date 2026-06-01 --data-dir /path/to/data
	fedleave pay-period --year 2026 --date 2026-06-01 --daily --data-dir /path/to/data

	# Leave earned/used and ending balances for every pay period in a year
	fedleave pay-periods --year 2026 --data-dir /path/to/data

	# Project end-of-year balance including automatic annual/sick accrual
	fedleave balance --year 2026 --project --use-or-lose --data-dir /path/to/data

	# Project balance to a custom date
	fedleave balance --year 2026 --project --project-to 2026-12-15 --data-dir /path/to/data

	fedleave activity --year 2026 --date 2026-01-11 --data-dir /path/to/data

Building a standalone `fedleave` binary
--------------------------------------

If you'd rather have a single `fedleave` executable you can build a platform-specific binary using PyInstaller. The repository includes a helper script and Makefile target.

1. Prepare a clean build environment (recommended):

```bash
python -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip
```

2. Build using the Makefile or the platform-appropriate script:

Linux / macOS:

```bash
make build
# or:
./scripts/build_pyinstaller.sh
```

Windows PowerShell:

```powershell
python -m venv .build-venv
.\.build-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pyinstaller
pwsh .\scripts\build_pyinstaller.ps1
```

3. Output:

- The built executable will appear in `dist/fedleave` (Linux) and is platform-specific. Build on the target platform or use an appropriate builder.

Notes and caveats:

- PyInstaller build installs PyInstaller and your package into a temporary venv under `.pyinstaller-venv`.
- The produced binary is not cross-platform; build on the OS you intend to run on.


