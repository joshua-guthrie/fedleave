import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fedleave_gui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tools_menu_hides_internal_data_folder(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    tools_action = next(action for action in window.menuBar().actions() if action.text() == "Tools")
    labels = [action.text() for action in tools_action.menu().actions()]

    assert labels == [
        "Validate Data",
        "Export Data...",
        "Import Data...",
        "Open Preferences Folder",
    ]
    assert "Open Data Folder" not in labels
