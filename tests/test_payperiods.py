from datetime import date

from fedleave.payperiods import generate_pay_periods


def test_generate_26_pay_periods():
    start = date(2026, 1, 11)
    periods = generate_pay_periods(start, 26)

    assert len(periods) == 26
    assert periods[0]["pay_period_number"] == 1
    assert periods[0]["start_date"] == "2026-01-11"
    assert periods[0]["end_date"] == "2026-01-24"
    assert periods[1]["start_date"] == "2026-01-25"
    assert periods[-1]["end_date"] == "2027-01-09"
