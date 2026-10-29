"""One cached, read-only CLI boundary shared by planning and historical views."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path


class ReadOnlySnapshotSource:
    def __init__(self, backend: Path, data_dir: str | None):
        self.backend, self.data_dir = backend, data_dir
        self._years = None
        self._inventory = None
        self._snapshots = {}

    def _run(self, args):
        command = [str(self.backend), *args, *(["--data-dir", self.data_dir] if self.data_dir else [])]
        kwargs = {"capture_output": True, "text": True, "check": False, "timeout": 30}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            result = subprocess.run(command, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("The selected backend did not respond within 30 seconds.") from exc
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "The selected backend failed.").strip())
        try:
            payload = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError("The selected backend returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("The selected backend returned an unsupported snapshot format.")
        return payload

    def inventory(self):
        if self._inventory is None:
            rows = self._run(["years", "--json"]).get("years")
            if not isinstance(rows, list):
                raise RuntimeError("The selected backend returned an invalid leave-year inventory.")
            self._inventory = deepcopy(rows)
        return deepcopy(self._inventory)

    def years(self):
        if self._years is None:
            self._years = sorted(
                {
                    row["leave_year"]
                    for row in self.inventory()
                    if isinstance(row, dict) and row.get("valid") is True and type(row.get("leave_year")) is int
                }
            )
        return list(self._years)

    def snapshot(self, year):
        if year not in self.years():
            raise RuntimeError(f"Leave year {year} is not initialized and readable in the selected data directory.")
        if year not in self._snapshots:
            snapshot = self._run(["snapshot", "--year", str(year), "--json"])
            if snapshot.get("leave_year") != year or not isinstance(snapshot.get("calculation_context"), dict):
                raise RuntimeError(
                    "The selected backend must support read-only snapshots with calculation context. "
                    "Update that backend; no alternate datastore was loaded."
                )
            snapshot["calculation_context"]["backend"] = str(self.backend)
            snapshot["planning_available_years"] = self.years()
            self._snapshots[year] = deepcopy(snapshot)
        return deepcopy(self._snapshots[year])

    def clear(self):
        self._years = None
        self._inventory = None
        self._snapshots.clear()
