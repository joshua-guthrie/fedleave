"""Present balances, pay-period activity, daily activity, and month views."""

from __future__ import annotations

import calendar as _calendar
from datetime import date as _date
from datetime import timedelta as _timedelta
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import get_leave_year_path, load_leave_year, parse_iso_date, resolve_leave_year_for_date
from ..config import get_default_data_dir, load_config
from ..ledger import (
    calculate_balances,
    calculate_daily_activity,
    calculate_pay_period_activity,
    calculate_use_or_lose,
    ensure_automatic_accruals,
)
from ..payperiods import normalize_pay_period, pay_period_pay_date
from ..storage import load_json, write_json
from ..transaction_effects import signed_balance_effect, transaction_is_effective

_DISPLAY_CATEGORY_LABELS = {
    "annual": "A",
    "sick": "S",
    "overtime": "OT",
    "comp": "Comp",
    "credit": "Cr",
    "travel_comp": "TC",
    "admin": "Admin",
    "lwop": "LWOP",
    "military": "Mil",
    "court": "Court",
    "religious_comp": "RC",
    "time_off_award": "TOA",
    "excused": "Exc",
    "holiday": "Hol",
    "flex": "Flex",
    "other": "Other",
    "restored_annual": "RA",
}


def _display_line(transaction: dict) -> str:
    label = _DISPLAY_CATEGORY_LABELS.get(transaction.get("category"), str(transaction.get("category", "")))
    signed_hours = signed_balance_effect(transaction)
    hours = abs(signed_hours)
    sign = "-" if signed_hours < 0 else "+"
    return f"{label} {sign}{hours:.1f}"


def _month_bounds(year: int, month: int) -> tuple[_date, _date, _date, _date]:
    if month < 1 or month > 12:
        raise ValueError("--month must be between 1 and 12.")

    month_start = _date(year, month, 1)
    month_end = _date(year, month, _calendar.monthrange(year, month)[1])
    calendar_start = month_start - _timedelta(days=(month_start.weekday() + 1) % 7)
    calendar_end = month_end + _timedelta(days=(5 - month_end.weekday()) % 7)
    return month_start, month_end, calendar_start, calendar_end


def _holiday_names_by_date(year: int, data_dir: Path | None) -> dict[str, str]:
    cache_file = get_default_data_dir(data_dir) / "holiday_cache" / f"federal_holidays_{year}.json"
    if not cache_file.exists():
        return {}
    try:
        cache = load_json(cache_file)
    except Exception:
        return {}
    names = {}
    for holiday in cache.get("holidays", []):
        display_date = holiday.get("display_date") or holiday.get("observed_date") or holiday.get("actual_date")
        name = holiday.get("name") or holiday.get("short_name")
        if display_date and name:
            names[str(display_date)] = str(name)
    return names


def _transactions_by_date(leave_year: dict, start: _date, end: _date) -> dict[str, list[dict]]:
    entries: dict[str, list[dict]] = {}
    for transaction in leave_year.get("transactions", []):
        if not transaction_is_effective(transaction):
            continue
        try:
            transaction_date = parse_iso_date(str(transaction.get("date", "")))
        except ValueError:
            continue
        if not start <= transaction_date <= end:
            continue
        day_entries = entries.setdefault(transaction_date.isoformat(), [])
        day_entries.append(
            {
                "id": transaction.get("id"),
                "category": transaction.get("category"),
                "direction": transaction.get("direction"),
                "hours": float(transaction.get("hours", 0.0)),
                "status": transaction.get("status"),
                "source": transaction.get("source"),
                "description": transaction.get("description", ""),
            }
        )

    for day_entries in entries.values():
        day_entries.sort(key=lambda entry: str(entry.get("id") or ""))
    return entries


def _pay_periods_for_range(
    leave_year: dict,
    range_start: _date,
    range_end: _date,
    month_start: _date,
    month_end: _date,
) -> list[dict]:
    rows = []
    for pay_period in leave_year.get("pay_periods", []):
        try:
            period_start = parse_iso_date(str(pay_period["start_date"]))
            period_end = parse_iso_date(str(pay_period["end_date"]))
        except (KeyError, ValueError):
            continue
        if period_end < range_start or period_start > range_end:
            continue
        activity = calculate_pay_period_activity(leave_year, period_start.isoformat())
        totals = {}
        categories = sorted({*activity["earned"], *activity["used"], *activity["worked"], *activity["net"]})
        for category in categories:
            totals[category] = {
                "earned": activity["earned"].get(category, 0.0),
                "used": activity["used"].get(category, 0.0),
                "worked": activity["worked"].get(category, 0.0),
                "net": activity["net"].get(category, 0.0),
            }
        rows.append(
            {
                "number": pay_period.get("pay_period_number"),
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
                "pay_date": pay_period_pay_date(pay_period),
                "touches_display_month": not (period_end < month_start or period_start > month_end),
                "totals": totals,
                "ending_balances": dict(
                    sorted(calculate_balances(leave_year, until_date=period_end.isoformat()).items())
                ),
            }
        )
    return rows


def _dates_from_pay_periods(pay_periods: list[dict], field: str) -> set[str]:
    return {str(period.get(field)) for period in pay_periods if period.get(field)}


def _is_leave_year_end_keyword(value: str | None) -> bool:
    return bool(value and value.strip().lower() == "leave-year-end")


def _resolve_balance_leave_year(
    year: int | None,
    as_of: str | None,
    data_dir: Path | None,
) -> tuple[int, dict]:
    if year is not None:
        return year, load_leave_year(year, data_dir)

    target = "today" if as_of is None or _is_leave_year_end_keyword(as_of) else as_of
    return resolve_leave_year_for_date(target, data_dir)


def _resolve_balance_date(value: str | None, leave_year: dict, *, default_today: bool) -> str | None:
    if value is None:
        return _date.today().isoformat() if default_today else None
    if _is_leave_year_end_keyword(value):
        leave_year_end = leave_year.get("leave_year_end")
        if not leave_year_end:
            raise ValueError("Leave year is missing leave_year_end.")
        return parse_iso_date(str(leave_year_end)).isoformat()
    return parse_iso_date(value).isoformat()


@app.command()
def balance(
    year: int | None = typer.Option(None, help="Leave year. Defaults to the leave year containing --as-of or today."),
    as_of: str | None = typer.Option(
        None, help="Compute balances through this date YYYY-MM-DD, today, or leave-year-end."
    ),
    project: bool = typer.Option(
        False, help="Deprecated compatibility flag; projection is enabled by --project-to or --use-or-lose."
    ),
    project_to: str | None = typer.Option(
        None,
        help="Projection end date YYYY-MM-DD, today, or leave-year-end. Defaults to leave year end when projection is enabled.",
    ),
    use_or_lose: bool = typer.Option(
        False, help="Show projected annual carryover and use-or-lose amounts at year end."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(year, OptionInfo):
        year = None
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
        year, leave_year = _resolve_balance_leave_year(year, as_of, data_dir)
        as_of = _resolve_balance_date(as_of, leave_year, default_today=True)
        project_to = _resolve_balance_date(project_to, leave_year, default_today=False)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    accrual_through = as_of
    try:
        added_accruals = ensure_automatic_accruals(leave_year, accrual_through)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)
    if added_accruals:
        write_json(get_leave_year_path(year, data_dir), leave_year)

    include_projected = project or use_or_lose or project_to is not None
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

    if include_projected:
        console.print(f"Projected balances for {year} as of {projection_label}:")
    else:
        console.print(f"Balances for {year} as of {as_of}:")

    for category, amount in sorted(balances.items()):
        console.print(f"  {category}: {amount:.2f}")

    if added_accruals:
        console.print(f"Posted {added_accruals} automatic annual/sick accrual transactions through {accrual_through}.")

    if use_or_lose:
        console.print("")
        console.print(f"Carryover limit: {use_or_lose_data['carryover_limit']:.2f}")
        console.print(f"Projected annual carryover: {use_or_lose_data['annual_carryover']:.2f}")
        console.print(f"Projected use-or-lose: {use_or_lose_data['use_or_lose']:.2f}")


@app.command(name="use-or-lose")
@app.command(name="use-or-loose")
def use_or_lose(
    year: int | None = typer.Option(None, help="Leave year. Defaults to the current leave year."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    balance(
        year=year,
        as_of="leave-year-end",
        use_or_lose=True,
        json_output=json_output,
        data_dir=data_dir,
    )


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
        activity_output = dict(activity)
        activity_output["pay_period"] = normalize_pay_period(activity["pay_period"])
        _print_json(
            {
                "year": year,
                "date": date,
                "pay_period": normalize_pay_period(pay_period),
                "activity": activity_output,
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
            console.print(
                f"Posted {added_accruals} automatic annual/sick accrual transactions through {final_accrual_date}."
            )

    for pay_period in pay_periods:
        activity = calculate_pay_period_activity(leave_year, pay_period["start_date"])
        activity_output = dict(activity)
        activity_output["pay_period"] = normalize_pay_period(activity["pay_period"])
        balances = calculate_balances(leave_year, until_date=pay_period["end_date"])
        summaries.append(
            {
                "pay_period": normalize_pay_period(pay_period),
                "activity": activity_output,
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


@app.command()
def month(
    year: int = typer.Option(..., help="Leave year."),
    month: int = typer.Option(..., help="Calendar month number, 1-12."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    try:
        month_start, month_end, calendar_start, calendar_end = _month_bounds(year, month)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    try:
        leave_year = load_leave_year(year, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)

    try:
        added_accruals = ensure_automatic_accruals(leave_year, calendar_end.isoformat())
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)
    if added_accruals:
        write_json(get_leave_year_path(year, data_dir), leave_year)

    holidays = _holiday_names_by_date(year, data_dir)
    transactions = _transactions_by_date(leave_year, calendar_start, calendar_end)
    pay_period_rows = _pay_periods_for_range(
        leave_year,
        calendar_start,
        calendar_end,
        month_start,
        month_end,
    )
    all_pay_dates = _dates_from_pay_periods(pay_period_rows, "pay_date")
    pay_dates = set()
    for pay_date in all_pay_dates:
        try:
            parsed_pay_date = parse_iso_date(pay_date)
        except ValueError:
            continue
        if calendar_start <= parsed_pay_date <= calendar_end:
            pay_dates.add(pay_date)
    pay_period_end_dates = _dates_from_pay_periods(pay_period_rows, "end")
    today = _date.today()

    days = []
    current = calendar_start
    while current <= calendar_end:
        date_key = current.isoformat()
        entries = transactions.get(date_key, [])
        days.append(
            {
                "date": date_key,
                "in_display_month": month_start <= current <= month_end,
                "holiday_name": holidays.get(date_key),
                "is_today": current == today,
                "is_payday": date_key in pay_dates,
                "is_pay_period_end": date_key in pay_period_end_dates,
                "entries": entries,
                "display_lines": [_display_line(entry) for entry in entries],
            }
        )
        current += _timedelta(days=1)

    today_balance = calculate_balances(leave_year, until_date=today.isoformat())
    projected_balances = calculate_balances(
        leave_year,
        until_date=today.isoformat(),
        include_projected=True,
        project_until=leave_year.get("leave_year_end"),
    )
    try:
        cfg = load_config(data_dir)
    except FileNotFoundError:
        cfg = None
    use_or_lose = calculate_use_or_lose(leave_year, projected_balances, cfg)

    result = {
        "year": year,
        "month": month,
        "today": today.isoformat(),
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "calendar_start": calendar_start.isoformat(),
        "calendar_end": calendar_end.isoformat(),
        "days": days,
        "pay_periods": pay_period_rows,
        "pay_dates": sorted(pay_dates),
        "pay_period_end_dates": sorted(pay_period_end_dates),
        "balance_as_of_today": {
            "as_of": today.isoformat(),
            "balances": dict(sorted(today_balance.items())),
        },
        "projected_balance": {
            "project_to": leave_year.get("leave_year_end"),
            "balances": dict(sorted(projected_balances.items())),
            "use_or_lose": use_or_lose,
        },
        "automatic_accruals_posted": added_accruals,
        "automatic_accruals_posted_through": calendar_end.isoformat(),
    }

    if json_output:
        _print_json(result)
        return

    console.print(f"Month view for {year}-{month:02d} ({calendar_start} to {calendar_end})")
    if added_accruals:
        console.print(f"Posted {added_accruals} automatic annual/sick accrual transactions through {calendar_end}.")
    for day in days:
        if (
            not day["in_display_month"]
            and not day["entries"]
            and not day["holiday_name"]
            and not day["is_payday"]
            and not day["is_pay_period_end"]
        ):
            continue
        details = list(day["display_lines"])
        if day["holiday_name"]:
            details.append(str(day["holiday_name"]))
        if day["is_payday"]:
            details.append("Pay day")
        if day["is_pay_period_end"]:
            details.append("Pay period end")
        if day["is_today"]:
            details.append("Today")
        console.print(f"  {day['date']}: {', '.join(details) if details else 'no activity'}")


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
    for category in sorted({*activity["earned"], *activity["used"], *activity["net"]}):
        earned = activity["earned"].get(category, 0.0)
        used = activity["used"].get(category, 0.0)
        net = activity["net"].get(category, 0.0)
        console.print(f"  {category}: earned={earned:.2f} used={used:.2f} net={net:.2f}")


@app.command(name="compare-leave-balances")
def compare_leave_balances(
    category: str = typer.Option(..., help="Leave category to compare across all available leave years."),
    as_of: str = typer.Option("today", "--as-of", help="Comparison date YYYY-MM-DD or today."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    if isinstance(category, OptionInfo):
        raise typer.Exit(code=2)
    if isinstance(as_of, OptionInfo):
        as_of = "today"
    if not isinstance(json_output, bool):
        json_output = False
    if isinstance(data_dir, OptionInfo):
        data_dir = None

    from ..charting import COMPARISON_CATEGORY_LABELS, comparison_chart_points

    if category not in COMPARISON_CATEGORY_LABELS:
        console.print(
            f"[red]ERROR:[/red] Invalid category: {category}. Valid categories: {', '.join(COMPARISON_CATEGORY_LABELS)}"
        )
        raise typer.Exit(code=2)

    try:
        points, max_value, resolved_as_of = comparison_chart_points(category, as_of, data_dir)
    except FileNotFoundError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        raise typer.Exit(code=2)

    title = COMPARISON_CATEGORY_LABELS[category]
    y_rounding = 50 if category in {"annual", "sick"} else 10
    y_max = int((float(max_value) + (49 if y_rounding == 50 else 9)) // y_rounding * y_rounding) if max_value else 10

    if json_output:
        _print_json(
            {
                "ok": True,
                "category": category,
                "title": title,
                "as_of": resolved_as_of,
                "y_axis": {"min": 0, "max": y_max},
                "point_count": len(points),
                "max_value_hours": float(max_value),
                "years": [point["year"] for point in points],
                "points": points,
            }
        )
        return

    console.print(f"{title} as of {resolved_as_of}:")
    for point in points:
        display_value = f"{float(point['value']):.2f}".rstrip("0").rstrip(".")
        console.print(f"  {point['year']}\t{display_value}")
