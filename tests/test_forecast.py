"""Independent arithmetic, coverage, allocation and isolation contracts for #121."""

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import date, timedelta

import pytest

from fedleave.config import Config
from fedleave.forecast import ForecastParameters, allocate_demand, forecast, percentile, retrospective_check
from fedleave.history import confirm_coverage, coverage_status, prepare_history, represented_periods
from fedleave.payperiods import generate_pay_periods
from fedleave.planning import new_scenario, project
from leave_year_support import tx

TODAY = date(2026, 6, 30)


def source(year=2026, *, start=None, count=26, transactions=(), balances=None):
    start = start or f"{year}-01-01"
    config = Config().model_dump()
    config["defaults"].update(
        annual_leave_accrual_hours=0,
        sick_leave_accrual_hours=0,
        normal_workdays=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    )
    config["holidays"]["enabled"] = False
    return {
        "leave_year": year,
        "leave_year_start": start,
        "leave_year_end": (date.fromisoformat(start) + timedelta(days=count * 14 - 1)).isoformat(),
        "pay_period_count": count,
        "pay_periods": generate_pay_periods(date.fromisoformat(start), count),
        "annual_leave_accrual_hours": 0,
        "sick_leave_accrual_hours": 0,
        "starting_balances": balances if balances is not None else {"annual": 100, "sick": 100},
        "snapshot_rules": config,
        "transactions": list(transactions),
        "calculation_context": {"data_store": "test-store", "backend": "test-backend"},
    }


def references(hours=(16, 24, 32, 40, 40), category="annual"):
    return {
        year: source(year, transactions=[tx(f"used-{year}", f"{year}-07-15", category, "used", value)])
        for year, value in zip(range(2021, 2026), hours, strict=False)
    }


def confirmations(history):
    return tuple(row for snapshot in history.values() for row in confirm_coverage(snapshot))


def params(**values):
    return ForecastParameters(**{"cutoff": "2026-06-30", "horizon": "2026-07-31", **values})


def run(target=None, history=None, coverage=None, **values):
    target = target if target is not None else source()
    history = history if history is not None else references()
    return forecast(
        target, history, confirmations(history) if coverage is None else coverage, params(**values), today=TODAY
    )


def summary(result, scenario="typical", category="annual"):
    return next(row for row in result.scenarios[scenario].summaries if row["category"] == category)


def test_double_counting_32_40_24_and_48_examples():
    target = source(transactions=[tx("booked", "2026-07-12", "annual", "used", 24)])
    result = run(target)
    typical, higher = summary(result), summary(result, "higher")
    assert (typical["estimated_total_hours"], higher["estimated_total_hours"]) == (32, 40)
    assert (typical["additional_estimated_hours"], higher["additional_estimated_hours"]) == (8, 16)
    assert (typical["allocated_horizon_balance"], higher["allocated_horizon_balance"]) == (68, 60)
    assert summary(result, "scheduled")["horizon_balance"] == 76
    target["transactions"][0]["hours"] = 48
    result = run(target)
    for name in ("typical", "higher"):
        assert summary(result, name)["additional_estimated_hours"] == 0
        assert summary(result, name)["horizon_balance"] == 52
        assert result.scenarios[name].allocations == ()


def test_categories_and_months_do_not_offset_one_another():
    history = references()
    for year, snapshot in history.items():
        snapshot["transactions"].extend(
            [
                tx(f"sick-{year}", f"{year}-07-10", "sick", "used", 8),
                tx(f"aug-{year}", f"{year}-08-10", "annual", "used", 16),
            ]
        )
    target = source(transactions=[tx("large", "2026-07-12", "annual", "used", 48)])
    result = run(target, history, categories=("annual", "sick"), horizon="2026-08-31")
    monthly = result.scenarios["typical"].monthly
    assert next(r for r in monthly if r["category"] == "annual" and r["month"] == 7)["additional_estimated_hours"] == 0
    assert next(r for r in monthly if r["category"] == "annual" and r["month"] == 8)["additional_estimated_hours"] == 16
    assert next(r for r in monthly if r["category"] == "sick" and r["month"] == 7)["additional_estimated_hours"] == 8


def test_percentiles_are_linear_and_keep_unrounded_values():
    assert percentile([10, 20, 30, 40], 0.5) == 25
    assert percentile([10, 20, 30, 40], 0.8) == pytest.approx(34)
    assert percentile([1, 2], 0.8) == 1.8
    assert percentile([], 0.8) is None


def test_unknown_coverage_is_missing_and_confirmed_zero_use_is_zero():
    history = references((0, 0, 0))
    missing = run(history=history, coverage=())
    assert missing.scenarios["typical"].projection is None
    assert summary(missing)["estimated_total_hours"] is None
    assert summary(missing)["horizon_balance"] is None
    confirmed = run(history=history)
    assert summary(confirmed)["estimated_total_hours"] == 0
    assert summary(confirmed)["horizon_balance"] == 100
    assert summary(confirmed)["allocation_complete"]
    assert all(row["hours"] == 0 for row in confirmed.scenarios["typical"].monthly[0]["per_year_rates"])


def test_scheduled_only_is_exactly_shared_engine_even_without_history():
    target = source(transactions=[tx("later", "2026-07-14", "annual", "used", 8)])
    result = run(target, history={})
    direct = project(target, new_scenario(target, today=TODAY, cutoff="2026-06-30", horizon="2026-07-31"), today=TODAY)
    actual = result.scenarios["scheduled"].projection
    assert actual.daily == direct.daily
    assert actual.categories == direct.categories
    assert actual.capacity == direct.capacity


def test_partial_coverage_supports_seasonal_but_not_whole_year_fallback():
    history = references((16, 24, 32))
    coverage = []
    for snapshot in history.values():
        periods = represented_periods(snapshot)
        ids = [
            p["period_id"]
            for p in periods
            if p["start"] <= f"{snapshot['leave_year']}-07-31" and p["end"] >= f"{snapshot['leave_year']}-07-01"
        ]
        coverage.extend(confirm_coverage(snapshot, ids))
    result = run(history=history, coverage=coverage)
    row = result.scenarios["typical"].monthly[0]
    assert row["estimator"] == "Calendar-month seasonal"
    assert row["estimated_total_hours"] == 24
    assert row["eligible_fallback_years"] == []
    limited = run(history=history, coverage=coverage, excluded_years=(2021,))
    assert summary(limited)["estimated_total_hours"] is None


def test_fallback_uses_its_own_population_and_reports_limited_history():
    history = references((16, 24, 32, 40))
    for year in (2021, 2022):
        snapshot = history[year]
        snapshot["snapshot_rules"]["holidays"]["enabled"] = True
        snapshot["calculation_context"].update(
            holiday_coverage=[year],
            holidays=[{"observed_date": f"{year}-07-{day:02d}"} for day in range(1, 32)],
        )
    result = run(history=history)
    row = result.scenarios["typical"].monthly[0]
    assert row["estimator"] == "Whole-year fallback"
    assert row["eligible_seasonal_years"] == [2023, 2024]
    assert row["source_years"] == [2021, 2022, 2023, 2024]
    assert row["observation_count"] == 4
    assert not row["limited_history"]
    limited = run(history=history, reference_years=(2023, 2024))
    assert limited.scenarios["typical"].monthly[0]["limited_history"]
    assert any(w["code"] == "LIMITED_HISTORY" for w in limited.warnings)


def test_material_source_change_requires_confirmation_but_display_changes_do_not():
    snapshot = source(2025, transactions=[tx("id", "2025-07-15", "annual", "used", 8)])
    coverage = confirm_coverage(snapshot)
    snapshot["transactions"][0]["description"] = "display only"
    assert all(row["confirmed"] for row in coverage_status(snapshot, coverage)[0])
    snapshot["transactions"][0]["hours"] = 16
    states = coverage_status(snapshot, coverage)[0]
    assert len([row for row in states if row["state"] == "Stale"]) == 1
    assert not prepare_history(snapshot, source(), coverage, cutoff="2026-06-30").observation("annual")["eligible"]
    assert prepare_history(snapshot, source(), confirm_coverage(snapshot), cutoff="2026-06-30").observation("annual")[
        "eligible"
    ]
    assert not any(row["confirmed"] for row in coverage_status(snapshot, ())[0])


def test_competing_categories_share_capacity_proportionally_and_deterministically():
    result = allocate_demand({"annual": 32, "sick": 24}, {"2026-07-01": 8, "2026-07-02": 8, "2026-07-03": 24}, 0.25)
    assert sum(row["hours"] for row in result) == 40
    assert sum(row["hours"] for row in result if row["category"] == "annual") == 22.75
    assert sum(row["hours"] for row in result if row["category"] == "sick") == 17.25
    assert result == allocate_demand(
        {"sick": 24, "annual": 32}, {"2026-07-03": 24, "2026-07-02": 8, "2026-07-01": 8}, 0.25
    )
    for day, capacity in {"2026-07-01": 8, "2026-07-02": 8, "2026-07-03": 24}.items():
        assert sum(row["hours"] for row in result if row["date"] == day) <= capacity


def test_single_category_preserves_other_scheduled_absence_capacity_and_negative_balances():
    target = source(balances={"annual": 24}, transactions=[tx("sick-booking", "2026-07-01", "sick", "used", 8)])
    result = run(target, references((40, 40, 40)), horizon="2026-07-06")
    # Six-day target exposure is 48 hours; estimates scale July's 248-hour source.
    assert all(row["category"] == "annual" for row in result.scenarios["typical"].allocations)
    assert all(row["date"] > "2026-07-01" for row in result.scenarios["typical"].allocations)
    target["starting_balances"]["annual"] = 1
    negative = run(target, references((40, 40, 40)), horizon="2026-07-06")
    assert summary(negative)["minimum_balance"] < 0
    assert summary(negative)["earliest_negative_date"]


def test_incomplete_curve_and_hypothetical_full_demand_are_separate():
    history = references((400, 400, 400))
    target = source()
    result = run(target, history, horizon="2026-07-03")
    row = summary(result)
    assert row["allocated_hours"] == 24
    assert row["unallocated_hours"] == pytest.approx(400 * 3 / 31 - 24)
    assert row["allocated_horizon_balance"] == 76
    assert row["hypothetical_full_demand_balance"] == pytest.approx(100 - 400 * 3 / 31)
    assert not row["allocation_complete"]
    daily = [day for day in result.scenarios["typical"].projection.daily if day.category == "annual"]
    assert daily[-1].scenario == row["allocated_horizon_balance"]
    assert all(a["date"] <= "2026-07-03" for a in result.scenarios["typical"].allocations)
    target["snapshot_rules"]["rules"]["annual"]["expires"] = True
    uncertain = run(target, history, horizon="2026-07-03")
    assert summary(uncertain)["hypothetical_full_demand_balance"] is None


def test_ineffective_statuses_and_future_history_are_never_training_data():
    history = references((32, 32, 32))
    for year, snapshot in history.items():
        snapshot["transactions"].extend(
            tx(f"{status}-{year}", f"{year}-07-10", "annual", "used", 100, status=status)
            for status in ("denied", "cancelled")
        )
    target = source(transactions=[tx("denied", "2026-07-12", "annual", "used", 24, status="denied")])
    result = run(target, history)
    assert summary(result)["scheduled_hours"] == 0
    assert summary(result)["estimated_total_hours"] == 32
    history[2026] = source(transactions=[tx("current", "2026-07-01", "annual", "used", 200, status="reconciled")])
    assert summary(run(history=history, reference_years=tuple(history)))["estimated_total_hours"] == 32
    assert next(row for row in run(history=history).history if row["year"] == 2026)["exclusion_reason"]


def test_confirmed_status_basis_unfinished_and_off_schedule_warnings():
    history = references((32, 32, 32))
    for year, snapshot in history.items():
        snapshot["transactions"][0]["status"] = "requested"
        snapshot["transactions"].append(tx(f"confirmed-{year}", f"{year}-07-14", "annual", "used", 8))
    assert summary(run(history=history))["estimated_total_hours"] == 40
    confirmed = run(history=history, status_basis="confirmed")
    assert summary(confirmed)["estimated_total_hours"] == 8
    assert any(w["code"] == "UNRESOLVED_RECORDED_STATUS" for w in confirmed.warnings)
    assert confirmed.assumptions["historical_statuses"] == ("worked", "submitted", "certified", "reconciled")


def test_year_bounds_gaps_and_27_periods():
    snapshot = source(2025, count=27)
    assert len(represented_periods(snapshot)) == 27
    snapshot["pay_periods"][2]["start_date"] = "2025-01-30"
    with pytest.raises(ValueError, match="gaps"):
        represented_periods(snapshot)


def test_both_january_edges_are_combined_for_rates_but_target_segments_stay_separate():
    history = {}
    for year, start in ((2023, "2023-01-08"), (2024, "2024-01-07"), (2025, "2025-01-05")):
        history[year] = source(
            year,
            start=start,
            transactions=[
                tx(f"jan-first-{year}", f"{year}-01-10", "annual", "used", 8),
                tx(f"jan-last-{year}", f"{year + 1}-01-02", "annual", "used", 8),
            ],
        )
    target = source(start="2026-01-04")
    result = run(target, history, cutoff="2026-12-31", horizon="2027-01-02")
    row = result.scenarios["typical"].monthly[0]
    assert (row["start"], row["end"], row["exposure"]) == ("2027-01-01", "2027-01-02", 16)
    assert row["estimated_total_hours"] == pytest.approx(16 / 15)
    observations = row["seasonal_observations"]
    assert [o["exposure"] for o in observations] == [240, 232, 240]
    assert all(len(o["transaction_ids"]) == 2 for o in observations)
    entire = run(target, history, cutoff="2026-01-04", horizon="2027-01-02")
    assert len([r for r in entire.scenarios["typical"].monthly if r["month"] == 1]) == 2


def test_leap_day_partial_month_and_observed_holidays_use_shared_calendar():
    history = {}
    for year in (2020, 2021, 2022):
        history[year] = source(year, transactions=[tx(str(year), f"{year}-02-14", "annual", "used", 8)])
    target = source(2024)
    target["snapshot_rules"]["holidays"]["enabled"] = True
    target["calculation_context"].update(holiday_coverage=[2024], holidays=[{"observed_date": "2024-02-29"}])
    result = forecast(
        target, history, confirmations(history), ForecastParameters("2024-02-27", "2024-02-29"), today=date(2024, 2, 27)
    )
    row = result.scenarios["typical"].monthly[0]
    assert row["exposure"] == 8
    assert all(a["date"] == "2024-02-28" for a in result.scenarios["typical"].allocations)
    assert summary(result)["additional_estimated_hours"] == pytest.approx(8 / 28)


def test_unknown_schedule_or_holidays_produces_missing_estimates_not_zero_exposure():
    target = source()
    target["snapshot_rules"]["holidays"]["enabled"] = True
    result = run(target)
    assert summary(result)["estimated_total_hours"] is None
    assert result.scenarios["typical"].monthly[0]["exposure"] is None
    assert any(w["code"] == "MISSING_HOLIDAY_CONTEXT" for w in result.warnings)


def test_current_schedule_is_explicit_and_off_schedule_hours_remain_in_usage():
    history = references((8, 8, 8))
    target = source()
    target["snapshot_rules"]["defaults"]["normal_workdays"] = ["mon"]
    result = run(target, history)
    assert all(
        "currently configured work schedule" in text for text in result.assumptions["historical_schedules"].values()
    )
    assert any(w["code"] == "OFF_SCHEDULE_HISTORY" for w in result.warnings)
    assert all(row["hours"] == 8 for row in result.scenarios["typical"].monthly[0]["seasonal_observations"])


def test_changed_accrual_dates_preserve_earlier_negative_then_recovery():
    target = source(balances={"annual": 0})
    target["pay_periods"] = [
        {"pay_period_number": 14, "start_date": "2026-07-01", "end_date": "2026-07-14", "accrual_date": "2026-07-08"}
    ]
    target["annual_leave_accrual_hours"] = 8
    # History eligibility is needed for references, not a synthetic target's PP inventory.
    result = run(target, references((4, 4, 4)), horizon="2026-07-08")
    row = summary(result)
    assert row["minimum_balance"] < 0
    assert row["horizon_balance"] > 0
    assert row["earliest_negative_date"] < "2026-07-08"
    assert any(
        event.timing == "Synthetic accrual" and event.date == "2026-07-08"
        for event in result.scenarios["typical"].projection.events
    )


def test_retrospective_check_trains_only_earlier_years_and_reports_both_errors():
    history = references((16, 24, 32, 40, 40))
    original = deepcopy(history)
    result = retrospective_check(history, confirmations(history), 2025, today=TODAY, cutoffs=("2025-07-01",))
    assert len(result.rows) == 2
    for row in result.rows:
        assert set(row["source_years"]) == {2021, 2022, 2023, 2024}
        assert row["actual_hours"] == 40
        assert row["absolute_error"] == abs(row["estimated_future_hours"] - 40)
        assert row["whole_year_source_years"] == [2021, 2022, 2023, 2024]
    assert all(row["sample_count"] == 1 for row in result.summaries)
    assert result.rows[0]["estimated_future_hours"] < result.rows[1]["estimated_future_hours"]
    assert "do not reconstruct" in result.limitation
    assert history == original


def test_retrospective_missing_coverage_no_prior_training_and_zero_actual_are_explicit():
    history = references((0,))
    result = retrospective_check(history, confirmations(history), 2021, today=TODAY, cutoffs=("2021-07-01",))
    assert all(row["actual_hours"] == 0 for row in result.rows)
    assert all(row["estimated_future_hours"] is None for row in result.rows)
    assert all(row["sample_count"] == 0 and row["mean_absolute_error"] is None for row in result.summaries)
    missing = retrospective_check(history, (), 2021, today=TODAY, cutoffs=("2021-07-01",))
    assert all(row["actual_hours"] is None for row in missing.rows)
    with pytest.raises(ValueError, match="pay-period-end"):
        retrospective_check(history, (), 2021, today=TODAY, cutoffs=("2021-07-02",))


def test_ineffective_malformed_rows_are_excluded_before_historical_validation():
    history = references((32, 32, 32))
    for year, snapshot in history.items():
        snapshot["transactions"].extend(
            [
                tx(f"denied-{year}", "invalid", "annual", "used", float("nan"), status="denied"),
                tx(f"void-{year}", "2099-01-01", "annual", "used", 1000, void=True),
            ]
        )
    result = run(history=history)
    assert summary(result)["estimated_total_hours"] == 32
    assert not any(w["code"] == "INVALID_HISTORICAL_USAGE" for w in result.warnings)


def test_malformed_one_category_does_not_invent_zero_or_mask_other_category():
    history = references((32, 32, 32))
    history[2021]["transactions"].append(tx("bad", "2021-07-03", "annual", "used", float("nan")))
    result = run(history=history, categories=("annual", "sick"))
    annual = next(row for row in result.scenarios["typical"].monthly if row["category"] == "annual")
    assert annual["seasonal_observations"][0]["hours"] is None
    assert not annual["seasonal_observations"][0]["eligible"]
    assert summary(result, category="sick")["estimated_total_hours"] == 0
    assert any(w["code"] == "INVALID_HISTORICAL_USAGE" for w in result.warnings)


def test_unavailable_category_is_null_in_monthly_summary_and_daily_views():
    history = references((32, 32, 32))
    for year, snapshot in history.items():
        snapshot["transactions"].append(tx(f"bad-sick-{year}", f"{year}-07-03", "sick", "used", float("nan")))
    result = run(history=history, categories=("annual", "sick"))
    assert summary(result)["estimated_total_hours"] == 32
    assert summary(result, category="sick")["allocated_horizon_balance"] is None
    assert all(
        row["allocated_closing_balance"] is None
        for row in result.scenarios["typical"].monthly
        if row["category"] == "sick"
    )
    from fedleave_analytics.forecast_model import forecast_tables

    assert all(row["typical"] is None for row in forecast_tables(result, "sick")["Daily closing balances"][0])


def test_combined_forecasts_share_capacity_independently_and_do_not_cap_to_balances():
    target = source(balances={"annual": 0, "sick": 0})
    target["snapshot_rules"]["defaults"].update(workday_end="08:00", lunch_start="07:30", lunch_end="07:30")
    history = references((32, 32, 32))
    for year, snapshot in history.items():
        snapshot["transactions"].append(tx(f"sick-{year}", f"{year}-07-15", "sick", "used", 24))
    result = run(target, history, categories=("annual", "sick"))
    for scenario in ("typical", "higher"):
        rows = result.scenarios[scenario].allocations
        assert sum(row["hours"] for row in rows) == 31
        assert sum(row["hours"] for row in rows if row["category"] == "annual") == 17.75
        assert sum(row["hours"] for row in rows if row["category"] == "sick") == 13.25
        assert all(
            sum(row["hours"] for row in rows if row["date"] == f"2026-07-{day:02d}") <= 1 for day in range(1, 32)
        )
        assert summary(result, scenario)["minimum_balance"] < 0
        assert summary(result, scenario, "sick")["minimum_balance"] < 0
    assert result.scenarios["typical"].allocations != ()
    assert sum(row["hours"] for row in result.scenarios["higher"].allocations) == 31


def test_reserve_equality_zero_and_retrospective_reference_filter():
    result = run(reserves={"annual": 68})
    assert summary(result)["horizon_balance"] == 68
    assert summary(result)["first_reserve_breach"] is None
    assert summary(run(reserves={"annual": 0}))["first_reserve_breach"] is None
    history = references()
    check = retrospective_check(
        history, confirmations(history), 2025, today=TODAY, reference_years=(2024, 2025), cutoffs=("2025-07-01",)
    )
    assert all(row["source_years"] == [2024] for row in check.rows)


def test_yearend_unallocated_demand_does_not_fabricate_full_demand_cap_effects():
    history = references((4000, 4000, 4000))
    for year, snapshot in history.items():
        snapshot["transactions"][0]["date"] = f"{year}-12-15"
    target = source()
    result = run(target, history, cutoff="2026-12-01", horizon=target["leave_year_end"])
    row = summary(result)
    assert row["unallocated_hours"] > 0
    assert row["hypothetical_full_demand_balance"] is None
    assert "year-end" in row["full_demand_explanation"]


def test_forecast_is_immutable_deterministic_and_has_no_filesystem_capability(monkeypatch):
    target, history = source(), references()
    coverage = confirmations(history)
    before = deepcopy((target, history, coverage))

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure forecasts cannot access files")

    monkeypatch.setattr("builtins.open", forbidden)
    result = run(target, history, coverage)
    assert asdict(result) == asdict(run(target, history, coverage))
    assert (target, history, coverage) == before
    encoded = json.dumps(result.to_dict())
    assert "month-exposure-median-p80-v1" in encoded
    assert all(
        event.timing == "Estimated" for event in result.scenarios["typical"].projection.events if event.scenario_row_id
    )
    assert all(
        event.original_transaction_id is None
        for event in result.scenarios["typical"].projection.events
        if event.scenario_row_id
    )
    assert result.scenarios["typical"].projection.source == result.scenarios["scheduled"].projection.source
    assert result.scenarios["higher"].projection.capacity[1].baseline_scheduled == 0


@pytest.mark.parametrize(
    "values",
    [
        {"categories": ()},
        {"categories": ("overtime",)},
        {"status_basis": "all"},
        {"reserves": {"annual": float("nan")}},
    ],
)
def test_invalid_parameters(values):
    with pytest.raises(ValueError):
        run(**values)
