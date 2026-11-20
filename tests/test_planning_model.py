import json
from copy import deepcopy
from dataclasses import replace

import pytest

from fedleave_analytics.planning_model import PlanningSession, category_options, load_planning_snapshot
from test_planning import TODAY, category, operation, scenario, snapshot, tx


def test_session_delete_reset_and_recalculate():
    source = snapshot()
    before = deepcopy(source)
    session = PlanningSession(source, today=TODAY, definition=replace(scenario(source), reserves={"annual": 80}))
    replacement = operation(source, operation="replace", original_ids=("scheduled",))
    session.set_operations((replacement,))
    assert category(session.calculate()).scenario.horizon_balance == 84
    session.delete_operation("tentative")
    assert category(session.calculate()).scenario.horizon_balance == 92
    session.set_operations((replacement,))
    session.reset()
    result = session.calculate()
    assert category(result).baseline == category(result).scenario
    assert session.definition.reserves == {"annual": 80}
    assert source == before


def test_model_tables_use_the_same_result_with_filters():
    source = snapshot()
    session = PlanningSession(
        source,
        today=TODAY,
        definition=replace(scenario(source), operations=(operation(source),), reserves={"annual": 80}),
    )
    session.calculate()
    rows = session.rows("annual")
    annual = next(row for row in rows["Summary"][0] if row["category"] == "Annual leave")
    daily = rows["Daily closing balances"][0]
    assert daily[-1]["baseline"] == annual["horizon_balance"] == 92
    assert min(row["baseline"] for row in daily) == annual["minimum_balance"]
    assert daily[-1]["scenario"] == 68
    assert any(
        row["scenario_row_id"] == "tentative" and row["timing"] == "Tentative"
        for row in rows["Events and provenance"][0]
    )


def test_historical_cutoff_limitation_is_in_scenario_assumptions():
    source = snapshot()
    session = PlanningSession(source, today=TODAY, definition=scenario(source))
    assert "presently available leave records" in str(session.definition.assumptions)
    assert session.definition.source["snapshot_fingerprint"]


def test_category_choices_distinguish_purpose_restrictions_and_exclude_work_tracking():
    choices = dict(category_options())
    assert "overtime" not in choices
    assert "fmla" not in choices
    assert "purpose restricted" not in choices["annual"]
    for category_name in ("sick", "military", "court", "religious_comp", "ppl"):
        assert "purpose restricted" in choices[category_name]


@pytest.fixture
def selected_backend(tmp_path):
    backend = tmp_path / "backend.exe"
    backend.touch()
    return backend.resolve()


def test_loader_uses_exact_backend_years_discovery_and_single_snapshot(monkeypatch, selected_backend):
    source = snapshot()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        payload = {"years": [{"leave_year": 2026, "valid": True}]} if command[1] == "years" else source
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr("fedleave_analytics.snapshots.subprocess.run", run)
    backend = selected_backend
    result = load_planning_snapshot(backend, "/selected data with spaces", 2026)
    assert calls == [
        [str(backend), "years", "--json", "--data-dir", "/selected data with spaces"],
        [str(backend), "snapshot", "--year", "2026", "--json", "--data-dir", "/selected data with spaces"],
    ]
    assert result["calculation_context"]["backend"] == str(backend)
    calls.clear()
    with pytest.raises(RuntimeError, match="not initialized"):
        load_planning_snapshot(backend, "/selected data with spaces", 2027)
    assert len(calls) == 1


def test_loader_failure_never_falls_back_or_changes_active_scenario(monkeypatch, selected_backend):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "selected store unavailable"})()

    monkeypatch.setattr("fedleave_analytics.snapshots.subprocess.run", run)
    with pytest.raises(RuntimeError, match="selected store unavailable"):
        load_planning_snapshot(selected_backend, "/selected store", 2026)
    assert len(calls) == 1


def test_planner_summary_is_baseline_four_columns_with_latest_minimum_date_and_filters():
    source = snapshot()
    source["annual_leave_accrual_hours"] = 0
    source["starting_balances"] = {"annual": 100, "lwop": 8, "excused": 8, "holiday": 8, "sick": 0}
    source["transactions"] = [
        tx("use-one", "2026-07-10", "annual", "used", 8),
        tx("earn-back", "2026-07-15", "annual", "earned", 8),
        tx("use-two", "2026-07-20", "annual", "used", 8),
    ]
    session = PlanningSession(source, today=TODAY, definition=scenario(source))
    session.calculate()

    rows, columns = session.rows("annual")["Summary"]
    assert [label for _key, label in columns] == [
        "Leave Type",
        "Balance on 2026-07-31",
        "Starting Balance",
        "Min Balance",
        "Min Balance Date",
    ]
    labels = {row["category"] for row in rows}
    assert "Annual leave" in labels
    assert not {"Leave without pay", "Excused", "Holiday", "Sick"} & labels
    annual = next(row for row in rows if row["category"] == "Annual leave")
    assert annual == {
        "category": "Annual leave",
        "horizon_balance": 92,
        "starting_balance": 100,
        "minimum_balance": 92,
        "minimum_date": "2026-07-31",
    }
