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
			fedleave init --year YEAR --leave-year-start YYYY-MM-DD [--annual-accrual FLOAT] [--annual-start FLOAT] [--sick-start FLOAT] [--comp-start FLOAT] [--credit-start FLOAT] [--travel-comp-start FLOAT] [--data-dir PATH]

		Example:
			fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-accrual 6 --annual-start 120 --sick-start 180 --data-dir ~/.local/share/fedleave

	add
		Add a transaction to a leave year ledger.

		Syntax:
			fedleave add --year YEAR --date YYYY-MM-DD --category CATEGORY (--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS) [--description TEXT] [--status STATUS] [--source SOURCE] [--data-dir PATH]

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
		Show current balances computed from the ledger for a leave year.

		Syntax:
			fedleave balance --year YEAR [--data-dir PATH]

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

Void a transaction:

	fedleave void --id TRANSACTION_ID --reason "TEXT" --data-dir /path/to/data

	Example:
		fedleave void --id 20260310-002 --reason "Entered in error"

Rollover preview/apply:

	fedleave rollover --from-year 2026 --to-year 2027 --preview --data-dir /path/to/data

Holiday commands:

	fedleave holidays generate --year 2026 --data-dir /path/to/data
	fedleave holidays import-ics --year 2026 --file opm-holidays.ics --data-dir /path/to/data
	fedleave holidays list --year 2026 --data-dir /path/to/data

## Generating reports

Reports are produced from the leave-year JSON plus template files and a chart image pipeline.

Prerequisites:

- `matplotlib` and `odfpy` installed in your environment (see `requirements.txt`).
- `libreoffice` available on your PATH to convert ODT/ODS files to PDF.
- Templates present under `templates/` (e.g. `summary_template.odt`, `yearly_chart_template.ods`).

Typical workflow:

1. Prepare the data for the year:

```bash
fedleave balance --year 2026 --data-dir ./.data
```

2. Generate charts (the project uses `matplotlib`):

```bash
python -m fedleave.charts --year 2026 --data-dir ./.data --output reports/chart_2026.png
```

3. Produce an ODT/ODS report using templates (this project provides `reports` module hooks):

```bash
python -m fedleave.reports generate --year 2026 --data-dir ./.data --output reports/fedleave_2026.odt
```

4. Convert to PDF with LibreOffice headless:

```bash
libreoffice --headless --convert-to pdf reports/fedleave_2026.odt --outdir reports/
```

Notes:

- `fedleave.reports` and `fedleave.charts` are the integration points; they may be lightweight stubs in the reference implementation. If a command/module isn't implemented, you can assemble the ODT/ODS by using `odfpy` and inserting the PNG chart(s) produced by `matplotlib`.
- For small use, exporting charts as PNG and embedding them into a pre-made ODT template is the quickest path.

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

