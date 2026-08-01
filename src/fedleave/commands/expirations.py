"""Report expiring leave lots and record approved expiration extensions."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date
from ..config import get_default_data_dir, load_config
from ..expirations import EXPIRING_CATEGORIES, expiration_report, expiration_rules, synchronize_expirations
from ..storage import load_json, write_json


def _config(data_dir: Path | None) -> dict | None:
    try:
        return load_config(data_dir)
    except FileNotFoundError:
        return None


@app.command("expirations")
def expirations(
    year: int | None = typer.Option(None, help="Leave year; defaults to the year containing today."),
    within_pay_periods: int | None = typer.Option(
        None, help="Only include lots expiring within this many pay periods."
    ),
    category: str | None = typer.Option(None, help="Only include one expiring leave category."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(year, OptionInfo):
        year = None
    if isinstance(within_pay_periods, OptionInfo):
        within_pay_periods = None
    if isinstance(category, OptionInfo):
        category = None
    if isinstance(data_dir, OptionInfo):
        data_dir = None
    if not isinstance(json_output, bool):
        json_output = False
    if category and category not in EXPIRING_CATEGORIES:
        console.print(f"[red]ERROR:[/red] Expiration tracking is supported only for {', '.join(EXPIRING_CATEGORIES)}.")
        raise typer.Exit(code=2)
    if within_pay_periods is not None and within_pay_periods < 0:
        console.print("[red]ERROR:[/red] --within-pay-periods must be zero or positive.")
        raise typer.Exit(code=2)
    try:
        if year is None:
            base = get_default_data_dir(data_dir) / "leave_years"
            candidates = sorted(base.glob("*.json"))
            today = date.today()
            selected = None
            for path in candidates:
                payload = load_json(path)
                if (
                    parse_iso_date(str(payload.get("leave_year_start", "")))
                    <= today
                    <= parse_iso_date(str(payload.get("leave_year_end", "")))
                ):
                    selected = int(payload.get("leave_year", path.stem))
                    break
            if selected is None:
                raise FileNotFoundError("No leave year contains today.")
            year = selected
        leave_year = load_leave_year(year, data_dir)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    report = expiration_report(leave_year, _config(data_dir))
    if report.pop("changed", False):
        write_json(get_leave_year_path(year, data_dir), leave_year)
    rows = report["lots"]
    if category:
        rows = [row for row in rows if row["category"] == category]
    if within_pay_periods is not None:
        rows = [row for row in rows if row["pay_periods_remaining"] <= within_pay_periods]
    report["lots"] = rows
    report["filters"] = {"category": category, "within_pay_periods": within_pay_periods}
    if json_output:
        _print_json(report)
        return
    console.print(f"Expiration status as of {report['as_of']}")
    if report["earliest_expiration_date"]:
        console.print(f"Earliest expiration: {report['earliest_expiration_date']}")
    for threshold, hours in report["hours_expiring_within_pay_periods"].items():
        console.print(f"Within {threshold} pay period(s): {hours:.2f} hours")
    for row in rows:
        console.print(
            f"{row['transaction_id']}  {row['category']}  {row['remaining_hours']:.2f} hours  "
            f"expires {row['expiration_date']} (PP {row.get('expiration_pay_period') or '?'} of "
            f"{row.get('expiration_pay_period_year')}; {row['pay_periods_remaining']} PP; "
            f"{row['hours_per_pay_period_to_use']:.2f} hours/PP)"
        )


@app.command("expiration-extend")
def expiration_extend(
    id: str = typer.Option(..., "--id", help="Earned transaction ID."),
    new_date: str = typer.Option(..., help="New expiration date YYYY-MM-DD."),
    reason: str = typer.Option(..., help="Reason for the extension."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(data_dir, OptionInfo):
        data_dir = None
    if not isinstance(json_output, bool):
        json_output = False
    try:
        extended_date = parse_iso_date(new_date)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)
    if not reason.strip():
        console.print("[red]ERROR:[/red] --reason is required.")
        raise typer.Exit(code=2)

    base = get_default_data_dir(data_dir)
    found = None
    found_path = None
    leave_year = None
    config = _config(data_dir)
    for path in sorted((base / "leave_years").glob("*.json")):
        payload = load_json(path)
        changed = synchronize_expirations(payload, config)["changed"]
        if changed:
            write_json(path, payload)
        for transaction in payload.get("transactions", []):
            if str(transaction.get("id")) == id and not transaction.get("void"):
                found, found_path, leave_year = transaction, path, payload
                break
        if found:
            break
    if not found or found_path is None or leave_year is None:
        console.print(f"[red]ERROR:[/red] Transaction not found: {id}")
        raise typer.Exit(code=1)
    category = str(found.get("category", ""))
    rule = expiration_rules(config).get(category, {})
    if found.get("direction") not in {"earned", "restored"} or not rule.get("expires"):
        console.print(f"[red]ERROR:[/red] {id} is not an earned lot in an expiring category.")
        raise typer.Exit(code=2)
    if not rule.get("allow_extension"):
        console.print(f"[red]ERROR:[/red] Extensions are disabled for {category}.")
        raise typer.Exit(code=2)
    current = parse_iso_date(str(found.get("expiration_date") or found.get("date")))
    if extended_date <= current:
        console.print("[red]ERROR:[/red] --new-date must be later than the current expiration date.")
        raise typer.Exit(code=2)
    found["expiration_date"] = extended_date.isoformat()
    found["expiration_pay_period"] = None
    found["expiration_extension_reason"] = reason.strip()
    found["expiration_extended_at"] = datetime.now().isoformat()
    write_json(found_path, leave_year)
    result = {
        "action": "expiration_extended",
        "transaction_id": id,
        "category": category,
        "previous_expiration_date": current.isoformat(),
        "new_expiration_date": extended_date.isoformat(),
        "reason": reason.strip(),
    }
    if json_output:
        _print_json(result)
    else:
        console.print(f"Extended {id} from {current.isoformat()} to {extended_date.isoformat()}.")
