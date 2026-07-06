from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date
from ..config import load_config
from ..ledger import (
    calculate_balances,
    calculate_daily_activity,
    calculate_pay_period_activity,
    calculate_use_or_lose,
    ensure_automatic_accruals,
)
from ..storage import write_json


@app.command()
def balance(
    year: int = typer.Option(..., help="Leave year."),
    as_of: str | None = typer.Option(None, help="Compute balances through this date YYYY-MM-DD or today."),
    project: bool = typer.Option(False, help="Project future automatic annual and sick accrual to the projection date or year end."),
    project_to: str | None = typer.Option(None, help="Projection end date YYYY-MM-DD or today. Defaults to leave year end when --project is enabled."),
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

    try:
        if as_of:
            as_of = parse_iso_date(as_of).isoformat()
        if project_to:
            project_to = parse_iso_date(project_to).isoformat()
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

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
    date: str = typer.Option(..., help="Date inside the pay period YYYY-MM-DD or today."),
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
        date = parse_iso_date(date).isoformat()
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
    date: str = typer.Option(..., help="Date to query YYYY-MM-DD or today."),
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

    try:
        date = parse_iso_date(date).isoformat()
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

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
