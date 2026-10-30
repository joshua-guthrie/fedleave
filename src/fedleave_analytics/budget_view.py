"""Read-only Leave Budget with cancellable worker results and explicit transfer."""

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fedleave.budget import CATEGORIES, STRATEGIES, STRATEGY_HELP, BudgetParameters, budget
from fedleave.planning import source_identity

from .budget_model import CUMULATIVE_COLUMNS, export_csv, result_views
from .charts import BLUE, RED, AnalyticsChartWindow, ResponsivePixmapLabel, render_planning_chart, table_widget
from .planning_model import LABELS, export_destination
from .planning_view import _Task
from .preferences import load_preferences, save_preferences
from .snapshots import ReadOnlySnapshotSource


class BudgetWidget(QWidget):
    source_loaded = Signal(object)
    transfer_ready = Signal(object, object)

    def __init__(self, backend, data_dir, year, pdf_folder="", *, today=None, parent=None):
        super().__init__(parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder, self.today = pdf_folder, today or date.today()
        self.snapshot, self.result = None, None
        self._revision, self._loading, self._closed, self._updating = 0, False, False, False
        self._tasks, self._charts, self._views, self.tables = {}, [], {}, {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.recalculate)
        layout = QVBoxLayout(self)
        form = QGridLayout()
        self.cutoff_edit, self.horizon_edit = QDateEdit(), QDateEdit()
        for edit in (self.cutoff_edit, self.horizon_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.dateChanged.connect(self._changed)
        self.strategy_combo = QComboBox()
        for key, label in STRATEGIES.items():
            self.strategy_combo.addItem(label, key)
        self.strategy_combo.currentIndexChanged.connect(self._strategy_changed)
        for index, (label, control) in enumerate(
            (("Cutoff", self.cutoff_edit), ("Horizon", self.horizon_edit), ("Scheduling strategy", self.strategy_combo))
        ):
            text = QLabel(label)
            text.setBuddy(control)
            form.addWidget(text, 0, index * 2)
            form.addWidget(control, 0, index * 2 + 1)
        self.eligibility, self.reserves = {}, {}
        for index, category in enumerate(CATEGORIES):
            check = QCheckBox(LABELS[category])
            check.setToolTip("Select only if this category is eligible for your intended leave purpose.")
            check.toggled.connect(self._changed)
            reserve = QLineEdit("0")
            reserve.setMaximumWidth(85)
            reserve.setAccessibleName(f"{LABELS[category]} reserve hours")
            reserve.setToolTip("Optional minimum bank reserve, in hours")
            reserve.textChanged.connect(self._changed)
            form.addWidget(check, 1 + index // 3, (index % 3) * 2)
            form.addWidget(reserve, 1 + index // 3, (index % 3) * 2 + 1)
            self.eligibility[category], self.reserves[category] = check, reserve
        layout.addLayout(form)
        self.strategy_label = QLabel()
        self.strategy_label.setWordWrap(True)
        layout.addWidget(self.strategy_label)
        note = QLabel(
            "Select purpose-eligible categories; adjacent fields are optional reserve hours. Suggestions are estimated planning entries, not booked leave. Current configured schedule is assumed; future rosters are not known. Double-click a result row for exact details."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        for label, callback in (
            ("Calculate", self.recalculate),
            ("Cancel", self.cancel),
            ("Open Chart", self.open_chart),
            ("Save Table as CSV...", self.save_csv),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            if label == "Calculate":
                self.calculate_button = button
        self.transfer_button = QPushButton("Send suggestions to What-if...")
        self.transfer_button.clicked.connect(self.transfer)
        self.transfer_button.setEnabled(False)
        buttons.addWidget(self.transfer_button)
        layout.addLayout(buttons)
        self.status_label = QLabel("Load the selected year read-only to calculate deadline budgets.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        splitter = QSplitter(Qt.Vertical)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current budget")
        scroll.setWidget(self.chart_image)
        splitter.addWidget(scroll)
        self.detail_tabs = QTabWidget()
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([290, 320])
        layout.addWidget(splitter, 1)
        self._strategy_changed()

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
        self.snapshot = None

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
        self._loading = True
        self._set_enabled(False)
        backend, data_dir, year = self.backend, self.data_dir, self.year

        def load():
            source = ReadOnlySnapshotSource(backend, data_dir)
            snapshot = source.snapshot(year)
            snapshot["planning_available_years"] = source.years()
            try:
                preferences, error = load_preferences(snapshot), ""
            except ValueError as exc:
                preferences, error = {}, str(exc)
            return snapshot, preferences, error

        self.status_label.setText("Loading the selected backend and datastore read-only...")
        self._launch("load", load)

    def set_data(self, snapshot, preferences=None, error=""):
        self._updating = True
        self.snapshot = deepcopy(snapshot)
        self._preference_error = error
        start = QDate.fromString(snapshot["leave_year_start"], "yyyy-MM-dd")
        end = QDate.fromString(snapshot["leave_year_end"], "yyyy-MM-dd")
        for edit in (self.cutoff_edit, self.horizon_edit):
            edit.setDateRange(start, end)
        self.cutoff_edit.setDate(min(max(QDate(self.today.year, self.today.month, self.today.day), start), end))
        self.horizon_edit.setDate(end)
        strategy = (preferences or {}).get("budget_strategy", "even")
        self.strategy_combo.setCurrentIndex(max(0, self.strategy_combo.findData(strategy)))
        self._updating = self._loading = False
        self._set_enabled(True)
        self._strategy_changed(persist=False)
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _parameters(self):
        return BudgetParameters(
            self.cutoff_edit.date().toString("yyyy-MM-dd"),
            self.horizon_edit.date().toString("yyyy-MM-dd"),
            self.strategy_combo.currentData(),
            tuple(c for c, check in self.eligibility.items() if check.isChecked()),
            {c: float(edit.text()) for c, edit in self.reserves.items()},
        )

    def _strategy_changed(self, _index=0, *, persist=True):
        strategy = self.strategy_combo.currentData()
        self.strategy_label.setText(
            f"{STRATEGIES[strategy]}: {STRATEGY_HELP[strategy]} Deadline priority always applies."
        )
        if self._updating:
            return
        if persist and self.snapshot is not None:
            try:
                preferences = load_preferences(self.snapshot)
                save_preferences(self.snapshot, {**preferences, "budget_strategy": strategy})
                self._preference_error = ""
            except (OSError, ValueError) as exc:
                self._preference_error = str(exc)
        self._changed()

    def _clear(self):
        self.progress.hide()
        self.result = None
        self.transfer_button.setEnabled(False)
        self.chart_image.set_source_pixmap(QPixmap())
        self._views, self.tables = {}, {}
        while self.detail_tabs.count():
            widget = self.detail_tabs.widget(0)
            self.detail_tabs.removeTab(0)
            widget.deleteLater()

    def _changed(self, *_args):
        if self._updating or self._closed:
            return
        self._revision += 1
        self._clear()
        self.status_label.setText("Controls changed; calculating from the cached read-only snapshot...")
        if self.snapshot is not None:
            self._timer.start()

    def recalculate(self):
        if self.snapshot is None or self._closed or self._updating:
            return
        self._timer.stop()
        self._clear()
        try:
            parameters = self._parameters()
        except ValueError as exc:
            self.status_label.setText(f"Invalid reserve: {exc}")
            return
        snapshot, today = deepcopy(self.snapshot), self.today
        self._launch("calculate", lambda: budget(snapshot, parameters, today=today))

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
        elif kind == "transfer":
            self.transfer_ready.emit(*value)
        else:
            self.result = value
            self._render()

    @Slot(int, str, object)
    def _failed(self, revision, _kind, error):
        self._tasks.pop(revision, None)
        if revision != self._revision or self._closed:
            return
        self.progress.hide()
        self._loading = False
        self._set_enabled(True)
        self._clear()
        self.status_label.setText(
            "; ".join(item.get("message", str(item)) for item in error) if isinstance(error, list) else str(error)
        )

    def _render(self):
        result = self.result
        self._views = result_views(result)
        for title, (rows, columns) in self._views.items():
            table = table_widget(rows, columns)
            self.tables[title] = table
            self.detail_tabs.addTab(table, title)
            table.cellDoubleClicked.connect(lambda row, _column, name=title: self.show_detail(name, row))
        points = [dict(row, date=row["deadline"]) for row in result.cumulative]
        self.chart_image.set_source_pixmap(
            render_planning_chart(
                "Leave Budget — cumulative deadlines",
                points,
                [],
                None,
                result.parameters.cutoff,
                result.parameters.horizon,
                series=(
                    ("required_hours", "Required", RED, Qt.SolidLine, 135),
                    ("available_hours", "Feasibly allocated", BLUE, Qt.DashLine, 500),
                ),
                caption=f"{STRATEGIES[result.parameters.strategy]}. Eligible categories and dated balances constrain the shared capacity. Suggestions are not booked leave.",
                value_basis="Cumulative hours by deadline",
                origin_label="First deadline",
            )
        )
        self.status_label.setText(
            f"{result.state} | {STRATEGIES[result.parameters.strategy]} | Known additional required {result.required_hours:g} h; suggested {result.allocated_hours:g} h; unallocated {result.unallocated_hours:g} h. {len(result.warnings)} warnings. "
            + (f"Preferences: {self._preference_error}" if self._preference_error else "")
        )
        self.transfer_button.setEnabled(bool(result.suggestions))

    def show_detail(self, title, displayed_row):
        table = self.tables[title]
        item = table.item(displayed_row, 0)
        index = item.data(Qt.UserRole + 1) if item else None
        if not isinstance(index, int):
            return
        row = deepcopy(self._views[title][0][index])
        if "detail" in row:
            row["detail"] = json.loads(row["detail"])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Leave Budget — {title}")
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(row, indent=2, sort_keys=True))
        layout.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def save_csv(self):
        if self.result is None or not self._views:
            return
        title = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Leave Budget Table",
            str(Path(self.pdf_folder or ".") / f"fedleave-budget-{self.year}.csv"),
            "CSV files (*.csv)",
        )
        if path:
            try:
                export_csv(Path(path), self.snapshot, self.result, title)
            except (ValueError, OSError) as exc:
                self.status_label.setText(str(exc))

    def open_chart(self):
        if self.result is None:
            return
        snapshot, result = deepcopy((self.snapshot, self.result))

        def export():
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Leave Budget Chart Data", "fedleave-budget-deadlines.csv", "CSV files (*.csv)"
            )
            if path:
                try:
                    export_csv(Path(path), snapshot, result, "Cumulative deadlines")
                except (ValueError, OSError) as exc:
                    self.status_label.setText(str(exc))

        chart = AnalyticsChartWindow(
            "Leave Budget — cumulative deadlines",
            self.chart_image.source_pixmap(),
            list(result.cumulative),
            CUMULATIVE_COLUMNS,
            self.pdf_folder,
            f"fedleave-budget-{self.year}",
            csv_export=export,
            export_target=lambda path: export_destination(Path(path), snapshot),
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda: self._charts.remove(chart) if chart in self._charts else None)
        chart.show()

    def transfer(self):
        if self.result is None or not self.result.suggestions:
            return
        result = deepcopy(self.result)
        backend, data_dir, year = self.backend, self.data_dir, self.year

        def load():
            fresh = ReadOnlySnapshotSource(backend, data_dir).snapshot(year)
            if source_identity(fresh) != result.source:
                raise ValueError(
                    "STALE_SNAPSHOT: Source changed. Refresh and recalculate Leave Budget before transfer."
                )
            return fresh, result

        self.status_label.setText("Checking a fresh read-only snapshot before in-memory transfer...")
        self._launch("transfer", load)

    def cancel(self):
        self._revision += 1
        self._timer.stop()
        self._loading = False
        self._set_enabled(True)
        self.progress.hide()
        self._clear()
        self.status_label.setText("Canceled. No leave records were changed.")

    def _set_enabled(self, enabled):
        for control in (
            self.cutoff_edit,
            self.horizon_edit,
            self.strategy_combo,
            self.calculate_button,
            *self.eligibility.values(),
            *self.reserves.values(),
        ):
            control.setEnabled(enabled)

    def shutdown(self):
        self.cancel()
        self._closed = True
        for chart in list(self._charts):
            chart.close()
