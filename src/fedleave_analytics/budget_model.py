"""Presentation/export/transfer of the one pure budget result contract."""

import csv
import io
import json
from dataclasses import asdict, replace

from fedleave.budget import STRATEGIES
from fedleave.planning import export_scenario, import_scenario, source_identity, validate_scenario

from .planning_model import (
    DAILY_COLUMNS,
    SUMMARY_COLUMNS,
    WARNING_COLUMNS,
    PlanningSession,
    projection_summary,
    write_export,
)

DEADLINE_COLUMNS = [
    ("category", "Category"),
    ("deadline", "Inclusive deadline"),
    ("required_hours", "Additional required (h)"),
    ("allocated_hours", "Suggested (h)"),
    ("after_required_hours", "After suggestion risk (h)"),
    ("feasibility", "Feasibility / scope"),
    ("remaining_at_cutoff", "Cutoff remaining (h)"),
    ("scheduled_hours", "Scheduled eligible (h)"),
    ("periods_remaining", "Usable pay periods"),
    ("usable_work_hours", "Usable work hours"),
    ("shared_capacity_at_priority", "Shared capacity at deadline priority (h)"),
    ("average_hours_per_period", "Unrounded average h/period"),
    ("outcome", "Configured outcome"),
    ("lot_id", "Lot ID"),
    ("original_hours", "Original hours"),
    ("local_hours", "Local lot hours"),
    ("other_disposals", "Other known disposals (h)"),
    ("constraint", "Constraint"),
    ("earned_date", "Original earned date"),
    ("available_from", "Available from"),
    ("known_remaining_at_boundary", "Known remaining at boundary (h)"),
    ("past_at_risk_hours", "Past unresolved risk (h)"),
    ("past_disposed_hours", "Past disposed (h)"),
    ("deadline_derivation", "Deadline derivation"),
    ("pre_cap_balance", "Annual pre-cap (h)"),
    ("cap", "Cap (h)"),
    ("id", "Obligation ID"),
]
CUMULATIVE_COLUMNS = [
    ("deadline", "Deadline"),
    ("required_hours", "Cumulative required (h)"),
    ("available_hours", "Feasibly allocated (h)"),
    ("dated_capacity_bound_hours", "Dated capacity upper bound (h)"),
    ("joint_capacity_shortfall_hours", "Joint capacity shortfall (h)"),
    ("work_capacity_hours", "Shared work capacity (h)"),
    ("shortfall_hours", "Unallocated (h)"),
    ("capacity_basis", "Constraint basis"),
]
SUGGESTION_COLUMNS = [
    (key, title)
    for key, title in (
        ("date", "Suggested date"),
        ("period_id", "Pay period"),
        ("category", "Category"),
        ("hours", "Suggested hours"),
        ("deadline", "Deadline"),
        ("lot_id", "Lot ID"),
        ("obligation_id", "Obligation ID"),
        ("id", "Synthetic row ID"),
        ("strategy", "Strategy"),
        ("provenance", "Provenance"),
    )
]
DATE_COLUMNS = [
    (key, title)
    for key, title in (
        ("date", "Date"),
        ("period_id", "Pay period"),
        ("work_hours", "Work hours"),
        ("scheduled_hours", "Existing absence (h)"),
        ("suggested_hours", "Suggested (h)"),
        ("remaining_capacity", "Remaining capacity (h)"),
        ("reason", "Capacity basis"),
    )
]
PERIOD_COLUMNS = [
    ("period_id", "Pay period"),
    ("start", "Start"),
    ("end", "End"),
    ("partial_current", "Partial current period"),
    *[
        (c, c.replace("_", " ").title() + " (h)")
        for c in ("annual", "comp", "travel_comp", "restored_annual", "time_off_award", "credit")
    ],
    ("suggested_hours", "Total suggested (h)"),
    ("remaining_capacity", "Remaining capacity (h)"),
]


def result_views(result):
    summary = (projection_summary(result.after), SUMMARY_COLUMNS)
    audit = [
        {
            "section": row.get("section"),
            "id": row.get("id", row.get("transaction_id")),
            "detail": json.dumps(row, sort_keys=True),
        }
        for row in result.audit
    ]
    return {
        "Deadlines": (list(result.deadlines), DEADLINE_COLUMNS),
        "Credit cap timeline": (
            [r for r in result.deadlines if r["category"] == "credit"],
            [
                ("deadline", "Period deadline"),
                ("period_id", "Pay period"),
                ("pre_cap_balance", "Projected pre-cap (h)"),
                ("cap", "Credit cap (h)"),
                ("known_disposal", "Known next-day disposal (h)"),
                ("required_hours", "Additional required (h)"),
                ("allocated_hours", "Suggested (h)"),
                ("after_required_hours", "After suggestion risk (h)"),
                ("outcome", "Policy / limitation"),
                ("feasibility", "Feasibility"),
            ],
        ),
        "Suggested pay periods": (list(result.periods), PERIOD_COLUMNS),
        "Suggested dates": (list(result.suggestions), SUGGESTION_COLUMNS),
        "Daily capacity": (list(result.dates), DATE_COLUMNS),
        "Cumulative deadlines": (list(result.cumulative), CUMULATIVE_COLUMNS),
        "Before and after balances": summary,
        "Daily balances": ([asdict(r) for r in result.after.daily], DAILY_COLUMNS),
        "Source and allocation audit": (
            audit,
            [("section", "Section"), ("id", "Source ID"), ("detail", "Exact audit JSON")],
        ),
        "Warnings": ([asdict(w) for w in result.warnings], WARNING_COLUMNS),
    }


def export_csv(path, snapshot, result, view):
    rows, columns = result_views(result)[view]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for key, value in dict(
        schema_version=result.schema_version,
        method_version=result.method_version,
        source=result.source,
        parameters=asdict(result.parameters),
        strategy=STRATEGIES[result.parameters.strategy],
        units="hours",
        assumptions=result.assumptions,
        state=result.state,
        required_hours=result.required_hours,
        allocated_hours=result.allocated_hours,
        unallocated_hours=result.unallocated_hours,
        first_infeasible_deadline=result.first_infeasible_deadline,
        warning_codes=[w.code for w in result.warnings],
        table=view,
    ).items():
        writer.writerow(["# " + key, json.dumps(value, sort_keys=True)])
    writer.writerow([title for _, title in columns])
    for row in rows:
        writer.writerow(
            [
                "N/A"
                if row.get(key) is None
                else json.dumps(row[key], sort_keys=True)
                if isinstance(row[key], (dict, list, tuple))
                else row[key]
                for key, _ in columns
            ]
        )
    write_export(path, stream.getvalue(), snapshot)


def transfer_session(fresh, result, *, today, current=None, mode="replace"):
    """Validate all material context before constructing an atomic in-memory candidate."""
    if source_identity(fresh) != result.source:
        raise ValueError(
            "STALE_SNAPSHOT: Source records or calculation context changed. Refresh and recalculate Leave Budget before transfer."
        )
    definition = validate_scenario(fresh, result.scenario)
    if mode == "merge":
        if current is None:
            raise ValueError("A current scenario is required for merge.")
        current = validate_scenario(fresh, current)
        # Keep budget-specific projection assumptions when combining existing operations.
        current = replace(current, assumptions={**current.assumptions, **definition.assumptions})
        definition = import_scenario(fresh, current, export_scenario(definition), mode="merge")
    elif mode != "replace":
        raise ValueError("Choose Replace or Merge explicitly.")
    candidate = PlanningSession(fresh, today=today, definition=definition)
    candidate.calculate()
    if mode == "replace" and (
        candidate.result.daily != result.after.daily or candidate.result.categories != result.after.categories
    ):
        raise ValueError("Transfer projection differs from Leave Budget. No scenario was changed.")
    return candidate
