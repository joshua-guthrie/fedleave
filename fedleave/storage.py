from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


LEGACY_TRANSACTION_AUDIT_FIELDS = {
    "void",
    "void_reason",
    "replaces_transaction_id",
    "correction_reason",
    "reconcile_history",
}


def ensure_data_dir(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "leave_years").mkdir(exist_ok=True)
    (data_dir / "holiday_cache").mkdir(exist_ok=True)
    (data_dir / "backups").mkdir(exist_ok=True)


def atomic_write_json(path: Path, data: dict, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"File already exists: {path}")

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = Path(f.name)
            json.dump(data, f, indent=2, sort_keys=False)
            f.write("\n")
        temp_path.replace(path)
    except Exception:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        raise


def backup_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    backup_dir = path.parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    counter = 0
    while True:
        suffix = f".{timestamp}" if counter == 0 else f".{timestamp}.{counter}"
        backup_path = backup_dir / f"{path.name}{suffix}.bak"
        if not backup_path.exists():
            break
        counter += 1
    shutil.copy2(path, backup_path)
    return backup_path


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def remove_legacy_transaction_history(data: dict) -> bool:
    """Remove superseded transactions and audit-only fields in place."""
    changed = data.pop("starting_balance_history", None) is not None
    transactions = data.get("transactions")
    if not isinstance(transactions, list):
        return changed

    retained = []
    for transaction in transactions:
        if not isinstance(transaction, dict):
            retained.append(transaction)
            continue
        if transaction.get("void") is True or transaction.get("direction") == "voided":
            changed = True
            continue
        for field in LEGACY_TRANSACTION_AUDIT_FIELDS:
            if field in transaction:
                del transaction[field]
                changed = True
        retained.append(transaction)

    if len(retained) != len(transactions):
        changed = True
    if changed:
        data["transactions"] = retained
    return changed


def write_json(path: Path, data: dict, backup: bool = True) -> None:
    if backup and path.exists():
        backup_file(path)
    atomic_write_json(path, data, overwrite=True)


def migrate_leave_year_files(data_dir: Path) -> int:
    """Normalize every leave-year file in a data store and return the change count."""
    year_dir = data_dir / "leave_years"
    if not year_dir.exists():
        return 0

    changed = 0
    for path in sorted(year_dir.glob("*.json")):
        data = load_json(path)
        if remove_legacy_transaction_history(data):
            write_json(path, data)
            changed += 1
    return changed
