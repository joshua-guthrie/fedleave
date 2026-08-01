import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox

from fedleave_gui.main_window import MainWindow, _pay_period_rows


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _period(number: int, *, touches: bool = True) -> dict:
    return {
        "number": number,
        "start": "2026-06-28",
        "end": "2026-07-11",
        "pay_date": "2026-07-17",
        "touches_display_month": touches,
        "totals": {
            "annual": {"earned": 6.0, "used": 2.0, "worked": 0.0, "net": 4.0},
            "credit": {"earned": 0.0, "used": 0.0, "worked": 0.0, "net": 0.0},
        },
        "ending_balances": {"annual": 14.0, "sick": 20.0, "credit": 0.0},
    }


def test_pay_period_rows_match_month_report_layout():
    assert _pay_period_rows(_period(14)) == [
        ["Annual Leave", "6", "2", "14"],
        ["Sick Leave", "", "", "20"],
    ]


def test_gui_renders_separate_table_for_each_visible_pay_period(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    window.month_json = {"pay_periods": [_period(14), _period(15), _period(13, touches=False)]}

    window._render_pay_periods()

    assert len(window.pay_period_tables) == 2
    groups = window.pay_period_widget.findChildren(QGroupBox)
    assert [group.title() for group in groups] == [
        "PP 14: 2026-06-28 to 2026-07-11",
        "PP 15: 2026-06-28 to 2026-07-11",
    ]
    table = window.pay_period_tables[0]
    assert [table.horizontalHeaderItem(column).text() for column in range(4)] == [
        "Type",
        "Earned",
        "Used",
        "Balance",
    ]
    assert table.horizontalHeaderItem(0).textAlignment() & Qt.AlignLeft
    assert all(table.horizontalHeaderItem(column).textAlignment() & Qt.AlignRight for column in range(1, 4))
    assert table.rowCount() == 2
    assert [table.item(0, column).text() for column in range(4)] == ["Annual Leave", "6", "2", "14"]
    assert table.item(0, 0).textAlignment() & Qt.AlignLeft
    assert all(table.item(0, column).textAlignment() & Qt.AlignRight for column in range(1, 4))


def test_section_headings_are_bold(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    assert window.pay_periods_label.font().bold() is True
    assert window.as_of_today_label.font().bold() is True
