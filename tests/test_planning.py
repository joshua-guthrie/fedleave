"""Arithmetic, identity, provenance and nonmutation contracts for issue #120."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date

import pytest

from fedleave.config import Config
from fedleave.cross_year import seed_accruals
from fedleave.ledger import calculate_balances
from fedleave.planning import (
    PlanningValidationError,
    export_scenario,
    import_scenario,
    make_operation,
    new_scenario,
    project,
    scheduled_transactions,
    validate_scenario,
)

TODAY = date(2026, 7, 1)


def tx(id="scheduled", day="2026-07-15", category="annual", direction="used", hours=16, **extra):
    return {
        "id": id,
        "date": day,
        "category": category,
        "direction": direction,
        "hours": hours,
        "status": "approved",
        "source": "manual",
        **extra,
    }


def snapshot():
    config = Config().model_dump()
    config["holidays"]["enabled"] = False
    return {
        "leave_year": 2026,
        "leave_year_start": "2026-01-01",
        "leave_year_end": "2026-12-31",
        "annual_leave_accrual_hours": 8,
        "sick_leave_accrual_hours": 0,
        "starting_balances": {"annual": 100, "sick": 40},
        "snapshot_rules": config,
        "pay_periods": [
            {
                "pay_period_number": 14,
                "start_date": "2026-07-01",
                "end_date": "2026-07-14",
                "accrual_date": "2026-07-08",
            }
        ],
        "transactions": [tx()],
        "calculation_context": {"data_store": "test-store", "backend": "test-backend"},
    }


def scenario(source, **values):
    return new_scenario(source, today=TODAY, cutoff="2026-07-01", horizon="2026-07-31", **values)


def operation(source, **values):
    return make_operation(
        source,
        **{
            "row_id": "tentative",
            "operation": "add",
            "date": "2026-07-23",
            "category": "annual",
            "hours": 24,
            **values,
        },
    )


def category(result, key="annual"):
    return next(row for row in result.categories if row.category == key)


def test_acceptance_add_replace_remove_reset_and_no_mutation():
    source = snapshot()
    unchanged = deepcopy(source)
    empty = replace(scenario(source), reserves={"annual": 80})
    result = project(source, replace(empty, operations=(operation(source),)), today=TODAY)
    annual = category(result)
    assert annual.baseline.cutoff_balance == 100
    assert annual.baseline.horizon_balance == 92
    assert annual.scenario.horizon_balance == 68
    assert annual.scenario.first_reserve_breach == "2026-07-23"
    assert annual.scenario.reserve_shortfall == 12
    for action, expected in (("replace", 84), ("remove", 108)):
        op = operation(
            source,
            operation=action,
            original_ids=("scheduled",),
            hours=0 if action == "remove" else 24,
            date=None if action == "remove" else "2026-07-15",
            category=None if action == "remove" else "annual",
        )
        definition = replace(empty, operations=(op,))
        result = project(source, definition, today=TODAY)
        assert category(result).scenario.horizon_balance == expected
        assert result.operations[0].original_ids == ("scheduled",)
    reset = project(source, empty, today=TODAY)
    assert all(row.baseline == row.scenario for row in reset.categories)
    assert all(row.delta == 0 for row in reset.daily)
    assert source == unchanged
    assert project(source, empty, today=TODAY) == reset


def test_empty_scenario_matches_dated_canonical_balances_with_rates_and_existing_accruals():
    source = snapshot()
    source["annual_leave_accrual_hours"] = 4
    source["accrual_rate_changes"] = [{"category": "annual", "effective_date": "2026-07-20", "hours_per_pay_period": 6}]
    source["pay_periods"].append(
        {"pay_period_number": 15, "start_date": "2026-07-15", "end_date": "2026-07-28", "accrual_date": "2026-07-22"}
    )
    source["transactions"].append(tx("existing-accrual", "2026-07-08", "annual", "earned", 4, source="auto_accrual"))
    private = deepcopy(source)
    seed_accruals(private)
    result = project(source, scenario(source), today=TODAY)
    for point in result.daily:
        expected = calculate_balances(private, until_date=point.date)[point.category]
        assert point.baseline == expected
        assert point.scenario == expected
    assert category(result).baseline.horizon_balance == 94
    synthetic = [event for event in result.events if event.branch == "baseline" and event.timing == "Synthetic accrual"]
    assert len(synthetic) == 1
    assert synthetic[0].date == "2026-07-22"
    assert synthetic[0].hours == 6


def test_positive_final_balance_does_not_hide_earlier_negative_or_minimum():
    source = snapshot()
    source["starting_balances"]["annual"] = 0
    source["transactions"] = []
    result = project(
        source, replace(scenario(source), operations=(operation(source, date="2026-07-02", hours=4),)), today=TODAY
    )
    summary = category(result).scenario
    assert summary.horizon_balance == 4
    assert summary.earliest_negative_date == "2026-07-02"
    assert summary.negative_shortfall == 4
    assert summary.minimum_date == "2026-07-02"
    assert summary.minimum_balance == -4


@pytest.mark.parametrize("reserve,breach", [(92, None), (92.25, "2026-07-15"), (0, None)])
def test_reserve_equality_zero_and_partial_hours(reserve, breach):
    source = snapshot()
    result = project(source, replace(scenario(source), reserves={"annual": reserve}), today=TODAY)
    assert category(result).baseline.first_reserve_breach == breach
    half = operation(source, hours=0.25)
    assert (
        category(project(source, replace(scenario(source), operations=(half,)), today=TODAY)).scenario.horizon_balance
        == 91.75
    )


@pytest.mark.parametrize("hours", [0, -1, float("inf"), float("nan"), "oops", True, 0.1])
def test_invalid_scenario_hours_are_row_errors_not_a_negative_projection(hours):
    source = snapshot()
    definition = replace(scenario(source), operations=(operation(source, hours=hours),))
    with pytest.raises(PlanningValidationError) as error:
        project(source, definition, today=TODAY)
    assert error.value.errors[0]["row_id"] == "tentative"
    assert error.value.errors[0]["field"] == "hours"


@pytest.mark.parametrize("day", ["2026-07-01", "2026-06-30", "2027-01-01", "2026-7-2"])
def test_out_of_window_and_non_iso_tentative_dates(day):
    source = snapshot()
    with pytest.raises(PlanningValidationError):
        project(source, replace(scenario(source), operations=(operation(source, date=day),)), today=TODAY)


def test_reversed_horizon_rejected_and_future_year_default_is_clamped():
    source = snapshot()
    with pytest.raises(PlanningValidationError):
        new_scenario(source, today=TODAY, cutoff="2026-07-20", horizon="2026-07-19")
    assert new_scenario(source, today=date(2025, 1, 1)).cutoff == "2026-01-01"
    assert new_scenario(source, today=date(2027, 1, 1)).cutoff == "2026-12-31"


@pytest.mark.parametrize("extra", [{"void": True}, {"status": "denied"}, {"status": "cancelled"}])
def test_ineffective_originals_do_not_affect_baseline_or_become_replaceable(extra):
    source = snapshot()
    source["transactions"] = [tx(**extra)]
    result = project(source, scenario(source), today=TODAY)
    assert category(result).baseline.horizon_balance == 108
    assert not scheduled_transactions(source, "2026-07-01", "2026-07-31")
    with pytest.raises(PlanningValidationError):
        validate_scenario(
            source,
            replace(
                scenario(source), operations=(operation(source, operation="replace", original_ids=("scheduled",)),)
            ),
        )


def test_malformed_source_is_visible_and_unknown_rather_than_zero():
    source = snapshot()
    source["transactions"] = [tx(status="unrecognized")]
    result = project(source, scenario(source), today=TODAY)
    assert category(result).baseline.horizon_balance is None
    assert any(warning.code == "MALFORMED_SOURCE_RECORD" for warning in result.warnings)
    assert category(result, "sick").baseline.horizon_balance == 40


def test_conflicting_targets_synthetic_targets_and_atomic_multi_target_replacement():
    source = snapshot()
    original = operation(source, operation="replace", original_ids=("scheduled",))
    conflict = replace(original, row_id="second", operation="remove", hours=0, date=None, category=None)
    with pytest.raises(PlanningValidationError, match="already targeted"):
        validate_scenario(source, replace(scenario(source), operations=(original, conflict)))
    for targets in (("scheduled", "missing"), ("scenario:tentative",)):
        with pytest.raises(PlanningValidationError, match="missing"):
            validate_scenario(
                source,
                replace(scenario(source), operations=(operation(source, operation="replace", original_ids=targets),)),
            )
    assert category(project(source, scenario(source), today=TODAY)).scenario.horizon_balance == 92


def test_historical_accrual_and_non_absence_originals_cannot_be_replaced():
    source = snapshot()
    source["transactions"] += [
        tx("historical", "2026-06-01"),
        tx("accrual", "2026-07-20", direction="earned", source="auto_accrual"),
    ]
    for transaction_id in ("historical", "accrual"):
        with pytest.raises(PlanningValidationError):
            validate_scenario(
                source,
                replace(
                    scenario(source),
                    operations=(operation(source, operation="replace", original_ids=(transaction_id,)),),
                ),
            )


def test_same_day_capacity_is_cross_category_and_does_not_reschedule():
    source = snapshot()
    source["transactions"] = []
    one = operation(source, row_id="one", date="2026-07-06", hours=4)
    two = operation(source, row_id="two", date="2026-07-06", category="sick", hours=4)
    definition = replace(scenario(source), operations=(one, two))
    result = project(source, definition, today=TODAY)
    row = next(row for row in result.capacity if row.date == "2026-07-06")
    assert (row.work_hours, row.total_proposed_absence, row.excess_hours) == (8, 8, 0)
    result = project(
        source, replace(definition, operations=(replace(one, hours=8), replace(two, hours=8))), today=TODAY
    )
    row = next(row for row in result.capacity if row.date == "2026-07-06")
    assert row.excess_hours == 8
    assert row.tentative_by_category == {"annual": 8, "sick": 8}
    assert any(warning.code == "CAPACITY_CONFLICT" and warning.date == row.date for warning in result.warnings)
    assert {event.date for event in result.events if event.timing == "Tentative"} == {"2026-07-06"}


def test_configured_tour_workdays_holidays_and_scheduled_absence_capacity():
    source = snapshot()
    source["snapshot_rules"]["defaults"].update(workday_end="17:30", normal_workdays=["mon", "tue", "wed", "thu"])
    source["snapshot_rules"]["holidays"]["enabled"] = True
    source["calculation_context"].update(holiday_coverage=[2026], holidays=[{"observed_date": "2026-07-06"}])
    source["transactions"] = [tx("sick", "2026-07-07", "sick", hours=4)]
    op = operation(source, date="2026-07-07", hours=8)
    result = project(source, replace(scenario(source), operations=(op,)), today=TODAY)
    rows = {row.date: row for row in result.capacity}
    assert rows["2026-07-03"].work_hours == 0
    assert rows["2026-07-06"].work_hours == 0
    assert rows["2026-07-07"].work_hours == 10
    assert rows["2026-07-07"].remaining_capacity == 6
    assert rows["2026-07-07"].excess_hours == 2
    removal = operation(
        source, row_id="remove", operation="remove", original_ids=("sick",), date=None, category=None, hours=0
    )
    result = project(source, replace(scenario(source), operations=(op, removal)), today=TODAY)
    row = next(row for row in result.capacity if row.date == "2026-07-07")
    assert row.excess_hours == 0
    assert row.scenario_scheduled == 0


def test_missing_schedule_holiday_context_and_historical_cutoff_are_explicit():
    source = snapshot()
    source["snapshot_rules"].pop("defaults")
    source["snapshot_rules"]["holidays"]["enabled"] = True
    result = project(source, scenario(source), today=date(2026, 8, 1))
    assert all(row.work_hours is None for row in result.capacity)
    assert {"UNKNOWN_WORK_SCHEDULE", "MISSING_HOLIDAY_CONTEXT", "HISTORICAL_CUTOFF"} <= {
        warning.code for warning in result.warnings
    }


def test_past_planned_absence_remains_unresolved_recorded_through_cutoff():
    source = snapshot()
    source["transactions"].append(tx("past-planned", "2026-06-01", hours=2, status="requested"))
    result = project(source, scenario(source), today=TODAY)
    assert any(warning.code == "UNRESOLVED_RECORDED_STATUS" for warning in result.warnings)
    assert (
        next(event for event in result.events if event.original_transaction_id == "past-planned").timing
        == "Recorded Through Cutoff"
    )


def test_annual_carryover_only_at_actual_year_end_and_pre_cap_is_separate():
    source = snapshot()
    source["starting_balances"]["annual"] = 300
    source["transactions"] = []
    midyear = project(source, scenario(source), today=TODAY)
    assert category(midyear).scenario.annual_carryover is None
    year_end = project(source, replace(scenario(source), horizon="2026-12-31"), today=TODAY)
    annual = category(year_end).scenario
    assert (annual.annual_pre_cap_balance, annual.annual_carryover, annual.prospective_forfeiture) == (308, 240, 68)


def lot_source():
    source = snapshot()
    source["snapshot_rules"]["rules"]["comp"]["expiration_action"] = "expire"
    source["transactions"] = [
        tx("lot", "2026-07-01", "comp", "earned", 10, expiration_date="2026-07-15"),
        tx("comp-use", "2026-07-10", "comp", hours=4),
    ]
    return source


def test_scenario_recalculates_derived_disposal_without_double_counting():
    source = lot_source()
    source["transactions"].append(
        tx("old-disposal", "2026-07-16", "comp", "expired", 6, source="expiration-engine", earned_transaction_id="lot")
    )
    result = project(
        source,
        replace(scenario(source), operations=(operation(source, category="comp", date="2026-07-14", hours=2),)),
        today=TODAY,
    )
    disposals = [event for event in result.events if event.timing == "Synthetic expiration"]
    assert [(event.branch, event.hours) for event in disposals] == [("baseline", 6), ("scenario", 4)]
    assert category(result, "comp").scenario.horizon_balance == 0
    assert source["transactions"][-1]["hours"] == 6


def test_lot_order_spanning_expiry_boundary_extensions_and_explicit_links():
    source = lot_source()
    source["transactions"] = [
        tx("later", "2026-07-01", "comp", "earned", 4, expiration_date="2026-07-20"),
        tx("earlier", "2026-07-01", "comp", "earned", 3, expiration_date="2026-07-10"),
    ]
    op = operation(source, category="comp", date="2026-07-10", hours=5)
    result = project(source, replace(scenario(source), operations=(op,)), today=TODAY)
    tentative = [event for event in result.events if event.timing == "Tentative"]
    assert sorted((event.earned_transaction_id, event.hours) for event in tentative) == [("earlier", 3), ("later", 2)]
    linked = replace(op, hours=4, earned_transaction_id="later")
    result = project(source, replace(scenario(source), operations=(linked,)), today=TODAY)
    assert [(event.earned_transaction_id, event.hours) for event in result.events if event.timing == "Tentative"] == [
        ("later", 4)
    ]
    source["transactions"][1].update(expiration_date="2026-07-18", expiration_extension_reason="Approved extension")
    extended = replace(op, date="2026-07-15", hours=3, earned_transaction_id="earlier")
    result = project(source, replace(scenario(source), operations=(extended,)), today=TODAY)
    assert not [warning for warning in result.warnings if warning.row_id == "tentative"]


@pytest.mark.parametrize("use_date,earn_date", [("2026-07-16", "2026-07-01"), ("2026-07-02", "2026-07-10")])
def test_ineligible_lot_use_is_retained_with_explicit_warning(use_date, earn_date):
    source = lot_source()
    source["transactions"] = [tx("lot", earn_date, "comp", "earned", 10, expiration_date="2026-07-15")]
    result = project(
        source,
        replace(scenario(source), operations=(operation(source, category="comp", date=use_date, hours=2),)),
        today=TODAY,
    )
    assert any(
        warning.code == "MISSING_LOT_PROVENANCE" and warning.row_id == "tentative" for warning in result.warnings
    )
    assert any(event.timing == "Tentative" and event.date == use_date for event in result.events)


def test_unknown_opening_lots_and_unsupported_policy_have_null_metrics():
    source = snapshot()
    source["starting_balances"]["comp"] = 10
    source["snapshot_rules"]["rules"]["time_off_award"].update(expires=True, expiration_days_after_earned=None)
    source["transactions"].append(tx("award", "2026-07-02", "time_off_award", "earned", 4))
    result = project(source, scenario(source), today=TODAY)
    assert category(result, "comp").scenario.horizon_balance is None
    assert category(result, "time_off_award").scenario.horizon_balance is None
    assert any(lot.remaining_hours is None for lot in result.lots)
    assert {"MISSING_LOT_PROVENANCE", "UNSUPPORTED_CATEGORY_POLICY"} <= {warning.code for warning in result.warnings}
    assert category(result).scenario.horizon_balance == 92


def test_json_roundtrip_stale_reference_unrelated_changes_and_atomic_import():
    source = snapshot()
    active = replace(
        scenario(source),
        operations=(operation(source, operation="replace", original_ids=("scheduled",)),),
        reserves={"annual": 80},
    )
    text = export_scenario(active)
    imported = import_scenario(source, scenario(source), text, mode="replace")
    assert project(source, imported, today=TODAY) == project(source, active, today=TODAY)
    changed = deepcopy(source)
    changed["transactions"].append(tx("unrelated", "2026-07-30", "sick", hours=1))
    imported = import_scenario(changed, scenario(changed), text, mode="replace")
    result = project(changed, imported, today=TODAY)
    assert category(result).scenario.horizon_balance == 84
    assert any(warning.code == "SNAPSHOT_CHANGED" for warning in result.warnings)
    changed["transactions"][0]["hours"] = 8
    before = active.to_dict()
    with pytest.raises(PlanningValidationError, match="changed materially"):
        import_scenario(changed, active, text, mode="replace")
    assert active.to_dict() == before
    for invalid in (
        "not JSON",
        text.replace('"schema_version": 1', '"schema_version": 99'),
        text.replace('"operation": "replace"', '"operation": "unknown"'),
        text.replace('"hours": 24', '"hours": NaN'),
    ):
        with pytest.raises(PlanningValidationError):
            import_scenario(source, active, invalid, mode="replace")
    with pytest.raises(PlanningValidationError):
        import_scenario(source, active, text, mode="merge")
    assert active.to_dict() == before
    assert json.loads(export_scenario(active))["schema_version"] == 1


def test_operation_order_is_deterministic_and_categories_do_not_pool_balances():
    source = snapshot()
    one, two = operation(source, row_id="one", hours=2), operation(source, row_id="two", category="sick", hours=3)
    first = project(source, replace(scenario(source), operations=(one, two)), today=TODAY)
    second = project(source, replace(scenario(source), operations=(two, one)), today=TODAY)
    assert first == second
    assert category(first).scenario.horizon_balance == 90
    assert category(first, "sick").scenario.horizon_balance == 37
    assert all(
        event.id.startswith("scenario:") and event.original_transaction_id is None
        for event in first.events
        if event.timing == "Tentative"
    )


def test_parental_scenarios_reuse_canonical_windows_and_do_not_double_count_capacity():
    source = snapshot()
    source["transactions"] = [
        tx("grant", "2026-07-01", "ppl", "earned", 480),
        tx("ppl-used", "2026-07-15", "ppl", "used", 8),
    ]
    result = project(
        source, replace(scenario(source), operations=(operation(source, category="ppl", hours=4),)), today=TODAY
    )
    assert category(result, "ppl").baseline.horizon_balance == 472
    assert category(result, "ppl").scenario.horizon_balance == 468
    assert category(result, "fmla").scenario.horizon_balance == -12
    assert next(row for row in result.capacity if row.date == "2026-07-23").total_proposed_absence == 4


def test_projection_has_no_file_or_repository_capability(monkeypatch):
    from pathlib import Path

    source = lot_source()
    before = deepcopy(source)

    def forbidden(*args, **kwargs):
        raise AssertionError("Projection must not open files")

    monkeypatch.setattr(Path, "open", forbidden)
    result = project(
        source,
        replace(scenario(source), operations=(operation(source, category="comp", hours=2, date="2026-07-14"),)),
        today=TODAY,
    )
    assert result.schema_version == 1
    assert source == before


def test_missing_source_fingerprint_is_rejected_before_import_changes_state():
    source = snapshot()
    document = scenario(source).to_dict()
    document["source"].pop("snapshot_fingerprint")
    with pytest.raises(PlanningValidationError, match="fingerprint"):
        validate_scenario(source, document)


def test_using_beyond_available_lots_retains_shortfall_and_all_proposed_hours():
    source = lot_source()
    source["transactions"] = source["transactions"][:1]
    result = project(
        source,
        replace(scenario(source), operations=(operation(source, category="comp", hours=12, date="2026-07-14"),)),
        today=TODAY,
    )
    summary = category(result, "comp").scenario
    assert summary.earliest_negative_date == "2026-07-14"
    assert summary.negative_shortfall == 2
    assert sum(row.hours for row in result.events if row.timing == "Tentative") == 12
    assert any(
        warning.code == "MISSING_LOT_PROVENANCE" and warning.row_id == "tentative" for warning in result.warnings
    )
