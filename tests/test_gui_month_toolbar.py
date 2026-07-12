import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fedleave_gui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_month_toolbar_uses_centered_layout_with_larger_controls(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    window.year = 2026
    window.month = 7
    window.month_json = {"days": [], "pay_periods": []}
    window.render_month()

    assert window.title_label.text() == "July 2026"
    assert window.previous_button.text() == "< Previous"
    assert window.today_button.text() == "Today"
    assert window.next_button.text() == "Next >"

    assert window.previous_button.font().pointSizeF() >= 16.0
    assert window.today_button.font().pointSizeF() >= 16.0
    assert window.next_button.font().pointSizeF() >= 16.0
    assert window.title_label.font().pointSizeF() >= 16.0
    assert window.previous_button.font().bold() is True
    assert window.today_button.font().bold() is True
    assert window.next_button.font().bold() is True
    assert window.title_label.font().bold() is True

    layout = window.month_toolbar_layout
    assert layout.itemAt(0).widget() is window.previous_button
    assert layout.itemAt(1).spacerItem() is not None
    assert layout.itemAt(2).widget() is window.month_toolbar_center
    assert layout.itemAt(3).spacerItem() is not None
    assert layout.itemAt(4).widget() is window.next_button

    center_layout = window.month_toolbar_center.layout()
    assert center_layout.itemAt(0).widget() is window.title_label
    assert center_layout.itemAt(1).widget() is window.today_button
