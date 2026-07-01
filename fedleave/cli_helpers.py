from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from .config import get_default_data_dir
from .storage import load_json
from .validation import sanitize_text
def resolve_data_dir(data_dir: Path | None) -> Path:
    return get_default_data_dir(data_dir)


def get_leave_year_path(year: int, data_dir: Path | None) -> Path:
    base_dir = resolve_data_dir(data_dir)
    return base_dir / "leave_years" / f"{year}.json"


def load_leave_year(year: int, data_dir: Path | None = None) -> dict[str, Any]:
    path = get_leave_year_path(year, data_dir)
    if not path.exists():
        raise FileNotFoundError(f"Leave year file not found: {path}")
    return load_json(path)


def resolve_leave_year_for_date(transaction_date: str, data_dir: Path | None = None) -> tuple[int, dict[str, Any]]:
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


def normalize_iso_date(date_str: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str.strip())
    if not match:
        return date_str
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def parse_iso_date(date_str: str) -> date:
    normalized = normalize_iso_date(date_str)
    try:
        return date.fromisoformat(normalized)
    except Exception as exc:
        raise ValueError(
            f"Invalid date: {date_str}. Use YYYY-MM-DD, for example 2026-01-11."
        ) from exc


def sanitize_text(value: str, *, field_name: str = "value", max_length: int = 1024) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains null byte which is not allowed")
    if len(value) > max_length:
        raise ValueError(f"{field_name} too long (max {max_length} characters)")
    # strip trailing and leading whitespace
    return value.strip()
