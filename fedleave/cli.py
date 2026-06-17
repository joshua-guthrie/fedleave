from __future__ import annotations

from pathlib import Path
from typer.models import OptionInfo

import typer
from rich.console import Console

from .cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date, sanitize_text
from .ledger import add_transaction_to_leave_year, calculate_balances, calculate_daily_activity, create_transaction, normalize_direction, TRANSACTION_CATEGORIES, TRANSACTION_DIRECTIONS
from .storage import write_json
from .config import get_default_data_dir, load_config
from .holidays import generate_federal_holidays
from . import reports
import json
from .payperiods import generate_pay_periods
from datetime import date as _date, datetime as _datetime
import shutil
import tempfile

console = Console()

HELP_TEXT = """
fedleave — Federal leave and time tracker

Usage:
    fedleave COMMAND [OPTIONS]

Primary commands:
    init        Initialize data directory and create leave year JSON
    add         Add a transaction to a leave year
    list        List transactions for a leave year
    balance     Show balances calculated from the ledger
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

    fedleave add --year YEAR --date YYYY-MM-DD --category CATEGORY [--earned HOURS | --used HOURS | --worked HOURS | --adjusted HOURS] [--description TEXT] [--status STATUS] [--source SOURCE]
        Exactly one of `--earned`, `--used`, `--worked`, or `--adjusted` must be provided.
        Valid categories: annual, sick, overtime, comp, credit, travel_comp, admin, lwop, military, court, religious_comp, time_off_award, excused, holiday, flex, other, restored_annual

    Examples:
        fedleave add --year 2026 --date 2026-03-10 --category annual --used 4 --description "Medical appointment"
        fedleave add --year 2026 --date 2026-03-12 --category overtime --worked 3

    fedleave correct --id TRANSACTION_ID --hours HOURS --reason "TEXT" [--data-dir PATH]
        Perform an audit-safe correction: void the original transaction and create a replacement linked to it.
    Example:
        fedleave correct --id 20260310-001 --hours 3 --reason "Only used 3 hours"

    fedleave void --id TRANSACTION_ID --reason "TEXT" [--data-dir PATH]
        Mark a transaction as void while preserving its record.
    Example:
        fedleave void --id 20260310-002 --reason "Entered in error"

    fedleave rollover --from-year YEAR --to-year YEAR [--preview] [--data-dir PATH]
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
    fedleave reports generate --year 2026 --data-dir ./.data --output reports/fedleave_2026.odt

Notes on data directory:
    Default: ~/.local/share/fedleave
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
app.add_typer(reports.app, name="reports")

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
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
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

    add_transaction_to_leave_year(leave_year, transaction)
    write_json(get_leave_year_path(year, data_dir), leave_year)
    console.print(f"Added transaction [bold]{transaction.id}[/bold] to {year}")


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
    console.print(f"Corrected {id}: created replacement {replacement.id}")

@app.command(name="list")
def list_transactions(
    year: int = typer.Option(..., help="Leave year."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
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
        console.print(
            f"{transaction['id']} {transaction['date']} {transaction['category']} {transaction['direction']} {transaction['hours']} {transaction['status']} {transaction['description']}"
        )


@app.command()
def rollover(
    from_year: int = typer.Option(..., help="Leave year to roll from."),
    to_year: int = typer.Option(..., help="Leave year to roll to."),
    preview: bool = typer.Option(False, help="Preview rollover without applying."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Preview or apply a leave year rollover.

    The basic implementation carries forward annual and sick balances and writes a new leave year JSON.
    """
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
        if sick_balance and sick_balance > 0:
            tx2 = _create_tx(date=new_start, category="sick", direction="starting_balance", hours=sick_balance, existing_ids=existing_ids)
            new_ly["transactions"].append(tx2.model_dump())
    except Exception:
        pass

    # write new leave year file
    year_path = base / "leave_years" / f"{to_year_int}.json"
    try:
        write_json(year_path, new_ly)
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
def report(
    year: int = typer.Option(..., help="Leave year."),
    output: str = typer.Option("fedleave_report.odt", help="Output path (ODT or PDF)."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    chart: str | None = typer.Option(None, help="Path to existing chart PNG."),
    template: str | None = typer.Option(None, help="Path to ODT template."),
) -> None:
    """Generate a report. If `--output` ends with `.pdf`, attempt to produce a PDF (requires LibreOffice).

    The command checks for `odfpy` and LibreOffice and prints helpful install instructions when missing.
    """
    out_path = Path(output)
    is_pdf = out_path.suffix.lower() == ".pdf"

    # Ensure odfpy is installed
    try:
        import odf.opendocument  # noqa: F401
    except Exception:
        console.print("[red]ERROR:[/red] Missing Python dependency `odfpy`. Install with: `pip install odfpy`")
        raise typer.Exit(code=2)

    if is_pdf:
        # generate a temporary ODT then convert
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".odt", delete=False) as tf:
            tmp_odt = Path(tf.name)

        # generate ODT
        reports.generate(year=year, data_dir=data_dir, chart=chart, output=str(tmp_odt), template=template)

        # check for conversion
        pdf_candidate = tmp_odt.with_suffix(".pdf")
        if not pdf_candidate.exists():
            lo = shutil.which("libreoffice") or shutil.which("soffice")
            if not lo:
                console.print("[red]ERROR:[/red] LibreOffice not found. Install it to enable PDF conversion." )
                console.print("  Debian/Ubuntu: sudo apt-get install -y libreoffice-core libreoffice-writer")
                console.print("  macOS: brew install --cask libreoffice")
                console.print("  Windows: install LibreOffice from https://www.libreoffice.org/")
                raise typer.Exit(code=2)
            # attempt conversion using reports helper
            try:
                reports._convert_to_pdf(tmp_odt)
            except Exception as exc:
                console.print(f"[red]ERROR:[/red] PDF conversion failed: {exc}")
                raise typer.Exit(code=4)

        # move PDF to desired output
        final_pdf = tmp_odt.with_suffix(".pdf")
        try:
            shutil.move(str(final_pdf), str(out_path))
            console.print(f"Wrote PDF: {out_path}")
        finally:
            try:
                tmp_odt.unlink()
            except Exception:
                pass
    else:
        # output ODT
        reports.generate(year=year, data_dir=data_dir, chart=chart, output=str(out_path), template=template)

    # create new leave year file
    new_start_date = src.get("leave_year_end")
    # naive: set new start as day after end
    from datetime import datetime, timedelta
    try:
        end_date = datetime.fromisoformat(src.get("leave_year_end"))
        new_start = (end_date + timedelta(days=1)).date().isoformat()
    except Exception:
        new_start = f"{to_year}-01-11"

    new_leave_year = {
        "schema_version": 1,
        "leave_year": to_year,
        "leave_year_start": new_start,
        "leave_year_end": None,
        "pay_period_count": src.get("pay_period_count", 26),
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
        "carryover_from_previous_year": {
            "annual": carry_forward,
            "sick": sick_balance,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        "transactions": [],
        "pay_periods": [],
        "holidays": [],
        "rollover_status": {
            "rolled_from_previous_year": True,
            "rolled_to_next_year": False,
            "rollover_completed_at": None,
        }
    }

    # populate pay periods for the new year
    try:
        pp_start = _date.fromisoformat(new_start)
        new_leave_year["pay_periods"] = generate_pay_periods(pp_start, new_leave_year.get("pay_period_count", 26))
    except Exception:
        new_leave_year["pay_periods"] = []

    # create starting-balance transactions for audit trail
    existing_ids: list[str] = []
    # annual
    try:
        from .ledger import create_transaction, add_transaction_to_leave_year

        tx_annual = create_transaction(
            date=new_leave_year["leave_year_start"],
            category="annual",
            direction="starting_balance",
            hours=carry_forward,
            description=f"Carryover from {from_year}",
            status="reconciled",
            source="rollover",
            existing_ids=existing_ids,
        )
        add_transaction_to_leave_year(new_leave_year, tx_annual)
        existing_ids.append(tx_annual.id)

        tx_sick = create_transaction(
            date=new_leave_year["leave_year_start"],
            category="sick",
            direction="starting_balance",
            hours=sick_balance,
            description=f"Carryover from {from_year}",
            status="reconciled",
            source="rollover",
            existing_ids=existing_ids,
        )
        add_transaction_to_leave_year(new_leave_year, tx_sick)
        existing_ids.append(tx_sick.id)
    except Exception:
        pass

    # generate federal holidays for the new year and cache
    try:
        holidays_data = generate_federal_holidays(to_year, base)
        new_leave_year["holidays"] = holidays_data.get("holidays", []) if isinstance(holidays_data, dict) else []
    except Exception:
        new_leave_year["holidays"] = []

    # mark rollover completed timestamp
    new_leave_year.setdefault("rollover_status", {})["rollover_completed_at"] = _datetime.now().isoformat()

    target_path = base / "leave_years" / f"{to_year}.json"
    write_json(target_path, new_leave_year)
    console.print(f"Created new leave year file: {target_path}")


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
) -> None:
    """Validate leave year JSON files in the data directory.

    With `--apply` the command will write back normalized dates for transactions when safe.
    """
    from .storage import write_json
    base = get_default_data_dir(data_dir)
    year_dir = base / "leave_years"
    if not year_dir.exists():
        console.print(f"No leave_years directory found in {base}")
        raise typer.Exit(code=1)

    any_issues = False
    for pj in sorted(year_dir.iterdir()):
        if pj.suffix != ".json":
            continue
        ly = load_leave_year(int(pj.stem), data_dir)
        issues = validate_leave_year(ly)
        if not issues:
            console.print(f"{pj.name}: OK")
            continue

        any_issues = True
        console.print(f"{pj.name}: {len(issues)} issues found")
        for iss in issues:
            console.print(f"  - {iss.get('path')}: {iss.get('message')}")
        # interactive prompt: apply suggested fixes for this file?
        if apply or typer.confirm(f"Apply suggested fixes to {pj.name}?"):
            fixed = apply_fixes_to_leave_year(ly, issues)
            try:
                write_json(pj, fixed)
                console.print(f"  Applied fixes to {pj.name}")
            except Exception as exc:
                console.print(f"  Failed to write fixes: {exc}")

    if any_issues:
        raise typer.Exit(code=2)
    console.print("Validation completed: no issues found")


@app.command()
def void(
    id: str = typer.Option(..., help="Transaction ID to void (YYYYMMDD-NNN)."),
    reason: str = typer.Option("", help="Reason for voiding the transaction."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Void a transaction while preserving the audit trail."""
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
                    console.print(f"Voided transaction {id} in {pj.name}")
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
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    include_projected = project or use_or_lose
    balances = calculate_balances(
        leave_year,
        until_date=as_of,
        include_projected=include_projected,
        project_until=project_to,
    )

    if as_of:
        console.print(f"Balances for {year} as of {as_of}:")
    elif include_projected:
        projection_label = project_to or leave_year.get("leave_year_end") or "year end"
        console.print(f"Projected balances for {year} as of {projection_label}:")
    else:
        console.print(f"Balances for {year}:")

    for category, amount in sorted(balances.items()):
        console.print(f"  {category}: {amount:.2f}")

    if use_or_lose:
        try:
            cfg = load_config(data_dir)
        except FileNotFoundError:
            cfg = None

        use_or_lose_data = calculate_use_or_lose(leave_year, balances, cfg)
        console.print("")
        console.print(f"Carryover limit: {use_or_lose_data['carryover_limit']:.2f}")
        console.print(f"Projected annual carryover: {use_or_lose_data['annual_carryover']:.2f}")
        console.print(f"Projected use-or-lose: {use_or_lose_data['use_or_lose']:.2f}")

@app.command(name="activity")
def daily_activity(
    year: int = typer.Option(..., help="Leave year."),
    date: str = typer.Option(..., help="Date to query YYYY-MM-DD."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    activity = calculate_daily_activity(leave_year, date)
    if not any(activity.values()):
        console.print(f"No leave activity recorded on {date} for {year}.")
        raise typer.Exit(code=0)

    console.print(f"Leave activity for {date} ({year}):")
    for category in sorted({*activity['earned'], *activity['used'], *activity['net']}):
        earned = activity['earned'].get(category, 0.0)
        used = activity['used'].get(category, 0.0)
        net = activity['net'].get(category, 0.0)
        console.print(f"  {category}: earned={earned:.2f} used={used:.2f} net={net:.2f}")

@app.command()
def help() -> None:
    typer.echo(app.get_help(ctx=None))

if __name__ == "__main__":
    app()
