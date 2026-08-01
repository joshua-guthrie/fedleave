import subprocess
import sys
from datetime import date
from pathlib import Path

from fedleave_analytics.analytics import analyze_leave_year


def payload(transactions):
    return {
        "year": 2026,
        "leave_year_start": "2026-01-01",
        "leave_year_end": "2026-12-31",
        "pay_periods": [{"pay_period_number": 1, "start_date": "2026-01-01", "end_date": "2026-01-14"}],
        "transactions": transactions,
    }


def test_analytics_uses_hours_and_separates_future_rows():
    result = analyze_leave_year(
        payload(
            [
                {
                    "id": "1",
                    "date": "2026-01-03",
                    "category": "annual",
                    "direction": "used",
                    "hours": 8,
                    "status": "approved",
                },
                {
                    "id": "2",
                    "date": "2026-12-20",
                    "category": "annual",
                    "direction": "used",
                    "hours": 4,
                    "status": "planned",
                },
                {
                    "id": "3",
                    "date": "2026-01-04",
                    "category": "annual",
                    "direction": "used",
                    "hours": 20,
                    "status": "denied",
                },
            ]
        ),
        date(2026, 6, 1),
    )
    assert result["visible_categories"] == ["annual"]
    assert "final_quarter" not in result
    december = next(row for row in result["months"] if row["month"] == "Dec 2026")
    assert december["future_scheduled"] == 4
    saturday = next(row for row in result["weekdays"] if row["weekday"] == "Saturday")
    assert saturday["through_today"] == 8


def test_analytics_builds_every_required_summary_and_seasonality_table():
    data = payload(
        [
            {
                "id": "1",
                "date": "2026-01-03",
                "category": "annual",
                "direction": "used",
                "hours": 8,
                "status": "approved",
            },
            {"id": "2", "date": "2026-12-20", "category": "sick", "direction": "used", "hours": 4, "status": "planned"},
            {
                "id": "3",
                "date": "2026-05-01",
                "category": "overtime",
                "direction": "worked",
                "hours": 3,
                "status": "reconciled",
            },
        ]
    )
    data["pay_periods"] = [
        {"pay_period_number": 1, "start_date": "2026-01-01", "end_date": "2026-01-14"},
        {"pay_period_number": 2, "start_date": "2026-01-15", "end_date": "2026-01-28"},
    ]

    result = analyze_leave_year(data, date(2026, 6, 1))

    assert len(result["weekdays"]) == 7
    assert result["pay_periods"][1]["full_leave_year"] == 0
    assert len(result["heatmap"]) == 365
    assert next(row for row in result["overtime_months"] if row["month"] == "May 2026")["through_today"] == 3
    summary_metrics = {row["metric"] for row in result["summary"]}
    assert "Total Leave Used or Scheduled" in summary_metrics
    assert "Highest Leave-Use Weekday" not in summary_metrics


def test_comp_lifecycle_reconciles_and_uses_matured_lots_only():
    data = payload(
        [
            {
                "id": "earned",
                "date": "2026-01-01",
                "category": "comp",
                "direction": "earned",
                "hours": 10,
                "status": "reconciled",
                "expiration_date": "2026-06-30",
            },
            {
                "id": "used-before",
                "date": "2026-03-02",
                "category": "comp",
                "direction": "used",
                "hours": 4,
                "status": "reconciled",
                "earned_transaction_id": "earned",
            },
            {
                "id": "paid",
                "date": "2026-06-30",
                "category": "comp",
                "direction": "paid_out",
                "hours": 4,
                "status": "planned",
                "earned_transaction_id": "earned",
            },
            {
                "id": "used-after",
                "date": "2026-07-01",
                "category": "comp",
                "direction": "used",
                "hours": 2,
                "status": "planned",
                "earned_transaction_id": "earned",
            },
        ]
    )
    data["starting_balances"] = {"comp": 2}

    result = analyze_leave_year(data, date(2026, 7, 15))

    outstanding = next(row for row in result["lifecycle"]["summary"] if row["metric"] == "Outstanding Comp")
    assert outstanding["full_leave_year"] == 2
    lot = result["lifecycle"]["lots"][0]
    assert lot["projected_remaining"] == 0
    matured = result["lifecycle"]["matured_lots"][0]
    assert matured["used_before_expiration"] == 4
    assert matured["percentage_consumed"] == 40


def test_denied_and_disposition_transactions_are_not_absence_hours():
    result = analyze_leave_year(
        payload(
            [
                {
                    "id": "1",
                    "date": "2026-02-01",
                    "category": "annual",
                    "direction": "used",
                    "hours": 8,
                    "status": "denied",
                },
                {
                    "id": "2",
                    "date": "2026-02-02",
                    "category": "comp",
                    "direction": "paid_out",
                    "hours": 6,
                    "status": "planned",
                },
                {
                    "id": "3",
                    "date": "2026-02-03",
                    "category": "annual",
                    "direction": "used",
                    "hours": 2,
                    "status": "approved",
                },
            ]
        ),
        date(2026, 2, 15),
    )

    assert next(row for row in result["summary"] if row["metric"] == "Total Leave Used or Scheduled")["value"] == 2
    assert result["source"]["transactions_received"] == 3
    assert result["source"]["transactions_included"] == 2


def test_credit_hours_are_analyzed_and_heatmaps_only_include_nonzero_series():
    data = payload(
        [
            {
                "id": "annual-used",
                "date": "2026-02-01",
                "category": "annual",
                "direction": "used",
                "hours": 8,
                "status": "approved",
            },
            {
                "id": "annual-earned",
                "date": "2026-02-01",
                "category": "annual",
                "direction": "earned",
                "hours": 4,
                "status": "reconciled",
            },
            {
                "id": "sick-earned",
                "date": "2026-02-01",
                "category": "sick",
                "direction": "earned",
                "hours": 4,
                "status": "reconciled",
            },
            {
                "id": "credit-earned",
                "date": "2026-02-02",
                "category": "credit",
                "direction": "earned",
                "hours": 4,
                "status": "reconciled",
            },
            {
                "id": "credit-worked",
                "date": "2026-02-03",
                "category": "credit",
                "direction": "worked",
                "hours": 2,
                "status": "reconciled",
            },
            {
                "id": "credit-used",
                "date": "2026-02-04",
                "category": "credit",
                "direction": "used",
                "hours": 1,
                "status": "approved",
            },
        ]
    )
    data["starting_balances"] = {"credit": 3}

    result = analyze_leave_year(data, date(2026, 6, 1))

    metrics = {row["metric"]: row for row in result["lifecycle"]["summary"]}
    assert metrics["Credit Hours Earned"]["full_leave_year"] == 4
    assert metrics["Credit Hours Worked"]["full_leave_year"] == 2
    assert metrics["Credit Hours Used"]["full_leave_year"] == 1
    assert metrics["Outstanding Credit Hours"]["through_today"] == 8
    february = next(row for row in result["lifecycle"]["monthly_credit"] if row["month"] == "Feb 2026")
    assert (february["earned"], february["worked"], february["used"]) == (4, 2, 1)
    comparison = next(row for row in result["lifecycle"]["monthly_overtime_vs_comp"] if row["month"] == "Feb 2026")
    assert comparison["credit_earned"] == 6
    assert [option["key"] for option in result["heatmap_options"]] == [
        "all-used",
        "annual:used",
        "credit:earned",
        "credit:used",
    ]
    assert "annual:earned" not in result["heatmap_series"]
    assert "sick:earned" not in result["heatmap_series"]
    assert any(
        warning["severity"] == "Error"
        and warning["area"] == "Credit hours"
        and "'worked' direction" in warning["message"]
        for warning in result["warnings"]
    )


def test_analytics_package_entrypoint_supports_direct_execution():
    entrypoint = Path(__file__).parents[1] / "src" / "fedleave_analytics" / "__main__.py"
    result = subprocess.run(
        [sys.executable, str(entrypoint), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Read-only FedLeave seasonality" in result.stdout
