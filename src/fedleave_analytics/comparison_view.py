"""Read-only cumulative usage view in the existing Analytics companion."""

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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fedleave.usage_comparison import ABSENCE_CATEGORIES, ALIGNMENTS, ComparisonParameters, compare_usage

from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, render_usage_comparison, table_widget
from .comparison_model import OBSERVATION_COLUMNS, TRANSACTION_COLUMNS, comparison_tables, export_csv
from .forecast_model import update_coverage
from .planning_model import export_destination
from .planning_view import _Task
from .preferences import load_preferences, save_preferences
from .seasonality import LABELS
from .snapshots import ReadOnlySnapshotSource


class ComparisonWidget(QWidget):
    source_loaded = Signal(object)
    progress_changed = Signal(int, str)

    def __init__(self, backend: Path, data_dir, year, pdf_folder="", *, today=None, parent=None):
        super().__init__(parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder, self.today = pdf_folder, today or date.today()
        self.snapshot, self.result, self.history = None, None, {}
        self.preferences, self._source_errors = {"coverage": [], "excluded_years": []}, []
        self._revision, self._closed, self._loading, self._updating = 0, False, False, False
        self._tasks, self._charts, self._views, self.tables, self._years = {}, [], {}, {}, []
        self._cancel_event = Event()
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
        self.alignment_combo, self.basis_combo = QComboBox(), QComboBox()
        for key, label in ALIGNMENTS.items():
            self.alignment_combo.addItem(label, key)
        self.basis_combo.addItem("All effective used statuses", "effective")
        self.basis_combo.addItem("Confirmed: worked/submitted/certified/reconciled", "confirmed")
        self.alignment_combo.currentIndexChanged.connect(self._changed)
        self.basis_combo.currentIndexChanged.connect(self._changed)
        self.category_button = QToolButton()
        self.category_button.setText("Categories: Annual Leave")
        self.category_button.setPopupMode(QToolButton.InstantPopup)
        menu, self.category_actions = QMenu(self), {}
        for category in ABSENCE_CATEGORIES:
            action = QAction(LABELS.get(category, category.title()), menu)
            action.setCheckable(True)
            action.setChecked(category == "annual")
            action.toggled.connect(self._categories_changed)
            menu.addAction(action)
            self.category_actions[category] = action
        self.category_button.setMenu(menu)
        self.category_button.setToolTip(
            "Choose one category or an explicit sum. Sick and purpose-restricted leave are included only when selected."
        )
        for column, (text, widget) in enumerate(
            (
                ("Cutoff", self.cutoff_edit),
                ("Alignment", self.alignment_combo),
                ("Recorded status basis", self.basis_combo),
                ("Absence categories", self.category_button),
            )
        ):
            label = QLabel(text)
            label.setBuddy(widget)
            form.addWidget(label, 0, column)
            form.addWidget(widget, 1, column)
        self.schedule_check = QCheckBox(
            "Normalize using the target's current schedule for all years (explicit analysis assumption)"
        )
        self.schedule_check.setToolTip(
            "Otherwise use backend-supplied historical rosters only; unavailable exposure gives N/A. Irregular historical rosters are not reconstructed."
        )
        self.schedule_check.toggled.connect(self._changed)
        form.addWidget(self.schedule_check, 2, 0, 1, 4)
        layout.addLayout(form)
        explanation = QLabel(
            "Recorded Through Cutoff sums effective absence, not balances or confirmed attendance. Confirm coverage from each year's start; unknown history stays N/A. Future target bookings are Scheduled. Double-click a value for its source years and transaction IDs."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        actions = QHBoxLayout()
        self.calculate_button = self._button(
            actions, "Calculate", self.recalculate, "Recalculate from cached read-only snapshots."
        )
        self._button(actions, "Cancel", self.cancel, "Discard the pending calculation; leave records are unchanged.")
        self._button(
            actions,
            "Open Chart",
            self.open_chart,
            "Open the exact chart and data with CSV, PNG, PDF and Print controls.",
        )
        self._button(
            actions,
            "Save Table as CSV...",
            self.save_csv,
            "Export the current exact table, cutoff, categories, alignment and assumptions.",
        )
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status_label = QLabel(
            "Select the target year and confirm complete historical coverage before comparing totals."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.splitter = QSplitter(Qt.Vertical)
        coverage = QWidget()
        coverage_layout = QVBoxLayout(coverage)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            [
                "Reference",
                "Exclude unusual",
                "Year",
                "Start",
                "End",
                "Confirmed periods",
                "Cutoff eligibility / limitation",
            ]
        )
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.itemChanged.connect(self._history_edited)
        self.history_table.currentCellChanged.connect(self._show_periods)
        self.period_table = table_widget(
            [], [("period_id", "Pay period"), ("start", "Start"), ("end", "End"), ("state", "Coverage")]
        )
        self.period_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.period_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.period_table.setMinimumHeight(65)
        self.history_table.setMinimumHeight(65)
        coverage_split = QSplitter(Qt.Horizontal)
        coverage_split.addWidget(self.history_table)
        coverage_split.addWidget(self.period_table)
        coverage_split.setSizes([850, 500])
        coverage_layout.addWidget(coverage_split)
        buttons = QHBoxLayout()
        self.coverage_buttons = [
            self._button(
                buttons,
                label,
                lambda _checked=False, yes=yes, whole=whole: self._confirm(yes, whole),
                "Store or revoke your assertion that the selected year/periods contain complete leave records. This does not modify leave data.",
            )
            for label, yes, whole in (
                ("Confirm whole year", True, True),
                ("Revoke whole year", False, True),
                ("Confirm selected periods", True, False),
                ("Revoke selected periods", False, False),
            )
        ]
        coverage_layout.addLayout(buttons)
        self.splitter.addWidget(coverage)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current comparison")
        scroll.setWidget(self.chart_image)
        self.splitter.addWidget(scroll)
        self.detail_tabs = QTabWidget()
        self.splitter.addWidget(self.detail_tabs)
        self.splitter.setSizes([190, 280, 200])
        layout.addWidget(self.splitter, 1)

    @staticmethod
    def _button(layout, text, callback, tooltip):
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _categories_changed(self):
        selected = [action.text() for action in self.category_actions.values() if action.isChecked()]
        self.category_button.setText(
            "Categories: " + (selected[0] if len(selected) == 1 else f"{len(selected)} selected")
        )
        self.category_button.setToolTip("Explicit sum: " + ", ".join(selected))
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
        self.snapshot, self.history, self._years = None, {}, []
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
        self.cancel()
        self.snapshot, self.history, self._years = None, {}, []
        self._updating = True
        self.history_table.setRowCount(0)
        self.period_table.setRowCount(0)
        self._updating = False
        self._loading = True
        self._set_enabled(False)
        self._cancel_event = Event()
        canceled, revision = self._cancel_event, self._revision + 1
        source, year = ReadOnlySnapshotSource(self.backend, self.data_dir), self.year

        def load():
            target = source.snapshot(year)
            history, errors = {}, []
            inventory = source.inventory()
            for index, row in enumerate(inventory, 1):
                if canceled.is_set():
                    raise RuntimeError("Canceled historical loading.")
                reference = row.get("leave_year") if isinstance(row, dict) else None
                if type(reference) is not int or reference == year:
                    continue
                self.progress_changed.emit(
                    revision, f"Loading read-only year {reference} ({index}/{len(inventory)})..."
                )
                try:
                    history[reference] = source.snapshot(reference)
                except (RuntimeError, ValueError, OSError) as exc:
                    errors.append({"code": "HISTORICAL_LOAD_FAILED", "message": str(exc), "year": reference})
            try:
                preferences = load_preferences(target)
            except ValueError as exc:
                preferences = {"coverage": [], "excluded_years": []}
                errors.append({"code": "PREFERENCES_UNAVAILABLE", "message": str(exc)})
            return target, history, preferences, errors

        self.status_label.setText("Loading the selected datastore and reference years read-only...")
        self._launch("load", load)

    def set_data(self, snapshot, history, preferences=None, errors=()):
        self._updating = True
        self.snapshot, self.history = deepcopy((snapshot, history))
        self.preferences = deepcopy(preferences or {"coverage": [], "excluded_years": []})
        self._source_errors = list(deepcopy(errors))
        self.year = snapshot["leave_year"]
        start, end = (QDate.fromString(snapshot[key], "yyyy-MM-dd") for key in ("leave_year_start", "leave_year_end"))
        self.cutoff_edit.setDateRange(start, end)
        self.cutoff_edit.setDate(min(max(QDate(self.today.year, self.today.month, self.today.day), start), end))
        self._years = [
            self.year,
            *sorted((set(history) | {e["year"] for e in errors if "year" in e}) - {self.year}, reverse=True),
        ]
        default = sorted(y for y, s in history.items() if s["leave_year_end"] < snapshot["leave_year_start"])[-5:]
        selected, excluded = (
            set(self.preferences.get("reference_years", default)),
            set(self.preferences.get("excluded_years", [])),
        )
        self.history_table.setRowCount(len(self._years))
        for i, year in enumerate(self._years):
            source = snapshot if year == self.year else history.get(year, {})
            for column, checked in ((0, year in selected), (1, year in excluded)):
                item = QTableWidgetItem("Target" if year == self.year and column == 0 else "")
                item.setFlags(
                    Qt.ItemIsEnabled
                    | Qt.ItemIsSelectable
                    | (Qt.ItemIsUserCheckable if year != self.year else Qt.NoItemFlags)
                )
                if year != self.year:
                    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.history_table.setItem(i, column, item)
            for column, value in enumerate(
                (
                    year,
                    source.get("leave_year_start", "N/A"),
                    source.get("leave_year_end", "N/A"),
                    "Checking...",
                    "Unconfirmed coverage is missing, not zero.",
                ),
                2,
            ):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.history_table.setItem(i, column, item)
        self.history_table.resizeColumnsToContents()
        self._updating, self._loading = False, False
        self.history_table.setCurrentCell(0, 2)
        self._set_enabled(True)
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _parameters(self):
        return ComparisonParameters(
            self.cutoff_edit.date().toString("yyyy-MM-dd"),
            tuple(category for category, action in self.category_actions.items() if action.isChecked()),
            tuple(
                year
                for i, year in enumerate(self._years)
                if year != self.year and self.history_table.item(i, 0).checkState() == Qt.Checked
            ),
            tuple(
                year
                for i, year in enumerate(self._years)
                if year != self.year and self.history_table.item(i, 1).checkState() == Qt.Checked
            ),
            self.alignment_combo.currentData(),
            self.basis_combo.currentData(),
            self.schedule_check.isChecked(),
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
        if self.snapshot is not None:
            self.status_label.setText("Calculating from cached read-only snapshots...")
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
            result = compare_usage(snapshot, history, coverage, parameters, today=today)
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
            if self._save_preferences(value):
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
            self.status_label.setText("Comparison unavailable: " + "; ".join(row["message"] for row in errors))

    def _render_result(self):
        current = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        self._views = comparison_tables(self.result)
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
            if title in {"Summary", "Daily alignment", "Year details"}:
                table.cellActivated.connect(lambda row, column, title=title: self.drilldown(title, row, column))
            if title == current:
                self.detail_tabs.setCurrentWidget(table)
        self.chart_image.set_source_pixmap(render_usage_comparison(self.result))
        metadata = {row["year"]: row for row in self.result.history}
        self._updating = True
        for i, year in enumerate(self._years):
            row = metadata.get(year, {})
            periods = row.get("periods", [])
            self.history_table.item(i, 5).setText(f"{sum(p['confirmed'] for p in periods)} / {len(periods)}")
            cutoff = row.get("aligned_cutoff")
            observation = next(
                (
                    o
                    for o in self.result.observations
                    if o["year"] == year and o["date"] == self.result.parameters.cutoff
                ),
                {},
            )
            reason = row.get("exclusion_reason") or observation.get("missing_reason")
            self.history_table.item(i, 6).setText(
                reason or (f"Eligible through {cutoff}" if cutoff else "No exact aligned cutoff")
            )
        self._updating = False
        self._show_periods()
        summary = self.result.summary
        categories = ", ".join(self.result.parameters.categories)

        def value(key):
            number = summary.get(key)
            return "N/A" if number is None else f"{number:.6g}"

        self.status_label.setText(
            f"Recorded {value('recorded')} h | Median {value('median')} h | Difference {value('difference')} h "
            f"({value('percentage_difference')}%) | Reference count {summary['observation_count']}. "
            f"{ALIGNMENTS[self.result.parameters.alignment]} | {categories} | {summary['history_label']}. "
            + (summary.get("target_missing_reason") or "")
            + f" Warnings: {len(self.result.warnings)}. Review coverage and schedule assumptions in the tables."
        )

    def _selected_year(self):
        index = self.history_table.currentRow()
        return self._years[index] if 0 <= index < len(self._years) else None

    def _show_periods(self, *_args):
        if self._updating:
            return
        year = self._selected_year()
        self.coverage_buttons[0].setText("Confirm through cutoff" if year == self.year else "Confirm whole year")
        metadata = next((row for row in self.result.history if row["year"] == year), {}) if self.result else {}
        periods = metadata.get("periods", [])
        sorting = self.period_table.isSortingEnabled()
        self.period_table.setSortingEnabled(False)
        self.period_table.setRowCount(len(periods))
        for i, period in enumerate(periods):
            for column, key in enumerate(("period_id", "start", "end", "state")):
                item = QTableWidgetItem(str(period[key]))
                if key == "period_id":
                    item.setData(Qt.DisplayRole, int(period[key]))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.period_table.setItem(i, column, item)
        self.period_table.setSortingEnabled(sorting)

    def _save_preferences(self, candidate):
        try:
            save_preferences(self.snapshot, candidate)
        except (OSError, ValueError) as exc:
            self.status_label.setText(f"Analytics preferences were not changed: {exc}")
            return False
        self.preferences = deepcopy(candidate)
        return True

    def _history_edited(self, item):
        if self._updating or item.column() not in (0, 1):
            return
        parameters = self._parameters()
        candidate = {
            **self.preferences,
            "reference_years": list(parameters.reference_years),
            "excluded_years": list(parameters.excluded_years),
        }
        if self._save_preferences(candidate):
            self._changed()
        else:
            self._updating = True
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            self._updating = False

    def _confirm(self, confirmed, whole):
        year = self._selected_year()
        snapshot = self.snapshot if year == self.year else self.history.get(year)
        if snapshot is None:
            self.status_label.setText("Select a loaded year first.")
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
            self.status_label.setText("Select the pay periods whose coverage you intend to change.")
            return
        snapshot, preferences = deepcopy((snapshot, self.preferences))
        through = self.cutoff_edit.date().toString("yyyy-MM-dd") if confirmed and year == self.year else None
        self._launch(
            "coverage",
            lambda: update_coverage(preferences, snapshot, periods, confirmed=confirmed, strict=False, through=through),
        )

    def _dialog(self, title, rows, columns, callback=None):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(1150, 520)
        layout = QVBoxLayout(dialog)
        table = table_widget(rows, columns)
        layout.addWidget(table)
        if callback:
            table.cellActivated.connect(lambda r, c: callback(rows[table.item(r, 0).data(Qt.UserRole + 1)]))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _transactions(self, observation):
        ids = set(observation.get("transaction_ids", []))
        rows = [
            row for row in self.result.transactions if row["source_year"] == observation["year"] and row["id"] in ids
        ]
        self._dialog(
            f"Known included transactions — {observation['year']} through {observation.get('mapped_date') or 'N/A'}",
            rows,
            TRANSACTION_COLUMNS,
        )

    def drilldown(self, title, displayed_row, column):
        if self.result is None:
            return
        table = self.tables[title]
        index = table.item(displayed_row, 0).data(Qt.UserRole + 1)
        row, columns = self._views[title][0][index], self._views[title][1]
        if title == "Year details":
            self._transactions(row)
            return
        key, day = columns[column][0], row["date"]
        observations = [o for o in self.result.observations if o["date"] == day]
        if key.startswith("reference_"):
            self._transactions(next(o for o in observations if o["year"] == int(key.removeprefix("reference_"))))
        elif key in {"recorded", "scheduled", "hours_per_100"}:
            self._transactions(next(o for o in observations if o["role"] == "Target"))
        else:
            self._dialog(
                f"Contributing year totals — {day}; median/range are derived statistics",
                [o for o in observations if o["role"] == "Reference"],
                OBSERVATION_COLUMNS,
                self._transactions,
            )

    def _export(self, snapshot, result, title, rows=None, columns=None):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Usage Comparison Table",
            str(Path(self.pdf_folder or ".") / f"fedleave-usage-comparison-{result.source['leave_year']}.csv"),
            "CSV files (*.csv)",
        )
        if path:
            try:
                export_csv(Path(path), snapshot, result, title, rows, columns)
            except (OSError, ValueError) as exc:
                self.status_label.setText(str(exc))

    def save_csv(self):
        title = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        if self.result is not None and title in self._views:
            self._export(self.snapshot, self.result, title)

    def open_chart(self):
        if self.result is None:
            return
        snapshot, result = deepcopy((self.snapshot, self.result))
        rows, columns = comparison_tables(result)["Daily alignment"]
        chart = AnalyticsChartWindow(
            "Cumulative Usage Comparison",
            self.chart_image.source_pixmap(),
            rows,
            columns,
            self.pdf_folder,
            f"fedleave-usage-comparison-{self.year}",
            csv_export=lambda: self._export(snapshot, result, "Daily alignment"),
            export_target=lambda path: export_destination(Path(path), snapshot),
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda: self._charts.remove(chart) if chart in self._charts else None)
        chart.show()

    def _set_enabled(self, enabled):
        for widget in (
            self.cutoff_edit,
            self.alignment_combo,
            self.basis_combo,
            self.category_button,
            self.schedule_check,
            self.history_table,
            self.period_table,
            self.calculate_button,
            *self.coverage_buttons,
        ):
            widget.setEnabled(enabled)

    def cancel(self):
        self._revision += 1
        self._timer.stop()
        self._cancel_event.set()
        self._loading = False
        self.progress.hide()
        self._set_enabled(True)
        self._clear_result()
        self.status_label.setText("Canceled. Leave records are unchanged.")

    def shutdown(self):
        self.cancel()
        self._closed = True
        for chart in list(self._charts):
            chart.close()
