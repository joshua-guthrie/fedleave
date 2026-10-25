"""Calendar labels, usage-only FMLA input and same-day grant/use editing."""

from fedleave_gui.main_window import (
    CATEGORY_LABELS,
    DayEditDialog,
    ExpirationStatusDialog,
    ForceBalanceDialog,
    _day_values_by_category,
)


def test_full_names_and_usage_only_controls(qtbot):
    assert CATEGORY_LABELS["ppl"] == ("PPL", "Paid Parental Leave (PPL)")
    assert CATEGORY_LABELS["fmla"] == ("FMLA", "Family and Medical Leave Act (FMLA)")
    dialog = DayEditDialog({"date": "2026-10-01", "entries": []})
    qtbot.addWidget(dialog)
    for category in ("ppl", "fmla"):
        index = dialog.add_category.findData(category)
        assert index >= 0
        assert dialog.add_category.itemText(index) == CATEGORY_LABELS[category][1]
        dialog.add_category.setCurrentIndex(index)
        dialog._add_selected_category()
    assert dialog.directions["fmla"].count() == 1
    assert dialog.directions["fmla"].currentData() == "use"
    assert dialog.inputs["ppl"].maximum() >= 480
    dialog.directions["ppl"].setCurrentIndex(1)
    assert dialog.inputs["ppl"].value() == 480
    dialog.inputs["ppl"].setValue(360)
    dialog.directions["ppl"].setCurrentIndex(0)
    dialog.directions["ppl"].setCurrentIndex(1)
    assert dialog.inputs["ppl"].value() == 360
    dialog.inputs["fmla"].setValue(8)
    assert dialog.values()["ppl"] == 360
    assert dialog.values()["fmla"] == -8


def test_same_date_grant_and_usage_edits_show_usage_not_net_entitlement(qtbot):
    day = {
        "date": "2026-10-01",
        "entries": [
            {"category": "ppl", "direction": "earned", "hours": 480},
            {"category": "ppl", "direction": "used", "hours": 8},
        ],
    }
    assert _day_values_by_category(day)["ppl"] == -8
    dialog = DayEditDialog(day)
    qtbot.addWidget(dialog)
    assert dialog.inputs["ppl"].value() == 8
    assert dialog.directions["ppl"].currentData() == "use"


def test_existing_earned_amount_is_preserved_and_force_shortcut_excludes_trackers(qtbot):
    dialog = DayEditDialog(
        {"date": "2026-10-01", "entries": [{"category": "ppl", "direction": "earned", "hours": 360}]}
    )
    qtbot.addWidget(dialog)
    assert dialog.inputs["ppl"].value() == 360
    forced = ForceBalanceDialog()
    qtbot.addWidget(forced)
    assert forced.category_input.findData("ppl") == -1
    assert forced.category_input.findData("fmla") == -1


def test_expiration_dialog_shows_source_window_schedule_and_loss(qtbot):
    from PySide6.QtWidgets import QLabel

    payload = {
        "as_of": "2026-10-01",
        "lots": [],
        "parental": {
            "ppl_windows": [
                {
                    "transaction_id": "grant",
                    "source_leave_year": 2026,
                    "last_eligible_usage_date": "2027-08-31",
                    "expiration_effective_date": "2027-09-01",
                    "scheduled_used_hours": 80,
                    "protected_scheduled_hours": 80,
                    "potential_unused_loss_hours": 280,
                    "expired_unused_hours": 0,
                }
            ]
        },
    }
    dialog = ExpirationStatusDialog(payload, [1, 3])
    qtbot.addWidget(dialog)
    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    for expected in ("2026 / grant", "2027-08-31", "2027-09-01", "Scheduled 80.00", "loss 280.00"):
        assert expected in text
