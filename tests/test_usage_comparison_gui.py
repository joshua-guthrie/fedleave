import csv
import json
import os
import sysconfig
from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QThread, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog

from fedleave.history import confirm_coverage
from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.comparison_model import comparison_tables, csv_document
from fedleave_analytics.comparison_view import ComparisonWidget
from leave_year_support import store, tree, tx
from test_forecast import source

TODAY = date(2026, 6, 30)


def wait_result(qtbot, view):
    qtbot.waitUntil(lambda: view.result is not None and not view._tasks and not view._timer.isActive(), timeout=30000)


@pytest.fixture
def comparison(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "preferences/analytics.json"
    )
    view = ComparisonWidget(Path("/selected/backend"), "/selected/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    render = view._render_result

    def render_on_gui_thread():
        assert QThread.currentThread() == view.thread()
        render()

    monkeypatch.setattr(view, "_render_result", render_on_gui_thread)
    target = source(transactions=[tx("target", "2026-02-01", "annual", "used", 104)])
    history = {
        year: source(year, transactions=[tx(f"ref-{year}", f"{year}-02-01", "annual", "used", hours)])
        for year, hours in zip((2023, 2024, 2025), (64, 80, 96), strict=True)
    }
    coverage = [row for snapshot in (target, *history.values()) for row in confirm_coverage(snapshot)]
    view.set_data(target, history, {"coverage": coverage, "excluded_years": []})
    wait_result(qtbot, view)
    yield view
    view.shutdown()
    qtbot.waitUntil(lambda: not view._tasks, timeout=30000)


def test_existing_analytics_routes_comparison_year_context_help_refresh_and_exports(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(ComparisonWidget, "activate", lambda self: calls.append("activate"))
    window = AnalyticsWindow(
        Path("/backend"),
        "/exact/store",
        2026,
        font_size=12,
        pdf_folder="/pdf",
        auto_load=False,
        initial_view="comparison",
    )
    qtbot.addWidget(window)
    assert window.pages.currentWidget() is window.comparer
    assert window.help_section() == "comparison"
    assert (window.comparer.backend, window.comparer.data_dir, window.comparer.year, window.comparer.pdf_folder) == (
        Path("/backend"),
        "/exact/store",
        2026,
        "/pdf",
    )
    assert window.comparer.font().pointSize() == 12
    for method, name in (("load_source", "refresh"), ("open_chart", "chart"), ("save_csv", "csv")):
        monkeypatch.setattr(window.comparer, method, lambda name=name: calls.append(name))
    window.refresh_data()
    window.open_chart()
    window.save_csv()
    assert calls[-3:] == ["refresh", "chart", "csv"]
    window.year_combo.addItem("2025", 2025)
    window.year_combo.setCurrentIndex(window.year_combo.findData(2025))
    assert window.comparer.year == 2025
    window.close()


def test_controls_reuse_cached_sources_and_keep_exact_result_tables(qtbot, comparison, monkeypatch):
    view = comparison
    assert view.result.summary["difference"] == 24
    assert not view.chart_image.source_pixmap().isNull()

    def forbidden(*args):
        raise AssertionError("Control edits must not reload backend snapshots")

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource._run", forbidden)
    view.alignment_combo.setCurrentIndex(1)
    wait_result(qtbot, view)
    assert view.result.parameters.alignment == "calendar"
    view.category_actions["sick"].setChecked(True)
    view.schedule_check.setChecked(True)
    view.basis_combo.setCurrentIndex(1)
    wait_result(qtbot, view)
    assert view.result.parameters.categories == ("annual", "sick")
    assert view.result.parameters.status_basis == "confirmed"
    assert view.result.summary["hours_per_100"] is not None
    tables = comparison_tables(view.result)
    assert tables["Summary"][0][0] == view.result.summary
    assert tables["Daily alignment"][0] == list(view.result.points)
    assert tables["Year details"][0] == list(view.result.observations)


def test_coverage_target_and_reference_exclusion_save_outside_leave_data(qtbot, comparison, tmp_path):
    view = comparison
    view.history_table.item(view._years.index(2025), 1).setCheckState(Qt.Checked)
    wait_result(qtbot, view)
    assert view.result.summary["median"] == 72
    assert view.result.summary["band_lower"] is None
    assert view.result.summary["limited_history"]
    view.history_table.setCurrentCell(0, 2)
    view._confirm(False, True)
    wait_result(qtbot, view)
    assert view.result.summary["recorded"] is None
    assert "Coverage unconfirmed" in view.status_label.text()
    view._confirm(True, True)
    wait_result(qtbot, view)
    assert view.result.summary["recorded"] == 104
    view.period_table.horizontalHeader().sectionClicked.emit(0)
    view.period_table.selectRow(0)
    view._confirm(False, False)
    wait_result(qtbot, view)
    assert view.result.summary["recorded"] is None
    saved = json.loads((tmp_path / "preferences/analytics.json").read_text())
    preferences = next(iter(saved["sources"].values()))
    assert preferences["excluded_years"] == [2025]
    assert len(preferences["coverage"]) == 90
    target_records = [row for row in preferences["coverage"] if row["start"].startswith("2026")]
    assert max(row.get("confirmed_through", row["end"]) for row in target_records) == "2026-06-30"


def test_failed_preference_write_preserves_controls_coverage_and_results(comparison, monkeypatch):
    view = comparison
    before = deepcopy(view.preferences)

    def fail(*args):
        raise OSError("preferences unavailable")

    monkeypatch.setattr("fedleave_analytics.comparison_view.save_preferences", fail)
    item = view.history_table.item(1, 1)
    item.setCheckState(Qt.Checked)
    assert item.checkState() == Qt.Unchecked
    assert view.preferences == before
    assert view.result.summary["difference"] == 24
    assert "preferences unavailable" in view.status_label.text()


def test_median_drilldown_lists_year_totals_then_original_transactions(comparison, monkeypatch):
    view = comparison
    dialogs = []
    monkeypatch.setattr(
        view, "_dialog", lambda title, rows, columns, callback=None: dialogs.append((title, rows, columns, callback))
    )
    median_column = next(i for i, (key, _) in enumerate(view._views["Summary"][1]) if key == "median")
    view.drilldown("Summary", 0, median_column)
    title, observations, columns, callback = dialogs[-1]
    assert "derived statistics" in title
    assert sorted(row["hours"] for row in observations) == [64, 80, 96]
    assert all(row["mapped_date"] for row in observations)
    callback(observations[1])
    assert dialogs[-1][1][0]["id"] == "ref-2024"
    assert dialogs[-1][1][0]["hours"] == 80


def test_sorted_year_drilldown_retains_actual_source_identity(comparison, monkeypatch):
    view = comparison
    captured = []
    monkeypatch.setattr(view, "_transactions", lambda row: captured.append(row))
    table = view.tables["Year details"]
    table.setSortingEnabled(True)
    year_column = next(i for i, (key, _) in enumerate(view._views["Year details"][1]) if key == "year")
    table.sortItems(year_column, Qt.DescendingOrder)
    source_index = table.item(0, 0).data(Qt.UserRole + 1)
    view.drilldown("Year details", 0, year_column)
    assert captured == [view.result.observations[source_index]]


def test_csv_chart_png_pdf_exports_share_exact_data_and_metadata(comparison, tmp_path, monkeypatch):
    view = comparison
    path = tmp_path / "summary.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "CSV"))
    view.save_csv()
    exported = list(csv.reader(path.read_text().splitlines()))
    assert ["Alignment", "Leave-year progress"] in exported
    assert ["Cutoff", "2026-06-30"] in exported
    assert float(exported[-1][0]) == 104
    assert "current-schedule" in csv_document(view.result, "Year details")
    view.open_chart()
    chart = view._charts[-1]
    assert chart.centralWidget().widget(1).rowCount() == len(view.result.points)
    path = tmp_path / "chart.png"
    chart.save_png()
    assert QPixmap(str(path)).width() == 1610
    path = tmp_path / "chart.pdf"
    chart.save_pdf()
    assert path.read_bytes().startswith(b"%PDF-")
    file_action = chart.menuBar().actions()[0]
    file_menu = file_action.menu()
    assert "Print..." in [action.text() for action in file_menu.actions()]
    chart.close()


def test_late_results_after_edit_cancel_source_change_and_close_are_discarded(qtbot, comparison):
    view = comparison
    revision, result = view._revision, view.result
    view.cutoff_edit.setDate(QDate(2026, 6, 29))
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.cancel()
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.set_source(Path("/other/backend"), "/other/store", 2025)
    view._finished(revision, "load", (source(), {}, {}, []))
    assert view.snapshot is None
    assert view.history_table.rowCount() == 0
    view.shutdown()
    view._finished(revision, "calculate", result)
    assert view.result is None


def test_cancel_during_worker_loading_discards_late_snapshot_and_preferences(qtbot, monkeypatch, tmp_path):
    released = Event()

    def snapshot(self, year):
        assert released.wait(10)
        return source(year)

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource.snapshot", snapshot)
    monkeypatch.setattr(
        "fedleave_analytics.snapshots.ReadOnlySnapshotSource.inventory",
        lambda self: [{"leave_year": 2026, "valid": True}],
    )
    path = tmp_path / "preferences.json"
    monkeypatch.setattr("fedleave_analytics.preferences.analytics_preferences_path", lambda: path)
    view = ComparisonWidget(Path("/selected/backend"), "/exact/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    assert not view.cutoff_edit.isEnabled()
    view.set_source(Path("/other/backend"), "/other/store", 2025)
    view.shutdown()
    released.set()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None and view.result is None
    assert not path.exists()


def test_real_backend_legacy_readonly_store_survives_coverage_and_exports(qtbot, tmp_path, monkeypatch):
    data = tmp_path / "ledger datastore"
    for year in (2025, 2026):
        store(
            data,
            year,
            start=f"{year}-01-01",
            transactions=[
                tx(f"use-{year}", f"{year}-02-01", "annual", "used", 8),
                tx(f"void-{year}", f"{year}-02-01", "annual", "used", 900, void=True, history=[{"legacy": True}]),
            ],
        )
    before, files = tree(data), list(data.rglob("*.json"))
    for path in files:
        path.chmod(0o444)
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "gui/analytics.json"
    )
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    view = ComparisonWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    try:
        view.load_source()
        wait_result(qtbot, view)
        assert view.result.summary["recorded"] is None
        for row in range(view.history_table.rowCount()):
            view.history_table.setCurrentCell(row, 2)
            view._confirm(True, True)
            wait_result(qtbot, view)
        assert view.result.summary["recorded"] == 8
        assert view.result.summary["median"] == 8
        assert view.result.source["backend"] == str(backend)
        path = tmp_path / "usage.csv"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "CSV"))
        view.save_csv()
        assert path.exists()
        view.open_chart()
        assert not view._charts[-1].image_label.source_pixmap().isNull()
        view.cancel()
        view.shutdown()
        qtbot.waitUntil(lambda: not view._tasks, timeout=30000)
        assert tree(data) == before
    finally:
        for path in files:
            path.chmod(0o644)
        view.shutdown()
        QThreadPool.globalInstance().waitForDone(30000)


def test_missing_store_is_not_initialized(qtbot, tmp_path):
    data = tmp_path / "missing"
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    view = ComparisonWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None and view.result is None
    assert not data.exists()
    view.shutdown()
