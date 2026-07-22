from __future__ import annotations

import json
from datetime import datetime as _datetime
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date, resolve_leave_year_for_date, sanitize_text
from ..ledger import (
    Transaction,
    TRANSACTION_CATEGORIES,
    TRANSACTION_DIRECTIONS,
    TRANSACTION_STATUSES,
    add_transaction_to_leave_year,
    create_transaction,
    normalize_direction,
)
from ..storage import write_json

_SET_DAY_CATEGORIES = [
    "annual",
    "sick",
    "credit",
    "comp",
    "travel_comp",
    "overtime",
    "admin",
    "lwop",
    "military",
    "court",
    "religious_comp",
    "time_off_award",
    "excused",
    "holiday",
    "flex",
    "other",
    "restored_annual",
]


def _direction_for_signed_day_value(category: str, value: float) -> tuple[str, float]:
    if value < 0:
        return "used", abs(value)
    if category == "overtime":
        return "worked", value
    return "earned", value


def _set_day_values(
    *,
    date: str,
    values: dict[str, float | None],
    comments: dict[str, str | None],
    authoritative: bool,
    data_dir: Path | None,
) -> dict:
    if not authoritative:
        raise ValueError("--authoritative is required for set-day.")

    date = parse_iso_date(date).isoformat()
    year, leave_year = resolve_leave_year_for_date(date, data_dir)
    transactions = leave_year.setdefault("transactions", [])
    existing_ids = [transaction.get("id", "") for transaction in transactions]
    changed: list[dict] = []
    removed_ids: list[str] = []
    created_ids: list[str] = []

    for category in _SET_DAY_CATEGORIES:
        value = values.get(category)
        if value is None:
            continue
        value = float(value)
        direction, hours = _direction_for_signed_day_value(category, value)

        replaced = [
            transaction
            for transaction in transactions
            if transaction.get("date") == date and transaction.get("category") == category
        ]
        existing_comment = next(
            (str(transaction.get("description", "")).strip() for transaction in replaced if str(transaction.get("description", "")).strip()),
            "",
        )
        raw_comment = comments.get(category)
        if raw_comment is None:
            comment = existing_comment
        else:
            comment = sanitize_text(raw_comment, field_name=f"{category} comment")

        removed_ids.extend(str(transaction.get("id", "")) for transaction in replaced)
        transactions[:] = [transaction for transaction in transactions if transaction not in replaced]

        new_id = None
        if hours:
            transaction = create_transaction(
                date=date,
                category=category,
                direction=direction,
                hours=hours,
                description=comment,
                status="reconciled",
                source="set-day",
                existing_ids=existing_ids,
            )
            add_transaction_to_leave_year(leave_year, transaction)
            existing_ids.append(transaction.id)
            new_id = transaction.id
            created_ids.append(transaction.id)

        changed.append(
            {
                "category": category,
                "value": value,
                "direction": direction if hours else None,
                "hours": hours,
                "comment": comment,
                "transaction_id": new_id,
            }
        )

    write_json(get_leave_year_path(year, data_dir), leave_year)
    return {
        "action": "set-day",
        "year": year,
        "date": date,
        "authoritative": True,
        "changed": changed,
        "removed_transaction_ids": removed_ids,
        "created_transaction_ids": created_ids,
    }


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
    authoritative: bool = typer.Option(False, help="Remove existing same-date/category/direction transactions before adding this one."),
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
        retained = []
        for existing in leave_year.get("transactions", []):
            if (
                existing.get("date") == date
                and existing.get("category") == category
                and existing.get("direction") == direction
            ):
                replaced_ids.append(existing.get("id", ""))
            else:
                retained.append(existing)
        leave_year["transactions"] = retained

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


@app.command(name="set-day")
def set_day(
    date: str = typer.Option(..., help="Date to update YYYY-MM-DD or today."),
    authoritative: bool = typer.Option(False, help="Replace active transactions for supplied categories on this date."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    annual: float | None = typer.Option(None, help="Signed annual leave hours."),
    annual_comment: str | None = typer.Option(None, help="Annual leave comment."),
    sick: float | None = typer.Option(None, help="Signed sick leave hours."),
    sick_comment: str | None = typer.Option(None, help="Sick leave comment."),
    credit: float | None = typer.Option(None, help="Signed credit hours."),
    credit_comment: str | None = typer.Option(None, help="Credit hours comment."),
    comp: float | None = typer.Option(None, help="Signed comp time hours."),
    comp_comment: str | None = typer.Option(None, help="Comp time comment."),
    travel_comp: float | None = typer.Option(None, "--travel-comp", help="Signed travel comp hours."),
    travel_comp_comment: str | None = typer.Option(None, "--travel-comp-comment", help="Travel comp comment."),
    overtime: float | None = typer.Option(None, help="Signed overtime hours."),
    overtime_comment: str | None = typer.Option(None, help="Overtime comment."),
    admin: float | None = typer.Option(None, help="Signed admin leave hours."),
    admin_comment: str | None = typer.Option(None, help="Admin leave comment."),
    lwop: float | None = typer.Option(None, help="Signed LWOP hours."),
    lwop_comment: str | None = typer.Option(None, help="LWOP comment."),
    military: float | None = typer.Option(None, help="Signed military leave hours."),
    military_comment: str | None = typer.Option(None, help="Military leave comment."),
    court: float | None = typer.Option(None, help="Signed court leave hours."),
    court_comment: str | None = typer.Option(None, help="Court leave comment."),
    religious_comp: float | None = typer.Option(None, "--religious-comp", help="Signed religious comp hours."),
    religious_comp_comment: str | None = typer.Option(None, "--religious-comp-comment", help="Religious comp comment."),
    time_off_award: float | None = typer.Option(None, "--time-off-award", help="Signed time-off award hours."),
    time_off_award_comment: str | None = typer.Option(None, "--time-off-award-comment", help="Time-off award comment."),
    excused: float | None = typer.Option(None, help="Signed excused leave hours."),
    excused_comment: str | None = typer.Option(None, help="Excused leave comment."),
    holiday: float | None = typer.Option(None, help="Signed holiday hours."),
    holiday_comment: str | None = typer.Option(None, help="Holiday comment."),
    flex: float | None = typer.Option(None, help="Signed flex hours."),
    flex_comment: str | None = typer.Option(None, help="Flex comment."),
    other: float | None = typer.Option(None, help="Signed other leave hours."),
    other_comment: str | None = typer.Option(None, help="Other leave comment."),
    restored_annual: float | None = typer.Option(None, "--restored-annual", help="Signed restored annual leave hours."),
    restored_annual_comment: str | None = typer.Option(None, "--restored-annual-comment", help="Restored annual leave comment."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if not isinstance(authoritative, bool):
        authoritative = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None
    if isinstance(annual_comment, OptionInfo):
        annual_comment = None
    if isinstance(sick_comment, OptionInfo):
        sick_comment = None
    if isinstance(credit_comment, OptionInfo):
        credit_comment = None
    if isinstance(comp_comment, OptionInfo):
        comp_comment = None
    if isinstance(travel_comp_comment, OptionInfo):
        travel_comp_comment = None
    if isinstance(overtime_comment, OptionInfo):
        overtime_comment = None
    if isinstance(admin_comment, OptionInfo):
        admin_comment = None
    if isinstance(lwop_comment, OptionInfo):
        lwop_comment = None
    if isinstance(military_comment, OptionInfo):
        military_comment = None
    if isinstance(court_comment, OptionInfo):
        court_comment = None
    if isinstance(religious_comp_comment, OptionInfo):
        religious_comp_comment = None
    if isinstance(time_off_award_comment, OptionInfo):
        time_off_award_comment = None
    if isinstance(excused_comment, OptionInfo):
        excused_comment = None
    if isinstance(holiday_comment, OptionInfo):
        holiday_comment = None
    if isinstance(flex_comment, OptionInfo):
        flex_comment = None
    if isinstance(other_comment, OptionInfo):
        other_comment = None
    if isinstance(restored_annual_comment, OptionInfo):
        restored_annual_comment = None

    values = {
        "annual": annual,
        "sick": sick,
        "credit": credit,
        "comp": comp,
        "travel_comp": travel_comp,
        "overtime": overtime,
        "admin": admin,
        "lwop": lwop,
        "military": military,
        "court": court,
        "religious_comp": religious_comp,
        "time_off_award": time_off_award,
        "excused": excused,
        "holiday": holiday,
        "flex": flex,
        "other": other,
        "restored_annual": restored_annual,
    }
    comments = {
        "annual": annual_comment,
        "sick": sick_comment,
        "credit": credit_comment,
        "comp": comp_comment,
        "travel_comp": travel_comp_comment,
        "overtime": overtime_comment,
        "admin": admin_comment,
        "lwop": lwop_comment,
        "military": military_comment,
        "court": court_comment,
        "religious_comp": religious_comp_comment,
        "time_off_award": time_off_award_comment,
        "excused": excused_comment,
        "holiday": holiday_comment,
        "flex": flex_comment,
        "other": other_comment,
        "restored_annual": restored_annual_comment,
    }
    values = {key: value for key, value in values.items() if not isinstance(value, OptionInfo)}
    if all(value is None for value in values.values()):
        console.print("[red]ERROR:[/red] At least one leave category value is required.")
        raise typer.Exit(code=2)

    try:
        result = _set_day_values(
            date=date,
            values=values,
            comments=comments,
            authoritative=authoritative,
            data_dir=data_dir,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    if json_output:
        _print_json(result)
        return

    console.print(
        f"Updated {result['date']} in leave year {result['year']} "
        f"({len(result['created_transaction_ids'])} created, {len(result['removed_transaction_ids'])} removed)."
    )


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
        if transaction.get("date") == date
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
        transaction["hours"] = float(hours)
        transaction["status"] = status
        transaction["source"] = source
        transaction["description"] = reason
        transaction["updated_at"] = _datetime.now().isoformat()
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
    date: str | None = typer.Option(None, help="Optional corrected transaction date YYYY-MM-DD or today."),
    category: str | None = typer.Option(None, help="Optional corrected transaction category."),
    direction: str | None = typer.Option(None, help="Optional corrected direction (earned/used/worked/adjusted)."),
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
    """Update a transaction in place, retaining only its final values."""
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

            matches = [t for t in ly.get("transactions", []) if t.get("date") == search_date and t.get("category") == search_type]
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
                    "would_update_transaction_id": id,
                }
            )
            return
        console.print("Preview: would update transaction with:")
        console.print(f"  date={date or orig['date']} category={category or orig['category']} direction={direction or orig['direction']} hours={hours}")
        return

    # Sanitize the reason before updating the final record.
    try:
        reason = sanitize_text(reason, field_name="reason")
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    try:
        updated = Transaction.model_validate(
            {
                **orig,
                "date": date or orig["date"],
                "category": category or orig["category"],
                "direction": direction or orig["direction"],
                "hours": hours,
                "description": reason,
                "status": "reconciled",
                "source": "correction",
                "updated_at": _datetime.now().isoformat(),
            }
        ).model_dump()
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    orig.clear()
    orig.update(updated)
    write_json(get_leave_year_path(int(leave_year.get("leave_year", 0)), data_dir), leave_year)
    if json_output:
        _print_json(
            {
                "action": "corrected",
                "year": int(leave_year.get("leave_year", 0)),
                "original_transaction_id": id,
                "transaction_id": id,
                "transaction": orig,
                "reason": reason,
            }
        )
        return
    if show_transaction_ids:
        console.print(f"Corrected transaction {id} in place")
    else:
        console.print("Corrected transaction in place")

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

    transactions = list(leave_year.get("transactions", []))
    if not transactions:
        if json_output:
            _print_json({**leave_year, "year": year, "transactions": []})
            return
        console.print(f"No transactions found for {year}.")
        raise typer.Exit(code=0)

    transactions = sorted(transactions, key=lambda item: item["id"])
    if json_output:
        # Keep the existing transaction list interface while exposing the
        # normalized leave-year metadata required by read-only companions.
        _print_json({**leave_year, "year": year, "transactions": transactions})
        return

    for transaction in transactions:
        transaction_id = f"{transaction['id']} " if show_transaction_ids else ""
        console.print(
            f"{transaction_id}{transaction['date']} {transaction['category']} {transaction['direction']} {transaction['hours']} {transaction['status']} {transaction['description']}"
        )

@app.command()
def void(
    id: str = typer.Option(..., help="Transaction ID to delete (YYYYMMDD-NNN)."),
    reason: str = typer.Option("", help="Optional reason for deleting the transaction (not stored)."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    show_transaction_ids: bool = typer.Option(
        False,
        "--show-transaction-ids",
        "--ShowTransactionIDs",
        help="Show transaction IDs in human-readable output.",
    ),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Delete a transaction. The command name is retained for compatibility."""
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
            for t in list(ly.get("transactions", [])):
                if t.get("id") == id:
                    ly["transactions"].remove(t)
                    write_json(pj, ly)
                    if json_output:
                        _print_json(
                            {
                                "action": "deleted",
                                "year": int(pj.stem),
                                "transaction_id": id,
                                "deleted_transaction_ids": [id],
                                "reason": reason,
                                "file": str(pj),
                            }
                        )
                        return
                    detail = f"transaction {id}" if show_transaction_ids else "transaction"
                    console.print(f"Deleted {detail} from {pj.name}")
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
