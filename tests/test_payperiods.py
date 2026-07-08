from datetime import date

from fedleave.payperiods import generate_pay_periods, normalize_pay_period, pay_period_pay_date


def test_generate_26_pay_periods():
    start = date(2026, 1, 11)
    periods = generate_pay_periods(start, 26)

    assert len(periods) == 26
    assert periods[0]["pay_period_number"] == 1
    assert periods[0]["start_date"] == "2026-01-11"
    assert periods[0]["end_date"] == "2026-01-24"
    assert periods[0]["pay_date"] == "2026-01-30"
    assert periods[1]["start_date"] == "2026-01-25"
    assert periods[1]["pay_date"] == "2026-02-13"
    assert periods[-1]["end_date"] == "2027-01-09"
    assert periods[-1]["pay_date"] == "2027-01-15"


def test_pay_date_is_inferred_for_older_pay_period_records():
    old_period = {
        "pay_period_number": 1,
        "start_date": "2026-01-11",
        "end_date": "2026-01-24",
        "accrual_date": "2026-01-24",
    }

    assert pay_period_pay_date(old_period) == "2026-01-30"
    assert normalize_pay_period(old_period)["pay_date"] == "2026-01-30"
