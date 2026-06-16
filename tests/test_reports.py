from pathlib import Path
import json

from fedleave.reports import generate


def test_generate_report_injects_summary_and_metadata(tmp_path: Path):
    data_dir = tmp_path / "data"
    leave_years = data_dir / "leave_years"
    leave_years.mkdir(parents=True)

    report_year = 2026
    leave_year = {
        "schema_version": 1,
        "leave_year": report_year,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2026-12-31",
        "pay_period_count": 26,
        "annual_leave_accrual_hours": 6.0,
        "sick_leave_accrual_hours": 4.0,
        "starting_balances": {
            "annual": 120.0,
            "sick": 80.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        "transactions": [
            {
                "id": "20260601-001",
                "date": "2026-06-01",
                "category": "annual",
                "direction": "used",
                "hours": 20.0,
                "description": "Vacation",
                "status": "worked",
                "source": "manual",
            }
        ],
    }
    (leave_years / f"{report_year}.json").write_text(json.dumps(leave_year), encoding="utf-8")

    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    output_path = tmp_path / "fedleave_report.odt"
    generate(
        year=report_year,
        data_dir=data_dir,
        chart=str(chart_path),
        output=str(output_path),
    )

    assert output_path.exists()

    with Path(output_path).open("rb") as handle:
        from zipfile import ZipFile

        with ZipFile(handle) as archive:
            content = archive.read("content.xml").decode("utf-8")

    assert f"Fedleave Report — {report_year}" in content
    assert "Prepared by" in content
    assert "SummaryTable" in content
    assert "Total" in content
    assert "Leave Balance Chart" in content
