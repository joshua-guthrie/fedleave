from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import get_default_data_dir
from .storage import load_json


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
