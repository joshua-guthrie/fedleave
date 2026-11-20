"""Exact cumulative usage tables."""

from __future__ import annotations

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
