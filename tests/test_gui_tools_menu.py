import os
from PySide6.QtWidgets import QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFileDialog

from fedleave_gui.main_window import MainWindow
from fedleave_gui.settings import GuiSettings


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tools_menu_hides_internal_data_folder(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    tools_action = next(action for action in window.menuBar().actions() if action.text() == "Tools")
    labels = [action.text() for action in tools_action.menu().actions()]

    assert labels == [
        "Change Accrual...",
        "Validate Data",
        "Export Data...",
        "Import Data...",
    ]
    assert "Open Preferences Folder" not in labels


def test_view_menu_includes_select_month_action(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    view_action = next(action for action in window.menuBar().actions() if action.text() == "View")
    labels = [action.text() for action in view_action.menu().actions() if action.text()]

    assert "Select Month..." in labels
    assert "View Leave Transactions..." in labels


def test_file_menu_includes_change_leave_year_action(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    (tmp_path / "leave_years").mkdir()
    (tmp_path / "leave_years" / "2024.json").write_text("{}", encoding="utf-8")
    (tmp_path / "leave_years" / "2026.json").write_text("{}", encoding="utf-8")
    window.settings.data_dir = str(tmp_path)

    file_action = next(action for action in window.menuBar().actions() if action.text() == "File")
    labels = [action.text() for action in file_action.menu().actions() if action.text()]

    assert "Change Leave Year..." in labels


def test_change_leave_year_action_updates_displayed_year(monkeypatch, tmp_path):
    _application()
    refreshed: list[int] = []

    def fake_refresh(self):
        refreshed.append(self.year)

    monkeypatch.setattr(MainWindow, "refresh", fake_refresh)
    window = MainWindow()
    (tmp_path / "leave_years").mkdir()
    (tmp_path / "leave_years" / "2024.json").write_text("{}", encoding="utf-8")
    (tmp_path / "leave_years" / "2026.json").write_text("{}", encoding="utf-8")
    window.settings.data_dir = str(tmp_path)

    class FakeChangeLeaveYearDialog:
        def __init__(self, years, current_year, parent=None):
            assert years == [2024, 2026]
            assert current_year == window.year

        def exec(self):
            return QDialog.Accepted

        def selected_year(self):
            return 2024

    monkeypatch.setattr("fedleave_gui.main_window.ChangeLeaveYearDialog", FakeChangeLeaveYearDialog)

    window.change_leave_year()

    assert window.year == 2024
    assert refreshed[-1] == 2024


def test_yearly_comparison_menu_refreshes_when_a_second_leave_year_is_added(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr("fedleave_gui.main_window.load_settings", lambda: GuiSettings(data_dir=str(tmp_path)))
    window = MainWindow()

    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    (leave_years / "2026.json").write_text("{}", encoding="utf-8")

    view_action = next(action for action in window.menuBar().actions() if action.text() == "View")
    yearly_comparison_action = next(
        action for action in view_action.menu().actions() if action.menu() and action.text() == "Yearly Leave Comparison"
    )

    assert yearly_comparison_action.menu().isEnabled() is False

    (leave_years / "2027.json").write_text("{}", encoding="utf-8")
    window._refresh_yearly_comparison_menu()

    assert yearly_comparison_action.menu().isEnabled() is True


def test_change_accrual_action_updates_backend_and_refreshes(monkeypatch):
    _application()
    refreshed: list[int] = []

    def fake_refresh(self):
        refreshed.append(self.year)

    class FakeBackend:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        def accrual_change(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "action": "accrual_changed",
                "year": 2026,
                "previous_hours_per_pay_period": 6.0,
                "new_hours_per_pay_period": 8.0,
                "updated_auto_accrual_transactions": 13,
            }

    fake_backend = FakeBackend()
    monkeypatch.setattr(MainWindow, "refresh", fake_refresh)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: fake_backend)
    window = MainWindow()

    class FakeChangeAccrualDialog:
        def __init__(self, parent=None):
            self.parent = parent

        def exec(self):
            return QDialog.Accepted

        def selected_effective_date(self):
            return "2026-07-12"

        def selected_hours(self):
            return 8.0

    monkeypatch.setattr("fedleave_gui.main_window.ChangeAccrualDialog", FakeChangeAccrualDialog)

    window.change_accrual()

    assert fake_backend.calls == [
        {
            "as_of": "2026-07-12",
            "hours": 8.0,
            "category": "annual",
        }
    ]
    assert refreshed[-1] == window.year


def test_import_data_uses_safe_default_and_refreshes(monkeypatch, tmp_path):
    _application()
    captured: list[list[str]] = []
    refreshed: list[bool] = []

    class FakeBackend:
        def run_text(self, args, include_data_dir=True):
            captured.append(list(args))
            return "imported"

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: FakeBackend())
    window = MainWindow()
    window.refresh = lambda: refreshed.append(True)

    archive = tmp_path / "backup.json"
    archive.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(archive), "JSON files (*.json)"))

    window.import_data()

    assert captured == [["import-data", "--input", str(archive)]]
    assert refreshed == [True]


def test_help_menu_hides_backend_about_action(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    help_action = next(action for action in window.menuBar().actions() if action.text() == "Help")
    labels = [action.text() for action in help_action.menu().actions() if action.text()]

    assert labels == ["Help Contents", "Leave Abbreviations", "About FedLeave Calendar"]


def test_select_month_action_updates_displayed_month(monkeypatch):
    _application()
    refreshed: list[tuple[int, int]] = []

    def fake_refresh(self):
        refreshed.append((self.year, self.month))

    monkeypatch.setattr(MainWindow, "refresh", fake_refresh)
    window = MainWindow()

    class FakeSelectMonthDialog:
        def __init__(self, year, month, parent=None):
            assert (year, month) == (window.year, window.month)

        def exec(self):
            return QDialog.Accepted

        def selected_year_month(self):
            return 2027, 3

    monkeypatch.setattr("fedleave_gui.main_window.SelectMonthDialog", FakeSelectMonthDialog)

    window.select_month()

    assert (window.year, window.month) == (2027, 3)
    assert refreshed[-1] == (2027, 3)
