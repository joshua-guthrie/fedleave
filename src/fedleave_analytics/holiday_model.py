"""Exact option tables and exports shared by the view and chart windows."""

import csv
import io
import json
from dataclasses import asdict

from .planning_model import DAILY_COLUMNS, SUMMARY_COLUMNS, WARNING_COLUMNS, projection_summary, write_export

OPTION_COLUMNS = [
    ("start", "Start"),
    ("end", "End"),
    ("label", "Option"),
    ("calendar_days", "Calendar days away"),
    ("additional_hours", "Additional required (h)"),
    ("state", "Funding feasibility"),
    ("efficiency", "Calendar days / additional standard day"),
    ("workdays", "Scheduled workdays off"),
    ("unfunded_hours", "Unfunded (h)"),
    ("existing_hours", "Existing Scheduled (h)"),
    ("existing_discretionary_hours", "Existing discretionary (h)"),
    ("existing_other_hours", "Other-purpose dependency (h)"),
    ("funding_by_category", "Proposed category funding (h)"),
    ("expiring_hours", "Expiring hours used before deadline"),
    ("standard_day_hours", "Assumed standard day (h)"),
    ("minimum_balances", "Baseline / scenario minimum balances and dates"),
    ("ending_balances", "Baseline / scenario year-end balances (h)"),
    ("reserve_flags", "First reserve breach dates"),
    ("annual_forfeiture_reduction", "Annual use-or-lose reduction (h)"),
    ("reasons", "Constraints"),
    ("mixed_purpose", "Mixed-purpose dependency"),
    ("boundary_truncated", "Search boundary truncation"),
    ("id", "Option ID"),
]
DAY_COLUMNS = [
    (key, title)
    for key, title in (
        ("date", "Date"),
        ("scheduled_hours", "Scheduled work (h)"),
        ("reason", "Schedule basis"),
        ("holiday", "Nonworking holiday"),
        ("existing_discretionary_hours", "Existing discretionary (h)"),
        ("existing_other_hours", "Other-purpose Scheduled (h)"),
        ("additional_hours", "Additional required (h)"),
        ("proposed_hours", "Proposed funded (h)"),
        ("funding", "Daily category / lot funding"),
        ("transaction_ids", "Original transaction IDs"),
        ("overbooked", "Existing hours above schedule"),
    )
]
FUNDING_COLUMNS = [
    ("date", "Proposed date"),
    ("category", "Category"),
    ("hours", "Proposed hours"),
    ("lot_id", "Original lot ID"),
    ("deadline", "Inclusive expiration deadline"),
    ("row_id", "Scenario row ID"),
]


def result_views(result, selected=None):
    views = {
        "Options": (
            [dict(option.metrics, source_index=i) for i, option in enumerate(result.candidates)],
            OPTION_COLUMNS,
        ),
        "No leave required": (
            list(result.no_leave),
            [
                ("start", "Start"),
                ("end", "End"),
                ("calendar_days", "Calendar days"),
                ("label", "Section"),
                ("boundary_truncated", "Boundary truncation"),
            ],
        ),
        "Search calendar": (list(result.daily), DAY_COLUMNS),
        "Warnings": ([asdict(w) for w in result.warnings], WARNING_COLUMNS),
        "Assumptions": (
            [{"key": k, "value": v} for k, v in result.assumptions.items()],
            [("key", "Assumption"), ("value", "Value")],
        ),
    }
    if selected is not None:
        option = result.candidates[selected]
        views.update(
            {
                "Selected days": (list(option.days), DAY_COLUMNS),
                "Selected funding": (list(option.funding), FUNDING_COLUMNS),
                "Before and after balances": (projection_summary(option.after), SUMMARY_COLUMNS),
                "Daily balances": ([asdict(r) for r in option.after.daily], DAILY_COLUMNS),
                "Selected warnings": ([asdict(w) for w in option.after.warnings], WARNING_COLUMNS),
            }
        )
    return views


def export_csv(path, snapshot, result, title, selected=None):
    rows, columns = result_views(result, selected)[title]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for key, value in dict(
        schema=result.schema_version,
        method=result.method_version,
        source=result.source,
        parameters=asdict(result.parameters),
        assumptions=result.assumptions,
        selected_option=result.candidates[selected].metrics if selected is not None else None,
        enumerated=result.enumerated_count,
        evaluated=result.evaluated_count,
        table=title,
    ).items():
        writer.writerow(["# " + key, json.dumps(value, sort_keys=True, allow_nan=False)])
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow(
            [
                ""
                if row.get(key) is None
                else json.dumps(row[key], sort_keys=True, allow_nan=False)
                if isinstance(row[key], (list, tuple, dict))
                else row[key]
                for key, _ in columns
            ]
        )
    write_export(path, stream.getvalue(), snapshot)
