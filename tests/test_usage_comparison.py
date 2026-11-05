from copy import deepcopy

import pytest

from fedleave.usage_comparison import CumulativeParameters, cumulative_usage
from leave_year_support import tx
from test_forecast import source


def run(target=None, categories=("annual",)):
    return cumulative_usage(target or source(), categories)


def point(result, day):
    return next(row for row in result.points if row["date"] == day)


def test_cumulative_total_is_the_running_sum_of_effective_used_hours():
    target = source(
        transactions=[
            tx("one", "2026-02-01", "annual", "used", 4),
            tx("two", "2026-02-01", "annual", "used", 4),
            tx("later", "2026-03-10", "annual", "used", 8),
        ]
    )
    result = run(target)
    assert result.summary["total_hours"] == 16
    assert result.summary["transaction_count"] == 3
    assert point(result, "2026-01-31")["hours"] == 0
    assert point(result, "2026-02-01")["hours"] == 8
    assert point(result, "2026-03-09")["hours"] == 8
    assert point(result, "2026-03-10")["hours"] == 16
    assert result.points[0]["date"] == "2026-01-01"
    assert result.points[-1]["date"] == target["leave_year_end"]


def test_openings_accruals_disposals_corrections_and_overtime_are_not_usage():
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
    assert run(target).summary["total_hours"] == 104


def test_categories_select_one_or_an_explicit_sum():
    target = source(
        transactions=[
            tx("one", "2026-02-01", "annual", "used", 4),
            tx("sick", "2026-02-01", "sick", "used", 2),
        ]
    )
    assert run(target, ("annual",)).summary["total_hours"] == 4
    assert run(target, ("sick",)).summary["total_hours"] == 2
    assert run(target, ("annual", "sick")).summary["total_hours"] == 6


@pytest.mark.parametrize("extra", [{"void": True}, {"status": "denied"}, {"status": "cancelled"}])
def test_ineffective_rows_are_ignored(extra):
    target = source(transactions=[tx("ignored", "2026-02-01", "annual", "used", 900, **extra)])
    assert run(target).summary["total_hours"] == 0


def test_future_planned_bookings_are_included_with_a_warning():
    target = source(
        transactions=[
            tx("before", "2026-02-01", "annual", "used", 104),
            tx("after", "2026-07-01", "annual", "used", 24, status="planned"),
        ]
    )
    result = run(target)
    assert result.summary["total_hours"] == 128
    assert any(w["code"] == "UNRESOLVED_RECORDED_STATUS" for w in result.warnings)


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
def test_malformed_usage_warns_and_is_excluded_without_fabricating_usage(change):
    target = source(
        transactions=[tx("good", "2026-02-01", "annual", "used", 8), tx("bad", "2026-02-02", "annual", "used", 8)]
    )
    target["transactions"][1].update(change)
    result = run(target)
    assert result.summary["total_hours"] == 8
    assert result.summary["excluded_malformed"] == 1
    assert any(w["code"] == "INVALID_USAGE" for w in result.warnings)


def test_out_of_year_usage_is_excluded_with_a_warning():
    target = source(transactions=[tx("bad", "2025-12-31", "annual", "used", 8)])
    result = run(target)
    assert result.summary["total_hours"] == 0
    assert any(w["code"] == "INVALID_USAGE" for w in result.warnings)


def test_non_physical_absence_categories_are_rejected():
    with pytest.raises(ValueError):
        run(source(), ("overtime",))
    with pytest.raises(ValueError):
        run(source(), ("fmla",))
    with pytest.raises(ValueError):
        run(source(), ())


def test_inputs_are_not_mutated_and_result_is_deterministic():
    target = source(transactions=[tx("use", "2026-02-01", "annual", "used", 8)])
    before = deepcopy(target)
    result = cumulative_usage(target, ("annual",))
    assert target == before
    assert result == cumulative_usage(target, ("annual",))
    assert result.parameters == CumulativeParameters(("annual",))


def test_malformed_transaction_row_is_excluded():
    target = source(transactions=[tx("use", "2026-02-01", "annual", "used", 8), "not a row"])
    result = run(target)
    assert result.summary["total_hours"] == 8
    assert result.summary["excluded_malformed"] == 1
    assert any(w["code"] == "INVALID_USAGE" for w in result.warnings)
