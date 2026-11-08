"""What-if planner calendar interaction and offline contextual help."""

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from fedleave_analytics.help_view import AnalyticsHelpDialog
from fedleave_analytics.planning_controls import ScenarioDateDialog
from fedleave_analytics.planning_view import PlannerWidget
from fedleave_analytics.planning_window import PlanningWindow
from test_planning_gui import planner as planner
from test_planning_gui import row_with_source, wait_result


def test_single_click_and_keyboard_open_calendar_commit_and_cancel(qtbot, planner):
    original = deepcopy(planner.session.snapshot)
    planner.add_tentative()
    wait_result(qtbot, planner)
    planner.resize(1250, 850)
    planner.show()
    row = row_with_source(planner, "Proposed")
    item = planner.scenario_table.item(row, 1)
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
    planner.scenario_table.setCurrentCell(row, 1)
    QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
    qtbot.keyClick(planner.scenario_table, Qt.Key_Space)
    assert item.text() == "2026-07-23"
    assert planner.session.snapshot == original


def test_cancel_preserves_invalid_proposed_date_and_scheduled_rows_have_no_picker(qtbot, planner, monkeypatch):
    planner.add_tentative()
    proposed = row_with_source(planner, "Proposed")
    planner.scenario_table.item(proposed, 1).setText("not-a-date")
    monkeypatch.setattr(ScenarioDateDialog, "exec", lambda dialog: QDialog.Rejected)
    planner.pick_date(proposed, 1)
    assert planner.scenario_table.item(proposed, 1).text() == "not-a-date"

    scheduled = row_with_source(planner, "Scheduled")

    def forbidden(*args):
        raise AssertionError("Scheduled dates are fixed")

    monkeypatch.setattr("fedleave_analytics.planning_view.ScenarioDateDialog", forbidden)
    planner.pick_date(scheduled, 1)
    assert not planner.scenario_table.item(scheduled, 1).flags() & Qt.ItemIsEditable


def test_no_future_dates_does_not_invent_a_date(qtbot, planner, monkeypatch):
    planner.add_tentative()
    planner.cutoff_edit.setDate(planner.horizon_edit.date())
    proposed = row_with_source(planner, "Proposed")
    before = planner.scenario_table.item(proposed, 1).text()
    monkeypatch.setattr(ScenarioDateDialog, "exec", lambda dialog: pytest.fail("No date window is available"))
    planner.pick_date(proposed, 1)
    assert planner.scenario_table.item(proposed, 1).text() == before
    assert "No tentative date" in planner.status_label.text()


def test_help_is_offline_contextual_and_all_planning_actions_have_tips(qtbot, monkeypatch):
    monkeypatch.setattr(PlannerWidget, "activate", lambda self: None)
    words = (
        "Add tentative use",
        "Unchanged",
        "Replace",
        "Proposed",
        "100 hours",
        "92-hour baseline",
    )
    seen = []

    def inspect(dialog):
        assert dialog.available
        text = dialog.browser.toPlainText()
        assert all(word in text for word in words)
        seen.append(window.help_section_name)
        return QDialog.Rejected

    monkeypatch.setattr(AnalyticsHelpDialog, "exec", inspect)
    window = PlanningWindow("what-if", Path("/backend"), "/store", 2026)
    qtbot.addWidget(window)
    assert all(button.toolTip() for button in window.widget.findChildren(QPushButton))
    window.help_action.trigger()
    assert seen == ["what-if"]
    assert window.help_action.shortcut().toString() == "F1"
    window.close()
