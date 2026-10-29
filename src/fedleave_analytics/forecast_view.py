"""Usage Forecast in the existing Analytics companion; no ledger mutation UI."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Event

from PySide6.QtCore import QDate, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fedleave.forecast import ForecastParameters, forecast, retrospective_check

from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, render_forecast_chart, table_widget
from .forecast_model import DAILY_COLUMNS, export_csv, forecast_tables, update_coverage
from .planning_model import export_destination, write_export
from .planning_view import _Task
from .preferences import load_preferences, save_preferences
from .snapshots import ReadOnlySnapshotSource


class ForecastWidget(QWidget):
    source_loaded = Signal(object)
    result_changed = Signal()

    def __init__(self, backend: Path, data_dir, year, pdf_folder="", *, today=None, parent=None):
        super().__init__(parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder, self.today = pdf_folder, today or date.today()
        self.snapshot, self.result, self.retrospective = None, None, None
        self.history, self.preferences, self._source_errors = {}, {"coverage": [], "excluded_years": []}, []
        self._revision, self._closed, self._updating, self._loading = 0, False, False, False
        self._tasks, self._charts, self._views, self._history_years = {}, [], {}, []
        self._cancel_event = Event()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.recalculate)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QGridLayout()
        self.cutoff_edit, self.horizon_edit = QDateEdit(), QDateEdit()
        for edit in (self.cutoff_edit, self.horizon_edit):
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setCalendarPopup(True)
            edit.dateChanged.connect(self._changed)
        self.scope_combo = QComboBox()
        for label, categories in (
            ("Annual only", ("annual",)),
            ("Sick only", ("sick",)),
            ("Annual and sick (shared capacity)", ("annual", "sick")),
        ):
            self.scope_combo.addItem(label, categories)
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        self.category_combo = QComboBox()
        self.category_combo.addItem("Annual leave", "annual")
        self.category_combo.currentIndexChanged.connect(self._render_result)
        self.basis_combo = QComboBox()
        self.basis_combo.addItem("All effective used statuses", "effective")
        self.basis_combo.addItem("Confirmed: worked/submitted/certified/reconciled", "confirmed")
        self.basis_combo.currentIndexChanged.connect(self._changed)
        for column, (label, widget) in enumerate(
            (
                ("Cutoff", self.cutoff_edit),
                ("Horizon", self.horizon_edit),
                ("Forecast scope", self.scope_combo),
                ("Chart category", self.category_combo),
            )
        ):
            caption = QLabel(label)
            caption.setBuddy(widget)
            form.addWidget(caption, 0, column)
            form.addWidget(widget, 1, column)
        form.addWidget(QLabel("Historical status basis"), 2, 0)
        form.addWidget(self.basis_combo, 2, 1, 1, 2)
        reserve_layout = QHBoxLayout()
        self.reserves = {}
        for category in ("annual", "sick"):
            label = QLabel(f"{category.title()} reserve")
            edit = QLineEdit()
            edit.setPlaceholderText("Optional hours")
            edit.setMaximumWidth(110)
            edit.textChanged.connect(self._changed)
            label.setBuddy(edit)
            reserve_layout.addWidget(label)
            reserve_layout.addWidget(edit)
            self.reserves[category] = edit
        form.addLayout(reserve_layout, 2, 3)
        layout.addLayout(form)
        explanation = QLabel(
            "Usage Forecast is a read-only planning and analysis feature. It does not create, modify, or delete leave transactions. "
            "Forecast calculations use isolated in-memory data, and historical coverage preferences are stored separately from leave records. "
            "Confirm only years or pay periods whose leave records you consider complete."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        actions = QHBoxLayout()
        self.calculate_button = self._button(actions, "Calculate", self.recalculate)
        self.cancel_button = self._button(actions, "Cancel", self.cancel)
        self._button(actions, "Open Chart", self.open_chart)
        self._button(actions, "Save Table as CSV...", self.save_csv)
        self._button(actions, "Export Results JSON...", self.export_json)
        layout.addLayout(actions)
        self.status_label = QLabel(
            "Load the selected leave year to calculate Scheduled; estimates require confirmed history."
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
            ["Reference", "Exclude unusual", "Year", "Start", "End", "Confirmed periods", "Eligibility / limitations"]
        )
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.history_table.itemChanged.connect(self._history_edited)
        self.history_table.currentCellChanged.connect(self._show_periods)
        coverage_tables = QSplitter(Qt.Horizontal)
        coverage_tables.addWidget(self.history_table)
        self.period_table = table_widget(
            [], [("period_id", "Pay period"), ("start", "Start"), ("end", "End"), ("state", "Coverage")]
        )
        self.period_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.period_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.period_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.period_table.setMinimumHeight(90)
        coverage_tables.addWidget(self.period_table)
        coverage_tables.setSizes([850, 500])
        coverage_layout.addWidget(coverage_tables, 1)
        buttons = QHBoxLayout()
        self.coverage_buttons = [
            self._button(buttons, "Confirm whole year", lambda: self._confirm(True, True)),
            self._button(buttons, "Revoke whole year", lambda: self._confirm(False, True)),
            self._button(buttons, "Confirm selected periods", lambda: self._confirm(True, False)),
            self._button(buttons, "Revoke selected periods", lambda: self._confirm(False, False)),
        ]
        coverage_layout.addLayout(buttons)
        retrospective = QHBoxLayout()
        retrospective.addWidget(QLabel("Retrospective usage check year"))
        self.check_year = QComboBox()
        retrospective.addWidget(self.check_year)
        self.check_button = self._button(retrospective, "Run retrospective usage check", self.run_retrospective)
        retrospective.addStretch(1)
        coverage_layout.addLayout(retrospective)
        self.coverage_tabs = QTabWidget()
        self.coverage_tabs.addTab(coverage, "Historical coverage and reference years")
        self.splitter.addWidget(self.coverage_tabs)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current forecast")
        scroll.setWidget(self.chart_image)
        self.splitter.addWidget(scroll)
        self.detail_tabs, self.tables = QTabWidget(), {}
        self.splitter.addWidget(self.detail_tabs)
        self.splitter.setSizes([220, 300, 230])
        layout.addWidget(self.splitter, 1)
        self._scope_changed()

    @staticmethod
    def _button(layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def activate(self):
        if self.snapshot is None and not self._loading:
            self.load_source()

    def set_source(self, backend, data_dir, year):
        if (backend, data_dir, year) == (self.backend, self.data_dir, self.year):
            return
        self.cancel()
        for window in list(self._charts):
            window.close()
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.snapshot, self.history = None, {}
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

    def load_source(self):
        self.cancel()
        self.snapshot = None
        self._updating = True
        try:
            self.history = {}
            self._history_years = []
            self.history_table.setRowCount(0)
            self.period_table.setRowCount(0)
            self.check_year.clear()
        finally:
            self._updating = False
        self._loading = True
        self._set_enabled(False)
        self._cancel_event = Event()
        canceled = self._cancel_event
        source = ReadOnlySnapshotSource(self.backend, self.data_dir)
        year = self.year

        def load():
            target = source.snapshot(year)
            history, errors = {}, []
            for row in source.inventory():
                if isinstance(row, dict) and row.get("valid") is not True and type(row.get("leave_year")) is int:
                    errors.append(
                        {
                            "code": "INVALID_HISTORICAL_SOURCE",
                            "message": "The selected backend reports invalid historical year metadata; no zero usage is assumed.",
                            "year": row["leave_year"],
                        }
                    )
            for reference in source.years():
                if canceled.is_set():
                    raise RuntimeError("Canceled historical loading.")
                if reference == year:
                    continue
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

        self.status_label.setText("Loading the selected datastore and historical snapshots read-only...")
        self._launch("load", load)

    def set_data(self, snapshot, history, preferences=None, errors=()):
        self._updating = True
        self.snapshot, self.history = deepcopy((snapshot, history))
        self.preferences = deepcopy(preferences or {"coverage": [], "excluded_years": []})
        self._source_errors = deepcopy(list(errors))
        start = QDate.fromString(snapshot["leave_year_start"], "yyyy-MM-dd")
        end = QDate.fromString(snapshot["leave_year_end"], "yyyy-MM-dd")
        for edit in (self.cutoff_edit, self.horizon_edit):
            edit.setDateRange(start, end)
        self.cutoff_edit.setDate(min(max(QDate(self.today.year, self.today.month, self.today.day), start), end))
        self.horizon_edit.setDate(end)
        self._history_years = sorted(set(history) | {row["year"] for row in errors if "year" in row}, reverse=True)
        eligible = sorted(
            (year for year, source in history.items() if source["leave_year_end"] < snapshot["leave_year_start"]),
            key=lambda y: (history[y]["leave_year_end"], y),
        )[-5:]
        selected = set(self.preferences.get("reference_years", eligible))
        excluded = set(self.preferences.get("excluded_years", []))
        self.history_table.setRowCount(len(self._history_years))
        self.check_year.clear()
        for index, year in enumerate(self._history_years):
            source = history.get(year, {})
            for column, checked in ((0, year in selected), (1, year in excluded)):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                self.history_table.setItem(index, column, item)
            for column, value in enumerate(
                (
                    year,
                    source.get("leave_year_start", "N/A"),
                    source.get("leave_year_end", "N/A"),
                    "Checking...",
                    "Historical coverage defaults to unconfirmed.",
                ),
                2,
            ):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.history_table.setItem(index, column, item)
            if source and source["leave_year_end"] < self.today.isoformat():
                self.check_year.addItem(str(year), year)
        self.history_table.resizeColumnsToContents()
        self._updating = False
        self._loading = False
        self._set_enabled(True)
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _scope_changed(self):
        self._updating = True
        current = self.category_combo.currentData()
        self.category_combo.clear()
        for category in self.scope_combo.currentData():
            self.category_combo.addItem(f"{category.title()} leave", category)
        self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(current)))
        for category, edit in self.reserves.items():
            edit.setEnabled(category in self.scope_combo.currentData())
        self._updating = False
        self._changed()

    def _parameters(self):
        categories = tuple(self.scope_combo.currentData())
        return ForecastParameters(
            self.cutoff_edit.date().toString("yyyy-MM-dd"),
            self.horizon_edit.date().toString("yyyy-MM-dd"),
            categories,
            tuple(
                year
                for i, year in enumerate(self._history_years)
                if self.history_table.item(i, 0).checkState() == Qt.Checked
            ),
            tuple(
                year
                for i, year in enumerate(self._history_years)
                if self.history_table.item(i, 1).checkState() == Qt.Checked
            ),
            self.basis_combo.currentData(),
            {
                category: float(self.reserves[category].text())
                for category in categories
                if self.reserves[category].text().strip()
            },
        )

    def _clear_result(self):
        self.result, self.retrospective, self._views = None, None, {}
        self.chart_image.set_source_pixmap(QPixmap())
        self.chart_image.clear()
        for table in self.tables.values():
            table.setRowCount(0)

    def _changed(self):
        if self._updating or self._closed:
            return
        self._revision += 1
        self._clear_result()
        self.status_label.setText("Controls changed; calculating from cached read-only snapshots...")
        if self.snapshot is not None:
            self._timer.start()

    def recalculate(self):
        if self.snapshot is None or self._closed or self._updating:
            return
        self._timer.stop()
        self._clear_result()
        try:
            parameters = self._parameters()
        except (ValueError, TypeError) as exc:
            self.status_label.setText(f"Invalid forecast input: {exc}")
            return
        target, history, coverage, errors, today = deepcopy(
            (self.snapshot, self.history, self.preferences.get("coverage", []), self._source_errors, self.today)
        )

        def calculate():
            result = forecast(target, history, coverage, parameters, today=today)
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
        elif kind == "retrospective":
            self.retrospective = value
            self._render_retrospective()
            self.detail_tabs.setCurrentWidget(self.tables["Retrospective checks"])
            self.status_label.setText(value.limitation)
        else:
            self.result = value
            self._render_result()
            self.result_changed.emit()

    def _render_retrospective(self):
        if self.retrospective is None:
            return
        category = self.category_combo.currentData()
        for title, rows, keys in (
            (
                "Retrospective checks",
                self.retrospective.rows,
                (
                    "evaluation_year",
                    "cutoff",
                    "horizon",
                    "category",
                    "scenario",
                    "source_years",
                    "actual_hours",
                    "estimated_future_hours",
                    "error_hours",
                    "absolute_error",
                    "whole_year_estimate",
                    "whole_year_error",
                    "whole_year_source_years",
                    "actual_coverage_complete",
                    "training_population_note",
                ),
            ),
            (
                "Retrospective MAE",
                self.retrospective.summaries,
                (
                    "evaluation_year",
                    "horizon",
                    "category",
                    "scenario",
                    "sample_count",
                    "mean_absolute_error",
                    "whole_year_sample_count",
                    "whole_year_mean_absolute_error",
                ),
            ),
        ):
            self._install_table(
                title,
                [row for row in rows if row["category"] == category],
                [(key, key.replace("_", " ").title()) for key in keys],
            )

    @Slot(int, str, object)
    def _failed(self, revision, kind, errors):
        self._tasks.pop(revision, None)
        if revision == self._revision and not self._closed:
            self._loading = False
            self._set_enabled(True)
            self.progress.hide()
            self.status_label.setText("Forecast unavailable: " + "; ".join(item["message"] for item in errors))

    def _install_table(self, title, rows, columns):
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
        self._views[title] = (rows, columns)

    def _render_result(self, *_args):
        if self.result is None or self._updating or self._closed:
            return
        category = self.category_combo.currentData()
        if category not in self.result.parameters.categories:
            return
        current = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        self._views = forecast_tables(self.result, category)
        for title, (rows, columns) in list(self._views.items()):
            self._install_table(title, rows, columns)
        self._render_retrospective()
        self.tables["Monthly explanations"].cellActivated.connect(self._source_drilldown)
        for index in range(self.detail_tabs.count()):
            if self.detail_tabs.tabText(index) == current:
                self.detail_tabs.setCurrentIndex(index)
        completeness = {row["scenario"]: row["allocation_complete"] for row in self._views["Summary"][0]}
        self.chart_image.set_source_pixmap(
            render_forecast_chart(
                f"Usage Forecast — {category.title()} leave",
                self._views["Daily closing balances"][0],
                self.result.parameters.reserves.get(category),
                self.result.parameters.cutoff,
                self.result.parameters.horizon,
                completeness,
            )
        )
        self._updating = True
        history = {row["year"]: row for row in self.result.history}
        for i, year in enumerate(self._history_years):
            row = history.get(year, {})
            periods = row.get("periods", ())
            confirmed = sum(p["confirmed"] for p in periods)
            self.history_table.item(i, 5).setText(f"{confirmed} / {len(periods)}")
            self.history_table.item(i, 6).setText(
                row.get("exclusion_reason")
                or (
                    "Coverage confirmed"
                    if periods and confirmed == len(periods)
                    else "Partial/unconfirmed coverage; review month eligibility"
                )
            )
        self._updating = False
        self._show_periods()
        incomplete = any(not value for key, value in completeness.items() if key != "scheduled")
        self.status_label.setText(
            "Incomplete Allocation / unavailable history: curves include allocated estimates only; review unallocated hours and N/A metrics."
            if incomplete
            else "Scheduled, Typical Usage and Higher Usage use separate category balances and the same scheduled baseline. Daily closing hours; no ledger changes."
        )

    def _selected_year(self):
        row = self.history_table.currentRow()
        return self._history_years[row] if 0 <= row < len(self._history_years) else None

    def _show_periods(self, *_args):
        if self._updating:
            return
        year = self._selected_year()
        history = next((row for row in self.result.history if row["year"] == year), None) if self.result else None
        periods = history.get("periods", []) if history else []
        sorting = self.period_table.isSortingEnabled()
        self.period_table.setSortingEnabled(False)
        self.period_table.setRowCount(len(periods))
        for i, period in enumerate(periods):
            for column, key in enumerate(("period_id", "start", "end", "state")):
                item = QTableWidgetItem(str(period[key]))
                if key == "period_id" and str(period[key]).isdigit():
                    item.setData(Qt.DisplayRole, int(period[key]))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.period_table.setItem(i, column, item)
        self.period_table.setSortingEnabled(sorting)

    def _confirm(self, confirmed, whole):
        year = self._selected_year()
        if self.snapshot is None or year not in self.history:
            self.status_label.setText("Select a loaded historical year first.")
            return
        periods = None
        if not whole:
            periods = [
                self.period_table.item(index.row(), 0).text()
                for index in self.period_table.selectionModel().selectedRows()
            ]
            if not periods:
                self.status_label.setText("Select the pay periods whose coverage you intend to change.")
                return
        snapshot, preferences = deepcopy((self.history[year], self.preferences))
        self._launch("coverage", lambda: update_coverage(preferences, snapshot, periods, confirmed=confirmed))

    def _save_preferences(self, candidate):
        try:
            save_preferences(self.snapshot, candidate)
        except (ValueError, OSError) as exc:
            self.status_label.setText(f"Analytics preferences were not changed: {exc}")
            return False
        self.preferences = deepcopy(candidate)
        return True

    def _history_edited(self, item):
        if self._updating or item.column() not in (0, 1):
            return
        candidate = {
            **self.preferences,
            "reference_years": [
                year
                for i, year in enumerate(self._history_years)
                if self.history_table.item(i, 0).checkState() == Qt.Checked
            ],
            "excluded_years": [
                year
                for i, year in enumerate(self._history_years)
                if self.history_table.item(i, 1).checkState() == Qt.Checked
            ],
        }
        if self._save_preferences(candidate):
            self._changed()
        else:
            self._updating = True
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            self._updating = False

    def run_retrospective(self):
        year = self.check_year.currentData()
        if self.snapshot is None or year is None:
            self.status_label.setText("Load a completed historical year first.")
            return
        try:
            parameters = self._parameters()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        snapshots, coverage, today = deepcopy(
            ({**self.history, self.year: self.snapshot}, self.preferences.get("coverage", []), self.today)
        )
        self._launch(
            "retrospective",
            lambda: retrospective_check(
                snapshots,
                coverage,
                year,
                today=today,
                categories=parameters.categories,
                status_basis=parameters.status_basis,
                excluded_years=parameters.excluded_years,
                reference_years=parameters.reference_years,
            ),
        )

    def _source_drilldown(self, row, _column):
        table = self.tables["Monthly explanations"]
        index = table.item(row, 0).data(Qt.UserRole + 1)
        if index is None:
            return
        explanation = self._views["Monthly explanations"][0][index]
        observations = [
            {**item, "basis": basis}
            for basis in ("seasonal", "fallback")
            for item in explanation[f"{basis}_observations"]
        ]
        dialog = QDialog(self)
        dialog.setWindowTitle("Historical source rates, transaction IDs and coverage")
        dialog.resize(1100, 550)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            table_widget(
                observations,
                [
                    (key, key.replace("_", " ").title())
                    for key in (
                        "year",
                        "basis",
                        "hours",
                        "exposure",
                        "rate",
                        "eligible",
                        "exclusion_reason",
                        "transaction_ids",
                        "source_key",
                    )
                ],
            )
        )
        self._button(layout, "Close", dialog.accept)
        dialog.exec()

    def save_csv(self):
        if self.result is None:
            return
        title = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        if title not in self._views:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Forecast Table",
            str(Path(self.pdf_folder or ".") / f"fedleave-forecast-{self.year}.csv"),
            "CSV files (*.csv)",
        )
        if path:
            try:
                rows, columns = self._views[title]
                export_csv(
                    Path(path), self.snapshot, self.result, self.category_combo.currentData(), title, rows, columns
                )
            except (OSError, ValueError) as exc:
                self.status_label.setText(str(exc))

    def export_json(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Forecast Results",
            str(Path(self.pdf_folder or ".") / f"fedleave-forecast-{self.year}.json"),
            "JSON files (*.json)",
        )
        if path:
            try:
                payload = {
                    **self.result.to_dict(),
                    "retrospective": self.retrospective.to_dict() if self.retrospective else None,
                }
                write_export(Path(path), json.dumps(payload, indent=2, sort_keys=True) + "\n", self.snapshot)
            except (OSError, ValueError) as exc:
                self.status_label.setText(str(exc))

    def open_chart(self):
        if self.result is None:
            return
        snapshot, result, category = deepcopy((self.snapshot, self.result, self.category_combo.currentData()))
        rows = self._views["Daily closing balances"][0]

        def export():
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Forecast Chart Data", f"fedleave-forecast-{self.year}-daily.csv", "CSV files (*.csv)"
            )
            if path:
                export_csv(Path(path), snapshot, result, category, "Daily closing balances")

        chart = AnalyticsChartWindow(
            f"Usage Forecast — {category.title()} leave",
            self.chart_image.source_pixmap(),
            rows,
            DAILY_COLUMNS,
            self.pdf_folder,
            f"fedleave-forecast-{self.year}-{category}",
            csv_export=export,
            export_target=lambda path: export_destination(Path(path), snapshot),
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda: self._charts.remove(chart) if chart in self._charts else None)
        chart.show()

    def _set_enabled(self, enabled):
        for widget in (
            self.cutoff_edit,
            self.horizon_edit,
            self.scope_combo,
            self.basis_combo,
            self.category_combo,
            self.check_year,
            self.check_button,
            self.history_table,
            self.period_table,
            self.calculate_button,
            *self.coverage_buttons,
        ):
            widget.setEnabled(enabled)
        for category, edit in self.reserves.items():
            edit.setEnabled(enabled and category in self.scope_combo.currentData())

    def cancel(self):
        self._revision += 1
        self._timer.stop()
        self._cancel_event.set()
        self._loading = False
        self.progress.hide()
        self._set_enabled(True)
        self._clear_result()
        self.status_label.setText("Canceled. No leave records were changed.")

    def shutdown(self):
        self.cancel()
        self._closed = True
        for chart in list(self._charts):
            chart.close()
