import os
import sysconfig
from copy import deepcopy
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QThread
from PySide6.QtWidgets import QFileDialog

from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.budget_model import transfer_session
from fedleave_analytics.holiday_model import export_csv, result_views
from fedleave_analytics.holiday_view import HolidayWidget
from leave_year_support import store, tree
from test_holiday_planner import TODAY, friday, run, snapshot


def wait_result(qtbot, view):
    qtbot.waitUntil(lambda: view.result is not None and not view._tasks and not view._timer.isActive(), timeout=60000)


@pytest.fixture
def view(qtbot, monkeypatch):
    widget = HolidayWidget(Path("/backend"), "/store", 2026, today=TODAY)
    qtbot.addWidget(widget)
    render = widget._render

    def on_gui():
        assert QThread.currentThread() == widget.thread()
        render()

    monkeypatch.setattr(widget, "_render", on_gui)
    widget.set_data(snapshot())
    widget.end_edit.setDate(QDate(2026, 5, 26))
    wait_result(qtbot, widget)
    yield widget
    widget.shutdown()
    qtbot.waitUntil(lambda: not widget._tasks, timeout=60000)


def test_container_routes_context_help_and_actions(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(HolidayWidget, "activate", lambda self: calls.append("activate"))
    window = AnalyticsWindow(
        Path("/backend"),
        "/exact/store",
        2026,
        pdf_folder="/pdf",
        font_size=12,
        auto_load=False,
        initial_view="holidays",
    )
    qtbot.addWidget(window)
    view = window.holiday_planner
    assert window.planning_tabs.currentWidget() is view
    assert window.help_section() == "holidays"
    assert (view.backend, view.data_dir, view.year, view.pdf_folder, view.font().pointSize()) == (
        Path("/backend"),
        "/exact/store",
        2026,
        "/pdf",
        12,
    )
    for name, label in (("load_source", "refresh"), ("open_chart", "chart"), ("save_csv", "csv")):
        monkeypatch.setattr(view, name, lambda label=label: calls.append(label))
    window.refresh_data()
    window.open_chart()
    window.save_csv()
    assert calls[-3:] == ["refresh", "chart", "csv"]
    window.year_combo.addItem("2025", 2025)
    window.year_combo.setCurrentIndex(window.year_combo.findData(2025))
    assert view.year == 2025
    window.close()


def test_cached_controls_sorted_selection_exact_exports(view, qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "fedleave_analytics.snapshots.ReadOnlySnapshotSource._run",
        lambda *args: pytest.fail("Control edits must reuse snapshots"),
    )
    assert view.result.parameters.minimum_days == 4
    assert not view.chart_image.source_pixmap().isNull()
    view.ranking_combo.setCurrentIndex(view.ranking_combo.findData("least"))
    wait_result(qtbot, view)
    view.option_table.sortItems(0, Qt.DescendingOrder)
    view.option_table.setCurrentCell(0, 0)
    index = view.option_table.item(0, 0).data(Qt.UserRole + 1)
    assert view._selected == index
    assert view.tables["Selected days"].item(0, 0).text() == view.result.candidates[index].metrics["start"]
    for title in result_views(view.result, index):
        path = tmp_path / (title.replace(" ", "-") + ".csv")
        export_csv(path, view.snapshot, view.result, title, index)
        assert "holiday-options-1" in path.read_text()
    view.open_chart()
    chart = view._charts[-1]
    assert chart.centralWidget().widget(1).rowCount() == len(view.result.candidates[index].days)
    for extension, method in (("png", chart.save_png), ("pdf", chart.save_pdf), ("csv", view.save_csv)):
        path = tmp_path / f"option.{extension}"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), extension))
        method()
        assert path.stat().st_size > 0
    chart.close()
    view.reserves["annual"].setText("NaN")
    qtbot.waitUntil(lambda: "finite" in view.status_label.text(), timeout=30000)
    assert view.result is None and not view.transfer_button.isEnabled()


def test_transfer_reproduces_candidate_and_stale_source_rejected():
    data = snapshot()
    option = friday(run(data))
    session = transfer_session(data, option, today=TODAY, label="Holiday Planner")
    assert session.result.daily == option.after.daily
    assert session.definition.operations == option.scenario.operations
    changed = deepcopy(data)
    changed["starting_balances"]["annual"] += 1
    with pytest.raises(ValueError, match="STALE_SNAPSHOT"):
        transfer_session(changed, option, today=TODAY, label="Holiday Planner")
    original = deepcopy(data)
    assert run(data).source == option.source
    assert data == original


def test_cancel_source_change_close_discard_late_results(view):
    revision, result = view._revision, view.result
    view.minimum_spin.setValue(5)
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.cancel()
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.set_source(Path("/other"), "/other/store", 2027)
    view._finished(revision, "load", (snapshot(),))
    assert view.snapshot is None
    view.shutdown()
    view._finished(revision, "calculate", result)
    assert view.result is None


def test_real_readonly_legacy_store_unchanged(qtbot, tmp_path):
    base = tmp_path / "readonly-data"
    store(base, start="2026-01-01", balances={"annual": 100})
    import json

    config = json.loads((base / "config.json").read_text())
    config["holidays"]["enabled"] = False
    (base / "config.json").write_text(json.dumps(config))
    for path in base.rglob("*.json"):
        path.chmod(0o444)
    before = tree(base)
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    widget = HolidayWidget(backend, str(base), 2026, today=TODAY)
    qtbot.addWidget(widget)
    widget.load_source()
    wait_result(qtbot, widget)
    assert widget.snapshot["planning_available_years"] == [2026]
    assert widget.result.candidates
    assert tree(base) == before
    widget.shutdown()
    qtbot.waitUntil(lambda: not widget._tasks, timeout=60000)
