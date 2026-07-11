import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fedleave_gui.main_window import DayEditDialog


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
