"""Issue #137: real calendar/chooser interaction and offline contextual help."""

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.help_view import AnalyticsHelpDialog
from fedleave_analytics.planning_controls import ScenarioDateDialog, ScheduledUseDialog
from fedleave_analytics.planning_view import PlannerWidget
from test_planning import category, tx
from test_planning_gui import planner as planner
from test_planning_gui import wait_result


def test_single_click_and_keyboard_open_calendar_commit_and_cancel(qtbot, planner):
    original = deepcopy(planner.session.snapshot)
    planner.add_tentative()
    wait_result(qtbot, planner)
    planner.resize(1250, 850)
    planner.show()
    item = planner.scenario_table.item(0, 2)
    seen = []

    def choose():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ScenarioDateDialog)
        seen.append(dialog.calendar.selectedDate())
        assert dialog.calendar.minimumDate() == QDate(2026, 7, 2)
        assert dialog.calendar.maximumDate() == QDate(2026, 7, 31)
        dialog.calendar.setSelectedDate(QDate(2026, 7, 23))
        dialog.calendar.clicked.emit(QDate(2026, 7, 23))

    QTimer.singleShot(0, choose)
    qtbot.mouseClick(
        planner.scenario_table.viewport(), Qt.LeftButton, pos=planner.scenario_table.visualItemRect(item).center()
    )
    assert seen == [QDate(2026, 7, 2)]
    assert item.text() == "2026-07-23"
    wait_result(qtbot, planner)
    planner.scenario_table.setCurrentCell(0, 2)
    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
    qtbot.keyClick(planner.scenario_table, Qt.Key_Space)
    assert item.text() == "2026-07-23"
    assert planner.session.snapshot == original


def test_cancel_preserves_invalid_date_and_remove_has_no_date_picker(qtbot, planner, monkeypatch):
    planner.add_tentative()
    planner.scenario_table.item(0, 2).setText("not-a-date")
    monkeypatch.setattr(ScenarioDateDialog, "exec", lambda dialog: QDialog.Rejected)
    planner.pick_date(0, 2)
    assert planner.scenario_table.item(0, 2).text() == "not-a-date"
    planner.reset_scenario()
    wait_result(qtbot, planner)
    planner.scheduled_table.selectRow(0)
    planner.add_selected("remove")
    wait_result(qtbot, planner)

    def forbidden(*args):
        raise AssertionError("Remove operations have no editable date")

    monkeypatch.setattr("fedleave_analytics.planning_view.ScenarioDateDialog", forbidden)
    planner.pick_date(0, 2)
    assert not planner.scenario_table.item(0, 2).flags() & Qt.ItemIsEditable


def test_no_future_dates_does_not_invent_a_date(qtbot, planner, monkeypatch):
    planner.add_tentative()
    planner.cutoff_edit.setDate(planner.horizon_edit.date())
    before = planner.scenario_table.item(0, 2).text()
    monkeypatch.setattr(ScenarioDateDialog, "exec", lambda dialog: pytest.fail("No date window is available"))
    planner.pick_date(0, 2)
    assert planner.scenario_table.item(0, 2).text() == before
    assert "No tentative date" in planner.status_label.text()


@pytest.mark.parametrize("operation", ["replace", "remove"])
def test_action_button_chooses_booking_without_background_selection(qtbot, planner, operation):
    original = deepcopy(planner.session.snapshot)
    planner.scheduled_table.clearSelection()
    seen = []

    def choose():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ScheduledUseDialog)
        assert not dialog.confirm_button.isEnabled()
        dialog.table.item(0, 0).setCheckState(Qt.Checked)
        assert dialog.confirm_button.isEnabled()
        seen.extend(dialog.selected_transactions())
        dialog.confirm_button.click()

    QTimer.singleShot(0, choose)
    qtbot.mouseClick(planner.replace_button if operation == "replace" else planner.remove_button, Qt.LeftButton)
    assert [row["id"] for row in seen] == ["scheduled"]
    assert planner.scenario_table.item(0, 6).text() == "scheduled"
    if operation == "replace":
        planner.scenario_table.item(0, 4).setText("24")
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == (84 if operation == "replace" else 108)
    planner.scenario_table.selectRow(0)
    qtbot.mouseClick(planner.delete_button, Qt.LeftButton)
    wait_result(qtbot, planner)
    assert category(planner.session.result).scenario.horizon_balance == 92
    assert planner.session.snapshot == original


def test_sorted_multiselect_chooser_uses_ids_and_blocks_already_targeted(qtbot):
    rows = [
        tx(id="first", day="2026-07-10", hours=4),
        tx(id="second", day="2026-07-20", hours=8),
        tx(id="blocked", day="2026-07-25", hours=2),
    ]
    original = deepcopy(rows)
    dialog = ScheduledUseDialog(rows, "replace", selected_ids={"first", "blocked"}, targeted_ids={"blocked"})
    qtbot.addWidget(dialog)
    dialog.table.sortItems(1, Qt.DescendingOrder)
    assert not dialog.table.item(0, 0).flags() & Qt.ItemIsEnabled
    assert dialog.table.item(0, 0).checkState() == Qt.Unchecked
    dialog.table.item(1, 0).setCheckState(Qt.Checked)
    assert [row["id"] for row in dialog.selected_transactions()] == ["first", "second"]
    assert rows == original


def test_chooser_cancel_and_empty_list_leave_draft_intact(qtbot, planner, monkeypatch):
    before = planner._collect_definition()
    monkeypatch.setattr(ScheduledUseDialog, "exec", lambda dialog: QDialog.Rejected)
    planner.choose_scheduled("replace")
    assert planner._collect_definition() == before
    dialog = ScheduledUseDialog([], "remove")
    qtbot.addWidget(dialog)
    assert not dialog.confirm_button.isEnabled()
    assert "No existing scheduled leave" in dialog.notice.text()


def test_help_is_offline_contextual_and_all_planning_actions_have_tips(qtbot, monkeypatch):
    monkeypatch.setattr(PlannerWidget, "activate", lambda self: None)
    window = AnalyticsWindow(Path("/backend"), "/store", 2026, auto_load=False, initial_view="planning")
    qtbot.addWidget(window)
    for widget in (window.planner, window.forecaster, window.budgeter):
        monkeypatch.setattr(widget, "activate", lambda: None)
        assert all(button.toolTip() for button in widget.findChildren(QPushButton))
    expected = {window.planner: "what-if", window.forecaster: "forecast", window.budgeter: "budget"}
    seen = []

    def inspect(dialog):
        assert dialog.available
        text = dialog.browser.toPlainText()
        assert all(
            word in text
            for word in (
                "Add tentative use",
                "Replace scheduled use",
                "Remove scheduled use",
                "Undo selected changes",
                "Usage Forecast",
                "Leave Budget",
                "100 hours",
                "92-hour baseline",
            )
        )
        seen.append(window.help_section())
        return QDialog.Rejected

    monkeypatch.setattr(AnalyticsHelpDialog, "exec", inspect)
    for widget, section in expected.items():
        window.planning_tabs.setCurrentWidget(widget)
        window.help_action.trigger()
        assert seen[-1] == section
    window.pages.setCurrentWidget(window.summary_page)
    window.help_action.trigger()
    assert seen[-1] == "overview"
    assert window.help_action.shortcut().toString() == "F1"
    window.close()
