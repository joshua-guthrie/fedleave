import os
from copy import deepcopy
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QFileDialog

from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.budget_model import export_csv, result_views, transfer_session
from fedleave_analytics.budget_view import BudgetWidget
from fedleave_analytics.planning_model import export_destination
from test_budget import TODAY, run
from test_forecast import source


def wait_result(qtbot, view):
    qtbot.waitUntil(lambda: view.result is not None and not view._tasks, timeout=30000)


@pytest.fixture
def view(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "preferences/analytics.json"
    )
    widget = BudgetWidget(Path("/selected/backend"), "/selected/store", 2026, today=TODAY)
    qtbot.addWidget(widget)
    widget.set_data(source(balances={"annual": 288}))
    wait_result(qtbot, widget)
    yield widget
    widget.shutdown()
    qtbot.waitUntil(lambda: not widget._tasks, timeout=30000)


def test_all_strategies_reuse_snapshot_preferences_exports_and_charts(qtbot, view, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "fedleave_analytics.snapshots.ReadOnlySnapshotSource._run",
        lambda *a: pytest.fail("Strategy edits must use cached snapshot"),
    )
    assert not view.result.suggestions
    view.eligibility["annual"].setChecked(True)
    wait_result(qtbot, view)
    for index in range(4):
        view.strategy_combo.setCurrentIndex(index)
        wait_result(qtbot, view)
        assert view.result.allocated_hours == 48
        assert view.result.parameters.strategy == view.strategy_combo.currentData()
        assert not view.chart_image.source_pixmap().isNull()
    assert '"budget_strategy": "weighted"' in (tmp_path / "preferences/analytics.json").read_text()
    view.open_chart()
    chart = view._charts[-1]
    assert chart.centralWidget().widget(1).rowCount() == len(view.result.cumulative)
    for extension in ("csv", "png", "pdf"):
        path = tmp_path / f"budget.{extension}"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), extension))
        {"csv": view.save_csv, "png": chart.save_png, "pdf": chart.save_pdf}[extension]()
        assert path.stat().st_size > 0
    assert "Capacity-weighted" in (tmp_path / "budget.csv").read_text()
    chart.close()
    view.reserves["annual"].setText("NaN")
    qtbot.waitUntil(lambda: "finite" in view.status_label.text(), timeout=30000)
    assert view.result is None
    assert not view.transfer_button.isEnabled()


def test_stale_results_cancel_reload_and_close(qtbot, view):
    revision, result = view._revision, view.result
    view.cutoff_edit.setDate(QDate(2026, 11, 2))
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.cancel()
    view._finished(revision, "calculate", result)
    assert view.result is None
    view.set_source(Path("/other/backend"), "/other/store", 2027)
    view._finished(revision, "load", (source(), {}, ""))
    assert view.snapshot is None
    assert view.tables == {}
    view.shutdown()
    view._finished(revision, "calculate", result)
    assert view.result is None


def test_transfer_validates_complete_material_source_and_reproduces_balances(tmp_path):
    snapshot = source(balances={"annual": 288})
    result = run(snapshot, eligible_categories=("annual",))
    candidate = transfer_session(snapshot, result, today=TODAY)
    assert candidate.result.daily == result.after.daily
    assert candidate.result.categories == result.after.categories
    assert all(op.operation == "add" and op.row_id.startswith("budget:") for op in candidate.definition.operations)
    before = deepcopy(candidate.definition)
    changed = deepcopy(snapshot)
    changed["starting_balances"]["annual"] += 1
    with pytest.raises(ValueError, match="STALE_SNAPSHOT"):
        transfer_session(changed, result, today=TODAY)
    assert candidate.definition == before
    for name in result_views(result):
        path = tmp_path / (name.replace(" ", "-") + ".csv")
        export_csv(path, snapshot, result, name)
        assert "deadline-budget-v1" in path.read_text()
    with pytest.raises(ValueError):
        with export_destination(Path("test-store/leave_years/2026.json"), snapshot):
            pass


def test_analytics_container_routes_budget_actions(qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(BudgetWidget, "activate", lambda self: calls.append("activate"))
    window = AnalyticsWindow(Path("/backend"), "/store", 2026, auto_load=False, initial_view="budget")
    qtbot.addWidget(window)
    assert window.pages.currentWidget() is window.planning_page
    assert window.planning_tabs.currentWidget() is window.budgeter
    monkeypatch.setattr(window.budgeter, "load_source", lambda: calls.append("refresh"))
    monkeypatch.setattr(window.budgeter, "open_chart", lambda: calls.append("chart"))
    monkeypatch.setattr(window.budgeter, "save_csv", lambda: calls.append("csv"))
    window.refresh_data()
    window.open_chart()
    window.save_csv()
    assert calls[-3:] == ["refresh", "chart", "csv"]
    window.close()


def test_real_backend_legacy_readonly_ledger_all_strategies_export_and_transfer(qtbot, tmp_path, monkeypatch):
    import json
    import sysconfig

    from PySide6.QtCore import QThreadPool

    from leave_year_support import store, tree, tx

    data = tmp_path / "selected ledger store"
    store(
        data,
        start="2026-01-01",
        balances={"annual": 288},
        transactions=[tx("legacy", "2026-06-01", "annual", "used", 2, void=True, history=[{"old": True}])],
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
    widget = BudgetWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(widget)
    received = []
    widget.transfer_ready.connect(lambda fresh, result: received.append(transfer_session(fresh, result, today=TODAY)))
    try:
        widget.load_source()
        wait_result(qtbot, widget)
        assert widget.result.source["backend"] == str(backend)
        assert widget.result.source["data_store"] == str(data.resolve())
        widget.eligibility["annual"].setChecked(True)
        wait_result(qtbot, widget)
        for index in range(4):
            widget.strategy_combo.setCurrentIndex(index)
            wait_result(qtbot, widget)
            assert widget.result.allocated_hours == 48
            for title in result_views(widget.result):
                export_csv(tmp_path / f"export-{index}.csv", widget.snapshot, widget.result, title)
            widget.transfer()
            qtbot.waitUntil(lambda: len(received) == index + 1 and not widget._tasks, timeout=30000)
            assert received[-1].result.daily == widget.result.after.daily
        widget.cancel()
        widget.shutdown()
        qtbot.waitUntil(lambda: not widget._tasks, timeout=30000)
        assert tree(data) == before
        assert (tmp_path / "gui/analytics.json").exists()
    finally:
        for path in files:
            path.chmod(0o644)
        widget.shutdown()
        QThreadPool.globalInstance().waitForDone(30000)


def test_transfer_replace_merge_cancel_and_failed_merge_keep_draft(qtbot, monkeypatch):
    from dataclasses import replace

    from PySide6.QtWidgets import QMessageBox

    from fedleave.planning import make_operation, new_scenario
    from fedleave_analytics.planning_model import PlanningSession
    from fedleave_analytics.planning_view import PlannerWidget

    snapshot = source(balances={"annual": 288})
    result = run(snapshot, eligible_categories=("annual",))
    planner = PlannerWidget(Path("/backend"), "/store", 2026, today=TODAY)
    qtbot.addWidget(planner)
    active = replace(
        new_scenario(snapshot, today=TODAY),
        operations=(
            make_operation(snapshot, row_id="existing", operation="add", date="2026-12-29", category="annual", hours=1),
        ),
    )
    planner._install_import(PlanningSession(snapshot, today=TODAY, definition=active))
    qtbot.waitUntil(lambda: not planner._tasks, timeout=30000)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    choice = ["Cancel"]
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: next(button for button in self.buttons() if button.text().replace("&", "") == choice[0]),
    )
    original = planner._collect_definition()
    planner.accept_budget(snapshot, result)
    assert planner._collect_definition() == original
    choice[0] = "Merge operations"
    planner.accept_budget(snapshot, result)
    qtbot.waitUntil(lambda: not planner._tasks, timeout=30000)
    assert {op.row_id for op in planner.session.definition.operations} == {
        "existing",
        *(op.row_id for op in result.scenario.operations),
    }
    assert planner.session.definition.assumptions["budget_method"] == "deadline-budget-v1"
    # Same IDs cannot be silently merged a second time.
    merged = planner.session.definition
    planner.accept_budget(snapshot, result)
    qtbot.waitUntil(lambda: not planner._tasks, timeout=30000)
    assert planner.session.definition == merged
    choice[0] = "Replace scenario"
    planner.accept_budget(snapshot, result)
    qtbot.waitUntil(lambda: not planner._tasks, timeout=30000)
    assert planner.session.result.daily == result.after.daily
    assert "existing" not in {op.row_id for op in planner.session.definition.operations}
    planner.shutdown()


def test_missing_store_and_interrupted_load_cannot_create_data(qtbot, tmp_path, monkeypatch):
    import sysconfig
    from threading import Event

    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    missing = tmp_path / "missing"
    widget = BudgetWidget(backend, str(missing), 2026, today=TODAY)
    qtbot.addWidget(widget)
    widget.load_source()
    qtbot.waitUntil(lambda: not widget._tasks, timeout=30000)
    assert widget.snapshot is None
    assert not missing.exists()
    release = Event()

    def delayed(self, year):
        assert release.wait(10)
        return source()

    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource.snapshot", delayed)
    monkeypatch.setattr("fedleave_analytics.snapshots.ReadOnlySnapshotSource.years", lambda self: [2026])
    widget.load_source()
    widget.cancel()
    release.set()
    qtbot.waitUntil(lambda: not widget._tasks, timeout=30000)
    assert widget.snapshot is None
    assert not missing.exists()
    widget.shutdown()


def test_shared_preference_updates_preserve_strategy_from_another_view(tmp_path, monkeypatch):
    from fedleave_analytics.preferences import load_preferences, save_preferences

    monkeypatch.setattr(
        "fedleave_analytics.preferences.analytics_preferences_path", lambda: tmp_path / "analytics.json"
    )
    snapshot = source()
    save_preferences(snapshot, {"coverage": [], "excluded_years": [], "budget_strategy": "latest"})
    save_preferences(snapshot, {"coverage": [], "excluded_years": [2024]})
    assert load_preferences(snapshot)["budget_strategy"] == "latest"
    save_preferences(snapshot, {"budget_strategy": "even"})
    assert load_preferences(snapshot)["excluded_years"] == [2024]
    for invalid in ("surprise", []):
        with pytest.raises(ValueError, match="strategy"):
            save_preferences(snapshot, {"budget_strategy": invalid})


def test_sorted_row_details_show_exact_source_audit(qtbot, view, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QPlainTextEdit

    seen = []

    def inspect(dialog):
        control = dialog.findChild(QPlainTextEdit)
        assert control.isReadOnly()
        seen.append(control.toPlainText())
        return 0

    monkeypatch.setattr(QDialog, "exec", inspect)
    title = "Source and allocation audit"
    table = view.tables[title]
    table.sortItems(0, Qt.DescendingOrder)
    source_index = table.item(0, 0).data(Qt.UserRole + 1)
    view.show_detail(title, 0)
    assert view._views[title][0][source_index]["section"] in seen[0]
