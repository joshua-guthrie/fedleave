import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
                {"category": "annual", "hours": 4, "direction": "used"},
                {"category": "credit", "hours": 2, "direction": "earned"},
            ],
        }
    )

    assert dialog.inputs["annual"].minimum() == 0
    assert dialog.inputs["annual"].value() == 4
    assert dialog.directions["annual"].currentData() == "use"
    assert dialog.inputs["credit"].value() == 2
    assert dialog.directions["credit"].currentData() == "earn"
    assert dialog.values() == {"annual": -4.0, "credit": 2.0}


def test_new_leave_type_defaults_to_use_and_never_accepts_negative_hours():
    _application()
    dialog = DayEditDialog({"date": "2026-07-08", "entries": []})
    annual_index = dialog.add_category.findData("annual")
    dialog.add_category.setCurrentIndex(annual_index)

    dialog._add_selected_category()

    assert dialog.directions["annual"].currentData() == "use"
    assert dialog.inputs["annual"].minimum() == 0
    dialog.inputs["annual"].setValue(-3)
    assert dialog.inputs["annual"].value() == 0
    dialog.inputs["annual"].setValue(3)
    assert dialog.values()["annual"] == -3.0

    dialog.directions["annual"].setCurrentIndex(dialog.directions["annual"].findData("earn"))
    assert dialog.values()["annual"] == 3.0


def test_save_day_preview_dialog_lists_existing_and_new_values_without_signs():
    _application()
    dialog = SaveDayPreviewDialog(
        {"date": "2026-07-08"},
        {"annual": -4.0, "credit": 2.0},
        {"annual": 5.0, "credit": 0.0, "sick": -1.5},
    )

    assert dialog.windowTitle() == "Review Save for 2026-07-08"
    assert dialog.table.rowCount() == 3
    assert [dialog.table.item(0, column).text() for column in range(3)] == ["Annual Leave", "4 used", "5 earned"]
    assert [dialog.table.item(1, column).text() for column in range(3)] == ["Credit Hours", "2 earned", "0"]
    assert [dialog.table.item(2, column).text() for column in range(3)] == ["Sick Leave", "0", "1.5 used"]


def test_edit_day_requires_preview_confirmation(monkeypatch):
    _application()

    class FakeBackend:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, float]]] = []

        def set_day(self, day: str, values: dict[str, float]) -> None:
            self.calls.append((day, values))

    fake_backend = FakeBackend()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    monkeypatch.setattr(MainWindow, "_backend", lambda self: fake_backend)
    window = MainWindow()

    class FakeEditDialog:
        def __init__(self, day, parent=None):
            self._values = {"annual": -3.0}

        def exec(self):
            return 1

        def values(self):
            return self._values

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

    assert fake_backend.calls == [("2026-07-08", {"annual": -3.0})]
