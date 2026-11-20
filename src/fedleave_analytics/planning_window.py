"""Standalone window for the read-only What-if Planner."""

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

from .help_view import AnalyticsHelpDialog
from .planning_view import PlannerWidget

TOOL = "what-if"
TITLE = "What-if Planner"
NOTICE = (
    "What-if Planner: compare a session-only scenario with the unchanged scheduled baseline. "
    "Closing this window discards the draft."
)


class PlanningWindow(QMainWindow):
    """Host the read-only What-if Planner."""

    def __init__(
        self,
        tool: str,
        backend: Path,
        data_dir: str | None,
        year: int,
        font_size: int = 10,
    ) -> None:
        super().__init__()
        if tool != TOOL:
            raise ValueError(f"Unsupported planning tool: {tool!r}.")
        self.tool = tool
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.font_size = font_size
        self._closing = False

        self.help_section_name = TOOL
        self.setWindowTitle(f"FedLeave {TITLE}")
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
        self.open_chart_button.setToolTip("Open the chart and its daily closing balances.")
        self.open_chart_button.clicked.connect(self.open_chart)
        controls.addWidget(self.open_chart_button)
        controls.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setToolTip("Close this window and discard the draft.")
        self.close_button.clicked.connect(self.close)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)

        self.notice_label = QLabel(NOTICE)
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)

        self.widget = PlannerWidget(self.backend, self.data_dir, self.year, parent=self)
        self.widget.source_loaded.connect(self._source_loaded)
        layout.addWidget(self.widget, 1)
        self.setCentralWidget(root)

        file_menu = self.menuBar().addMenu("File")
        for label, callback in (
            ("Refresh", self.refresh_data),
            ("Open Chart", self.open_chart),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        self.help_action = QAction("Help...", self)
        self.help_action.setShortcut("F1")
        self.help_action.setToolTip("Open detailed offline instructions for the What-if Planner.")
        self.help_action.triggered.connect(self.show_help)
        file_menu.addAction(self.help_action)
        file_menu.addSeparator()
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

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

    def closeEvent(self, event) -> None:
        self._closing = True
        self.widget.shutdown()
        super().closeEvent(event)
