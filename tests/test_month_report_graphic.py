from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from fedleave.ledger import TRANSACTION_CATEGORIES
from fedleave.executable_search import is_executable
from fedleave_month_report_graphic.report import (
    ArgumentError,
    CATEGORY_LABELS,
    find_fedleave,
    Options,
    OutputError,
    PAYDAY_STROKE,
    ReportData,
    load_report_data,
    parse_args,
    parse_month,
    render_svg,
    write_output,
)


def _report_data() -> ReportData:
    return ReportData(
        month_json={
            "year": 2026,
            "month": 7,
            "days": [
                {
                    "date": "2026-06-28",
                    "in_display_month": False,
                    "holiday_name": None,
                    "entries": [],
                    "display_lines": [],
                },
                {
                    "date": "2026-07-01",
                    "in_display_month": True,
                    "holiday_name": None,
                    "entries": [
                        {
                            "id": "20260701-001",
                            "category": "annual",
                            "direction": "used",
                            "hours": 2.0,
                            "status": "planned",
                            "source": "manual",
                            "description": "Private appointment",
                        },
                        {
                            "id": "20260701-002",
                            "category": "credit",
                            "direction": "earned",
                            "hours": 0.0,
                            "status": "planned",
                            "source": "manual",
                            "description": "Zero-value detail",
                        },
                    ],
                    "display_lines": ["A -2.0", "Cr +0.0"],
                },
            ],
            "pay_periods": [
                {
                    "number": 14,
                    "start": "2026-06-28",
                    "end": "2026-07-11",
                    "pay_date": "2026-07-17",
                    "totals": {
                        "annual": {"earned": 6.0, "used": 2.0, "worked": 0.0, "net": 4.0},
                        "credit": {"earned": 0.0, "used": 0.0, "worked": 0.0, "net": 0.0},
                    },
                    "ending_balances": {
                        "annual": 14.0,
                        "sick": 20.0,
                        "credit": 3.0,
                    },
                }
            ],
        },
        balance_json={"balances": {"annual": 124.0, "sick": 0.0}},
        projected_json={"balances": {"annual": 180.0}, "use_or_lose": {"use_or_lose": 0.0}},
        pay_periods_json=None,
        today=date(2026, 7, 1),
        generated_at=datetime(2026, 7, 1, 12, 30),
    )


def test_parse_month_accepts_number_and_full_english_name():
    assert parse_month("7") == 7
    assert parse_month("July") == 7
    assert parse_month("july") == 7

    with pytest.raises(ArgumentError):
        parse_month("Jul")

    with pytest.raises(ArgumentError):
        parse_month("13")


def test_parse_args_requires_year_and_month_together(tmp_path):
    with pytest.raises(ArgumentError, match="together"):
        parse_args(["--year", "2026", "--outputFile", str(tmp_path / "out.png")])

    with pytest.raises(ArgumentError, match="together"):
        parse_args(["--month", "July", "--outputFile", str(tmp_path / "out.png")])


def test_parse_args_supports_version_without_output_file(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["--version"])

    assert exc.value.code == 0
    assert "fedleaveMonthReportGraphic" in capsys.readouterr().out


def test_parse_args_rejects_existing_output_without_overwrite(tmp_path):
    output = tmp_path / "report.png"
    output.write_bytes(b"existing")

    with pytest.raises(OutputError):
        parse_args(["--outputFile", str(output)])


def test_find_fedleave_accepts_explicit_path(tmp_path):
    fedleave = tmp_path / "fedleave"
    fedleave.write_text("#!/bin/sh\n", encoding="utf-8")
    fedleave.chmod(0o755)

    assert find_fedleave(fedleave) == fedleave


def test_windows_executable_detection_rejects_extensionless_binary(monkeypatch, tmp_path):
    monkeypatch.setattr("fedleave_month_report_graphic.report.sys.platform", "win32")
    linux_binary_name = tmp_path / "fedleave"
    windows_binary_name = tmp_path / "fedleave.exe"
    linux_binary_name.write_bytes(b"not a windows executable")
    windows_binary_name.write_bytes(b"fake exe")

    assert is_executable(linux_binary_name) is False
    assert is_executable(windows_binary_name) is True


def test_render_svg_omits_private_transaction_fields_and_zero_values():
    svg = render_svg(_report_data(), 1920)

    assert "FedLeave Month Report - July 2026" in svg
    assert ">A<" in svg
    assert ">-2<" in svg
    assert "Private appointment" not in svg
    assert "20260701-001" not in svg
    assert "manual" not in svg
    assert "planned" not in svg
    assert "Zero-value detail" not in svg
    assert not re.search(r">\+?0(?:\.0+)?<", svg)


def test_render_svg_uses_backend_pay_dates_not_every_friday():
    data = _report_data()
    with_payday = render_svg(data, 1920)

    data_without_payday = _report_data()
    data_without_payday.month_json["pay_periods"][0].pop("pay_date")
    without_payday = render_svg(data_without_payday, 1920)

    assert with_payday.count(f'stroke="{PAYDAY_STROKE}"') == without_payday.count(f'stroke="{PAYDAY_STROKE}"') + 1


def test_render_svg_applies_issue_28_cosmetic_layout():
    svg = render_svg(_report_data(), 1920)

    assert ">Markers<" not in svg
    assert ">Projected<" not in svg
    assert ">Use/Lose<" not in svg
    assert ">End of Year Use or Loose<" in svg
    assert ">Type<" in svg
    assert ">Earned<" in svg
    assert ">Used<" in svg
    assert ">Balance<" in svg
    assert ">14<" in svg
    assert ">Wrk<" not in svg
    assert ">Net<" not in svg
    for category in TRANSACTION_CATEGORIES:
        assert f">{CATEGORY_LABELS[category][0]}<" in svg
        assert f">{CATEGORY_LABELS[category][1]}<" in svg


def test_render_svg_places_marker_legend_at_bottom_of_abbreviations_section():
    svg = render_svg(_report_data(), 1920)

    assert 'x="1240.0" y="1004.0" width="16"' in svg
    assert 'x="1702.0" y="1004.0" width="16"' in svg
    assert '<text x="1264.0" y="1018.0"' in svg
    assert ">Holiday<" in svg
    assert ">Pay Day<" in svg
    assert ">Pay Period End<" in svg
    assert ">Today<" in svg


def test_render_svg_shows_year_end_use_or_lose_when_annual_exceeds_carryover():
    data = _report_data()
    data.balance_json = {"balances": {"annual": 300.0, "sick": 20.0}}
    data.projected_json = {
        "balances": {"annual": 300.0, "sick": 20.0},
        "use_or_lose": {
            "carryover_limit": 240.0,
            "annual_carryover": 240.0,
            "use_or_lose": 60.0,
        },
    }

    svg = render_svg(data, 1920)

    assert ">End of Year Use or Loose<" in svg
    assert ">Annual<" in svg
    assert ">300<" in svg
    assert ">60<" in svg


def test_render_svg_shows_decimal_use_or_lose_from_issue_30_backup():
    data = _report_data()
    data.balance_json = {"balances": {"annual": 180.35, "sick": 589.85}}
    data.projected_json = {
        "project_to": "2027-01-09",
        "balances": {"annual": 292.35, "sick": 693.85},
        "use_or_lose": {
            "carryover_limit": 240.0,
            "annual_carryover": 240.0,
            "use_or_lose": 52.35,
        },
    }

    svg = render_svg(data, 1920)

    assert ">End of Year Use or Loose<" in svg
    assert ">180.35<" in svg
    assert ">52.35<" in svg
    assert ">0<" not in svg


def test_load_report_data_prefers_enriched_month_payload(monkeypatch, tmp_path):
    calls = []
    month_payload = _report_data().month_json
    month_payload["balance_as_of_today"] = {"as_of": "2026-07-01", "balances": {"annual": 124.0}}
    month_payload["projected_balance"] = {
        "project_to": "2027-01-09",
        "balances": {"annual": 180.0},
        "use_or_lose": {"use_or_lose": 0.0},
    }
    projected_payload = {
        "year": 2026,
        "as_of": "2027-01-09",
        "projected": True,
        "project_to": "2027-01-09",
        "balances": {"annual": 180.0},
        "use_or_lose": {
            "carryover_limit": 240.0,
            "annual_carryover": 180.0,
            "use_or_lose": 0.0,
        },
    }

    monkeypatch.setattr("fedleave_month_report_graphic.report.find_fedleave", lambda explicit=None: tmp_path / "fedleave")

    def fake_run_fedleave(_fedleave, args):
        calls.append(args)
        if args[0] == "month":
            return month_payload
        if args[0] == "use-or-lose":
            return projected_payload
        raise AssertionError(f"Unexpected extra fedleave call: {args}")

    monkeypatch.setattr("fedleave_month_report_graphic.report.run_fedleave", fake_run_fedleave)

    _fedleave, data = load_report_data(
        Options(tmp_path / "month.png", 2026, 7, 1920, None, None, False, False, False)
    )

    assert [call[0] for call in calls] == ["month", "use-or-lose"]
    assert data.balance_json["balances"]["annual"] == 124.0
    assert data.projected_json["balances"]["annual"] == 180.0
    assert data.projected_json["use_or_lose"]["use_or_lose"] == 0.0


def test_write_output_creates_svg_and_png(tmp_path):
    data = _report_data()
    svg_output = tmp_path / "month.svg"
    png_output = tmp_path / "month.png"

    write_output(
        data,
        Options(svg_output, 2026, 7, 800, None, None, False, False, False),
    )
    write_output(
        data,
        Options(png_output, 2026, 7, 800, None, None, False, False, False),
    )

    assert svg_output.read_text(encoding="utf-8").startswith("<svg")
    assert png_output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
