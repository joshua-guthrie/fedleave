from __future__ import annotations

import json
from datetime import date as _date
from datetime import datetime as _datetime
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import load_leave_year
from ..config import get_default_data_dir, load_config
from ..expirations import expiration_report
from ..ledger import calculate_balances, create_transaction
from ..payperiods import generate_pay_periods
from ..storage import write_json


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
    try:
        config = load_config(base)
    except FileNotFoundError:
        config = None
    expiration_data = expiration_report(src, config, as_of=_date.fromisoformat(str(src["leave_year_end"])))
    expiring_lots = [lot for lot in expiration_data["lots"] if float(lot["remaining_hours"]) > 0.000001]

    # read carryover limit from config if present
    cfg_path = base / "config.json"
    carryover_limit = 240.0
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            carryover_limit = float(
                cfg.get("rules", {}).get("annual", {}).get("carryover_limit_hours", carryover_limit)
            )
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
        "carried_expiring_lots": len(expiring_lots),
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
        console.print(f"  expiring leave lots carried individually: {len(expiring_lots)}")

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
        "rollover_status": {
            "rolled_from_previous_year": True,
            "rolled_to_next_year": False,
            "rollover_completed_at": None,
        },
    }
    for lot in expiring_lots:
        category = str(lot["category"])
        new_ly["carryover_from_previous_year"][category] = float(
            new_ly["carryover_from_previous_year"].get(category, 0.0)
        ) + float(lot["remaining_hours"])

    # create starting-balance transactions
    existing_ids = []
    if carry_forward and carry_forward > 0:
        tx = create_transaction(
            date=new_start,
            category="annual",
            direction="starting_balance",
            hours=carry_forward,
            existing_ids=existing_ids,
        )
        new_ly["transactions"].append(tx.model_dump())
        existing_ids.append(tx.id)
        result["created_transaction_ids"].append(tx.id)
    if sick_balance and sick_balance > 0:
        tx2 = create_transaction(
            date=new_start, category="sick", direction="starting_balance", hours=sick_balance, existing_ids=existing_ids
        )
        new_ly["transactions"].append(tx2.model_dump())
        existing_ids.append(tx2.id)
        result["created_transaction_ids"].append(tx2.id)
    source_by_id = {str(tx.get("id", "")): tx for tx in src.get("transactions", [])}
    for lot in expiring_lots:
        category = str(lot["category"])
        tx = create_transaction(
            date=new_start,
            category=category,
            direction="restored" if category == "restored_annual" else "earned",
            hours=float(lot["remaining_hours"]),
            description=f"Expiration lot carried from {lot['transaction_id']}",
            status="reconciled",
            source="expiration-rollover",
            existing_ids=existing_ids,
        )
        carried = tx.model_dump()
        carried["expiration_date"] = lot["expiration_date"]
        carried["expiration_pay_period"] = lot.get("expiration_pay_period")
        carried["original_earned_date"] = lot["earned_date"]
        carried["carried_from_transaction_id"] = lot["transaction_id"]
        new_ly["transactions"].append(carried)
        existing_ids.append(tx.id)
        result["created_transaction_ids"].append(tx.id)
        original = source_by_id.get(str(lot["transaction_id"]))
        if original is not None:
            original["rolled_over_to_transaction_id"] = tx.id
    source_status = src.setdefault("rollover_status", {})
    source_status["rolled_to_next_year"] = True
    source_status["rollover_completed_at"] = _datetime.now().isoformat()

    # write new leave year file
    year_path = base / "leave_years" / f"{to_year_int}.json"
    try:
        write_json(year_path, new_ly)
        write_json(base / "leave_years" / f"{from_year}.json", src)
        result["created_file"] = str(year_path)
        if json_output:
            _print_json(result)
        else:
            console.print(f"Created leave year file: {year_path}")
    except Exception as exc:
        console.print(f"[red]ERROR:[/red] Failed to write new leave year: {exc}")
        raise typer.Exit(code=4)
