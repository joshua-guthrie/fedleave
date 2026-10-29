import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest

from fedleave_analytics.forecast_model import csv_document, export_csv, forecast_tables, update_coverage
from fedleave_analytics.preferences import load_preferences, save_preferences
from fedleave_analytics.snapshots import ReadOnlySnapshotSource
from test_forecast import confirmations, references, run, source


@pytest.fixture
def preferences_file(tmp_path, monkeypatch):
    path = tmp_path / "gui/preferences.json"
    monkeypatch.setattr("fedleave_analytics.preferences.analytics_preferences_path", lambda: path)
    return path


def test_preferences_are_versioned_outside_datastore_and_scoped_to_source(preferences_file, tmp_path):
    snapshot = source()
    datastore = tmp_path / "leave data"
    datastore.mkdir()
    ledger = datastore / "canonical.json"
    ledger.write_text("canonical bytes")
    snapshot["calculation_context"]["data_store"] = str(datastore)
    before = load_preferences(snapshot)
    assert not preferences_file.exists()
    prefs = update_coverage(before, source(2025))
    prefs["excluded_years"] = [2024]
    save_preferences(snapshot, prefs)
    assert json.loads(preferences_file.read_text())["schema_version"] == 1
    assert load_preferences(snapshot) == prefs
    assert ledger.read_text() == "canonical bytes"
    other = deepcopy(snapshot)
    other["calculation_context"]["data_store"] = str(tmp_path / "other")
    assert load_preferences(other) == {"coverage": [], "excluded_years": []}
    save_preferences(other, {"coverage": [], "excluded_years": [2020]})
    assert load_preferences(snapshot) == prefs


def test_preferences_refuse_datastore_destination_before_creating_directories(tmp_path, monkeypatch):
    snapshot = source()
    datastore = tmp_path / "canonical"
    snapshot["calculation_context"]["data_store"] = str(datastore)
    path = datastore / "subfolder/analytics.json"
    monkeypatch.setattr("fedleave_analytics.preferences.analytics_preferences_path", lambda: path)
    with pytest.raises(ValueError, match="outside"):
        save_preferences(snapshot, {"coverage": []})
    assert not datastore.exists()


def test_invalid_preferences_are_not_silently_overwritten(preferences_file):
    preferences_file.parent.mkdir()
    original = '{"schema_version": 99, "sources": {}}'
    preferences_file.write_text(original)
    with pytest.raises(ValueError, match="schema"):
        load_preferences(source())
    with pytest.raises(ValueError, match="unsupported"):
        save_preferences(source(), {"coverage": []})
    assert preferences_file.read_text() == original


def test_confirm_revoke_one_period_and_whole_year_are_private_preference_changes():
    snapshot = source(2025)
    original = {"coverage": [], "excluded_years": []}
    all_confirmed = update_coverage(original, snapshot)
    assert len(all_confirmed["coverage"]) == 26
    revoked = update_coverage(all_confirmed, snapshot, ["1"], confirmed=False)
    assert len(revoked["coverage"]) == 25
    assert len(update_coverage(revoked, snapshot, ["1"])["coverage"]) == 26
    assert update_coverage(all_confirmed, snapshot, confirmed=False)["coverage"] == []
    assert original == {"coverage": [], "excluded_years": []}


def test_snapshot_source_caches_discovery_and_each_year_with_defensive_copies(monkeypatch):
    calls = []
    histories = references()

    def backend(command, **kwargs):
        assert kwargs["timeout"] == 30
        assert command[-2:] == ["--data-dir", "/chosen data"]
        calls.append(command)
        payload = (
            {"years": [{"leave_year": year, "valid": True} for year in histories]}
            if command[1] == "years"
            else histories[int(command[command.index("--year") + 1])]
        )
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr("fedleave_analytics.snapshots.subprocess.run", backend)
    client = ReadOnlySnapshotSource(Path("/exact/backend"), "/chosen data")
    first = client.snapshot(2025)
    first["transactions"].clear()
    second = client.snapshot(2025)
    assert second["transactions"]
    assert len(calls) == 2
    client.snapshot(2024)
    assert len(calls) == 3
    assert all(call[0] == str(Path("/exact/backend")) for call in calls)
    client.clear()
    client.snapshot(2025)
    assert len(calls) == 5


def test_tables_chart_rows_and_csv_all_consume_the_same_versioned_result(tmp_path):
    result = run()
    tables = forecast_tables(result, "annual")
    daily = tables["Daily closing balances"][0]
    summary = tables["Summary"][0]
    typical = next(row for row in summary if row["scenario"] == "typical")
    assert daily[-1]["typical"] == typical["allocated_horizon_balance"]
    monthly = tables["Monthly explanations"][0]
    assert (
        next(row for row in monthly if row["scenario"] == "typical")["allocated_closing_balance"]
        == daily[-1]["typical"]
    )
    encoded = csv_document(result, "annual", "Monthly explanations")
    assert "month-exposure-median-p80-v1" in encoded
    assert "historical_statuses" in encoded
    assert "historical_coverage" in encoded
    assert "Per-year hours/exposure/rates" in encoded
    path = tmp_path / "daily.csv"
    export_csv(path, source(), result, "annual", "Daily closing balances")
    with path.open(newline="") as handle:
        exported = list(csv.reader(handle))
    assert ["Category filter", "annual"] in exported
    assert ["Units", "hours"] in exported
    assert exported[-1][0] == daily[-1]["date"]
    assert float(exported[-1][3]) == daily[-1]["typical"]


def test_no_history_daily_values_are_null_not_a_fake_zero_forecast():
    result = run(history={})
    rows = forecast_tables(result, "annual")["Daily closing balances"][0]
    assert all(row["scheduled"] == 100 for row in rows)
    assert all(row["typical"] is None and row["higher"] is None for row in rows)


def test_coverage_preferences_round_trip_keeps_rates_and_allocations(preferences_file):
    snapshot, history = source(), references()
    prefs = {"coverage": list(confirmations(history)), "excluded_years": [2021]}
    save_preferences(snapshot, prefs)
    loaded = load_preferences(snapshot)
    assert (
        run(snapshot, history, loaded["coverage"], excluded_years=tuple(loaded["excluded_years"])).to_dict()
        == run(snapshot, history, prefs["coverage"], excluded_years=(2021,)).to_dict()
    )
