from __future__ import annotations

import json
from datetime import datetime as _datetime
from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..cli_helpers import load_leave_year, parse_iso_date
from ..config import get_default_data_dir
from ..ledger import apply_fixes_to_leave_year, validate_leave_year
from ..storage import atomic_write_json, ensure_data_dir, load_json, write_json


@app.command()
def init(
    year: int = typer.Option(..., help="Leave year."),
    leave_year_start: str = typer.Option(..., help="Leave year start date YYYY-MM-DD or today."),
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
    from ..config import init_config
    # validate leave_year_start early to avoid creating bad state
    try:
        leave_year_start = parse_iso_date(leave_year_start).isoformat()
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


def _is_single_leave_year_backup(data: dict) -> bool:
    return (
        isinstance(data.get("leave_year"), int)
        and isinstance(data.get("transactions"), list)
        and isinstance(data.get("pay_periods"), list)
    )


def _normalize_import_archive(data: dict) -> tuple[dict, str]:
    if isinstance(data.get("leave_years"), dict):
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported import archive schema_version")
        return data, "archive"

    if _is_single_leave_year_backup(data):
        year = str(data["leave_year"])
        return {
            "schema_version": 1,
            "config": None,
            "leave_years": {year: data},
            "holiday_cache": {},
        }, "single leave-year backup"

    if data.get("schema_version") != 1:
        raise ValueError("Unsupported import archive schema_version")
    raise ValueError("Import archive missing leave_years mapping")


@app.command("import-data")
def import_data(
    input: Path = typer.Option(..., help="Input JSON archive path."),
    overwrite: bool = typer.Option(False, help="Overwrite existing files, creating backups first."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
) -> None:
    """Import a JSON archive created by export-data or a single leave-year backup."""
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

    try:
        archive, import_kind = _normalize_import_archive(archive)
    except ValueError as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
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

    console.print(f"Imported fedleave {import_kind} into {base}")

@app.command(name="validate")
def validate(
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    apply: bool = typer.Option(False, help="Apply automatic fixes where possible."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Validate leave year JSON files in the data directory.

    With `--apply` the command will write back normalized dates for transactions when safe.
    """
    from ..storage import write_json
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
