import json
import sys
from pathlib import Path
import types

import pytest

import fedleave.executable_search as executable_search
import fedleave_gui.backend as backend_module
from fedleave_gui.backend import BackendOptions, FedleaveBackend


def _fake_fedleave(path: Path) -> Path:
    script = path.with_suffix(".py") if sys.platform.startswith("win") else path
    script.write_text(
        """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:1] == ["month"]:
    print(json.dumps({"year": int(args[args.index("--year") + 1]), "month": int(args[args.index("--month") + 1]), "days": []}))
elif args[:1] == ["set-day"]:
    print(json.dumps({"action": "set-day", "args": args}))
elif args[:1] == ["validate"]:
    print(json.dumps({"ok": True}))
elif args[:1] == ["use-or-lose"]:
    print(
        json.dumps(
            {
                "year": int(args[args.index("--year") + 1]),
                "as_of": "2027-01-09",
                "projected": True,
                "project_to": "2027-01-09",
                "balances": {"annual": 166.0},
                "use_or_lose": {
                    "carryover_limit": 240.0,
                    "annual_carryover": 166.0,
                    "use_or_lose": 0.0,
                },
            }
        )
    )
elif args[:1] == ["--version"]:
    print("fedleave 0.2.0")
else:
    print("ok")
""",
        encoding="utf-8",
    )
    if sys.platform.startswith("win"):
        wrapper = path.with_suffix(".cmd")
        wrapper.write_text(f'@python "{script}" %*\n', encoding="utf-8")
        return wrapper

    script.chmod(0o755)
    return script


def _bundle_executable(bundle_root: Path, app_name: str) -> Path:
    bundle_root.mkdir(parents=True, exist_ok=True)
    executable = bundle_root / (f"{app_name}.exe" if sys.platform.startswith("win") else app_name)
    executable.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_gui_backend_uses_fedleave_binary_for_month_and_set_day(tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend = FedleaveBackend(BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data")))

    month = backend.load_month(2026, 7)
    assert month["year"] == 2026
    assert month["month"] == 7

    projection = backend.use_or_lose(2026)
    assert projection["year"] == 2026
    assert projection["use_or_lose"]["use_or_lose"] == 0.0

    result = backend.set_day(
        "2026-07-08",
        {"annual": -5.0, "credit": 2.0},
        comments={"annual": "Leave", "credit": "Late"},
    )
    args = result["args"]
    assert args[:4] == ["set-day", "--date", "2026-07-08", "--authoritative"]
    assert "--json" in args
    assert "--annual" in args
    assert "-5" in args
    assert "--annual-comment" in args
    assert "Leave" in args
    assert "--credit" in args
    assert "2" in args
    assert "--credit-comment" in args
    assert "Late" in args
    assert args[-2:] == ["--data-dir", str(tmp_path / "data")]


def test_gui_backend_reports_version_and_executable_path(tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend = FedleaveBackend(BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data")))

    assert backend.version() == "fedleave 0.2.0"
    assert backend.executable_path() == fake


def test_find_fedleave_uses_bundled_backend_directory(tmp_path: Path, monkeypatch):
    app_executable = _bundle_executable(tmp_path / "FedLeaveCalendar", "FedLeaveCalendar")
    backend_executable = _bundle_executable(tmp_path / "fedleave", "fedleave")

    monkeypatch.setattr(sys, "argv", [str(app_executable)])
    monkeypatch.setattr(
        executable_search,
        "__file__",
        str(tmp_path / "fedleave" / "executable_search.py"),
    )
    monkeypatch.setattr(backend_module.shutil, "which", lambda name: None)

    assert backend_module.find_fedleave() == backend_executable


def test_find_month_report_graphic_uses_bundled_backend_directory(tmp_path: Path, monkeypatch):
    app_executable = _bundle_executable(tmp_path / "FedLeaveCalendar", "FedLeaveCalendar")
    report_executable = _bundle_executable(tmp_path / "fedleaveMonthReportGraphic", "fedleaveMonthReportGraphic")

    monkeypatch.setattr(sys, "argv", [str(app_executable)])
    monkeypatch.setattr(
        executable_search,
        "__file__",
        str(tmp_path / "fedleave" / "executable_search.py"),
    )
    monkeypatch.setattr(backend_module.shutil, "which", lambda name: None)

    assert backend_module.find_month_report_graphic() == report_executable


def test_run_chart_app_uses_bundled_companion_executable(tmp_path: Path, monkeypatch):
    chart_executable = _bundle_executable(tmp_path / "CreditHoursChartForTheYear", "CreditHoursChartForTheYear")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(backend_module, "find_companion_app", lambda name, explicit=None: chart_executable)
    monkeypatch.setattr(backend_module.subprocess, "run", fake_run)

    backend = FedleaveBackend(BackendOptions(data_dir=str(tmp_path / "data")))
    backend.run_chart_app(
        "CreditHoursChartForTheYear",
        output_file=tmp_path / "chart.png",
        year=2026,
        data_dir=str(tmp_path / "data"),
    )

    assert captured["command"] == [
        str(chart_executable),
        "--outputFile",
        str(tmp_path / "chart.png"),
        "--resolution",
        "1920",
        "--year",
        "2026",
        "--data-dir",
        str(tmp_path / "data"),
    ]
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["check"] is False


def test_find_fedleave_reports_search_paths_when_missing(tmp_path: Path, monkeypatch):
    app_executable = _bundle_executable(tmp_path / "FedLeaveCalendar", "FedLeaveCalendar")

    monkeypatch.setattr(sys, "argv", [str(app_executable)])
    monkeypatch.setattr(
        executable_search,
        "__file__",
        str(tmp_path / "fedleave" / "executable_search.py"),
    )
    monkeypatch.setattr(executable_search, "_candidate_roots", lambda: iter([tmp_path / "fedleave" / "bin", tmp_path / "fedleave" / "dist" ]))
    monkeypatch.setattr(backend_module.shutil, "which", lambda name: None)

    with pytest.raises(backend_module.BackendMissingError, match="Searched:"):
        backend_module.find_fedleave()


def test_gui_backend_hides_windows_console_when_launching_backend(monkeypatch, tmp_path: Path):
    fake = _fake_fedleave(tmp_path / "fedleave")
    backend_module = __import__("fedleave_gui.backend", fromlist=["FedleaveBackend"])
    backend = backend_module.FedleaveBackend(
        backend_module.BackendOptions(fedleave_path=str(fake), data_dir=str(tmp_path / "data"))
    )

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(returncode=0, stdout="fedleave 0.2.0", stderr="")

    monkeypatch.setattr(backend_module.sys, "platform", "win32")
    monkeypatch.setattr(backend_module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(backend_module.subprocess, "run", fake_run)
    monkeypatch.setattr(backend_module, "find_fedleave", lambda explicit=None: fake)

    assert backend.version() == "fedleave 0.2.0"
    assert captured["command"] == [str(fake), "--version"]
    assert captured["kwargs"]["creationflags"] == 0x08000000
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["check"] is False
