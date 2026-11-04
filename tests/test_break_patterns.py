from copy import deepcopy
from datetime import date, timedelta

import pytest

from fedleave.break_patterns import BreakParameters, analyze_breaks
from fedleave.config import Config
from fedleave.history import confirm_coverage
from leave_year_support import tx

TODAY = date(2028, 1, 1)


def source(year=2026, start="2026-06-01", end="2026-06-30", transactions=(), lengths=None):
    config = Config().model_dump()
    config["holidays"]["enabled"] = False
    config["defaults"].update(normal_workdays=["mon", "tue", "wed", "thu", "fri"])
    current, periods = date.fromisoformat(start), []
    lengths = lengths or [(date.fromisoformat(end) - current).days + 1]
    for number, length in enumerate(lengths, 1):
        last = current + timedelta(days=length - 1)
        periods.append({"pay_period_number": number, "start_date": current.isoformat(), "end_date": last.isoformat()})
        current = last + timedelta(days=1)
    return {
        "leave_year": year,
        "leave_year_start": start,
        "leave_year_end": periods[-1]["end_date"],
        "pay_periods": periods,
        "pay_period_count": len(periods),
        "transactions": list(transactions),
        "snapshot_rules": config,
        "calculation_context": {"backend": "test-backend", "data_store": "test-store"},
    }


def analyze(snapshot=None, history=None, coverage=None, **values):
    snapshot, history = snapshot or source(), history or {}
    all_sources = {**history, snapshot["leave_year"]: snapshot}
    coverage = (
        coverage
        if coverage is not None
        else [row for s in all_sources.values() for row in confirm_coverage(s, strict=False)]
    )
    return analyze_breaks(
        snapshot, history, coverage, BreakParameters(**{"cutoff": "2026-06-30", **values}), today=TODAY
    )


def annual(*days, hours=8, **values):
    return [tx(f"use-{day}", day, "annual", "used", hours, **values) for day in days]


def test_friday_monday_is_four_calendar_days_two_workdays_and_sixteen_hours():
    result = analyze(source(transactions=annual("2026-06-05", "2026-06-08")))
    (interval,) = result.recorded
    assert (
        interval["start"],
        interval["end"],
        interval["calendar_days"],
        interval["fully_absent_workdays"],
        interval["selected_hours"],
    ) == ("2026-06-05", "2026-06-08", 4, 2, 16)
    assert interval["completed"] and not interval["substantial"]
    assert result.summary["qualifying_break_count"] == 0
    assert result.summary["time_since_status"] == "No qualifying break in covered history"
    assert result.summary["last_completed_break_end"] is None


def test_three_workdays_qualify_partial_day_interrupts_and_weekends_extend():
    snapshot = source(transactions=annual("2026-06-08", "2026-06-09", "2026-06-10"))
    result = analyze(snapshot)
    (interval,) = result.recorded
    assert interval["substantial"] and interval["completed"]
    assert (interval["start"], interval["end"], interval["calendar_days"]) == ("2026-06-06", "2026-06-10", 5)
    assert result.summary["median_completed_workdays"] == 3
    assert result.summary["last_completed_break_end"] == "2026-06-10"
    assert result.summary["calendar_days_since"] == 20
    assert result.summary["scheduled_workdays_since"] == 14
    snapshot["transactions"][1]["hours"] = 4
    partial = analyze(snapshot)
    assert len(partial.recorded) == 2
    assert partial.summary["qualifying_break_count"] == 0
    assert partial.summary["partially_absent_workdays"] == 1


def test_standalone_weekend_is_not_a_break_and_monday_holiday_extends_friday():
    assert not analyze().recorded
    snapshot = source(transactions=annual("2026-06-05"))
    snapshot["snapshot_rules"]["holidays"]["enabled"] = True
    snapshot["calculation_context"].update(holiday_coverage=[2026], holidays=[{"observed_date": "2026-06-08"}])
    (interval,) = analyze(snapshot).recorded
    assert (interval["start"], interval["end"], interval["calendar_days"], interval["fully_absent_workdays"]) == (
        "2026-06-05",
        "2026-06-08",
        4,
        1,
    )


def test_nonstandard_sunday_thursday_ten_hour_schedule():
    snapshot = source(transactions=annual("2026-06-07", "2026-06-08", "2026-06-09", hours=10))
    snapshot["snapshot_rules"]["defaults"].update(
        normal_workdays=["sun", "mon", "tue", "wed", "thu"],
        workday_start="07:00",
        workday_end="18:00",
        lunch_start="12:00",
        lunch_end="13:00",
    )
    (interval,) = analyze(snapshot).recorded
    assert interval["fully_absent_workdays"] == 3
    assert interval["selected_hours"] == 30
    assert interval["start"] == "2026-06-05"


def test_aggregate_same_day_rows_and_keep_sick_context_separate_until_selected():
    snapshot = source(
        transactions=[tx("a", "2026-06-09", "annual", "used", 4), tx("b", "2026-06-09", "annual", "used", 4)]
    )
    result = analyze(snapshot)
    assert result.summary["fully_absent_workdays"] == 1
    assert result.recorded[0]["selected_hours"] == 8
    snapshot["transactions"][1]["category"] = "sick"
    separate = analyze(snapshot)
    day = next(row for row in separate.daily if row["date"] == "2026-06-09")
    assert (day["classification"], day["selected_hours"], day["other_hours"], day["combined_absence_ratio"]) == (
        "Partial",
        4,
        4,
        1,
    )
    combined = analyze(snapshot, grouping="custom", categories=("annual", "sick"))
    assert combined.summary["fully_absent_workdays"] == 1
    assert combined.recorded[0]["selected_hours"] == 8


def test_raw_overbooked_hours_preserved_ratio_capped_and_warning_traceable():
    result = analyze(source(transactions=annual("2026-06-09", hours=10)))
    day = next(row for row in result.daily if row["date"] == "2026-06-09")
    assert (day["classification"], day["selected_hours"], day["absence_ratio"], day["overbooked"]) == (
        "Full",
        10,
        1,
        True,
    )
    assert result.recorded[0]["selected_hours"] == 10
    assert any(w["code"] == "HOURS_ABOVE_SCHEDULE" and w["date"] == "2026-06-09" for w in result.warnings)


def test_cross_year_vacation_joins_only_contiguous_covered_dates():
    previous = source(2025, "2025-12-22", "2025-12-31", annual("2025-12-31"))
    current = source(2026, "2026-01-01", "2026-01-09", annual("2026-01-01", "2026-01-02"))
    result = analyze(current, {2025: previous}, years=(2025, 2026), cutoff="2026-01-09")
    (interval,) = result.recorded
    assert (interval["start"], interval["end"], interval["fully_absent_workdays"]) == ("2025-12-31", "2026-01-04", 3)
    assert interval["source_years"] == [2025, 2026]
    assert len(interval["transaction_refs"]) == 3
    missing = analyze(
        current,
        {2025: previous},
        list(confirm_coverage(current, strict=False)),
        years=(2025, 2026),
        cutoff="2026-01-09",
    )
    assert missing.recorded[0]["incomplete_start"]
    assert missing.recorded[0]["fully_absent_workdays"] == 2


def test_unknown_coverage_interrupts_intervals_and_elapsed_history_without_inventing_a_streak():
    snapshot = source(
        start="2026-06-01",
        end="2026-06-30",
        lengths=[7, 7, 16],
        transactions=annual("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-05", "2026-06-08"),
    )
    coverage = confirm_coverage(snapshot, [1, 3], strict=False)
    result = analyze(snapshot, coverage=coverage)
    assert result.summary["calendar_days_since"] is None
    assert "Coverage incomplete" in result.summary["time_since_status"]
    assert result.summary["unknown_recorded_days"] == 7
    assert any(item["incomplete_end"] for item in result.recorded)
    assert not any(gap["start"] < "2026-06-08" and gap["end"] > "2026-06-14" for gap in result.gaps)


def test_missing_selected_year_range_is_unknown_and_never_joins_or_counts_workdays():
    previous = source(2025, "2025-12-01", "2025-12-05", annual("2025-12-05"))
    current = source(2026, "2026-01-01", "2026-01-09", annual("2026-01-01"))
    result = analyze(current, {2025: previous}, years=(2025, 2026), cutoff="2026-01-09")
    assert result.summary["unknown_recorded_days"] == 26
    assert len(result.recorded) == 2
    assert result.recorded[0]["incomplete_end"]
    assert result.recorded[1]["incomplete_start"]


def test_ongoing_at_cutoff_and_scheduled_continuation_do_not_reset_recorded_metrics():
    snapshot = source(transactions=annual("2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11"))
    cutoff = analyze(snapshot, cutoff="2026-06-09")
    assert cutoff.summary["qualifying_break_count"] == 0
    assert cutoff.upcoming[0]["continuation_of"] == cutoff.recorded[0]["id"]
    assert cutoff.upcoming[0]["combined_fully_absent_workdays"] == 4
    assert cutoff.upcoming[0]["substantial"]
    ongoing = analyze(snapshot, cutoff="2026-06-10")
    assert ongoing.summary["time_since_status"] == "Break in progress"
    assert ongoing.summary["last_completed_break_end"] is None
    assert ongoing.summary["calendar_days_since"] is None
    assert all(row["timing"] == "Scheduled" for row in ongoing.upcoming)
    snapshot["transactions"].append(tx("future-huge", "2026-06-20", "annual", "used", 80))
    assert analyze(snapshot, cutoff="2026-06-10").summary == ongoing.summary


def test_longest_gap_counts_roster_days_and_retains_smaller_sick_absences_as_context():
    snapshot = source(
        transactions=[
            *annual("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-15", "2026-06-16", "2026-06-17"),
            tx("sick", "2026-06-10", "sick", "used", 8),
        ]
    )
    result = analyze(snapshot)
    middle = next(gap for gap in result.gaps if not gap["partial_history"])
    assert (middle["start"], middle["end"], middle["scheduled_workdays"], middle["calendar_days"]) == (
        "2026-06-04",
        "2026-06-12",
        7,
        9,
    )
    assert middle["other_absence_hours"] == 8
    assert "not confirmed attendance" in middle["basis"]
    assert any(ref["id"] == "sick" for ref in middle["transaction_refs"])


def test_leap_day_is_a_real_nonworking_bridge():
    snapshot = source(2020, "2020-02-27", "2020-03-04", annual("2020-02-28", "2020-03-02"))
    result = analyze(snapshot, cutoff="2020-03-04")
    assert result.recorded[0]["calendar_days"] == 4
    assert any(row["date"] == "2020-02-29" and row["classification"] == "Nonworking" for row in result.daily)


def test_no_qualifying_history_and_unknown_history_are_not_fake_zero_or_never():
    empty = analyze()
    assert empty.summary["fully_absent_workdays"] == 0
    assert empty.summary["median_completed_workdays"] is None
    assert empty.summary["time_since_status"] == "No qualifying break in covered history"
    missing = analyze(coverage=[])
    assert missing.summary["fully_absent_workdays"] is None
    assert missing.summary["qualifying_break_count"] is None
    assert all(row["completed_count"] is None for row in missing.distribution)


def test_observed_qualifying_interval_with_unknown_completion_is_not_labeled_absent():
    snapshot = source(transactions=annual("2026-06-01", "2026-06-02", "2026-06-03"))
    coverage = confirm_coverage(snapshot, strict=False, through="2026-06-03")
    result = analyze(snapshot, coverage=coverage)
    assert result.summary["qualifying_break_count"] == 1
    assert "completion is unknown" in result.summary["time_since_status"]
    assert result.summary["last_completed_break_end"] is None
    assert result.summary["calendar_days_since"] is None


def test_unknown_historical_roster_or_holiday_context_produces_unknown_classification():
    snapshot = source(transactions=annual("2026-06-09"))
    unknown = analyze(snapshot, assume_current_schedule=False)
    assert unknown.summary["fully_absent_workdays"] is None
    assert any(row["known_selected_hours"] == 8 for row in unknown.daily)
    snapshot["snapshot_rules"]["holidays"]["enabled"] = True
    no_holidays = analyze(snapshot)
    assert no_holidays.summary["fully_absent_workdays"] is None
    assert any(w["code"] == "MISSING_HOLIDAY_CONTEXT" for w in no_holidays.warnings)


@pytest.mark.parametrize("extra", [{"void": True}, {"status": "denied"}, {"status": "cancelled"}])
def test_ineffective_rows_do_not_create_absence(extra):
    assert not analyze(source(transactions=annual("2026-06-09", **extra))).recorded


def test_statuses_earnings_rollover_and_fmla_tracking_keep_physical_absence_single_counted():
    snapshot = source(
        transactions=[
            tx("planned", "2026-06-09", "annual", "used", 8, status="planned"),
            tx("ppl", "2026-06-10", "ppl", "used", 8),
            tx("fmla", "2026-06-10", "fmla", "used", 8),
            tx("rollover", "2026-06-11", "comp", "earned", 900, source="expiration-rollover"),
            tx("expire", "2026-06-12", "annual", "expired", 900),
        ]
    )
    result = analyze(snapshot, grouping="all")
    assert result.summary["fully_absent_workdays"] == 2
    assert sum(row["hours"] for row in result.transactions) == 16
    assert any(w["code"] == "UNRESOLVED_RECORDED_STATUS" for w in result.warnings)
    confirmed = analyze(snapshot, grouping="all", status_basis="confirmed")
    assert confirmed.summary["fully_absent_workdays"] == 1


@pytest.mark.parametrize("change", [{"hours": float("nan")}, {"hours": -1}, {"status": "unknown"}, {"date": "bad"}])
def test_malformed_usage_is_unknown_with_actionable_warning(change):
    row = tx("bad", "2026-06-09", "annual", "used", 8)
    row.update(change)
    result = analyze(source(transactions=[row]))
    assert any(w["code"] == "INVALID_USAGE" for w in result.warnings)
    assert any(row["classification"] == "Unknown" for row in result.daily)


def test_inputs_not_mutated_distribution_and_timing_are_recorded_only():
    snapshot = source(transactions=[*annual("2026-06-08", "2026-06-09", "2026-06-10"), *annual("2026-06-29", hours=4)])
    before = deepcopy(snapshot)
    result = analyze(snapshot, cutoff="2026-06-19")
    assert snapshot == before
    assert result == analyze(snapshot, cutoff="2026-06-19")
    assert result.distribution[2]["completed_count"] == 1
    assert next(row for row in result.day_distribution if row["classification"] == "Full")["days"] == 3
    assert result.timing[0]["selected_hours"] == 24
    assert result.summary["selected_recorded_hours"] == 24
    assert result.summary["partially_absent_workdays"] == 0


def test_overlap_and_mixed_sources_rejected():
    snapshot = source()
    prior = source(2025, "2026-06-01", "2026-06-30")
    with pytest.raises(ValueError, match="overlap"):
        analyze(snapshot, {2025: prior}, years=(2025, 2026))
    prior["calculation_context"]["backend"] = "other"
    with pytest.raises(ValueError, match="same backend"):
        analyze(snapshot, {2025: prior}, years=(2025, 2026))
