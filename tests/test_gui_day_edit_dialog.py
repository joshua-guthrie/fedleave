import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fedleave_gui.main_window import DayEditDialog, MainWindow, SaveDayPreviewDialog


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_existing_values_use_explicit_direction_and_positive_hours():
    _application()
    dialog = DayEditDialog(
        {
            "date": "2026-07-08",
            "entries": [
                {"category": "annual", "hours": 4, "direction": "used", "description": "Appointment"},
                {"category": "credit", "hours": 2, "direction": "earned", "description": "Stayed late"},
            ],
        }
    )

    assert dialog.inputs["annual"].minimum() == 0
    assert dialog.inputs["annual"].value() == 4
    assert dialog.directions["annual"].currentData() == "use"
    assert dialog.comment_inputs["annual"].text() == "Appointment"
    assert dialog.inputs["credit"].value() == 2
    assert dialog.directions["credit"].currentData() == "earn"
    assert dialog.comment_inputs["credit"].text() == "Stayed late"
    assert dialog.values() == {"annual": -4.0, "credit": 2.0}


def test_new_leave_type_defaults_to_use_and_never_accepts_negative_hours():
    _application()
    dialog = DayEditDialog({"date": "2026-07-08", "entries": []})
    annual_index = dialog.add_category.findData("annual")
    dialog.add_category.setCurrentIndex(annual_index)

    dialog._add_selected_category()

    assert dialog.directions["annual"].currentData() == "use"
    assert dialog.inputs["annual"].minimum() == 0
    assert dialog.comment_inputs["annual"].text() == ""
    dialog.inputs["annual"].setValue(-3)
    assert dialog.inputs["annual"].value() == 0
    dialog.inputs["annual"].setValue(3)
    assert dialog.values()["annual"] == -3.0

    dialog.directions["annual"].setCurrentIndex(dialog.directions["annual"].findData("earn"))
    assert dialog.values()["annual"] == 3.0


def test_day_edit_dialog_returns_comments_for_existing_and_new_rows():
    _application()
    dialog = DayEditDialog(
        {
            "date": "2026-07-08",
            "entries": [{"category": "annual", "hours": 4, "direction": "used", "description": "Appointment"}],
        }
    )
    credit_index = dialog.add_category.findData("credit")
    dialog.add_category.setCurrentIndex(credit_index)
    dialog._add_selected_category()

    dialog.comment_inputs["annual"].setText("Updated appointment")
    dialog.comment_inputs["credit"].setText("Late night")

    assert dialog.comments() == {"annual": "Updated appointment", "credit": "Late night"}


def test_save_day_preview_dialog_lists_existing_and_new_values_without_signs():
    _application()
    dialog = SaveDayPreviewDialog(
        {"date": "2026-07-08"},
        {"annual": -4.0, "credit": 2.0},
        {"annual": 5.0, "credit": 0.0, "sick": -1.5},
    )

    assert dialog.windowTitle() == "Review Save for 2026-07-08"
    assert dialog.table.rowCount() == 3
    assert dialog.table.horizontalHeaderItem(0).textAlignment() & Qt.AlignLeft
    assert all(dialog.table.horizontalHeaderItem(column).textAlignment() & Qt.AlignRight for column in range(1, 3))
    assert [
        dialog.table.item(0, 0).text(),
        dialog.table.item(0, 1).text().strip(),
        dialog.table.item(0, 2).text().strip(),
    ] == ["Annual Leave", "4 used", "5 earned"]
    assert dialog.table.item(0, 0).textAlignment() & Qt.AlignLeft
    assert all(dialog.table.item(0, column).textAlignment() & Qt.AlignRight for column in range(1, 3))
    assert [
        dialog.table.item(1, 0).text(),
        dialog.table.item(1, 1).text().strip(),
        dialog.table.item(1, 2).text().strip(),
    ] == ["Credit Hours", "2 earned", "0"]
    assert [
        dialog.table.item(2, 0).text(),
        dialog.table.item(2, 1).text().strip(),
        dialog.table.item(2, 2).text().strip(),
    ] == ["Sick Leave", "0", "1.5 used"]


def test_edit_day_requires_preview_confirmation(monkeypatch):
    _application()

    class FakeBackend:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, float], dict[str, str] | None]] = []

        def set_day(self, day: str, values: dict[str, float], comments: dict[str, str] | None = None) -> None:
            self.calls.append((day, values, comments))

    fake_backend = FakeBackend()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: fake_backend)
    window = MainWindow()

    class FakeEditDialog:
        def __init__(self, day, parent=None):
            self._values = {"annual": -3.0}
            self._comments = {"annual": "Doctor visit"}

        def exec(self):
            return 1

        def values(self):
            return self._values

        def comments(self):
            return self._comments

    class FakePreviewDialog:
        def __init__(self, day, existing_values, new_values, parent=None):
            self.day = day
            self.existing_values = existing_values
            self.new_values = new_values

        def exec(self):
            return 0

    monkeypatch.setattr("fedleave_gui.main_window.DayEditDialog", FakeEditDialog)
    monkeypatch.setattr("fedleave_gui.main_window.SaveDayPreviewDialog", FakePreviewDialog)

    window.edit_day({"date": "2026-07-08", "entries": [{"category": "annual", "direction": "used", "hours": 2.0}]})

    assert fake_backend.calls == []

    class AcceptedPreviewDialog(FakePreviewDialog):
        def exec(self):
            return 1

    monkeypatch.setattr("fedleave_gui.main_window.SaveDayPreviewDialog", AcceptedPreviewDialog)

    window.edit_day({"date": "2026-07-08", "entries": [{"category": "annual", "direction": "used", "hours": 2.0}]})

    assert fake_backend.calls == [("2026-07-08", {"annual": -3.0}, {"annual": "Doctor visit"})]
