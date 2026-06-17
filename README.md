# fedleave

Federal leave and time tracker.

This project is a Python-first command-line application for tracking federal-style leave balances, generating pay period calendars, and producing LibreOffice-compatible reports.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Commands

Run `fedleave --help` after installation.

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
			fedleave add --year YEAR --date YYYY-MM-DD --category CATEGORY (--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS) [--description TEXT] [--status STATUS] [--source SOURCE] [--data-dir PATH]

		Defaults:
			--status planned
			--source manual
			--data-dir ~/.local/share/fedleave

		Notes:
			- Exactly one of `--earned`, `--used`, `--worked`, or `--adjusted` must be provided.
			- Valid categories include: annual, sick, overtime, comp, credit, travel_comp, admin, lwop, military, court, religious_comp, time_off_award, excused, holiday, flex, other, restored_annual.

		Examples:
			fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
			fedleave add --year 2026 --date 2026-03-12 --category overtime --worked 3

	list
		List transactions for a leave year.

		Syntax:
			fedleave list --year YEAR [--data-dir PATH]

	balance
	Show leave balances for a year, optionally as of a given date, projected to year end, and/or with use-or-lose calculations.

	Syntax:
		fedleave balance --year YEAR [--as-of YYYY-MM-DD] [--project] [--project-to YYYY-MM-DD] [--use-or-lose] [--data-dir PATH]

	Notes:
		- `--year YEAR` reads the leave year file and computes balances from all recorded transactions.
		- `--as-of YYYY-MM-DD` computes balances using only transactions on or before that date.
		- `--project` adds projected automatic annual and sick accruals for future pay periods through the leave year end (or via `--project-to`).
		- `--project-to YYYY-MM-DD` projects accruals only through the specified date instead of year end.
		- `--use-or-lose` prints projected annual carryover and the amount that would be lost at year end based on the configured carryover limit.
		- Federal employees earn annual and sick leave automatically each pay period; this tool projects that accrual based on the leave year pay periods and configured accrual rates.

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

For the full project specification, rules, and report details see the project documentation or the repository spec.

## Additional Command Examples

Correction (audit-safe):

	fedleave correct --id TRANSACTION_ID --hours HOURS --reason "TEXT" --data-dir /path/to/data

	Example:
		fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours"

Alternatively, you can correct by transaction date and type (more human-friendly):

	fedleave correct --search-date YYYY-MM-DD --search-type CATEGORY --hours HOURS --reason "TEXT" --data-dir /path/to/data

	Example:
		fedleave correct --search-date 2026-06-01 --search-type annual --hours 3 --reason "Adjust entry" --data-dir ./.data

Void a transaction:

	fedleave void --id TRANSACTION_ID --reason "TEXT" --data-dir /path/to/data

	Example:
		fedleave void --id 20260310-002 --reason "Entered in error"

Rollover preview/apply:

	fedleave rollover --from-year 2026 --to-year 2027 --preview --data-dir /path/to/data

Holiday commands:

	fedleave holidays generate --year 2026 [--source python_holidays|opm_ics] --data-dir /path/to/data
	fedleave holidays import-ics --year 2026 --file opm-holidays.ics --data-dir /path/to/data
	fedleave holidays list --year 2026 --data-dir /path/to/data

Daily and as-of queries:

	# Current ledger balance through all recorded transactions
	fedleave balance --year 2026 --data-dir /path/to/data

	# Balance as of a specific date
	fedleave balance --year 2026 --as-of 2026-06-01 --data-dir /path/to/data

	# Project end-of-year balance including automatic annual/sick accrual
	fedleave balance --year 2026 --project --use-or-lose --data-dir /path/to/data

	# Project balance to a custom date
	fedleave balance --year 2026 --project --project-to 2026-12-15 --data-dir /path/to/data

	fedleave activity --year 2026 --date 2026-01-11 --data-dir /path/to/data

## Generating reports

Reports are built from a leave year JSON, a report template, and a generated chart image.

Prerequisites:

- `matplotlib` and `odfpy` installed in your environment.
- `libreoffice` on PATH if you want automatic ODT → PDF conversion.
- A report template at `templates/report_template.odt`.

If you do not have a template yet, generate the default one:

```bash
python3 scripts/generate_templates.py
```

Robust report workflow:

1. Initialize or prepare your year data:

```bash
fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-start 120 --sick-start 180 --data-dir ./.data
```

2. Add any transactions and verify the balance file exists:

```bash
fedleave add --year 2026 --date 2026-06-01 --category annual --used 20 --description "Vacation" --data-dir ./.data
fedleave balance --year 2026 --data-dir ./.data
```

3. Generate the report chart PNG:

```bash
python -m fedleave.charts --year 2026 --data-dir ./.data --output ./.data/reports/chart_2026.png
```

4. Generate the ODT report from the template:

```bash
python -m fedleave.reports generate --year 2026 --data_dir ./.data --chart ./.data/reports/chart_2026.png --output ./.data/reports/fedleave_2026.odt
```

If you want to use a custom template, pass `--template`:

```bash
python -m fedleave.reports generate --year 2026 --data_dir ./.data --chart ./.data/reports/chart_2026.png --template templates/report_template.odt --output ./.data/reports/fedleave_2026.odt
```

5. If LibreOffice is installed, the report generator attempts headless PDF conversion automatically. If it does not, convert manually:

```bash
libreoffice --headless --convert-to pdf ./.data/reports/fedleave_2026.odt --outdir ./.data/reports
```

Direct `fedleave` report command
--------------------------------

You can call the report generator directly from the `fedleave` CLI. The command accepts the same options as the report generator and will attempt to produce a PDF when the `--output` filename ends in `.pdf`.

Examples:

```bash
# produce an ODT
fedleave report --year 2026 --output reports/fedleave_2026.odt --data-dir ./.data

# produce a PDF (requires LibreOffice on PATH)
fedleave report --year 2026 --output reports/fedleave_2026.pdf --data-dir ./.data
```

Helpful notes when dependencies are missing
------------------------------------------

- If the Python package `odfpy` is missing you will see an error instructing you to install it:

	pip install odfpy

- If LibreOffice is not installed and you request a PDF, the CLI will print platform-specific suggestions to install it:

	- Debian/Ubuntu: `sudo apt-get install -y libreoffice-core libreoffice-writer`
	- macOS: `brew install --cask libreoffice`
	- Windows: download + install from https://www.libreoffice.org/

The CLI gives clear errors and exit codes when these dependencies are missing so you can quickly remedy the environment.

Important notes:

- The generator replaces template placeholders `{{TITLE}}`, `{{DATE}}`, `{{PREPARED_BY}}`, `{{SUMMARY_TABLE}}`, and `{{CHART}}`.
- If `odfpy` is missing, the ODT generator cannot run, but chart generation still works.
- If the template is missing, run `python3 scripts/generate_templates.py` or provide a custom `--template` path.
- The summary table is derived from the current leave year balances and is embedded directly into the ODT.

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
- The script bundles the ODT template into the binary; to include additional files, edit `scripts/build_pyinstaller.sh` and add more `--add-data` entries.

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
	The project is logic-heavy and report-heavy, not performance-heavy.
	Python is better for rapid iteration on:
		- Federal leave rules
		- Pay period calculations
		- JSON validation
		- Federal holiday handling
		- CLI syntax
		- LibreOffice report generation
		- Chart generation
		- Testing

===============================================================================
1. PROJECT PURPOSE
===============================================================================

Create a local Linux command-line application named fedleave.

The application tracks federal-style leave and time balances using JSON files.
It generates printable yearly leave charts and summary reports using
LibreOffice-compatible formats, then converts those reports to PDF.

The application is a personal planning, tracking, and reconciliation tool.
It is not the official system of record.

The application shall track:

	- Annual leave
	- Sick leave
	- Overtime worked
	- Regular compensatory time earned and used
	- Credit hours earned and used
	- Travel compensatory time earned and used
	- Time-off awards
	- Administrative leave
	- Excused absence
	- Leave without pay
	- Court leave
	- Military leave
	- Religious compensatory time
	- Restored annual leave
	- Other configurable leave/time categories

===============================================================================
2. REQUIRED PROJECT FOLDER STRUCTURE
===============================================================================

Create a separate VS Code project folder:

	fedleave/

Recommended structure:

	fedleave/
	|-- README.md
	|-- pyproject.toml
	|-- requirements.txt
	|-- .gitignore
	|-- .vscode/
	|   |-- settings.json
	|   |-- launch.json
	|
	|-- fedleave/
	|   |-- __init__.py
	|   |-- __main__.py
	|   |-- cli.py
	|   |-- models.py
	|   |-- config.py
	|   |-- storage.py
	|   |-- ledger.py
	|   |-- rules.py
	|   |-- payperiods.py
	|   |-- holidays.py
	|   |-- rollover.py
	|   |-- balances.py
	|   |-- reports.py
	|   |-- charts.py
	|   |-- libreoffice.py
	|   |-- validation.py
	|   |-- corrections.py
	|   |-- theme.py
	|   |-- utils.py
	|
	|-- templates/
	|   |-- yearly_chart_template.ods
	|   |-- summary_template.odt
	|   |-- theme.json
	|
	|-- examples/
	|   |-- example_config.json
	|   |-- example_2026.json
	|
	|-- tests/
	|   |-- test_payperiods.py
	|   |-- test_balances.py
	|   |-- test_rules_annual.py
	|   |-- test_rules_credit.py
	|   |-- test_rules_comp.py
	|   |-- test_rules_travel_comp.py
	|   |-- test_holidays.py
	|   |-- test_rollover.py
	|   |-- test_corrections.py
	|   |-- test_cli.py
	|
	|-- scripts/
	|   |-- build_pyinstaller.sh
	|   |-- clean_reports.sh
	|   |-- create_sample_data.sh

===============================================================================
3. RECOMMENDED PYTHON STACK
===============================================================================

Use:

	Python 3.11 or newer

Recommended packages:

	typer
	pydantic
	python-dateutil
	holidays
	icalendar
	matplotlib
	odfpy
	rich
	pytest
	pyinstaller

Purpose of each:

	typer:
		Command-line interface.

	pydantic:
		JSON schema validation and model validation.

	python-dateutil:
		Date handling.

	holidays:
		Offline generation of US federal holidays.

	icalendar:
		Import OPM iCalendar holiday files if available.

	matplotlib:
		Generate trend chart images.

	odfpy:
		Generate or modify ODS/ODT LibreOffice-compatible files.

	rich:
		Better command-line tables and error output.

	pytest:
		Automated tests.

	pyinstaller:
		Single-file executable distribution.

