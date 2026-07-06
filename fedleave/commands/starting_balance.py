from __future__ import annotations

from datetime import datetime as _datetime
from pathlib import Path

import typer

from ..cli_app import console, starting_balance_app
from ..cli_helpers import get_leave_year_path, load_leave_year, sanitize_text
from ..ledger import TRANSACTION_CATEGORIES
from ..storage import write_json


@starting_balance_app.command("set")
def starting_balance_set(
    year: int = typer.Option(..., help="Leave year."),
    category: str = typer.Option(..., help="Leave category to update."),
    hours: float = typer.Option(..., help="New starting balance hours."),
    reason: str = typer.Option(..., help="Reason for the starting-balance correction."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Set one starting balance and preserve a dated audit history."""
    if category not in TRANSACTION_CATEGORIES:
        console.print(
            f"[red]ERROR:[/red] Invalid category: {category}. Valid categories: {', '.join(TRANSACTION_CATEGORIES)}."
        )
        raise typer.Exit(code=2)
    if hours < 0:
        console.print("[red]ERROR:[/red] --hours must be zero or positive.")
        raise typer.Exit(code=2)

    reason_text = sanitize_text(reason, field_name="reason")
    if not reason_text:
        console.print("[red]ERROR:[/red] --reason is required.")
        raise typer.Exit(code=2)

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    starting_balances = leave_year.setdefault("starting_balances", {})
    old_hours = float(starting_balances.get(category, 0.0))
    new_hours = float(hours)
    starting_balances[category] = new_hours

    carryover = leave_year.setdefault("carryover_from_previous_year", {})
    old_carryover = carryover.get(category)
    carryover_updated = False
    if old_carryover is not None and float(old_carryover) == old_hours:
        carryover[category] = new_hours
        carryover_updated = True

    history = leave_year.setdefault("starting_balance_history", [])
    history.append(
        {
            "updated_at": _datetime.now().isoformat(),
            "year": int(year),
            "category": category,
            "old_hours": old_hours,
            "new_hours": new_hours,
            "reason": reason_text,
            "carryover_updated": carryover_updated,
            "old_carryover_hours": float(old_carryover) if old_carryover is not None else None,
            "new_carryover_hours": float(carryover.get(category)) if category in carryover else None,
        }
    )

    try:
        write_json(get_leave_year_path(year, data_dir), leave_year)
    except Exception as exc:
        console.print(f"[red]ERROR:[/red] Failed to write leave year: {exc}")
        raise typer.Exit(code=4)

    console.print(f"Set {category} starting balance for {year}: {old_hours:.2f} -> {new_hours:.2f}")
    if carryover_updated:
        console.print(f"Updated {category} carryover_from_previous_year to {new_hours:.2f}")
    console.print("Recorded starting balance audit history entry")
