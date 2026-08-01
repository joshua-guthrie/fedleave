from __future__ import annotations

from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import get_leave_year_path, parse_iso_date, resolve_leave_year_for_date, sanitize_text
from ..ledger import TRANSACTION_CATEGORIES, add_transaction_to_leave_year, calculate_balances, create_transaction
from ..storage import write_json


@app.command("force-balance")
def force_balance(
    date: str = typer.Option(..., help="Effective date YYYY-MM-DD or today."),
    category: str = typer.Option(..., help="Leave category whose balance will be forced."),
    hours: float = typer.Option(..., help="Required balance as of the effective date."),
    comment: str = typer.Option(..., help="Required explanation for the adjustment."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(data_dir, OptionInfo):
        data_dir = None
    if not isinstance(json_output, bool):
        json_output = False
    try:
        effective_date = parse_iso_date(date).isoformat()
        if category not in TRANSACTION_CATEGORIES:
            raise ValueError(f"Invalid category: {category}.")
        if hours < 0:
            raise ValueError("Forced balance must be zero or positive.")
        comment = sanitize_text(comment, field_name="comment")
        if not comment:
            raise ValueError("A comment is required for a forced balance.")
        year, leave_year = resolve_leave_year_for_date(effective_date, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    transactions = leave_year.setdefault("transactions", [])
    replaced_ids = [
        str(tx.get("id", ""))
        for tx in transactions
        if not tx.get("void")
        and tx.get("source") == "forced-balance"
        and tx.get("date") == effective_date
        and tx.get("category") == category
    ]
    if replaced_ids:
        transactions[:] = [tx for tx in transactions if str(tx.get("id", "")) not in replaced_ids]

    previous_balance = float(calculate_balances(leave_year, until_date=effective_date).get(category, 0.0))
    adjustment = float(hours) - previous_balance
    transaction = None
    if abs(adjustment) > 0.000001:
        transaction = create_transaction(
            date=effective_date,
            category=category,
            direction="forced_increase" if adjustment > 0 else "forced_decrease",
            hours=abs(adjustment),
            description=comment,
            status="reconciled",
            source="forced-balance",
            existing_ids=[str(tx.get("id", "")) for tx in transactions],
        )
        add_transaction_to_leave_year(leave_year, transaction)

    write_json(get_leave_year_path(year, data_dir), leave_year)
    result = {
        "action": "balance_forced",
        "year": year,
        "date": effective_date,
        "category": category,
        "previous_balance": previous_balance,
        "forced_balance": float(hours),
        "adjustment": adjustment,
        "transaction_id": transaction.id if transaction else None,
        "replaced_transaction_ids": replaced_ids,
        "comment": comment,
    }
    if json_output:
        _print_json(result)
        return
    console.print(f"Forced {category} balance to {hours:.2f} as of {effective_date} (adjustment {adjustment:+.2f}).")
