"""Exact break-analysis tables and guarded CSV exports, without Qt."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from fedleave.break_patterns import GROUPS

from .planning_model import write_export

INTERVAL_COLUMNS = [
    ("id", "Interval ID"),
    ("start", "Start"),
    ("end", "End"),
    ("calendar_days", "Calendar days"),
    ("fully_absent_workdays", "Fully absent scheduled workdays"),
    ("selected_hours", "Selected usage (h)"),
    ("other_hours", "Other-category context (h)"),
    ("substantial", "Meets selected threshold"),
    ("completed", "Completed recorded interval"),
    ("incomplete_start", "Leading boundary incomplete"),
    ("incomplete_end", "Trailing boundary incomplete"),
    ("at_cutoff", "Ongoing at cutoff"),
    ("timing", "Basis"),
    ("source_years", "Source years"),
    ("recorded_workdays", "Recorded workdays"),
    ("scheduled_workdays", "Scheduled workdays"),
    ("combined_fully_absent_workdays", "Recorded + scheduled continuation workdays"),
    ("continuation_of", "Continues recorded interval"),
    ("schedule_bases", "Schedule basis"),
    ("transaction_refs", "Original transaction references"),
]
DAY_COLUMNS = [
    ("date", "Date"),
    ("source_year", "Leave year"),
    ("timing", "Basis"),
    ("classification", "Selected absence classification"),
    ("scheduled_hours", "Scheduled hours"),
    ("selected_hours", "Selected hours"),
    ("other_hours", "Other-category hours"),
    ("known_selected_hours", "Known entered selected hours"),
    ("known_other_hours", "Known entered other hours"),
    ("coverage_confirmed", "Recorded coverage confirmed"),
    ("absence_ratio", "Selected coverage ratio (0–1)"),
    ("combined_absence_ratio", "Selected + other ratio (0–1)"),
    ("overbooked", "Hours above schedule"),
    ("unknown_reasons", "Unknown reasons"),
    ("schedule_basis", "Schedule basis"),
    ("selected_transaction_ids", "Selected transaction IDs"),
    ("other_transaction_ids", "Other transaction IDs"),
    ("source_key", "Source identity"),
]
TRANSACTION_COLUMNS = [
    ("source_year", "Source year"),
    ("id", "Original ID"),
    ("date", "Date"),
    ("category", "Category"),
    ("hours", "Used hours"),
    ("selected", "Selected grouping"),
    ("status", "Status"),
    ("timing", "Basis"),
    ("description", "Description"),
    ("source_key", "Source identity"),
]
DISTRIBUTION_COLUMNS = [
    ("label", "Fully absent scheduled workdays"),
    ("completed_count", "Completed bounded intervals"),
    ("incomplete_count", "Ongoing/truncated observed lengths"),
    ("basis", "Basis"),
]


def group_label(parameters):
    return GROUPS[parameters.grouping][0] if parameters.grouping in GROUPS else "Custom selected absence"


def break_tables(result):
    summary = result.summary
    summary_rows = [
        {"metric": label, "value": summary[key], "units": units, "basis": basis}
        for key, label, units, basis in (
            (
                "fully_absent_workdays",
                "Fully absent scheduled workdays",
                "workdays",
                "Selected grouping in covered recorded history",
            ),
            (
                "partially_absent_workdays",
                "Partially absent scheduled workdays",
                "workdays",
                "Selected grouping; other categories remain separate",
            ),
            (
                "selected_recorded_hours",
                "Selected usage in covered history",
                "hours",
                "Recorded Through Cutoff, not confirmed attendance",
            ),
            ("other_recorded_hours", "Other-category contextual usage", "hours", "Not added to the selected grouping"),
            (
                "qualifying_break_count",
                "Observed substantial breaks",
                "intervals",
                f"At least {result.parameters.substantial_workdays} fully absent scheduled workdays",
            ),
            (
                "median_completed_workdays",
                "Median completed break length",
                "workdays",
                "Completed, fully bounded recorded intervals only",
            ),
            (
                "completed_length_sample_count",
                "Completed length observations",
                "intervals",
                "Ongoing/truncated intervals excluded from median",
            ),
            (
                "time_since_status",
                "Time since last substantial break",
                "status",
                "Recorded history only; future bookings never reset it",
            ),
            (
                "last_completed_break_end",
                "Last completed substantial break ended",
                "date",
                "N/A for ongoing breaks or unknown intervening coverage",
            ),
            (
                "calendar_days_since",
                "Elapsed calendar days since break end",
                "calendar days",
                "Difference between cutoff and known completed end",
            ),
            (
                "scheduled_workdays_since",
                "Scheduled workdays since break end",
                "workdays",
                "Exposure, not confirmed attendance",
            ),
            (
                "contextual_other_hours_since",
                "Other-category usage since break end",
                "hours",
                "Sick/other smaller absences may occur within this gap",
            ),
            (
                "longest_gap_workdays",
                "Scheduled workdays between substantial breaks",
                "workdays",
                "Largest covered gap, including labeled observed boundaries; not attendance",
            ),
            (
                "longest_gap_start",
                "Largest covered gap starts",
                "date",
                "Inclusive; inspect gap table for partial history",
            ),
            ("longest_gap_end", "Largest covered gap ends", "date", "Inclusive; inspect gap table for partial history"),
            (
                "longest_gap_calendar_days",
                "Largest covered gap calendar duration",
                "calendar days",
                "Not charged leave hours",
            ),
            (
                "longest_gap_partial_history",
                "Largest covered gap touches observed boundary",
                "partial history",
                "Coverage gaps never join",
            ),
            (
                "longest_gap_other_hours",
                "Other-category usage in largest gap",
                "hours",
                "Contextual absence; not continuous attendance",
            ),
            (
                "covered_recorded_days",
                "Covered recorded calendar dates",
                "calendar days",
                "Known usage coverage and represented schedule",
            ),
            (
                "unknown_recorded_days",
                "Unknown recorded calendar dates",
                "calendar days",
                "Missing/stale usage, schedule or holiday context",
            ),
        )
    ]
    coverage = [
        {**row, **period, "periods": None}
        for row in result.coverage
        for period in row["periods"] or ({"period_id": None, "state": "Not selected"},)
    ]
    return {
        "Summary": (
            summary_rows,
            [("metric", "Metric"), ("value", "Value"), ("units", "Units"), ("basis", "Basis / limitation")],
        ),
        "Recorded breaks": (list(result.recorded), INTERVAL_COLUMNS),
        "Upcoming breaks": (list(result.upcoming), INTERVAL_COLUMNS),
        "Daily classification": (list(result.daily), DAY_COLUMNS),
        "Scheduled workday gaps": (
            list(result.gaps),
            [
                ("start", "Start"),
                ("end", "End"),
                ("scheduled_workdays", "Scheduled workdays"),
                ("calendar_days", "Calendar days"),
                ("selected_absence_hours", "Selected smaller absences (h)"),
                ("other_absence_hours", "Other-category context (h)"),
                ("partial_history", "Observed boundary / partial history"),
                ("basis", "Basis"),
                ("transaction_refs", "Original transactions"),
            ],
        ),
        "Break-length distribution": (list(result.distribution), DISTRIBUTION_COLUMNS),
        "Day distribution": (
            list(result.day_distribution),
            [("classification", "Classification"), ("days", "Recorded covered workdays / nonworking / unknown dates")],
        ),
        "Month and quarter timing": (
            list(result.timing),
            [
                ("basis", "Grouping"),
                ("period", "Period"),
                ("start", "Start"),
                ("end", "End"),
                ("full_days", "Fully absent workdays"),
                ("partial_days", "Partially absent workdays"),
                ("selected_hours", "Selected covered usage (h)"),
                ("other_hours", "Other-category context (h)"),
                ("unknown_days", "Unknown dates"),
                ("usage_covered_days", "Usage-covered dates"),
            ],
        ),
        "Source transactions": (list(result.transactions), TRANSACTION_COLUMNS),
        "Coverage": (
            coverage,
            [
                ("year", "Year"),
                ("selected", "Selected"),
                ("period_id", "Pay period"),
                ("start", "Start"),
                ("end", "End"),
                ("state", "Coverage"),
                ("schedule_basis", "Schedule basis"),
                ("work_schedule", "Represented work schedule"),
                ("holidays_enabled", "Nonworking holidays enabled"),
                ("holiday_coverage", "Cached calendar years"),
            ],
        ),
        "Warnings": (
            list(result.warnings),
            [
                ("code", "Warning"),
                ("year", "Source year"),
                ("date", "Date"),
                ("transaction_id", "Original ID"),
                ("message", "Explanation"),
            ],
        ),
    }


def csv_document(result, title, rows=None, columns=None):
    if rows is None:
        rows, columns = break_tables(result)[title]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for key, value in (
        ("Schema version", result.schema_version),
        ("Method", result.method_version),
        ("Source", result.source),
        ("Cutoff", result.parameters.cutoff),
        ("Group", group_label(result.parameters)),
        ("Categories", result.categories),
        (
            "Substantial break",
            f"At least {result.parameters.substantial_workdays} fully absent scheduled workdays in one calendar interval; user-selected analysis threshold, not an employment rule.",
        ),
        ("Parameters", asdict(result.parameters)),
        ("Coverage and schedule assumptions", result.coverage),
        ("Units", "hours, scheduled workdays and calendar days are distinct; ratios capped at 1 only"),
        (
            "Timing",
            "Recorded Through Cutoff does not establish attendance. Future bookings are Scheduled and cannot reset recorded metrics.",
        ),
        (
            "Interval boundaries",
            "Unknown coverage ends an interval. Ongoing/truncated lengths are lower bounds; completed-length statistics exclude them.",
        ),
        ("Table", title),
    ):
        writer.writerow([key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, list, tuple)) else value])
    writer.writerow([])
    writer.writerow([label for key, label in columns])
    for row in rows:
        writer.writerow(
            [
                json.dumps(row.get(key), sort_keys=True)
                if isinstance(row.get(key), (dict, list, tuple))
                else row.get(key)
                for key, _ in columns
            ]
        )
    return output.getvalue()


def export_csv(path, snapshot, result, title, rows=None, columns=None):
    write_export(path, csv_document(result, title, rows, columns), snapshot)
