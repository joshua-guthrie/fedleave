import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from fedleave_analytics.analytics import analyze_leave_year
from fedleave_analytics.seasonality import SeasonalitySelection, seasonality_options, seasonality_series


def seasonal_payload(rows=(), *, start="2026-01-11", count=26):
    from datetime import timedelta

    from fedleave.categories import CATEGORY_POLICIES
    from fedleave.payperiods import generate_pay_periods

    return {
        "year": 2026,
        "leave_year_start": start,
        "leave_year_end": (date.fromisoformat(start) + timedelta(days=count * 14 - 1)).isoformat(),
        "pay_periods": generate_pay_periods(date.fromisoformat(start), count),
        "category_definitions": {key: {} for key in CATEGORY_POLICIES},
        "transactions": list(rows),
    }


def seasonal_tx(id, category="comp", direction="used", hours=8, day="2026-06-01", **extra):
    return {
        "id": id,
        "date": day,
        "category": category,
        "direction": direction,
        "hours": hours,
        "status": "reconciled",
        "source": "manual",
        **extra,
    }


def payload(transactions):
    return {
        "year": 2026,
        "leave_year_start": "2026-01-01",
        "leave_year_end": "2026-12-31",
        "pay_periods": [{"pay_period_number": 1, "start_date": "2026-01-01", "end_date": "2026-01-14"}],
        "transactions": transactions,
    }


@pytest.mark.parametrize("grouping", ["month", "weekday", "pay_period"])
@pytest.mark.parametrize("category", ["annual", "sick", "comp", "travel_comp", "credit", "time_off_award", "ppl"])
def test_seasonality_used_filters_and_conserves_hours(grouping, category):
    data = seasonal_payload(
        [
            seasonal_tx("selected", category, hours=3.25),
            seasonal_tx("future", category, hours=2, day="2026-06-02"),
            seasonal_tx("other", "sick" if category != "sick" else "annual", hours=10),
            seasonal_tx("not-use", category, direction="earned", hours=100),
            seasonal_tx("denied", category, status="denied"),
        ]
    )
    before = deepcopy(data)
    result = seasonality_series(data, grouping=grouping, category=category, cutoff=date(2026, 6, 1))
    assert result["total_hours"] == 5.25
    assert sum(row["through_today"] for row in result["rows"]) == 3.25
    assert sum(row["future_scheduled"] for row in result["rows"]) == 2
    assert sum(row["full_leave_year"] for row in result["rows"]) == 5.25
    assert result["source_transaction_ids"] == ["selected", "future"]
    assert all(
        row["category"] == category and row["direction"] == "used"
        for bucket in result["bucket_transactions"]
        for row in bucket
    )
    assert data == before
    reversed_data = {**data, "transactions": list(reversed(data["transactions"]))}
    assert seasonality_series(reversed_data, grouping=grouping, category=category, cutoff=date(2026, 6, 1)) == result


def test_seasonality_default_matches_existing_all_used_buckets():
    data = seasonal_payload(
        [
            seasonal_tx("a", "annual"),
            seasonal_tx("s", "sick", hours=4, day="2026-10-01"),
            seasonal_tx("c", "comp", hours=2, day="2026-02-01"),
        ]
    )
    old = analyze_leave_year(data, date(2026, 6, 1))
    for grouping, key in (("month", "months"), ("weekday", "weekdays"), ("pay_period", "pay_periods")):
        result = seasonality_series(data, grouping=grouping, cutoff=date(2026, 6, 1))
        assert result["rows"] == old[key]
        assert result["total_hours"] == 14


@pytest.mark.parametrize(
    "category,direction",
    [
        ("comp", "earned"),
        ("travel_comp", "earned"),
        ("credit", "earned"),
        ("credit", "worked"),
        ("time_off_award", "earned"),
        ("restored_annual", "restored"),
        ("ppl", "earned"),
    ],
)
@pytest.mark.parametrize("grouping", ["month", "weekday", "pay_period"])
def test_seasonality_genuine_credits_only(category, direction, grouping):
    rows = [seasonal_tx("new", category, direction, 10), seasonal_tx("future", category, direction, 2, "2026-06-02")]
    rows += [
        seasonal_tx(action, category, action, 100)
        for action in (
            "starting_balance",
            "forced_increase",
            "adjusted",
            "corrected",
            "reconciled",
            "used",
            "paid_out",
            "expired",
            "forfeited",
        )
    ]
    result = seasonality_series(
        seasonal_payload(rows), grouping=grouping, category=category, activity="earned", cutoff=date(2026, 6, 1)
    )
    assert result["total_hours"] == 12
    assert sum(row["through_today"] for row in result["rows"]) == 10
    assert sum(row["future_scheduled"] for row in result["rows"]) == 2
    assert result["series"][1][1] == "Future Dated"
    assert "credits" in result["description"] and "carryover" in result["description"]


@pytest.mark.parametrize("category", ["comp", "travel_comp", "time_off_award", "restored_annual", "ppl"])
@pytest.mark.parametrize(
    "provenance",
    [
        {"source": "expiration-rollover"},
        {"carryover_generated": True},
        {"carried_from_transaction_id": "old"},
        {"carried_from_leave_year": 2025},
        {"carryover_chain": [2025]},
        {"origin_leave_year": 2025},
        {"original_earned_date": "2025-12-01"},
    ],
)
def test_seasonality_carried_lots_never_become_new_earnings(category, provenance):
    result = seasonality_series(
        seasonal_payload(
            [seasonal_tx("new", category, "earned", 10), seasonal_tx("carried", category, "earned", 100, **provenance)]
        ),
        grouping="month",
        category=category,
        activity="earned",
        cutoff=date(2026, 6, 1),
    )
    assert result["total_hours"] == 10
    assert result["source_transaction_ids"] == ["new"]


def test_seasonality_credit_legacy_worked_link_and_ambiguity_are_auditable():
    rows = [
        seasonal_tx("earned", "credit", "earned", 8),
        seasonal_tx("legacy", "credit", "worked", 8, earned_transaction_id="earned"),
        seasonal_tx("independent", "credit", "worked", 3),
        seasonal_tx("overtime", "overtime", "worked", 50),
    ]
    data = seasonal_payload(rows)
    result = seasonality_series(data, grouping="month", category="credit", activity="earned", cutoff=date(2026, 6, 1))
    assert result["total_hours"] == 11
    rows[1].pop("earned_transaction_id")
    ambiguous = seasonality_series(
        data, grouping="month", category="credit", activity="earned", cutoff=date(2026, 6, 1)
    )
    assert ambiguous["total_hours"] is None and ambiguous["known_total_hours"] == 11
    assert ambiguous["warnings"][0]["code"] == "POSSIBLE_DUPLICATE_CREDIT"
    independent = seasonal_payload(
        [seasonal_tx("one", "credit", "earned", 8), seasonal_tx("two", "credit", "earned", 8)]
    )
    assert (
        seasonality_series(
            independent, grouping="month", category="credit", activity="earned", cutoff=date(2026, 6, 1)
        )["total_hours"]
        == 16
    )


@pytest.mark.parametrize(
    "status,void,expected",
    [
        ("planned", False, 8),
        ("requested", False, 8),
        ("approved", False, 8),
        ("reconciled", False, 8),
        ("denied", False, 0),
        ("cancelled", False, 0),
        ("approved", True, 0),
    ],
)
def test_seasonality_canonical_statuses_and_recorded_framing(status, void, expected):
    result = seasonality_series(
        seasonal_payload([seasonal_tx("status", status=status, void=void)]),
        grouping="month",
        category="comp",
        cutoff=date(2026, 6, 1),
    )
    assert result["total_hours"] == expected
    assert result["columns"][1][1] == "Recorded Through Cutoff"
    assert "does not confirm attendance" in result["description"]


@pytest.mark.parametrize(
    "extra", [{"status": "surprise"}, {"hours": -2}, {"hours": float("nan")}, {"date": "nonsense"}]
)
def test_seasonality_malformed_records_do_not_become_verified_zero(extra):
    result = seasonality_series(
        seasonal_payload([seasonal_tx("bad", **extra)]), grouping="month", cutoff=date(2026, 6, 1)
    )
    assert result["total_hours"] is None
    assert result["warnings"][0]["transaction_id"] == "bad"
    assert "Incomplete/unverified" in result["description"]


def test_seasonality_unknown_carry_origin_excludes_credit_with_source_warning():
    data = seasonal_payload([seasonal_tx("suspect", direction="earned", origin_transaction_id="old-unknown")])
    result = seasonality_series(data, grouping="month", category="comp", activity="earned", cutoff=date(2026, 6, 1))
    assert result["total_hours"] is None and result["known_total_hours"] == 0
    assert "suspect" in result["description"]
    assert result["warnings"][0]["code"] == "UNVERIFIED_EARNING_ORIGIN"


def test_seasonality_supported_zero_options_and_backend_registry_are_respected():
    data = seasonal_payload()
    keys = [row["key"] for row in seasonality_options(data)]
    assert keys[0] == "all-used"
    assert "comp:earned" in keys and "comp:used" in keys and "ppl:earned" in keys and "ppl:used" in keys
    assert all(key not in keys for key in ("annual:earned", "sick:earned", "fmla:earned", "overtime:earned"))
    assert (
        next(row for row in seasonality_options(data) if row["key"] == "fmla:used")["label"] == "FMLA Tracking — Used"
    )
    data["category_definitions"].pop("ppl")
    assert not any(row["category"] == "ppl" for row in seasonality_options(data))
    result = seasonality_series(data, grouping="month", category="comp", cutoff=date(2026, 6, 1))
    assert result["total_hours"] == 0 and "No matching transactions" in result["description"]
    with pytest.raises(ValueError):
        SeasonalitySelection("month", "all", "earned")


def test_seasonality_fmla_is_separate_from_physical_absence():
    data = seasonal_payload(
        [
            seasonal_tx("ppl", "ppl", hours=8),
            seasonal_tx("tracking", "fmla", hours=4),
            seasonal_tx("annual", "annual", hours=2),
        ]
    )
    assert seasonality_series(data, grouping="month", cutoff=date(2026, 6, 1))["total_hours"] == 10
    fmla = seasonality_series(data, grouping="weekday", category="fmla", cutoff=date(2026, 6, 1))
    assert fmla["total_hours"] == 12
    assert sum(row["hours"] for row in fmla["transactions"] if row["derived"]) == 8
    assert "entitlement tracking" in fmla["description"]


def test_seasonality_real_27_period_bounds_weekends_and_cross_year_months():
    data = seasonal_payload(
        [
            seasonal_tx("sat", day="2026-06-06", hours=2),
            seasonal_tx("sun", day="2026-06-07", hours=3),
            seasonal_tx("last", day="2027-01-09", hours=4),
        ],
        start="2025-12-28",
        count=27,
    )
    month = seasonality_series(data, grouping="month", cutoff=date(2026, 6, 6))
    assert len(month["rows"]) == 14 and month["rows"][-1]["month"] == "Jan 2027"
    weekday = seasonality_series(data, grouping="weekday", cutoff=date(2026, 6, 6))
    assert [row["weekday"] for row in weekday["rows"]] == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    assert weekday["rows"][5]["full_leave_year"] == 6 and weekday["rows"][6]["full_leave_year"] == 3
    periods = seasonality_series(data, grouping="pay_period", cutoff=date(2026, 6, 6))
    assert len(periods["rows"]) == 27
    assert all(result["total_hours"] == 9 for result in (month, weekday, periods))


def test_seasonality_earnings_across_source_and_carried_year_sum_once():
    original = seasonal_payload([seasonal_tx("original", direction="earned", hours=10, day="2026-09-01")])
    successor = seasonal_payload(
        [
            seasonal_tx(
                "copy",
                direction="earned",
                hours=10,
                day="2027-01-10",
                source="expiration-rollover",
                original_earned_date="2026-09-01",
                origin_transaction_id="original",
            )
        ],
        start="2027-01-10",
    )
    successor["year"] = 2027
    totals = [
        seasonality_series(value, grouping="month", category="comp", activity="earned", cutoff=date(2027, 6, 1))[
            "total_hours"
        ]
        for value in (original, successor)
    ]
    assert totals == [10, 0]


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
