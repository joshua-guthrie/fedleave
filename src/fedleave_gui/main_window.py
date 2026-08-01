from __future__ import annotations

import calendar
import html
import subprocess
import tempfile
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QDate, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QFont, QPageLayout, QPainter, QPixmap, QResizeEvent, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from fedleave.config import get_default_data_dir
from fedleave.payperiods import calculate_pay_date
from fedleave.project_info import OFFICIAL_PROJECT_URL
from fedleave_month_report_graphic.report import BASE_WIDTH as MONTH_REPORT_WIDTH
from fedleave_month_report_graphic.report import ReportData as MonthReportData
from fedleave_month_report_graphic.report import render_svg as render_month_report_svg

from .backend import BackendError, BackendMissingError, BackendOptions, FedleaveBackend, find_analytics
from .chart_windows import LeaveChartDialog
from .resources import asset_file, help_base_url, help_file, window_icon
from .settings import GuiSettings, load_settings, save_settings, settings_path

CATEGORY_LABELS = {
    "annual": ("A", "Annual Leave"),
    "sick": ("S", "Sick Leave"),
    "overtime": ("OT", "Overtime"),
    "comp": ("Comp", "Comp Time"),
    "credit": ("Cr", "Credit Hours"),
    "travel_comp": ("TC", "Travel Comp"),
    "admin": ("Admin", "Admin Leave"),
    "lwop": ("LWOP", "LWOP"),
    "military": ("Mil", "Military Leave"),
    "court": ("Court", "Court Leave"),
    "religious_comp": ("RC", "Religious Comp"),
    "time_off_award": ("TOA", "Time-Off Award"),
    "excused": ("Exc", "Excused Leave"),
    "holiday": ("H", "Holiday"),
    "flex": ("Flex", "Flex"),
    "other": ("Other", "Other"),
    "restored_annual": ("RA", "Restored Annual"),
}

EDITABLE_CATEGORIES = list(CATEGORY_LABELS)

LEAVE_CHARTS = [
    ("Annual Leave Balance", "AnnualLeaveChartForTheYear"),
    ("Sick Leave Balance", "SickLeaveChartForTheYear"),
    ("Credit Hours Balance", "CreditHoursChartForTheYear"),
    ("Comp Time Balance", "CompTimeChartForTheYear"),
    ("Travel Comp Balance", "TravelCompChartForTheYear"),
    ("Time Off Award Balance", "TimeOffAwardChartForTheYear"),
]

YEARLY_COMPARISON_CHARTS = [
    ("Annual Leave", "AnnualLeaveYearlyComparison", "annual"),
    ("Sick Leave", "SickLeaveYearlyComparison", "sick"),
    ("Credit Hours", "CreditHoursYearlyComparison", "credit"),
    ("Comp Time", "CompTimeYearlyComparison", "comp"),
    ("Travel Comp", "TravelCompYearlyComparison", "travel_comp"),
    ("Time Off Award", "TimeOffAwardYearlyComparison", "time_off_award"),
    ("Overtime Worked", "OvertimeYearlyComparison", "overtime"),
]

CHART_APP_CATEGORIES = {
    "AnnualLeaveChartForTheYear": "annual",
    "SickLeaveChartForTheYear": "sick",
    "CreditHoursChartForTheYear": "credit",
    "CompTimeChartForTheYear": "comp",
    "TravelCompChartForTheYear": "travel_comp",
    "TimeOffAwardChartForTheYear": "time_off_award",
}


@dataclass
class DayValue:
    category: str
    value: float


def _nonzero(value: Any) -> bool:
    try:
        return abs(float(value)) > 0.000001
    except (TypeError, ValueError):
        return False


TABLE_TEXT_ALIGNMENT = Qt.AlignLeft | Qt.AlignVCenter
TABLE_NUMBER_ALIGNMENT = Qt.AlignRight | Qt.AlignVCenter


def _set_table_header_alignments(table: QTableWidget, alignments: list[int]) -> None:
    for column, alignment in enumerate(alignments):
        header_item = table.horizontalHeaderItem(column)
        if header_item is not None:
            header_item.setTextAlignment(alignment)


def _table_item(value: str, alignment: int) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setTextAlignment(alignment)
    return item


def _fmt(value: Any, *, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not _nonzero(number):
        return ""
    text = f"{abs(number):.2f}".rstrip("0").rstrip(".")
    if signed:
        return ("+" if number > 0 else "-") + text
    return text


def _entry_value(entry: dict[str, Any]) -> DayValue | None:
    category = str(entry.get("category", ""))
    if category not in CATEGORY_LABELS:
        return None
    hours = float(entry.get("hours", 0.0))
    if not _nonzero(hours):
        return None
    direction = str(entry.get("direction", ""))
    value = -hours if direction in {"used", "expired", "forfeited", "forced_decrease"} else hours
    return DayValue(category, value)


def _day_values_by_category(day: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for entry in day.get("entries", []):
        value = _entry_value(entry)
        if value is None:
            continue
        values[value.category] = values.get(value.category, 0.0) + value.value
    return values


def _day_comments_by_category(day: dict[str, Any]) -> dict[str, str]:
    comments: dict[str, str] = {}
    for entry in day.get("entries", []):
        value = _entry_value(entry)
        if value is None:
            continue
        description = str(entry.get("description", "")).strip()
        if description and value.category not in comments:
            comments[value.category] = description
    return comments


def _format_value_summary(value: Any) -> str:
    if not _nonzero(value):
        return "0"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    text = f"{abs(number):.2f}".rstrip("0").rstrip(".")
    direction = "earned" if number > 0 else "used"
    return f"{text} {direction}"


def _review_save_value_text(value: Any) -> str:
    return f"     {_format_value_summary(value)}"


def _category_display_text(category: str) -> str:
    return CATEGORY_LABELS.get(category, (category, category))[1]


def _month_toolbar_font(widget: QWidget) -> QFont:
    font = QFont(widget.font())
    point_size = font.pointSizeF()
    if point_size <= 0:
        point_size = 10.0
    font.setPointSizeF(max(point_size * 1.8, point_size + 6.0, 16.0))
    font.setBold(True)
    return font


def _section_heading(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


def _balance_date_label(selected: date, today: date | None = None) -> str:
    reference = today or date.today()
    if selected == reference:
        return "Today"
    return f"{selected.month}/{selected.day}/{selected.year}"


class DayCell(QPushButton):
    def __init__(self, day: dict[str, Any], settings: GuiSettings) -> None:
        super().__init__()
        self.day = day
        self.setMinimumSize(112, 92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self._display_text = self._text_for_day(settings)
        lines = self._display_text.splitlines()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(2)
        self.day_label = QLabel(lines[0])
        self.day_label.setObjectName("dayNumber")
        self.day_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.day_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.day_label)

        self.details_label = QLabel("\n".join(lines[1:]))
        self.details_label.setObjectName("dayDetails")
        self.details_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.details_label.setWordWrap(True)
        self.details_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.details_label, 1)
        self.setStyleSheet(self._style_for_day(settings))

    def display_text(self) -> str:
        return self._display_text

    def _text_for_day(self, settings: GuiSettings) -> str:
        parts = [str(int(str(self.day["date"])[-2:]))]
        holiday_name = self.day.get("holiday_name")
        if settings.show_holidays and holiday_name:
            parts.append(str(holiday_name))
        for entry in self.day.get("entries", []):
            if not settings.show_auto_accruals and entry.get("source") == "auto_accrual":
                continue
            value = _entry_value(entry)
            if value is None:
                continue
            short, _ = CATEGORY_LABELS[value.category]
            parts.append(f"{short:<5} {_fmt(value.value, signed=True):>5}")
        if settings.show_paydays and self.day.get("is_payday"):
            parts.append("Pay day")
        if settings.show_pay_period_end and self.day.get("is_pay_period_end"):
            parts.append("PP end")
        return "\n".join(parts)

    def _style_for_day(self, settings: GuiSettings) -> str:
        background = "#ffffff"
        border = "#cbd5e1"
        if not self.day.get("in_display_month"):
            background = "#f8fafc"
        if settings.show_holidays and self.day.get("holiday_name"):
            background = "#fff7ed"
            border = "#f97316"
        if settings.show_paydays and self.day.get("is_payday"):
            background = "#eff6ff"
            border = "#2563eb"
        if settings.show_pay_period_end and self.day.get("is_pay_period_end"):
            border = "#16a34a"
        if self.day.get("is_today"):
            background = "#fefce8"
            border = "#ca8a04"
        return (
            "QPushButton {"
            f"background: {background}; border: 1px solid {border}; color: #1f2937;"
            "font-family: monospace;"
            "}"
            "QLabel { color: #1f2937; background: transparent; border: none; }"
            "QPushButton:hover { border-width: 2px; }"
        )


class DayEditDialog(QDialog):
    def __init__(self, day: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit {day['date']}")
        self.day = day
        self.inputs: dict[str, QDoubleSpinBox] = {}
        self.directions: dict[str, QComboBox] = {}
        self.comment_inputs: dict[str, QLineEdit] = {}
        values = _day_values_by_category(day)
        comments = _day_comments_by_category(day)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose Use or Earn for each leave type, then enter positive hours."))
        form = QFormLayout()
        for category, (_, label) in CATEGORY_LABELS.items():
            current = values.get(category, 0.0)
            if not _nonzero(current):
                continue
            form.addRow(label, self._input_row(category, current, comments.get(category, "")))
        self.add_category = QComboBox()
        for category, (_, label) in CATEGORY_LABELS.items():
            if category not in self.inputs:
                self.add_category.addItem(label, category)
        add_button = QPushButton("Add Leave Type")
        add_button.clicked.connect(self._add_selected_category)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_category)
        add_row.addWidget(add_button)
        layout.addLayout(form)
        self.form = form
        layout.addLayout(add_row)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _spinner(self, value: float = 0.0) -> QDoubleSpinBox:
        spinner = QDoubleSpinBox()
        spinner.setRange(0.0, 24.0)
        spinner.setSingleStep(0.25)
        spinner.setDecimals(2)
        spinner.setValue(abs(value))
        return spinner

    def _input_row(self, category: str, value: float = 0.0, comment: str = "") -> QWidget:
        direction = QComboBox()
        direction.addItem("Use", "use")
        direction.addItem("Earn", "earn")
        if value > 0:
            direction.setCurrentIndex(direction.findData("earn"))
        spinner = self._spinner(value)
        self.directions[category] = direction
        self.inputs[category] = spinner

        comment_input = QLineEdit()
        comment_input.setPlaceholderText("Comment")
        comment_input.setText(comment)
        self.comment_inputs[category] = comment_input

        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(direction)
        top_row.addWidget(spinner, 1)
        row_layout.addLayout(top_row)
        row_layout.addWidget(comment_input)
        return row

    def _add_selected_category(self) -> None:
        category = self.add_category.currentData()
        if not category or category in self.inputs:
            return
        self.form.addRow(CATEGORY_LABELS[category][1], self._input_row(category))
        index = self.add_category.currentIndex()
        self.add_category.removeItem(index)

    def values(self) -> dict[str, float]:
        return {
            category: (-widget.value() if self.directions[category].currentData() == "use" else widget.value())
            for category, widget in self.inputs.items()
        }

    def comments(self) -> dict[str, str]:
        return {category: widget.text().strip() for category, widget in self.comment_inputs.items()}


class SaveDayPreviewDialog(QDialog):
    _COLUMN_WEIGHT_SUM = 5

    def __init__(
        self,
        day: dict[str, Any],
        existing_values: dict[str, float],
        new_values: dict[str, float],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Review Save for {day['date']}")
        self.resize(640, 420)
        self.setModal(True)
        self._existing_values = dict(existing_values)
        self._new_values = dict(new_values)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "This will replace the current values for each listed leave type. "
                "Review the current and new values before saving."
            )
        )
        layout.addWidget(QLabel(f"Date: {day['date']}"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Leave Type", "Existing", "New"])
        self.table.verticalHeader().setVisible(False)
        _set_table_header_alignments(self.table, [TABLE_TEXT_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self._populate_table()
        QTimer.singleShot(0, self._apply_column_widths)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Save Changes")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_column_widths()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        total_width = self.table.viewport().width()
        if total_width <= 0:
            return
        leave_type_width = total_width // self._COLUMN_WEIGHT_SUM
        value_width = (total_width - leave_type_width) // 2
        new_width = total_width - leave_type_width - value_width
        self.table.setColumnWidth(0, leave_type_width)
        self.table.setColumnWidth(1, value_width)
        self.table.setColumnWidth(2, new_width)

    def _populate_table(self) -> None:
        categories = sorted({*self._existing_values, *self._new_values})
        rows = [
            category
            for category in categories
            if _nonzero(self._existing_values.get(category, 0.0)) or _nonzero(self._new_values.get(category, 0.0))
        ]
        self.table.setRowCount(len(rows))
        for row, category in enumerate(rows):
            values = [
                (_category_display_text(category), TABLE_TEXT_ALIGNMENT),
                (_review_save_value_text(self._existing_values.get(category, 0.0)), TABLE_NUMBER_ALIGNMENT),
                (_review_save_value_text(self._new_values.get(category, 0.0)), TABLE_NUMBER_ALIGNMENT),
            ]
            for column, (value, alignment) in enumerate(values):
                self.table.setItem(row, column, _table_item(value, alignment))


class AbbreviationsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Leave Abbreviations")
        self.resize(520, 520)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(CATEGORY_LABELS), 2)
        self.table.setHorizontalHeaderLabels(["Abbreviation", "Leave Type"])
        self.table.verticalHeader().setVisible(False)
        _set_table_header_alignments(self.table, [TABLE_TEXT_ALIGNMENT, TABLE_TEXT_ALIGNMENT])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        for row, (short, label) in enumerate(CATEGORY_LABELS.values()):
            self.table.setItem(row, 0, _table_item(short, TABLE_TEXT_ALIGNMENT))
            self.table.setItem(row, 1, _table_item(label, TABLE_TEXT_ALIGNMENT))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DiagnosticDialog(QDialog):
    """Display an error report that can be selected and copied verbatim."""

    def __init__(self, title: str, report: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("The import could not be completed. Copy this report when filing an issue:"))
        self.report = QPlainTextEdit(report)
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.report, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy_button = buttons.addButton("Copy Report", QDialogButtonBox.ActionRole)
        copy_button.clicked.connect(self._copy_report)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_report(self) -> None:
        self.report.selectAll()
        self.report.copy()


class PreferencesDialog(QDialog):
    def __init__(self, settings: GuiSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.fedleave_path = QLineEdit(settings.fedleave_path)
        self.data_dir = QLineEdit(settings.data_dir)
        self.first_day = QComboBox()
        self.first_day.addItems(["Sunday", "Monday"])
        self.first_day.setCurrentText(settings.first_day_of_week)
        self.payday_offset = QSpinBox()
        self.payday_offset.setRange(0, 13)
        self.payday_offset.setValue(settings.payday_offset_days)
        self.show_auto = QCheckBox()
        self.show_auto.setChecked(settings.show_auto_accruals)
        self.show_holidays = QCheckBox()
        self.show_holidays.setChecked(settings.show_holidays)
        self.show_paydays = QCheckBox()
        self.show_paydays.setChecked(settings.show_paydays)
        self.show_pp_end = QCheckBox()
        self.show_pp_end.setChecked(settings.show_pay_period_end)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 18)
        self.font_size.setValue(settings.font_size)
        self.orientation = QComboBox()
        self.orientation.addItems(["Landscape", "Portrait"])
        self.orientation.setCurrentText(settings.print_orientation)
        self.pdf_folder = QLineEdit(settings.pdf_export_folder)
        self.expiration_reminders = QLineEdit(
            ", ".join(str(value) for value in settings.expiration_reminder_pay_periods)
        )
        form.addRow("Backend executable path", self.fedleave_path)
        form.addRow("Data directory", self.data_dir)
        form.addRow("First day of week", self.first_day)
        form.addRow("Pay day offset from pay-period end", self.payday_offset)
        form.addRow("Show automatic accruals", self.show_auto)
        form.addRow("Enable holiday highlighting", self.show_holidays)
        form.addRow("Enable pay-day highlighting", self.show_paydays)
        form.addRow("Enable pay-period-end highlighting", self.show_pp_end)
        form.addRow("Calendar font size", self.font_size)
        form.addRow("Print orientation", self.orientation)
        form.addRow("PDF export folder", self.pdf_folder)
        form.addRow("Expiration reminders (pay periods)", self.expiration_reminders)
        layout.addLayout(form)
        layout.addWidget(QLabel(f"Settings file: {settings_path()}"))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply(self) -> GuiSettings:
        self.settings.fedleave_path = self.fedleave_path.text().strip()
        self.settings.data_dir = self.data_dir.text().strip()
        self.settings.first_day_of_week = self.first_day.currentText()
        self.settings.payday_offset_days = self.payday_offset.value()
        self.settings.show_auto_accruals = self.show_auto.isChecked()
        self.settings.show_holidays = self.show_holidays.isChecked()
        self.settings.show_paydays = self.show_paydays.isChecked()
        self.settings.show_pay_period_end = self.show_pp_end.isChecked()
        self.settings.font_size = self.font_size.value()
        self.settings.print_orientation = self.orientation.currentText()
        self.settings.pdf_export_folder = self.pdf_folder.text().strip()
        reminders = []
        for value in self.expiration_reminders.text().split(","):
            try:
                number = int(value.strip())
            except ValueError:
                continue
            if number >= 0 and number not in reminders:
                reminders.append(number)
        self.settings.expiration_reminder_pay_periods = sorted(reminders) or [1, 3, 6, 12]
        return self.settings


class StartYearDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Start New Leave Year")
        today = date.today()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(today.year)
        self.start = QLineEdit(f"{today.year}-01-01")
        self.annual_accrual = self._hours(6.0)
        self.annual = self._hours()
        self.sick = self._hours()
        self.credit = self._hours()
        self.comp = self._hours()
        self.travel = self._hours()
        self.restored = self._hours()
        form.addRow("Leave year", self.year)
        form.addRow("Leave year start date", self.start)
        form.addRow("Annual accrual rate", self.annual_accrual)
        form.addRow("Annual leave carryover", self.annual)
        form.addRow("Sick leave carryover", self.sick)
        form.addRow("Credit hours carryover", self.credit)
        form.addRow("Comp time carryover", self.comp)
        form.addRow("Travel comp carryover", self.travel)
        form.addRow("Restored annual leave", self.restored)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _hours(self, value: float = 0.0) -> QDoubleSpinBox:
        spinner = QDoubleSpinBox()
        spinner.setRange(0.0, 10000.0)
        spinner.setSingleStep(0.25)
        spinner.setDecimals(2)
        spinner.setValue(value)
        return spinner


class SelectMonthDialog(QDialog):
    def __init__(self, year: int, month: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Month")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.year_input = QSpinBox()
        self.year_input.setRange(1900, 9999)
        self.year_input.setValue(year)
        form.addRow("Year", self.year_input)

        self.month_input = QComboBox()
        for month_number in range(1, 13):
            self.month_input.addItem(calendar.month_name[month_number], month_number)
        self.month_input.setCurrentIndex(max(0, month - 1))
        form.addRow("Month", self.month_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_year_month(self) -> tuple[int, int]:
        return self.year_input.value(), int(self.month_input.currentData())


class SelectDateDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QDate.currentDate())
        form.addRow("Date", self.date_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_date(self) -> date:
        selected = self.date_input.date()
        return date(selected.year(), selected.month(), selected.day())


class ChangeAccrualDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Annual Accrual")
        self.setModal(True)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Change the annual leave accrual rate starting on the selected date. "
            "FedLeave will update future automatic annual leave accrual transactions for that leave year."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()

        self.effective_date_input = QDateEdit()
        self.effective_date_input.setCalendarPopup(True)
        self.effective_date_input.setDisplayFormat("yyyy-MM-dd")
        self.effective_date_input.setDate(QDate.currentDate())
        form.addRow("Effective date", self.effective_date_input)

        self.hours_input = QComboBox()
        for hours in (4, 6, 8):
            self.hours_input.addItem(f"{hours} hours per pay period", hours)
        self.hours_input.setCurrentIndex(1)
        form.addRow("Annual accrual rate", self.hours_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_effective_date(self) -> str:
        return self.effective_date_input.date().toString("yyyy-MM-dd")

    def selected_hours(self) -> float:
        return float(self.hours_input.currentData())


class ForceBalanceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Force Leave Balance")
        self.setModal(True)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Set the exact balance for one leave category on a date. FedLeave records the difference "
            "as an auditable adjustment that affects that date and all later dates."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.category_input = QComboBox()
        for category, (_short, label) in CATEGORY_LABELS.items():
            if category != "overtime":
                self.category_input.addItem(label, category)
        self.hours_input = QDoubleSpinBox()
        self.hours_input.setRange(0.0, 10000.0)
        self.hours_input.setDecimals(2)
        self.hours_input.setSingleStep(0.25)
        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Why this balance is being corrected")
        form.addRow("Effective date", self.date_input)
        form.addRow("Leave category", self.category_input)
        form.addRow("Forced balance", self.hours_input)
        form.addRow("Comment", self.comment_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply Adjustment")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        if not self.comment_input.text().strip():
            QMessageBox.warning(self, "Comment Required", "Enter a comment explaining the forced balance.")
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        return {
            "date": self.date_input.date().toString("yyyy-MM-dd"),
            "category": str(self.category_input.currentData()),
            "hours": self.hours_input.value(),
            "comment": self.comment_input.text().strip(),
        }


class ExpirationStatusDialog(QDialog):
    def __init__(self, payload: dict[str, Any], reminders: list[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Expiring Leave Status")
        self.resize(1050, 600)
        layout = QVBoxLayout(self)
        earliest = payload.get("earliest_expiration_date") or "None"
        layout.addWidget(QLabel(f"As of {payload.get('as_of', '')}    Earliest expiration: {earliest}"))
        lots = [row for row in payload.get("lots", []) if float(row.get("remaining_hours", 0.0)) > 0]
        summary = []
        for threshold in reminders:
            hours = sum(
                float(row.get("remaining_hours", 0.0))
                for row in lots
                if int(row.get("pay_periods_remaining", 0)) <= threshold
            )
            summary.append(f"within {threshold} PP: {hours:.2f} h")
        layout.addWidget(QLabel("    ".join(summary)))
        layout.addWidget(
            QLabel(
                f"Expired/forfeited this leave year: "
                f"{float(payload.get('expired_or_forfeited_this_leave_year', 0.0)):.2f} hours"
            )
        )
        self.table = QTableWidget(len(lots), 8)
        self.table.setHorizontalHeaderLabels(
            ["Leave Type", "Earned", "Original Hours", "Remaining", "Expires", "PP Left", "Use / PP", "Lot ID"]
        )
        self.table.verticalHeader().setVisible(False)
        alignments = (
            [TABLE_TEXT_ALIGNMENT, TABLE_TEXT_ALIGNMENT]
            + [TABLE_NUMBER_ALIGNMENT] * 2
            + [TABLE_TEXT_ALIGNMENT]
            + [TABLE_NUMBER_ALIGNMENT] * 2
            + [TABLE_TEXT_ALIGNMENT]
        )
        _set_table_header_alignments(self.table, alignments)
        for row_number, row in enumerate(lots):
            values = [
                _category_display_text(str(row.get("category", ""))),
                str(row.get("earned_date", "")),
                f"{float(row.get('earned_hours', 0.0)):.2f}",
                f"{float(row.get('remaining_hours', 0.0)):.2f}",
                str(row.get("expiration_date", "")),
                str(row.get("pay_periods_remaining", "")),
                f"{float(row.get('hours_per_pay_period_to_use', 0.0)):.2f}",
                str(row.get("transaction_id", "")),
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_number, column, _table_item(value, alignments[column]))
        for column in range(7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ChangeLeaveYearDialog(QDialog):
    def __init__(self, years: list[int], current_year: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Leave Year")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.year_input = QComboBox()
        for year in years:
            self.year_input.addItem(str(year), year)
        if years:
            index = self.year_input.findData(current_year)
            self.year_input.setCurrentIndex(index if index >= 0 else 0)
        form.addRow("Leave year", self.year_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_year(self) -> int:
        return int(self.year_input.currentData())


class TransactionDateRangeDialog(QDialog):
    def __init__(self, start: date, end: date, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("View Leave Transactions")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.start_date_input = QDateEdit()
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setDisplayFormat("yyyy-MM-dd")
        self.start_date_input.setDate(QDate(start.year, start.month, start.day))
        form.addRow("Start Date", self.start_date_input)

        self.end_date_input = QDateEdit()
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setDisplayFormat("yyyy-MM-dd")
        self.end_date_input.setDate(QDate(end.year, end.month, end.day))
        form.addRow("End Date", self.end_date_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_dates(self) -> tuple[date, date]:
        start = date.fromisoformat(self.start_date_input.date().toString("yyyy-MM-dd"))
        end = date.fromisoformat(self.end_date_input.date().toString("yyyy-MM-dd"))
        return start, end


class LeaveTransactionsDialog(QDialog):
    def __init__(
        self, start: date, end: date, transactions: list[dict[str, Any]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Leave Transactions")
        self.resize(1100, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Transactions from {start.isoformat()} to {end.isoformat()}"))

        self.table = QTableWidget(len(transactions), 8)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Type", "Direction", "Hours", "Status", "Source", "Description", "ID"]
        )
        self.table.verticalHeader().setVisible(False)
        _set_table_header_alignments(
            self.table,
            [
                TABLE_TEXT_ALIGNMENT,
                TABLE_TEXT_ALIGNMENT,
                TABLE_TEXT_ALIGNMENT,
                TABLE_NUMBER_ALIGNMENT,
                TABLE_TEXT_ALIGNMENT,
                TABLE_TEXT_ALIGNMENT,
                TABLE_TEXT_ALIGNMENT,
                TABLE_TEXT_ALIGNMENT,
            ],
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._populate_rows(transactions)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_rows(self, transactions: list[dict[str, Any]]) -> None:
        for row, transaction in enumerate(transactions):
            category = str(transaction.get("category", "")).strip()
            label = CATEGORY_LABELS.get(category, (category, category))[1]
            self._set_row(
                row,
                [
                    str(transaction.get("date", "")),
                    label,
                    str(transaction.get("direction", "")).replace("_", " ").title(),
                    _fmt(transaction.get("hours")),
                    str(transaction.get("status", "")).replace("_", " "),
                    str(transaction.get("source", "")).replace("_", " "),
                    str(transaction.get("description", "")),
                    str(transaction.get("id", "")),
                ],
            )

    def _set_row(self, row: int, values: list[str]) -> None:
        alignments = [
            TABLE_TEXT_ALIGNMENT,
            TABLE_TEXT_ALIGNMENT,
            TABLE_TEXT_ALIGNMENT,
            TABLE_NUMBER_ALIGNMENT,
            TABLE_TEXT_ALIGNMENT,
            TABLE_TEXT_ALIGNMENT,
            TABLE_TEXT_ALIGNMENT,
            TABLE_TEXT_ALIGNMENT,
        ]
        for column, value in enumerate(values):
            self.table.setItem(row, column, _table_item(value, alignments[column]))


def _leave_year_metadata(source: FedleaveBackend | dict[str, Any]) -> dict[str, Any]:
    return source if isinstance(source, dict) else source.leave_years()


def _available_leave_years(source: FedleaveBackend | dict[str, Any]) -> list[int]:
    return sorted(
        int(record["leave_year"]) for record in _leave_year_metadata(source)["years"] if record.get("valid") is True
    )


def _visible_categories(source: FedleaveBackend | dict[str, Any]) -> set[str]:
    return set(_leave_year_metadata(source)["visible_categories"])


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.backend = self._backend()
        self.setWindowIcon(window_icon())
        self.today = date.today()
        self.year = self.today.year
        self.month = self.today.month
        self.balance_as_of = self.today
        self.month_json: dict[str, Any] | None = None
        self.use_or_lose_json: dict[str, Any] | None = None
        self.balance_snapshot: dict[str, Any] | None = None
        self.yearly_comparison_menu: Any | None = None
        self.leave_chart_actions: dict[str, QAction] = {}
        self.yearly_comparison_actions: dict[str, QAction] = {}
        self._leave_chart_windows: list[LeaveChartDialog] = []
        self._analytics_processes: list[subprocess.Popen[Any]] = []
        self.setWindowTitle("FedLeave Calendar")
        self.resize(1320, 860)
        self._build_ui()

    def start_initial_load(self) -> None:
        """Load an existing leave year or guide a first-time user through setup."""
        try:
            years = _available_leave_years(self.backend)
        except BackendMissingError:
            QMessageBox.critical(
                self,
                "Backend Missing",
                "The fedleave backend executable could not be found. Open Preferences to set the path.",
            )
            self.preferences()
            return
        except BackendError as exc:
            QMessageBox.warning(self, "Backend Error", str(exc))
            return
        if years:
            if self.year not in years:
                self.year = max(years)
            self.refresh()
            return

        if (
            QMessageBox.question(
                self,
                "Create a Leave Year",
                "No leave year is available. Would you like to create one now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            == QMessageBox.Yes
        ):
            self.new_leave_year()

    def start_background_checks(self) -> None:
        """Start low-frequency network and expiration reminders after the window is shown."""
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(6 * 60 * 60 * 1000)
        self._update_timer.timeout.connect(self.check_for_updates_periodically)
        self._update_timer.start()
        QTimer.singleShot(1500, self.check_for_updates_periodically)
        QTimer.singleShot(2000, self.check_expiration_reminders)

    def _backend(self) -> FedleaveBackend:
        configured_data_dir = Path(self.settings.data_dir).expanduser() if self.settings.data_dir else None
        return FedleaveBackend(
            BackendOptions(
                fedleave_path=self.settings.fedleave_path or None,
                data_dir=str(get_default_data_dir(configured_data_dir)),
            )
        )

    def _build_ui(self) -> None:
        self._build_menus()
        toolbar = QToolBar("Month")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(toolbar)
        self.month_toolbar_widget = QWidget()
        self.month_toolbar_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.month_toolbar_layout = QHBoxLayout(self.month_toolbar_widget)
        self.month_toolbar_layout.setContentsMargins(8, 4, 8, 4)
        self.month_toolbar_layout.setSpacing(12)

        self.previous_button = QPushButton("< Previous")
        self.previous_button.clicked.connect(self.previous_month)
        self.previous_button.setMinimumHeight(42)
        self.previous_button.setMinimumWidth(140)
        self.previous_button.setFont(_month_toolbar_font(self.previous_button))
        self.month_toolbar_layout.addWidget(self.previous_button)
        self.month_toolbar_layout.addStretch(1)

        self.month_toolbar_center = QWidget()
        self.month_toolbar_center.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        center_layout = QHBoxLayout(self.month_toolbar_center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(_month_toolbar_font(self.title_label))
        self.title_label.setMinimumWidth(180)
        self.today_button = QPushButton("Today")
        self.today_button.clicked.connect(self.go_today)
        self.today_button.setMinimumHeight(42)
        self.today_button.setMinimumWidth(92)
        self.today_button.setFont(_month_toolbar_font(self.today_button))
        center_layout.addWidget(self.title_label)
        center_layout.addWidget(self.today_button)
        self.month_toolbar_layout.addWidget(self.month_toolbar_center)
        self.month_toolbar_layout.addStretch(1)

        self.next_button = QPushButton("Next >")
        self.next_button.clicked.connect(self.next_month)
        self.next_button.setMinimumHeight(42)
        self.next_button.setMinimumWidth(120)
        self.next_button.setFont(_month_toolbar_font(self.next_button))
        self.month_toolbar_layout.addWidget(self.next_button)

        toolbar.addWidget(self.month_toolbar_widget)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.calendar_widget = QWidget()
        self.calendar_layout = QGridLayout(self.calendar_widget)
        self.calendar_layout.setSpacing(4)
        top.addWidget(self.calendar_widget, 3)
        side = QVBoxLayout()
        self.pay_periods_label = _section_heading("Pay Periods")
        side.addWidget(self.pay_periods_label)
        self.pay_period_scroll = QScrollArea()
        self.pay_period_scroll.setWidgetResizable(True)
        self.pay_period_widget = QWidget()
        self.pay_period_layout = QVBoxLayout(self.pay_period_widget)
        self.pay_period_layout.setContentsMargins(0, 0, 0, 0)
        self.pay_period_layout.setSpacing(8)
        self.pay_period_scroll.setWidget(self.pay_period_widget)
        self.pay_period_tables: list[QTableWidget] = []
        side.addWidget(self.pay_period_scroll)
        top.addLayout(side, 1)
        root_layout.addLayout(top, 4)
        self.balance_button = QPushButton()
        balance_font = QFont(self.balance_button.font())
        balance_font.setBold(True)
        self.balance_button.setFont(balance_font)
        self.balance_button.setCursor(Qt.PointingHandCursor)
        self.balance_button.setMinimumHeight(36)
        self.balance_button.clicked.connect(self.select_balance_date)
        self._update_balance_button_text()
        self.as_of_today_label = self.balance_button
        root_layout.addWidget(self.balance_button)
        self.balance_table = QTableWidget(0, 3)
        self.balance_table.setHorizontalHeaderLabels(["Category", "Balance", "Use or Lose"])
        _set_table_header_alignments(
            self.balance_table, [TABLE_TEXT_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT]
        )
        self.balance_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root_layout.addWidget(self.balance_table, 1)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._action(file_menu, "New Leave Year...", self.new_leave_year)
        self._action(file_menu, "Change Leave Year...", self.change_leave_year)
        self._action(file_menu, "Refresh", self.refresh)
        self._action(file_menu, "Print Preview...", self.print_preview)
        self._action(file_menu, "Print Month...", self.print_month)
        self._action(file_menu, "Save Month as PDF...", self.save_pdf)
        self._action(file_menu, "Preferences...", self.preferences)
        self._action(file_menu, "Exit", self.close)
        view_menu = self.menuBar().addMenu("View")
        self._action(view_menu, "Previous Month", self.previous_month)
        self._action(view_menu, "Next Month", self.next_month)
        self._action(view_menu, "Select Month...", self.select_month)
        self._action(view_menu, "Today", self.go_today)
        analysis_menu = self.menuBar().addMenu("Analysis")
        self._action(analysis_menu, "View Leave Transactions...", self.view_leave_transactions)
        self._action(analysis_menu, "Analytics...", self.open_analytics)
        leave_charts_menu = analysis_menu.addMenu("Leave Charts")
        for label, app_name in LEAVE_CHARTS:
            self.leave_chart_actions[CHART_APP_CATEGORIES[app_name]] = self._action(
                leave_charts_menu,
                label,
                lambda _checked=False, app_name=app_name, label=label: self.open_leave_chart(app_name, label),
            )
        self.yearly_comparison_menu = analysis_menu.addMenu("Yearly Leave Comparison")
        for label, app_name, category in YEARLY_COMPARISON_CHARTS:
            self.yearly_comparison_actions[category] = self._action(
                self.yearly_comparison_menu,
                f"{label} Comparison",
                lambda _checked=False, app_name=app_name, label=label, category=category: (
                    self.open_yearly_leave_comparison(app_name, label, category)
                ),
            )
        self.yearly_comparison_menu.setEnabled(False)
        self._toggle(
            view_menu, "Show Automatic Accruals in Day Cells", self.settings.show_auto_accruals, "show_auto_accruals"
        )
        self._toggle(view_menu, "Show Holidays", self.settings.show_holidays, "show_holidays")
        self._toggle(view_menu, "Show Pay-Day Highlight", self.settings.show_paydays, "show_paydays")
        self._toggle(
            view_menu, "Show Pay-Period End Highlight", self.settings.show_pay_period_end, "show_pay_period_end"
        )
        tools_menu = self.menuBar().addMenu("Tools")
        self._action(tools_menu, "Change Accrual...", self.change_accrual)
        self._action(tools_menu, "Force Leave Balance...", self.force_leave_balance)
        self._action(tools_menu, "Expiring Leave Status...", self.show_expirations)
        self._action(tools_menu, "Validate Data", self.validate_data)
        self._action(tools_menu, "Export FedLeave Data...", self.export_data)
        self._action(tools_menu, "Import FedLeave Data...", self.import_data)
        import_external_menu = tools_menu.addMenu("Import From External App")
        self._action(import_external_menu, "FRC-E WMS HTTP Leave Report", self.import_wms_http_leave_report)
        help_menu = self.menuBar().addMenu("Help")
        self._action(help_menu, "Help Contents", self.show_help)
        self._action(help_menu, "Leave Abbreviations", self.show_abbreviations)
        self._action(help_menu, "Official Project Website", self.open_project_website)
        self._action(help_menu, "Check for Updates...", self.check_for_updates)
        self._action(help_menu, "About FedLeave Calendar", self.about_gui)

    def _action(self, menu: Any, text: str, callback: Any) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _toggle(self, menu: Any, text: str, checked: bool, setting_name: str) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        action.setChecked(checked)
        action.triggered.connect(lambda value: self._set_toggle(setting_name, value))
        menu.addAction(action)
        return action

    def _set_toggle(self, name: str, value: bool) -> None:
        setattr(self.settings, name, bool(value))
        save_settings(self.settings)
        self.render_month()

    def _apply_month_display_settings(self) -> None:
        if not self.month_json:
            return
        _apply_payday_offset(self.month_json, self.settings.payday_offset_days)

    def _update_balance_button_text(self) -> None:
        if not hasattr(self, "balance_button"):
            return
        self.balance_button.setText(f"Leave Balances as of {_balance_date_label(self.balance_as_of)}")

    def _refresh_balance_snapshot(self) -> None:
        if not self.month_json:
            self.balance_snapshot = None
            self._update_balance_button_text()
            return

        if self.balance_as_of == date.today():
            snapshot = self.month_json.get("balance_as_of_today")
            if isinstance(snapshot, dict):
                self.balance_snapshot = snapshot
                self._update_balance_button_text()
                return

        try:
            self.balance_snapshot = self.backend.balance(self.year, as_of=self.balance_as_of.isoformat())
        except BackendError:
            snapshot = self.month_json.get("balance_as_of_today")
            self.balance_snapshot = snapshot if isinstance(snapshot, dict) else None
        self._update_balance_button_text()

    def select_balance_date(self) -> None:
        dialog = SelectDateDialog("Leave Balances as Of", self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.balance_as_of = dialog.selected_date()
        self._refresh_balance_snapshot()
        self._render_balances()

    def preferences(self) -> None:
        dialog = PreferencesDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = dialog.apply()
            save_settings(self.settings)
            self.backend = self._backend()
            # Apply display-only preferences immediately, even if the backend
            # reload subsequently fails or takes time.
            self.render_month()
            self.refresh()

    def _refresh_yearly_comparison_menu(self, metadata: dict[str, Any] | None = None) -> None:
        if self.yearly_comparison_menu is None:
            return
        self.yearly_comparison_menu.setEnabled(len(_available_leave_years(metadata or self.backend)) > 1)

    def _refresh_chart_visibility(self, metadata: dict[str, Any] | None = None) -> None:
        visible = _visible_categories(metadata or self.backend)
        for category, action in self.leave_chart_actions.items():
            action.setVisible(category in visible)
        for category, action in self.yearly_comparison_actions.items():
            action.setVisible(category in visible)

    def refresh(self) -> None:
        try:
            self.backend = self._backend()
            self.month_json = self.backend.load_month(self.year, self.month)
            self.use_or_lose_json = self.backend.use_or_lose(self.year)
            self._refresh_balance_snapshot()
            metadata = self.backend.leave_years()
            self._refresh_yearly_comparison_menu(metadata)
            self._refresh_chart_visibility(metadata)
        except BackendMissingError:
            QMessageBox.critical(
                self,
                "Backend Missing",
                "The fedleave backend executable could not be found. Open Preferences to set the path.",
            )
            self.preferences()
            return
        except BackendError as exc:
            QMessageBox.warning(self, "Backend Error", str(exc))
            return
        self.render_month()

    def render_month(self) -> None:
        if not self.month_json:
            return
        self._apply_month_display_settings()
        self.title_label.setText(f"{calendar.month_name[self.month]} {self.year}")
        self._render_calendar()
        self._render_pay_periods()
        self._render_balances()

    def _render_calendar(self) -> None:
        while self.calendar_layout.count():
            item = self.calendar_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        headers = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        if self.settings.first_day_of_week == "Monday":
            headers = headers[1:] + headers[:1]
        for index, header in enumerate(headers):
            label = QLabel(header)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-weight: 600; padding: 4px;")
            self.calendar_layout.addWidget(label, 0, index)
        days = list(self.month_json.get("days", []))
        if self.settings.first_day_of_week == "Monday":
            days = _monday_first(days)
        for index, day in enumerate(days):
            row = index // 7 + 1
            col = index % 7
            cell = DayCell(day, self.settings)
            cell.setFont(QFont("monospace", self.settings.font_size))
            cell.clicked.connect(lambda _, selected=day: self.edit_day(selected))
            self.calendar_layout.addWidget(cell, row, col)

    def _render_pay_periods(self) -> None:
        periods = [period for period in self.month_json.get("pay_periods", []) if period.get("touches_display_month")]
        while self.pay_period_layout.count():
            item = self.pay_period_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.pay_period_tables = []
        if not periods:
            self.pay_period_layout.addWidget(QLabel("No pay periods touch this month."))
            self.pay_period_layout.addStretch(1)
            return
        for period in periods:
            title = f"PP {period.get('number') or ''}: {period.get('start') or ''} to {period.get('end') or ''}"
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            pay_date = QLabel(f"Pay date: {period.get('pay_date') or 'Not available'}")
            pay_date.setStyleSheet("color: #475569;")
            group_layout.addWidget(pay_date)

            rows = _pay_period_rows(period)
            table = QTableWidget(len(rows), 4)
            table.setHorizontalHeaderLabels(["Type", "Earned", "Used", "Balance"])
            table.verticalHeader().setVisible(False)
            _set_table_header_alignments(
                table,
                [TABLE_TEXT_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT],
            )
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for column in range(1, 4):
                table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
            table.setSelectionMode(QTableWidget.NoSelection)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            for row, values in enumerate(rows):
                self._set_row(
                    table,
                    row,
                    values,
                    [TABLE_TEXT_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT],
                )
            table.resizeRowsToContents()
            row_height = table.verticalHeader().defaultSectionSize()
            table.setFixedHeight(table.horizontalHeader().height() + max(1, len(rows)) * row_height + 4)
            group_layout.addWidget(table)
            self.pay_period_layout.addWidget(group)
            self.pay_period_tables.append(table)
        self.pay_period_layout.addStretch(1)

    def _render_balances(self) -> None:
        snapshot = (
            self.balance_snapshot or (self.month_json.get("balance_as_of_today") if self.month_json else {}) or {}
        )
        balance = snapshot.get("balances") or {}
        use_or_lose = (
            (self.use_or_lose_json or {}).get("use_or_lose") if isinstance(self.use_or_lose_json, dict) else {}
        )
        if not isinstance(use_or_lose, dict):
            use_or_lose = {}
        if not use_or_lose:
            use_or_lose = (self.month_json.get("projected_balance") or {}).get("use_or_lose") or {}
        self.balance_table.setRowCount(0)
        for category, value in sorted(balance.items()):
            if not _nonzero(value):
                continue
            row = self.balance_table.rowCount()
            self.balance_table.insertRow(row)
            lose = use_or_lose.get("use_or_lose") if category == "annual" else None
            self._set_row(
                self.balance_table,
                row,
                [CATEGORY_LABELS.get(category, ("", category))[1], _fmt(value), _fmt(lose)],
                [TABLE_TEXT_ALIGNMENT, TABLE_NUMBER_ALIGNMENT, TABLE_NUMBER_ALIGNMENT],
            )

    def _set_row(self, table: QTableWidget, row: int, values: list[str], alignments: list[int] | None = None) -> None:
        for column, value in enumerate(values):
            alignment = alignments[column] if alignments and column < len(alignments) else TABLE_TEXT_ALIGNMENT
            table.setItem(row, column, _table_item(value, alignment))

    def edit_day(self, day: dict[str, Any]) -> None:
        dialog = DayEditDialog(day, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values:
            return
        preview = SaveDayPreviewDialog(day, _day_values_by_category(day), values, self)
        if preview.exec() != QDialog.Accepted:
            return
        try:
            self.backend.set_day(str(day["date"]), values, comments=dialog.comments())
        except BackendError as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return
        self.refresh()

    def previous_month(self) -> None:
        self.month -= 1
        if self.month < 1:
            self.month = 12
            self.year -= 1
        self.refresh()

    def next_month(self) -> None:
        self.month += 1
        if self.month > 12:
            self.month = 1
            self.year += 1
        self.refresh()

    def go_today(self) -> None:
        self.today = date.today()
        self.balance_as_of = self.today
        self.year = self.today.year
        self.month = self.today.month
        self.refresh()

    def select_month(self) -> None:
        dialog = SelectMonthDialog(self.year, self.month, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.year, self.month = dialog.selected_year_month()
        self.refresh()

    def new_leave_year(self) -> None:
        dialog = StartYearDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        if (
            QMessageBox.question(self, "Create Leave Year", f"Create Leave Year {dialog.year.value()}?")
            != QMessageBox.Yes
        ):
            return
        try:
            self.backend.init_year(
                year=dialog.year.value(),
                leave_year_start=dialog.start.text().strip(),
                annual_accrual=dialog.annual_accrual.value(),
                annual_start=dialog.annual.value(),
                sick_start=dialog.sick.value(),
                credit_start=dialog.credit.value(),
                comp_start=dialog.comp.value(),
                travel_comp_start=dialog.travel.value(),
                restored_annual_start=dialog.restored.value(),
            )
        except BackendError as exc:
            QMessageBox.warning(self, "Create Failed", str(exc))
            return
        self.balance_as_of = date.today()
        self.year = dialog.year.value()
        self.month = 1
        self.refresh()

    def validate_data(self) -> None:
        try:
            payload = self.backend.validate()
        except BackendError as exc:
            QMessageBox.warning(self, "Validation Failed", str(exc))
            return
        QMessageBox.information(
            self, "Validate Data", "Data is valid." if payload.get("ok") else "Validation found issues."
        )

    def export_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export FedLeave Data", "fedleave_backup.json", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            self.backend.run_text(["export-data", "--output", path])
        except BackendError as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))
            return
        QMessageBox.information(self, "Export FedLeave Data", "Export complete.")

    def _select_import_mode(self) -> str | None:
        prompt = QMessageBox(self)
        prompt.setWindowTitle("Import FedLeave Data")
        prompt.setIcon(QMessageBox.Question)
        prompt.setText("How should the selected backup be imported?")
        prompt.setInformativeText(
            "Merge adds transactions that are missing from the current data and keeps current "
            "transactions when IDs match.\n\n"
            "Replace restores the selected backup over matching files. Current files are backed "
            "up first."
        )
        merge_button = prompt.addButton("Merge", QMessageBox.AcceptRole)
        replace_button = prompt.addButton("Replace", QMessageBox.DestructiveRole)
        prompt.addButton(QMessageBox.Cancel)
        prompt.exec()
        selected_button = prompt.clickedButton()
        if selected_button is merge_button:
            return "--merge"
        if selected_button is replace_button:
            return "--overwrite"
        return None

    def import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import FedLeave Data", "", "JSON files (*.json)")
        if not path:
            return
        import_option = self._select_import_mode()
        if import_option is None:
            return

        try:
            self.backend.run_text(["import-data", "--input", path, import_option])
        except BackendError as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))
            return
        self.refresh()

    def import_wms_http_leave_report(self) -> None:
        if (
            QMessageBox.warning(
                self,
                "Experimental WMS Import",
                "This importer is experimental. Please report problems as GitHub issues. If the report "
                "does not contain information you consider private, attaching the original HTML file "
                "will make the issue much easier to diagnose.",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok,
            )
            != QMessageBox.Ok
        ):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import FRC-E WMS HTTP Leave Report",
            "",
            "HTML files (*.html *.htm)",
        )
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                "Import FRC-E WMS HTTP Leave Report",
                "This will overwrite matching leave transactions from the selected WMS report. Continue?",
            )
            != QMessageBox.Yes
        ):
            return
        try:
            self.backend.run_text(["import-wms-http", "--input", path])
        except BackendError as exc:
            DiagnosticDialog("WMS Import Failed", str(exc), self).exec()
            return
        self.refresh()

    def change_accrual(self) -> None:
        dialog = ChangeAccrualDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.backend.accrual_change(
                as_of=dialog.selected_effective_date(),
                hours=dialog.selected_hours(),
                category="annual",
            )
        except BackendError as exc:
            QMessageBox.warning(self, "Change Accrual", str(exc))
            return
        self.refresh()

    def force_leave_balance(self) -> None:
        dialog = ForceBalanceDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            result = self.backend.force_balance(**dialog.values())
        except BackendError as exc:
            QMessageBox.warning(self, "Force Leave Balance", str(exc))
            return
        QMessageBox.information(
            self,
            "Force Leave Balance",
            f"{_category_display_text(str(result.get('category', '')))} was set to "
            f"{float(result.get('forced_balance', 0.0)):.2f} hours as of {result.get('date', '')}.",
        )
        self.refresh()

    def _update_check_is_due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        try:
            previous = datetime.fromisoformat(self.settings.last_update_check_utc)
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return True
        return now - previous >= timedelta(hours=24)

    def check_for_updates_periodically(self) -> None:
        if self._update_check_is_due():
            self._perform_update_check(interactive=False)

    def check_for_updates(self) -> None:
        self._perform_update_check(interactive=True)

    def _perform_update_check(self, *, interactive: bool) -> None:
        self.settings.last_update_check_utc = datetime.now(timezone.utc).isoformat()
        save_settings(self.settings)
        try:
            result = self.backend.check_for_updates()
        except BackendError as exc:
            if interactive:
                QMessageBox.warning(self, "Check for Updates", str(exc))
            return
        if result.get("status") != "ok":
            if interactive:
                QMessageBox.information(
                    self, "Check for Updates", str(result.get("message", "Update check unavailable."))
                )
            return
        latest = str(result.get("latest_version") or "")
        if result.get("update_available"):
            if not interactive and latest == self.settings.last_update_notified_version:
                return
            QMessageBox.information(
                self,
                "FedLeave Update Available",
                f"FedLeave {latest} is available (installed: {result.get('current_version', '')}).\n\n"
                f"Download: {result.get('release_url', '')}\n\n{result.get('instructions', '')}",
            )
            self.settings.last_update_notified_version = latest
            save_settings(self.settings)
        elif interactive:
            QMessageBox.information(self, "Check for Updates", "This installation is up to date.")

    def _expiration_payload(self) -> dict[str, Any] | None:
        if not hasattr(self.backend, "expirations"):
            return None
        try:
            return self.backend.expirations(self.year)
        except BackendError:
            return None

    def show_expirations(self) -> None:
        payload = self._expiration_payload()
        if payload is None:
            QMessageBox.warning(self, "Expiring Leave Status", "Expiration status could not be loaded.")
            return
        ExpirationStatusDialog(payload, self.settings.expiration_reminder_pay_periods, self).exec()

    def check_expiration_reminders(self) -> None:
        today_text = date.today().isoformat()
        if self.settings.last_expiration_reminder_date == today_text:
            return
        payload = self._expiration_payload()
        if payload is None:
            return
        limits = self.settings.expiration_reminder_pay_periods
        if not limits:
            return
        urgent = [
            row
            for row in payload.get("lots", [])
            if float(row.get("remaining_hours", 0.0)) > 0 and int(row.get("pay_periods_remaining", 0)) <= max(limits)
        ]
        if not urgent:
            return
        total = sum(float(row.get("remaining_hours", 0.0)) for row in urgent)
        QMessageBox.warning(
            self,
            "Expiring Leave Reminder",
            f"{total:.2f} hours are due to expire within {max(limits)} pay periods. "
            "Open Tools > Expiring Leave Status for lot details.",
        )
        self.settings.last_expiration_reminder_date = today_text
        save_settings(self.settings)

    def open_leave_chart(self, app_name: str, label: str) -> None:
        year = self.month_json.get("year") if isinstance(self.month_json, dict) else self.year
        data_dir = self.settings.data_dir or None
        with tempfile.TemporaryDirectory() as temp_dir_name:
            output_file = Path(temp_dir_name) / f"{app_name}.png"
            try:
                self.backend.run_chart_app(
                    app_name,
                    output_file=output_file,
                    year=int(year) if year is not None else None,
                    data_dir=data_dir,
                )
            except BackendError as exc:
                QMessageBox.warning(self, f"{label} Chart", str(exc))
                return
            pixmap = QPixmap(str(output_file))
            if pixmap.isNull():
                QMessageBox.warning(self, f"{label} Chart", "Chart image could not be loaded.")
                return
            dialog = LeaveChartDialog(label, pixmap, self)
            self._leave_chart_windows.append(dialog)

            def _cleanup() -> None:
                if dialog in self._leave_chart_windows:
                    self._leave_chart_windows.remove(dialog)

            dialog.finished.connect(lambda _: _cleanup())
            dialog.show()

    def open_analytics(self) -> None:
        try:
            analytics = find_analytics()
            backend = self.backend.executable_path()
        except BackendError as exc:
            QMessageBox.warning(self, "FedLeave Analytics", str(exc))
            return
        command = [
            str(analytics),
            "--backend",
            str(backend),
            "--year",
            str(self.year),
            "--font-size",
            str(self.settings.font_size),
        ]
        command.extend(["--data-dir", str(self.backend.data_directory())])
        if self.settings.pdf_export_folder:
            command.extend(["--pdf-folder", self.settings.pdf_export_folder])
        try:
            process = subprocess.Popen(command)
        except OSError as exc:
            QMessageBox.warning(self, "FedLeave Analytics", str(exc))
            return
        self._analytics_processes.append(process)

    def open_yearly_leave_comparison(self, app_name: str, label: str, _category: str) -> None:
        dialog = SelectDateDialog(f"{label} Comparison", self)
        if dialog.exec() != QDialog.Accepted:
            return

        data_dir = self.settings.data_dir or None
        with tempfile.TemporaryDirectory() as temp_dir_name:
            output_file = Path(temp_dir_name) / f"{app_name}.png"
            try:
                self.backend.run_chart_app(
                    app_name,
                    output_file=output_file,
                    as_of=dialog.selected_date().isoformat(),
                    data_dir=data_dir,
                )
            except BackendError as exc:
                QMessageBox.warning(self, f"{label} Comparison", str(exc))
                return
            pixmap = QPixmap(str(output_file))
            if pixmap.isNull():
                QMessageBox.warning(self, f"{label} Comparison", "Chart image could not be loaded.")
                return
            chart_dialog = LeaveChartDialog(f"{label} Comparison", pixmap, self)
            self._leave_chart_windows.append(chart_dialog)

            def _cleanup() -> None:
                if chart_dialog in self._leave_chart_windows:
                    self._leave_chart_windows.remove(chart_dialog)

            chart_dialog.finished.connect(lambda _: _cleanup())
            chart_dialog.show()

    def _month_report_data(self) -> MonthReportData:
        if not self.month_json:
            raise BackendError("Month data is not loaded.")
        month_json = dict(self.month_json)
        balance_json = month_json.get("balance_as_of_today")
        if not isinstance(balance_json, dict):
            balance_json = {"balances": {}}
        projected_json = self.use_or_lose_json
        if not isinstance(projected_json, dict):
            projected_json = month_json.get("projected_balance")
        if not isinstance(projected_json, dict):
            projected_json = {"balances": {}, "use_or_lose": {}}
        return MonthReportData(
            month_json=month_json,
            balance_json=balance_json,
            projected_json=projected_json,
            pay_periods_json=None,
            today=self.today,
            generated_at=datetime.now(),
        )

    def _print_document(self, printer: QPrinter) -> None:
        printer.setPageOrientation(QPageLayout.Landscape)
        svg = render_month_report_svg(self._month_report_data(), MONTH_REPORT_WIDTH)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        painter = QPainter(printer)
        try:
            painter.fillRect(printer.pageLayout().paintRectPixels(printer.resolution()), QColor("white"))
            renderer.render(painter, printer.pageLayout().paintRectPixels(printer.resolution()))
        finally:
            painter.end()

    def print_preview(self) -> None:
        preview = QPrintPreviewDialog(self)
        preview.paintRequested.connect(self._print_document)
        preview.exec()

    def print_month(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.Accepted:
            self._print_document(printer)

    def save_pdf(self) -> None:
        folder = self.settings.pdf_export_folder or str(Path.home())
        default = str(Path(folder) / f"fedleave-{self.year}-{self.month:02d}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save Month as PDF", default, "PDF files (*.pdf)")
        if not path:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        self._print_document(printer)

    def show_help(self) -> None:
        self._show_html_file("fedleave-calendar-help.html", "Help Contents")

    def open_project_website(self) -> None:
        webbrowser.open(OFFICIAL_PROJECT_URL)

    def about_gui(self) -> None:
        self._show_html_file("about-fedleave-calendar.html", "About FedLeave Calendar")

    def _show_html_file(self, filename: str, title: str) -> None:
        path = help_file(filename)
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        if path.exists():
            if filename == "about-fedleave-calendar.html":
                browser.document().addResource(
                    QTextDocument.ImageResource,
                    QUrl("qrc:/about-fedleave-calendar-logo"),
                    QPixmap(str(asset_file("fedleave-logo.png"))),
                )
            browser.document().setBaseUrl(help_base_url(filename))
            browser.setHtml(path.read_text(encoding="utf-8"))
        else:
            browser.setHtml(f"<h1>{html.escape(title)}</h1><p>Help file was not found.</p>")
        layout.addWidget(browser)
        dialog.exec()

    def change_leave_year(self) -> None:
        years = _available_leave_years(self.backend)
        if not years:
            QMessageBox.warning(self, "Change Leave Year", "No leave year files were found.")
            return

        dialog = ChangeLeaveYearDialog(years, self.year, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.balance_as_of = date.today()
        self.year = dialog.selected_year()
        self.refresh()

    def show_abbreviations(self) -> None:
        AbbreviationsDialog(self).exec()

    def view_leave_transactions(self) -> None:
        today = date.today()
        start_default = date(self.year, self.month, 1)
        end_default = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        if end_default > today:
            end_default = today

        dialog = TransactionDateRangeDialog(start_default, end_default, self)
        if dialog.exec() != QDialog.Accepted:
            return

        start_date, end_date = dialog.selected_dates()
        if end_date < start_date:
            QMessageBox.warning(self, "View Leave Transactions", "The end date must be on or after the start date.")
            return

        try:
            transactions = self._transactions_in_range(start_date, end_date)
        except BackendError as exc:
            QMessageBox.warning(self, "View Leave Transactions", str(exc))
            return

        if not transactions:
            QMessageBox.information(
                self, "View Leave Transactions", "No leave transactions were found for that date range."
            )
            return

        LeaveTransactionsDialog(start_date, end_date, transactions, self).exec()

    def _transactions_in_range(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        years = _available_leave_years(self.backend)
        if not years:
            years = [self.year]

        rows: list[dict[str, Any]] = []
        for year in years:
            for transaction in self.backend.list_transactions(year):
                try:
                    transaction_date = date.fromisoformat(str(transaction.get("date", "")))
                except ValueError:
                    continue
                if transaction_date < start_date or transaction_date > end_date:
                    continue
                if not _nonzero(transaction.get("hours")):
                    continue
                rows.append(transaction)

        rows.sort(key=lambda transaction: (str(transaction.get("date", "")), str(transaction.get("id", ""))))
        return rows

    def about_backend(self) -> None:
        try:
            version = self.backend.version()
            executable = self.backend.executable_path()
        except BackendError as exc:
            QMessageBox.warning(self, "About fedleave Backend", f"Backend information could not be read.\n\n{exc}")
            return
        QMessageBox.information(self, "About fedleave Backend", f"{version}\n\nExecutable: {executable}")


def _monday_first(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [days[index : index + 7] for index in range(0, len(days), 7)]
    reordered: list[dict[str, Any]] = []
    for row in rows:
        if len(row) == 7:
            reordered.extend(row[1:] + row[:1])
        else:
            reordered.extend(row)
    return reordered


def _pay_period_rows(period: dict[str, Any]) -> list[list[str]]:
    totals = period.get("totals") or {}
    balances = period.get("ending_balances") or {}
    categories = sorted({*totals, *balances})
    rows: list[list[str]] = []
    for category in categories:
        category_totals = totals.get(category) or {}
        earned = _fmt(category_totals.get("earned"))
        used = _fmt(category_totals.get("used"))
        balance = _fmt(balances.get(category))
        if not any((earned, used, balance)):
            continue
        label = CATEGORY_LABELS.get(category, (category, category))[1]
        rows.append([label, earned, used, balance])
    return rows


def _apply_payday_offset(month_json: dict[str, Any], payday_offset_days: int) -> dict[str, Any]:
    pay_dates: set[str] = set()
    for period in month_json.get("pay_periods", []):
        end_value = period.get("end_date") or period.get("end")
        if not end_value:
            continue
        try:
            end_date = date.fromisoformat(str(end_value))
        except ValueError:
            continue
        pay_date = calculate_pay_date(end_date, payday_offset_days).isoformat()
        period["pay_date"] = pay_date
        pay_dates.add(pay_date)

    month_json["pay_dates"] = sorted(pay_dates)
    for day in month_json.get("days", []):
        day["is_payday"] = str(day.get("date")) in pay_dates
    return month_json
