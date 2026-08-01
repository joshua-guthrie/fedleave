from __future__ import annotations

from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import (
    get_leave_year_path,
    load_leave_year,
    parse_iso_date,
    resolve_leave_year_for_date,
    sanitize_text,
)
from ..ledger import ensure_automatic_accruals, upsert_accrual_rate_change
from ..storage import write_json


@app.command("accrual-change")
def accrual_change(
    year: int | None = typer.Option(None, help="Leave year. Defaults to the leave year containing --as-of."),
    as_of: str = typer.Option(..., help="Effective date YYYY-MM-DD or today."),
    category: str = typer.Option(..., help="Automatic accrual category: annual or sick."),
    hours: float = typer.Option(..., help="New hours earned per pay period from --as-of forward."),
    reason: str = typer.Option("", help="Reason for the accrual-rate change."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(year, OptionInfo):
        year = None
    if isinstance(reason, OptionInfo):
        reason = ""
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        effective_date = parse_iso_date(as_of).isoformat()
        category = sanitize_text(category, field_name="category").lower()
        reason = sanitize_text(reason, field_name="reason")
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    try:
        if year is None:
            year, leave_year = resolve_leave_year_for_date(effective_date, data_dir)
        else:
            leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    leave_year_end = leave_year.get("leave_year_end")
    if not leave_year_end:
        console.print("[red]ERROR:[/red] Leave year is missing leave_year_end.")
        raise typer.Exit(code=2)
    try:
        leave_year_start_date = parse_iso_date(str(leave_year.get("leave_year_start", "")))
        leave_year_end_date = parse_iso_date(str(leave_year_end))
        effective = parse_iso_date(effective_date)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)
    if not leave_year_start_date <= effective <= leave_year_end_date:
        console.print(
            f"[red]ERROR:[/red] --as-of {effective_date} is outside leave year "
            f"{year} ({leave_year_start_date.isoformat()} to {leave_year_end_date.isoformat()})."
        )
        raise typer.Exit(code=2)

    try:
        result = upsert_accrual_rate_change(
            leave_year,
            category=category,
            effective_date=effective_date,
            hours_per_pay_period=float(hours),
            reason=reason,
        )
        added_accruals = ensure_automatic_accruals(leave_year, str(leave_year_end))
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    write_json(get_leave_year_path(year, data_dir), leave_year)

    payload = {
        "action": "accrual_changed",
        "year": year,
        **result,
        "automatic_accruals_posted": added_accruals,
        "accrual_rate_changes": leave_year.get("accrual_rate_changes", []),
    }
    if json_output:
        _print_json(payload)
        return

    console.print(
        f"Changed {category} accrual for {year} as of {effective_date}: "
        f"{result['previous_hours_per_pay_period']:.2f} -> {result['new_hours_per_pay_period']:.2f}"
    )
    console.print(f"Updated {result['updated_auto_accrual_transactions']} automatic {category} accrual transactions.")
    if added_accruals:
        console.print(f"Posted {added_accruals} missing automatic accrual transactions through {leave_year_end}.")
