import csv
import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from fedleave.planning import PlanningValidationError
from fedleave_analytics.planning_model import PlanningSession, category_options, load_planning_snapshot, write_export
from test_planning import TODAY, category, operation, scenario, snapshot


def test_session_delete_reset_dirty_indicator_and_atomic_import():
    source = snapshot()
    before = deepcopy(source)
    session = PlanningSession(source, today=TODAY, definition=replace(scenario(source), reserves={"annual": 80}))
    assert not session.modified
    session.set_operations((operation(source, operation="replace", original_ids=("scheduled",)),))
    assert session.modified
    assert category(session.calculate()).scenario.horizon_balance == 84
    encoded = session.export_json()
    session.mark_saved()
    assert not session.modified
    session.delete_operation("tentative")
    assert category(session.calculate()).scenario.horizon_balance == 92
    session.import_json(encoded, mode="replace")
    assert not session.modified
    before_import = session.definition.to_dict()
    with pytest.raises(PlanningValidationError):
        session.import_json(encoded, mode="merge")
    assert session.definition.to_dict() == before_import
    session.reset()
    result = session.calculate()
    assert category(result).baseline == category(result).scenario
    assert session.definition.reserves == {"annual": 80}
    assert source == before


def test_models_tables_and_csv_use_the_same_result_with_filters_and_assumptions(tmp_path):
    source = snapshot()
    session = PlanningSession(
        source,
        today=TODAY,
        definition=replace(scenario(source), operations=(operation(source),), reserves={"annual": 80}),
    )
    session.calculate()
    rows = session.rows("annual")
    annual = next(row for row in rows["Summary"][0] if row["category"] == "annual")
    daily = rows["Daily closing balances"][0]
    assert daily[-1]["scenario"] == annual["scenario_horizon"] == 68
    assert min(row["scenario"] for row in daily) == annual["scenario_minimum"]
    assert any(
        row["scenario_row_id"] == "tentative" and row["timing"] == "Tentative"
        for row in rows["Events and provenance"][0]
    )
    path = tmp_path / "daily.csv"
    session.export_csv(path, "annual", "Daily closing balances")
    with path.open(newline="", encoding="utf-8") as handle:
        exported = list(csv.reader(handle))
    assert ["Cutoff", "2026-07-01"] in exported
    assert ["Horizon", "2026-07-31"] in exported
    assert ["Units", "hours"] in exported
    assert ["Category filter", "annual"] in exported
    assert any(row[0] == "Assumptions" and "closing balances" in row[1] for row in exported)
    assert exported[-1] == ["2026-07-31", "annual", "92.0", "68.0", "-24.0"]


def test_historical_cutoff_limitation_is_in_scenario_json():
    source = snapshot()
    session = PlanningSession(source, today=TODAY, definition=scenario(source))
    assert "presently available leave records" in session.export_json()
    assert json.loads(session.export_json())["source"]["snapshot_fingerprint"]


def test_category_choices_distinguish_purpose_restrictions_and_exclude_work_tracking():
    choices = dict(category_options())
    assert "overtime" not in choices
    assert "fmla" not in choices
    assert "purpose restricted" not in choices["annual"]
    for category_name in ("sick", "military", "court", "religious_comp", "ppl"):
        assert "purpose restricted" in choices[category_name]


def test_export_rejects_datastore_targets_and_does_not_follow_hard_links(tmp_path):
    data = tmp_path / "store"
    data.mkdir()
    ledger = data / "ledger.json"
    ledger.write_text("canonical bytes")
    source = snapshot()
    source["calculation_context"]["data_store"] = str(data)
    with pytest.raises(ValueError, match="outside"):
        write_export(ledger, "scenario", source)
    assert ledger.read_text() == "canonical bytes"
    alias = tmp_path / "chosen-export.json"
    os.link(ledger, alias)
    write_export(alias, "scenario definition", source)
    assert alias.read_text() == "scenario definition"
    assert ledger.read_text() == "canonical bytes"


def test_loader_uses_exact_backend_years_discovery_and_single_snapshot(monkeypatch):
    source = snapshot()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        payload = {"years": [{"leave_year": 2026, "valid": True}]} if command[1] == "years" else source
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr("fedleave_analytics.planning_model.subprocess.run", run)
    result = load_planning_snapshot(Path("/selected/backend"), "/selected data with spaces", 2026)
    assert calls == [
        ["/selected/backend", "years", "--json", "--data-dir", "/selected data with spaces"],
        ["/selected/backend", "snapshot", "--year", "2026", "--json", "--data-dir", "/selected data with spaces"],
    ]
    assert result["calculation_context"]["backend"] == "/selected/backend"
    calls.clear()
    with pytest.raises(RuntimeError, match="not initialized"):
        load_planning_snapshot(Path("/selected/backend"), "/selected data with spaces", 2027)
    assert len(calls) == 1


def test_loader_failure_never_falls_back_or_changes_active_scenario(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "selected store unavailable"})()

    monkeypatch.setattr("fedleave_analytics.planning_model.subprocess.run", run)
    with pytest.raises(RuntimeError, match="selected store unavailable"):
        load_planning_snapshot(Path("/selected/backend"), "/selected store", 2026)
    assert len(calls) == 1
