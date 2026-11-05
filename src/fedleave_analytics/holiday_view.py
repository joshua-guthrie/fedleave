"""Holiday options using the existing companion's worker and export lifecycle."""

from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Event

from PySide6.QtCore import QDate, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fedleave.break_patterns import DISCRETIONARY_CATEGORIES
from fedleave.holiday_planner import RANKINGS, HolidayParameters, plan_holidays
from fedleave.planning import source_identity

from .budget_view import BudgetWidget
from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, table_widget
from .holiday_charts import render_holiday_option
from .holiday_model import DAY_COLUMNS, export_csv, result_views
from .planning_model import LABELS, export_destination
from .snapshots import ReadOnlySnapshotSource


class HolidayWidget(BudgetWidget):
    """Reuse BudgetWidget's bounded read-only workers and stale-result guards."""

    progress_changed = Signal(int, int, int)

    def __init__(self, backend, data_dir, year, pdf_folder="", *, today=None, parent=None):
        QWidget.__init__(self, parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder, self.today = pdf_folder, today or date.today()
        self.snapshot, self.result = None, None
        self._revision, self._loading, self._closed, self._updating = 0, False, False, False
        self._tasks, self._charts, self._views, self.tables = {}, [], {}, {}
        self._cancel_event, self._selected = Event(), None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self.recalculate)
        self.progress_changed.connect(self._progress)
        layout, form = QVBoxLayout(self), QGridLayout()
        self.cutoff_edit, self.start_edit, self.end_edit = QDateEdit(), QDateEdit(), QDateEdit()
        self.minimum_spin, self.maximum_spin = QSpinBox(), QSpinBox()
        self.minimum_spin.setRange(1, 366)
        self.minimum_spin.setValue(4)
        self.maximum_spin.setRange(1, 366)
        self.maximum_spin.setValue(21)
        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setRange(0, 10000)
        self.hours_spin.setValue(40)
        self.hours_spin.setSuffix(" h")
        self.ranking_combo = QComboBox()
        for key, label in RANKINGS.items():
            self.ranking_combo.addItem(label, key)
        self.ranking_combo.currentIndexChanged.connect(self._changed)
        for i, (label, control) in enumerate(
            (
                ("Cutoff", self.cutoff_edit),
                ("Search from", self.start_edit),
                ("Through", self.end_edit),
                ("Minimum calendar days", self.minimum_spin),
                ("Maximum interval days", self.maximum_spin),
                ("Maximum additional hours", self.hours_spin),
                ("Rank options", self.ranking_combo),
            )
        ):
            text = QLabel(label)
            text.setBuddy(control)
            form.addWidget(text, (i // 4) * 2, i % 4)
            form.addWidget(control, (i // 4) * 2 + 1, i % 4)
        for edit in (self.cutoff_edit, self.start_edit, self.end_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.dateChanged.connect(self._changed)
        for spin in (self.minimum_spin, self.maximum_spin, self.hours_spin):
            spin.valueChanged.connect(self._changed)
        self.eligibility, self.reserves = {}, {}
        banks = QGridLayout()
        for i, category in enumerate(DISCRETIONARY_CATEGORIES):
            check, reserve = QCheckBox(LABELS[category]), QLineEdit("0")
            check.setToolTip(
                "Propose only this discretionary category. Availability does not establish agency approval or purpose eligibility."
            )
            check.toggled.connect(self._changed)
            reserve.setAccessibleName(f"{LABELS[category]} reserve hours")
            reserve.setToolTip("Minimum reserve in hours at every projected date.")
            reserve.setMaximumWidth(75)
            reserve.textChanged.connect(self._changed)
            banks.addWidget(check, i // 3, (i % 3) * 2)
            banks.addWidget(reserve, i // 3, (i % 3) * 2 + 1)
            self.eligibility[category], self.reserves[category] = check, reserve
        layout.addLayout(form)
        layout.addLayout(banks)
        self.mixed_check = QCheckBox("Show options dependent on other-purpose scheduled absence")
        self.infeasible_check = QCheckBox("Show infeasible / incomplete funding")
        filters = QHBoxLayout()
        for check in (self.mixed_check, self.infeasible_check):
            check.toggled.connect(self._changed)
            filters.addWidget(check)
        layout.addLayout(filters)
        note = QLabel(
            "Independent planning options, not booked leave. Current configured regular tour and cached observed holidays are assumed; irregular rosters are not reconstructed. Select eligible discretionary categories; adjacent fields are reserve hours. Efficiency is calendar days per additional standard-workday-equivalent; Already scheduled options have N/A efficiency. Select an option for exact days, funding and balance effects."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        for label, callback in (
            ("Calculate", self.recalculate),
            ("Cancel", self.cancel),
            ("Open Chart", self.open_chart),
            ("Save Table as CSV...", self.save_csv),
            ("Open in What-if Planner", self.transfer),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
            if label == "Calculate":
                self.calculate_button = button
            if label == "Open in What-if Planner":
                self.transfer_button = button
                button.setEnabled(False)
        layout.addLayout(actions)
        self.status_label = QLabel("Load a selected initialized leave year read-only to find future break options.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        split = QSplitter(Qt.Vertical)
        self.option_table = table_widget([], [])
        self.option_table.currentCellChanged.connect(self._selection_changed)
        split.addWidget(self.option_table)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("Select a break option")
        scroll.setWidget(self.chart_image)
        split.addWidget(scroll)
        self.detail_tabs = QTabWidget()
        split.addWidget(self.detail_tabs)
        split.setSizes([150, 240, 180])
        layout.addWidget(split, 1)

    def load_source(self):
        self.cancel()
        self.snapshot, self._loading = None, True
        self._set_enabled(False)
        backend, data_dir, year = self.backend, self.data_dir, self.year

        def load():
            source = ReadOnlySnapshotSource(backend, data_dir)
            snapshot = source.snapshot(year)
            snapshot["planning_available_years"] = source.years()
            return (snapshot,)

        self.status_label.setText("Loading the selected backend and datastore read-only...")
        self._launch("load", load)

    def set_data(self, snapshot, *_unused):
        self._updating = True
        self.snapshot = deepcopy(snapshot)
        first, last = (QDate.fromString(snapshot[k], "yyyy-MM-dd") for k in ("leave_year_start", "leave_year_end"))
        for edit in (self.cutoff_edit, self.start_edit, self.end_edit):
            edit.setDateRange(first, last)
        cutoff = min(max(QDate(self.today.year, self.today.month, self.today.day), first), last)
        self.cutoff_edit.setDate(cutoff)
        self.start_edit.setDate(min(cutoff.addDays(1), last))
        self.end_edit.setDate(last)
        for category, check in self.eligibility.items():
            available = float(snapshot.get("starting_balances", {}).get(category, 0) or 0) > 0 or any(
                t.get("category") == category and t.get("direction") in {"earned", "restored"}
                for t in snapshot.get("transactions", [])
            )
            if category == "annual":
                available = available or snapshot.get("annual_leave_accrual_hours", 0) > 0
            check.setChecked(
                bool(available and snapshot["snapshot_rules"].get("rules", {}).get(category, {}).get("enabled", True))
            )
        self._updating = self._loading = False
        self._set_enabled(True)
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _set_enabled(self, enabled):
        for control in (
            self.cutoff_edit,
            self.start_edit,
            self.end_edit,
            self.minimum_spin,
            self.maximum_spin,
            self.hours_spin,
            self.ranking_combo,
            self.mixed_check,
            self.infeasible_check,
            self.calculate_button,
            *self.eligibility.values(),
            *self.reserves.values(),
        ):
            control.setEnabled(enabled)

    def _clear(self):
        self._selected = None
        self.option_table.setRowCount(0)
        super()._clear()

    def _changed(self, *_args):
        if not self._updating:
            self._cancel_event.set()
        super()._changed()

    def _parameters(self):
        return HolidayParameters(
            self.cutoff_edit.date().toString("yyyy-MM-dd"),
            self.start_edit.date().toString("yyyy-MM-dd"),
            self.end_edit.date().toString("yyyy-MM-dd"),
            self.minimum_spin.value(),
            self.hours_spin.value(),
            self.maximum_spin.value(),
            tuple(k for k, v in self.eligibility.items() if v.isChecked()),
            {k: float(v.text()) for k, v in self.reserves.items() if v.text().strip()},
            self.ranking_combo.currentData(),
            self.mixed_check.isChecked(),
            self.infeasible_check.isChecked(),
        )

    def recalculate(self):
        if self.snapshot is None or self._closed or self._updating:
            return
        self._timer.stop()
        self._cancel_event.set()
        self._cancel_event = Event()
        self._clear()
        try:
            params = self._parameters()
        except ValueError as exc:
            self.status_label.setText(f"Invalid reserve: {exc}")
            return
        snapshot, today, event = deepcopy(self.snapshot), self.today, self._cancel_event
        revision = self._revision + 1
        self.status_label.setText("Finding bounded options on cached context; funding each independently...")
        self._launch(
            "calculate",
            lambda: plan_holidays(
                snapshot,
                params,
                today=today,
                canceled=event.is_set,
                progress=lambda done, total: self.progress_changed.emit(revision, done, total),
            ),
        )

    @Slot(int, int, int)
    def _progress(self, revision, done, total):
        if revision == self._revision and not self._closed:
            self.status_label.setText(
                f"Funding option {done} of {total} bounded ranges; alternatives are independent..."
            )

    def _render(self):
        views = result_views(self.result)
        rows, columns = views["Options"]
        previous = self.option_table
        table = table_widget(rows, columns)
        previous.parent().replaceWidget(0, table)
        previous.deleteLater()
        self.option_table = table
        table.currentCellChanged.connect(self._selection_changed)
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setSelectionMode(table.SelectionMode.SingleSelection)
        self.status_label.setText(
            f"{len(rows)} options | {self.result.enumerated_count} normalized ranges; {self.result.evaluated_count} evaluated | {len(self.result.warnings)} source warnings. Proposed rows are scenarios; no leave was booked."
        )
        if rows:
            table.setCurrentCell(0, 0)
        else:
            self._detail(None)

    def _selection_changed(self, row, *_args):
        if self.result is None or row < 0:
            return
        item = self.option_table.item(row, 0)
        index = item.data(Qt.UserRole + 1) if item else None
        if isinstance(index, int):
            self._detail(index)

    def _detail(self, selected):
        self._selected = selected
        self._views = result_views(self.result, selected)
        self.tables = {}
        while self.detail_tabs.count():
            page = self.detail_tabs.widget(0)
            self.detail_tabs.removeTab(0)
            page.deleteLater()
        for name, (rows, columns) in self._views.items():
            table = table_widget(rows, columns)
            self.tables[name] = table
            self.detail_tabs.addTab(table, name)
        if selected is not None:
            self.chart_image.set_source_pixmap(render_holiday_option(self.result, selected))
            self.detail_tabs.setCurrentIndex(list(self.tables).index("Selected days"))
        self.transfer_button.setEnabled(
            selected is not None and self.result.candidates[selected].metrics["unfunded_hours"] == 0
        )

    def save_csv(self):
        if self.result is None:
            return
        title = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Holiday Planner Table",
            str(Path(self.pdf_folder or ".") / "fedleave-holiday-options.csv"),
            "CSV files (*.csv)",
        )
        if path:
            try:
                export_csv(Path(path), self.snapshot, self.result, title, self._selected)
            except (ValueError, OSError) as exc:
                self.status_label.setText(str(exc))

    def open_chart(self):
        if self.result is None or self._selected is None:
            return
        snapshot, result, selected = deepcopy((self.snapshot, self.result, self._selected))

        def export():
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Holiday Option Chart Data", "fedleave-holiday-option.csv", "CSV files (*.csv)"
            )
            if path:
                try:
                    export_csv(Path(path), snapshot, result, "Selected days", selected)
                except (ValueError, OSError) as exc:
                    self.status_label.setText(str(exc))

        chart = AnalyticsChartWindow(
            "Holiday and Weekend Planner — selected option",
            self.chart_image.source_pixmap(),
            list(result.candidates[selected].days),
            DAY_COLUMNS,
            self.pdf_folder,
            "fedleave-holiday-option",
            csv_export=export,
            export_target=lambda path: export_destination(Path(path), snapshot),
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda: self._charts.remove(chart) if chart in self._charts else None)
        chart.show()

    def transfer(self):
        if self.result is None or self._selected is None:
            return
        option = deepcopy(self.result.candidates[self._selected])
        if option.metrics["unfunded_hours"]:
            self.status_label.setText("This option has unfunded hours; select a fully funded option before transfer.")
            return
        backend, data_dir, year = self.backend, self.data_dir, self.year

        def load():
            fresh = ReadOnlySnapshotSource(backend, data_dir).snapshot(year)
            if source_identity(fresh) != option.source:
                raise ValueError("STALE_SNAPSHOT: Refresh and recalculate Holiday Planner before transfer.")
            return fresh, option

        self._launch("transfer", load)

    def cancel(self):
        self._cancel_event.set()
        super().cancel()
