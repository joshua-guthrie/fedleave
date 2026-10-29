"""Qt-independent planner session and presentation of the shared result contract."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Any

from fedleave.planning import (
    GENERAL_CATEGORIES,
    METHOD_VERSION,
    PLANNABLE_CATEGORIES,
    PlanningValidationError,
    ProjectionResult,
    Scenario,
    ScenarioOperation,
    export_scenario,
    fingerprint,
    import_scenario,
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
SUMMARY_COLUMNS = [
    ("category", "Category"),
    ("reserve", "Reserve (h)"),
    ("cutoff_balance", "Cutoff (h)"),
    ("baseline_horizon", "Baseline horizon (h)"),
    ("scenario_horizon", "Scenario horizon (h)"),
    ("baseline_minimum", "Baseline minimum (h)"),
    ("baseline_minimum_date", "Baseline minimum date"),
    ("scenario_minimum", "Scenario minimum (h)"),
    ("scenario_minimum_date", "Scenario minimum date"),
    ("baseline_breach", "Baseline first reserve breach"),
    ("baseline_reserve_shortfall", "Baseline first reserve shortfall (h)"),
    ("scenario_breach", "Scenario first reserve breach"),
    ("scenario_reserve_shortfall", "Scenario first reserve shortfall (h)"),
    ("baseline_negative_date", "Baseline first negative date"),
    ("baseline_shortfall", "Baseline first negative shortfall (h)"),
    ("negative_date", "Scenario first negative date"),
    ("shortfall", "Scenario first shortfall (h)"),
    ("baseline_pre_cap", "Baseline year-end pre-cap (h)"),
    ("scenario_pre_cap", "Scenario year-end pre-cap (h)"),
    ("baseline_carryover", "Baseline annual carryover (h)"),
    ("scenario_carryover", "Scenario annual carryover (h)"),
    ("baseline_forfeiture", "Baseline prospective forfeiture (h)"),
    ("scenario_forfeiture", "Scenario prospective forfeiture (h)"),
]
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


@contextmanager
def export_destination(path: Path, snapshot: dict):
    """Atomic user-requested output outside the canonical datastore.

    Replacing the output inode also avoids modifying an existing hard link to
    a ledger, even if that link was placed outside the datastore.
    """
    destination = path.expanduser().resolve()
    data_store = snapshot.get("calculation_context", {}).get("data_store")
    if data_store and destination.is_relative_to(Path(data_store).expanduser().resolve()):
        raise ValueError("Choose an export location outside the selected leave datastore.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=destination.parent, suffix=destination.suffix, delete=False
        ) as handle:
            temporary = Path(handle.name)
        yield temporary
        temporary.replace(destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def write_export(path: Path, text: str, snapshot: dict) -> None:
    with export_destination(path, snapshot) as temporary:
        temporary.write_text(text, encoding="utf-8", newline="")


def load_planning_snapshot(backend: Path, data_dir: str | None, year: int) -> dict:
    """Use the shared cached read-only CLI boundary for one planner load."""
    return ReadOnlySnapshotSource(backend, data_dir).snapshot(year)


class PlanningSession:
    """Session-only scenario edits; no datastore reference or ledger writer."""

    def __init__(
        self,
        snapshot: dict,
        *,
        today: date,
        definition: Scenario | dict | None = None,
        saved_fingerprint: str | None = None,
    ):
        self.snapshot = deepcopy(snapshot)
        self.today = today
        self.definition = (
            validate_scenario(self.snapshot, definition)
            if definition is not None
            else new_scenario(self.snapshot, today=today)
        )
        self.result: ProjectionResult | None = None
        self._saved_fingerprint = saved_fingerprint or fingerprint(self.definition.to_dict())

    @property
    def saved_fingerprint(self) -> str:
        return self._saved_fingerprint

    @property
    def modified(self) -> bool:
        return fingerprint(self.definition.to_dict()) != self._saved_fingerprint

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

    def export_json(self) -> str:
        return export_scenario(self.definition)

    def mark_saved(self) -> None:
        self._saved_fingerprint = fingerprint(self.definition.to_dict())

    def import_json(self, text: str, *, mode: str) -> None:
        candidate = import_scenario(self.snapshot, self.definition, text, mode=mode)
        self.set_definition(candidate)
        self.mark_saved()

    def rows(self, category: str) -> dict[str, tuple[list[dict], list[tuple[str, str]]]]:
        if self.result is None:
            return {}
        result = self.result
        summary = [
            {
                "category": row.category,
                "reserve": row.reserve,
                "cutoff_balance": row.baseline.cutoff_balance,
                "baseline_horizon": row.baseline.horizon_balance,
                "scenario_horizon": row.scenario.horizon_balance,
                "baseline_minimum": row.baseline.minimum_balance,
                "baseline_minimum_date": row.baseline.minimum_date,
                "scenario_minimum": row.scenario.minimum_balance,
                "scenario_minimum_date": row.scenario.minimum_date,
                "baseline_breach": row.baseline.first_reserve_breach,
                "baseline_reserve_shortfall": row.baseline.reserve_shortfall,
                "scenario_breach": row.scenario.first_reserve_breach,
                "scenario_reserve_shortfall": row.scenario.reserve_shortfall,
                "baseline_negative_date": row.baseline.earliest_negative_date,
                "baseline_shortfall": row.baseline.negative_shortfall,
                "negative_date": row.scenario.earliest_negative_date,
                "shortfall": row.scenario.negative_shortfall,
                "baseline_pre_cap": row.baseline.annual_pre_cap_balance,
                "scenario_pre_cap": row.scenario.annual_pre_cap_balance,
                "baseline_carryover": row.baseline.annual_carryover,
                "scenario_carryover": row.scenario.annual_carryover,
                "baseline_forfeiture": row.baseline.prospective_forfeiture,
                "scenario_forfeiture": row.scenario.prospective_forfeiture,
            }
            for row in result.categories
        ]
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
            "Summary": (summary, SUMMARY_COLUMNS),
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

    def csv_metadata(self, category: str, table: str) -> list[list[Any]]:
        return [
            ["Result schema version", self.result.schema_version if self.result else 1],
            ["Calculation method", METHOD_VERSION],
            ["Leave year", self.definition.source["leave_year"]],
            ["Scenario", self.definition.name],
            ["Cutoff", self.definition.cutoff],
            ["Horizon", self.definition.horizon],
            ["Units", "hours"],
            ["Category filter", category],
            ["Table", table],
            ["Reserve thresholds", json.dumps(self.definition.reserves, sort_keys=True)],
            [
                "Source identity",
                json.dumps(self.result.source if self.result else self.definition.source, sort_keys=True),
            ],
            [
                "Assumptions",
                json.dumps(self.result.assumptions if self.result else self.definition.assumptions, sort_keys=True),
            ],
            ["Scenario operations", json.dumps([asdict(row) for row in self.definition.operations], sort_keys=True)],
            [
                "Warnings",
                json.dumps([asdict(row) for row in self.result.warnings], sort_keys=True) if self.result else "[]",
            ],
        ]

    def export_csv(self, path: Path, category: str, table: str) -> None:
        if self.result is None:
            raise PlanningValidationError(
                [{"field": "result", "message": "Calculate a valid scenario before exporting results."}]
            )
        rows, columns = self.rows(category)[table]
        handle = io.StringIO(newline="")
        writer = csv.writer(handle)
        writer.writerows(self.csv_metadata(category, table))
        writer.writerow([label for _, label in columns])
        writer.writerows([[row.get(key) for key, _ in columns] for row in rows])
        write_export(path, handle.getvalue(), self.snapshot)
