from __future__ import annotations

import sys
import types

import pytest


def _install_chart_import_stubs(monkeypatch):
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.array = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "numpy", numpy_stub)

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


@pytest.mark.parametrize(
    "module_name, app_name, category",
    [
        ("yearly_leave_comparison_chart.annual", "AnnualLeaveYearlyComparison", "annual"),
        ("yearly_leave_comparison_chart.sick", "SickLeaveYearlyComparison", "sick"),
        ("yearly_leave_comparison_chart.credit", "CreditHoursYearlyComparison", "credit"),
        ("yearly_leave_comparison_chart.comp", "CompTimeYearlyComparison", "comp"),
        ("yearly_leave_comparison_chart.travel_comp", "TravelCompYearlyComparison", "travel_comp"),
        ("yearly_leave_comparison_chart.time_off_award", "TimeOffAwardYearlyComparison", "time_off_award"),
        ("yearly_leave_comparison_chart.overtime", "OvertimeYearlyComparison", "overtime"),
    ],
)
def test_yearly_comparison_chart_modules_expose_expected_specs(monkeypatch, module_name, app_name, category):
    _install_chart_import_stubs(monkeypatch)
    module = __import__(module_name, fromlist=["SPEC", "main"])

    assert module.SPEC.app_name == app_name
    assert module.SPEC.category == category

    captured = {}
    monkeypatch.setattr(module, "run_comparison_chart_app", lambda spec: captured.setdefault("spec", spec))

    module.main()

    assert captured["spec"] == module.SPEC