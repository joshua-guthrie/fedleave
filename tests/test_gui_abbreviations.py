import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QTableWidget

from fedleave_gui.main_window import CATEGORY_LABELS, AbbreviationsDialog


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_abbreviations_dialog_uses_complete_noneditable_table():
    _application()
    dialog = AbbreviationsDialog()
    table = dialog.table

    assert isinstance(table, QTableWidget)
    assert table.rowCount() == len(CATEGORY_LABELS)
    assert table.columnCount() == 2
    assert table.horizontalHeaderItem(0).text() == "Abbreviation"
    assert table.horizontalHeaderItem(1).text() == "Leave Type"
    assert table.horizontalHeaderItem(0).textAlignment() & Qt.AlignLeft
    assert table.horizontalHeaderItem(1).textAlignment() & Qt.AlignLeft
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeToContents
    assert table.horizontalHeader().sectionResizeMode(1) == QHeaderView.Stretch

    expected = list(CATEGORY_LABELS.values())
    actual = [(table.item(row, 0).text(), table.item(row, 1).text()) for row in range(table.rowCount())]
    assert actual == expected
    assert all(
        table.item(row, column).textAlignment() & Qt.AlignLeft for row in range(table.rowCount()) for column in range(2)
    )
    assert all(
        not (table.item(row, column).flags() & Qt.ItemIsEditable)
        for row in range(table.rowCount())
        for column in range(2)
    )
