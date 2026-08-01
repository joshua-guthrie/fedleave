"""Generate, import, and display cached federal holidays."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..cli_app import app, console
from ..cli_helpers import sanitize_text
from ..config import get_default_data_dir
from ..holidays import generate_federal_holidays
from ..storage import write_json


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
            from ..holidays import import_ics

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
