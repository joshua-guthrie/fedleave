import importlib
import json
import sys
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

import fedleave.executable_search as executable_search

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def _install_chart_import_stubs(monkeypatch):
    pil_module = types.ModuleType("PIL")
    image_module = types.ModuleType("PIL.Image")
    image_draw_module = types.ModuleType("PIL.ImageDraw")
    image_font_module = types.ModuleType("PIL.ImageFont")

    class _DummyFont:
        pass

    def _truetype(*args, **kwargs):
        return _DummyFont()

    image_font_module.FreeTypeFont = _DummyFont
    image_font_module.ImageFont = _DummyFont
    image_font_module.truetype = _truetype

    pil_module.Image = image_module
    pil_module.ImageDraw = image_draw_module
    pil_module.ImageFont = image_font_module

    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageDraw", image_draw_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageFont", image_font_module)


def _make_bundle_executable(bundle_root: Path, app_name: str) -> Path:
    bundle_root.mkdir(parents=True, exist_ok=True)
    executable = bundle_root / (f"{app_name}.exe" if sys.platform.startswith("win") else app_name)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


@pytest.mark.parametrize(
    "module_name, app_name",
    [
        ("annual_leave_chart.chart", "AnnualLeaveChartForTheYear"),
        ("sick_leave_chart.chart", "SickLeaveChartForTheYear"),
    ],
)
def test_find_fedleave_app_uses_sibling_executable(tmp_path, monkeypatch, module_name, app_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    app_path = tmp_path / app_name
    fedleave_name = "fedleave.exe" if sys.platform.startswith("win") else "fedleave"
    fedleave_path = tmp_path / fedleave_name
    app_path.write_text("#!/bin/sh\n")
    fedleave_path.write_text("#!/bin/sh\n")
    app_path.chmod(0o755)
    fedleave_path.chmod(0o755)

    monkeypatch.setattr(sys, "argv", [str(app_path)])
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    assert module.find_fedleave_app() == fedleave_path


@pytest.mark.parametrize(
    "module_name, app_name",
    [
        ("annual_leave_chart.chart", "AnnualLeaveChartForTheYear"),
        ("sick_leave_chart.chart", "SickLeaveChartForTheYear"),
    ],
)
def test_find_fedleave_app_ignores_package_directory(tmp_path, monkeypatch, module_name, app_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    app_path = tmp_path / app_name
    python_path = tmp_path / "python"
    package_dir = tmp_path / "fedleave"
    path_fedleave_name = "fedleave.exe" if sys.platform.startswith("win") else "fedleave"
    path_fedleave = tmp_path / "bin" / path_fedleave_name
    app_path.write_text("#!/bin/sh\n")
    python_path.write_text("#!/bin/sh\n")
    package_dir.mkdir()
    path_fedleave.parent.mkdir()
    path_fedleave.write_text("#!/bin/sh\n")
    app_path.chmod(0o755)
    python_path.chmod(0o755)
    package_dir.chmod(0o755)
    path_fedleave.chmod(0o755)

    monkeypatch.setattr(sys, "argv", [str(app_path)])
    monkeypatch.setattr(sys, "executable", str(python_path))
    monkeypatch.setattr(module, "__file__", str(tmp_path / "annual_leave_chart" / "chart.py"))
    monkeypatch.setattr(
        executable_search,
        "__file__",
        str(tmp_path / "fedleave" / "executable_search.py"),
    )
    monkeypatch.setattr(module.shutil, "which", lambda name: str(path_fedleave))

    assert module.find_fedleave_app() == path_fedleave


@pytest.mark.parametrize(
    "module_name, app_name",
    [
        ("annual_leave_chart.chart", "AnnualLeaveChartForTheYear"),
        ("sick_leave_chart.chart", "SickLeaveChartForTheYear"),
    ],
)
def test_find_fedleave_app_uses_bundled_backend_directory(tmp_path, monkeypatch, module_name, app_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    app_path = _make_bundle_executable(tmp_path / app_name, app_name)
    fedleave_path = _make_bundle_executable(tmp_path / "fedleave", "fedleave")

    monkeypatch.setattr(sys, "argv", [str(app_path)])
    monkeypatch.setattr(
        executable_search,
        "__file__",
        str(tmp_path / "fedleave" / "executable_search.py"),
    )
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    assert module.find_fedleave_app() == fedleave_path


@pytest.mark.parametrize("module_name", ["annual_leave_chart.chart", "sick_leave_chart.chart"])
def test_run_fedleave_uses_subcommand_arguments(monkeypatch, module_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    captured = {}

    def fake_run(cmd, text, capture_output, check):
        captured["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "find_fedleave_app", lambda: Path("/tmp/fedleave"))

    module.run_fedleave(["balance", "--year", "2026", "--json"])

    assert captured["cmd"] == [str(Path("/tmp/fedleave")), "balance", "--year", "2026", "--json"]


def test_balance_chart_font_loader_uses_windows_fonts(monkeypatch):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module("fedleave.charting")
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("WINDIR", "C:/Windows")

    chosen: dict[str, object] = {}

    def fake_exists(self):
        return str(self).lower().endswith("arialbd.ttf")

    def fake_truetype(path, size):
        chosen["path"] = path
        chosen["size"] = size
        return module.ImageFont.FreeTypeFont()

    monkeypatch.setattr(module.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(module.ImageFont, "truetype", fake_truetype)

    font = module.load_font(18, bold=True)

    assert isinstance(font, module.ImageFont.FreeTypeFont)
    assert str(chosen["path"]).lower().endswith("arialbd.ttf")
    assert chosen["size"] == 18


@pytest.mark.parametrize("module_name", ["annual_leave_chart.chart", "sick_leave_chart.chart"])
def test_legacy_chart_font_loader_uses_windows_fonts(monkeypatch, module_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("WINDIR", "C:/Windows")

    chosen: dict[str, object] = {}

    def fake_exists(self):
        return str(self).lower().endswith("segoeui.ttf")

    def fake_truetype(path, size):
        chosen["path"] = path
        chosen["size"] = size
        return module.ImageFont.FreeTypeFont()

    monkeypatch.setattr(module.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(module.ImageFont, "truetype", fake_truetype)

    font = module.load_font(18, scale=1.0)

    assert isinstance(font, module.ImageFont.FreeTypeFont)
    assert str(chosen["path"]).lower().endswith("segoeui.ttf")
    assert chosen["size"] == 18


@pytest.mark.parametrize("module_name", ["annual_leave_chart.chart", "sick_leave_chart.chart"])
def test_infer_leave_year_uses_current_leave_year(tmp_path, monkeypatch, module_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 1)

    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    (leave_years / "2025.json").write_text(
        json.dumps({"leave_year_start": "2025-01-12", "leave_year_end": "2026-01-10"})
    )
    (leave_years / "2026.json").write_text(
        json.dumps({"leave_year_start": "2026-01-11", "leave_year_end": "2027-01-09"})
    )

    monkeypatch.setattr(module, "date", FakeDate)

    assert module.infer_leave_year(tmp_path) == 2026


@pytest.mark.parametrize("module_name", ["annual_leave_chart.chart", "sick_leave_chart.chart"])
def test_infer_leave_year_falls_back_to_latest_year(tmp_path, monkeypatch, module_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2030, 6, 1)

    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    (leave_years / "2025.json").write_text(
        json.dumps({"leave_year_start": "2025-01-12", "leave_year_end": "2026-01-10"})
    )
    (leave_years / "2026.json").write_text(
        json.dumps({"leave_year_start": "2026-01-11", "leave_year_end": "2027-01-09"})
    )

    monkeypatch.setattr(module, "date", FakeDate)

    assert module.infer_leave_year(tmp_path) == 2026


@pytest.mark.parametrize(
    "module_name, balance_function",
    [
        ("annual_leave_chart.chart", "annual_balance_points"),
        ("sick_leave_chart.chart", "sick_leave_balance_points"),
    ],
)
def test_main_uses_supplied_data_dir_for_inferred_year(tmp_path, monkeypatch, capsys, module_name, balance_function):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    data_dir = tmp_path / "data"
    leave_years = data_dir / "leave_years"
    leave_years.mkdir(parents=True)
    (leave_years / "2026.json").write_text(
        json.dumps({"leave_year_start": "2026-01-11", "leave_year_end": "2027-01-09"})
    )
    output = tmp_path / "chart.png"
    captured = {}

    def fake_balance_points(year, data_dir_arg):
        captured["year"] = year
        captured["data_dir"] = data_dir_arg
        if balance_function == "sick_leave_balance_points":
            return [], {"leave_year_start": "2026-01-11", "leave_year_end": "2027-01-09"}, Decimal("0")
        return [], {"leave_year_start": "2026-01-11", "leave_year_end": "2027-01-09"}

    monkeypatch.setattr(sys, "argv", ["chart", "--outputFile", str(output), "--data-dir", str(data_dir)])
    monkeypatch.setattr(module, balance_function, fake_balance_points)
    monkeypatch.setattr(module, "render", lambda *args, **kwargs: None)

    module.main()
    capsys.readouterr()

    assert captured == {"year": 2026, "data_dir": data_dir}


@pytest.mark.parametrize("module_name", ["annual_leave_chart.chart", "sick_leave_chart.chart"])
def test_get_leave_year_data_reads_leave_year_file_after_fedleave_balance(tmp_path, monkeypatch, module_name):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)

    data_dir = tmp_path / "data"
    leave_years = data_dir / "leave_years"
    leave_years.mkdir(parents=True)
    leave_year = {
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "starting_balances": {"annual": 120, "sick": 180},
        "transactions": [],
        "pay_periods": [],
    }
    (leave_years / "2026.json").write_text(json.dumps(leave_year))
    captured = {}

    def fake_run_fedleave(args):
        captured["args"] = args
        return {"balances": {"annual": 120, "sick": 180}}

    monkeypatch.setattr(module, "run_fedleave", fake_run_fedleave)

    assert module.get_leave_year_data(2026, data_dir) == leave_year
    assert captured["args"] == [
        "balance",
        "--year",
        "2026",
        "--json",
        "--data-dir",
        str(data_dir),
    ]


@pytest.mark.parametrize(
    "module_name, balance_function, category, expected",
    [
        ("annual_leave_chart.chart", "annual_balance_points", "annual", Decimal("126")),
        ("sick_leave_chart.chart", "sick_leave_balance_points", "sick", Decimal("184")),
    ],
)
def test_balance_points_accept_pay_period_end_date_schema(
    monkeypatch, module_name, balance_function, category, expected
):
    _install_chart_import_stubs(monkeypatch)
    module = importlib.import_module(module_name)
    leave_year = {
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "starting_balances": {"annual": 120, "sick": 180},
        "transactions": [
            {
                "id": "20260124-001",
                "date": "2026-01-24",
                "category": category,
                "direction": "earned",
                "hours": 6 if category == "annual" else 4,
            }
        ],
        "pay_periods": [{"end_date": "2026-01-24"}],
    }
    monkeypatch.setattr(module, "get_leave_year_data", lambda year, data_dir: leave_year)

    result = getattr(module, balance_function)(2026)
    points = result[0]

    assert points == [(date(2026, 1, 24), expected)]
