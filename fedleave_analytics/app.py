from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fedleave.config import get_default_data_dir

from .analytics import analyze_leave_year
from .charts import (
    AnalyticsChartWindow,
    render_bar_chart,
    render_heatmap,
    render_horizontal_bar_chart,
    table_widget,
)


SUMMARY_COLUMNS = [
    ("metric", "Metric"), ("value", "Value"), ("units", "Units"),
    ("period_or_date", "Period or Date"), ("basis", "Basis"),
]
TIME_COLUMNS = [
    ("through_today", "Through Today"), ("future_scheduled", "Future Scheduled"),
    ("full_leave_year", "Full Leave Year"),
]
MONTH_COLUMNS = [("month", "Month"), *TIME_COLUMNS]
WEEKDAY_COLUMNS = [("weekday", "Weekday"), *TIME_COLUMNS]
PAY_PERIOD_COLUMNS = [
    ("pay_period", "Pay Period"), ("start_date", "Start Date"), ("end_date", "End Date"), *TIME_COLUMNS,
]
HEATMAP_COLUMNS = [
    ("date", "Date"), ("weekday", "Weekday"), ("through_today", "Through Today"),
    ("future_scheduled", "Future Scheduled"), ("full_day_total", "Full-Day Total"),
    ("categories", "Categories"),
]
NET_COLUMNS = [
    ("month", "Month"), ("earned_or_added", "Earned or Added"), ("used", "Used"),
    ("paid_out", "Paid Out"), ("forfeited", "Forfeited"), ("expired", "Expired"),
    ("net_change", "Net Change"),
]
FINAL_COLUMNS = [
    ("period", "Period"), ("start_date", "Start Date"), ("end_date", "End Date"),
    ("leave_hours", "Leave Hours"), ("percentage", "Percentage"),
]
LIFECYCLE_COLUMNS = [("metric", "Metric"), *TIME_COLUMNS, ("units", "Units")]
LOT_COLUMNS = [
    ("earned_date", "Earned Date"), ("original", "Original"), ("used", "Used"),
    ("paid_out", "Paid Out"), ("forfeited", "Forfeited"), ("expired", "Expired"),
    ("remaining_today", "Remaining Today"), ("projected_remaining", "Projected Remaining"),
    ("expiration", "Expiration"), ("age", "Age"), ("status", "Status"),
    ("description", "Description"), ("source", "Source"),
]
ALLOCATION_COLUMNS = [
    ("event_date", "Event Date"), ("event_type", "Event Type"), ("hours", "Hours"),
    ("earned_lot_date", "Earned Lot Date"), ("expiration_date", "Expiration Date"),
    ("allocation_method", "Allocation Method"), ("transaction_id", "Transaction ID"),
]
MATURED_COLUMNS = [
    ("matured_lots", "Matured Lots"), ("earned_hours", "Earned Hours"),
    ("used_before_expiration", "Used Before Expiration"), ("paid_out", "Paid Out"),
    ("forfeited", "Forfeited"), ("expired", "Expired"),
    ("percentage_consumed", "Percentage Consumed"),
]
OVERTIME_COMP_COLUMNS = [
    ("month", "Month"), ("overtime_worked", "Overtime Worked"),
    ("comp_earned", "Comp Earned"), ("credit_earned", "Credit Earned or Worked"),
    ("combined_additional_work", "Combined Additional Work"),
]
COMP_MONTH_COLUMNS = [
    ("month", "Month"), ("earned", "Comp Earned"), ("used", "Comp Used"),
    ("paid_out", "Comp Paid Out"), ("forfeited", "Comp Forfeited"), ("expired", "Comp Expired"),
]
CREDIT_MONTH_COLUMNS = [
    ("month", "Month"), ("earned", "Credit Earned"), ("worked", "Credit Worked"),
    ("used", "Credit Used"), ("forfeited", "Credit Forfeited"), ("expired", "Credit Expired"),
]
WARNING_COLUMNS = [
    ("severity", "Severity"), ("area", "Area"), ("date_or_lot", "Date or Lot"), ("message", "Message"),
]
TRANSACTION_COLUMNS = [
    ("date", "Date"), ("category", "Category"), ("direction", "Direction"),
    ("hours", "Hours"), ("status", "Status"), ("timing", "Timing"),
    ("description", "Description"), ("source", "Source"),
    ("transaction_id", "Transaction ID"), ("earned_transaction_id", "Earned Transaction ID"),
]


SEASONALITY_VIEWS: dict[str, tuple[str, list[tuple[str, str]], str, list[tuple[str, str]]]] = {
    "Leave Used by Month": ("months", MONTH_COLUMNS, "month", [
        ("through_today", "Through Today"), ("future_scheduled", "Future Scheduled"),
    ]),
    "Leave Used by Day of Week": ("weekdays", WEEKDAY_COLUMNS, "weekday", [
        ("through_today", "Through Today"), ("future_scheduled", "Future Scheduled"),
    ]),
    "Leave Used by Pay Period": ("pay_periods", PAY_PERIOD_COLUMNS, "pay_period", [
        ("through_today", "Through Today"), ("future_scheduled", "Future Scheduled"),
    ]),
    "Overtime Worked by Month": ("overtime_months", MONTH_COLUMNS, "month", [
        ("through_today", "Through Today"), ("future_scheduled", "Future Scheduled"),
    ]),
    "Net Leave Accumulation by Month": ("net_accumulation", NET_COLUMNS, "month", [
        ("earned_or_added", "Earned or Added"), ("used", "Used"), ("net_change", "Net Change"),
    ]),
    "Final-Quarter Leave Concentration": ("final_quarter.rows", FINAL_COLUMNS, "period", [
        ("leave_hours", "Leave Hours"),
    ]),
}


def _payload_value(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        value = value[part]
    return value


def load_analytics_data(backend: Path, data_dir: str | None, year: int) -> dict[str, Any]:
    command = [str(backend), "list", "--year", str(year), "--json"]
    if data_dir:
        command.extend(["--data-dir", data_dir])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "fedleave command failed").strip())
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The fedleave backend returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("The fedleave backend returned an unsupported JSON payload.")
    return analyze_leave_year(payload)


class AnalyticsLoader(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, backend: Path, data_dir: str | None, year: int) -> None:
        super().__init__()
        self.backend = backend
        self.data_dir = data_dir
        self.year = year

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(load_analytics_data(self.backend, self.data_dir, self.year))
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            self.failed.emit(str(exc))


class TransactionDialog(QDialog):
    def __init__(self, rows: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Supporting Transactions")
        self.resize(1100, 560)
        layout = QVBoxLayout(self)
        heading = QLabel(f"{len(rows)} transaction(s); total {_format_number(sum(float(row.get('hours') or 0) for row in rows))} hours")
        layout.addWidget(heading)
        layout.addWidget(table_widget(rows, TRANSACTION_COLUMNS), 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignRight)


def _format_number(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


class AnalyticsWindow(QMainWindow):
    def __init__(
        self,
        backend: Path,
        data_dir: str | None,
        year: int,
        font_size: int = 10,
        pdf_folder: str = "",
        auto_load: bool = True,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.data_dir = data_dir
        self.year = year
        self.pdf_folder = pdf_folder
        self.data: dict[str, Any] | None = None
        self._load_thread: QThread | None = None
        self._loader: AnalyticsLoader | None = None
        self._chart_windows: list[AnalyticsChartWindow] = []
        self._current_table: QTableWidget | None = None
        self._current_rows: list[dict[str, Any]] = []
        self._current_columns: list[tuple[str, str]] = []

        self.setWindowTitle("FedLeave Analytics")
        self.resize(1320, 860)
        font = self.font()
        font.setPointSize(font_size)
        self.setFont(font)
        self._build_ui()
        if auto_load:
            self.refresh_data()

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
        self.refresh_button.clicked.connect(self.refresh_data)
        controls.addWidget(self.refresh_button)
        self.open_chart_button = QPushButton("Open Chart")
        self.open_chart_button.clicked.connect(self.open_chart)
        controls.addWidget(self.open_chart_button)
        self.csv_button = QPushButton("Save Table as CSV...")
        self.csv_button.clicked.connect(self.save_csv)
        controls.addWidget(self.csv_button)
        controls.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)

        self.notice_label = QLabel("No data loaded yet.")
        self.notice_label.setWordWrap(True)
        layout.addWidget(self.notice_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.pages = QTabWidget()
        self.summary_page = QWidget()
        self.seasonality_page = QWidget()
        self.heatmap_page = QWidget()
        self.lifecycle_page = QWidget()
        self.pages.addTab(self.summary_page, "Summary")
        self.pages.addTab(self.seasonality_page, "Seasonality")
        self.pages.addTab(self.heatmap_page, "Calendar Heatmap")
        self.pages.addTab(self.lifecycle_page, "Overtime, Comp, and Credit")
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self._build_summary_page()
        self._build_seasonality_page()
        self._build_heatmap_page()
        self._build_lifecycle_page()
        self.pages.currentChanged.connect(self._page_changed)

        file_menu = self.menuBar().addMenu("File")
        for label, callback in (
            ("Refresh", self.refresh_data),
            ("Open Chart", self.open_chart),
            ("Save Table as CSV...", self.save_csv),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        file_menu.addSeparator()
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

    def _build_summary_page(self) -> None:
        layout = QVBoxLayout(self.summary_page)
        self.summary_splitter = QSplitter(Qt.Vertical)
        self.summary_table = table_widget([], SUMMARY_COLUMNS)
        self.warning_table = table_widget([], WARNING_COLUMNS)
        self.summary_splitter.addWidget(self.summary_table)
        warning_container = QWidget()
        warning_layout = QVBoxLayout(warning_container)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.addWidget(QLabel("Data-Quality Warnings"))
        warning_layout.addWidget(self.warning_table)
        self.summary_splitter.addWidget(warning_container)
        self.summary_splitter.setSizes([600, 180])
        layout.addWidget(self.summary_splitter)

    def _build_seasonality_page(self) -> None:
        layout = QVBoxLayout(self.seasonality_page)
        row = QHBoxLayout()
        row.addWidget(QLabel("Analysis"))
        self.seasonality_selector = QComboBox()
        self.seasonality_selector.addItems(SEASONALITY_VIEWS)
        self.seasonality_selector.currentTextChanged.connect(self._render_seasonality)
        row.addWidget(self.seasonality_selector)
        row.addStretch(1)
        layout.addLayout(row)
        self.seasonality_description = QLabel()
        self.seasonality_description.setWordWrap(True)
        layout.addWidget(self.seasonality_description)
        self.seasonality_splitter = QSplitter(Qt.Vertical)
        self.seasonality_chart_scroll = QScrollArea()
        self.seasonality_chart_scroll.setWidgetResizable(True)
        self.seasonality_chart_image = QLabel()
        self.seasonality_chart_image.setAlignment(Qt.AlignCenter)
        self.seasonality_chart_scroll.setWidget(self.seasonality_chart_image)
        self.seasonality_splitter.addWidget(self.seasonality_chart_scroll)
        self.seasonality_table = table_widget([], MONTH_COLUMNS)
        self.seasonality_splitter.addWidget(self.seasonality_table)
        self.seasonality_splitter.setSizes([360, 430])
        layout.addWidget(self.seasonality_splitter, 1)

    def _build_heatmap_page(self) -> None:
        layout = QVBoxLayout(self.heatmap_page)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Heatmap"))
        self.heatmap_selector = QComboBox()
        self.heatmap_selector.currentIndexChanged.connect(self._render_heatmap)
        selector_row.addWidget(self.heatmap_selector)
        selector_row.addStretch(1)
        layout.addLayout(selector_row)
        self.heatmap_description = QLabel()
        self.heatmap_description.setWordWrap(True)
        layout.addWidget(self.heatmap_description)
        splitter = QSplitter(Qt.Vertical)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.heatmap_image = QLabel("No heatmap loaded")
        self.heatmap_image.setAlignment(Qt.AlignCenter)
        scroll.setWidget(self.heatmap_image)
        splitter.addWidget(scroll)
        self.heatmap_table = table_widget([], HEATMAP_COLUMNS)
        self.heatmap_table.cellDoubleClicked.connect(self._heatmap_drilldown)
        splitter.addWidget(self.heatmap_table)
        splitter.setSizes([430, 320])
        layout.addWidget(splitter)

    def _build_lifecycle_page(self) -> None:
        layout = QVBoxLayout(self.lifecycle_page)
        self.lifecycle_tabs = QTabWidget()
        self.lifecycle_tabs.currentChanged.connect(self._page_changed)
        layout.addWidget(self.lifecycle_tabs)
        self.lifecycle_table = table_widget([], LIFECYCLE_COLUMNS)
        self.lot_table = table_widget([], LOT_COLUMNS)
        self.allocation_table = table_widget([], ALLOCATION_COLUMNS)
        self.matured_table = table_widget([], MATURED_COLUMNS)
        for table, title in (
            (self.lifecycle_table, "Lifecycle Summary"),
            (self.lot_table, "Comp Lots"),
            (self.allocation_table, "Allocation Detail"),
            (self.matured_table, "Expiration Performance"),
        ):
            self.lifecycle_tabs.addTab(table, title)
        self.overtime_comp_page, self.overtime_comp_image, self.overtime_comp_table = self._monthly_lifecycle_page(OVERTIME_COMP_COLUMNS)
        self.comp_month_page, self.comp_month_image, self.comp_month_table = self._monthly_lifecycle_page(COMP_MONTH_COLUMNS)
        self.credit_month_page, self.credit_month_image, self.credit_month_table = self._monthly_lifecycle_page(CREDIT_MONTH_COLUMNS)
        self.lifecycle_tabs.addTab(self.overtime_comp_page, "Overtime, Comp, and Credit by Month")
        self.lifecycle_tabs.addTab(self.comp_month_page, "Monthly Comp Lifecycle")
        self.lifecycle_tabs.addTab(self.credit_month_page, "Monthly Credit Lifecycle")

    def _monthly_lifecycle_page(
        self, columns: list[tuple[str, str]]
    ) -> tuple[QWidget, QLabel, QTableWidget]:
        page = QWidget()
        layout = QVBoxLayout(page)
        splitter = QSplitter(Qt.Vertical)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        image = QLabel()
        image.setAlignment(Qt.AlignCenter)
        scroll.setWidget(image)
        splitter.addWidget(scroll)
        table = table_widget([], columns)
        splitter.addWidget(table)
        splitter.setSizes([360, 380])
        layout.addWidget(splitter)
        return page, image, table

    def _replace_table(
        self,
        old_table: QTableWidget,
        rows: list[dict[str, Any]],
        columns: list[tuple[str, str]],
    ) -> QTableWidget:
        new_table = table_widget(rows, columns)
        parent = old_table.parentWidget()
        if isinstance(parent, QSplitter):
            index = parent.indexOf(old_table)
            old_table.setParent(None)
            parent.insertWidget(index, new_table)
        elif parent and parent.layout():
            parent_layout = parent.layout()
            parent_layout.replaceWidget(old_table, new_table)
            old_table.hide()
            old_table.setParent(None)
        old_table.deleteLater()
        return new_table

    @Slot()
    def refresh_data(self) -> None:
        if self._load_thread and self._load_thread.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.progress.show()
        self.notice_label.setText("Loading normalized leave-year data from fedleave…")
        self._load_thread = QThread(self)
        self._loader = AnalyticsLoader(self.backend, self.data_dir, self.year)
        self._loader.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._loader.run)
        self._loader.finished.connect(self._loaded)
        self._loader.failed.connect(self._load_failed)
        self._loader.finished.connect(self._load_thread.quit)
        self._loader.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._loader.deleteLater)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.start()

    @Slot(dict)
    def _loaded(self, data: dict[str, Any]) -> None:
        self.data = data
        self.progress.hide()
        self.refresh_button.setEnabled(True)
        self._load_thread = None
        self._loader = None
        self._render_all()

    @Slot(str)
    def _load_failed(self, message: str) -> None:
        self.progress.hide()
        self.refresh_button.setEnabled(True)
        self._load_thread = None
        self._loader = None
        self.notice_label.setText("Data could not be loaded. The tables below are not current.")
        QMessageBox.critical(
            self,
            "FedLeave Analytics",
            f"Could not load analytics data for leave year {self.year}.\n\n{message}",
        )

    def set_data(self, data: dict[str, Any]) -> None:
        """Load normalized data directly; used by tests and embedded callers."""
        self._loaded(data)

    def _render_all(self) -> None:
        if not self.data:
            return
        available = [int(year) for year in self.data.get("available_leave_years", []) if year is not None]
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        for year in sorted(set(available or [self.year])):
            self.year_combo.addItem(str(year), year)
        index = self.year_combo.findData(self.year)
        self.year_combo.setCurrentIndex(max(0, index))
        self.year_combo.blockSignals(False)

        source = self.data["source"]
        if source["transactions_received"] == 0:
            self.notice_label.setText(
                "No transactions were returned for this leave year. Verify the selected leave year and the calendar's data settings."
            )
        elif source["absence_transactions"] == 0:
            self.notice_label.setText("Transactions were loaded, but none qualify as used or scheduled absence. Seasonality and heatmap totals are therefore zero.")
        else:
            self.notice_label.setText(
                "Values are hours. Through Today includes dates on or before today; Future Scheduled includes later active transactions."
            )

        self.summary_table = self._replace_table(self.summary_table, self.data["summary"], SUMMARY_COLUMNS)
        self.warning_table = self._replace_table(self.warning_table, self.data["warnings"], WARNING_COLUMNS)
        self._render_seasonality()
        self._render_heatmap()
        lifecycle = self.data["lifecycle"]
        replacements = (
            ("lifecycle_table", lifecycle["summary"], LIFECYCLE_COLUMNS),
            ("lot_table", lifecycle["lots"], LOT_COLUMNS),
            ("allocation_table", lifecycle["allocations"], ALLOCATION_COLUMNS),
            ("matured_table", lifecycle["matured_lots"], MATURED_COLUMNS),
        )
        for attribute, rows, columns in replacements:
            old = getattr(self, attribute)
            index = self.lifecycle_tabs.indexOf(old)
            title = self.lifecycle_tabs.tabText(index)
            new = table_widget(rows, columns)
            self.lifecycle_tabs.removeTab(index)
            self.lifecycle_tabs.insertTab(index, new, title)
            setattr(self, attribute, new)
        self.overtime_comp_table = self._replace_table(
            self.overtime_comp_table, lifecycle["monthly_overtime_vs_comp"], OVERTIME_COMP_COLUMNS
        )
        self.comp_month_table = self._replace_table(
            self.comp_month_table, lifecycle["monthly_comp"], COMP_MONTH_COLUMNS
        )
        self.credit_month_table = self._replace_table(
            self.credit_month_table, lifecycle["monthly_credit"], CREDIT_MONTH_COLUMNS
        )
        self._render_monthly_lifecycle_charts()
        self.lifecycle_table.cellDoubleClicked.connect(self._lifecycle_drilldown)
        self.lot_table.cellDoubleClicked.connect(self._lot_drilldown)
        self.allocation_table.cellDoubleClicked.connect(self._allocation_drilldown)
        self.overtime_comp_table.cellDoubleClicked.connect(self._monthly_lifecycle_drilldown)
        self.comp_month_table.cellDoubleClicked.connect(self._monthly_lifecycle_drilldown)
        self.credit_month_table.cellDoubleClicked.connect(self._monthly_lifecycle_drilldown)
        self._page_changed()

    def _render_seasonality(self) -> None:
        if not self.data:
            return
        name = self.seasonality_selector.currentText()
        path, columns, label_key, series = SEASONALITY_VIEWS[name]
        rows = list(_payload_value(self.data, path))
        descriptions = {
            "Leave Used by Month": "Actual and scheduled absence grouped by calendar month within the selected leave year.",
            "Leave Used by Day of Week": "Actual and scheduled absence grouped Monday through Sunday; weekends remain visible.",
            "Leave Used by Pay Period": "Actual and scheduled absence assigned to the pay period containing each transaction date.",
            "Overtime Worked by Month": "Paid overtime worked; comp earned instead of paid overtime is excluded.",
            "Net Leave Accumulation by Month": "Balance-increasing hours minus used, paid-out, forfeited, and expired hours. Starting balances are excluded.",
            "Final-Quarter Leave Concentration": "The final quarter is the final 25 percent of calendar days in the selected leave year.",
        }
        self.seasonality_description.setText(descriptions[name])
        new_table = table_widget(rows, columns)
        new_table.cellDoubleClicked.connect(self._seasonality_drilldown)
        table_index = self.seasonality_splitter.indexOf(self.seasonality_table)
        self.seasonality_table.setParent(None)
        self.seasonality_splitter.insertWidget(table_index, new_table)
        self.seasonality_table.deleteLater()
        self.seasonality_table = new_table
        if label_key == "month":
            chart = render_horizontal_bar_chart(f"{name} — {self.data['year']}", rows, label_key, series)
            self.seasonality_chart_image.setPixmap(chart.scaled(1180, 345, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.seasonality_chart_scroll.show()
            self.seasonality_splitter.setSizes([360, 430])
        else:
            self.seasonality_chart_scroll.hide()
            self.seasonality_splitter.setSizes([0, 790])
        self._page_changed()

    def _render_heatmap(self) -> None:
        if not self.data:
            return
        current_key = self.heatmap_selector.currentData()
        self.heatmap_selector.blockSignals(True)
        self.heatmap_selector.clear()
        for option in self.data["heatmap_options"]:
            self.heatmap_selector.addItem(option["label"], option["key"])
        selected_index = self.heatmap_selector.findData(current_key)
        self.heatmap_selector.setCurrentIndex(max(0, selected_index))
        self.heatmap_selector.blockSignals(False)
        selected_key = str(self.heatmap_selector.currentData() or "all-used")
        rows = self.data["heatmap_series"][selected_key]
        title = self.heatmap_selector.currentText()
        option = next(item for item in self.data["heatmap_options"] if item["key"] == selected_key)
        activity = "used" if option["direction"] == "used" else "earned"
        self.heatmap_description.setText(
            f"Each cell represents hours {activity} on that date. Darker cells contain more hours; "
            "a red outline and F indicate a future-dated transaction."
        )
        pixmap = render_heatmap(f"{title} Heatmap — {self.data['year']}", rows)
        self.heatmap_image.setPixmap(pixmap.scaled(1200, 440, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        new_table = table_widget(rows, HEATMAP_COLUMNS)
        new_table.cellDoubleClicked.connect(self._heatmap_drilldown)
        parent = self.heatmap_table.parentWidget()
        if isinstance(parent, QSplitter):
            index = parent.indexOf(self.heatmap_table)
            self.heatmap_table.setParent(None)
            parent.insertWidget(index, new_table)
        elif parent and parent.layout():
            parent.layout().replaceWidget(self.heatmap_table, new_table)
        self.heatmap_table.deleteLater()
        self.heatmap_table = new_table

    def _render_monthly_lifecycle_charts(self) -> None:
        if not self.data:
            return
        lifecycle = self.data["lifecycle"]
        chart_specs = (
            (
                self.overtime_comp_image,
                "Overtime, Comp, and Credit by Month",
                lifecycle["monthly_overtime_vs_comp"],
                [("overtime_worked", "Overtime Worked"), ("comp_earned", "Comp Earned"),
                 ("credit_earned", "Credit Earned or Worked")],
            ),
            (
                self.comp_month_image,
                "Monthly Comp Lifecycle",
                lifecycle["monthly_comp"],
                [("earned", "Earned"), ("used", "Used"), ("paid_out", "Paid Out"),
                 ("forfeited", "Forfeited"), ("expired", "Expired")],
            ),
            (
                self.credit_month_image,
                "Monthly Credit Lifecycle",
                lifecycle["monthly_credit"],
                [("earned", "Earned"), ("worked", "Worked"), ("used", "Used"),
                 ("forfeited", "Forfeited"), ("expired", "Expired")],
            ),
        )
        for image, title, rows, series in chart_specs:
            chart = render_horizontal_bar_chart(f"{title} — {self.data['year']}", rows, "month", series)
            image.setPixmap(chart.scaled(1180, 345, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _year_changed(self) -> None:
        selected = self.year_combo.currentData()
        if selected is None or int(selected) == self.year:
            return
        self.year = int(selected)
        self.refresh_data()

    def _page_changed(self, _index: int = -1) -> None:
        page = self.pages.currentIndex()
        self.open_chart_button.setEnabled(page != 0)
        if page == 0:
            self._set_current_table(self.summary_table, self.data.get("summary", []) if self.data else [], SUMMARY_COLUMNS)
        elif page == 1:
            name = self.seasonality_selector.currentText()
            path, columns, _label, _series = SEASONALITY_VIEWS[name]
            self._set_current_table(self.seasonality_table, list(_payload_value(self.data, path)) if self.data else [], columns)
        elif page == 2:
            selected_key = str(self.heatmap_selector.currentData() or "all-used")
            rows = self.data.get("heatmap_series", {}).get(selected_key, []) if self.data else []
            self._set_current_table(self.heatmap_table, rows, HEATMAP_COLUMNS)
        elif self.data:
            lifecycle = self.data["lifecycle"]
            mappings = [
                (self.lifecycle_table, lifecycle["summary"], LIFECYCLE_COLUMNS),
                (self.lot_table, lifecycle["lots"], LOT_COLUMNS),
                (self.allocation_table, lifecycle["allocations"], ALLOCATION_COLUMNS),
                (self.matured_table, lifecycle["matured_lots"], MATURED_COLUMNS),
                (self.overtime_comp_table, lifecycle["monthly_overtime_vs_comp"], OVERTIME_COMP_COLUMNS),
                (self.comp_month_table, lifecycle["monthly_comp"], COMP_MONTH_COLUMNS),
                (self.credit_month_table, lifecycle["monthly_credit"], CREDIT_MONTH_COLUMNS),
            ]
            index = self.lifecycle_tabs.currentIndex()
            self._set_current_table(*mappings[index])

    def _set_current_table(self, table: QTableWidget, rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
        self._current_table = table
        self._current_rows = rows
        self._current_columns = columns

    def open_chart(self) -> None:
        if not self.data:
            return
        page = self.pages.currentIndex()
        if page == 1:
            name = self.seasonality_selector.currentText()
            path, columns, label_key, series = SEASONALITY_VIEWS[name]
            rows = list(_payload_value(self.data, path))
            title = f"{name} — {self.data['year']}"
        elif page == 2:
            selected_key = str(self.heatmap_selector.currentData() or "all-used")
            rows = self.data["heatmap_series"][selected_key]
            columns = HEATMAP_COLUMNS
            title = f"{self.heatmap_selector.currentText()} Heatmap — {self.data['year']}"
            pixmap = render_heatmap(title, rows)
            self._show_chart(title, pixmap, rows, columns, f"{selected_key}-heatmap")
            return
        elif page == 3:
            index = self.lifecycle_tabs.currentIndex()
            if index == 4:
                rows = self.data["lifecycle"]["monthly_overtime_vs_comp"]
                columns, label_key = OVERTIME_COMP_COLUMNS, "month"
                series = [
                    ("overtime_worked", "Overtime Worked"),
                    ("comp_earned", "Comp Earned"),
                    ("credit_earned", "Credit Earned or Worked"),
                ]
                title = f"Monthly Overtime, Comp, and Credit — {self.data['year']}"
            elif index == 5:
                rows = self.data["lifecycle"]["monthly_comp"]
                columns, label_key = COMP_MONTH_COLUMNS, "month"
                series = [("earned", "Earned"), ("used", "Used"), ("paid_out", "Paid Out"), ("forfeited", "Forfeited"), ("expired", "Expired")]
                title = f"Monthly Comp Lifecycle — {self.data['year']}"
            elif index == 6:
                rows = self.data["lifecycle"]["monthly_credit"]
                columns, label_key = CREDIT_MONTH_COLUMNS, "month"
                series = [("earned", "Earned"), ("worked", "Worked"), ("used", "Used"), ("forfeited", "Forfeited"), ("expired", "Expired")]
                title = f"Monthly Credit Lifecycle — {self.data['year']}"
            else:
                QMessageBox.information(self, "Open Chart", "Select one of the monthly lifecycle tabs to open a chart. The other tabs are structured tables.")
                return
        else:
            return
        pixmap = render_bar_chart(title, rows, label_key, series)
        self._show_chart(title, pixmap, rows, columns, title.lower().replace(" ", "-"))

    def _show_chart(
        self,
        title: str,
        pixmap: QPixmap,
        rows: list[dict[str, Any]],
        columns: list[tuple[str, str]],
        slug: str,
    ) -> None:
        clean_slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
        base_name = f"fedleave-{clean_slug}-{self.data['year'] if self.data else self.year}"
        window = AnalyticsChartWindow(title, pixmap, rows, columns, self.pdf_folder, base_name)
        self._chart_windows.append(window)
        window.destroyed.connect(lambda: self._chart_windows.remove(window) if window in self._chart_windows else None)
        window.show()

    def save_csv(self) -> None:
        if not self.data or not self._current_rows:
            QMessageBox.information(self, "Save Table", "The selected table has no rows to export.")
            return
        default_name = f"fedleave-analytics-{self.data['year']}.csv"
        default_path = str(Path(self.pdf_folder).expanduser() / default_name) if self.pdf_folder else default_name
        path, _filter = QFileDialog.getSaveFileName(self, "Save Table as CSV", default_path, "CSV files (*.csv)")
        if not path:
            return
        try:
            with Path(path).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Leave Year", self.data["year"]])
                writer.writerow([label for _key, label in self._current_columns])
                for row in self._current_rows:
                    writer.writerow([row.get(key) for key, _label in self._current_columns])
        except OSError as exc:
            QMessageBox.warning(self, "Save Table", f"Could not save CSV to {path}.\n\n{exc}")

    def _seasonality_drilldown(self, row_index: int, _column: int) -> None:
        if not self.data:
            return
        name = self.seasonality_selector.currentText()
        path, _columns, _label, _series = SEASONALITY_VIEWS[name]
        rows = list(_payload_value(self.data, path))
        row_index = self._source_row_index(self.seasonality_table, row_index)
        if not 0 <= row_index < len(rows):
            return
        selected = rows[row_index]
        transactions = self.data["transactions"]
        if name in {"Leave Used by Month", "Overtime Worked by Month", "Net Leave Accumulation by Month"}:
            key = selected.get("month_key", "")
            transactions = [row for row in transactions if str(row["date"]).startswith(str(key))]
        elif name == "Leave Used by Day of Week":
            transactions = [row for row in transactions if datetime.fromisoformat(row["date"]).strftime("%A") == selected["weekday"]]
        elif name == "Leave Used by Pay Period":
            transactions = [row for row in transactions if selected["start_date"] <= row["date"] <= selected["end_date"]]
        elif name == "Final-Quarter Leave Concentration":
            transactions = [row for row in transactions if selected["start_date"] <= row["date"] <= selected["end_date"]]
        TransactionDialog(transactions, self).exec()

    def _heatmap_drilldown(self, row_index: int, _column: int) -> None:
        if not self.data:
            return
        selected_key = str(self.heatmap_selector.currentData() or "all-used")
        heatmap_rows = self.data["heatmap_series"][selected_key]
        row_index = self._source_row_index(self.heatmap_table, row_index)
        if not 0 <= row_index < len(heatmap_rows):
            return
        selected_date = heatmap_rows[row_index]["date"]
        option = next(
            (item for item in self.data["heatmap_options"] if item["key"] == selected_key),
            {"category": "all", "direction": "used"},
        )
        rows = [
            row for row in self.data["transactions"]
            if row["date"] == selected_date
            and row["direction"] == option["direction"]
            and (option["category"] == "all" or row["category"] == option["category"])
        ]
        TransactionDialog(rows, self).exec()

    @staticmethod
    def _source_row_index(table: QTableWidget, displayed_row: int) -> int:
        item = table.item(displayed_row, 0)
        source_index = item.data(Qt.UserRole + 1) if item else None
        return int(source_index) if isinstance(source_index, int) else displayed_row

    def _lifecycle_drilldown(self, row_index: int, _column: int) -> None:
        if not self.data:
            return
        rows = self.data["lifecycle"]["summary"]
        row_index = self._source_row_index(self.lifecycle_table, row_index)
        if not 0 <= row_index < len(rows):
            return
        metric = rows[row_index]["metric"]
        mapping = {
            "Overtime Worked": ("overtime", "worked"),
            "Comp Earned": ("comp", "earned"),
            "Comp Used": ("comp", "used"),
            "Comp Paid Out": ("comp", "paid_out"),
            "Comp Forfeited": ("comp", "forfeited"),
            "Comp Expired": ("comp", "expired"),
            "Credit Hours Earned": ("credit", "earned"),
            "Credit Hours Worked": ("credit", "worked"),
            "Credit Hours Used": ("credit", "used"),
            "Credit Hours Forfeited": ("credit", "forfeited"),
            "Credit Hours Expired": ("credit", "expired"),
        }
        category_direction = mapping.get(metric)
        transactions = self.data["transactions"]
        if category_direction:
            category, direction = category_direction
            transactions = [row for row in transactions if row["category"] == category and row["direction"] == direction]
        else:
            transactions = [row for row in transactions if row["category"] == "comp"]
        TransactionDialog(transactions, self).exec()

    def _lot_drilldown(self, row_index: int, _column: int) -> None:
        if not self.data:
            return
        lots = self.data["lifecycle"]["lots"]
        row_index = self._source_row_index(self.lot_table, row_index)
        if not 0 <= row_index < len(lots):
            return
        lot_id = lots[row_index]["lot_id"]
        rows = [
            row for row in self.data["transactions"]
            if row["transaction_id"] == lot_id or row["earned_transaction_id"] == lot_id
        ]
        TransactionDialog(rows, self).exec()

    def _allocation_drilldown(self, row_index: int, _column: int) -> None:
        if not self.data:
            return
        allocations = self.data["lifecycle"]["allocations"]
        row_index = self._source_row_index(self.allocation_table, row_index)
        if not 0 <= row_index < len(allocations):
            return
        transaction_id = allocations[row_index]["transaction_id"]
        rows = [row for row in self.data["transactions"] if row["transaction_id"] == transaction_id]
        TransactionDialog(rows, self).exec()

    def _monthly_lifecycle_drilldown(self, row_index: int, _column: int) -> None:
        if not self.data:
            return
        table = self.sender()
        if table is self.overtime_comp_table:
            rows = self.data["lifecycle"]["monthly_overtime_vs_comp"]
            categories = {"overtime", "comp", "credit"}
        elif table is self.credit_month_table:
            rows = self.data["lifecycle"]["monthly_credit"]
            categories = {"credit"}
        else:
            rows = self.data["lifecycle"]["monthly_comp"]
            categories = {"comp"}
        row_index = self._source_row_index(table, row_index)
        if not 0 <= row_index < len(rows):
            return
        month_label = rows[row_index]["month"]
        month_key = datetime.strptime(month_label, "%b %Y").strftime("%Y-%m")
        transactions = [
            row for row in self.data["transactions"]
            if row["date"].startswith(month_key) and row["category"] in categories
        ]
        TransactionDialog(transactions, self).exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only FedLeave seasonality and lifecycle analytics.")
    parser.add_argument("--backend", help="Path to the fedleave executable")
    parser.add_argument("--data-dir")
    parser.add_argument("--year", type=int)
    parser.add_argument("--font-size", type=int, default=10)
    parser.add_argument("--pdf-folder", default="")
    args = parser.parse_args(argv)
    backend = Path(args.backend) if args.backend else Path("fedleave")
    year = args.year or datetime.now().year
    app = QApplication.instance() or QApplication(sys.argv)
    data_dir = args.data_dir or str(get_default_data_dir())
    window = AnalyticsWindow(backend, data_dir, year, args.font_size, args.pdf_folder)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
