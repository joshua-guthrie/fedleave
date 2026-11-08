"""Dialog for choosing a tentative scenario date."""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCalendarWidget, QDialog, QDialogButtonBox, QLabel, QVBoxLayout


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
