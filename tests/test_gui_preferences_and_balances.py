import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDialog

from fedleave_gui.main_window import MainWindow, PreferencesDialog, SelectDateDialog, _apply_payday_offset
from fedleave_gui.settings import GuiSettings, load_settings, save_settings


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_gui_settings_round_trip_preserves_payday_offset(monkeypatch, tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("fedleave_gui.settings.settings_path", lambda: settings_file)

    save_settings(GuiSettings(payday_offset_days=4))

    loaded = load_settings()

    assert loaded.payday_offset_days == 4


def test_preferences_dialog_applies_payday_offset(monkeypatch, tmp_path: Path):
    _application()
    monkeypatch.setattr("fedleave_gui.main_window.settings_path", lambda: tmp_path / "settings.json")
    settings = GuiSettings(payday_offset_days=6)

    dialog = PreferencesDialog(settings)
    dialog.payday_offset.setValue(5)

    updated = dialog.apply()

    assert updated.payday_offset_days == 5


def test_apply_payday_offset_updates_pay_dates_and_day_flags():
    month_json = {
        "days": [
            {"date": "2026-07-11", "is_payday": False},
            {"date": "2026-07-17", "is_payday": True},
        ],
        "pay_periods": [
            {"end_date": "2026-07-11", "pay_date": "2026-07-17"},
            {"end_date": "2026-07-25", "pay_date": "2026-07-31"},
        ],
    }

    _apply_payday_offset(month_json, 0)

    assert month_json["pay_periods"][0]["pay_date"] == "2026-07-11"
    assert month_json["pay_periods"][1]["pay_date"] == "2026-07-25"
    assert month_json["pay_dates"] == ["2026-07-11", "2026-07-25"]
    assert month_json["days"][0]["is_payday"] is True
    assert month_json["days"][1]["is_payday"] is False


def test_balance_button_updates_to_selected_as_of_date(monkeypatch):
    _application()

    class FakeBackend:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        def balance(self, year: int, *, as_of: str):
            self.calls.append((year, as_of))
            return {"year": year, "as_of": as_of, "balances": {"annual": 48.0, "sick": 12.0}}

    fake_backend = FakeBackend()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: fake_backend)
    window = MainWindow()
    window.month_json = {"projected_balance": {"use_or_lose": {"annual": 24.0}}}
    window.use_or_lose_json = {"use_or_lose": {"annual": 24.0}}

    class FakeSelectDateDialog:
        def __init__(self, title, parent=None):
            self.title = title

        def exec(self):
            return QDialog.Accepted

        def selected_date(self):
            return date(2026, 5, 8)

    monkeypatch.setattr("fedleave_gui.main_window.SelectDateDialog", FakeSelectDateDialog)

    window.select_balance_date()

    assert fake_backend.calls == [(window.year, "2026-05-08")]
    assert window.balance_button.text() == "Leave Balances as of 5/8/2026"
    assert window.balance_snapshot["balances"]["annual"] == 48.0
    assert window.balance_table.item(0, 0).text() == "Annual Leave"
    assert window.balance_table.item(0, 1).text() == "48"


def test_select_date_dialog_returns_a_date_for_balance_refresh():
    _application()
    dialog = SelectDateDialog("Leave Balances as Of")
    dialog.date_input.setDate(QDate(2026, 5, 8))

    selected = dialog.selected_date()

    assert selected == date(2026, 5, 8)
    assert isinstance(selected, date)
