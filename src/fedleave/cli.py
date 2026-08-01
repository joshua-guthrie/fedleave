"""Register all command modules and compatibility help commands."""

from __future__ import annotations

import typer

from .cli_app import HELP_TEXT, _print_json, app, console, starting_balance_app
from .commands.accruals import accrual_change
from .commands.balances import (
    balance,
    compare_leave_balances,
    daily_activity,
    month,
    pay_period_summary,
    pay_periods_summary,
    use_or_lose,
)
from .commands.data import export_data, import_data, import_wms_http, init, validate, years
from .commands.expirations import expiration_extend, expirations
from .commands.forced_balance import force_balance
from .commands.holidays import holidays
from .commands.rollover import rollover
from .commands.starting_balance import starting_balance_set
from .commands.transactions import add, correct, list_transactions, reconcile, set_day, types, void
from .commands.updates import check_for_updates_command

__all__ = [
    "HELP_TEXT",
    "_print_json",
    "accrual_change",
    "add",
    "app",
    "balance",
    "check_for_updates_command",
    "compare_leave_balances",
    "console",
    "correct",
    "daily_activity",
    "expiration_extend",
    "expirations",
    "export_data",
    "force_balance",
    "holidays",
    "import_data",
    "import_wms_http",
    "init",
    "list_transactions",
    "month",
    "pay_period_summary",
    "pay_periods_summary",
    "reconcile",
    "rollover",
    "set_day",
    "starting_balance_app",
    "starting_balance_set",
    "types",
    "use_or_lose",
    "validate",
    "void",
    "years",
]

app.add_typer(starting_balance_app, name="starting-balance")


@app.command()
def help() -> None:
    typer.echo(HELP_TEXT)


if __name__ == "__main__":
    app()
