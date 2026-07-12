import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fedleave_gui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_balance_table_headers_follow_left_aligned_text(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    window.month_json = {
        "balance_as_of_today": {"balances": {"annual": 12.0, "sick": 8.0}},
        "projected_balance": {"use_or_lose": {"use_or_lose": 240.0}},
    }

    window._render_balances()

    assert window.balance_table.horizontalHeaderItem(0).textAlignment() & Qt.AlignLeft
    assert all(window.balance_table.horizontalHeaderItem(column).textAlignment() & Qt.AlignRight for column in range(1, 3))
    assert [window.balance_table.horizontalHeaderItem(column).text() for column in range(3)] == [
        "Category",
        "Balance",
        "Use or Lose",
    ]
    assert window.balance_table.item(0, 0).textAlignment() & Qt.AlignLeft
    assert all(window.balance_table.item(0, column).textAlignment() & Qt.AlignRight for column in range(1, 3))
