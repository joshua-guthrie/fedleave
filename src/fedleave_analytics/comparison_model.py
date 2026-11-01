"""Exact comparison tables, CSV metadata and safe export; no Qt dependency."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from fedleave.usage_comparison import ALIGNMENTS

from .planning_model import write_export

POINT_COLUMNS = [
    ("date", "Target date"),
    ("period_id", "Pay-period ordinal"),
    ("day_offset", "Day offset (zero-based)"),
    ("recorded", "Recorded Through Cutoff (h)"),
    ("scheduled", "Scheduled continuation total (h)"),
    ("future_scheduled_hours", "Future entered usage (h)"),
    ("observation_count", "Eligible reference years"),
    ("median", "Historical median (h)"),
    ("p20", "Historical 20th percentile (h)"),
    ("p80", "Historical 80th percentile (h)"),
    ("difference", "Difference from median (h)"),
    ("percentage_difference", "Difference (%)"),
    ("hours_per_100", "Recorded hours per 100 scheduled work hours"),
]
OBSERVATION_COLUMNS = [
    ("date", "Target alignment date"),
    ("year", "Source year"),
    ("role", "Role"),
    ("mapped_date", "Actual source date"),
    ("timing", "Basis"),
    ("hours", "Cumulative comparison hours"),
    ("known_entered_hours", "Known entered cumulative hours"),
    ("coverage_complete", "Coverage complete from year start"),
    ("missing_reason", "Missing / exclusion reason"),
    ("exposure_hours", "Scheduled work exposure (h)"),
    ("hours_per_100", "Hours per 100 scheduled work hours"),
    ("schedule_basis", "Schedule basis"),
    ("transaction_ids", "Original transaction IDs"),
    ("source_key", "Source identity"),
]
TRANSACTION_COLUMNS = [
    ("source_year", "Source year"),
    ("id", "Original transaction ID"),
    ("date", "Date"),
    ("category", "Category"),
    ("hours", "Used hours"),
    ("status", "Status"),
    ("timing", "Basis"),
    ("coverage_confirmed", "Date coverage confirmed"),
    ("description", "Description"),
    ("source_key", "Source identity"),
]


def comparison_tables(result):
    references = [
        (f"reference_{row['year']}", f"Reference {row['year']} (h)") for row in result.history if row["selected"]
    ]
    coverage = [
        {**row, **period, "periods": None}
        for row in result.history
        for period in row["periods"] or ({"period_id": None, "state": "Unavailable"},)
    ]
    return {
        "Summary": (
            [result.summary],
            [
                ("recorded", "Recorded (h)"),
                ("median", "Median (h)"),
                ("difference", "Difference (h)"),
                ("percentage_difference", "Difference (%)"),
                ("observation_count", "Reference count"),
                ("p20", "20th percentile (h)"),
                ("p80", "80th percentile (h)"),
                ("hours_per_100", "Hours / 100 work h"),
                ("date", "Cutoff"),
                *references,
                ("history_label", "History limitation"),
                ("target_missing_reason", "Target coverage limitation"),
            ],
        ),
        "Daily alignment": (list(result.points), [*POINT_COLUMNS, *references]),
        "Year details": (list(result.observations), OBSERVATION_COLUMNS),
        "Source transactions": (list(result.transactions), TRANSACTION_COLUMNS),
        "Coverage": (
            coverage,
            [
                (key, label)
                for key, label in (
                    ("year", "Year"),
                    ("target", "Target"),
                    ("selected", "Reference selected"),
                    ("start", "Period start"),
                    ("end", "Period end"),
                    ("period_id", "Pay period"),
                    ("state", "Coverage"),
                    ("aligned_cutoff", "Aligned cutoff"),
                    ("exclusion_reason", "Exclusion reason"),
                    ("schedule_basis", "Schedule basis"),
                )
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


def csv_document(result, table_name, rows=None, columns=None):
    if rows is None:
        rows, columns = comparison_tables(result)[table_name]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for key, value in (
        ("Schema version", result.schema_version),
        ("Method", result.method_version),
        ("Source", result.source),
        ("Alignment", ALIGNMENTS[result.parameters.alignment]),
        ("Cutoff", result.parameters.cutoff),
        ("Units", "hours; normalized metric = used hours per 100 scheduled work hours elapsed"),
        ("Parameters", asdict(result.parameters)),
        ("Historical coverage and schedule assumptions", result.history),
        (
            "Percentiles",
            "Linear interpolation: index = (n - 1) * p. Selected historical range, not a confidence interval.",
        ),
        (
            "Timing",
            "Recorded Through Cutoff does not prove leave was taken. Future target entries are Scheduled; later reference values are historical context.",
        ),
        ("Table", table_name),
    ):
        writer.writerow([key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, tuple, list)) else value])
    writer.writerow([])
    writer.writerow([label for key, label in columns])
    for row in rows:
        writer.writerow(
            [
                json.dumps(row.get(key), sort_keys=True)
                if isinstance(row.get(key), (list, tuple, dict))
                else row.get(key)
                for key, _ in columns
            ]
        )
    return output.getvalue()


def export_csv(path, snapshot, result, table_name, rows=None, columns=None):
    write_export(path, csv_document(result, table_name, rows, columns), snapshot)
