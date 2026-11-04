import csv
import json
import os
import sysconfig
from datetime import date
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QThread, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QTabWidget

from fedleave.history import confirm_coverage
from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.break_model import break_tables, csv_document, export_csv
from fedleave_analytics.break_view import BreakPatternsWidget
from leave_year_support import store, tree, tx
from test_break_patterns import annual, source

TODAY = date(2026, 6, 19)


def wait_result(qtbot, view):
    qtbot.waitUntil(lambda: view.result is not None and not view._tasks and not view._timer.isActive(), timeout=30000)


@pytest.fixture
def breaks(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "gui/analytics.json"
    )
    view = BreakPatternsWidget(Path("/selected/backend"), "/selected/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    render = view._render_result

    def on_gui_thread():
        assert QThread.currentThread() == view.thread()
        render()

    monkeypatch.setattr(view, "_render_result", on_gui_thread)
    snapshot = source(
        transactions=[
            *annual("2026-06-08", "2026-06-09", "2026-06-10", "2026-06-29"),
            tx("partial", "2026-06-11", "annual", "used", 4),
            tx("sick", "2026-06-11", "sick", "used", 4),
        ]
    )
    coverage = confirm_coverage(snapshot, strict=False, through=TODAY.isoformat())
    view.set_data(snapshot, {}, {"coverage": list(coverage), "excluded_years": []})
    wait_result(qtbot, view)
    yield view
    view.shutdown()
    qtbot.waitUntil(lambda: not view._tasks, timeout=30000)


def test_analytics_routes_break_patterns_context_help_refresh_chart_csv_and_year(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(BreakPatternsWidget, "activate", lambda self: calls.append("activate"))
    window = AnalyticsWindow(
        Path("/backend"), "/exact/store", 2026, font_size=12, pdf_folder="/pdf", auto_load=False, initial_view="breaks"
    )
    qtbot.addWidget(window)
    assert window.pages.currentWidget() is window.break_patterns
    assert window.help_section() == "breaks"
    view = window.break_patterns
    assert (view.backend, view.data_dir, view.year, view.pdf_folder) == (Path("/backend"), "/exact/store", 2026, "/pdf")
    assert view.font().pointSize() == 12
    monkeypatch.setattr(view, "load_source", lambda: calls.append("refresh"))
    monkeypatch.setattr(view, "open_chart", lambda: calls.append("chart"))
    monkeypatch.setattr(view, "save_csv", lambda: calls.append("csv"))
    window.refresh_data()
    window.open_chart()
    window.save_csv()
    assert calls[-3:] == ["refresh", "chart", "csv"]
    window.year_combo.addItem("2025", 2025)
    window.year_combo.setCurrentIndex(window.year_combo.findData(2025))
    assert view.year == 2025
    window.close()


def test_group_threshold_schedule_and_cutoff_recalculate_from_cached_sources(qtbot, breaks, monkeypatch):
    view = breaks
    assert view.result.summary["fully_absent_workdays"] == 3
    assert view.result.summary["partially_absent_workdays"] == 1
    assert view.result.summary["qualifying_break_count"] == 1
    assert view.result.categories == ("annual", "restored_annual", "comp", "travel_comp", "credit", "time_off_award")

    def forbidden(*args):
        raise AssertionError("Control changes must use cached snapshots")

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource._run", forbidden)
    view.group_combo.setCurrentIndex(view.group_combo.findData("all"))
    wait_result(qtbot, view)
    assert view.result.summary["fully_absent_workdays"] == 4
    assert "sick" in view.definition_label.text().lower()
    view.threshold_spin.setValue(5)
    wait_result(qtbot, view)
    assert view.result.summary["qualifying_break_count"] == 0
    view.group_combo.setCurrentIndex(view.group_combo.findData("custom"))
    view.category_actions["sick"].setChecked(True)
    wait_result(qtbot, view)
    assert view.result.categories == ("annual", "sick")
    view.schedule_check.setChecked(False)
    wait_result(qtbot, view)
    assert view.result.summary["fully_absent_workdays"] is None
    assert view.result.summary["selected_recorded_hours"] == 32
    assert not view.chart_image.source_pixmap().isNull()


def test_coverage_confirmation_is_bounded_by_cutoff_and_preferences_outside_ledger(qtbot, breaks, tmp_path):
    view = breaks
    view._confirm(False, True)
    wait_result(qtbot, view)
    assert view.result.summary["fully_absent_workdays"] is None
    view._confirm(True, True)
    wait_result(qtbot, view)
    assert view.result.summary["fully_absent_workdays"] == 3
    saved = json.loads((tmp_path / "gui/analytics.json").read_text())
    preferences = next(iter(saved["sources"].values()))
    assert preferences["coverage"][0]["confirmed_through"] == TODAY.isoformat()
    view.today = date(2026, 6, 20)
    view.cutoff_edit.setDate(QDate(2026, 6, 20))
    wait_result(qtbot, view)
    assert view.result.summary["unknown_recorded_days"] == 1
    view.period_table.selectRow(0)
    view._confirm(False, False)
    wait_result(qtbot, view)
    assert view.result.summary["covered_recorded_days"] == 0


def test_failed_preference_write_preserves_coverage_and_result(qtbot, breaks, monkeypatch):
    original = breaks.preferences

    def fail(*args):
        raise OSError("preferences unavailable")

    monkeypatch.setattr("fedleave_analytics.break_view.save_preferences", fail)
    breaks._confirm(False, True)
    qtbot.waitUntil(lambda: not breaks._tasks, timeout=15000)
    assert breaks.preferences is original
    assert breaks.result.summary["fully_absent_workdays"] == 3
    assert "preferences unavailable" in breaks.status_label.text()


def test_refresh_preserves_selected_range_and_cutoff(qtbot, breaks, monkeypatch):
    view = breaks
    view.cutoff_edit.setDate(QDate(2026, 6, 15))
    wait_result(qtbot, view)
    snapshot = view.snapshot

    def run(self, args):
        return {"years": [{"leave_year": 2026, "valid": True}]} if args[0] == "years" else snapshot

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource._run", run)
    view.load_source()
    wait_result(qtbot, view)
    assert view.result.parameters.cutoff == "2026-06-15"
    assert view.result.parameters.years == (2026,)


def test_future_cutoff_is_not_labeled_recorded(qtbot, breaks):
    breaks.cutoff_edit.setDate(QDate(2026, 6, 20))
    qtbot.waitUntil(lambda: not breaks._tasks and not breaks._timer.isActive(), timeout=15000)
    assert breaks.result is None
    assert "no later than today" in breaks.status_label.text()


def test_csv_and_both_chart_exports_use_exact_result_rows(breaks, tmp_path, monkeypatch):
    view = breaks
    tables = break_tables(view.result)
    assert tables["Daily classification"][0] == list(view.result.daily)
    assert tables["Recorded breaks"][0] == list(view.result.recorded)
    path = tmp_path / "breaks.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "CSV"))
    view.detail_tabs.setCurrentWidget(view.tables["Recorded breaks"])
    view.save_csv()
    exported = list(csv.reader(path.read_text().splitlines()))
    assert ["Cutoff", TODAY.isoformat()] in exported
    assert ["Group", "Discretionary time off"] in exported
    assert "not an employment rule" in path.read_text()
    assert any("2026-06-06" in row for row in exported)
    assert "Scheduled workdays between substantial breaks" in csv_document(view.result, "Summary")
    view.open_chart()
    distribution = view._charts[-1]
    assert distribution.centralWidget().widget(1).rowCount() == 4
    path = tmp_path / "distribution.png"
    distribution.save_png()
    assert QPixmap(str(path)).width() == 1610
    path = tmp_path / "distribution.pdf"
    distribution.save_pdf()
    assert path.read_bytes().startswith(b"%PDF-")
    action = distribution.menuBar().actions()[0]
    menu = action.menu()
    assert "Print..." in [a.text() for a in menu.actions()]
    view.chart_combo.setCurrentIndex(1)
    view.open_chart()
    timeline = view._charts[-1]
    assert timeline.centralWidget().widget(1).rowCount() == len(view.result.recorded) + len(view.result.upcoming)
    path = tmp_path / "timeline.png"
    timeline.save_png()
    assert QPixmap(str(path)).width() == 1610
    distribution.close()
    timeline.close()


def test_sorted_drilldown_shows_classification_other_usage_and_original_ids(breaks, monkeypatch):
    view = breaks
    table = view.tables["Daily classification"]
    table.setSortingEnabled(True)
    table.sortItems(0, Qt.DescendingOrder)
    displayed_row = next(i for i in range(table.rowCount()) if table.item(i, 0).text() == "2026-06-11")
    captured = []

    def inspect(dialog):
        tabs = dialog.findChild(QTabWidget)
        days, transactions = tabs.widget(0), tabs.widget(1)
        captured.append(
            (
                [days.item(0, i).text() for i in range(days.columnCount())],
                [transactions.item(i, 1).text() for i in range(transactions.rowCount())],
            )
        )
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", inspect)
    view.drilldown("Daily classification", displayed_row)
    assert "Partial" in captured[0][0]
    assert set(captured[0][1]) == {"partial", "sick"}


def test_late_worker_results_after_edit_cancel_source_change_or_close_are_ignored(breaks):
    view = breaks
    revision, result = view._revision, view.result
    view.threshold_spin.setValue(4)
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.cancel()
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.set_source(Path("/other/backend"), "/other/store", 2025)
    view._finished(revision, "load", (source(), {}, {}, []))
    assert view.snapshot is None and view.history_table.rowCount() == 0
    view.shutdown()
    view._finished(revision, "calculate", result)
    assert view.result is None


def test_canceled_loading_does_not_install_late_source_or_write_preferences(qtbot, tmp_path, monkeypatch):
    released = Event()

    def snapshot(self, year):
        assert released.wait(10)
        return source()

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource.snapshot", snapshot)
    monkeypatch.setattr(
        "fedleave_analytics.snapshots.ReadOnlySnapshotSource.inventory",
        lambda self: [{"leave_year": 2026, "valid": True}],
    )
    path = tmp_path / "unwritten/analytics.json"
    monkeypatch.setattr("fedleave_analytics.preferences.analytics_preferences_path", lambda: path)
    view = BreakPatternsWidget(Path("/backend"), "/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    view.set_source(Path("/other"), "/other", 2025)
    view.shutdown()
    released.set()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None and view.result is None
    assert not path.exists()


def test_real_backend_readonly_legacy_history_joins_years_without_mutation(qtbot, tmp_path, monkeypatch):
    data = tmp_path / "canonical data"
    store(
        data,
        2025,
        "2025-01-12",
        transactions=[
            tx("friday", "2026-01-09", "annual", "used", 8),
            tx("legacy", "2025-06-01", "annual", "used", 900, void=True, history=[{"old": True}]),
        ],
    )
    store(
        data,
        2026,
        "2026-01-11",
        transactions=[
            tx("monday", "2026-01-12", "annual", "used", 8),
            tx("tuesday", "2026-01-13", "annual", "used", 8),
        ],
    )
    config_path = data / "config.json"
    config = json.loads(config_path.read_text())
    config["holidays"]["enabled"] = False
    config_path.write_text(json.dumps(config))
    before, files = tree(data), list(data.rglob("*.json"))
    for path in files:
        path.chmod(0o444)
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "gui/preferences.json"
    )
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    view = BreakPatternsWidget(backend, str(data), 2026, today=date(2026, 1, 20))
    qtbot.addWidget(view)
    try:
        view.load_source()
        wait_result(qtbot, view)
        view.history_table.item(view._years.index(2025), 0).setCheckState(Qt.Checked)
        wait_result(qtbot, view)
        for year in (2025, 2026):
            view.history_table.setCurrentCell(view._years.index(year), 1)
            view._confirm(True, True)
            wait_result(qtbot, view)
        interval = next(row for row in view.result.recorded if row["start"] == "2026-01-09")
        assert interval["end"] == "2026-01-13" and interval["fully_absent_workdays"] == 3
        assert interval["source_years"] == [2025, 2026]
        path = tmp_path / "export.csv"
        export_csv(path, view.snapshot, view.result, "Recorded breaks")
        assert path.exists()
        with pytest.raises(ValueError, match="outside"):
            export_csv(data / "protected.csv", view.snapshot, view.result, "Recorded breaks")
        view.chart_combo.setCurrentIndex(1)
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
    view = BreakPatternsWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None and view.result is None
    assert not data.exists()
    view.shutdown()
