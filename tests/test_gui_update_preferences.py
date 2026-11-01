"""Exercise persistent update preferences at the GUI's network boundary."""

import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from fedleave_gui.main_window import MainWindow, PreferencesDialog
from fedleave_gui.settings import load_settings


@pytest.fixture
def update_window(qtbot, monkeypatch, tmp_path):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("fedleave_gui.settings.settings_path", lambda: settings_file)
    monkeypatch.setattr("fedleave_gui.main_window.settings_path", lambda: settings_file)
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    calls = []

    def check_for_updates(self):
        calls.append(True)
        return {"status": "ok", "update_available": False}

    monkeypatch.setattr("fedleave_gui.backend.FedleaveBackend.check_for_updates", check_for_updates)
    window = MainWindow()
    qtbot.addWidget(window)
    return window, settings_file, calls


@pytest.mark.parametrize("legacy", [False, True])
def test_automatic_checks_default_to_enabled_for_new_and_existing_settings(update_window, legacy):
    window, settings_file, calls = update_window
    if legacy:
        settings_file.write_text(json.dumps({"font_size": 12}), encoding="utf-8")
    window.settings = load_settings()

    window.check_for_updates_periodically()
    window.check_for_updates_periodically()

    assert window.settings.automatic_update_checks is True
    assert calls == [True]  # A second callback still respects the daily throttle.
    if legacy:
        assert load_settings().font_size == 12


def test_saved_preference_blocks_startup_and_timer_checks_after_restart(update_window, qtbot, monkeypatch):
    window, settings_file, calls = update_window
    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: scheduled.append((delay, callback)))
    # The user can save Preferences before the queued startup check fires.
    window.start_background_checks()

    def disable_updates(dialog):
        assert dialog.automatic_update_checks.isChecked()
        dialog.automatic_update_checks.setChecked(False)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(PreferencesDialog, "exec", disable_updates)
    window.preferences()
    saved = settings_file.read_bytes()
    assert json.loads(saved)["automatic_update_checks"] is False
    assert load_settings().last_update_check_utc == ""

    startup_check = next(callback for delay, callback in scheduled if delay == 1500)
    startup_check()
    window._update_timer.timeout.emit()

    reopened = MainWindow()
    qtbot.addWidget(reopened)
    scheduled.clear()
    reopened.start_background_checks()
    next(callback for delay, callback in scheduled if delay == 1500)()
    reopened._update_timer.timeout.emit()

    assert calls == []
    assert settings_file.read_bytes() == saved
    assert reopened.settings.automatic_update_checks is False
    dialog = PreferencesDialog(reopened.settings)
    qtbot.addWidget(dialog)
    assert not dialog.automatic_update_checks.isChecked()


def test_cancel_does_not_change_update_preference_or_write_settings(update_window, monkeypatch):
    window, settings_file, calls = update_window

    def cancel_changes(dialog):
        dialog.automatic_update_checks.setChecked(False)
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(PreferencesDialog, "exec", cancel_changes)
    window.preferences()

    assert window.settings.automatic_update_checks is True
    assert not settings_file.exists()
    window.check_for_updates_periodically()
    assert calls == [True]


def test_manual_help_action_still_checks_when_automatic_checks_are_disabled(update_window, monkeypatch):
    window, settings_file, calls = update_window
    window.settings.automatic_update_checks = False
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    help_menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "Help")
    action = next(action for action in help_menu.actions() if action.text() == "Check for Updates...")

    action.trigger()

    assert calls == [True]
    assert messages == ["This installation is up to date."]
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["automatic_update_checks"] is False
    assert saved["last_update_check_utc"]


@pytest.mark.parametrize("recent_check", [False, True])
def test_reenable_restores_periodic_checks_with_existing_daily_throttle(update_window, monkeypatch, recent_check):
    window, settings_file, calls = update_window
    window.settings.automatic_update_checks = False
    previous = datetime.now(timezone.utc) - timedelta(hours=1 if recent_check else 25)
    window.settings.last_update_check_utc = previous.isoformat()

    def enable_updates(dialog):
        assert not dialog.automatic_update_checks.isChecked()
        dialog.automatic_update_checks.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(PreferencesDialog, "exec", enable_updates)
    window.preferences()
    window.check_for_updates_periodically()

    assert calls == ([] if recent_check else [True])
    assert load_settings().automatic_update_checks is True
    assert settings_file.exists()
