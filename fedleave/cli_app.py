from __future__ import annotations

import json

import typer
from rich.console import Console

from . import __version__


console = Console()


def _print_json(data: dict | list) -> None:
    typer.echo(json.dumps(data, indent=2))


HELP_TEXT = """
fedleave — Federal leave and time tracker

Usage:
    fedleave COMMAND [OPTIONS]

Primary commands:
    init        Initialize data directory and create leave year JSON
    add         Add a transaction to a leave year
    set-day     Authoritatively set signed leave values for one day
    accrual-change
                Change automatic annual/sick accrual hours from a date forward
    reconcile   Add or update one reconciled transaction by date/category/direction
    list        List transactions for a leave year
    starting-balance
                Set starting balances with audit history
    balance     Show balances calculated from the ledger
    use-or-lose Show year-end annual carryover and use-or-lose for a leave year
    pay-period  Show earned, used, overtime totals, and balances for a pay period
    pay-periods Show earned, used, overtime totals, and balances for every pay period
    month       Show calendar-day leave entries and pay periods for a month
    export-data Export config, leave years, and holiday cache to a JSON archive
    import-data Import a JSON archive created by export-data or a single leave-year backup
    correct     Audit-safe correction of transactions
    void        Void a transaction (preserve audit history)
    rollover    Preview or apply leave year rollover
    holidays    Manage federal holiday data
    help        Show this detailed help

Command details and examples:

    fedleave init --year YEAR --leave-year-start YYYY-MM-DD|today [options]
        --annual-accrual FLOAT       Annual leave accrual hours per pay period (default 6)
        --annual-start FLOAT         Starting annual leave hours
        --sick-start FLOAT           Starting sick leave hours
        --comp-start FLOAT           Starting comp time hours
        --credit-start FLOAT         Starting credit hours
        --travel-comp-start FLOAT    Starting travel comp hours
        --data-dir PATH              Override default data directory

    Examples:
        fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-accrual 6 \
            --annual-start 120 --sick-start 180 --data-dir ~/.local/share/fedleave

    Optional OPM ICS holiday import:
        fedleave init --year 2026 --leave-year-start 2026-01-11 --annual-accrual 6 \
            --annual-start 120 --sick-start 180 --holiday-source opm_ics \
            --holiday-ics-url https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/holidays.ics \
            --data-dir ~/.local/share/fedleave

    fedleave add --year YEAR --date YYYY-MM-DD|today --category CATEGORY [--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS] [--description TEXT] [--status STATUS] [--source SOURCE] [--authoritative] [--json] [--show-transaction-ids]
        Exactly one of `--earned`, `--used`, `--worked`, or `--adjusted` must be provided.
        --authoritative voids active transactions with the same date, category, and direction before adding the new transaction.
        --json emits the created transaction ID and any replaced transaction IDs.
        Transaction IDs are hidden by default in human-readable output. Use --show-transaction-ids when needed.
        Valid categories: annual, sick, overtime, comp, credit, travel_comp, admin, lwop, military, court, religious_comp, time_off_award, excused, holiday, flex, other, restored_annual

    Examples:
        fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
        fedleave add --year 2026 --date 2026-03-10 --category annual --used 3 --status reconciled --authoritative
        fedleave add --year 2026 --date 2026-03-12 --category overtime --worked 3

    fedleave set-day --date YYYY-MM-DD|today --authoritative --json [--annual HOURS] [--sick HOURS] [--credit HOURS] [--comp HOURS] [--travel-comp HOURS] [--overtime HOURS] [--data-dir PATH]
        Authoritatively replace active transactions for the supplied categories on a date.
        Positive values are earned or worked; negative values are used; zero clears active values for that category.

    fedleave accrual-change [--year YEAR] --as-of YYYY-MM-DD|today --category annual|sick --hours HOURS [--reason TEXT] [--json] [--data-dir PATH]
        Change automatic annual or sick leave accrual hours per pay period from the effective date forward.
        Updates future automatic accrual transactions and records the change in accrual_rate_changes.
    Example:
        fedleave accrual-change --year 2026 --as-of 2026-07-12 --category annual --hours 6 --reason "15-year service accrual"

    fedleave reconcile --date YYYY-MM-DD|today --category CATEGORY --direction DIRECTION --hours HOURS --reason TEXT [--status STATUS] [--source SOURCE] [--id TRANSACTION_ID] [--json] [--data-dir PATH]
        Infer the leave year from the date, then set the active transaction for that date/category/direction to the requested hours.
        Adds a transaction when no active match exists. Updates exactly one active match and records reconcile_history.
        If multiple active matches exist, rerun with --id to choose the transaction.

    fedleave list --year YEAR [--json] [--show-transaction-ids] [--data-dir PATH]
        List active transactions for a leave year. Transaction IDs are hidden unless --show-transaction-ids is passed.

    fedleave starting-balance set --year YEAR --category CATEGORY --hours HOURS --reason TEXT [--data-dir PATH]
        Set a leave year's starting balance for one category and record the prior value in starting_balance_history.
        If the matching carryover_from_previous_year value still equals the old starting balance, it is updated too.

    fedleave balance [--year YEAR] [--as-of YYYY-MM-DD|today|leave-year-end] [--project] [--project-to YYYY-MM-DD|today|leave-year-end] [--use-or-lose] [--json] [--data-dir PATH]
        Show balances calculated from the ledger as of a date. If omitted, --as-of defaults to today and --year is inferred.
        --project-to projects future annual and sick leave accruals through a custom date.
        --project is retained for compatibility with existing scripts.
        --use-or-lose prints projected annual carryover and annual leave lost above the carryover limit.
        --json emits balances, use-or-lose values, and automatic accrual posting details.

    fedleave use-or-lose [--year YEAR] [--json] [--data-dir PATH]
        Show year-end annual carryover and use-or-lose for a leave year.
        Alias: fedleave use-or-loose
        If --year is omitted, the current leave year is inferred from today.
        --json emits the same projected balance payload used by `fedleave balance --use-or-lose`.

    fedleave pay-period --year YEAR --date YYYY-MM-DD|today [--daily] [--json] [--data-dir PATH]
        Show leave earned/used, overtime worked, optional daily activity, and ending balances for the pay period containing the date.

    fedleave pay-periods --year YEAR [--json] [--data-dir PATH]
        Show earned/used/worked totals and ending balances for every pay period in the leave year.

    fedleave month --year YEAR --month MONTH [--json] [--data-dir PATH]
        Show calendar days, leave entries, holidays, display lines, and pay-period totals for one month.

    fedleave export-data --output fedleave_backup.json [--data-dir PATH]
        Export config, leave year files, and holiday cache to a portable JSON archive.

    fedleave import-data --input fedleave_backup.json [--overwrite] [--data-dir PATH]
        Import a JSON archive created by export-data or a single leave-year backup. Existing files are preserved unless --overwrite is used.

    fedleave correct --id TRANSACTION_ID --hours HOURS --reason "TEXT" [--json] [--show-transaction-ids] [--data-dir PATH]
        Perform an audit-safe correction: void the original transaction and create a replacement linked to it.
    Example:
        fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours"

    fedleave void --id TRANSACTION_ID --reason "TEXT" [--json] [--show-transaction-ids] [--data-dir PATH]
        Mark a transaction as void while preserving its record.
    Example:
        fedleave void --id 20260310-002 --reason "Entered in error"

    fedleave rollover --from-year YEAR --to-year YEAR [--preview] [--json] [--data-dir PATH]
        Preview or apply end-of-year rollover logic (carryover, forfeitures, starting balances, holiday generation).
    Example:
        fedleave rollover --from-year 2026 --to-year 2027 --preview

    fedleave holidays generate --year YEAR [--source python_holidays|opm_ics] [--data-dir PATH]
    fedleave holidays fetch --year YEAR --file path/to/opm.ics [--data-dir PATH]
    fedleave holidays list --year YEAR [--data-dir PATH]
    fedleave holidays import-ics --year YEAR --file path/to/opm.ics [--data-dir PATH]
        Manage federal holiday data sources, cache, and manual overrides.
    Examples:
        fedleave holidays generate --year 2026
        fedleave holidays import-ics --year 2026 --file opm-holidays.ics

    fedleave validate [--apply] [--json] [--data-dir PATH]
        Validate leave-year JSON files and optionally emit structured issue details.
Notes on data directory:
    Default: ~/.local/share/fedleave on Linux, `%LOCALAPPDATA%\\fedleave` on Windows
    Override per-command with `--data-dir /path/to/data`.

Safety and backups:
    All modifying operations create timestamped backups of JSON files before writing and write changes atomically.

Exit codes:
    0  Success
    1  General error (file not found, etc.)
    2  Syntax or usage error
    3  JSON validation error
    4  File read/write error
    8  Rollover error
    9  Holiday fetch/import/generation error

For full project specification and advanced usage, see the README in the project root.
"""

def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"fedleave {__version__}")
        raise typer.Exit()


app = typer.Typer(help=HELP_TEXT, add_completion=False)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the fedleave backend version and exit.",
    ),
) -> None:
    """Federal leave and time tracker."""


starting_balance_app = typer.Typer(help="Manage leave year starting balances.")
