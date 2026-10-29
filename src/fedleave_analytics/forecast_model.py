"""Qt-free presentation of one versioned forecast result and its exact tables."""

from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from dataclasses import asdict

from fedleave.forecast import ForecastResult
from fedleave.history import confirm_coverage, coverage_key

from .planning_model import write_export

SUMMARY_COLUMNS = [
    ("scenario", "Scenario"),
    ("category", "Category"),
    ("allocated_horizon_balance", "Allocated horizon (h)"),
    ("minimum_balance", "Minimum (h)"),
    ("minimum_date", "Earliest minimum"),
    ("first_reserve_breach", "First reserve breach"),
    ("allocation_complete", "Complete allocation"),
    ("unallocated_hours", "Unallocated demand (h)"),
    ("hypothetical_full_demand_balance", "Hypothetical full demand (h)"),
    ("estimated_total_hours", "Estimated total (h)"),
    ("scheduled_hours", "Scheduled (h)"),
    ("additional_estimated_hours", "Additional estimate (h)"),
    ("allocated_hours", "Allocated estimate (h)"),
    ("earliest_negative_date", "Earliest negative"),
    ("negative_shortfall", "Negative shortfall (h)"),
    ("reserve_shortfall", "Reserve shortfall (h)"),
    ("annual_pre_cap_balance", "Annual pre-cap (h)"),
    ("annual_carryover", "Actual year-end carryover (h)"),
    ("prospective_forfeiture", "Prospective forfeiture (h)"),
    ("full_demand_explanation", "Hypothetical limitation"),
]
MONTHLY_COLUMNS = [
    ("scenario", "Scenario"),
    ("category", "Category"),
    ("start", "Segment start"),
    ("end", "Segment end"),
    ("exposure", "Scheduled work exposure (h)"),
    ("source_years", "Estimator source years"),
    ("eligible_seasonal_years", "Eligible seasonal years"),
    ("eligible_fallback_years", "Eligible fallback years"),
    ("observation_count", "Year observations"),
    ("estimator", "Estimator/fallback"),
    ("limited_history", "Limited history"),
    ("estimated_total_hours", "Estimated total (h)"),
    ("scheduled_hours", "Scheduled (h)"),
    ("additional_estimated_hours", "Additional estimate (h)"),
    ("allocated_hours", "Allocated (h)"),
    ("unallocated_hours", "Unallocated (h)"),
    ("allocated_closing_balance", "Allocated closing balance (h)"),
    ("allocation_complete", "Complete allocation"),
    ("per_year_rates", "Per-year hours/exposure/rates"),
    ("seasonal_observations", "Seasonal eligibility/exclusion reasons"),
    ("fallback_observations", "Fallback eligibility/exclusion reasons"),
]
DAILY_COLUMNS = [
    ("date", "Date"),
    ("category", "Category"),
    ("scheduled", "Scheduled closing (h)"),
    ("typical", "Typical allocated closing (h)"),
    ("higher", "Higher allocated closing (h)"),
    ("typical_complete", "Typical complete"),
    ("higher_complete", "Higher complete"),
]
SOURCE_COLUMNS = [
    ("source_year", "Source year"),
    ("id", "Original ID"),
    ("date", "Recorded date"),
    ("category", "Category"),
    ("hours", "Hours"),
    ("status", "Status"),
    ("timing", "Basis"),
    ("coverage_confirmed", "Coverage confirmed"),
    ("description", "Note"),
    ("source_key", "Source identity"),
]
WARNING_COLUMNS = [
    ("code", "Warning"),
    ("message", "Explanation"),
    ("category", "Category"),
    ("date", "Date"),
    ("year", "Source year"),
    ("forecast_scenario", "Scenario"),
    ("transaction_id", "Original ID"),
    ("unallocated_hours", "Unallocated (h)"),
]


def update_coverage(preferences, snapshot, period_ids=None, *, confirmed=True):
    """Return a new preference document; persistence belongs to the GUI adapter."""
    result = deepcopy(preferences)
    key = coverage_key(snapshot)
    replacements = confirm_coverage(snapshot, period_ids)
    ids = {row["period_id"] for row in replacements}
    result["coverage"] = [
        row for row in result.get("coverage", []) if row.get("source_key") != key or row.get("period_id") not in ids
    ]
    if confirmed:
        result["coverage"].extend(replacements)
    return result


def forecast_tables(result: ForecastResult, category: str):
    scenarios = result.scenarios
    summaries = [row for scenario in scenarios.values() for row in scenario.summaries if row["category"] == category]
    daily_maps, complete = {}, {}
    for name, scenario in scenarios.items():
        summary = next(row for row in scenario.summaries if row["category"] == category)
        complete[name] = summary["allocation_complete"]
        daily_maps[name] = (
            {row.date: row.scenario for row in scenario.projection.daily if row.category == category}
            if scenario.projection and summary["available"]
            else {}
        )
    daily = [
        {
            "date": day,
            "category": category,
            **{name: values.get(day) for name, values in daily_maps.items()},
            "typical_complete": complete["typical"],
            "higher_complete": complete["higher"],
        }
        for day in daily_maps["scheduled"]
    ]
    monthly = [row for scenario in scenarios.values() for row in scenario.monthly if row["category"] == category]
    allocations = [
        row for scenario in scenarios.values() for row in scenario.allocations if row["category"] == category
    ]
    events = [
        dict(asdict(event), forecast_scenario=name)
        for name, scenario in scenarios.items()
        if scenario.projection
        for event in scenario.projection.events
        if event.category == category and event.branch == "scenario"
    ]
    lots = [
        dict(asdict(lot), forecast_scenario=name)
        for name, scenario in scenarios.items()
        if scenario.projection
        for lot in scenario.projection.lots
        if lot.category == category and lot.branch == "scenario"
    ]
    return {
        "Summary": (summaries, SUMMARY_COLUMNS),
        "Monthly explanations": (monthly, MONTHLY_COLUMNS),
        "Daily closing balances": (daily, DAILY_COLUMNS),
        "Source transactions": (
            [row for row in result.source_transactions if row["category"] == category],
            SOURCE_COLUMNS,
        ),
        "Estimated allocations": (
            allocations,
            [
                ("scenario", "Scenario"),
                ("date", "Date"),
                ("category", "Category"),
                ("hours", "Hours"),
                ("timing", "Basis"),
                ("source_id", "Synthetic provenance"),
            ],
        ),
        "Events and expiration": (
            events,
            [
                ("forecast_scenario", "Scenario"),
                ("date", "Date"),
                ("category", "Category"),
                ("direction", "Direction"),
                ("hours", "Hours"),
                ("timing", "Basis"),
                ("original_transaction_id", "Original ID"),
                ("scenario_row_id", "Synthetic provenance"),
                ("explanation", "Explanation"),
            ],
        ),
        "Expiring lots": (
            lots,
            [
                ("forecast_scenario", "Scenario"),
                ("transaction_id", "Lot ID"),
                ("category", "Category"),
                ("last_eligible_usage_date", "Last eligible date"),
                ("remaining_hours", "Remaining (h)"),
                ("disposed_hours", "Disposed (h)"),
            ],
        ),
        "Warnings": (list(result.warnings), WARNING_COLUMNS),
    }


def csv_document(result, category, table_name, rows=None, columns=None):
    if rows is None:
        rows, columns = forecast_tables(result, category)[table_name]
    handle = io.StringIO(newline="")
    writer = csv.writer(handle)
    for label, value in (
        ("Schema version", result.schema_version),
        ("Method version", result.method_version),
        ("Source", result.source),
        (
            "Forecast cutoff (retrospective cutoffs are per-row)"
            if table_name.startswith("Retrospective")
            else "Cutoff",
            result.parameters.cutoff,
        ),
        (
            "Forecast horizon (retrospective horizons are per-row)"
            if table_name.startswith("Retrospective")
            else "Horizon",
            result.parameters.horizon,
        ),
        ("Units", "hours"),
        ("Category filter", category),
        ("Table", table_name),
        ("Parameters", asdict(result.parameters)),
        ("History inclusion and coverage", result.history),
        ("Assumptions", result.assumptions),
    ):
        writer.writerow([label, json.dumps(value, sort_keys=True) if isinstance(value, (dict, tuple, list)) else value])
    writer.writerow([])
    writer.writerow([label for key, label in columns])
    for row in rows:
        writer.writerow(
            [
                json.dumps(row.get(key), sort_keys=True)
                if isinstance(row.get(key), (dict, list, tuple))
                else row.get(key)
                for key, label in columns
            ]
        )
    return handle.getvalue()


def export_csv(path, snapshot, result, category, table_name, rows=None, columns=None):
    write_export(path, csv_document(result, category, table_name, rows, columns), snapshot)
