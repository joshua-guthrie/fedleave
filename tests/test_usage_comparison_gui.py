import os
import sysconfig
from datetime import date
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.comparison_model import cumulative_tables
from fedleave_analytics.comparison_view import ComparisonWidget
from leave_year_support import source, store, tree, tx

TODAY = date(2026, 6, 30)


def wait_result(qtbot, view):
    qtbot.waitUntil(lambda: view.result is not None and not view._tasks and not view._timer.isActive(), timeout=30000)


@pytest.fixture
def comparison(qtbot, monkeypatch):
    view = ComparisonWidget(Path("/selected/backend"), "/selected/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    render = view._render_result

    def render_on_gui_thread():
        assert QThread.currentThread() == view.thread()
        render()

    monkeypatch.setattr(view, "_render_result", render_on_gui_thread)
    target = source(transactions=[tx("target", "2026-02-01", "annual", "used", 104)])
    view.set_data(target)
    wait_result(qtbot, view)
    yield view
    view.shutdown()
    qtbot.waitUntil(lambda: not view._tasks, timeout=30000)


def test_existing_analytics_routes_comparison_year_context_help_refresh_and_chart(qtbot, monkeypatch):
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
    assert window.comparer.category_actions["annual"].isChecked()
    for method, name in (("load_source", "refresh"), ("open_chart", "chart")):
        monkeypatch.setattr(window.comparer, method, lambda name=name: calls.append(name))
    window.refresh_data()
    window.open_chart()
    assert calls[-2:] == ["refresh", "chart"]
    window.year_combo.addItem("2025", 2025)
    window.year_combo.setCurrentIndex(window.year_combo.findData(2025))
    assert window.comparer.year == 2025
    window.close()


def test_comparison_uses_only_the_window_open_chart_button(qtbot):
    view = ComparisonWidget(Path("/selected/backend"), "/selected/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    assert "Open Chart" not in [button.text() for button in view.findChildren(QPushButton)]
    view.shutdown()


def test_controls_reuse_cached_sources_and_keep_exact_result(qtbot, comparison, monkeypatch):
    view = comparison
    assert view.result.summary["total_hours"] == 104
    assert not view.chart_image.source_pixmap().isNull()

    def forbidden(*args):
        raise AssertionError("Control edits must not reload backend snapshots")

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource._run", forbidden)
    view.category_actions["sick"].setChecked(True)
    wait_result(qtbot, view)
    assert view.result.parameters.categories == ("annual", "sick")
    tables = cumulative_tables(view.result)
    assert tables["Cumulative usage"][0] == list(view.result.points)
    assert tables["Source transactions"][0] == list(view.result.transactions)


def test_real_backend_legacy_readonly_store_survives_exports(qtbot, tmp_path, monkeypatch):
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
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    view = ComparisonWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    try:
        view.load_source()
        wait_result(qtbot, view)
        assert view.result.summary["total_hours"] == 8
        assert view.result.summary["source_year"] == 2026
        assert view.result.source["backend"] == str(backend)
        view.open_chart()
        chart = view._charts[-1]
        assert not chart.image_label.source_pixmap().isNull()
        path = tmp_path / "usage.png"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), "PNG"))
        chart.save_png()
        assert not QPixmap(str(path)).isNull()
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
        path = data / "usage.png"
        chart.save_png()
        assert warnings and "outside the selected leave datastore" in warnings[-1]
        assert not path.exists()
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


def test_chart_contains_daily_data_and_retains_graphic_export_actions(comparison, tmp_path, monkeypatch):
    view = comparison
    view.open_chart()
    chart = view._charts[-1]
    assert chart.centralWidget().widget(1).rowCount() == len(view.result.points)
    assert view.result.points[-1]["hours"] == 104
    path = tmp_path / "chart.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    chart.save_png()
    assert QPixmap(str(path)).width() == 1610
    path = tmp_path / "chart.pdf"
    chart.save_pdf()
    assert path.read_bytes().startswith(b"%PDF-")
    file_action = chart.menuBar().actions()[0]
    file_menu = file_action.menu()
    assert [action.text() for action in file_menu.actions() if not action.isSeparator()] == [
        "Save Graphic as PNG...",
        "Save Graphic as PDF...",
        "Print...",
        "Close",
    ]
    chart.close()


def test_late_results_after_edit_cancel_source_change_and_close_are_discarded(qtbot, comparison):
    view = comparison
    revision, result = view._revision, view.result
    view.category_actions["sick"].setChecked(True)
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.cancel()
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.set_source(Path("/other/backend"), "/other/store", 2025)
    view._finished(revision, "load", source())
    assert view.snapshot is None
    view.shutdown()
    view._finished(revision, "calculate", result)
    assert view.result is None


def test_cancel_during_worker_loading_discards_late_snapshot(qtbot, monkeypatch, tmp_path):
    released = Event()

    def snapshot(self, year):
        assert released.wait(10)
        return source(year)

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource.snapshot", snapshot)
    monkeypatch.setattr(
        "fedleave_analytics.snapshots.ReadOnlySnapshotSource.inventory",
        lambda self: [{"leave_year": 2026, "valid": True}],
    )
    view = ComparisonWidget(Path("/selected/backend"), "/exact/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    assert not view.category_button.isEnabled()
    view.set_source(Path("/other/backend"), "/other/store", 2025)
    view.shutdown()
    released.set()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.snapshot is None and view.result is None
