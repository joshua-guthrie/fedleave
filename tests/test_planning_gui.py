import json
import os
import subprocess
import sys
import sysconfig
import textwrap
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from fedleave.planning import PlanningValidationError, export_scenario
from fedleave_analytics.planning_view import PlannerWidget
from leave_year_support import store, tree, tx
from test_planning import TODAY, category, lot_source, operation, scenario, snapshot


def test_repeated_planner_rendering_and_process_shutdown_are_clean():
    # Native Qt reference corruption can surface only during a later render or
    # interpreter shutdown. Keep this in a child so a crash is a test failure,
    # including on Python 3.11 where None is not immortal.
    script = textwrap.dedent("""\
        import gc
        import json
        import sys
        import time
        from datetime import date
        from pathlib import Path
        from PySide6.QtCore import QCoreApplication, QDate, QEvent, QThreadPool
        from PySide6.QtWidgets import QApplication
        from fedleave_analytics.planning_view import PlannerWidget

        app = QApplication([])
        view = PlannerWidget(Path('/unused/backend'), '/unused/store', 2026, today=date(2026, 7, 1))

        def wait_result():
            deadline = time.monotonic() + 15
            while view.session is None or view.session.result is None or view._tasks:
                app.processEvents()
                if time.monotonic() >= deadline:
                    raise RuntimeError(view.status_label.text())
                time.sleep(.005)
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            gc.collect()

        view.set_snapshot(json.load(sys.stdin))
        wait_result()
        view.horizon_edit.setDate(QDate(2026, 7, 31))
        wait_result()
        for index in range(10):
            if index % 2:
                view.reset_scenario()
            else:
                view.add_tentative()
            view.recalculate()
            wait_result()
            assert not view.chart_image.source_pixmap().isNull()
        view.shutdown()
        assert QThreadPool.globalInstance().waitForDone(15000)
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        del view
        gc.collect()
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(snapshot()),
        text=True,
        capture_output=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def wait_result(qtbot, view, horizon="2026-07-31"):
    qtbot.waitUntil(
        lambda: view.session is not None and view.session.result is not None and view.session.result.horizon == horizon,
        timeout=15000,
    )


@pytest.fixture
def planner(qtbot):
    view = PlannerWidget(Path("/selected/backend"), "/selected/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    view.set_snapshot(snapshot())
    view.horizon_edit.setDate(QDate(2026, 7, 31))
    wait_result(qtbot, view)
    yield view
    view.shutdown()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)


def test_edit_add_reserve_invalid_row_and_no_backend_call_on_recalculation(qtbot, planner, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Scenario edits must reuse the snapshot")

    monkeypatch.setattr("fedleave_analytics.planning_view.load_planning_snapshot", forbidden)
    planner.add_tentative()
    planner.scenario_table.item(0, 2).setText("2026-07-23")
    planner.scenario_table.item(0, 4).setText("24")
    planner.reserve_edit.setText("80")
    wait_result(qtbot, planner)
    annual = category(planner.session.result).scenario
    assert (annual.horizon_balance, annual.first_reserve_breach) == (68, "2026-07-23")
    assert "Reserve breached 2026-07-23" in planner.status_label.text()
    assert not planner.chart_image.source_pixmap().isNull()
    assert planner.session.modified
    planner.scenario_table.item(0, 4).setText("NaN")
    qtbot.waitUntil(lambda: "positive hours" in planner.scenario_table.item(0, 7).text(), timeout=10000)
    assert planner.session.result is None
    assert planner.chart_image.source_pixmap().isNull()
    assert planner.scenario_table.item(0, 4).text() == "NaN"


def test_replace_remove_delete_and_reset_restore_originals_and_keep_reserve(qtbot, planner):
    planner.reserve_edit.setText("80")
    wait_result(qtbot, planner)
    planner.scheduled_table.selectRow(0)
    planner.add_selected("replace")
    planner.scenario_table.item(0, 4).setText("24")
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == 84
    assert planner.scenario_table.item(0, 6).text() == "scheduled"
    planner.scenario_table.selectRow(0)
    planner.delete_selected()
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == 92
    planner.scheduled_table.selectRow(0)
    planner.add_selected("remove")
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == 108
    planner.reset_scenario()
    wait_result(qtbot, planner)
    assert category(planner.session.result).baseline == category(planner.session.result).scenario
    assert planner.session.definition.reserves == {"annual": 80}


def test_import_is_atomic_roundtrips_and_keeps_explicit_lot_links(qtbot, planner):
    source = planner.session.snapshot
    definition = replace(scenario(source), operations=(operation(source),), reserves={"annual": 80})
    encoded = export_scenario(definition)
    planner.import_document(encoded, mode="replace")
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == 68
    before = planner.session.definition.to_dict()
    with pytest.raises(PlanningValidationError):
        planner.import_document(encoded, mode="merge")
    assert planner.session.definition.to_dict() == before
    with pytest.raises(PlanningValidationError):
        planner.import_document(encoded.replace('"schema_version": 1', '"schema_version": 99'), mode="replace")
    assert planner.session.definition.to_dict() == before
    assert not planner.session.modified
    assert planner.scenario_table.item(0, 0).text() == "tentative"


def test_stale_material_reference_remains_visible_until_explicit_resolution(qtbot, planner):
    planner.scheduled_table.selectRow(0)
    planner.add_selected("replace")
    wait_result(qtbot, planner)
    changed = deepcopy(planner.session.snapshot)
    changed["transactions"][0]["hours"] = 8
    planner.set_snapshot(changed)
    qtbot.waitUntil(lambda: "changed materially" in planner.status_label.text(), timeout=10000)
    assert planner.session.result is None
    assert planner.scenario_table.item(0, 6).text() == "scheduled"
    planner.scenario_table.selectRow(0)
    planner.resolve_selected()
    wait_result(qtbot, planner)
    assert planner.session.definition.operations[0].original_ids == ("scheduled",)


def test_file_import_refreshes_source_and_rejects_stale_refs_atomically(qtbot, planner, monkeypatch, tmp_path):
    source = deepcopy(planner.session.snapshot)
    encoded = export_scenario(
        replace(scenario(source), operations=(operation(source, operation="replace", original_ids=("scheduled",)),))
    )
    path = tmp_path / "import.json"
    path.write_text(encoded)
    changed = deepcopy(source)
    changed["transactions"][0]["hours"] = 8
    calls = []

    def load(*args):
        calls.append(args)
        return changed

    monkeypatch.setattr("fedleave_analytics.planning_view.load_planning_snapshot", load)
    before = planner.session.definition.to_dict(), planner.session.result
    planner.start_import(path, mode="replace")
    qtbot.waitUntil(lambda: "Import rejected" in planner.status_label.text(), timeout=10000)
    assert (planner.session.definition.to_dict(), planner.session.result) == before
    assert len(calls) == 1
    assert "changed materially" in planner.status_label.text()
    changed["transactions"][0]["hours"] = 16
    changed["transactions"].append(tx("unrelated", "2026-07-30", "sick", "used", 1))
    planner.start_import(path, mode="replace")
    qtbot.waitUntil(lambda: planner.session.definition.operations != (), timeout=10000)
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == 84
    assert category(planner.session.result, "sick").scenario.horizon_balance == 39


def test_imported_explicit_lot_link_survives_gui_roundtrip(qtbot, planner):
    source = lot_source()
    planner.set_snapshot(source)
    wait_result(qtbot, planner)
    op = operation(source, category="comp", date="2026-07-14", hours=2, earned_transaction_id="lot")
    planner.import_document(export_scenario(replace(scenario(source), operations=(op,))), mode="replace")
    wait_result(qtbot, planner)
    assert planner.scenario_table.item(0, 8).text() == "lot"
    assert planner.session.definition.operations[0].earned_transaction_id == "lot"
    assert planner._collect_definition()["operations"][0]["earned_transaction_id"] == "lot"


def test_old_worker_results_are_discarded_after_an_edit_cancel_or_source_change(planner):
    old_revision = planner._revision
    old_definition, old_result = planner.session.definition, planner.session.result
    planner.name_edit.setText("new draft")
    planner._finished(old_revision, "calculate", (old_definition, old_result))
    assert planner.session.result is None
    planner.cancel()
    planner._finished(old_revision, "calculate", (old_definition, old_result))
    assert planner.session.result is None
    planner.set_source(Path("/other/backend"), "/other/data", 2027)
    planner._finished(old_revision, "load", snapshot())
    assert planner.session is None


def test_canceled_load_and_window_close_never_install_late_snapshot(qtbot, monkeypatch):
    release = Event()

    def slow_load(*args):
        assert release.wait(10)
        return snapshot()

    monkeypatch.setattr("fedleave_analytics.planning_view.load_planning_snapshot", slow_load)
    view = PlannerWidget(Path("/backend"), "/store", 2026, today=TODAY)
    qtbot.addWidget(view)
    view.load_source()
    assert not view.add_button.isEnabled()
    view.cancel()
    view.shutdown()
    release.set()
    qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
    assert view.session is None
    assert view._closed


def test_chart_popup_has_exact_supporting_rows_and_all_export_actions(planner):
    planner.open_chart()
    chart = planner._charts[0]
    file_action = chart.menuBar().actions()[0]
    file_menu = file_action.menu()
    labels = [action.text() for action in file_menu.actions()]
    assert {"Save Table as CSV...", "Save Graphic as PNG...", "Save Graphic as PDF...", "Print..."} <= set(labels)
    table = chart.centralWidget().widget(1)
    assert table.rowCount() == len(planner._views["Daily closing balances"][0])
    assert not chart._pixmap.isNull()
    chart.close()


def test_real_backend_legacy_read_only_store_survives_full_planner_lifecycle(qtbot, tmp_path, monkeypatch):
    data = tmp_path / "selected datastore with spaces"
    ledger, _ = store(
        data,
        balances={"annual": 100},
        transactions=[
            tx("future", "2026-07-15", "annual", "used", 8),
            tx("legacy", "2026-06-02", "annual", "used", 2, void=True, history=[{"old": True}]),
        ],
    )
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    before = tree(data)
    year_file = data / "leave_years/2026.json"
    year_file.chmod(0o444)
    if os.name != "nt":
        year_file.parent.chmod(0o555)
    view = PlannerWidget(backend, str(data), 2026, today=TODAY)
    qtbot.addWidget(view)
    try:
        view.load_source()
        qtbot.waitUntil(lambda: view.session is not None, timeout=15000)
        view.horizon_edit.setDate(QDate(2026, 7, 31))
        wait_result(qtbot, view)
        view.add_tentative()
        wait_result(qtbot, view)
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
        view.pick_date(0, 2)
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        view.choose_scheduled("replace")
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        view.choose_scheduled("remove")
        definition_path = tmp_path / "scenario.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(definition_path), "JSON"))
        view.export_json()
        assert json.loads(definition_path.read_text())["operations"]
        view.import_document(definition_path.read_text(), mode="replace")
        wait_result(qtbot, view)
        view.session.export_csv(tmp_path / "results.csv", "annual", "Daily closing balances")
        before_import = view.session.definition.to_dict()
        with pytest.raises(PlanningValidationError):
            view.import_document("{}", mode="replace")
        assert view.session.definition.to_dict() == before_import
        view.reset_scenario()
        wait_result(qtbot, view)
        view.cancel()
        view.shutdown()
        view.close()
        qtbot.waitUntil(lambda: not view._tasks, timeout=15000)
        assert tree(data) == before
    finally:
        if os.name != "nt":
            year_file.parent.chmod(0o755)
        year_file.chmod(0o644)
        view.shutdown()
        QThreadPool.globalInstance().waitForDone(15000)
