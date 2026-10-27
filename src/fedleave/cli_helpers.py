"""Share data-directory, leave-year loading, and date parsing across commands."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from .config import get_default_data_dir, load_config
from .expirations import synchronize_expirations
from .storage import load_json, remove_legacy_transaction_history
from .validation import sanitize_text as sanitize_text


def resolve_data_dir(data_dir: Path | None) -> Path:
    """Resolve a command's optional data-directory override."""
    return get_default_data_dir(data_dir)


def get_leave_year_path(year: int, data_dir: Path | None) -> Path:
    """Return the conventional JSON path for a numbered leave year."""
    base_dir = resolve_data_dir(data_dir)
    return base_dir / "leave_years" / f"{year}.json"


def load_leave_year(year: int, data_dir: Path | None = None) -> dict[str, Any]:
    """Load and normalize a private copy. Only explicit mutations persist it."""
    path = get_leave_year_path(year, data_dir)
    if not path.exists():
        raise FileNotFoundError(f"Leave year file not found: {path}")
    leave_year = load_json(path)
    remove_legacy_transaction_history(leave_year)
    try:
        config = load_config(data_dir)
    except FileNotFoundError:
        config = None
    synchronize_expirations(leave_year, config)
    return leave_year


def load_read_snapshot(year: int, data_dir: Path | None = None) -> dict[str, Any]:
    """Canonical linked read model used by CLI reports and their consumers."""
    from .cross_year import resolve_snapshot

    return resolve_snapshot(resolve_data_dir(data_dir), year)


def read_snapshot_payload(year: int, data_dir: Path | None = None) -> dict[str, Any]:
    """Publish one read-only snapshot and its calculation context to companions.

    Cache reads never refresh the network, create directories, or persist the
    normalized ledger. Missing context is data, not permission to initialize it.
    """
    from .cross_year import seed_accruals

    snapshot = load_read_snapshot(year, data_dir)
    original_ids = {str(row.get("id")) for row in snapshot.get("transactions", [])}
    seed_accruals(snapshot)
    result = dict(snapshot)
    config = deepcopy(snapshot.config)
    warnings = []
    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("Configured defaults must be an object")
    schedule_fields = ("workday_start", "workday_end", "lunch_start", "lunch_end", "normal_workdays")
    if not all(key in defaults for key in schedule_fields):
        warnings.append(
            {
                "code": "MISSING_SCHEDULE_CONTEXT",
                "message": "Configured work tour is incomplete; working-hour capacity may be N/A.",
            }
        )
    if "time_increment_hours" not in defaults:
        warnings.append(
            {
                "code": "DEFAULT_TIME_INCREMENT",
                "message": "No configured time increment; the canonical 0.25-hour entry default is assumed.",
            }
        )
    base = resolve_data_dir(data_dir)
    start = date.fromisoformat(snapshot["leave_year_start"])
    end = date.fromisoformat(snapshot["leave_year_end"])
    holiday_settings = config.get("holidays", {})
    if not isinstance(holiday_settings, dict):
        raise ValueError("Configured holidays must be an object")
    enabled = holiday_settings.get("enabled", True)
    holiday_rows = deepcopy(snapshot.get("holidays", []))
    if not isinstance(holiday_rows, list) or any(not isinstance(row, dict) for row in holiday_rows):
        warnings.append(
            {
                "code": "INVALID_HOLIDAY_CONTEXT",
                "message": "Embedded holiday records are malformed; valid cached coverage is needed for working-hour capacity.",
            }
        )
        holiday_rows = []
    coverage = set()
    for calendar_year in range(start.year, end.year + 1):
        cache = (
            base / str(holiday_settings.get("cache_dir", "holiday_cache")) / f"federal_holidays_{calendar_year}.json"
        )
        if not enabled:
            coverage.add(calendar_year)
            continue
        if cache.exists():
            try:
                cached = load_json(cache)
                rows = cached["holidays"]
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Holiday records must be a list of objects")
                for row in rows:
                    day = row.get("observed_date") or row.get("date") or row.get("display_date")
                    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                        raise ValueError("Cached holidays need valid ISO observed dates")
                holiday_rows.extend(deepcopy(rows))
                coverage.add(calendar_year)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(
                    {
                        "code": "INVALID_HOLIDAY_CACHE",
                        "message": f"Cached holidays for {calendar_year} could not be read: {exc}",
                    }
                )
        if calendar_year not in coverage:
            warnings.append(
                {
                    "code": "MISSING_HOLIDAY_CONTEXT",
                    "message": f"No cached holiday coverage for calendar year {calendar_year}; working-hour capacity is N/A for those dates.",
                }
            )
    # Prefer observed dates; duplicate actual/display entries do not create
    # extra nonworking days or change capacity arithmetic.
    unique = {str(row.get("observed_date") or row.get("date") or row.get("display_date")): row for row in holiday_rows}
    result["snapshot_rules"] = config
    result["accounting_warnings"] = deepcopy(snapshot.warnings)
    result["entitlement_history"] = deepcopy(snapshot.entitlement_history)
    result["calculation_context"] = {
        "schema_version": 1,
        "synthetic_accrual_ids": sorted(
            str(row["id"])
            for row in snapshot["transactions"]
            if str(row["id"]) not in original_ids and row.get("source") == "auto_accrual"
        ),
        "data_store": str(base.resolve()),
        "work_schedule": {key: deepcopy(defaults.get(key)) for key in schedule_fields},
        "time_increment_hours": defaults.get("time_increment_hours", 0.25),
        "holidays_enabled": enabled,
        "holiday_coverage": sorted(coverage),
        "holidays": [unique[key] for key in sorted(unique)],
        "warnings": warnings,
    }
    return result


def resolve_leave_year_for_date(transaction_date: str, data_dir: Path | None = None) -> tuple[int, dict[str, Any]]:
    """Find and load the leave year whose inclusive bounds contain a date."""
    base = get_default_data_dir(data_dir)
    year_dir = base / "leave_years"
    if not year_dir.exists():
        raise FileNotFoundError(f"Leave year directory not found: {year_dir}")

    target = parse_iso_date(transaction_date)
    for path in sorted(year_dir.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            continue
        leave_year = load_json(path)
        remove_legacy_transaction_history(leave_year)
        try:
            config = load_config(data_dir)
        except FileNotFoundError:
            config = None
        try:
            start = parse_iso_date(str(leave_year.get("leave_year_start", "")))
            end = parse_iso_date(str(leave_year.get("leave_year_end", "")))
        except ValueError:
            continue
        if start <= target <= end:
            synchronize_expirations(leave_year, config)
            return int(leave_year.get("leave_year", path.stem)), leave_year

    raise FileNotFoundError(f"No leave year contains date {transaction_date}")


def normalize_iso_date(date_str: str) -> str:
    """Zero-pad a structurally valid year-month-day string."""
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str.strip())
    if not match:
        return date_str
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def parse_iso_date(date_str: str) -> date:
    """Parse an ISO date or the user-facing ``today`` keyword."""
    if date_str.strip().lower() == "today":
        return date.today()

    normalized = normalize_iso_date(date_str)
    try:
        return date.fromisoformat(normalized)
    except Exception as exc:
        raise ValueError(f"Invalid date: {date_str}. Use YYYY-MM-DD, for example 2026-01-11, or today.") from exc
