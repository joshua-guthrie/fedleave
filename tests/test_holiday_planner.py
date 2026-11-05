from copy import deepcopy
from dataclasses import asdict
from datetime import date

import pytest

from fedleave.holiday_planner import HolidayParameters, plan_holidays
from fedleave.planning import project
from leave_year_support import tx
from test_budget import lot
from test_forecast import source

TODAY = date(2026, 5, 20)


def snapshot(*, transactions=(), balances=None):
    result = source(transactions=transactions, balances={"annual": 100} if balances is None else balances)
    result["snapshot_rules"]["defaults"]["normal_workdays"] = ["mon", "tue", "wed", "thu", "fri"]
    result["snapshot_rules"]["holidays"]["enabled"] = True
    result["calculation_context"].update(
        holiday_coverage=[2026],
        holidays=[{"date": "2026-05-25", "observed_date": "2026-05-25", "name": "Monday holiday", "nonworking": True}],
    )
    return result


def run(data=None, **values):
    params = HolidayParameters(**{"cutoff": "2026-05-20", "start": "2026-05-21", "end": "2026-05-26", **values})
    return plan_holidays(data if data is not None else snapshot(), params, today=TODAY)


def friday(result):
    return next(o for o in result.candidates if (o.metrics["start"], o.metrics["end"]) == ("2026-05-22", "2026-05-25"))


def test_friday_holiday_exact_hours_and_nonmutation():
    data = snapshot()
    original = deepcopy(data)
    result = run(data)
    option = friday(result)
    assert (
        option.metrics["calendar_days"],
        option.metrics["workdays"],
        option.metrics["additional_hours"],
        option.metrics["efficiency"],
    ) == (4, 1, 8, 4)
    assert [(r["date"], r["hours"]) for r in option.funding] == [("2026-05-22", 8)]
    assert option.days[-1]["holiday"] == ["Monday holiday"]
    assert option.after.daily == project(data, option.scenario, today=TODAY).daily
    assert data == original
    assert asdict(result) == asdict(run(data))


@pytest.mark.parametrize("existing,additional", [(4, 4), (8, 0)])
def test_existing_booking(existing, additional):
    option = friday(run(snapshot(transactions=[tx("booked", "2026-05-22", "annual", "used", existing)])))
    assert option.metrics["additional_hours"] == additional
    if not additional:
        assert option.metrics["label"] == "Already scheduled"
        assert option.metrics["efficiency"] is None
        assert not option.scenario.operations


def test_expiry_and_independent_alternatives():
    data = snapshot(balances={}, transactions=[lot("old", hours=16, earned="2026-05-01", deadline="2026-05-21")])
    assert not run(data, eligible_categories=("comp",)).candidates
    data = snapshot(balances={}, transactions=[lot("usable", hours=16, earned="2026-05-01", deadline="2026-05-26")])
    result = run(data, eligible_categories=("comp",))
    assert len(result.candidates) >= 2
    assert all(sum(r["hours"] for r in o.funding) <= 16 for o in result.candidates)
    assert friday(result).metrics["expiring_hours"] == 8


def test_deadline_order_then_annual():
    data = snapshot(
        transactions=[
            lot("early", hours=4, earned="2026-05-01", deadline="2026-05-22"),
            lot("late", hours=2, earned="2026-05-01", deadline="2026-05-26"),
        ]
    )
    assert [(r["lot_id"], r["category"], r["hours"]) for r in friday(run(data)).funding] == [
        ("early", "comp", 4),
        ("late", "comp", 2),
        (None, "annual", 2),
    ]


def test_future_earnings_and_intermediate_reserve():
    data = snapshot(balances={}, transactions=[tx("later", "2026-05-26", "annual", "earned", 100)])
    assert all(o.metrics["start"] != "2026-05-22" for o in run(data, eligible_categories=("annual",)).candidates)
    data["starting_balances"] = {"annual": 10}
    option = friday(run(data, reserves={"annual": 4}, include_infeasible=True))
    assert option.metrics["state"] == "Infeasible"
    assert option.metrics["unfunded_hours"] == 2


def test_mixed_purpose_explicit_and_restricted_funding_rejected():
    data = snapshot(transactions=[tx("medical", "2026-05-22", "sick", "used", 4)])
    assert not any(o.metrics["start"] == "2026-05-22" for o in run(data).candidates)
    option = friday(run(data, include_mixed=True))
    assert option.metrics["mixed_purpose"] and option.metrics["existing_other_hours"] == 4
    assert option.metrics["additional_hours"] == 4
    assert all(r["category"] != "sick" for r in option.funding)
    with pytest.raises(ValueError, match="discretionary"):
        run(eligible_categories=("sick",))


def test_observed_marker_override_nonstandard_schedule_unknown_context():
    data = snapshot()
    data["calculation_context"]["holidays"] = [
        {"date": "2026-05-22", "observed_date": "2026-05-25", "nonworking": True}
    ]
    assert friday(run(data)).metrics["additional_hours"] == 8
    data["calculation_context"]["holidays"][0]["nonworking"] = False
    assert friday(run(data)).metrics["additional_hours"] == 16
    data["snapshot_rules"]["defaults"].update(
        normal_workdays=["sun", "mon", "tue", "wed", "thu"],
        workday_start="06:00",
        workday_end="16:30",
        lunch_start="12:00",
        lunch_end="12:30",
    )
    result = run(data)
    assert result.assumptions["daily_work_hours"] == 10
    assert next(r for r in result.daily if r["date"] == "2026-05-22")["scheduled_hours"] == 0
    assert next(r for r in result.daily if r["date"] == "2026-05-24")["scheduled_hours"] == 10
    data["calculation_context"]["holiday_coverage"] = []
    assert not run(data).candidates
    assert all(r["additional_hours"] is None for r in run(data).daily)


def test_no_leave_section_and_zero_capacity():
    data = snapshot()
    data["snapshot_rules"]["defaults"]["normal_workdays"] = ["tue"]
    result = run(data, maximum_hours=0)
    assert not result.candidates
    assert result.no_leave[0]["label"] == "No leave required"
    assert result.no_leave[0]["calendar_days"] == 5


@pytest.mark.parametrize("ranking", ["efficiency", "least", "longest", "expiring"])
def test_stable_bounded_ranking(ranking):
    result = run(ranking=ranking, limit=2)
    assert len(result.candidates) == 2
    ranges = [(o.metrics["start"], o.metrics["end"]) for o in result.candidates]
    assert len(set(ranges)) == 2
    assert ranges == [(o.metrics["start"], o.metrics["end"]) for o in run(ranking=ranking, limit=2).candidates]


@pytest.mark.parametrize(
    "values",
    [
        {"maximum_hours": -1},
        {"maximum_hours": float("nan")},
        {"start": "2026-05-20"},
        {"end": "2027-01-01"},
        {"maximum_days": 3},
        {"minimum_days": 0},
        {"limit": 101},
        {"ranking": "other"},
        {"reserves": {"annual": -1}},
    ],
)
def test_invalid(values):
    with pytest.raises(ValueError):
        run(**values)


def test_cancel():
    with pytest.raises(ValueError, match="Canceled"):
        plan_holidays(
            snapshot(), HolidayParameters("2026-05-20", "2026-05-21", "2026-05-26"), today=TODAY, canceled=lambda: True
        )


def test_disabled_expiration_and_extended_deadline():
    award = lot("award", category="time_off_award", hours=8, earned="2026-05-01", deadline="2026-05-21")
    data = snapshot(balances={}, transactions=[award])
    data["snapshot_rules"]["rules"]["time_off_award"]["expires"] = False
    option = friday(run(data, eligible_categories=("time_off_award",)))
    assert option.funding[0]["deadline"] is None
    assert option.metrics["expiring_hours"] == 0
    award.update(
        original_expiration_date="2026-05-21",
        expiration_date="2026-05-22",
        expiration_extension_reason="Authorized extension",
    )
    data = snapshot(balances={}, transactions=[award])
    data["snapshot_rules"]["rules"]["time_off_award"].update(expires=True, allow_extension=True)
    assert friday(run(data, eligible_categories=("time_off_award",))).metrics["expiring_hours"] == 8


def test_unknown_provenance_and_unsupported_credit_are_incomplete():
    data = snapshot(balances={"comp": 100})
    result = run(data, eligible_categories=("comp",), include_infeasible=True)
    assert friday(result).metrics["state"] == "Incomplete funding"
    assert any(w.code == "MISSING_LOT_PROVENANCE" for w in result.warnings)
    data = snapshot(balances={"credit": 100})
    data["snapshot_rules"]["rules"]["credit"]["usable_when"] = "unsupported"
    assert (
        friday(run(data, eligible_categories=("credit",), include_infeasible=True)).metrics["state"]
        == "Incomplete funding"
    )


def test_credit_usability_same_day_and_disabled_bank():
    data = snapshot(balances={}, transactions=[tx("earned", "2026-05-22", "credit", "earned", 8)])
    assert not any(o.metrics["start"] == "2026-05-22" for o in run(data, eligible_categories=("credit",)).candidates)
    data["snapshot_rules"]["rules"]["credit"].update(usable_when="same_day", same_day_use_allowed=True)
    assert friday(run(data, eligible_categories=("credit",))).metrics["state"] == "Feasible"
    data["snapshot_rules"]["rules"]["credit"]["enabled"] = False
    assert not run(data, eligible_categories=("credit",)).candidates


def test_ineffective_fmla_and_overtime_do_not_reduce_hours():
    entries = [
        tx("void", "2026-05-22", "annual", "used", 8, void=True),
        tx("denied", "2026-05-22", "annual", "used", 8, status="denied"),
        tx("fmla", "2026-05-22", "fmla", "used", 8),
        tx("ot", "2026-05-22", "overtime", "used", 8),
    ]
    option = friday(run(snapshot(transactions=entries)))
    assert option.metrics["existing_hours"] == 0
    assert option.metrics["additional_hours"] == 8


def test_explicit_lot_booking_is_not_reused():
    entries = [
        lot("bank", hours=8, earned="2026-05-01", deadline="2026-05-26"),
        tx("reserved", "2026-05-26", "comp", "used", 8, earned_transaction_id="bank"),
    ]
    data = snapshot(balances={}, transactions=entries)
    assert not any(o.metrics["start"] == "2026-05-22" for o in run(data, eligible_categories=("comp",)).candidates)
