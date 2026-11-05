"""Exact cumulative usage tables, CSV metadata and safe export; no Qt dependency."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from .planning_model import write_export

POINT_COLUMNS = [
    ("date", "Date"),
    ("hours", "Cumulative used hours (h)"),
]
TRANSACTION_COLUMNS = [
    ("source_year", "Source year"),
    ("id", "Original transaction ID"),
    ("date", "Date"),
    ("category", "Category"),
    ("hours", "Used hours"),
    ("status", "Status"),
    ("description", "Description"),
]


def cumulative_tables(result):
    return {
        "Cumulative usage": (list(result.points), POINT_COLUMNS),
        "Source transactions": (list(result.transactions), TRANSACTION_COLUMNS),
    }


def csv_document(result, table_name, rows=None, columns=None):
    if rows is None:
        rows, columns = cumulative_tables(result)[table_name]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for key, value in (
        ("Schema version", result.schema_version),
        ("Method", result.method_version),
        ("Source", result.source),
        ("Units", "hours; cumulative effective used hours from the leave-year start"),
        ("Parameters", asdict(result.parameters)),
        ("Summary", result.summary),
        ("Table", table_name),
    ):
        writer.writerow([key, json.dumps(value, sort_keys=True) if isinstance(value, (dict, tuple, list)) else value])
    writer.writerow([])
    writer.writerow([label for _key, label in columns])
    for row in rows:
        writer.writerow(
            [
                json.dumps(row.get(key), sort_keys=True)
                if isinstance(row.get(key), (list, tuple, dict))
                else row.get(key)
                for key, _label in columns
            ]
        )
    return output.getvalue()


def export_csv(path, snapshot, result, table_name, rows=None, columns=None):
    write_export(path, csv_document(result, table_name, rows, columns), snapshot)
