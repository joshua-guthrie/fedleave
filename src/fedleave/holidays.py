from __future__ import annotations

from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request

import holidays
try:
    from icalendar import Calendar
except Exception:
    Calendar = None

DEFAULT_OPM_ICS_URL = "https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/holidays.ics"


def _parse_ics(ics_bytes: bytes) -> dict[str, object]:
    if Calendar is None:
        raise RuntimeError("icalendar not available; install with `pip install icalendar`")

    cal = Calendar.from_ical(ics_bytes)
    entries: list[dict[str, object]] = []
    years: set[int] = set()
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        summary = component.get("SUMMARY")
        description = component.get("DESCRIPTION")
        dt = component.get("DTSTART").dt
        if isinstance(dt, datetime):
            observed_date = dt.date().isoformat()
        else:
            observed_date = dt.isoformat()
        years.add(int(observed_date.split("-")[0]))

        entries.append(
            {
                "name": str(summary) if summary is not None else "",
                "description": str(description) if description is not None else None,
                "actual_date": observed_date,
                "observed_date": observed_date,
                "display_date": observed_date,
                "code": "H",
                "short_name": None,
                "source": "opm_ics",
                "manual_override": False,
            }
        )

    year = years.pop() if len(years) == 1 else None
    return {
        "schema_version": 1,
        "year": year,
        "source": "opm_ics",
        "generated_at": datetime.now().isoformat(),
        "holidays": entries,
    }


def download_ics(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download ICS from {url}: {exc}") from exc


def generate_opm_holidays(year: int, ics_url: str = DEFAULT_OPM_ICS_URL) -> dict[str, object]:
    data = _parse_ics(download_ics(ics_url))
    events = [h for h in data["holidays"] if h["observed_date"].startswith(f"{year}-")]
    if not events:
        raise RuntimeError(f"No holidays found for {year} in OPM ICS feed")
    return {
        "schema_version": 1,
        "year": year,
        "source": "opm_ics",
        "generated_at": datetime.now().isoformat(),
        "holidays": events,
    }


def generate_federal_holidays(
    year: int,
    data_dir: Path,
    source: str = "python_holidays",
    ics_url: str = DEFAULT_OPM_ICS_URL,
) -> dict[str, object]:
    if source == "python_holidays":
        us_holidays = holidays.US(years=[year])
        entries = []
        for dt, name in sorted(us_holidays.items()):
            actual_date = dt.isoformat()
            observed_date = actual_date
            entries.append(
                {
                    "name": name,
                    "actual_date": actual_date,
                    "observed_date": observed_date,
                    "display_date": observed_date,
                    "code": "H",
                    "short_name": None,
                    "source": "python_holidays",
                    "manual_override": False,
                }
            )
        return {
            "schema_version": 1,
            "year": year,
            "source": "python_holidays",
            "generated_at": datetime.now().isoformat(),
            "holidays": entries,
        }

    if source == "opm_ics":
        return generate_opm_holidays(year, ics_url)

    raise ValueError(f"Unsupported holiday source: {source}")


def import_ics(file_path: Path) -> dict[str, object]:
    """Import an OPM ICS file and return holiday entries in the cache format.

    Requires `icalendar` package.
    """
    if Calendar is None:
        raise RuntimeError("icalendar not available; install with `pip install icalendar`")

    with open(file_path, "rb") as fh:
        return _parse_ics(fh.read())
