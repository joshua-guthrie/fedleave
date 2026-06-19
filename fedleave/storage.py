from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


def ensure_data_dir(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "leave_years").mkdir(exist_ok=True)
    (data_dir / "holiday_cache").mkdir(exist_ok=True)
    (data_dir / "backups").mkdir(exist_ok=True)


def atomic_write_json(path: Path, data: dict, overwrite: bool = True) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    if path.exists() and not overwrite:
        raise FileExistsError(f"File already exists: {path}")
    temp_path.replace(path)


def backup_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    backup_dir = path.parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = backup_dir / f"{path.name}.{timestamp}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict, backup: bool = True) -> None:
    if backup and path.exists():
        backup_file(path)
    atomic_write_json(path, data, overwrite=True)
