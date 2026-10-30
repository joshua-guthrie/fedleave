"""Independent deadline arithmetic, dated funding, strategy and isolation contracts."""

from copy import deepcopy
from dataclasses import asdict
from datetime import date

import pytest

from fedleave.budget import BudgetParameters, budget
from fedleave.planning import project
from leave_year_support import tx
from test_forecast import source

TODAY = date(2026, 11, 1)


def run(snapshot=None, **values):
    snapshot = snapshot if snapshot is not None else source(balances={"annual": 288})
    params = BudgetParameters(**dict(cutoff="2026-11-01", horizon=snapshot["leave_year_end"], **values))
    return budget(snapshot, params, today=TODAY)


def lot(key, category="comp", hours=16, earned="2026-10-01", deadline="2026-11-04"):
    row = tx(key, earned, category, "earned", hours)
    row["expiration_date"] = deadline
    return row


def deadline(result, key):
    return next(r for r in result.deadlines if r["id"] == key)


def test_annual_no_double_scheduled_subtraction_and_default_no_eligibility():
    snapshot = source(balances={"annual": 288}, transactions=[tx("booked", "2026-11-05", "annual", "used", 16)])
    result = run(snapshot)
    row = deadline(result, "annual-cap")
    assert row["required_hours"] == 32
    assert row["scheduled_hours"] == 16
    assert row["pre_cap_balance"] == 272
    assert result.suggestions == ()
    assert result.state == "Infeasible"
    result = run(snapshot, eligible_categories=("annual",))
    assert result.required_hours == 32
    assert result.allocated_hours == 32
    assert deadline(result, "annual-cap")["after_required_hours"] == 0
    assert result.state == "Feasible"


def test_two_lots_compete_for_24_hours_and_recompute_residual():
    result = run(source(balances={}, transactions=[lot("a"), lot("b")]), eligible_categories=("comp",))
    assert result.required_hours == 32
    assert result.allocated_hours == 24
    assert result.unallocated_hours == 8
    assert result.first_infeasible_deadline["shortfall_hours"] == 8
    assert sum(r["after_required_hours"] or 0 for r in result.deadlines) == 8
    assert result.state == "Partially feasible"
    assert all(r["suggested_hours"] <= (r["work_hours"] or 0) for r in result.dates)


def test_linked_usage_protects_only_its_lot_and_after_expiry_protects_none():
    booked = tx("booked", "2026-11-03", "comp", "used", 8)
    booked["earned_transaction_id"] = "b"
    late = tx("late", "2026-11-05", "comp", "used", 8)
    late["earned_transaction_id"] = "a"
    result = run(source(balances={}, transactions=[lot("a"), lot("b"), booked, late]))
    assert deadline(result, "a")["scheduled_hours"] == 0
    assert deadline(result, "a")["required_hours"] == 16
    assert deadline(result, "b")["scheduled_hours"] == 8
    assert deadline(result, "b")["required_hours"] == 8
    assert any(w.code == "CONFLICTING_CARRYOVER" for w in result.warnings)


def test_unlinked_usage_allocated_once_fifo():
    result = run(source(balances={}, transactions=[lot("a"), lot("b"), tx("booked", "2026-11-03", "comp", "used", 20)]))
    assert deadline(result, "a")["scheduled_hours"] == 16
    assert deadline(result, "b")["scheduled_hours"] == 4
    assert sum(r["required_hours"] or 0 for r in result.deadlines) == 12


def test_future_lot_earned_date_and_original_snapshot_never_modified():
    snapshot = source(balances={}, transactions=[lot("future", earned="2026-11-03")])
    original = deepcopy(snapshot)
    result = run(snapshot, eligible_categories=("comp",), strategy="earliest")
    assert deadline(result, "future")["remaining_at_cutoff"] == 0
    assert all(r["date"] >= "2026-11-03" for r in result.suggestions)
    assert snapshot == original
    assert asdict(result) == asdict(run(snapshot, eligible_categories=("comp",), strategy="earliest"))
    shared = project(snapshot, result.scenario, today=TODAY)
    assert shared.daily == result.after.daily
    assert shared.categories == result.after.categories


@pytest.mark.parametrize("strategy", ["even", "earliest", "latest", "weighted"])
def test_strategies_keep_raw_demand_and_reconcile(strategy):
    result = run(eligible_categories=("annual",), strategy=strategy)
    assert result.required_hours == 48
    assert result.allocated_hours == 48
    assert sum(r["suggested_hours"] for r in result.periods) == 48
    assert sum(r["suggested_hours"] for r in result.dates) == 48
    assert all(r["hours"] % 0.25 == 0 for r in result.suggestions)


def test_strategy_dates_differ_and_even_periods_are_equal():
    snapshot = source(balances={"annual": 280})
    # Exactly five full periods remain after this cutoff.
    values = dict(cutoff="2026-10-21", horizon=snapshot["leave_year_end"], eligible_categories=("annual",))
    results = {
        s: budget(snapshot, BudgetParameters(strategy=s, **values), today=TODAY)
        for s in ("even", "earliest", "latest", "weighted")
    }
    assert [r["suggested_hours"] for r in results["even"].periods] == [8] * 5
    assert results["earliest"].suggestions[0]["date"] == "2026-10-22"
    assert results["latest"].suggestions[0]["date"] == snapshot["leave_year_end"]
    assert results["even"].suggestions != results["earliest"].suggestions


def test_outside_horizon_past_and_unknown_opening_are_separate():
    snapshot = source(
        balances={"comp": 5}, transactions=[lot("outside", deadline="2027-02-01"), lot("old", deadline="2026-10-31")]
    )
    result = run(snapshot, eligible_categories=("comp",))
    assert deadline(result, "outside")["required_hours"] is None
    assert deadline(result, "outside")["status"] == "Outside current horizon"
    assert deadline(result, "old")["required_hours"] == 0
    assert deadline(result, "comp-unknown-opening")["required_hours"] is None
    assert result.state == "Unknown/unsupported"


def test_credit_timeline_counts_loss_once_and_transfer_matches():
    snapshot = source(balances={"credit": 40})
    result = run(snapshot, eligible_categories=("credit",), strategy="earliest")
    caps = [r for r in result.deadlines if r["category"] == "credit"]
    assert sum(r["required_hours"] for r in caps) == 16
    assert sum(r["after_required_hours"] for r in caps) == 0
    assert result.allocated_hours == 16
    assert project(snapshot, result.scenario, today=TODAY).daily == result.after.daily
    assert result.after.assumptions["scenario_assumptions"]["budget_credit_caps"]


def test_unsupported_credit_does_not_disable_annual():
    snapshot = source(balances={"annual": 248, "credit": 40})
    snapshot["snapshot_rules"]["rules"]["credit"]["expires"] = True
    result = run(snapshot, eligible_categories=("annual", "credit"))
    assert deadline(result, "annual-cap")["allocated_hours"] == 8
    assert deadline(result, "credit-policy")["required_hours"] is None
    assert any(w.code == "UNSUPPORTED_CREDIT_CAP" for w in result.warnings)


def test_six_actual_periods_average_and_partial_current_period():
    snapshot = source(balances={"annual": 288})
    cutoff = snapshot["pay_periods"][19]["end_date"]
    result = budget(snapshot, BudgetParameters(cutoff, snapshot["leave_year_end"]), today=TODAY)
    annual = deadline(result, "annual-cap")
    assert annual["periods_remaining"] == 6
    assert annual["average_hours_per_period"] == 8
    result = budget(snapshot, BudgetParameters("2026-10-28", snapshot["leave_year_end"]), today=TODAY)
    assert result.periods[0]["partial_current"] is True


def test_cutoff_on_deadline_has_no_opportunities_or_division_by_zero():
    result = run(source(balances={}, transactions=[lot("due", deadline="2026-11-01")]), eligible_categories=("comp",))
    row = deadline(result, "due")
    assert row["required_hours"] == 16
    assert row["periods_remaining"] == 0
    assert row["average_hours_per_period"] is None
    assert result.state == "Infeasible"
    assert result.first_infeasible_deadline["available_hours"] == 0


def test_nonstandard_workdays_lunch_observed_holiday_and_weekend_deadline():
    snapshot = source(balances={}, transactions=[lot("due", hours=16, deadline="2026-11-08")])
    defaults = snapshot["snapshot_rules"]["defaults"]
    defaults.update(
        normal_workdays=["tue", "thu"],
        workday_start="08:00",
        workday_end="15:00",
        lunch_start="12:00",
        lunch_end="13:00",
    )
    snapshot["snapshot_rules"]["holidays"]["enabled"] = True
    snapshot["calculation_context"].update(holiday_coverage=[2026], holidays=[{"observed_date": "2026-11-05"}])
    result = run(snapshot, eligible_categories=("comp",), strategy="latest")
    assert {r["date"] for r in result.suggestions} == {"2026-11-03"}
    assert result.allocated_hours == 6
    assert deadline(result, "due")["after_required_hours"] == 10


def test_even_redistributes_and_weighted_uses_remaining_period_capacity():
    snapshot = source(balances={"annual": 280})
    # Last two periods: first has only 8 hours remaining, second has 112.
    cutoff = snapshot["pay_periods"][-3]["end_date"]
    period = snapshot["pay_periods"][-2]
    from datetime import timedelta

    start = date.fromisoformat(period["start_date"])
    snapshot["transactions"] = [
        tx(f"busy-{i}", (start + timedelta(days=i)).isoformat(), "sick", "used", 8) for i in range(13)
    ]
    values = dict(cutoff=cutoff, horizon=snapshot["leave_year_end"], eligible_categories=("annual",))
    even = budget(snapshot, BudgetParameters(strategy="even", **values), today=TODAY)
    assert [r["suggested_hours"] for r in even.periods] == [8, 32]
    weighted = budget(snapshot, BudgetParameters(strategy="weighted", **values), today=TODAY)
    assert [r["suggested_hours"] for r in weighted.periods] == [2.75, 37.25]


def test_reserve_and_future_scheduled_use_prevent_early_overspend():
    snapshot = source(
        balances={"annual": 20},
        transactions=[
            tx("future-earn", "2026-12-01", "annual", "earned", 260),
            tx("booking", "2026-12-02", "annual", "used", 8),
        ],
    )
    result = run(snapshot, eligible_categories=("annual",), strategy="earliest", reserves={"annual": 16})
    assert result.required_hours == 32
    assert sum(r["hours"] for r in result.suggestions if r["date"] < "2026-12-01") == 4
    assert all(r.scenario >= 16 for r in result.after.daily if r.category == "annual")


def test_deadline_priority_before_placement_strategy_and_dated_joint_bound():
    snapshot = source(
        balances={"annual": 256}, transactions=[lot("early", category="travel_comp", hours=16, deadline="2026-11-03")]
    )
    result = run(snapshot, eligible_categories=("annual", "travel_comp"), strategy="latest")
    assert result.suggestions[0]["category"] == "travel_comp"
    assert sum(r["hours"] for r in result.suggestions if r["category"] == "travel_comp") == 16
    future = source(balances={}, transactions=[lot("a", earned="2026-11-04"), lot("b", earned="2026-11-04")])
    result = run(future, eligible_categories=("comp",))
    due = next(r for r in result.cumulative if r["deadline"] == "2026-11-04")
    assert due["work_capacity_hours"] == 24
    assert due["dated_capacity_bound_hours"] == 8
    assert due["joint_capacity_shortfall_hours"] == 24


def test_disabled_award_expiry_extensions_warn_and_known_disposal():
    award = lot("award", category="time_off_award", hours=8)
    extended = lot("extended", deadline="2026-11-08")
    extended.update(expiration_extension_reason="Approved extension", original_expiration_date="2026-11-04")
    payout = tx("payout", "2026-11-02", "comp", "paid_out", 4, earned_transaction_id="extended")
    snapshot = source(balances={}, transactions=[award, extended, payout])
    snapshot["snapshot_rules"]["rules"]["time_off_award"]["expires"] = False
    snapshot["snapshot_rules"]["rules"]["comp"].update(allow_extension=True, expiration_action="warn")
    result = run(snapshot)
    assert deadline(result, "award")["required_hours"] == 0
    row = deadline(result, "extended")
    assert row["outcome"] == "warn"
    assert row["required_hours"] == 12
    assert row["other_disposals"] == 4
    assert row["deadline_derivation"] == "Stored extension"


def test_midyear_horizon_missing_periods_and_unknown_holidays_are_explicit():
    snapshot = source(balances={"annual": 288})
    result = budget(snapshot, BudgetParameters("2026-06-30", "2026-07-31"), today=TODAY)
    assert deadline(result, "annual-cap")["status"] == "Outside current horizon"
    assert deadline(result, "annual-cap")["required_hours"] is None
    snapshot["pay_periods"].pop()
    result = run(snapshot, eligible_categories=("annual",))
    assert result.state == "Unknown/unsupported"
    assert any(w.code == "INCOMPLETE_PAY_PERIODS" for w in result.warnings)
    assert all(r["date"] <= snapshot["pay_periods"][-1]["end_date"] for r in result.suggestions)
    snapshot = source(balances={"annual": 288})
    snapshot["snapshot_rules"]["holidays"]["enabled"] = True
    result = run(snapshot, eligible_categories=("annual",))
    assert result.state == "Unknown/unsupported"
    assert deadline(result, "annual-cap")["usable_work_hours"] is None
    assert not result.suggestions


def test_increment_residuals_malformed_policy_and_no_need_states():
    snapshot = source(balances={}, transactions=[lot("odd", hours=8.1)])
    snapshot["snapshot_rules"]["defaults"]["time_increment_hours"] = 0.5
    result = run(snapshot, eligible_categories=("comp",))
    assert result.allocated_hours == 8
    assert deadline(result, "odd")["after_required_hours"] == pytest.approx(0.1)
    assert run(source(balances={})).state == "No additional use required"
    snapshot["transactions"].append(tx("bad", "2026-11-02", "comp", "used", 2, status="nonsense"))
    result = run(snapshot, eligible_categories=("comp",))
    assert deadline(result, "comp-policy")["required_hours"] is None
    assert result.state == "Unknown/unsupported"


def test_credit_early_use_affects_later_cap_and_no_double_known_disposal():
    snapshot = source(balances={"credit": 40}, transactions=[tx("new-credit", "2026-11-22", "credit", "earned", 20)])
    result = run(snapshot, eligible_categories=("credit",), strategy="earliest")
    assert result.required_hours == 36
    assert result.allocated_hours == 36
    assert all((r["after_required_hours"] or 0) == 0 for r in result.deadlines)
    snapshot = source(
        balances={"credit": 40}, transactions=[tx("already-forfeit", "2026-11-05", "credit", "forfeited", 16)]
    )
    assert run(snapshot).required_hours == 0


def test_credit_next_day_and_next_period_constraints():
    snapshot = source(balances={}, transactions=[tx("credit", "2026-11-03", "credit", "earned", 40)])
    result = run(snapshot, eligible_categories=("credit",), strategy="earliest")
    assert all(r["date"] >= "2026-11-04" for r in result.suggestions)
    snapshot["snapshot_rules"]["rules"]["credit"]["same_pay_period_use_allowed"] = False
    result = run(snapshot, eligible_categories=("credit",), strategy="earliest")
    assert not result.suggestions  # Excess expires before these earnings become usable.
    assert result.unallocated_hours == 16


def test_capacity_weights_use_work_capacity_even_when_demand_is_small():
    from datetime import timedelta

    snapshot = source(balances={"annual": 244})
    cutoff = snapshot["pay_periods"][-3]["end_date"]
    period = snapshot["pay_periods"][-2]
    start = date.fromisoformat(period["start_date"])
    snapshot["transactions"] = [
        tx(f"busy-{i}", (start + timedelta(days=i)).isoformat(), "sick", "used", 8 if i < 13 else 6) for i in range(14)
    ]
    result = budget(
        snapshot,
        BudgetParameters(cutoff, snapshot["leave_year_end"], strategy="weighted", eligible_categories=("annual",)),
        today=TODAY,
    )
    # Two hours versus 112, not two versus 56 (the demand-capped daily sum).
    assert [r["suggested_hours"] for r in result.periods] == [0, 4]


def test_payout_policy_is_identified_without_claiming_automatic_forfeiture():
    snapshot = source(balances={"annual": 248}, transactions=[lot("payout-lot")])
    snapshot["snapshot_rules"]["rules"]["comp"]["expiration_action"] = "payout"
    result = run(snapshot, eligible_categories=("annual", "comp"))
    row = deadline(result, "comp-policy")
    assert row["required_hours"] is None
    assert "payout" in row["outcome"]
    assert "Unsupported" in row["outcome"]
    assert deadline(result, "annual-cap")["allocated_hours"] == 8
    assert any(a.get("id") == "payout-lot" for a in result.audit)


def test_funding_on_proposed_day_cannot_use_an_already_negative_bank():
    snapshot = source(balances={"annual": -8}, transactions=[tx("future-earn", "2026-12-01", "annual", "earned", 280)])
    result = run(snapshot, eligible_categories=("annual",), strategy="earliest")
    assert all(r["date"] >= "2026-12-01" for r in result.suggestions)
    assert result.allocated_hours == 32


def test_failed_funding_audit_explains_balance_date_and_reserve_threshold():
    snapshot = source(balances={"annual": 20}, transactions=[tx("earn", "2026-12-01", "annual", "earned", 260)])
    result = run(snapshot, eligible_categories=("annual",), strategy="earliest", reserves={"annual": 16})
    failures = [a for a in result.audit if a["section"] == "Dated funding check"]
    assert failures
    assert any(
        a["code"] == "DATED_BALANCE_OR_RESERVE" and a["check_date"] < "2026-12-01" and a["minimum_allowed"] == 16
        for a in failures
    )
    assert all(
        a["candidate_closing_balance"] < a["minimum_allowed"]
        for a in failures
        if a["code"] == "DATED_BALANCE_OR_RESERVE"
    )


def test_malformed_credit_records_keep_risk_unknown_and_other_categories_usable():
    snapshot = source(
        balances={"annual": 248, "credit": 40},
        transactions=[tx("bad-credit", "2026-11-02", "credit", "used", 2, status="unsupported")],
    )
    result = run(snapshot, eligible_categories=("annual", "credit"))
    assert result.state == "Unknown/unsupported"
    assert deadline(result, "credit-policy")["required_hours"] is None
    assert deadline(result, "annual-cap")["allocated_hours"] == 8
