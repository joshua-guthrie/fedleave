"""Break Patterns inside the existing read-only Analytics companion."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Event

from PySide6.QtCore import QDate, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fedleave.break_patterns import GROUPS, BreakParameters, analyze_breaks
from fedleave.usage_comparison import ABSENCE_CATEGORIES

from .break_charts import render_break_distribution, render_break_timeline
from .break_model import DAY_COLUMNS, INTERVAL_COLUMNS, TRANSACTION_COLUMNS, break_tables, export_csv, group_label
from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, table_widget
from .forecast_model import update_coverage
from .planning_model import export_destination
from .planning_view import _Task
from .preferences import load_preferences, save_preferences
from .seasonality import LABELS
from .snapshots import ReadOnlySnapshotSource


class BreakPatternsWidget(QWidget):
    source_loaded = Signal(object)
    progress_changed = Signal(int, str)

    def __init__(self, backend: Path, data_dir, year, pdf_folder="", *, today=None, parent=None):
        super().__init__(parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder, self.today = pdf_folder, today or date.today()
        self.snapshot, self.result, self.history = None, None, {}
        self.preferences, self._source_errors = {"coverage": [], "excluded_years": []}, []
        self._revision, self._loading, self._closed, self._updating = 0, False, False, False
        self._tasks, self._charts, self._views, self.tables, self._years = {}, [], {}, {}, []
        self._chosen_years, self._chosen_cutoff, self._cancel_event = None, None, Event()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.recalculate)
        self.progress_changed.connect(self._progress)
        self._build_ui()

    def _build_ui(self):
        layout, form = QVBoxLayout(self), QGridLayout()
        self.cutoff_edit = QDateEdit()
        self.cutoff_edit.setDisplayFormat("yyyy-MM-dd")
        self.cutoff_edit.setCalendarPopup(True)
        self.cutoff_edit.dateChanged.connect(self._changed)
        self.group_combo, self.basis_combo, self.chart_combo = QComboBox(), QComboBox(), QComboBox()
        for key, (label, _) in GROUPS.items():
            self.group_combo.addItem(label, key)
        self.group_combo.addItem("Custom selected absence", "custom")
        self.group_combo.currentIndexChanged.connect(self._group_changed)
        self.basis_combo.addItem("All effective used statuses", "effective")
        self.basis_combo.addItem("Confirmed recorded statuses only", "confirmed")
        self.basis_combo.setToolTip(
            "Confirmed means worked/submitted/certified/reconciled. Future effective bookings remain Scheduled."
        )
        self.basis_combo.currentIndexChanged.connect(self._changed)
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 366)
        self.threshold_spin.setValue(3)
        self.threshold_spin.setSuffix(" fully absent workdays")
        self.threshold_spin.setToolTip(
            "A user-selected analysis threshold within one consecutive calendar interval; not an employment rule."
        )
        self.threshold_spin.valueChanged.connect(self._changed)
        self.category_button = QToolButton()
        self.category_button.setPopupMode(QToolButton.InstantPopup)
        self.category_button.setText("Custom categories...")
        menu, self.category_actions = QMenu(self), {}
        for category in ABSENCE_CATEGORIES:
            action = QAction(LABELS.get(category, category.title()), menu)
            action.setCheckable(True)
            action.setChecked(category == "annual")
            action.toggled.connect(self._changed)
            menu.addAction(action)
            self.category_actions[category] = action
        self.category_button.setMenu(menu)
        for column, (text, widget) in enumerate(
            (
                ("Cutoff", self.cutoff_edit),
                ("Grouping", self.group_combo),
                ("Substantial break", self.threshold_spin),
                ("Custom grouping", self.category_button),
            )
        ):
            label = QLabel(text)
            label.setBuddy(widget)
            form.addWidget(label, 0, column)
            form.addWidget(widget, 1, column)
        self.schedule_check = QCheckBox(
            "Use the current regular schedule where historical rosters are unavailable (analysis assumption)"
        )
        self.schedule_check.setChecked(True)
        self.schedule_check.setToolTip(
            "Configured workdays and tour minus lunch apply to earlier years only as an explicit analysis assumption. Irregular rosters are not reconstructed."
        )
        self.schedule_check.toggled.connect(self._changed)
        form.addWidget(self.schedule_check, 2, 0, 1, 3)
        form.addWidget(self.basis_combo, 2, 3)
        layout.addLayout(form)
        self.definition_label = QLabel()
        self.definition_label.setWordWrap(True)
        layout.addWidget(self.definition_label)
        actions = QHBoxLayout()
        self.calculate_button = self._button(
            actions, "Calculate", self.recalculate, "Recalculate from cached read-only year snapshots."
        )
        self._button(actions, "Cancel", self.cancel, "Discard pending work; leave records are unchanged.")
        self.chart_combo.addItems(["Break-length distribution", "Break timeline"])
        self.chart_combo.currentIndexChanged.connect(self._render_chart)
        actions.addWidget(self.chart_combo)
        self._button(
            actions,
            "Open Chart",
            self.open_chart,
            "Open this chart with its exact table and CSV, PNG, PDF and Print actions.",
        )
        self._button(
            actions,
            "Save Table as CSV...",
            self.save_csv,
            "Export the selected exact table with categories, cutoff, coverage and assumptions.",
        )
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status_label = QLabel("Select covered years to analyze recorded breaks; future bookings remain Scheduled.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.splitter = QSplitter(Qt.Vertical)
        coverage = QWidget()
        coverage_layout = QVBoxLayout(coverage)
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(
            ["Analyze", "Year", "Start", "End", "Coverage periods", "Coverage / assumption"]
        )
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.itemChanged.connect(self._years_changed)
        self.history_table.currentCellChanged.connect(self._show_periods)
        self.history_table.setMinimumHeight(70)
        self.period_table = table_widget(
            [], [("period_id", "Pay period"), ("start", "Start"), ("end", "End"), ("state", "Coverage")]
        )
        self.period_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.period_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.period_table.setMinimumHeight(70)
        coverage_split = QSplitter(Qt.Horizontal)
        coverage_split.addWidget(self.history_table)
        coverage_split.addWidget(self.period_table)
        coverage_split.setSizes([800, 500])
        coverage_layout.addWidget(coverage_split)
        buttons = QHBoxLayout()
        self.coverage_buttons = [
            self._button(
                buttons,
                text,
                lambda _checked=False, yes=yes, whole=whole: self._confirm(yes, whole),
                "Confirm only complete usage history. Assertions stop at cutoff and are saved outside leave records; unknown history is never zero.",
            )
            for text, yes, whole in (
                ("Confirm through cutoff", True, True),
                ("Revoke whole year", False, True),
                ("Confirm selected periods", True, False),
                ("Revoke selected periods", False, False),
            )
        ]
        coverage_layout.addLayout(buttons)
        self.splitter.addWidget(coverage)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current break analysis")
        scroll.setWidget(self.chart_image)
        self.splitter.addWidget(scroll)
        self.detail_tabs = QTabWidget()
        self.splitter.addWidget(self.detail_tabs)
        self.splitter.setSizes([180, 280, 200])
        layout.addWidget(self.splitter, 1)
        self._group_changed()

    @staticmethod
    def _button(layout, label, callback, tooltip):
        button = QPushButton(label)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _group_changed(self, *_args):
        self.category_button.setEnabled(self.group_combo.currentData() == "custom")
        self._changed()

    def activate(self):
        if self.snapshot is None and not self._loading:
            self.load_source()

    def set_source(self, backend, data_dir, year):
        if (backend, data_dir, year) == (self.backend, self.data_dir, self.year):
            return
        self.cancel()
        for chart in list(self._charts):
            chart.close()
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.snapshot, self.history, self._years, self._chosen_years, self._chosen_cutoff = None, {}, [], None, None
        self.history_table.setRowCount(0)
        self.period_table.setRowCount(0)

    def _launch(self, kind, function):
        self._revision += 1
        task = _Task(self._revision, kind, function)
        self._tasks[self._revision] = task
        task.signals.finished.connect(self._finished)
        task.signals.failed.connect(self._failed)
        self.progress.show()
        QThreadPool.globalInstance().start(task)

    @Slot(int, str)
    def _progress(self, revision, message):
        if revision == self._revision and not self._closed:
            self.status_label.setText(message)

    def load_source(self):
        if self.snapshot is not None:
            self._chosen_cutoff = self.cutoff_edit.date().toString("yyyy-MM-dd")
        self.cancel()
        self.snapshot, self.history, self._years = None, {}, []
        self._updating = True
        self.history_table.setRowCount(0)
        self.period_table.setRowCount(0)
        self._updating, self._loading = False, True
        self._set_enabled(False)
        self._cancel_event = Event()
        canceled, revision = self._cancel_event, self._revision + 1
        source, year = ReadOnlySnapshotSource(self.backend, self.data_dir), self.year

        def load():
            anchor = source.snapshot(year)
            history, errors = {}, []
            inventory = source.inventory()
            for index, row in enumerate(inventory, 1):
                if canceled.is_set():
                    raise RuntimeError("Canceled year loading.")
                reference = row.get("leave_year") if isinstance(row, dict) else None
                if type(reference) is not int or reference == year:
                    continue
                self.progress_changed.emit(
                    revision, f"Loading year {reference} read-only ({index}/{len(inventory)})..."
                )
                try:
                    history[reference] = source.snapshot(reference)
                except (RuntimeError, ValueError, OSError) as exc:
                    errors.append({"code": "YEAR_LOAD_FAILED", "message": str(exc), "year": reference})
            try:
                preferences = load_preferences(anchor)
            except ValueError as exc:
                preferences = {"coverage": [], "excluded_years": []}
                errors.append({"code": "PREFERENCES_UNAVAILABLE", "message": str(exc)})
            return anchor, history, preferences, errors

        self.status_label.setText("Loading selected backend years and schedule context read-only...")
        self._launch("load", load)

    def set_data(self, snapshot, history, preferences=None, errors=()):
        self._updating = True
        self.snapshot, self.history = deepcopy((snapshot, history))
        self.preferences = deepcopy(preferences or {"coverage": [], "excluded_years": []})
        self._source_errors = deepcopy(list(errors))
        self.year = snapshot["leave_year"]
        self._years = [
            self.year,
            *sorted((set(history) | {row["year"] for row in errors if "year" in row}) - {self.year}, reverse=True),
        ]
        chosen = self._chosen_years if self._chosen_years is not None else (self.year,)
        self.history_table.setRowCount(len(self._years))
        for i, year in enumerate(self._years):
            source = snapshot if year == self.year else history.get(year, {})
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if year in chosen else Qt.Unchecked)
            self.history_table.setItem(i, 0, item)
            for column, value in enumerate(
                (
                    year,
                    source.get("leave_year_start", "N/A"),
                    source.get("leave_year_end", "N/A"),
                    "Checking...",
                    "Unknown coverage remains N/A.",
                ),
                1,
            ):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.history_table.setItem(i, column, item)
        self._set_cutoff_bounds()
        start, end = self.cutoff_edit.minimumDate(), self.cutoff_edit.maximumDate()
        chosen = (
            QDate.fromString(self._chosen_cutoff, "yyyy-MM-dd")
            if self._chosen_cutoff
            else QDate(self.today.year, self.today.month, self.today.day)
        )
        self.cutoff_edit.setDate(min(max(chosen, start), end))
        self.history_table.resizeColumnsToContents()
        self._updating, self._loading = False, False
        self._set_enabled(True)
        self.history_table.setCurrentCell(0, 1)
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _set_cutoff_bounds(self):
        if self.snapshot is None:
            return
        selected = [
            self.snapshot if year == self.year else self.history.get(year)
            for i, year in enumerate(self._years)
            if self.history_table.item(i, 0).checkState() == Qt.Checked
        ]
        selected = [source for source in selected if source]
        if selected:
            start = min(source["leave_year_start"] for source in selected)
            end = max(source["leave_year_end"] for source in selected)
            self.cutoff_edit.setDateRange(QDate.fromString(start, "yyyy-MM-dd"), QDate.fromString(end, "yyyy-MM-dd"))

    def _years_changed(self, item):
        if self._updating or item.column() != 0:
            return
        self._chosen_years = tuple(
            year for i, year in enumerate(self._years) if self.history_table.item(i, 0).checkState() == Qt.Checked
        )
        self._updating = True
        self._set_cutoff_bounds()
        self._updating = False
        self._changed()

    def _parameters(self):
        return BreakParameters(
            self.cutoff_edit.date().toString("yyyy-MM-dd"),
            tuple(
                year for i, year in enumerate(self._years) if self.history_table.item(i, 0).checkState() == Qt.Checked
            ),
            self.group_combo.currentData(),
            tuple(category for category, action in self.category_actions.items() if action.isChecked())
            if self.group_combo.currentData() == "custom"
            else (),
            self.threshold_spin.value(),
            self.schedule_check.isChecked(),
            self.basis_combo.currentData(),
        )

    def _clear_result(self):
        self.result, self._views = None, {}
        self.chart_image.set_source_pixmap(QPixmap())
        self.chart_image.clear()
        for table in self.tables.values():
            table.setRowCount(0)

    def _changed(self, *_args):
        if self._updating or self._closed:
            return
        self._revision += 1
        self._clear_result()
        parameters = self._parameters()
        selected = GROUPS[parameters.grouping][1] if parameters.grouping in GROUPS else parameters.categories
        self.definition_label.setText(
            f"{group_label(parameters)}: {', '.join(LABELS.get(category, category) for category in selected) or 'select categories'}. Substantial means at least {parameters.substantial_workdays} fully absent scheduled workdays in one calendar interval. This is an analysis threshold, not an employment rule. Recorded dates do not establish attendance; future bookings remain Scheduled."
        )
        if self.snapshot is not None:
            self._chosen_cutoff = self.cutoff_edit.date().toString("yyyy-MM-dd")
            self._timer.start()

    def recalculate(self):
        if self.snapshot is None or self._closed or self._updating:
            return
        self._timer.stop()
        self._clear_result()
        parameters = self._parameters()
        snapshot, history, coverage, errors, today = deepcopy(
            (self.snapshot, self.history, self.preferences.get("coverage", []), self._source_errors, self.today)
        )

        def calculate():
            result = analyze_breaks(snapshot, history, coverage, parameters, today=today)
            return replace(result, warnings=(*result.warnings, *errors))

        self._launch("calculate", calculate)

    @Slot(int, str, object)
    def _finished(self, revision, kind, value):
        self._tasks.pop(revision, None)
        if revision != self._revision or self._closed:
            return
        self.progress.hide()
        self._loading = False
        self._set_enabled(True)
        if kind == "load":
            self.set_data(*value)
        elif kind == "coverage":
            try:
                save_preferences(self.snapshot, value)
            except (OSError, ValueError) as exc:
                self.status_label.setText(f"Coverage preferences were not changed: {exc}")
            else:
                self.preferences = deepcopy(value)
                self._changed()
        else:
            self.result = value
            self._render_result()

    @Slot(int, str, object)
    def _failed(self, revision, kind, errors):
        self._tasks.pop(revision, None)
        if revision == self._revision and not self._closed:
            self._loading = False
            self._set_enabled(True)
            self.progress.hide()
            self.status_label.setText("Break Patterns unavailable: " + "; ".join(row["message"] for row in errors))

    def _render_result(self):
        current = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        self._views = break_tables(self.result)
        for title, (rows, columns) in self._views.items():
            table = table_widget(rows, columns)
            old = self.tables.get(title)
            if old is not None:
                index = self.detail_tabs.indexOf(old)
                self.detail_tabs.removeTab(index)
                self.detail_tabs.insertTab(index, table, title)
                old.deleteLater()
            else:
                self.detail_tabs.addTab(table, title)
            self.tables[title] = table
            if title in {"Recorded breaks", "Upcoming breaks", "Daily classification", "Scheduled workday gaps"}:
                table.cellActivated.connect(lambda row, column, title=title: self.drilldown(title, row))
            if title == current:
                self.detail_tabs.setCurrentWidget(table)
        self._render_chart()
        metadata = {row["year"]: row for row in self.result.coverage}
        self._updating = True
        for i, year in enumerate(self._years):
            context = metadata.get(year, {})
            periods = context.get("periods", [])
            complete = sum(period["confirmed"] for period in periods)
            partial = sum(period["state"].startswith("Confirmed through") for period in periods)
            self.history_table.item(i, 4).setText(
                f"{complete} full + {partial} partial / {len(periods)}" if partial else f"{complete} / {len(periods)}"
            )
            self.history_table.item(i, 5).setText(
                context.get("schedule_basis")
                or next((error["message"] for error in self._source_errors if error.get("year") == year), "Unavailable")
            )
            self.history_table.item(i, 5).setToolTip(self.history_table.item(i, 5).text())
        self._updating = False
        self._show_periods()
        summary = self.result.summary

        def value(key):
            number = summary[key]
            return "N/A" if number is None else f"{number:g}"

        since = (
            summary["time_since_status"]
            if summary["calendar_days_since"] is None
            else f"{summary['calendar_days_since']} calendar days / {summary['scheduled_workdays_since']} scheduled workdays since {summary['last_completed_break_end']}"
        )
        self.status_label.setText(
            f"Full / partial absent scheduled workdays: {value('fully_absent_workdays')} / {value('partially_absent_workdays')}; observed substantial breaks: {value('qualifying_break_count')}. {since}. Unknown recorded dates: {summary['unknown_recorded_days']}. Review boundaries, assumptions and {len(self.result.warnings)} warnings."
        )

    def _render_chart(self, *_args):
        if self.result is None:
            return
        self.chart_image.set_source_pixmap(
            render_break_distribution(self.result)
            if self.chart_combo.currentIndex() == 0
            else render_break_timeline(self.result)
        )

    def _selected_year(self):
        index = self.history_table.currentRow()
        return self._years[index] if 0 <= index < len(self._years) else None

    def _show_periods(self, *_args):
        if self._updating:
            return
        year = self._selected_year()
        context = next((row for row in self.result.coverage if row["year"] == year), {}) if self.result else {}
        periods = context.get("periods", [])
        sorting = self.period_table.isSortingEnabled()
        self.period_table.setSortingEnabled(False)
        self.period_table.setRowCount(len(periods))
        for i, period in enumerate(periods):
            for column, key in enumerate(("period_id", "start", "end", "state")):
                item = QTableWidgetItem(str(period[key]))
                item.setToolTip(str(period[key]))
                if key == "period_id":
                    item.setData(Qt.DisplayRole, int(period[key]))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.period_table.setItem(i, column, item)
        self.period_table.setSortingEnabled(sorting)

    def _confirm(self, confirmed, whole):
        year = self._selected_year()
        snapshot = self.snapshot if year == self.year else self.history.get(year)
        if snapshot is None:
            self.status_label.setText("Select a loaded year first.")
            return
        cutoff = self.cutoff_edit.date().toString("yyyy-MM-dd")
        if confirmed and snapshot["leave_year_start"] > cutoff:
            self.status_label.setText("Dates after cutoff remain Scheduled; future recorded coverage is not confirmed.")
            return
        periods = (
            None
            if whole
            else [
                self.period_table.item(index.row(), 0).text()
                for index in self.period_table.selectionModel().selectedRows()
            ]
        )
        if periods == []:
            self.status_label.setText("Select the periods whose complete usage coverage you intend to change.")
            return
        through = cutoff if confirmed and cutoff < snapshot["leave_year_end"] else None
        snapshot, preferences = deepcopy((snapshot, self.preferences))
        self._launch(
            "coverage",
            lambda: update_coverage(preferences, snapshot, periods, confirmed=confirmed, strict=False, through=through),
        )

    def drilldown(self, title, displayed_row):
        if self.result is None:
            return
        index = self.tables[title].item(displayed_row, 0).data(Qt.UserRole + 1)
        row = self._views[title][0][index]
        if title == "Daily classification":
            dates = {row["date"]}
        else:
            dates = {day["date"] for day in self.result.daily if row["start"] <= day["date"] <= row["end"]}
        daily = [day for day in self.result.daily if day["date"] in dates]
        entries = [entry for entry in self.result.transactions if entry["date"] in dates]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Break details — {min(dates)} through {max(dates)}")
        dialog.resize(1150, 650)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        tabs.addTab(table_widget(daily, DAY_COLUMNS), "Daily classification and assumptions")
        tabs.addTab(table_widget(entries, TRANSACTION_COLUMNS), "Original transactions")
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _export(self, snapshot, result, title, rows=None, columns=None):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Break Patterns Table",
            str(Path(self.pdf_folder or ".") / f"fedleave-break-patterns-{self.year}.csv"),
            "CSV files (*.csv)",
        )
        if path:
            try:
                export_csv(Path(path), snapshot, result, title, rows, columns)
            except (ValueError, OSError) as exc:
                self.status_label.setText(str(exc))

    def save_csv(self):
        title = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        if self.result is not None and title in self._views:
            self._export(self.snapshot, self.result, title)

    def open_chart(self):
        if self.result is None:
            return
        snapshot, result = deepcopy((self.snapshot, self.result))
        if self.chart_combo.currentIndex() == 0:
            title = "Break-length distribution"
            rows, columns = break_tables(result)[title]
        else:
            title = "Break timeline"
            rows, columns = [*result.recorded, *result.upcoming], INTERVAL_COLUMNS
        chart = AnalyticsChartWindow(
            title,
            self.chart_image.source_pixmap(),
            rows,
            columns,
            self.pdf_folder,
            f"fedleave-break-patterns-{self.year}",
            csv_export=lambda: self._export(snapshot, result, title, rows, columns),
            export_target=lambda path: export_destination(Path(path), snapshot),
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda: self._charts.remove(chart) if chart in self._charts else None)
        chart.show()

    def _set_enabled(self, enabled):
        for widget in (
            self.cutoff_edit,
            self.group_combo,
            self.basis_combo,
            self.threshold_spin,
            self.schedule_check,
            self.history_table,
            self.period_table,
            self.calculate_button,
            *self.coverage_buttons,
        ):
            widget.setEnabled(enabled)
        self.category_button.setEnabled(enabled and self.group_combo.currentData() == "custom")

    def cancel(self):
        self._revision += 1
        self._timer.stop()
        self._cancel_event.set()
        self._loading = False
        self.progress.hide()
        self._set_enabled(True)
        self._clear_result()
        self.status_label.setText("Canceled. No leave records changed.")

    def shutdown(self):
        self.cancel()
        self._closed = True
        for chart in list(self._charts):
            chart.close()
