from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fedleave.executable_search import is_executable, iter_executable_candidates


class BackendError(RuntimeError):
    pass


class BackendMissingError(BackendError):
    pass


@dataclass(frozen=True)
class BackendOptions:
    fedleave_path: str | None = None
    data_dir: str | None = None


def _find_companion_app(app_name: str, *, explicit: str | None = None, description: str) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if is_executable(path):
            return path
        raise BackendMissingError(f"{description} executable was not found.")

    searched: list[Path] = []
    for candidate in iter_executable_candidates(app_name):
        searched.append(candidate)
        if is_executable(candidate):
            return candidate

    path_hit = shutil.which(app_name)
    if path_hit:
        return Path(path_hit)

    details = "\n".join(f"  - {candidate}" for candidate in searched)
    raise BackendMissingError(
        f"{description} executable was not found.\n\n"
        f"Searched:\n{details}\n\n"
        "Set the backend path in Preferences or place the companion bundle next "
        "to this application."
    )


def find_fedleave(explicit: str | None = None) -> Path:
    return _find_companion_app("fedleave", explicit=explicit, description="fedleave backend")


def find_companion_app(app_name: str, explicit: str | None = None) -> Path:
    return _find_companion_app(app_name, explicit=explicit, description=app_name)


def find_month_report_graphic(explicit: str | None = None) -> Path:
    return _find_companion_app(
        "fedleaveMonthReportGraphic",
        explicit=explicit,
        description="fedleaveMonthReportGraphic",
    )


class FedleaveBackend:
    def __init__(self, options: BackendOptions | None = None) -> None:
        self.options = options or BackendOptions()

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        kwargs: dict[str, Any] = {"text": True, "capture_output": True, "check": False}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        return subprocess.run(command, **kwargs)

    def run_json(self, args: list[str]) -> dict[str, Any]:
        fedleave = find_fedleave(self.options.fedleave_path)
        command = [str(fedleave), *args]
        if self.options.data_dir:
            command.extend(["--data-dir", self.options.data_dir])
        result = self._run_command(command)
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
        result = self._run_command(command)
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

    def use_or_lose(self, year: int) -> dict[str, Any]:
        return self.run_json(["use-or-lose", "--year", str(year), "--json"])

    def load_month(self, year: int, month: int) -> dict[str, Any]:
        return self.run_json(["month", "--year", str(year), "--month", str(month), "--json"])

    def set_day(self, day: str, values: dict[str, float], comments: dict[str, str] | None = None) -> dict[str, Any]:
        args = ["set-day", "--date", day, "--authoritative", "--json"]
        for category, value in values.items():
            option = f"--{category.replace('_', '-')}"
            args.extend([option, _format_number(value)])
            if comments is not None:
                args.extend([f"{option}-comment", comments.get(category, "")])
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

    def run_chart_app(
        self,
        app_name: str,
        *,
        output_file: Path,
        year: int | None = None,
        resolution: int = 1920,
        data_dir: str | None = None,
    ) -> None:
        chart_app = find_companion_app(app_name)
        command = [
            str(chart_app),
            "--outputFile",
            str(output_file),
            "--resolution",
            str(resolution),
        ]
        if year is not None:
            command.extend(["--year", str(year)])
        if data_dir:
            command.extend(["--data-dir", data_dir])
        kwargs: dict[str, Any] = {"text": True, "capture_output": True, "check": False}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        result = subprocess.run(command, **kwargs)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or f"{app_name} command failed").strip()
            raise BackendError(message)


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
    kwargs: dict[str, Any] = {"text": True, "capture_output": True, "check": False}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    result = subprocess.run(command, **kwargs)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "fedleaveMonthReportGraphic command failed").strip()
        raise BackendError(message)


def _format_number(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")
