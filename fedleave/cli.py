from __future__ import annotations

from pathlib import Path
from typer.models import OptionInfo

import typer
from rich.console import Console

from .cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date, sanitize_text
from .ledger import (
    TRANSACTION_CATEGORIES,
    TRANSACTION_DIRECTIONS,
    TRANSACTION_STATUSES,
    add_transaction_to_leave_year,
    apply_fixes_to_leave_year,
    calculate_balances,
    calculate_daily_activity,
    calculate_pay_period_activity,
    calculate_use_or_lose,
    create_transaction,
    ensure_automatic_accruals,
    normalize_direction,
    validate_leave_year,
)
from .storage import atomic_write_json, ensure_data_dir, load_json, write_json
from .config import get_default_data_dir, load_config
from .holidays import generate_federal_holidays
import json
from .payperiods import generate_pay_periods
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

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
    reconcile   Add or update one reconciled transaction by date/category/direction
    list        List transactions for a leave year
    starting-balance
                Set starting balances with audit history
    balance     Show balances calculated from the ledger
    pay-period  Show earned, used, overtime totals, and balances for a pay period
    pay-periods Show earned, used, overtime totals, and balances for every pay period
    export-data Export config, leave years, and holiday cache to a JSON archive
    import-data Import a JSON archive created by export-data
    correct     Audit-safe correction of transactions
    void        Void a transaction (preserve audit history)
    rollover    Preview or apply leave year rollover
    holidays    Manage federal holiday data
    help        Show this detailed help

Command details and examples:

    fedleave init --year YEAR --leave-year-start YYYY-MM-DD [options]
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

    fedleave add --year YEAR --date YYYY-MM-DD --category CATEGORY [--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS] [--description TEXT] [--status STATUS] [--source SOURCE] [--authoritative] [--json] [--show-transaction-ids]
        Exactly one of `--earned`, `--used`, `--worked`, or `--adjusted` must be provided.
        --authoritative voids active transactions with the same date, category, and direction before adding the new transaction.
        --json emits the created transaction ID and any replaced transaction IDs.
        Transaction IDs are hidden by default in human-readable output. Use --show-transaction-ids when needed.
        Valid categories: annual, sick, overtime, comp, credit, travel_comp, admin, lwop, military, court, religious_comp, time_off_award, excused, holiday, flex, other, restored_annual

    Examples:
        fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
        fedleave add --year 2026 --date 2026-03-10 --category annual --used 3 --status reconciled --authoritative
        fedleave add --year 2026 --date 2026-03-12 --category overtime --worked 3

    fedleave reconcile --date YYYY-MM-DD --category CATEGORY --direction DIRECTION --hours HOURS --reason TEXT [--status STATUS] [--source SOURCE] [--id TRANSACTION_ID] [--json] [--data-dir PATH]
        Infer the leave year from the date, then set the active transaction for that date/category/direction to the requested hours.
        Adds a transaction when no active match exists. Updates exactly one active match and records reconcile_history.
        If multiple active matches exist, rerun with --id to choose the transaction.

    fedleave list --year YEAR [--show-transaction-ids] [--data-dir PATH]
        List transactions for a leave year. Transaction IDs are hidden unless --show-transaction-ids is passed.

    fedleave starting-balance set --year YEAR --category CATEGORY --hours HOURS --reason TEXT [--data-dir PATH]
        Set a leave year's starting balance for one category and record the prior value in starting_balance_history.
        If the matching carryover_from_previous_year value still equals the old starting balance, it is updated too.

    fedleave balance --year YEAR [--as-of YYYY-MM-DD] [--project] [--project-to YYYY-MM-DD] [--use-or-lose] [--json] [--data-dir PATH]
        Show balances calculated from the ledger.
        --project includes projected future annual and sick leave accruals through year end or --project-to.
        --use-or-lose prints projected annual carryover and annual leave lost above the carryover limit.
        --json emits balances, use-or-lose values, and automatic accrual posting details.

    fedleave pay-period --year YEAR --date YYYY-MM-DD [--daily] [--json] [--data-dir PATH]
        Show leave earned/used, overtime worked, optional daily activity, and ending balances for the pay period containing the date.

    fedleave pay-periods --year YEAR [--json] [--data-dir PATH]
        Show earned/used/worked totals and ending balances for every pay period in the leave year.

    fedleave export-data --output fedleave_backup.json [--data-dir PATH]
        Export config, leave year files, and holiday cache to a portable JSON archive.

    fedleave import-data --input fedleave_backup.json [--overwrite] [--data-dir PATH]
        Import a JSON archive created by export-data. Existing files are preserved unless --overwrite is used.

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

app = typer.Typer(help=HELP_TEXT, add_completion=False)
starting_balance_app = typer.Typer(help="Manage leave year starting balances.")

@app.command()
def init(
    year: int = typer.Option(..., help="Leave year."),
    leave_year_start: str = typer.Option(..., help="Leave year start date YYYY-MM-DD."),
    annual_accrual: float = typer.Option(6.0, help="Annual leave accrual hours per pay period."),
    annual_start: float = typer.Option(0.0, help="Starting annual leave hours."),
    sick_start: float = typer.Option(0.0, help="Starting sick leave hours."),
    comp_start: float = typer.Option(0.0, help="Starting comp time hours."),
    credit_start: float = typer.Option(0.0, help="Starting credit hours."),
    travel_comp_start: float = typer.Option(0.0, help="Starting travel comp hours."),
    time_off_award_start: float = typer.Option(0.0, help="Starting time-off award hours."),
    religious_comp_start: float = typer.Option(0.0, help="Starting religious comp hours."),
    restored_annual_start: float = typer.Option(0.0, help="Starting restored annual leave hours."),
    holiday_source: str = typer.Option("python_holidays", help="Holiday source: python_holidays or opm_ics."),
    holiday_ics_url: str = typer.Option(
        "https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/holidays.ics",
        help="iCalendar URL to download federal holidays from when --holiday-source=opm_ics.",
    ),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    from .config import init_config
    # validate leave_year_start early to avoid creating bad state
    try:
        parse_iso_date(leave_year_start)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    init_config(
        year=year,
        leave_year_start=leave_year_start,
        annual_accrual=annual_accrual,
        starting_balances={
            "annual": annual_start,
            "sick": sick_start,
            "comp": comp_start,
            "credit": credit_start,
            "travel_comp": travel_comp_start,
            "time_off_award": time_off_award_start,
            "religious_comp": religious_comp_start,
            "restored_annual": restored_annual_start,
        },
        holiday_source=holiday_source,
        holiday_ics_url=holiday_ics_url,
        data_dir=data_dir,
    )

@app.command()
def add(
    year: int = typer.Option(..., help="Leave year."),
    date: str = typer.Option(..., help="Transaction date YYYY-MM-DD."),
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


def _resolve_leave_year_for_date(transaction_date: str, data_dir: Path | None = None) -> tuple[int, dict]:
    base = get_default_data_dir(data_dir)
    year_dir = base / "leave_years"
    if not year_dir.exists():
        raise FileNotFoundError(f"Leave year directory not found: {year_dir}")

    target = parse_iso_date(transaction_date)
    for path in sorted(year_dir.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            continue
        leave_year = load_json(path)
        try:
            start = parse_iso_date(str(leave_year.get("leave_year_start", "")))
            end = parse_iso_date(str(leave_year.get("leave_year_end", "")))
        except ValueError:
            continue
        if start <= target <= end:
            return int(leave_year.get("leave_year", path.stem)), leave_year

    raise FileNotFoundError(f"No leave year contains date {transaction_date}")


@app.command()
def reconcile(
    date: str = typer.Option(..., help="Transaction date YYYY-MM-DD."),
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
        year, leave_year = _resolve_leave_year_for_date(date, data_dir)
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


def _read_json_files_by_stem(directory: Path) -> dict[str, dict]:
    if not directory.exists():
        return {}
    return {
        path.stem: load_json(path)
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix == ".json"
    }


@app.command("export-data")
def export_data(
    output: Path = typer.Option(..., help="Output JSON archive path."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Export fedleave data to a portable JSON archive."""
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    base = get_default_data_dir(data_dir)
    if not base.exists():
        console.print(f"[red]ERROR:[/red] Data directory not found: {base}")
        raise typer.Exit(code=1)

    archive = {
        "schema_version": 1,
        "exported_at": _datetime.now().isoformat(),
        "source_data_dir": str(base),
        "config": load_json(base / "config.json") if (base / "config.json").exists() else None,
        "leave_years": _read_json_files_by_stem(base / "leave_years"),
        "holiday_cache": _read_json_files_by_stem(base / "holiday_cache"),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output, archive)
    console.print(f"Exported fedleave data to {output}")


def _write_import_file(path: Path, data: dict, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    if path.exists():
        write_json(path, data, backup=True)
    else:
        atomic_write_json(path, data)


@app.command("import-data")
def import_data(
    input: Path = typer.Option(..., help="Input JSON archive path."),
    overwrite: bool = typer.Option(False, help="Overwrite existing files, creating backups first."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Import a JSON archive created by export-data."""
    if not isinstance(overwrite, bool):
        overwrite = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    if not input.exists():
        console.print(f"[red]ERROR:[/red] Import archive not found: {input}")
        raise typer.Exit(code=1)

    try:
        archive = load_json(input)
    except json.JSONDecodeError as exc:
        console.print(f"[red]ERROR:[/red] Invalid JSON archive: {exc}")
        raise typer.Exit(code=3)

    if archive.get("schema_version") != 1:
        console.print("[red]ERROR:[/red] Unsupported import archive schema_version")
        raise typer.Exit(code=2)
    if not isinstance(archive.get("leave_years"), dict):
        console.print("[red]ERROR:[/red] Import archive missing leave_years mapping")
        raise typer.Exit(code=2)

    base = get_default_data_dir(data_dir)
    ensure_data_dir(base)

    try:
        config = archive.get("config")
        if config is not None:
            if not isinstance(config, dict):
                raise ValueError("config must be an object")
            _write_import_file(base / "config.json", config, overwrite=overwrite)

        for year, leave_year in archive.get("leave_years", {}).items():
            if not str(year).isdigit() or not isinstance(leave_year, dict):
                raise ValueError(f"Invalid leave year entry: {year}")
            _write_import_file(base / "leave_years" / f"{year}.json", leave_year, overwrite=overwrite)

        holiday_cache = archive.get("holiday_cache", {})
        if not isinstance(holiday_cache, dict):
            raise ValueError("holiday_cache must be an object")
        for name, cache in holiday_cache.items():
            if "/" in str(name) or "\\" in str(name) or not isinstance(cache, dict):
                raise ValueError(f"Invalid holiday cache entry: {name}")
            _write_import_file(base / "holiday_cache" / f"{name}.json", cache, overwrite=overwrite)
    except FileExistsError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    console.print(f"Imported fedleave data into {base}")


@app.command()
def correct(
    id: str | None = typer.Option(None, help="Transaction ID to correct (YYYYMMDD-NNN)."),
    hours: float = typer.Option(..., help="Corrected hours to record."),
    reason: str = typer.Option(..., help="Reason for correction."),
    date: str | None = typer.Option(None, help="Optional date for replacement transaction YYYY-MM-DD."),
    category: str | None = typer.Option(None, help="Optional category for replacement transaction."),
    direction: str | None = typer.Option(None, help="Optional direction for replacement transaction (earned/used/worked/adjusted)."),
    # human-friendly lookup: find transaction by date and type/category
    search_date: str | None = typer.Option(None, help="Find transaction by this transaction date YYYY-MM-DD."),
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
                # infer year from the provided transaction date
                target_year = int(search_date.split("-")[0])
            except Exception:
                console.print("[red]ERROR:[/red] Invalid search date; use YYYY-MM-DD")
                raise typer.Exit(code=2)

            try:
                ly = load_leave_year(target_year, data_dir)
            except FileNotFoundError:
                console.print(f"[red]ERROR:[/red] Leave year for {target_year} not found")
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

    # validate optional replacement date and sanitize reason before creating replacement
    if date:
        try:
            date = parse_iso_date(date).isoformat()
        except ValueError as exc:
            console.print(f"[red]ERROR:[/red] {exc}")
            raise typer.Exit(code=2)

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
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(show_transaction_ids, OptionInfo):
        show_transaction_ids = False

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    transactions = leave_year.get("transactions", [])
    if not transactions:
        console.print(f"No transactions found for {year}.")
        raise typer.Exit(code=0)

    for transaction in sorted(transactions, key=lambda item: item["id"]):
        transaction_id = f"{transaction['id']} " if show_transaction_ids else ""
        console.print(
            f"{transaction_id}{transaction['date']} {transaction['category']} {transaction['direction']} {transaction['hours']} {transaction['status']} {transaction['description']}"
        )


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


@app.command()
def rollover(
    from_year: int = typer.Option(..., help="Leave year to roll from."),
    to_year: int = typer.Option(..., help="Leave year to roll to."),
    preview: bool = typer.Option(False, help="Preview rollover without applying."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Preview or apply a leave year rollover.

    The basic implementation carries forward annual and sick balances and writes a new leave year JSON.
    """
    if not isinstance(preview, bool):
        preview = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    base = get_default_data_dir(data_dir)
    try:
        src = load_leave_year(from_year, base)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    balances = calculate_balances(src)
    annual_balance = balances.get("annual", 0.0)
    sick_balance = balances.get("sick", 0.0)

    # read carryover limit from config if present
    cfg_path = base / "config.json"
    carryover_limit = 240.0
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            carryover_limit = float(cfg.get("rules", {}).get("annual", {}).get("carryover_limit_hours", carryover_limit))
        except Exception:
            pass

    carry_forward = min(carryover_limit, annual_balance)
    forfeiture = max(0.0, annual_balance - carry_forward)
    result = {
        "action": "preview" if preview else "applied",
        "from_year": from_year,
        "to_year": to_year,
        "annual_balance": annual_balance,
        "carryover_limit": carryover_limit,
        "carry_forward": carry_forward,
        "forfeiture": forfeiture,
        "sick_balance": sick_balance,
        "created_file": None,
        "created_transaction_ids": [],
    }

    if json_output and preview:
        _print_json(result)
        return

    if not json_output:
        console.print(f"Rollover preview from {from_year} to {to_year}:")
        console.print(f"  annual_balance={annual_balance:.2f}")
        console.print(f"  carryover_limit={carryover_limit:.2f}")
        console.print(f"  carry_forward={carry_forward:.2f}")
        console.print(f"  forfeiture={forfeiture:.2f}")
        console.print(f"  sick_balance carried fully: {sick_balance:.2f}")

    if preview:
        return

    # Apply rollover: create the new leave year JSON and write starting balances
    # determine new leave_year_start by advancing the year in the source start
    src_start = src.get("leave_year_start")
    try:
        if src_start:
            src_date = _date.fromisoformat(src_start)
            new_start_date = src_date.replace(year=to_year)
            new_start = new_start_date.isoformat()
        else:
            new_start = _date(to_year, 1, 1).isoformat()
    except Exception:
        try:
            parts = src_start.split("-")
            new_start = f"{to_year}-{parts[1]}-{parts[2]}"
        except Exception:
            new_start = f"{to_year}-01-01"

    # ensure to_year as int
    to_year_int = int(to_year)

    try:
        ly_start_date = _date.fromisoformat(new_start)
        pay_periods = generate_pay_periods(ly_start_date, 26)
        ly_end = pay_periods[-1]["end_date"]
    except Exception:
        pay_periods = []
        ly_end = new_start

    new_ly = {
        "schema_version": 1,
        "leave_year": to_year_int,
        "leave_year_start": new_start,
        "leave_year_end": ly_end,
        "pay_period_count": len(pay_periods),
        "annual_leave_accrual_hours": src.get("annual_leave_accrual_hours", 6.0),
        "sick_leave_accrual_hours": src.get("sick_leave_accrual_hours", 4.0),
        "starting_balances": {
            "annual": carry_forward,
            "sick": sick_balance,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        "carryover_from_previous_year": {"annual": carry_forward},
        "transactions": [],
        "pay_periods": pay_periods,
        "holidays": [],
        "rollover_status": {"rolled_from_previous_year": True, "rolled_to_next_year": False, "rollover_completed_at": None},
    }

    # create starting-balance transactions
    existing_ids = []
    try:
        from .ledger import create_transaction as _create_tx
        if carry_forward and carry_forward > 0:
            tx = _create_tx(date=new_start, category="annual", direction="starting_balance", hours=carry_forward, existing_ids=existing_ids)
            new_ly["transactions"].append(tx.model_dump())
            existing_ids.append(tx.id)
            result["created_transaction_ids"].append(tx.id)
        if sick_balance and sick_balance > 0:
            tx2 = _create_tx(date=new_start, category="sick", direction="starting_balance", hours=sick_balance, existing_ids=existing_ids)
            new_ly["transactions"].append(tx2.model_dump())
            result["created_transaction_ids"].append(tx2.id)
    except Exception:
        pass

    # write new leave year file
    year_path = base / "leave_years" / f"{to_year_int}.json"
    try:
        write_json(year_path, new_ly)
        result["created_file"] = str(year_path)
        if json_output:
            _print_json(result)
        else:
            console.print(f"Created leave year file: {year_path}")
    except Exception as exc:
        console.print(f"[red]ERROR:[/red] Failed to write new leave year: {exc}")
        raise typer.Exit(code=4)


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


@app.command()
def holidays(
    action: str = typer.Option(..., help="Action: generate|list|import-ics"),
    year: int = typer.Option(..., help="Year for the holiday action."),
    file: str | None = typer.Option(None, help="Path to ICS file for import-ics."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Manage federal holiday data: generate, list, import-ics.

    - `generate`: generate using python-holidays and write cache.
    - `list`: print cached holidays.
    - `import-ics`: import an OPM ICS file (file path required).
    """
    base = get_default_data_dir(data_dir)
    cache_dir = base / "holiday_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"federal_holidays_{year}.json"

    if action == "generate":
        data = generate_federal_holidays(year, base)
        write_json(cache_file, data)
        console.print(f"Generated holidays for {year} -> {cache_file}")
        return

    if action == "list":
        if not cache_file.exists():
            console.print(f"No holiday cache for {year}. Run `fedleave holidays --action generate` first.")
            raise typer.Exit(code=1)
        data = json.loads(cache_file.read_text())
        for h in data.get("holidays", []):
            console.print(f"{h.get('display_date')} {h.get('name')} ({h.get('code')})")
        return

    if action == "import-ics":
        if not file:
            console.print("[red]ERROR:[/red] --file is required for import-ics")
            raise typer.Exit(code=2)
        # Full ICS import using icalendar
        try:
            from .holidays import import_ics
            # sanitize file path
            try:
                file_text = sanitize_text(file, field_name="file")
            except ValueError as exc:
                console.print(f"[red]ERROR:[/red] {exc}")
                raise typer.Exit(code=2)

            parsed = import_ics(Path(file_text))
            # set year if possible
            for h in parsed.get("holidays", []):
                if parsed.get("year") is None and h.get("actual_date"):
                    parsed["year"] = int(h.get("actual_date").split("-")[0])
            write_json(cache_file, parsed)
            console.print(f"Imported ICS to cache: {cache_file}")
            return
        except RuntimeError as exc:
            console.print(f"[red]ERROR:[/red] {exc}")
            raise typer.Exit(code=2)
        except Exception as exc:
            console.print(f"[red]ERROR:[/red] Failed to import ICS: {exc}")
            raise typer.Exit(code=2)

    console.print(f"Unknown holidays action: {action}")
    raise typer.Exit(code=2)


@app.command(name="validate")
def validate(
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    apply: bool = typer.Option(False, help="Apply automatic fixes where possible."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Validate leave year JSON files in the data directory.

    With `--apply` the command will write back normalized dates for transactions when safe.
    """
    from .storage import write_json
    if not isinstance(apply, bool):
        apply = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    base = get_default_data_dir(data_dir)
    year_dir = base / "leave_years"
    if not year_dir.exists():
        console.print(f"No leave_years directory found in {base}")
        raise typer.Exit(code=1)

    any_issues = False
    results = []
    for pj in sorted(year_dir.iterdir()):
        if pj.suffix != ".json":
            continue
        ly = load_leave_year(int(pj.stem), data_dir)
        issues = validate_leave_year(ly)
        if not issues:
            results.append({"file": pj.name, "year": int(pj.stem), "ok": True, "issues": [], "applied": False})
            if not json_output:
                console.print(f"{pj.name}: OK")
            continue

        any_issues = True
        result = {"file": pj.name, "year": int(pj.stem), "ok": False, "issues": issues, "applied": False}
        if not json_output:
            console.print(f"{pj.name}: {len(issues)} issues found")
            for iss in issues:
                console.print(f"  - {iss.get('path')}: {iss.get('message')}")
        # interactive prompt: apply suggested fixes for this file?
        should_apply = apply if json_output else apply or typer.confirm(f"Apply suggested fixes to {pj.name}?")
        if should_apply:
            fixed = apply_fixes_to_leave_year(ly, issues)
            try:
                write_json(pj, fixed)
                result["applied"] = True
                if not json_output:
                    console.print(f"  Applied fixes to {pj.name}")
            except Exception as exc:
                result["write_error"] = str(exc)
                if not json_output:
                    console.print(f"  Failed to write fixes: {exc}")
        results.append(result)

    if any_issues:
        if json_output:
            _print_json({"ok": False, "results": results})
        raise SystemExit(2)
    if json_output:
        _print_json({"ok": True, "results": results})
        return
    console.print("Validation completed: no issues found")


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
def balance(
    year: int = typer.Option(..., help="Leave year."),
    as_of: str | None = typer.Option(None, help="Compute balances through this date YYYY-MM-DD."),
    project: bool = typer.Option(False, help="Project future automatic annual and sick accrual to the projection date or year end."),
    project_to: str | None = typer.Option(None, help="Projection end date YYYY-MM-DD. Defaults to leave year end when --project is enabled."),
    use_or_lose: bool = typer.Option(False, help="Show projected annual carryover and use-or-lose amounts at year end."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(as_of, OptionInfo):
        as_of = None
    if not isinstance(project, bool):
        project = False
    if isinstance(project_to, OptionInfo):
        project_to = None
    if not isinstance(use_or_lose, bool):
        use_or_lose = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    accrual_through = as_of or _date.today().isoformat()
    try:
        added_accruals = ensure_automatic_accruals(leave_year, accrual_through)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)
    if added_accruals:
        write_json(get_leave_year_path(year, data_dir), leave_year)

    include_projected = project or use_or_lose
    balances = calculate_balances(
        leave_year,
        until_date=as_of,
        include_projected=include_projected,
        project_until=project_to,
    )
    projection_label = project_to or leave_year.get("leave_year_end") or "year end"
    use_or_lose_data = None
    if use_or_lose:
        try:
            cfg = load_config(data_dir)
        except FileNotFoundError:
            cfg = None
        use_or_lose_data = calculate_use_or_lose(leave_year, balances, cfg)

    if json_output:
        _print_json(
            {
                "year": year,
                "as_of": as_of,
                "projected": include_projected,
                "project_to": projection_label if include_projected else None,
                "balances": dict(sorted(balances.items())),
                "automatic_accruals_posted": added_accruals,
                "automatic_accruals_posted_through": accrual_through,
                "use_or_lose": use_or_lose_data,
            }
        )
        return

    if as_of:
        console.print(f"Balances for {year} as of {as_of}:")
    elif include_projected:
        console.print(f"Projected balances for {year} as of {projection_label}:")
    else:
        console.print(f"Balances for {year}:")

    for category, amount in sorted(balances.items()):
        console.print(f"  {category}: {amount:.2f}")

    if added_accruals:
        console.print(f"Posted {added_accruals} automatic annual/sick accrual transactions through {accrual_through}.")

    if use_or_lose:
        console.print("")
        console.print(f"Carryover limit: {use_or_lose_data['carryover_limit']:.2f}")
        console.print(f"Projected annual carryover: {use_or_lose_data['annual_carryover']:.2f}")
        console.print(f"Projected use-or-lose: {use_or_lose_data['use_or_lose']:.2f}")


@app.command(name="pay-period")
def pay_period_summary(
    year: int = typer.Option(..., help="Leave year."),
    date: str = typer.Option(..., help="Date inside the pay period YYYY-MM-DD."),
    daily: bool = typer.Option(False, help="Show activity for each day in the pay period."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if not isinstance(daily, bool):
        daily = False
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    try:
        pay_period = calculate_pay_period_activity(leave_year, date)["pay_period"]
        accrual_through = pay_period.get("accrual_date") or pay_period.get("end_date")
        added_accruals = ensure_automatic_accruals(leave_year, accrual_through)
        if added_accruals:
            write_json(get_leave_year_path(year, data_dir), leave_year)
        activity = calculate_pay_period_activity(leave_year, date)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    pay_period = activity["pay_period"]
    ending_balances = calculate_balances(leave_year, until_date=pay_period.get("end_date"))
    daily_activity_rows = []
    if daily or json_output:
        current = _date.fromisoformat(pay_period["start_date"])
        end = _date.fromisoformat(pay_period["end_date"])
        while current <= end:
            day = current.isoformat()
            day_activity = calculate_daily_activity(leave_year, day)
            daily_activity_rows.append({"date": day, **day_activity})
            current += _timedelta(days=1)

    if json_output:
        _print_json(
            {
                "year": year,
                "date": date,
                "pay_period": pay_period,
                "activity": activity,
                "daily_activity": daily_activity_rows if daily else None,
                "ending_balances": dict(sorted(ending_balances.items())),
                "automatic_accruals_posted": added_accruals,
                "automatic_accruals_posted_through": accrual_through,
            }
        )
        return

    console.print(
        f"Pay period {pay_period.get('pay_period_number')} "
        f"({pay_period.get('start_date')} to {pay_period.get('end_date')})"
    )
    if added_accruals:
        console.print(f"Posted {added_accruals} automatic annual/sick accrual transactions for this pay period.")

    if daily:
        console.print("")
        console.print("Daily activity:")
        for row in daily_activity_rows:
            day = row["date"]
            day_activity = {key: value for key, value in row.items() if key != "date"}
            day_categories = sorted({*day_activity["earned"], *day_activity["used"], *day_activity["net"]})
            if day_categories:
                console.print(f"  {day}:")
                for category in day_categories:
                    earned = day_activity["earned"].get(category, 0.0)
                    used = day_activity["used"].get(category, 0.0)
                    net = day_activity["net"].get(category, 0.0)
                    console.print(f"    {category}: earned={earned:.2f} used={used:.2f} net={net:.2f}")
            else:
                console.print(f"  {day}: no activity")

    categories = sorted({*activity["earned"], *activity["used"], *activity["worked"], *activity["net"]})
    if not categories:
        console.print("No leave or overtime activity recorded for this pay period.")
        return

    console.print("")
    console.print("Pay period totals:")
    for category in categories:
        earned = activity["earned"].get(category, 0.0)
        used = activity["used"].get(category, 0.0)
        worked = activity["worked"].get(category, 0.0)
        net = activity["net"].get(category, 0.0)
        if category == "overtime":
            console.print(f"  {category}: worked={worked:.2f} net={net:.2f}")
        else:
            console.print(f"  {category}: earned={earned:.2f} used={used:.2f} net={net:.2f}")

    console.print("")
    console.print(f"Balances at end of pay period {pay_period.get('pay_period_number')}:")
    for category, amount in sorted(ending_balances.items()):
        if amount:
            console.print(f"  {category}: {amount:.2f}")


@app.command(name="pay-periods")
def pay_periods_summary(
    year: int = typer.Option(..., help="Leave year."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    pay_periods = leave_year.get("pay_periods", [])
    if not pay_periods:
        console.print(f"No pay periods found for {year}.")
        raise typer.Exit(code=1)

    final_accrual_date = pay_periods[-1].get("accrual_date") or pay_periods[-1].get("end_date")
    try:
        added_accruals = ensure_automatic_accruals(leave_year, final_accrual_date)
        if added_accruals:
            write_json(get_leave_year_path(year, data_dir), leave_year)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    summaries = []
    if not json_output:
        console.print(f"Pay period summary for {year}:")
        if added_accruals:
            console.print(f"Posted {added_accruals} automatic annual/sick accrual transactions through {final_accrual_date}.")

    for pay_period in pay_periods:
        activity = calculate_pay_period_activity(leave_year, pay_period["start_date"])
        balances = calculate_balances(leave_year, until_date=pay_period["end_date"])
        summaries.append(
            {
                "pay_period": pay_period,
                "activity": activity,
                "ending_balances": dict(sorted(balances.items())),
            }
        )
        if json_output:
            continue
        console.print(
            f"Pay period {pay_period.get('pay_period_number')} "
            f"({pay_period.get('start_date')} to {pay_period.get('end_date')})"
        )
        categories = sorted({*activity["earned"], *activity["used"], *activity["worked"], *activity["net"]})
        if categories:
            for category in categories:
                earned = activity["earned"].get(category, 0.0)
                used = activity["used"].get(category, 0.0)
                worked = activity["worked"].get(category, 0.0)
                net = activity["net"].get(category, 0.0)
                if category == "overtime":
                    console.print(f"  {category}: worked={worked:.2f} net={net:.2f}")
                else:
                    console.print(f"  {category}: earned={earned:.2f} used={used:.2f} net={net:.2f}")
        else:
            console.print("  no activity")
        nonzero_balances = {category: amount for category, amount in sorted(balances.items()) if amount}
        balance_text = ", ".join(f"{category}={amount:.2f}" for category, amount in nonzero_balances.items())
        console.print(f"  ending balances: {balance_text or 'none'}")

    if json_output:
        _print_json(
            {
                "year": year,
                "pay_periods": summaries,
                "automatic_accruals_posted": added_accruals,
                "automatic_accruals_posted_through": final_accrual_date,
            }
        )
        return


@app.command(name="activity")
def daily_activity(
    year: int = typer.Option(..., help="Leave year."),
    date: str = typer.Option(..., help="Date to query YYYY-MM-DD."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    activity = calculate_daily_activity(leave_year, date)
    if not any(activity.values()):
        if json_output:
            _print_json({"year": year, "date": date, "activity": activity, "has_activity": False})
            return
        console.print(f"No leave activity recorded on {date} for {year}.")
        raise typer.Exit(code=0)

    if json_output:
        _print_json({"year": year, "date": date, "activity": activity, "has_activity": True})
        return

    console.print(f"Leave activity for {date} ({year}):")
    for category in sorted({*activity['earned'], *activity['used'], *activity['net']}):
        earned = activity['earned'].get(category, 0.0)
        used = activity['used'].get(category, 0.0)
        net = activity['net'].get(category, 0.0)
        console.print(f"  {category}: earned={earned:.2f} used={used:.2f} net={net:.2f}")

app.add_typer(starting_balance_app, name="starting-balance")

@app.command()
def help() -> None:
    typer.echo(app.get_help(ctx=None))

if __name__ == "__main__":
    app()
