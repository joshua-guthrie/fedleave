from __future__ import annotations

import calendar
import html
import os
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .backend import BackendError, BackendMissingError, BackendOptions, FedleaveBackend
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


@dataclass
class DayValue:
    category: str
    value: float


def _nonzero(value: Any) -> bool:
    try:
        return abs(float(value)) > 0.000001
    except (TypeError, ValueError):
        return False


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
    value = -hours if direction in {"used", "expired", "forfeited", "voided"} else hours
    return DayValue(category, value)


class DayCell(QPushButton):
    def __init__(self, day: dict[str, Any], settings: GuiSettings) -> None:
        super().__init__()
        self.day = day
        self.setMinimumSize(112, 92)
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
        values: dict[str, float] = {}
        for entry in day.get("entries", []):
            value = _entry_value(entry)
            if value is None:
                continue
            values[value.category] = values.get(value.category, 0.0) + value.value

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose Use or Earn for each leave type, then enter positive hours."))
        form = QFormLayout()
        for category, (_, label) in CATEGORY_LABELS.items():
            current = values.get(category, 0.0)
            if not _nonzero(current):
                continue
            form.addRow(label, self._input_row(category, current))
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

    def _input_row(self, category: str, value: float = 0.0) -> QWidget:
        direction = QComboBox()
        direction.addItem("Use", "use")
        direction.addItem("Earn", "earn")
        if value > 0:
            direction.setCurrentIndex(direction.findData("earn"))
        spinner = self._spinner(value)
        self.directions[category] = direction
        self.inputs[category] = spinner

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(direction)
        row_layout.addWidget(spinner, 1)
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
        form.addRow("Backend executable path", self.fedleave_path)
        form.addRow("Data directory", self.data_dir)
        form.addRow("First day of week", self.first_day)
        form.addRow("Show automatic accruals", self.show_auto)
        form.addRow("Enable holiday highlighting", self.show_holidays)
        form.addRow("Enable pay-day highlighting", self.show_paydays)
        form.addRow("Enable pay-period-end highlighting", self.show_pp_end)
        form.addRow("Calendar font size", self.font_size)
        form.addRow("Print orientation", self.orientation)
        form.addRow("PDF export folder", self.pdf_folder)
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
        self.settings.show_auto_accruals = self.show_auto.isChecked()
        self.settings.show_holidays = self.show_holidays.isChecked()
        self.settings.show_paydays = self.show_paydays.isChecked()
        self.settings.show_pay_period_end = self.show_pp_end.isChecked()
        self.settings.font_size = self.font_size.value()
        self.settings.print_orientation = self.orientation.currentText()
        self.settings.pdf_export_folder = self.pdf_folder.text().strip()
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.backend = self._backend()
        self.today = date.today()
        self.year = self.today.year
        self.month = self.today.month
        self.month_json: dict[str, Any] | None = None
        self.setWindowTitle("FedLeave Calendar")
        self.resize(1320, 860)
        self._build_ui()
        self.refresh()

    def _backend(self) -> FedleaveBackend:
        return FedleaveBackend(
            BackendOptions(
                fedleave_path=self.settings.fedleave_path or None,
                data_dir=self.settings.data_dir or None,
            )
        )

    def _build_ui(self) -> None:
        self._build_menus()
        toolbar = QToolBar("Month")
        self.addToolBar(toolbar)
        previous_action = QAction("< Previous", self)
        previous_action.triggered.connect(self.previous_month)
        next_action = QAction("Next >", self)
        next_action.triggered.connect(self.next_month)
        today_action = QAction("Today", self)
        today_action.triggered.connect(self.go_today)
        toolbar.addAction(previous_action)
        self.title_label = QLabel()
        self.title_label.setMinimumWidth(180)
        self.title_label.setAlignment(Qt.AlignCenter)
        toolbar.addWidget(self.title_label)
        toolbar.addAction(next_action)
        toolbar.addAction(today_action)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.calendar_widget = QWidget()
        self.calendar_layout = QGridLayout(self.calendar_widget)
        self.calendar_layout.setSpacing(4)
        top.addWidget(self.calendar_widget, 3)
        side = QVBoxLayout()
        side.addWidget(QLabel("Pay Periods"))
        self.pay_period_table = QTableWidget(0, 4)
        self.pay_period_table.setHorizontalHeaderLabels(["Period", "Dates", "Pay Day", "Summary"])
        self.pay_period_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        side.addWidget(self.pay_period_table)
        top.addLayout(side, 1)
        root_layout.addLayout(top, 4)
        root_layout.addWidget(QLabel("As of Today"))
        self.balance_table = QTableWidget(0, 3)
        self.balance_table.setHorizontalHeaderLabels(["Category", "Balance", "Use or Lose"])
        self.balance_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root_layout.addWidget(self.balance_table, 1)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._action(file_menu, "New Leave Year...", self.new_leave_year)
        self._action(file_menu, "Refresh", self.refresh)
        self._action(file_menu, "Print Preview...", self.print_preview)
        self._action(file_menu, "Print Month...", self.print_month)
        self._action(file_menu, "Save Month as PDF...", self.save_pdf)
        self._action(file_menu, "Preferences...", self.preferences)
        self._action(file_menu, "Exit", self.close)
        view_menu = self.menuBar().addMenu("View")
        self._action(view_menu, "Previous Month", self.previous_month)
        self._action(view_menu, "Next Month", self.next_month)
        self._action(view_menu, "Today", self.go_today)
        self._toggle(view_menu, "Show Automatic Accruals in Day Cells", self.settings.show_auto_accruals, "show_auto_accruals")
        self._toggle(view_menu, "Show Holidays", self.settings.show_holidays, "show_holidays")
        self._toggle(view_menu, "Show Pay-Day Highlight", self.settings.show_paydays, "show_paydays")
        self._toggle(view_menu, "Show Pay-Period End Highlight", self.settings.show_pay_period_end, "show_pay_period_end")
        tools_menu = self.menuBar().addMenu("Tools")
        self._action(tools_menu, "Validate Data", self.validate_data)
        self._action(tools_menu, "Export Data...", self.export_data)
        self._action(tools_menu, "Import Data...", self.import_data)
        self._action(tools_menu, "Open Data Folder", self.open_data_folder)
        self._action(tools_menu, "Open Preferences Folder", lambda: webbrowser.open(settings_path().parent.as_uri()))
        help_menu = self.menuBar().addMenu("Help")
        self._action(help_menu, "Help Contents", self.show_help)
        self._action(help_menu, "Leave Abbreviations", self.show_abbreviations)
        self._action(help_menu, "About FedLeave Calendar", self.about_gui)
        self._action(help_menu, "About fedleave Backend", self.about_backend)

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

    def refresh(self) -> None:
        try:
            self.backend = self._backend()
            self.month_json = self.backend.load_month(self.year, self.month)
        except BackendMissingError:
            QMessageBox.critical(self, "Backend Missing", "The fedleave backend executable could not be found. Open Preferences to set the path.")
            self.preferences()
            return
        except BackendError as exc:
            QMessageBox.warning(self, "Backend Error", str(exc))
            return
        self.render_month()

    def render_month(self) -> None:
        if not self.month_json:
            return
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
        self.pay_period_table.setRowCount(0)
        for period in periods:
            row = self.pay_period_table.rowCount()
            self.pay_period_table.insertRow(row)
            summaries = []
            for category, totals in sorted((period.get("totals") or {}).items()):
                parts = []
                for key in ("earned", "used", "worked", "net"):
                    value = totals.get(key)
                    if _nonzero(value):
                        parts.append(f"{key} {_fmt(value, signed=True)}")
                balance = (period.get("ending_balances") or {}).get(category)
                if _nonzero(balance):
                    parts.append(f"bal {_fmt(balance)}")
                if parts:
                    summaries.append(f"{CATEGORY_LABELS.get(category, ('', category))[1]}: " + ", ".join(parts))
            self._set_row(self.pay_period_table, row, [str(period.get("number") or ""), f"{period.get('start')} to {period.get('end')}", str(period.get("pay_date") or ""), "\n".join(summaries)])

    def _render_balances(self) -> None:
        balance = ((self.month_json.get("balance_as_of_today") or {}).get("balances") or {})
        use_or_lose = ((self.month_json.get("projected_balance") or {}).get("use_or_lose") or {})
        self.balance_table.setRowCount(0)
        for category, value in sorted(balance.items()):
            if not _nonzero(value):
                continue
            row = self.balance_table.rowCount()
            self.balance_table.insertRow(row)
            lose = use_or_lose.get("use_or_lose") if category == "annual" else None
            self._set_row(self.balance_table, row, [CATEGORY_LABELS.get(category, ("", category))[1], _fmt(value), _fmt(lose)])

    def _set_row(self, table: QTableWidget, row: int, values: list[str]) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, column, item)

    def edit_day(self, day: dict[str, Any]) -> None:
        dialog = DayEditDialog(day, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values:
            return
        if QMessageBox.question(self, "Confirm Authoritative Save", "Replace existing values for the supplied leave categories?") != QMessageBox.Yes:
            return
        try:
            self.backend.set_day(str(day["date"]), values)
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
        self.year = self.today.year
        self.month = self.today.month
        self.refresh()

    def preferences(self) -> None:
        dialog = PreferencesDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = dialog.apply()
            save_settings(self.settings)
            self.refresh()

    def new_leave_year(self) -> None:
        dialog = StartYearDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        if QMessageBox.question(self, "Create Leave Year", f"Create Leave Year {dialog.year.value()}?") != QMessageBox.Yes:
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
        self.year = dialog.year.value()
        self.month = 1
        self.refresh()

    def validate_data(self) -> None:
        try:
            payload = self.backend.validate()
        except BackendError as exc:
            QMessageBox.warning(self, "Validation Failed", str(exc))
            return
        QMessageBox.information(self, "Validate Data", "Data is valid." if payload.get("ok") else "Validation found issues.")

    def export_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Data", "fedleave_backup.json", "JSON files (*.json)")
        if not path:
            return
        try:
            self.backend.run_text(["export-data", "--output", path])
        except BackendError as exc:
            QMessageBox.warning(self, "Export Failed", str(exc))
            return
        QMessageBox.information(self, "Export Data", "Export complete.")

    def import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Data", "", "JSON files (*.json)")
        if not path:
            return
        try:
            self.backend.run_text(["import-data", "--input", path, "--overwrite"])
        except BackendError as exc:
            QMessageBox.warning(self, "Import Failed", str(exc))
            return
        self.refresh()

    def open_data_folder(self) -> None:
        if not self.settings.data_dir:
            QMessageBox.information(self, "Open Data Folder", "Set a custom data directory in Preferences first.")
            return
        webbrowser.open(Path(self.settings.data_dir).expanduser().as_uri())

    def _report_html(self) -> str:
        if not self.month_json:
            return "<h1>FedLeave Calendar</h1>"
        title = f"{calendar.month_name[self.month]} {self.year}"
        parts = [f"<h1>FedLeave Calendar - {html.escape(title)}</h1>", "<table border='1' cellspacing='0' cellpadding='4'>"]
        parts.append("<tr>" + "".join(f"<th>{day}</th>" for day in ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]) + "</tr>")
        days = list(self.month_json.get("days", []))
        for row in range(0, len(days), 7):
            parts.append("<tr>")
            for day in days[row : row + 7]:
                lines = html.escape(DayCell(day, self.settings).display_text()).replace("\n", "<br>")
                parts.append(f"<td valign='top' width='14%'>{lines}</td>")
            parts.append("</tr>")
        parts.append("</table><h2>Pay Periods</h2><ul>")
        for period in self.month_json.get("pay_periods", []):
            if period.get("touches_display_month"):
                parts.append(f"<li>PP {period.get('number')}: {period.get('start')} to {period.get('end')}</li>")
        parts.append("</ul><h2>As of Today</h2><ul>")
        for category, value in ((self.month_json.get("balance_as_of_today") or {}).get("balances") or {}).items():
            if _nonzero(value):
                parts.append(f"<li>{html.escape(CATEGORY_LABELS.get(category, ('', category))[1])}: {_fmt(value)}</li>")
        parts.append("</ul>")
        return "\n".join(parts)

    def _print_document(self, printer: QPrinter) -> None:
        document = QTextDocument()
        document.setHtml(self._report_html())
        document.print_(printer)

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

    def about_gui(self) -> None:
        self._show_html_file("about-fedleave-calendar.html", "About FedLeave Calendar")

    def _show_html_file(self, filename: str, title: str) -> None:
        path = _help_file(filename)
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        if path.exists():
            browser.setHtml(path.read_text(encoding="utf-8"))
        else:
            browser.setHtml(f"<h1>{html.escape(title)}</h1><p>Help file was not found.</p>")
        layout.addWidget(browser)
        dialog.exec()

    def show_abbreviations(self) -> None:
        rows = "\n".join(f"{short}: {label}" for short, label in CATEGORY_LABELS.values())
        QMessageBox.information(self, "Leave Abbreviations", rows)

    def about_backend(self) -> None:
        try:
            text = self.backend.run_text(["--version"])
        except BackendError:
            text = "fedleave backend version could not be read."
        QMessageBox.information(self, "About fedleave Backend", text.strip() or "fedleave backend")


def _monday_first(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [days[index : index + 7] for index in range(0, len(days), 7)]
    reordered: list[dict[str, Any]] = []
    for row in rows:
        if len(row) == 7:
            reordered.extend(row[1:] + row[:1])
        else:
            reordered.extend(row)
    return reordered


def _help_file(filename: str) -> Path:
    candidates = [
        Path(sys.argv[0]).resolve().parent / "help" / filename,
        Path(__file__).resolve().parents[1] / "help" / filename,
        Path.cwd() / "help" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
