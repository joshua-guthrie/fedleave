from copy import deepcopy
from dataclasses import replace
from datetime import date

import pytest

from fedleave.history import confirm_coverage, coverage_status
from fedleave.usage_comparison import ComparisonParameters, aligned_date, compare_usage
from leave_year_support import tx
from test_forecast import source

TODAY = date(2028, 1, 1)


def compare(target=None, history=None, coverage=None, **options):
    target = target or source(transactions=[tx("target", "2026-02-01", "annual", "used", 104)])
    history = (
        history
        if history is not None
        else {
            year: source(year, transactions=[tx(f"ref-{year}", f"{year}-02-01", "annual", "used", hours)])
            for year, hours in zip((2023, 2024, 2025), (64, 80, 96), strict=True)
        }
    )
    if coverage is None:
        coverage = [
            record for snapshot in (target, *history.values()) for record in confirm_coverage(snapshot, strict=False)
        ]
    return compare_usage(
        target, history, coverage, ComparisonParameters(**{"cutoff": "2026-06-30", **options}), today=TODAY
    )


def point(result, day):
    return next(row for row in result.points if row["date"] == day)


def test_104_against_64_80_96_uses_usage_and_exact_linear_percentiles():
    result = compare()
    summary = result.summary
    assert (summary["recorded"], summary["median"], summary["difference"], summary["percentage_difference"]) == (
        104,
        80,
        24,
        30,
    )
    assert summary["p20"] == 70.4
    assert summary["p80"] == 89.6
    assert summary["observation_count"] == 3
    assert not summary["limited_history"]
    assert summary["band_lower"] == summary["p20"]


def test_openings_accruals_disposals_corrections_and_overtime_are_not_absence():
    target = source(balances={"annual": 9999})
    target["transactions"] = (
        [tx("use", "2026-02-01", "annual", "used", 104)]
        + [
            tx(direction, "2026-02-02", "annual", direction, 1000)
            for direction in (
                "earned",
                "adjusted",
                "forced_decrease",
                "forced_increase",
                "expired",
                "forfeited",
                "corrected",
                "paid_out",
                "starting_balance",
            )
        ]
        + [tx("overtime", "2026-02-02", "overtime", "worked", 1000)]
    )
    assert compare(target).summary["recorded"] == 104


def test_future_bookings_are_a_separate_continuation_and_never_affect_cutoff_statistics():
    target = source(
        transactions=[
            tx("before", "2026-02-01", "annual", "used", 104),
            tx("after", "2026-07-01", "annual", "used", 24, status="planned"),
        ]
    )
    result = compare(target)
    assert result.summary["difference"] == 24
    assert point(result, "2026-07-01")["recorded"] is None
    assert point(result, "2026-07-01")["scheduled"] == 128
    assert point(result, "2026-07-01")["future_scheduled_hours"] == 24
    assert next(row for row in result.transactions if row["id"] == "after")["timing"] == "Scheduled"
    assert not any(w.get("transaction_id") == "after" for w in result.warnings)


def test_historical_future_of_aligned_cutoff_does_not_change_the_summary():
    history = {
        2025: source(
            2025,
            transactions=[
                tx("before", "2025-02-01", "annual", "used", 64),
                tx("context", "2025-08-01", "annual", "used", 800),
            ],
        )
    }
    result = compare(history=history)
    assert result.summary["median"] == 64
    assert point(result, "2026-09-01")["reference_2025"] == 864
    assert (
        next(row for row in result.transactions if row["id"] == "context")["timing"]
        == "Historical context beyond aligned cutoff"
    )


def test_progress_alignment_non_january_cutoff_inside_period_and_missing_27th():
    target = source(2026, start="2026-01-11", count=27)
    reference = source(2025, start="2025-01-12")
    assert aligned_date(target, reference, "2026-02-02") == "2025-02-03"
    result = compare(target, {2025: reference}, cutoff="2027-01-11")
    assert result.summary["reference_2025"] is None
    assert result.summary["observation_count"] == 0
    missing = next(row for row in result.observations if row["year"] == 2025 and row["date"] == "2027-01-11")
    assert missing["mapped_date"] is None
    assert "No exact equivalent" in missing["missing_reason"]


def test_calendar_alignment_january_in_following_calendar_year_and_two_januaries():
    target = source(2026, start="2026-01-01", count=27)
    reference = source(2025, start="2025-01-01", count=27)
    assert aligned_date(target, reference, "2027-01-05", "calendar") == "2026-01-05"
    assert aligned_date(target, source(2025, start="2025-01-12"), "2026-01-01", "calendar") == "2026-01-01"


def test_missing_leap_day_is_null_without_clamping_and_later_points_resume():
    target, reference = source(2024), source(2023)
    result = compare(target, {2023: reference}, cutoff="2024-02-29", alignment="calendar")
    assert result.summary["reference_2023"] is None
    assert point(result, "2024-03-01")["reference_2023"] == 0
    assert result.summary["median"] is None


def irregular(year, lengths):
    from datetime import timedelta

    snapshot = source(year)
    current, periods = date(year, 1, 1), []
    for i, length in enumerate(lengths, 1):
        end = current + timedelta(days=length - 1)
        periods.append({"pay_period_number": i, "start_date": current.isoformat(), "end_date": end.isoformat()})
        current = end + timedelta(days=1)
    snapshot.update(pay_periods=periods, pay_period_count=len(periods), leave_year_end=periods[-1]["end_date"])
    return snapshot


def test_actual_period_lengths_are_respected_without_clamping_an_offset():
    target, reference = irregular(2026, [10, 4]), irregular(2025, [7, 14])
    assert aligned_date(target, reference, "2026-01-10") is None
    assert aligned_date(target, reference, "2026-01-11") == "2025-01-08"
    result = compare(target, {2025: reference}, cutoff="2026-01-11")
    assert point(result, "2026-01-10")["reference_2025"] is None
    assert result.summary["reference_2025"] == 0


def test_unknown_coverage_is_missing_confirmed_zero_is_zero_and_a_gap_stays_missing():
    target, reference = source(), source(2025)
    coverage = list(confirm_coverage(target))
    missing = compare(target, {2025: reference}, coverage)
    assert missing.summary["median"] is None
    assert missing.summary["recorded"] == 0
    coverage += list(confirm_coverage(reference, [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]))
    gap = compare(target, {2025: reference}, coverage)
    assert gap.points[0]["reference_2025"] == 0
    assert point(gap, "2026-02-20")["reference_2025"] is None
    complete = compare(target, {2025: reference})
    assert complete.summary["median"] == 0
    assert complete.summary["percentage_difference"] is None
    assert complete.summary["band_lower"] is None


def test_unknown_target_coverage_does_not_invent_a_complete_curve():
    result = compare(coverage=[])
    assert all(row["recorded"] is None for row in result.points)
    assert all(row["scheduled"] is None for row in result.points)
    assert result.summary["target_missing_reason"]
    assert result.summary["difference"] is None


def test_material_edits_stale_coverage_and_display_only_changes_keep_it():
    target = source(transactions=[tx("id", "2026-02-01", "annual", "used", 8)])
    coverage = confirm_coverage(target)
    target["transactions"][0]["description"] = "Display-only edit"
    assert compare(target, {}, coverage).summary["recorded"] == 8
    target["transactions"][0]["hours"] = 16
    assert compare(target, {}, coverage).summary["recorded"] is None


def test_target_confirmation_stops_at_cutoff_even_inside_a_period():
    target = source(transactions=[tx("use", "2026-02-01", "annual", "used", 8)])
    coverage = confirm_coverage(target, through="2026-06-30")
    periods, covered = coverage_status(target, coverage)
    assert "2026-06-30" in covered and "2026-07-01" not in covered
    assert periods[12]["state"] == "Confirmed through 2026-06-30"
    assert not periods[12]["confirmed"]
    assert compare(target, {}, coverage).summary["recorded"] == 8
    assert compare(target, {}, coverage, cutoff="2026-07-01").summary["recorded"] is None


def test_multiple_same_day_rows_categories_and_confirmed_status_filter():
    target = source(
        transactions=[
            tx("one", "2026-02-01", "annual", "used", 4),
            tx("two", "2026-02-01", "annual", "used", 4),
            tx("sick", "2026-02-01", "sick", "used", 2),
            tx("pending", "2026-02-02", "annual", "used", 3, status="requested"),
            tx("future", "2026-07-01", "annual", "used", 8, status="planned"),
        ]
    )
    result = compare(target, {}, categories=("annual", "sick"))
    assert result.summary["recorded"] == 13
    assert any(w["code"] == "UNRESOLVED_RECORDED_STATUS" for w in result.warnings)
    confirmed = compare(target, {}, categories=("annual", "sick"), status_basis="confirmed")
    assert confirmed.summary["recorded"] == 10
    assert point(confirmed, "2026-07-01")["scheduled"] == 18
    detail = next(row for row in confirmed.observations if row["date"] == "2026-02-01")
    assert detail["transaction_ids"] == ["one", "sick", "two"]


@pytest.mark.parametrize("extra", [{"void": True}, {"status": "denied"}, {"status": "cancelled"}])
def test_ineffective_rows_are_ignored(extra):
    target = source(transactions=[tx("ignored", "2026-02-01", "annual", "used", 900, **extra)])
    assert compare(target, {}).summary["recorded"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"hours": float("nan")},
        {"hours": -1},
        {"hours": None},
        {"hours": True},
        {"status": "unknown"},
        {"direction": "unknown"},
        {"date": "not-a-date"},
        {"id": ""},
    ],
)
def test_malformed_usage_warns_and_never_manufactures_zero(change):
    target = source(transactions=[tx("bad", "2026-02-01", "annual", "used", 8, **{})])
    target["transactions"][0].update(change)
    result = compare(target, {})
    assert result.summary["recorded"] is None
    assert any(w["code"] == "INVALID_USAGE" for w in result.warnings)


def test_schedule_assumption_is_opt_in_and_missing_holidays_keep_normalization_unknown():
    target = source(transactions=[tx("use", "2026-01-07", "annual", "used", 4)])
    target["snapshot_rules"]["defaults"].update(
        normal_workdays=["sun", "mon", "tue", "wed", "thu"],
        workday_start="07:00",
        workday_end="18:00",
        lunch_start="12:00",
        lunch_end="13:00",
    )
    target["snapshot_rules"]["holidays"]["enabled"] = True
    target["calculation_context"].update(holiday_coverage=[2026], holidays=[{"observed_date": "2026-01-05"}])
    assert compare(target, {}, cutoff="2026-01-07").summary["hours_per_100"] is None
    result = compare(target, {}, cutoff="2026-01-07", assume_current_schedule=True)
    assert result.summary["target_exposure_hours"] == 40
    assert result.summary["hours_per_100"] == 10
    assert "Explicit analysis assumption" in result.history[0]["schedule_basis"]
    target["calculation_context"].pop("holiday_coverage")
    unknown = compare(target, {}, cutoff="2026-01-07", assume_current_schedule=True)
    assert unknown.summary["recorded"] == 4
    assert unknown.summary["hours_per_100"] is None
    assert any(w["code"] == "MISSING_HOLIDAY_CONTEXT" for w in unknown.warnings)


def test_backend_historical_schedule_supports_normalization_without_an_assumption():
    target = source(transactions=[tx("use", "2026-01-01", "annual", "used", 4)])
    target["calculation_context"]["historical_work_schedule"] = {
        "normal_workdays": ["thu"],
        "workday_start": "08:00",
        "workday_end": "16:30",
        "lunch_start": "12:00",
        "lunch_end": "12:30",
    }
    result = compare(target, {}, cutoff="2026-01-01")
    assert result.summary["hours_per_100"] == 50


def test_incomplete_historical_roster_and_malformed_record_do_not_invent_metrics():
    target = source(transactions=[tx("use", "2026-01-01", "annual", "used", 4)])
    target["calculation_context"]["historical_work_schedule"] = {"normal_workdays": ["thu"]}
    result = compare(target, {}, cutoff="2026-01-01")
    assert result.summary["recorded"] == 4
    assert result.summary["hours_per_100"] is None
    assert any(w["code"] == "INCOMPLETE_HISTORICAL_ROSTER" for w in result.warnings)
    assumed = compare(target, {}, cutoff="2026-01-01", assume_current_schedule=True)
    assert assumed.summary["hours_per_100"] == 50
    target["transactions"].append("malformed transaction")
    malformed = compare(target, {}, cutoff="2026-01-01")
    assert malformed.summary["recorded"] is None
    assert any(w["code"] == "INVALID_USAGE" for w in malformed.warnings)


def test_excluded_missing_invalid_and_nonprior_references_are_explicit():
    history = {2025: source(2025), 2027: source(2027), 2024: source(2024)}
    history[2024]["pay_periods"][1]["start_date"] = "2024-01-16"
    target = source()
    result = compare(
        target, history, confirm_coverage(target), reference_years=(2022, 2024, 2025, 2027), excluded_years=(2025,)
    )
    assert result.summary["observation_count"] == 0
    assert all(row["exclusion_reason"] for row in result.history if not row["target"])
    assert all(row["source_year"] == 2026 for row in result.transactions)


def test_inputs_and_provenance_are_not_mutated_and_result_is_deterministic():
    target, history = source(), {2025: source(2025)}
    coverage = [*confirm_coverage(target), *confirm_coverage(history[2025])]
    before = deepcopy((target, history, coverage))
    result = compare(target, history, coverage)
    assert (target, history, coverage) == before
    assert result == compare(target, history, coverage)
    with pytest.raises(ValueError, match="after today"):
        compare_usage(
            target, history, coverage, replace(result.parameters, cutoff="2026-12-01"), today=date(2026, 6, 30)
        )
