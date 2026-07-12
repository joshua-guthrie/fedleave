from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BackendError(RuntimeError):
    pass


class BackendMissingError(BackendError):
    pass


@dataclass(frozen=True)
class BackendOptions:
    fedleave_path: str | None = None
    data_dir: str | None = None


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if sys.platform.startswith("win"):
        return path.suffix.lower() in {".exe", ".bat", ".cmd"}
    return os.access(path, os.X_OK)


def find_fedleave(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if _is_executable(path):
            return path
        raise BackendMissingError("fedleave backend executable was not found.")

    names = ("fedleave.exe", "fedleave.bat", "fedleave.cmd") if sys.platform.startswith("win") else ("fedleave",)
    candidate_dirs: list[Path] = []
    for raw in (Path(sys.argv[0]), Path(sys.executable)):
        path = raw if raw.is_absolute() else Path.cwd() / raw
        resolved = path.resolve()
        candidate_dirs.append(resolved if resolved.is_dir() else resolved.parent)
    here = Path(__file__).resolve().parents[1]
    candidate_dirs.extend([here, here / "dist", here.parent / "dist"])

    seen: set[Path] = set()
    for directory in candidate_dirs:
        if directory in seen:
            continue
        seen.add(directory)
        for name in names:
            candidate = directory / name
            if _is_executable(candidate):
                return candidate

    path_hit = shutil.which("fedleave")
    if path_hit:
        return Path(path_hit)
    raise BackendMissingError("fedleave backend executable was not found.")


def find_month_report_graphic(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if _is_executable(path):
            return path
        raise BackendMissingError("fedleaveMonthReportGraphic executable was not found.")

    names = (
        ("fedleaveMonthReportGraphic.exe", "fedleaveMonthReportGraphic.bat", "fedleaveMonthReportGraphic.cmd")
        if sys.platform.startswith("win")
        else ("fedleaveMonthReportGraphic",)
    )
    candidate_dirs: list[Path] = []
    for raw in (Path(sys.argv[0]), Path(sys.executable)):
        path = raw if raw.is_absolute() else Path.cwd() / raw
        resolved = path.resolve()
        candidate_dirs.append(resolved if resolved.is_dir() else resolved.parent)
    here = Path(__file__).resolve().parents[1]
    candidate_dirs.extend([here, here / "dist", here.parent / "dist"])

    seen: set[Path] = set()
    for directory in candidate_dirs:
        if directory in seen:
            continue
        seen.add(directory)
        for name in names:
            candidate = directory / name
            if _is_executable(candidate):
                return candidate

    path_hit = shutil.which("fedleaveMonthReportGraphic")
    if path_hit:
        return Path(path_hit)
    raise BackendMissingError("fedleaveMonthReportGraphic executable was not found.")


class FedleaveBackend:
    def __init__(self, options: BackendOptions | None = None) -> None:
        self.options = options or BackendOptions()

    def run_json(self, args: list[str]) -> dict[str, Any]:
        fedleave = find_fedleave(self.options.fedleave_path)
        command = [str(fedleave), *args]
        if self.options.data_dir:
            command.extend(["--data-dir", self.options.data_dir])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "fedleave command failed").strip()
            raise BackendError(message)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError("fedleave returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise BackendError("fedleave returned an unexpected JSON payload.")
        return payload

    def run_text(self, args: list[str], *, include_data_dir: bool = True) -> str:
        fedleave = find_fedleave(self.options.fedleave_path)
        command = [str(fedleave), *args]
        if include_data_dir and self.options.data_dir:
            command.extend(["--data-dir", self.options.data_dir])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "fedleave command failed").strip()
            raise BackendError(message)
        return result.stdout

    def executable_path(self) -> Path:
        return find_fedleave(self.options.fedleave_path)

    def version(self) -> str:
        version = self.run_text(["--version"], include_data_dir=False).strip()
        if not version:
            raise BackendError("fedleave backend returned an empty version response.")
        return version

    def load_month(self, year: int, month: int) -> dict[str, Any]:
        return self.run_json(["month", "--year", str(year), "--month", str(month), "--json"])

    def set_day(self, day: str, values: dict[str, float]) -> dict[str, Any]:
        args = ["set-day", "--date", day, "--authoritative", "--json"]
        for category, value in values.items():
            args.extend([f"--{category.replace('_', '-')}", _format_number(value)])
        return self.run_json(args)

    def init_year(
        self,
        *,
        year: int,
        leave_year_start: str,
        annual_accrual: float,
        annual_start: float,
        sick_start: float,
        credit_start: float,
        comp_start: float,
        travel_comp_start: float,
        restored_annual_start: float,
    ) -> str:
        return self.run_text(
            [
                "init",
                "--year",
                str(year),
                "--leave-year-start",
                leave_year_start,
                "--annual-accrual",
                _format_number(annual_accrual),
                "--annual-start",
                _format_number(annual_start),
                "--sick-start",
                _format_number(sick_start),
                "--credit-start",
                _format_number(credit_start),
                "--comp-start",
                _format_number(comp_start),
                "--travel-comp-start",
                _format_number(travel_comp_start),
                "--restored-annual-start",
                _format_number(restored_annual_start),
            ]
        )

    def validate(self) -> dict[str, Any]:
        return self.run_json(["validate", "--json"])


def run_month_report_graphic(
    *,
    output_file: Path,
    year: int,
    month: int,
    fedleave_path: str | None = None,
    data_dir: str | None = None,
    graphic_path: str | None = None,
) -> None:
    graphic = find_month_report_graphic(graphic_path)
    command = [
        str(graphic),
        "--year",
        str(year),
        "--month",
        str(month),
        "--outputFile",
        str(output_file),
        "--overwrite",
    ]
    if fedleave_path:
        command.extend(["--fedleave", fedleave_path])
    if data_dir:
        command.extend(["--data-dir", data_dir])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "fedleaveMonthReportGraphic command failed").strip()
        raise BackendError(message)


def _format_number(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")
