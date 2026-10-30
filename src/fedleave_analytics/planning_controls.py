"""Data-only dialogs for choosing scenario dates and existing scheduled use."""

from copy import deepcopy

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QCalendarWidget, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .charts import table_widget


class ScenarioDateDialog(QDialog):
    def __init__(self, current, minimum, maximum, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose tentative use date")
        layout = QVBoxLayout(self)
        caption = QLabel(
            f"Choose a date after cutoff through horizon: {minimum.toString('yyyy-MM-dd')} to {maximum.toString('yyyy-MM-dd')}. Review working capacity after choosing."
        )
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.calendar = QCalendarWidget()
        self.calendar.setDateRange(minimum, maximum)
        selected = QDate.fromString(current, "yyyy-MM-dd")
        self.calendar.setSelectedDate(min(max(selected, minimum), maximum) if selected.isValid() else minimum)
        layout.addWidget(self.calendar)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Use date")
        buttons.button(QDialogButtonBox.Ok).setToolTip("Use the highlighted date for this tentative entry.")
        buttons.button(QDialogButtonBox.Cancel).setToolTip("Keep the original date unchanged.")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.calendar.clicked.connect(self.accept)
        self.calendar.activated.connect(self.accept)
        layout.addWidget(buttons)
        self.calendar.setFocus()

    def selected_date(self):
        return self.calendar.selectedDate().toString("yyyy-MM-dd")


class ScheduledUseDialog(QDialog):
    def __init__(self, transactions, operation, *, selected_ids=(), targeted_ids=(), parent=None):
        super().__init__(parent)
        self.transactions = deepcopy(transactions)
        self.setWindowTitle("Choose scheduled leave to " + operation)
        self.resize(1000, 490)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Check one or more existing bookings. Replace combines them into one editable tentative entry; the originals remain in the baseline."
            if operation == "replace"
            else "Check one or more existing bookings to omit from this scenario. The originals remain in the baseline and ledger."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        rows = [
            dict(
                tx,
                unavailable="Already used by a scenario change; undo or edit that change first."
                if str(tx["id"]) in targeted_ids
                else "",
            )
            for tx in self.transactions
        ]
        self.table = table_widget(
            rows,
            [
                ("choose", "Choose"),
                ("date", "Date"),
                ("category", "Category"),
                ("hours", "Hours"),
                ("status", "Status"),
                ("description", "Note"),
                ("id", "Original ID"),
                ("unavailable", "Availability"),
            ],
        )
        self.table.setSortingEnabled(False)
        for index, tx in enumerate(self.transactions):
            item = self.table.item(index, 0)
            item.setText("")
            flags = Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            available = str(tx["id"]) not in targeted_ids
            item.setFlags(flags | Qt.ItemIsEnabled if available else flags)
            item.setCheckState(Qt.Checked if available and str(tx["id"]) in selected_ids else Qt.Unchecked)
            item.setToolTip("Include this booking in the scenario change." if available else rows[index]["unavailable"])
        self.table.setSortingEnabled(True)
        for column, width in enumerate((60, 105, 130, 65, 90, 180, 135, 250)):
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 1)
        self.notice = QLabel(
            "No existing scheduled leave in this cutoff/horizon. Use Add tentative use for extra leave."
            if not rows
            else "Only effective future absence rows are listed. Check boxes to choose; Cancel makes no change."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.confirm_button = self.buttons.button(QDialogButtonBox.Ok)
        self.confirm_button.setText(
            "Replace checked bookings" if operation == "replace" else "Remove checked bookings from scenario"
        )
        self.confirm_button.setToolTip("Create one draft change from the checked bookings; never edit the ledger.")
        self.buttons.button(QDialogButtonBox.Cancel).setToolTip("Close without adding a scenario change.")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.table.itemChanged.connect(self._selection_changed)
        layout.addWidget(self.buttons)
        self._selection_changed()

    def selected_transactions(self):
        rows = []
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 0)
            if item.flags() & Qt.ItemIsEnabled and item.checkState() == Qt.Checked:
                rows.append(self.transactions[item.data(Qt.UserRole + 1)])
        return sorted(deepcopy(rows), key=lambda row: (row["date"], str(row["id"])))

    def _selection_changed(self, *_args):
        self.confirm_button.setEnabled(bool(self.selected_transactions()))
