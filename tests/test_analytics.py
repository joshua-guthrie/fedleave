from datetime import date

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
    result = analyze_leave_year(payload([
        {"id": "1", "date": "2026-01-03", "category": "annual", "direction": "used", "hours": 8, "status": "approved"},
        {"id": "2", "date": "2026-12-20", "category": "annual", "direction": "used", "hours": 4, "status": "planned"},
        {"id": "3", "date": "2026-01-04", "category": "annual", "direction": "used", "hours": 20, "status": "denied"},
    ]), date(2026, 6, 1))
    assert result["visible_categories"] == ["annual"]
    assert result["final_quarter"]["total_hours"] == 12
    december = next(row for row in result["months"] if row["month"] == "2026-12")
    assert december["future_scheduled"] == 4
    assert result["weekdays"]["Saturday"]["through_today"] == 8


def test_final_quarter_is_the_last_25_percent_of_inclusive_days():
    result = analyze_leave_year(payload([
        {"id": "1", "date": "2026-10-07", "category": "annual", "direction": "used", "hours": 2, "status": "approved"},
        {"id": "2", "date": "2026-10-08", "category": "annual", "direction": "used", "hours": 3, "status": "approved"},
    ]), date(2026, 10, 1))
    assert result["final_quarter"]["start_date"] == "2026-10-01"
    assert result["final_quarter"]["percentage"] == 100
