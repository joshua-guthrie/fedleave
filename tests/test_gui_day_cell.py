import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSizePolicy

from fedleave_gui.main_window import DayCell
from fedleave_gui.settings import GuiSettings


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_day_number_is_in_upper_right_and_details_remain_left_aligned():
    _application()
    day = {
        "date": "2026-07-08",
        "in_display_month": True,
        "entries": [{"category": "annual", "hours": 4, "direction": "used"}],
        "is_payday": True,
    }

    cell = DayCell(day, GuiSettings())

    assert cell.day_label.text() == "8"
    assert cell.day_label.alignment() & Qt.AlignRight
    assert cell.day_label.alignment() & Qt.AlignTop
    assert cell.details_label.alignment() & Qt.AlignLeft
    assert cell.details_label.alignment() & Qt.AlignTop
    assert cell.details_label.text() == "A        -4\nPay day"
    assert cell.display_text() == "8\nA        -4\nPay day"
    assert cell.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert cell.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
