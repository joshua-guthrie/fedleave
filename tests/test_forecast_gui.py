import json
import os
import sysconfig
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog

from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.forecast_view import ForecastWidget
from leave_year_support import store, tree, tx
from test_forecast import TODAY, confirmations, references, source, summary


def wait_result(qtbot, view, horizon="2026-07-31"):
    qtbot.waitUntil(
        lambda: view.result is not None and view.result.parameters.horizon == horizon and not view._tasks, timeout=30000
    )


@pytest.fixture
def forecast_view(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "preferences/analytics.json"
    )
    view = ForecastWidget(Path("/selected/backend"), "/selected/datastore", 2026, today=TODAY)
    qtbot.addWidget(view)
    history = references()
    view.set_data(source(), history, {"coverage": list(confirmations(history)), "excluded_years": []})
    view.horizon_edit.setDate(QDate(2026, 7, 31))
    wait_result(qtbot, view)
    yield view
    view.shutdown()
    qtbot.waitUntil(lambda: not view._tasks, timeout=30000)


def test_scope_reserves_invalid_input_and_cached_recalculation(qtbot, forecast_view, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Edits must reuse cached source snapshots")

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource._run", forbidden)
    view = forecast_view
    view.reserves["annual"].setText("80")
    wait_result(qtbot, view)
    assert summary(view.result)["first_reserve_breach"]
    assert not view.chart_image.source_pixmap().isNull()
    assert view.tables["Monthly explanations"].rowCount() == 3
    view.scope_combo.setCurrentIndex(2)
    wait_result(qtbot, view)
    assert view.result.parameters.categories == ("annual", "sick")
    view.category_combo.setCurrentIndex(1)
    assert all(row["category"] == "sick" for row in view._views["Daily closing balances"][0])
    view.reserves["annual"].setText("NaN")
    qtbot.waitUntil(lambda: "finite" in view.status_label.text(), timeout=15000)
    assert view.result is None
    assert view.chart_image.source_pixmap().isNull()


def test_coverage_confirm_revoke_and_manual_exclusions_persist_outside_ledger(qtbot, forecast_view):
    view = forecast_view
    view.history_table.item(0, 1).setCheckState(Qt.Checked)
    wait_result(qtbot, view)
    assert view.result.parameters.excluded_years == (2025,)
    assert summary(view.result)["estimated_total_hours"] == 28
    row_2024 = view._history_years.index(2024)
    view.history_table.setCurrentCell(row_2024, 2)
    view._confirm(False, True)
    qtbot.waitUntil(lambda: len(view.preferences["coverage"]) == 104, timeout=15000)
    wait_result(qtbot, view)
    assert summary(view.result)["estimated_total_hours"] == 24
    view._confirm(True, True)
    qtbot.waitUntil(lambda: len(view.preferences["coverage"]) == 130, timeout=15000)
    wait_result(qtbot, view)
    assert summary(view.result)["estimated_total_hours"] == 28
    view.period_table.horizontalHeader().sectionClicked.emit(0)
    assert view.period_table.item(0, 0).text() == "1"
    assert not view.period_table.item(0, 1).flags() & Qt.ItemIsEditable
    view.period_table.selectRow(0)
    view._confirm(False, False)
    qtbot.waitUntil(lambda: len(view.preferences["coverage"]) == 129, timeout=15000)
    wait_result(qtbot, view)
    assert view.period_table.item(0, 3).text() == "Unconfirmed"


def test_failed_preference_write_preserves_coverage_and_checkbox_state(qtbot, forecast_view, monkeypatch):
    view = forecast_view
    before = deepcopy(view.preferences)

    def fail(*args):
        raise OSError("preferences unavailable")

    monkeypatch.setattr("fedleave_analytics.forecast_view.save_preferences", fail)
    view.history_table.item(0, 1).setCheckState(Qt.Checked)
    assert view.history_table.item(0, 1).checkState() == Qt.Unchecked
    assert view.preferences == before
    assert "preferences unavailable" in view.status_label.text()
    view.history_table.setCurrentCell(0, 2)
    view._confirm(False, True)
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.preferences == before


def test_retrospective_tables_exports_and_category_switch_share_result(qtbot, forecast_view, tmp_path, monkeypatch):
    view = forecast_view
    view.scope_combo.setCurrentIndex(2)
    wait_result(qtbot, view)
    view.run_retrospective()
    qtbot.waitUntil(lambda: view.retrospective is not None and not view._tasks, timeout=30000)
    assert "do not reconstruct" in view.status_label.text()
    assert view.tables["Retrospective MAE"].rowCount() == 2
    view.category_combo.setCurrentIndex(1)
    assert all(row["category"] == "sick" for row in view._views["Retrospective checks"][0])
    path = tmp_path / "validation.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "CSV"))
    view.save_csv()
    assert path.exists()
    assert "do not reconstruct" in path.read_text()
    path = tmp_path / "forecast.json"
    view.export_json()
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == 1
    assert payload["retrospective"]["summaries"][0]["sample_count"] > 0
    assert payload["parameters"]["categories"] == ["annual", "sick"]


def test_chart_popup_reuses_exact_daily_data_and_existing_exports(qtbot, forecast_view, tmp_path, monkeypatch):
    view = forecast_view
    view.open_chart()
    chart = view._charts[-1]
    assert chart.centralWidget().widget(1).rowCount() == len(view._views["Daily closing balances"][0])
    file_action = chart.menuBar().actions()[0]
    menu = file_action.menu()
    assert {"Save Table as CSV...", "Save Graphic as PNG...", "Save Graphic as PDF...", "Print..."} <= {
        action.text() for action in menu.actions()
    }
    path = tmp_path / "chart.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "PNG"))
    chart.save_png()
    assert QPixmap(str(path)).width() == 1610
    path = tmp_path / "chart.pdf"
    chart.save_pdf()
    assert path.read_bytes().startswith(b"%PDF-")
    chart.close()


def test_late_results_after_edit_cancel_source_change_and_close_are_ignored(qtbot, forecast_view):
    view = forecast_view
    revision, result = view._revision, view.result
    view.horizon_edit.setDate(QDate(2026, 7, 30))
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.cancel()
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.set_source(Path("/different/backend"), "/other/store", 2027)
    view._finished(revision, "load", (source(), {}, {}, []))
    assert view.snapshot is None
    view.shutdown()
    view._finished(revision, "calculate", result)
    assert view.result is None


def test_existing_analytics_container_routes_forecast_actions(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(ForecastWidget, "activate", lambda self: calls.append("activate"))
    window = AnalyticsWindow(Path("/backend"), "/store", 2026, auto_load=False, initial_view="forecast")
    qtbot.addWidget(window)
    assert window.pages.currentWidget() is window.planning_page
    assert window.planning_tabs.currentWidget() is window.forecaster
    assert [window.planning_tabs.tabText(i) for i in range(window.planning_tabs.count())] == [
        "What-if Planner",
        "Usage Forecast",
    ]
    monkeypatch.setattr(window.forecaster, "load_source", lambda: calls.append("refresh"))
    monkeypatch.setattr(window.forecaster, "open_chart", lambda: calls.append("chart"))
    monkeypatch.setattr(window.forecaster, "save_csv", lambda: calls.append("csv"))
    window.refresh_data()
    window.open_chart()
    window.save_csv()
    assert calls[-3:] == ["refresh", "chart", "csv"]
    window.close()


def test_real_backend_readonly_legacy_store_survives_forecast_preferences_and_exports(qtbot, tmp_path, monkeypatch):
    data = tmp_path / "ledger datastore"
    for year in (2023, 2024, 2025, 2026):
        store(
            data,
            year=year,
            start=f"{year}-01-01",
            balances={"annual": 100},
            transactions=[
                tx(f"use-{year}", f"{year}-07-15", "annual", "used", 8),
                tx(f"legacy-{year}", f"{year}-06-01", "annual", "used", 2, void=True, history=[{"old": True}]),
            ],
        )
    config = json.loads((data / "config.json").read_text())
    config["holidays"]["enabled"] = False
    (data / "config.json").write_text(json.dumps(config))
    before = tree(data)
    files = list(data.rglob("*.json"))
    for path in files:
        path.chmod(0o444)
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "gui/analytics.json"
    )
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    view = ForecastWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    try:
        view.load_source()
        assert not view.cutoff_edit.isEnabled() and not view.reserves["annual"].isEnabled()
        qtbot.waitUntil(lambda: view.snapshot is not None, timeout=30000)
        view.horizon_edit.setDate(QDate(2026, 7, 31))
        wait_result(qtbot, view)
        assert summary(view.result)["estimated_total_hours"] is None
        for row in range(view.history_table.rowCount()):
            view.history_table.setCurrentCell(row, 2)
            view._confirm(True, True)
            qtbot.waitUntil(
                lambda: view.result is not None and not view._tasks and not view._timer.isActive(), timeout=30000
            )
        assert summary(view.result)["estimated_total_hours"] is not None
        path = tmp_path / "forecast.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "JSON"))
        view.export_json()
        assert json.loads(path.read_text())["scenarios"]["scheduled"]
        view.run_retrospective()
        qtbot.waitUntil(lambda: view.retrospective is not None and not view._tasks, timeout=30000)
        view.cancel()
        view.shutdown()
        qtbot.waitUntil(lambda: not view._tasks, timeout=30000)
        assert tree(data) == before
        assert (tmp_path / "gui/analytics.json").exists()
    finally:
        for path in files:
            path.chmod(0o644)
        view.shutdown()
        QThreadPool.globalInstance().waitForDone(30000)


def test_missing_backend_store_is_not_initialized(qtbot, tmp_path):
    data = tmp_path / "missing-store"
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    view = ForecastWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None
    assert not data.exists()
    view.shutdown()


def test_canceled_inflight_loading_never_installs_late_data_or_preferences(qtbot, monkeypatch, tmp_path):
    released = Event()

    def snapshot(self, year):
        assert released.wait(10)
        return source(year)

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource.snapshot", snapshot)
    monkeypatch.setattr(
        "fedleave_analytics.snapshots.ReadOnlySnapshotSource.inventory",
        lambda self: [{"leave_year": 2026, "valid": True}],
    )
    path = tmp_path / "not-created/analytics.json"
    monkeypatch.setattr("fedleave_analytics.preferences.analytics_preferences_path", lambda: path)
    view = ForecastWidget(Path("/backend"), "/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    view.cancel()
    view.shutdown()
    released.set()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None
    assert view.result is None
    assert not path.exists()
