import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fedleave_gui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeBackend:
    def list_transactions(self, year: int):
        if year == 2026:
            return [
                {
                    "id": "20260102-001",
                    "date": "2026-01-02",
                    "category": "annual",
                    "direction": "used",
                    "hours": 4.0,
                    "status": "planned",
                    "source": "manual",
                    "description": "Appointment",
                },
                {
                    "id": "20260105-001",
                    "date": "2026-01-05",
                    "category": "annual",
                    "direction": "used",
                    "hours": 0.0,
                    "status": "planned",
                    "source": "manual",
                    "description": "Zero row",
                },
            ]
        if year == 2027:
            return [
                {
                    "id": "20270103-001",
                    "date": "2027-01-03",
                    "category": "sick",
                    "direction": "used",
                    "hours": 8.0,
                    "status": "reconciled",
                    "source": "clocking-report",
                    "description": "Out sick",
                }
            ]
        return []


def test_transactions_in_range_filters_dates_and_zero_rows(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr("fedleave_gui.main_window._available_leave_years", lambda _data_dir: [2026, 2027])
    window = MainWindow()
    window.backend = _FakeBackend()

    rows = window._transactions_in_range(date(2026, 1, 1), date(2026, 1, 31))

    assert len(rows) == 1
    assert rows[0]["id"] == "20260102-001"
    assert rows[0]["date"] == "2026-01-02"
    assert rows[0]["hours"] == 4.0


def test_transactions_in_range_sorts_by_date_and_id(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr("fedleave_gui.main_window._available_leave_years", lambda _data_dir: [2026])
    window = MainWindow()

    class _OrderingBackend:
        def list_transactions(self, year: int):
            return [
                {"id": "20260103-002", "date": "2026-01-03", "hours": 2.0},
                {"id": "20260103-001", "date": "2026-01-03", "hours": 1.0},
                {"id": "20260102-001", "date": "2026-01-02", "hours": 3.0},
            ]

    window.backend = _OrderingBackend()

    rows = window._transactions_in_range(date(2026, 1, 1), date(2026, 1, 31))

    assert [row["id"] for row in rows] == ["20260102-001", "20260103-001", "20260103-002"]
