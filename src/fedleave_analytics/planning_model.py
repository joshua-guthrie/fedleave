"""Qt-independent planner session and presentation of the shared result contract."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Any

from fedleave.planning import (
    GENERAL_CATEGORIES,
    PLANNABLE_CATEGORIES,
    ProjectionResult,
    Scenario,
    ScenarioOperation,
    new_scenario,
    project,
    validate_scenario,
)

from .snapshots import ReadOnlySnapshotSource

LABELS = {
    "annual": "Annual leave",
    "credit": "Credit hours",
    "comp": "Comp time",
    "travel_comp": "Travel comp",
    "restored_annual": "Restored annual leave",
    "time_off_award": "Time-off award",
    "ppl": "Paid parental leave",
    "religious_comp": "Religious comp",
    "lwop": "Leave without pay",
}
DAILY_COLUMNS = [
    ("date", "Date"),
    ("category", "Category"),
    ("baseline", "Baseline closing (h)"),
    ("scenario", "Scenario closing (h)"),
    ("delta", "Delta (h)"),
]
EVENT_COLUMNS = [
    ("date", "Date"),
    ("branch", "Projection"),
    ("timing", "Event kind"),
    ("category", "Category"),
    ("direction", "Direction"),
    ("hours", "Hours"),
    ("signed_hours", "Balance effect (h)"),
    ("status", "Status"),
    ("id", "Event ID"),
    ("original_transaction_id", "Original transaction ID"),
    ("scenario_row_id", "Scenario row ID"),
    ("targeted_ids", "Targeted originals"),
    ("earned_transaction_id", "Earned lot ID"),
    ("explanation", "Explanation"),
]
CAPACITY_COLUMNS = [
    ("date", "Date"),
    ("work_hours", "Working capacity (h)"),
    ("baseline_scheduled", "Baseline scheduled (h)"),
    ("scenario_scheduled", "Scenario scheduled (h)"),
    ("remaining_capacity", "Remaining capacity (h)"),
    ("tentative_by_category", "Tentative hours by category"),
    ("total_proposed_absence", "Total proposed absence (h)"),
    ("excess_hours", "Capacity excess (h)"),
]
LOT_COLUMNS = [
    ("branch", "Projection"),
    ("transaction_id", "Lot ID"),
    ("category", "Category"),
    ("earned_date", "Earned date"),
    ("last_eligible_usage_date", "Last eligible use date"),
    ("remaining_hours", "Remaining available (h)"),
    ("disposed_hours", "Derived disposal (h)"),
]
WARNING_COLUMNS = [
    ("code", "Code"),
    ("branch", "Projection"),
    ("date", "Date"),
    ("category", "Category"),
    ("row_id", "Scenario row"),
    ("transaction_id", "Transaction ID"),
    ("message", "Message"),
]


def category_options() -> list[tuple[str, str]]:
    return [
        (
            category,
            LABELS.get(category, category.replace("_", " ").title())
            + (" (purpose restricted)" if category not in GENERAL_CATEGORIES else ""),
        )
        for category in PLANNABLE_CATEGORIES
    ]


def load_planning_snapshot(backend: Path, data_dir: str | None, year: int) -> dict:
    """Use the shared cached read-only CLI boundary for one planner load."""
    return ReadOnlySnapshotSource(backend, data_dir).snapshot(year)


def category_label(category: str) -> str:
    return LABELS.get(category, category.replace("_", " ").title())


PLANNER_SUMMARY_HIDDEN = frozenset({"excused", "holiday", "lwop"})


def planner_summary(result) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Four-column baseline summary for the What-if Planner results tab."""
    comparisons = {row.category: row for row in result.categories}
    baseline_daily: dict[str, list[tuple[str, float]]] = {}
    for row in result.daily:
        if row.baseline is not None:
            baseline_daily.setdefault(row.category, []).append((row.date, float(row.baseline)))
    rows = []
    for category in sorted(comparisons):
        if category in PLANNER_SUMMARY_HIDDEN:
            continue
        points = baseline_daily.get(category, [])
        if not any(value > 0 for _day, value in points):
            continue
        comparison = comparisons[category].baseline
        if points:
            minimum = min(value for _day, value in points)
            minimum_date = max(day for day, value in points if abs(value - minimum) <= 1e-9)
        else:
            minimum, minimum_date = comparison.minimum_balance, comparison.minimum_date
        rows.append(
            {
                "category": category_label(category),
                "horizon_balance": comparison.horizon_balance,
                "starting_balance": comparison.cutoff_balance,
                "minimum_balance": minimum,
                "minimum_date": minimum_date,
            }
        )
    columns = [
        ("category", "Leave Type"),
        ("horizon_balance", f"Balance on {result.horizon}"),
        ("starting_balance", "Starting Balance"),
        ("minimum_balance", "Min Balance"),
        ("minimum_date", "Min Balance Date"),
    ]
    return rows, columns


class PlanningSession:
    """Session-only scenario edits; no datastore reference or ledger writer."""

    def __init__(
        self,
        snapshot: dict,
        *,
        today: date,
        definition: Scenario | dict | None = None,
    ):
        self.snapshot = deepcopy(snapshot)
        self.today = today
        self.definition = (
            validate_scenario(self.snapshot, definition)
            if definition is not None
            else new_scenario(self.snapshot, today=today)
        )
        self.result: ProjectionResult | None = None

    def set_definition(self, document: Scenario | dict) -> None:
        validated = validate_scenario(self.snapshot, document)
        self.definition, self.result = validated, None

    def set_operations(self, operations: tuple[ScenarioOperation, ...]) -> None:
        self.set_definition(replace(self.definition, operations=operations))

    def delete_operation(self, row_id: str) -> None:
        self.set_operations(tuple(row for row in self.definition.operations if row.row_id != row_id))

    def reset(self) -> None:
        self.set_operations(())

    def calculate(self) -> ProjectionResult:
        self.result = project(self.snapshot, self.definition, today=self.today)
        return self.result

    def rows(self, category: str) -> dict[str, tuple[list[dict], list[tuple[str, str]]]]:
        if self.result is None:
            return {}
        result = self.result
        summary, summary_columns = planner_summary(result)
        events = [asdict(row) for row in result.events if row.category == category]
        originals = {str(row.get("id")): row for row in self.snapshot.get("transactions", [])}
        for operation in result.operations:
            for transaction_id in operation.original_ids:
                transaction = originals[transaction_id]
                if transaction["category"] == category:
                    events.append(
                        {
                            "id": f"scenario:{operation.row_id}:suppressed:{transaction_id}",
                            "date": transaction["date"],
                            "branch": "scenario",
                            "timing": "Removed in scenario",
                            "category": category,
                            "direction": "suppressed",
                            "hours": transaction["hours"],
                            "signed_hours": 0,
                            "status": transaction.get("status", "planned"),
                            "original_transaction_id": transaction_id,
                            "scenario_row_id": operation.row_id,
                            "targeted_ids": operation.original_ids,
                            "earned_transaction_id": transaction.get("earned_transaction_id"),
                            "explanation": "Original remains in the baseline; suppressed only in this scenario.",
                        }
                    )
        for row in events:
            row["targeted_ids"] = ", ".join(row["targeted_ids"])
        capacity = [asdict(row) for row in result.capacity]
        for row in capacity:
            row["tentative_by_category"] = json.dumps(row["tentative_by_category"], sort_keys=True)
        return {
            "Summary": (summary, summary_columns),
            "Daily closing balances": (
                [asdict(row) for row in result.daily if row.category == category],
                DAILY_COLUMNS,
            ),
            "Events and provenance": (
                sorted(events, key=lambda row: (row["date"], row["branch"], row["id"])),
                EVENT_COLUMNS,
            ),
            "Working-hour capacity": (capacity, CAPACITY_COLUMNS),
            "Expiring lots": ([asdict(row) for row in result.lots if row.category == category], LOT_COLUMNS),
            "Warnings": ([asdict(row) for row in result.warnings], WARNING_COLUMNS),
        }
