import os
import json
from PySide6.QtWidgets import QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QMessageBox

from fedleave_gui.backend import BackendError
from fedleave_gui.main_window import MainWindow, _visible_categories
from fedleave_gui.settings import GuiSettings


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_valid_year(path, year: int) -> None:
    path.write_text(
        json.dumps(
            {
                "leave_year": year,
                "leave_year_start": f"{year}-01-01",
                "leave_year_end": f"{year}-12-31",
                "starting_balances": {},
                "transactions": [],
            }
        ),
        encoding="utf-8",
    )


class _MetadataBackend:
    def __init__(self, years: list[int], visible_categories: list[str] | None = None):
        self._years = years
        self._visible_categories = visible_categories or []

    def leave_years(self):
        return {
            "years": [
                {
                    "leave_year": year,
                    "start_date": None,
                    "end_date": None,
                    "valid": True,
                }
                for year in self._years
            ],
            "visible_categories": self._visible_categories,
            "warnings": [],
        }


def test_tools_menu_hides_internal_data_folder(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    tools_action = next(action for action in window.menuBar().actions() if action.text() == "Tools")
    labels = [action.text() for action in tools_action.menu().actions()]

    assert labels == [
        "Change Accrual...",
        "Force Leave Balance...",
        "Expiring Leave Status...",
        "Validate Data",
        "Export FedLeave Data...",
        "Import FedLeave Data...",
        "Import From External App",
    ]
    assert "Open Preferences Folder" not in labels


def test_view_menu_includes_select_month_action(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    view_action = next(action for action in window.menuBar().actions() if action.text() == "View")
    labels = [action.text() for action in view_action.menu().actions() if action.text()]

    assert "Select Month..." in labels
    assert "View Leave Transactions..." not in labels
    assert "Analytics..." not in labels
    analysis_action = next(action for action in window.menuBar().actions() if action.text() == "Analysis")
    analysis_labels = [action.text() for action in analysis_action.menu().actions() if action.text()]
    assert "View Leave Transactions..." in analysis_labels
    assert "Analytics..." in analysis_labels


def test_analytics_view_action_launches_companion_with_current_context(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(
        "fedleave_gui.main_window.load_settings",
        lambda: GuiSettings(data_dir=str(tmp_path / "data"), font_size=12, pdf_export_folder=str(tmp_path / "pdf")),
    )
    window = MainWindow()
    window.year = 2027
    backend_path = tmp_path / "fedleave"
    analytics_path = tmp_path / "FedLeaveAnalytics"
    calls = []
    monkeypatch.setattr(window.backend, "executable_path", lambda: backend_path)
    monkeypatch.setattr("fedleave_gui.main_window.find_analytics", lambda: analytics_path)
    monkeypatch.setattr("fedleave_gui.main_window.subprocess.Popen", lambda command: calls.append(command))

    window.open_analytics()

    assert calls == [[
        str(analytics_path),
        "--backend", str(backend_path),
        "--year", "2027",
        "--font-size", "12",
        "--data-dir", str(tmp_path / "data"),
        "--pdf-folder", str(tmp_path / "pdf"),
    ]]


def test_analytics_view_action_passes_resolved_default_data_directory(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr("fedleave_gui.main_window.load_settings", lambda: GuiSettings())
    monkeypatch.setattr("fedleave_gui.main_window.get_default_data_dir", lambda _data_dir=None: tmp_path / "data")
    window = MainWindow()
    backend_path = tmp_path / "fedleave"
    analytics_path = tmp_path / "FedLeaveAnalytics"
    calls = []
    monkeypatch.setattr(window.backend, "executable_path", lambda: backend_path)
    monkeypatch.setattr("fedleave_gui.main_window.find_analytics", lambda: analytics_path)
    monkeypatch.setattr("fedleave_gui.main_window.subprocess.Popen", lambda command: calls.append(command))

    window.open_analytics()

    assert "--data-dir" in calls[0]
    assert calls[0][calls[0].index("--data-dir") + 1] == str(tmp_path / "data")


def test_file_menu_includes_change_leave_year_action(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    (tmp_path / "leave_years").mkdir()
    (tmp_path / "leave_years" / "2024.json").write_text("{}", encoding="utf-8")
    (tmp_path / "leave_years" / "2026.json").write_text("{}", encoding="utf-8")
    window.settings.data_dir = str(tmp_path)
    window.backend = _MetadataBackend([2024, 2026])

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
    window.backend = _MetadataBackend([2024, 2026])

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


def test_startup_loads_current_leave_year_when_available(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(
        "fedleave_gui.main_window.load_settings",
        lambda: GuiSettings(data_dir=str(tmp_path)),
    )
    window = MainWindow()
    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    _write_valid_year(leave_years / f"{window.today.year}.json", window.today.year)
    refreshed = []
    window.refresh = lambda: refreshed.append(window.year)

    window.start_initial_load()

    assert window.year == window.today.year
    assert refreshed == [window.today.year]


def test_startup_uses_latest_available_leave_year_when_current_is_missing(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(
        "fedleave_gui.main_window.load_settings",
        lambda: GuiSettings(data_dir=str(tmp_path)),
    )
    window = MainWindow()
    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    _write_valid_year(leave_years / "2024.json", 2024)
    _write_valid_year(leave_years / "2025.json", 2025)
    refreshed = []
    window.refresh = lambda: refreshed.append(window.year)

    window.start_initial_load()

    assert window.year == 2025
    assert refreshed == [2025]


def test_first_run_offers_to_open_new_leave_year_dialog(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(
        "fedleave_gui.main_window.load_settings",
        lambda: GuiSettings(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    window = MainWindow()
    opened = []
    window.new_leave_year = lambda: opened.append(True)

    window.start_initial_load()

    assert opened == [True]


def test_first_run_can_decline_new_leave_year_without_backend_error(monkeypatch, tmp_path):
    _application()
    refresh_calls = []
    monkeypatch.setattr(MainWindow, "refresh", lambda self: refresh_calls.append(True))
    monkeypatch.setattr(
        "fedleave_gui.main_window.load_settings",
        lambda: GuiSettings(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.No,
    )
    window = MainWindow()

    window.start_initial_load()

    assert refresh_calls == []


def test_yearly_comparison_menu_refreshes_when_a_second_leave_year_is_added(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr("fedleave_gui.main_window.load_settings", lambda: GuiSettings(data_dir=str(tmp_path)))
    window = MainWindow()

    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    _write_valid_year(leave_years / "2026.json", 2026)

    view_action = next(action for action in window.menuBar().actions() if action.text() == "Analysis")
    yearly_comparison_action = next(
        action for action in view_action.menu().actions() if action.menu() and action.text() == "Yearly Leave Comparison"
    )

    assert yearly_comparison_action.menu().isEnabled() is False

    _write_valid_year(leave_years / "2027.json", 2027)
    window._refresh_yearly_comparison_menu()

    assert yearly_comparison_action.menu().isEnabled() is True


def test_category_visibility_considers_balances_and_transactions_across_years(tmp_path):
    leave_years = tmp_path / "leave_years"
    leave_years.mkdir()
    (leave_years / "2025.json").write_text(json.dumps({
        "starting_balances": {"annual": 20, "religious_comp": 0},
        "transactions": [],
    }), encoding="utf-8")
    (leave_years / "2026.json").write_text(json.dumps({
        "starting_balances": {},
        "transactions": [
            {"category": "overtime", "hours": 2, "status": "reconciled"},
            {"category": "religious_comp", "hours": 4, "status": "denied"},
        ],
    }), encoding="utf-8")

    assert _visible_categories(_MetadataBackend([2025, 2026], ["annual", "overtime"])) == {
        "annual",
        "overtime",
    }


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


def test_import_data_can_merge_and_refreshes(monkeypatch, tmp_path):
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
    monkeypatch.setattr(window, "_select_import_mode", lambda: "--merge")

    archive = tmp_path / "backup.json"
    archive.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(archive), "JSON files (*.json)"))

    window.import_data()

    assert captured == [["import-data", "--input", str(archive), "--merge"]]
    assert refreshed == [True]


def test_import_data_can_replace(monkeypatch, tmp_path):
    _application()
    captured: list[list[str]] = []

    class FakeBackend:
        def run_text(self, args, include_data_dir=True):
            captured.append(list(args))
            return "imported"

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: FakeBackend())
    window = MainWindow()
    monkeypatch.setattr(window, "_select_import_mode", lambda: "--overwrite")

    archive = tmp_path / "backup.json"
    archive.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(archive), "JSON files (*.json)"))

    window.import_data()

    assert captured == [["import-data", "--input", str(archive), "--overwrite"]]


def test_import_data_cancel_does_not_run_backend(monkeypatch, tmp_path):
    _application()
    captured: list[list[str]] = []

    class FakeBackend:
        def run_text(self, args, include_data_dir=True):
            captured.append(list(args))
            return "imported"

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: FakeBackend())
    window = MainWindow()
    monkeypatch.setattr(window, "_select_import_mode", lambda: None)

    archive = tmp_path / "backup.json"
    archive.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(archive), "JSON files (*.json)"))

    window.import_data()

    assert captured == []


def test_import_wms_http_report_uses_html_picker_and_refreshes(monkeypatch, tmp_path):
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

    report = tmp_path / "clocking.html"
    report.write_text("<html><body><table class='jrPage'></table></body></html>", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(report), "HTML files (*.html *.htm)"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    window.import_wms_http_leave_report()

    assert captured == [["import-wms-http", "--input", str(report)]]
    assert refreshed == [True]


def test_wms_import_warning_precedes_picker_and_can_cancel(monkeypatch):
    _application()
    events: list[str] = []
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, text, *_args: events.append(text) or QMessageBox.Cancel,
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: events.append("picker") or ("", ""),
    )

    window.import_wms_http_leave_report()

    assert len(events) == 1
    assert "experimental" in events[0].lower()
    assert "GitHub issues" in events[0]
    assert "private" in events[0]


def test_wms_import_failure_uses_copyable_diagnostic_dialog(monkeypatch, tmp_path):
    _application()
    shown = []

    class FakeBackend:
        def run_text(self, args, include_data_dir=True):
            raise BackendError("WMS IMPORT COULD NOT CONTINUE\nReport row: 17\nGitHub issue URL")

    class FakeDiagnosticDialog:
        def __init__(self, title, report, parent=None):
            shown.append((title, report))

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: FakeBackend())
    monkeypatch.setattr("fedleave_gui.main_window.DiagnosticDialog", FakeDiagnosticDialog)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(tmp_path / "clocking.html"), "HTML"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    window = MainWindow()

    window.import_wms_http_leave_report()

    assert shown == [("WMS Import Failed", "WMS IMPORT COULD NOT CONTINUE\nReport row: 17\nGitHub issue URL")]


def test_force_balance_dialog_calls_backend_and_refreshes(monkeypatch):
    _application()
    calls = []
    refreshed = []

    class FakeBackend:
        def force_balance(self, **values):
            calls.append(values)
            return {**values, "forced_balance": values["hours"]}

    class FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

        def values(self):
            return {"date": "2026-07-22", "category": "annual", "hours": 40.0, "comment": "Payroll balance"}

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: FakeBackend())
    monkeypatch.setattr("fedleave_gui.main_window.ForceBalanceDialog", FakeDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    window = MainWindow()
    window.refresh = lambda: refreshed.append(True)

    window.force_leave_balance()

    assert calls == [{"date": "2026-07-22", "category": "annual", "hours": 40.0, "comment": "Payroll balance"}]
    assert refreshed == [True]


def test_periodic_update_alert_is_not_repeated_for_same_version(monkeypatch):
    _application()
    alerts = []

    class FakeBackend:
        def check_for_updates(self):
            return {
                "status": "ok",
                "update_available": True,
                "current_version": "0.2.0",
                "latest_version": "0.3.0",
                "release_url": "https://github.com/joshua-guthrie/fedleave/releases/tag/v0.3.0",
                "instructions": "Run the installer.",
            }

    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: FakeBackend())
    monkeypatch.setattr("fedleave_gui.main_window.save_settings", lambda settings: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: alerts.append(args[2]))
    window = MainWindow()

    window._perform_update_check(interactive=False)
    window._perform_update_check(interactive=False)

    assert len(alerts) == 1
    assert "0.3.0" in alerts[0]


def test_help_menu_hides_backend_about_action(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    help_action = next(action for action in window.menuBar().actions() if action.text() == "Help")
    labels = [action.text() for action in help_action.menu().actions() if action.text()]

    assert labels == [
        "Help Contents", "Leave Abbreviations", "Official Project Website",
        "Check for Updates...", "About FedLeave Calendar",
    ]


def test_open_project_website_uses_official_url(monkeypatch):
    _application()
    opened: list[str] = []
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr("fedleave_gui.main_window.webbrowser.open", opened.append)
    window = MainWindow()

    window.open_project_website()

    assert opened == ["https://www.westmouthbay.com/fedleave-application/"]


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
