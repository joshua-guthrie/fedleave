import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from fedleave_gui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_file_menu_exposes_month_graphic_export(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    file_action = next(action for action in window.menuBar().actions() if action.text() == "File")
    labels = [action.text() for action in file_action.menu().actions()]

    assert labels == [
        "New Leave Year...",
        "Refresh",
        "Print Preview...",
        "Print Month...",
        "Save Month as PDF...",
        "Save Month as PNG/SVG...",
        "Preferences...",
        "Exit",
    ]


def test_save_month_graphic_runs_companion_app_with_current_month(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    window.year = 2026
    window.month = 7
    window.settings.data_dir = "/tmp/fedleave-data"
    window.backend = SimpleNamespace(executable_path=lambda: Path("/tmp/fedleave"))

    captured: dict[str, object] = {}

    def fake_run_month_report_graphic(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("fedleave_gui.main_window.run_month_report_graphic", fake_run_month_report_graphic)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(tmp_path / "month"), "SVG files (*.svg)"))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    window.save_month_graphic()

    assert captured == {
        "output_file": tmp_path / "month.svg",
        "year": 2026,
        "month": 7,
        "fedleave_path": "/tmp/fedleave",
        "data_dir": "/tmp/fedleave-data",
    }
