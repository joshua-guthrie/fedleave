from __future__ import annotations

import json
from datetime import datetime as _datetime
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date, resolve_leave_year_for_date, sanitize_text
from ..ledger import (
    TRANSACTION_CATEGORIES,
    TRANSACTION_DIRECTIONS,
    TRANSACTION_STATUSES,
    add_transaction_to_leave_year,
    create_transaction,
    normalize_direction,
)
from ..storage import write_json


@app.command()
def add(
    year: int | None = typer.Option(None, help="Leave year."),
    date: str = typer.Option(..., help="Transaction date YYYY-MM-DD or today."),
    category: str = typer.Option(..., help="Leave category."),
    earned: float | None = typer.Option(None, help="Hours earned."),
    used: float | None = typer.Option(None, help="Hours used."),
    worked: float | None = typer.Option(None, help="Hours worked."),
    adjusted: float | None = typer.Option(None, help="Hours adjusted."),
    description: str = typer.Option("", help="Transaction description."),
    status: str = typer.Option("planned", help="Transaction status."),
    source: str = typer.Option("manual", help="Transaction source."),
    authoritative: bool = typer.Option(False, help="Void existing same-date/category/direction transactions before adding this one."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    show_transaction_ids: bool = typer.Option(
        False,
        "--show-transaction-ids",
        "--ShowTransactionIDs",
        help="Show transaction IDs in human-readable output.",
    ),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(status, OptionInfo):
        status = "planned"
    if isinstance(source, OptionInfo):
        source = "manual"
    if not isinstance(authoritative, bool):
        authoritative = False
    if isinstance(show_transaction_ids, OptionInfo):
        show_transaction_ids = False
    if not isinstance(json_output, bool):
        json_output = False

    try:
        direction, hours = normalize_direction(earned, used, worked, adjusted)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    # validate date and sanitize inputs before proceeding
    try:
        parsed = parse_iso_date(date)
        date = parsed.isoformat()
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    try:
        description = sanitize_text(description, field_name="description")
        source = sanitize_text(source, field_name="source")
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    try:
        if year is None:
            year, leave_year = resolve_leave_year_for_date(date, data_dir)
        else:
            leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    existing_ids = [transaction["id"] for transaction in leave_year.get("transactions", [])]
    try:
        transaction = create_transaction(
            date=date,
            category=category,
            direction=direction,
            hours=hours,
            description=description,
            status=status,
            source=source,
            existing_ids=existing_ids,
        )
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    replaced_ids: list[str] = []
    if authoritative:
        for existing in leave_year.get("transactions", []):
            if existing.get("void"):
                continue
            if (
                existing.get("date") == date
                and existing.get("category") == category
                and existing.get("direction") == direction
            ):
                existing["void"] = True
                existing["void_reason"] = f"Replaced by authoritative transaction {transaction.id}"
                replaced_ids.append(existing.get("id", ""))

    add_transaction_to_leave_year(leave_year, transaction)
    write_json(get_leave_year_path(year, data_dir), leave_year)
    result = {
        "action": "added",
        "year": year,
        "transaction_id": transaction.id,
        "transaction": transaction.model_dump(),
        "replaced_transaction_ids": replaced_ids,
        "automatic_accruals_posted": 0,
    }
    if json_output:
        _print_json(result)
        return
    detail = f"transaction [bold]{transaction.id}[/bold]" if show_transaction_ids else "transaction"
    if replaced_ids:
        replaced_detail = f"; replaced {', '.join(replaced_ids)}" if show_transaction_ids else f"; replaced {len(replaced_ids)} existing transaction(s)"
        console.print(f"Added {detail} to {year}{replaced_detail}")
    else:
        console.print(f"Added {detail} to {year}")


@app.command()
def reconcile(
    date: str = typer.Option(..., help="Transaction date YYYY-MM-DD or today."),
    category: str = typer.Option(..., help="Leave category."),
    direction: str = typer.Option(..., help="Transaction direction."),
    hours: float = typer.Option(..., help="Reconciled hours."),
    reason: str = typer.Option(..., help="Reason for the reconciliation."),
    status: str = typer.Option("reconciled", help="Transaction status."),
    source: str = typer.Option("clocking-report", help="Transaction source."),
    id: str | None = typer.Option(None, help="Transaction ID to update when multiple active matches exist."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Add or update one transaction using payroll reconciliation semantics."""
    if isinstance(id, OptionInfo):
        id = None
    if isinstance(status, OptionInfo):
        status = "reconciled"
    if isinstance(source, OptionInfo):
        source = "clocking-report"
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        date = parse_iso_date(date).isoformat()
        reason = sanitize_text(reason, field_name="reason")
        source = sanitize_text(source, field_name="source")
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    if not reason:
        console.print("[red]ERROR:[/red] --reason is required.")
        raise typer.Exit(code=2)
    if category not in TRANSACTION_CATEGORIES:
        console.print(
            f"[red]ERROR:[/red] Invalid category: {category}. Valid categories: {', '.join(TRANSACTION_CATEGORIES)}."
        )
        raise typer.Exit(code=2)
    if direction not in TRANSACTION_DIRECTIONS:
        console.print(
            f"[red]ERROR:[/red] Invalid direction: {direction}. Valid directions: {', '.join(TRANSACTION_DIRECTIONS)}."
        )
        raise typer.Exit(code=2)
    if status not in TRANSACTION_STATUSES:
        console.print(f"[red]ERROR:[/red] Invalid status: {status}. Valid statuses: {', '.join(TRANSACTION_STATUSES)}.")
        raise typer.Exit(code=2)
    if hours < 0:
        console.print("[red]ERROR:[/red] --hours must be zero or positive.")
        raise typer.Exit(code=2)

    try:
        year, leave_year = resolve_leave_year_for_date(date, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    transactions = leave_year.setdefault("transactions", [])
    active_matches = [
        transaction
        for transaction in transactions
        if not transaction.get("void")
        and transaction.get("date") == date
        and transaction.get("category") == category
        and transaction.get("direction") == direction
    ]

    if id:
        active_matches = [transaction for transaction in active_matches if transaction.get("id") == id]
        if not active_matches:
            console.print(f"[red]ERROR:[/red] Active matching transaction {id} not found")
            raise typer.Exit(code=1)

    if len(active_matches) > 1:
        result = {
            "action": "ambiguous",
            "year": year,
            "date": date,
            "category": category,
            "direction": direction,
            "matching_transaction_ids": [transaction.get("id") for transaction in active_matches],
            "message": "Multiple active matching transactions found; rerun with --id.",
        }
        if json_output:
            console.print(json.dumps(result, indent=2))
        else:
            console.print("[red]ERROR:[/red] Multiple active matching transactions found; rerun with --id:")
            for transaction in active_matches:
                console.print(
                    f"  {transaction.get('id')} {transaction.get('date')} {transaction.get('category')} {transaction.get('direction')} {transaction.get('hours')}"
                )
        raise typer.Exit(code=2)

    if len(active_matches) == 1:
        transaction = active_matches[0]
        old_values = {
            "hours": float(transaction.get("hours", 0.0)),
            "status": transaction.get("status"),
            "source": transaction.get("source"),
            "description": transaction.get("description", ""),
        }
        transaction["hours"] = float(hours)
        transaction["status"] = status
        transaction["source"] = source
        transaction["description"] = reason
        transaction["updated_at"] = _datetime.now().isoformat()
        transaction.setdefault("reconcile_history", []).append(
            {
                "updated_at": transaction["updated_at"],
                "reason": reason,
                "old": old_values,
                "new": {
                    "hours": float(hours),
                    "status": status,
                    "source": source,
                    "description": reason,
                },
            }
        )
        action = "updated"
        transaction_id = transaction.get("id")
    else:
        existing_ids = [transaction.get("id", "") for transaction in transactions]
        try:
            new_transaction = create_transaction(
                date=date,
                category=category,
                direction=direction,
                hours=hours,
                description=reason,
                status=status,
                source=source,
                existing_ids=existing_ids,
            )
        except ValueError as exc:
            console.print(f"[red]ERROR:[/red] {exc}")
            raise typer.Exit(code=2)
        add_transaction_to_leave_year(leave_year, new_transaction)
        action = "added"
        transaction_id = new_transaction.id

    write_json(get_leave_year_path(year, data_dir), leave_year)

    result = {
        "action": action,
        "year": year,
        "transaction_id": transaction_id,
        "date": date,
        "category": category,
        "direction": direction,
        "hours": float(hours),
        "status": status,
        "source": source,
        "reason": reason,
    }
    if json_output:
        console.print(json.dumps(result, indent=2))
    else:
        console.print(f"Reconciled {category} {direction} on {date}: {action} transaction {transaction_id} in {year}")

@app.command()
def correct(
    id: str | None = typer.Option(None, help="Transaction ID to correct (YYYYMMDD-NNN)."),
    hours: float = typer.Option(..., help="Corrected hours to record."),
    reason: str = typer.Option(..., help="Reason for correction."),
    date: str | None = typer.Option(None, help="Optional date for replacement transaction YYYY-MM-DD or today."),
    category: str | None = typer.Option(None, help="Optional category for replacement transaction."),
    direction: str | None = typer.Option(None, help="Optional direction for replacement transaction (earned/used/worked/adjusted)."),
    # human-friendly lookup: find transaction by date and type/category
    search_date: str | None = typer.Option(None, help="Find transaction by this transaction date YYYY-MM-DD or today."),
    search_type: str | None = typer.Option(None, help="Find transaction by this transaction category/type."),
    preview: bool = typer.Option(False, help="Preview the correction without writing changes."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    show_transaction_ids: bool = typer.Option(
        False,
        "--show-transaction-ids",
        "--ShowTransactionIDs",
        help="Show transaction IDs in human-readable output.",
    ),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Audit-safe correction: void the original transaction and create a replacement.

    The replacement transaction will link to the original via `replaces_transaction_id`.
    """
    # If this function is called directly (tests), Typer Option defaults arrive as OptionInfo objects.
    # Coerce those to None so direct calls behave like CLI invocation.
    if isinstance(id, OptionInfo):
        id = None
    if isinstance(date, OptionInfo):
        date = None
    if isinstance(category, OptionInfo):
        category = None
    if isinstance(direction, OptionInfo):
        direction = None
    if isinstance(search_date, OptionInfo):
        search_date = None
    if isinstance(search_type, OptionInfo):
        search_type = None
    if isinstance(show_transaction_ids, OptionInfo):
        show_transaction_ids = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    # Determine lookup target: if id provided use it, otherwise try search_date+search_type
    if not id:
        if search_date and search_type:
            try:
                search_date = parse_iso_date(search_date).isoformat()
            except ValueError as exc:
                console.print(f"[red]ERROR:[/red] {exc}")
                raise typer.Exit(code=2)

            try:
                _, ly = resolve_leave_year_for_date(search_date, data_dir)
            except FileNotFoundError as exc:
                console.print(f"[red]ERROR:[/red] {exc}")
                raise typer.Exit(code=1)

            matches = [t for t in ly.get("transactions", []) if t.get("date") == search_date and t.get("category") == search_type and not t.get("void")]
            if not matches:
                console.print(f"[red]ERROR:[/red] No matching transaction on {search_date} for category {search_type}")
                raise typer.Exit(code=1)
            if len(matches) > 1:
                console.print(f"[red]ERROR:[/red] Multiple matching transactions found; specify the transaction id:")
                for t in matches:
                    console.print(f"  {t.get('id')} {t.get('date')} {t.get('category')} {t.get('direction')} {t.get('hours')}")
                raise typer.Exit(code=2)

            # single match — use its id and set leave_year to the loaded year
            id = matches[0].get("id")
            leave_year = ly
        else:
            console.print("[red]ERROR:[/red] Either --id or both --search-date and --search-type are required")
            raise typer.Exit(code=2)
    else:
        try:
            leave_year = load_leave_year(int(id[:4]) if id and id[0:4].isdigit() else None, data_dir)
        except FileNotFoundError:
            # Fallback: try reading default year file via scan
            try:
                # attempt to locate the leave year containing the transaction
                base_dir = get_leave_year_path(0, data_dir).parent
                found = None
                for pj in base_dir.iterdir():
                    if pj.suffix == ".json":
                        ly = load_leave_year(int(pj.stem), data_dir)
                        for t in ly.get("transactions", []):
                            if t.get("id") == id:
                                leave_year = ly
                                found = pj
                                break
                    if found:
                        break
                if not found:
                    raise typer.Exit(code=1)
            except Exception:
                console.print(f"[red]ERROR:[/red] Transaction {id} not found")
                raise typer.Exit(code=1)

    # locate original transaction
    orig = None
    for t in leave_year.get("transactions", []):
        if t.get("id") == id:
            orig = t
            break
    if not orig:
        console.print(f"[red]ERROR:[/red] Transaction {id} not found")
        raise typer.Exit(code=1)

    # coerce possible Typer Option objects when called programmatically
    if not (isinstance(date, str) or date is None):
        date = None
    if not (isinstance(category, str) or category is None):
        category = None
    if not (isinstance(direction, str) or direction is None):
        direction = None
    if not isinstance(preview, bool):
        preview = False

    if date:
        try:
            date = parse_iso_date(date).isoformat()
        except ValueError as exc:
            console.print(f"[red]ERROR:[/red] {exc}")
            raise typer.Exit(code=2)

    if preview:
        if json_output:
            _print_json(
                {
                    "action": "preview",
                    "original_transaction_id": id,
                    "replacement": {
                        "date": date or orig["date"],
                        "category": category or orig["category"],
                        "direction": direction or orig["direction"],
                        "hours": hours,
                    },
                    "would_void_transaction_ids": [id],
                    "would_create_replacement": True,
                }
            )
            return
        console.print("Preview: would void original transaction and create replacement with:")
        console.print(f"  date={date or orig['date']} category={category or orig['category']} direction={direction or orig['direction']} hours={hours}")
        return

    # void original
    orig["void"] = True
    orig["void_reason"] = f"Correction: {reason}"

    # Sanitize reason before creating replacement.
    try:
        reason = sanitize_text(reason, field_name="reason")
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    # create replacement
    existing_ids = [t["id"] for t in leave_year.get("transactions", [])]
    try:
        replacement = create_transaction(
            date=date or orig["date"],
            category=category or orig["category"],
            direction=direction or orig["direction"],
            hours=hours,
            description=f"Correction of {id}: {reason}",
            status="reconciled",
            source="correction",
            existing_ids=existing_ids,
        )
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    # link replacement to original by setting fields on the model
    replacement.replaces_transaction_id = id
    replacement.correction_reason = reason

    add_transaction_to_leave_year(leave_year, replacement)
    write_json(get_leave_year_path(int(leave_year.get("leave_year", 0)), data_dir), leave_year)
    if json_output:
        _print_json(
            {
                "action": "corrected",
                "year": int(leave_year.get("leave_year", 0)),
                "original_transaction_id": id,
                "voided_transaction_ids": [id],
                "replacement_transaction_id": replacement.id,
                "replacement_transaction": replacement.model_dump(),
                "reason": reason,
            }
        )
        return
    if show_transaction_ids:
        console.print(f"Corrected transaction {id}: created replacement {replacement.id}")
    else:
        console.print("Corrected transaction and created replacement")

@app.command(name="list")
def list_transactions(
    year: int = typer.Option(..., help="Leave year."),
    show_transaction_ids: bool = typer.Option(
        False,
        "--show-transaction-ids",
        "--ShowTransactionIDs",
        help="Show transaction IDs in human-readable output.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(show_transaction_ids, OptionInfo):
        show_transaction_ids = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    transactions = [transaction for transaction in leave_year.get("transactions", []) if not transaction.get("void")]
    if not transactions:
        if json_output:
            _print_json({"year": year, "transactions": []})
            return
        console.print(f"No transactions found for {year}.")
        raise typer.Exit(code=0)

    transactions = sorted(transactions, key=lambda item: item["id"])
    if json_output:
        _print_json({"year": year, "transactions": transactions})
        return

    for transaction in transactions:
        transaction_id = f"{transaction['id']} " if show_transaction_ids else ""
        console.print(
            f"{transaction_id}{transaction['date']} {transaction['category']} {transaction['direction']} {transaction['hours']} {transaction['status']} {transaction['description']}"
        )

@app.command()
def void(
    id: str = typer.Option(..., help="Transaction ID to void (YYYYMMDD-NNN)."),
    reason: str = typer.Option("", help="Reason for voiding the transaction."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    show_transaction_ids: bool = typer.Option(
        False,
        "--show-transaction-ids",
        "--ShowTransactionIDs",
        help="Show transaction IDs in human-readable output.",
    ),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Void a transaction while preserving the audit trail."""
    if isinstance(show_transaction_ids, OptionInfo):
        show_transaction_ids = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    # find the transaction across leave years if needed
    base = get_leave_year_path(0, data_dir).parent
    found = False
    for pj in base.iterdir():
        if pj.suffix == ".json":
            ly = load_leave_year(int(pj.stem), data_dir)
            for t in ly.get("transactions", []):
                if t.get("id") == id:
                    t["void"] = True
                    t["void_reason"] = reason or "Voided by user"
                    write_json(pj, ly)
                    if json_output:
                        _print_json(
                            {
                                "action": "voided",
                                "year": int(pj.stem),
                                "transaction_id": id,
                                "voided_transaction_ids": [id],
                                "reason": t["void_reason"],
                                "file": str(pj),
                            }
                        )
                        return
                    detail = f"transaction {id}" if show_transaction_ids else "transaction"
                    console.print(f"Voided {detail} in {pj.name}")
                    found = True
                    break
        if found:
            break
    if not found:
        console.print(f"[red]ERROR:[/red] Transaction {id} not found")
        raise typer.Exit(code=1)

@app.command()
def types(
    which: str = typer.Option("both", help="Which types to show: 'categories', 'directions', or 'both'."),
) -> None:
    """Show supported leave categories and transaction directions."""
    valid = {"categories", "directions", "both"}
    if which not in valid:
        console.print(f"[red]ERROR:[/red] Invalid --which value: {which}. Use categories|directions|both")
        raise typer.Exit(code=2)

    if which in ("categories", "both"):
        console.print("Supported leave categories:")
        console.print("  " + ", ".join(TRANSACTION_CATEGORIES))

    if which in ("directions", "both"):
        console.print("Supported transaction directions:")
        console.print("  " + ", ".join(TRANSACTION_DIRECTIONS))
