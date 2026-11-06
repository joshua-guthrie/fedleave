"""Standalone single-tool windows for the read-only Planning tools.

Each Planning tool (What-if Planner, Usage Forecast, Leave Budget, Holiday and
Weekend Planner) gets its own window, independent of the Analytics window.
Budget and Holiday results can hand off to a fresh What-if window in-process.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .budget_view import BudgetWidget
from .forecast_view import ForecastWidget
from .help_view import AnalyticsHelpDialog
from .holiday_view import HolidayWidget
from .planning_view import PlannerWidget

TOOLS = {
    "what-if": ("What-if Planner", "what-if"),
    "forecast": ("Usage Forecast", "forecast"),
    "budget": ("Leave Budget", "budget"),
    "holidays": ("Holiday and Weekend Planner", "holidays"),
}

NOTICES = {
    "what-if": "What-if Planner: compare a session-only scenario with the unchanged scheduled baseline. Leave records are never modified.",
    "forecast": "Usage Forecast: Scheduled, Typical Usage and Higher Usage are historical planning scenarios. Confirm historical coverage and review allocation completeness.",
    "budget": "Leave Budget: deadline-first planning suggestions, explicit purpose eligibility, shared work capacity and before/after risk. Leave records are never modified.",
    "holidays": "Holiday and Weekend Planner: independent break options funded from eligible discretionary banks; no leave is booked.",
}


class PlanningWindow(QMainWindow):
    """Host one read-only Planning tool with shared year/refresh/export controls."""

    def __init__(
        self,
        tool: str,
        backend: Path,
        data_dir: str | None,
        year: int,
        font_size: int = 10,
        pdf_folder: str = "",
    ) -> None:
        super().__init__()
        if tool not in TOOLS:
            raise ValueError(f"Unsupported planning tool: {tool!r}.")
        self.tool = tool
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder = pdf_folder
        self.font_size = font_size
        self._child_windows: list[PlanningWindow] = []
        self._closing = False

        title, self.help_section_name = TOOLS[tool]
        self.setWindowTitle(f"FedLeave {title}")
        self.resize(1320, 860)
        font = self.font()
        font.setPointSize(font_size)
        self.setFont(font)
        self._build_ui()
        self.widget.activate()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Leave Year"))
        self.year_combo = QComboBox()
        self.year_combo.addItem(str(self.year), self.year)
        self.year_combo.currentIndexChanged.connect(self._year_changed)
        controls.addWidget(self.year_combo)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Read current records again from the selected backend and datastore.")
        self.refresh_button.clicked.connect(self.refresh_data)
        controls.addWidget(self.refresh_button)
        self.open_chart_button = QPushButton("Open Chart")
        self.open_chart_button.setToolTip("Open the chart with exact data and PNG, PDF, Print and CSV exports.")
        self.open_chart_button.clicked.connect(self.open_chart)
        controls.addWidget(self.open_chart_button)
        self.csv_button = QPushButton("Save Table as CSV...")
        self.csv_button.setToolTip("Export the current result table outside the leave datastore.")
        self.csv_button.clicked.connect(self.save_csv)
        controls.addWidget(self.csv_button)
        controls.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setToolTip("Close this planning window. Export any scenario you want to keep.")
        self.close_button.clicked.connect(self.close)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)

        self.notice_label = QLabel(NOTICES[self.tool])
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)

        self._build_tool()
        layout.addWidget(self.widget, 1)
        self.setCentralWidget(root)

        file_menu = self.menuBar().addMenu("File")
        for label, callback in (
            ("Refresh", self.refresh_data),
            ("Open Chart", self.open_chart),
            ("Save Table as CSV...", self.save_csv),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        self.help_action = QAction("Help...", self)
        self.help_action.setShortcut("F1")
        self.help_action.setToolTip("Open detailed offline instructions for this planning tool.")
        self.help_action.triggered.connect(self.show_help)
        file_menu.addAction(self.help_action)
        file_menu.addSeparator()
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

    def _build_tool(self) -> None:
        if self.tool == "what-if":
            self.widget = PlannerWidget(self.backend, self.data_dir, self.year, self.pdf_folder, parent=self)
        elif self.tool == "forecast":
            self.widget = ForecastWidget(self.backend, self.data_dir, self.year, self.pdf_folder, parent=self)
        elif self.tool == "budget":
            self.widget = BudgetWidget(self.backend, self.data_dir, self.year, self.pdf_folder, parent=self)
            self.widget.transfer_ready.connect(self._transfer_budget)
        else:
            self.widget = HolidayWidget(self.backend, self.data_dir, self.year, self.pdf_folder, parent=self)
            self.widget.transfer_ready.connect(self._transfer_holiday)
        self.widget.source_loaded.connect(self._source_loaded)

    def show_help(self):
        dialog = AnalyticsHelpDialog(self.help_section_name, self)
        dialog.exec()
        dialog.deleteLater()

    @Slot(object)
    def _source_loaded(self, snapshot) -> None:
        available = snapshot.get("planning_available_years", [self.year])
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        for year in sorted(set(available)):
            self.year_combo.addItem(str(year), year)
        self.year_combo.setCurrentIndex(max(0, self.year_combo.findData(self.year)))
        self.year_combo.blockSignals(False)

    def _year_changed(self) -> None:
        selected = self.year_combo.currentData()
        if selected is None or int(selected) == self.year:
            return
        self.year = int(selected)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.widget.set_source(self.backend, self.data_dir, self.year)
        self.widget.load_source()

    def open_chart(self) -> None:
        self.widget.open_chart()

    def save_csv(self) -> None:
        self.widget.save_csv()

    def _open_what_if(self) -> PlanningWindow:
        window = PlanningWindow("what-if", self.backend, self.data_dir, self.year, self.font_size, self.pdf_folder)
        self._child_windows.append(window)
        window.destroyed.connect(lambda: self._child_windows.remove(window) if window in self._child_windows else None)
        window.show()
        return window

    @Slot(object, object)
    def _transfer_budget(self, snapshot, result):
        self._open_what_if().widget.accept_budget(snapshot, result)

    @Slot(object, object)
    def _transfer_holiday(self, snapshot, option):
        self._open_what_if().widget.accept_option(snapshot, option, label="Holiday and Weekend Planner")

    def closeEvent(self, event) -> None:
        self._closing = True
        for window in list(self._child_windows):
            window.close()
        self.widget.shutdown()
        super().closeEvent(event)
