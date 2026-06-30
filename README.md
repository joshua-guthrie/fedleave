# fedleave

Federal leave and time tracker.

This project is a command-line application for tracking federal-style leave balances and generating pay period calendars.

The hope is that it is not only useful at the CLI, but could become the basis of larger leave tracking applications (web apps or GUIs).

Note:  In-case you're wondering... it was a 100% at home project.  None of it was done on company time!   It was also my first experiemnt into vibe coding.  So far, I'm impressed.

It's a little program I'm using to serve as a back end to an AI agent and a dashboard and figured it may be useful to someone else.

## Limitations
I'm making no effort to track expiring leave, such as travel comp time, award leave, etc.  I've never had the problem in my personal live of having to worry about leave expiring ! :)

The program is entirely single user.  I suppose it could be made into a multiple user system with seperate data files for each user, but that has never been my use case.  At your own peril.

I would not be using this application for any thing critical.  For me, it's a fun little experiement.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
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
fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
fedleave add --year 2026 --date 2026-03-12 --category overtime --worked 3 --description "Release support"
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
			fedleave add --year YEAR --date YYYY-MM-DD --category CATEGORY (--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS) [--description TEXT] [--status STATUS] [--source SOURCE] [--authoritative] [--show-transaction-ids] [--data-dir PATH]

		Defaults:
			--status planned
			--source manual
			--data-dir ~/.local/share/fedleave

		Notes:
			- Exactly one of `--earned`, `--used`, `--worked`, or `--adjusted` must be provided.
			- `--authoritative` voids active transactions with the same date, category, and direction before adding the new transaction.
			- Transaction IDs are hidden by default in human-readable output. Use `--show-transaction-ids` or `--ShowTransactionIDs` when needed.
			- Valid categories include: annual, sick, overtime, comp, credit, travel_comp, admin, lwop, military, court, religious_comp, time_off_award, excused, holiday, flex, other, restored_annual.

		Examples:
			fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
			fedleave add --year 2026 --date 2026-03-12 --category overtime --worked 3
			fedleave add --year 2026 --date 2026-03-10 --category annual --used 3 --status reconciled --authoritative --description "Actual leave used"

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
		fedleave balance --year YEAR [--as-of YYYY-MM-DD] [--project] [--project-to YYYY-MM-DD] [--use-or-lose] [--data-dir PATH]

	Notes:
		- `--year YEAR` reads the leave year file and computes balances from all recorded transactions.
		- `--as-of YYYY-MM-DD` computes balances using only transactions on or before that date.
		- Missing automatic annual and sick leave accrual transactions are posted through `--as-of`, or through today when `--as-of` is omitted.
		- `--project` adds projected automatic annual and sick accruals for future pay periods through the leave year end (or via `--project-to`).
		- `--project-to YYYY-MM-DD` projects accruals only through the specified date instead of year end.
		- `--use-or-lose` prints projected annual carryover and the amount that would be lost at year end based on the configured carryover limit; it enables year-end projection even when `--project` is not passed.
		- Federal employees earn annual and sick leave automatically each pay period; this tool posts or projects that accrual based on the leave year pay periods and configured accrual rates.

	pay-period
		Show earned, used, net leave, overtime worked, optional daily activity, and ending balances for the pay period containing a date.

		Syntax:
			fedleave pay-period --year YEAR --date YYYY-MM-DD [--daily] [--data-dir PATH]

		Notes:
			- Missing automatic annual and sick accrual transactions for the containing pay period are posted before totals are calculated.
			- Overtime is shown as `worked`, which is the amount expected for that pay period's paycheck.
			- `--daily` prints one row for every day in the pay period, including days with no activity.

	pay-periods
		Show earned, used, worked totals, and ending balances for every pay period in the leave year.

		Syntax:
			fedleave pay-periods --year YEAR [--data-dir PATH]

		Notes:
			- Missing automatic annual and sick accrual transactions are posted through the final pay period accrual date before totals are calculated.

activity
	Show earned, used, and net leave activity for one day.

	Syntax:
		fedleave activity --year YEAR --date YYYY-MM-DD [--data-dir PATH]
Global notes:

	Data directory:
		Default: `~/.local/share/fedleave`
		Use `--data-dir /path` to override on a per-command basis.

	Safety:
		- The application creates timestamped backups of JSON files before modifying them.
		- All writes are atomic using temporary file replacement.

	Exit codes:
		0   Success
		1   General error
		2   Syntax or usage error
		3   JSON validation error
		4   File read/write error

For the full project specification and rules, see the project documentation or the repository spec.

## Additional Command Examples

Correction (audit-safe):

	fedleave correct --id TRANSACTION_ID --hours HOURS --reason "TEXT" [--show-transaction-ids] --data-dir /path/to/data

	Example:
		fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours"

Alternatively, you can correct by transaction date and type (more human-friendly):

	fedleave correct --search-date YYYY-MM-DD --search-type CATEGORY --hours HOURS --reason "TEXT" [--show-transaction-ids] --data-dir /path/to/data

	Example:
		fedleave correct --search-date 2026-06-01 --search-type annual --hours 3 --reason "Adjust entry" --data-dir ./.data

Void a transaction:

	fedleave void --id TRANSACTION_ID --reason "TEXT" [--show-transaction-ids] --data-dir /path/to/data

	Example:
		fedleave void --id 20260310-002 --reason "Entered in error"

Rollover preview/apply:

	fedleave rollover --from-year 2026 --to-year 2027 --preview --data-dir /path/to/data

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

2. Build using the Makefile (or run the script directly):

```bash
make build
# or:
./scripts/build_pyinstaller.sh
```

3. Output:

- The built executable will appear in `dist/fedleave` (Linux) and is platform-specific. Build on the target platform or use an appropriate builder.

Notes and caveats:

- PyInstaller build installs PyInstaller and your package into a temporary venv under `.pyinstaller-venv`.
- The produced binary is not cross-platform; build on the OS you intend to run on.
- If you want me to run the build here, I can — it will take several minutes and produce `dist/fedleave`.

## Full Project Specification

The following is the complete project specification for `fedleave`. It describes the required folder structure, JSON models, rules, commands, and acceptance criteria.

PROJECT SPECIFICATION
FEDLEAVE - FEDERAL LEAVE AND TIME TRACKER

Project folder:
	fedleave/

Primary language:
	Python 3.

Reason for Python-first approach:
	The project is logic-heavy, not performance-heavy.
	Python is better for rapid iteration on:
		- Federal leave rules
		- Pay period calculations
		- JSON validation
		- Federal holiday handling
		- CLI syntax
		- Testing
