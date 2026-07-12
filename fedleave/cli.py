from __future__ import annotations

import typer

from .cli_app import HELP_TEXT, _print_json, app, console, starting_balance_app
from .commands.data import export_data, import_data, init, validate
from .commands.transactions import add, correct, list_transactions, reconcile, set_day, types, void
from .commands.starting_balance import starting_balance_set
from .commands.rollover import rollover
from .commands.holidays import holidays
from .commands.balances import balance, daily_activity, month, pay_period_summary, pay_periods_summary, use_or_lose
from .commands.accruals import accrual_change

app.add_typer(starting_balance_app, name="starting-balance")


@app.command()
def help() -> None:
    typer.echo(HELP_TEXT)


if __name__ == "__main__":
    app()
