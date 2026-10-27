"""Session-only What-if Planner with cancellable, generation-bound workers."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fedleave.planning import (
    PlanningValidationError,
    make_operation,
    scheduled_transactions,
    source_identity,
    transaction_fingerprint,
    validate_scenario,
)

from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, render_planning_chart, table_widget
from .planning_model import (
    DAILY_COLUMNS,
    PlanningSession,
    category_options,
    export_destination,
    load_planning_snapshot,
    write_export,
)


class _TaskSignals(QObject):
    finished = Signal(int, str, object)
    failed = Signal(int, str, object)


class _Task(QRunnable):
    def __init__(self, revision, kind, function):
        super().__init__()
        self.revision, self.kind, self.function = revision, kind, function
        self.signals = _TaskSignals()

    @Slot()
    def run(self):
        try:
            self.signals.finished.emit(self.revision, self.kind, self.function())
        except PlanningValidationError as exc:
            self.signals.failed.emit(self.revision, self.kind, exc.errors)
        except Exception as exc:
            self.signals.failed.emit(
                self.revision, self.kind, [{"field": self.kind, "message": str(exc), "code": "PLANNING_FAILED"}]
            )


class PlannerWidget(QWidget):
    """Present cached snapshots and pure projections, with no ledger writer."""

    source_loaded = Signal(object)
    result_changed = Signal()

    def __init__(
        self,
        backend: Path,
        data_dir: str | None,
        year: int,
        pdf_folder: str = "",
        *,
        today: date | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder = pdf_folder
        self.today = today or date.today()
        self.session: PlanningSession | None = None
        self._definition_source = None
        self._saved_fingerprint = None
        self._revision = 0
        self._closed = False
        self._loading = False
        self._updating = False
        self._tasks = {}
        self._fingerprints = {}
        self._draft_reserves = {}
        self._scheduled = []
        self._charts = []
        self._views = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.recalculate)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QGridLayout()
        self.name_edit = QLineEdit("What-if scenario")
        self.cutoff_edit = QDateEdit(QDate(self.today.year, self.today.month, self.today.day))
        self.horizon_edit = QDateEdit(self.cutoff_edit.date())
        for edit in (self.cutoff_edit, self.horizon_edit):
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.setCalendarPopup(True)
            edit.dateChanged.connect(self._changed)
        self.category_combo = QComboBox()
        for key, label in category_options():
            self.category_combo.addItem(label, key)
        self.reserve_edit = QLineEdit()
        self.reserve_edit.setPlaceholderText("Optional hours")
        self.reserve_edit.setMaximumWidth(130)
        for index, (label, widget) in enumerate(
            (
                ("Scenario", self.name_edit),
                ("Cutoff", self.cutoff_edit),
                ("Horizon", self.horizon_edit),
                ("Category", self.category_combo),
                ("Reserve", self.reserve_edit),
            )
        ):
            caption = QLabel(label)
            caption.setBuddy(widget)
            form.addWidget(caption, 0, index)
            form.addWidget(widget, 1, index)
        layout.addLayout(form)
        self.name_edit.textChanged.connect(self._changed)
        self.reserve_edit.textChanged.connect(self._reserve_changed)
        self.category_combo.currentIndexChanged.connect(self._category_changed)
        actions = QHBoxLayout()
        self.add_button = self._button(actions, "Add tentative use", self.add_tentative)
        self.replace_button = self._button(
            actions, "Replace selected scheduled use", lambda: self.add_selected("replace")
        )
        self.remove_button = self._button(actions, "Remove selected scheduled use", lambda: self.add_selected("remove"))
        self.delete_button = self._button(actions, "Delete scenario row", self.delete_selected)
        self.reset_button = self._button(actions, "Reset scenario", self.reset_scenario)
        layout.addLayout(actions)
        actions = QHBoxLayout()
        self.calculate_button = self._button(actions, "Recalculate", self.recalculate)
        self.cancel_button = self._button(actions, "Cancel", self.cancel)
        self.resolve_button = self._button(actions, "Resolve selected references", self.resolve_selected)
        self.export_button = self._button(actions, "Export scenario JSON...", self.export_json)
        self.import_button = self._button(actions, "Import scenario JSON...", self.import_json)
        self.modified_label = QLabel("Session only")
        actions.addWidget(self.modified_label)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status_label = QLabel(
            "Load a leave year to explore a scenario. Canonical leave records are never changed."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.splitter = QSplitter(Qt.Vertical)
        self.editor_tabs = QTabWidget()
        self.scenario_table = QTableWidget(0, 9)
        self.scenario_table.setHorizontalHeaderLabels(
            [
                "Scenario row ID",
                "Operation",
                "Date",
                "Category",
                "Hours to use",
                "Note",
                "Original transaction IDs",
                "Validation",
                "Earned lot ID (optional)",
            ]
        )
        self.scenario_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scenario_table.cellChanged.connect(self._cell_changed)
        for column, width in enumerate((175, 105, 125, 205, 100, 180, 210, 280, 190)):
            self.scenario_table.setColumnWidth(column, width)
        self.editor_tabs.addTab(self.scenario_table, "Scenario rows")
        self.scheduled_table = table_widget(
            [],
            [
                ("id", "Original ID"),
                ("date", "Scheduled date"),
                ("category", "Category"),
                ("hours", "Hours"),
                ("status", "Status"),
                ("description", "Note"),
            ],
        )
        self.scheduled_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scheduled_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.editor_tabs.addTab(self.scheduled_table, "Scheduled originals (select to replace/remove)")
        self.splitter.addWidget(self.editor_tabs)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current projection")
        scroll.setWidget(self.chart_image)
        self.splitter.addWidget(scroll)
        self.detail_tabs = QTabWidget()
        self.tables = {}
        for title in (
            "Summary",
            "Daily closing balances",
            "Events and provenance",
            "Working-hour capacity",
            "Expiring lots",
            "Warnings",
        ):
            table = table_widget([], [])
            self.tables[title] = table
            self.detail_tabs.addTab(table, title)
        self.splitter.addWidget(self.detail_tabs)
        self.splitter.setSizes([210, 320, 230])
        layout.addWidget(self.splitter, 1)

    @staticmethod
    def _button(layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def activate(self):
        if self.session is None and not self._loading:
            self.load_source()

    def set_source(self, backend: Path, data_dir: str | None, year: int):
        if (backend, data_dir, year) == (self.backend, self.data_dir, self.year):
            return
        self.cancel()
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.session = None
        self._scheduled = []
        self.scheduled_table.setRowCount(0)
        self.status_label.setText(
            "Source changed. Reload the selected leave year; references will be validated against that source."
        )

    def _launch(self, kind, function):
        self._revision += 1
        revision = self._revision
        task = _Task(revision, kind, function)
        self._tasks[revision] = task
        task.signals.finished.connect(self._finished)
        task.signals.failed.connect(self._failed)
        self.progress.show()
        QThreadPool.globalInstance().start(task)

    def load_source(self):
        self._timer.stop()
        self._clear_results()
        self.session = None
        self._set_loading(True)
        self.status_label.setText("Loading the selected leave year read-only...")
        backend, data_dir, year = self.backend, self.data_dir, self.year
        self._launch("load", lambda: load_planning_snapshot(backend, data_dir, year))

    def set_snapshot(self, snapshot: dict):
        """Install a snapshot, retaining old reference hashes for stale checks."""
        self._updating = True
        try:
            self.session = PlanningSession(snapshot, today=self.today, saved_fingerprint=self._saved_fingerprint)
            if self._saved_fingerprint is None:
                self._saved_fingerprint = self.session.saved_fingerprint
            initial = self._definition_source is None
            if initial:
                self._definition_source = source_identity(snapshot)
            start = QDate.fromString(snapshot["leave_year_start"], "yyyy-MM-dd")
            end = QDate.fromString(snapshot["leave_year_end"], "yyyy-MM-dd")
            for edit in (self.cutoff_edit, self.horizon_edit):
                edit.setDateRange(start, end)
            if initial:
                self.cutoff_edit.setDate(QDate.fromString(self.session.definition.cutoff, "yyyy-MM-dd"))
                self.horizon_edit.setDate(end)
        finally:
            self._updating = False
        self._refresh_scheduled()
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _refresh_scheduled(self):
        if self.session is None:
            return
        scheduled = scheduled_transactions(
            self.session.snapshot,
            self.cutoff_edit.date().toString("yyyy-MM-dd"),
            self.horizon_edit.date().toString("yyyy-MM-dd"),
        )
        if scheduled == self._scheduled:
            return
        self._scheduled = scheduled
        columns = [
            ("id", "Original ID"),
            ("date", "Scheduled date"),
            ("category", "Category"),
            ("hours", "Hours"),
            ("status", "Status"),
            ("description", "Note"),
        ]
        old = self.scheduled_table
        index = self.editor_tabs.indexOf(old)
        self.scheduled_table = table_widget(self._scheduled, columns)
        self.scheduled_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scheduled_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.editor_tabs.removeTab(index)
        self.editor_tabs.insertTab(index, self.scheduled_table, "Scheduled originals (select to replace/remove)")
        old.deleteLater()

    def _clear_results(self):
        if self.session:
            self.session.result = None
        self._views = {}
        for table in self.tables.values():
            table.setRowCount(0)
        self.chart_image.set_source_pixmap(QPixmap())
        self.chart_image.clear()
        self.chart_image.setText("No current projection")
        self.result_changed.emit()

    def _changed(self, *_args):
        if self._updating or self._closed:
            return
        self._revision += 1  # Invalidate old workers before the debounce fires.
        self._clear_results()
        self.modified_label.setText("Modified since last export/import")
        self.status_label.setText("Draft changed; recalculating daily closing balances...")
        self._timer.start()

    def _reserve_changed(self, text):
        if self._updating:
            return
        key = self.category_combo.currentData()
        if text.strip():
            self._draft_reserves[key] = text
        else:
            self._draft_reserves.pop(key, None)
        self._changed()

    def _category_changed(self, *_args):
        self.reserve_edit.blockSignals(True)
        self.reserve_edit.setText(str(self._draft_reserves.get(self.category_combo.currentData(), "")))
        self.reserve_edit.blockSignals(False)
        self._render_result()

    def _cell_changed(self, row, column):
        if self._updating:
            return
        if column == 6:
            self._capture_references(row)
        self._changed()

    def _capture_references(self, row):
        if self.session is None:
            return
        row_id = self.scenario_table.item(row, 0).text()
        ids = [value.strip() for value in self.scenario_table.item(row, 6).text().split(",") if value.strip()]
        originals = {str(tx.get("id")): tx for tx in self.session.snapshot.get("transactions", [])}
        self._fingerprints[row_id] = {key: transaction_fingerprint(originals[key]) for key in ids if key in originals}

    def _collect_definition(self):
        if self.session is None:
            raise PlanningValidationError([{"field": "snapshot", "message": "Load the selected leave year first."}])
        rows = []
        for row in range(self.scenario_table.rowCount()):

            def item(column):
                return self.scenario_table.item(row, column).text()

            row_id = item(0)
            operation = self.scenario_table.cellWidget(row, 1).currentData()
            rows.append(
                {
                    "row_id": row_id,
                    "operation": operation,
                    "date": item(2),
                    "category": self.scenario_table.cellWidget(row, 3).currentData(),
                    "hours": item(4),
                    "note": item(5),
                    "original_ids": [value.strip() for value in item(6).split(",") if value.strip()],
                    "original_fingerprints": deepcopy(self._fingerprints.get(row_id, {})),
                    "earned_transaction_id": item(8).strip() or None,
                }
            )
        return {
            "schema_version": 1,
            "name": self.name_edit.text(),
            "source": deepcopy(self._definition_source),
            "cutoff": self.cutoff_edit.date().toString("yyyy-MM-dd"),
            "horizon": self.horizon_edit.date().toString("yyyy-MM-dd"),
            "reserves": deepcopy(self._draft_reserves),
            "operations": rows,
            "assumptions": deepcopy(self.session.definition.assumptions),
        }

    def recalculate(self):
        if self._updating or self._closed:
            return
        self._timer.stop()
        try:
            document = self._collect_definition()
        except PlanningValidationError as exc:
            self._show_errors(exc.errors)
            return
        snapshot, today = deepcopy(self.session.snapshot), self.today
        self._refresh_scheduled()
        self._clear_results()
        self.status_label.setText("Calculating baseline and scenario from the same snapshot...")

        def calculate():
            session = PlanningSession(snapshot, today=today, definition=document)
            return session.definition, session.calculate()

        self._launch("calculate", calculate)

    @Slot(int, str, object)
    def _finished(self, revision, kind, value):
        self._tasks.pop(revision, None)
        if revision != self._revision or self._closed:
            return
        self.progress.hide()
        if kind == "load":
            self._set_loading(False)
            self.set_snapshot(value)
            return
        if kind == "import":
            self._set_loading(False)
            self._install_import(value)
            return
        definition, result = value
        self.session.set_definition(definition)
        self.session.result = result
        self._updating = True
        for row in range(self.scenario_table.rowCount()):
            self.scenario_table.item(row, 7).setText("Valid input")
        self._updating = False
        self.modified_label.setText(
            "Modified since last export/import"
            if self.session.modified
            else "Session only; unchanged since export/import"
        )
        self._render_result()

    @Slot(int, str, object)
    def _failed(self, revision, kind, errors):
        self._tasks.pop(revision, None)
        if revision == self._revision and not self._closed:
            self._set_loading(False)
            self.progress.hide()
            if kind == "import":
                self.status_label.setText(
                    "Import rejected; the active scenario is unchanged. "
                    + "; ".join(item["message"] for item in errors)
                )
                return
            self._clear_results()
            self._show_errors(errors)

    def _show_errors(self, errors):
        self.status_label.setText(
            "Invalid input: "
            + "; ".join(f"{item.get('row_id') or item.get('field')}: {item['message']}" for item in errors)
        )
        self._updating = True
        for row in range(self.scenario_table.rowCount()):
            row_id = self.scenario_table.item(row, 0).text()
            messages = [f"{item.get('field')}: {item['message']}" for item in errors if item.get("row_id") == row_id]
            item = self.scenario_table.item(row, 7)
            item.setText("; ".join(messages))
            item.setToolTip(item.text())
        self._updating = False

    def cancel(self):
        self._revision += 1
        self._timer.stop()
        self.progress.hide()
        self._set_loading(False)
        self._clear_results()
        self.status_label.setText("Canceled. The draft is retained; no leave data was changed.")

    def shutdown(self):
        self.cancel()
        self._closed = True
        for window in list(self._charts):
            window.close()

    def _set_loading(self, loading):
        self._loading = loading
        for widget in (
            self.name_edit,
            self.cutoff_edit,
            self.horizon_edit,
            self.category_combo,
            self.reserve_edit,
            self.editor_tabs,
            self.add_button,
            self.replace_button,
            self.remove_button,
            self.delete_button,
            self.reset_button,
            self.resolve_button,
            self.calculate_button,
            self.export_button,
            self.import_button,
        ):
            widget.setEnabled(not loading)

    def _append_operation(self, operation, *, notify=True):
        self._updating = True
        row = self.scenario_table.rowCount()
        self.scenario_table.insertRow(row)
        original = next((tx for tx in self._scheduled if str(tx.get("id")) in operation.original_ids), {})
        values = {
            0: operation.row_id,
            2: operation.date or original.get("date", ""),
            4: str(operation.hours),
            5: operation.note,
            6: ", ".join(operation.original_ids),
            7: "",
            8: operation.earned_transaction_id or "",
        }
        for column, value in values.items():
            item = QTableWidgetItem(value)
            if column in {0, 7}:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setToolTip(value)
            self.scenario_table.setItem(row, column, item)
        operation_combo = QComboBox()
        for key, label in (("add", "Add"), ("replace", "Replace"), ("remove", "Remove")):
            operation_combo.addItem(label, key)
        operation_combo.setCurrentIndex(operation_combo.findData(operation.operation))
        operation_combo.currentIndexChanged.connect(
            lambda _index, row_id=operation.row_id: self._operation_changed(row_id)
        )
        self.scenario_table.setCellWidget(row, 1, operation_combo)
        category_combo = QComboBox()
        for key, label in category_options():
            category_combo.addItem(label, key)
        category_combo.setCurrentIndex(
            max(
                0,
                category_combo.findData(
                    operation.category or original.get("category") or self.category_combo.currentData()
                ),
            )
        )
        category_combo.currentIndexChanged.connect(self._changed)
        self.scenario_table.setCellWidget(row, 3, category_combo)
        self._fingerprints[operation.row_id] = deepcopy(operation.original_fingerprints)
        self._updating = False
        self._operation_changed(operation.row_id, notify=notify)

    def _operation_changed(self, row_id, *, notify=True):
        for row in range(self.scenario_table.rowCount()):
            if self.scenario_table.item(row, 0).text() != row_id:
                continue
            removal = self.scenario_table.cellWidget(row, 1).currentData() == "remove"
            self._updating = True
            for column in (2, 4):
                item = self.scenario_table.item(row, column)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable if removal else item.flags() | Qt.ItemIsEditable)
            self.scenario_table.cellWidget(row, 3).setEnabled(not removal)
            if removal:
                self.scenario_table.item(row, 4).setText("0")
            self._updating = False
            break
        if notify:
            self._changed()

    def add_tentative(self):
        if self.session is None:
            self._show_errors([{"field": "snapshot", "message": "Load a leave year first."}])
            return
        cutoff = self.cutoff_edit.date().toPython()
        hours = self.session.result.assumptions.get("daily_work_hours") if self.session.result else ""
        operation = make_operation(
            self.session.snapshot,
            row_id="tentative-" + uuid4().hex[:12],
            operation="add",
            date=(cutoff + timedelta(days=1)).isoformat(),
            category=self.category_combo.currentData(),
            hours=hours if hours is not None else "",
        )
        self._append_operation(operation)
        self.editor_tabs.setCurrentWidget(self.scenario_table)

    def _selected_scheduled(self):
        rows = []
        for selected in self.scheduled_table.selectionModel().selectedRows():
            item = self.scheduled_table.item(selected.row(), 0)
            source_index = item.data(Qt.UserRole + 1)
            if isinstance(source_index, int) and 0 <= source_index < len(self._scheduled):
                rows.append(self._scheduled[source_index])
        return sorted(rows, key=lambda tx: (tx["date"], str(tx["id"])))

    def add_selected(self, operation):
        originals = self._selected_scheduled()
        if not originals or self.session is None:
            self.status_label.setText(
                "Select original absence rows in Scheduled originals, then choose Replace or Remove."
            )
            self.editor_tabs.setCurrentWidget(self.scheduled_table)
            return
        first = originals[0]
        op = make_operation(
            self.session.snapshot,
            row_id="tentative-" + uuid4().hex[:12],
            operation=operation,
            date=first["date"] if operation == "replace" else None,
            category=first["category"] if operation == "replace" else None,
            hours=sum(float(tx["hours"]) for tx in originals) if operation == "replace" else 0,
            original_ids=tuple(str(tx["id"]) for tx in originals),
        )
        self._append_operation(op)
        self.editor_tabs.setCurrentWidget(self.scenario_table)

    def delete_selected(self):
        selected = sorted({index.row() for index in self.scenario_table.selectionModel().selectedRows()}, reverse=True)
        if not selected and self.scenario_table.currentRow() >= 0:
            selected = [self.scenario_table.currentRow()]
        self._updating = True
        for row in selected:
            self._fingerprints.pop(self.scenario_table.item(row, 0).text(), None)
            self.scenario_table.removeRow(row)
        self._updating = False
        self._changed()

    def reset_scenario(self):
        self._updating = True
        self.scenario_table.setRowCount(0)
        self._fingerprints.clear()
        if self.session:
            self._definition_source = source_identity(self.session.snapshot)
        self._updating = False
        self._changed()

    def resolve_selected(self):
        selected = self.scenario_table.selectionModel().selectedRows()
        if not selected:
            self.status_label.setText(
                "Select scenario rows to accept their listed originals from the current snapshot. Review Scheduled originals first."
            )
            return
        for index in selected:
            self._capture_references(index.row())
        self._changed()

    def _render_result(self):
        if self.session is None or self.session.result is None:
            return
        category = self.category_combo.currentData()
        self._views = self.session.rows(category)
        current = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        for title, (rows, columns) in self._views.items():
            old = self.tables[title]
            index = self.detail_tabs.indexOf(old)
            table = table_widget(rows, columns)
            self.detail_tabs.removeTab(index)
            self.detail_tabs.insertTab(index, table, title)
            self.tables[title] = table
            old.deleteLater()
        for index in range(self.detail_tabs.count()):
            if self.detail_tabs.tabText(index) == current:
                self.detail_tabs.setCurrentIndex(index)
                break
        result = self.session.result
        daily = self._views["Daily closing balances"][0]
        events = self._views["Events and provenance"][0]
        self.chart_image.set_source_pixmap(
            render_planning_chart(
                f"What-if Planner — {self.category_combo.currentText()} — {result.scenario_name}",
                daily,
                events,
                self.session.definition.reserves.get(category),
                result.cutoff,
                result.horizon,
            )
        )
        selected = next(row for row in result.categories if row.category == category)
        summary = selected.scenario

        def fmt(value):
            return "N/A" if value is None else f"{value:g}"

        text = f"Daily closing balances. Scenario horizon: {fmt(summary.horizon_balance)} h; minimum: {fmt(summary.minimum_balance)} h on {summary.minimum_date or 'N/A'}."
        if summary.first_reserve_breach:
            text += f" Reserve breached {summary.first_reserve_breach}."
        if summary.earliest_negative_date:
            text += (
                f" Insufficient leave on {summary.earliest_negative_date}: {fmt(summary.negative_shortfall)} h short."
            )
        conflicts = [row for row in result.capacity if row.excess_hours]
        if conflicts:
            text += f" Working-hour capacity conflict on {conflicts[0].date} ({conflicts[0].excess_hours:g} h excess); requested entries retained."
        if result.warnings:
            text += f" {len(result.warnings)} warning(s); see Warnings. " + " ".join(
                warning.message for warning in result.warnings[:2]
            )
        self.status_label.setText(text)
        self.result_changed.emit()

    def _default_path(self, suffix):
        name = f"fedleave-what-if-{self.year}.{suffix}"
        return str(Path(self.pdf_folder).expanduser() / name) if self.pdf_folder else name

    def export_json(self):
        if self.session is None:
            return
        try:
            definition = validate_scenario(self.session.snapshot, self._collect_definition())
            path, _ = QFileDialog.getSaveFileName(
                self, "Export scenario definition", self._default_path("json"), "Scenario JSON (*.json)"
            )
            if not path:
                return
            candidate = PlanningSession(self.session.snapshot, today=self.today, definition=definition)
            write_export(Path(path), candidate.export_json(), self.session.snapshot)
            if definition != self.session.definition:
                self.session.set_definition(definition)
            self.session.mark_saved()
            self._saved_fingerprint = self.session.saved_fingerprint
            self.modified_label.setText("Unchanged since export")
        except PlanningValidationError as exc:
            self._show_errors(exc.errors)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Export scenario", str(exc))

    def import_document(self, text: str, *, mode: str):
        """Atomically import against a supplied snapshot; file imports refresh it."""
        if self.session is None:
            raise PlanningValidationError(
                [{"field": "snapshot", "message": "Load a leave year before importing a scenario."}]
            )
        active = (
            validate_scenario(self.session.snapshot, self._collect_definition())
            if mode == "merge"
            else self.session.definition
        )
        candidate = PlanningSession(self.session.snapshot, today=self.today, definition=active)
        candidate.import_json(text, mode=mode)
        self._install_import(candidate)

    def _install_import(self, candidate):
        self._timer.stop()
        self._revision += 1
        self.session = candidate
        self._saved_fingerprint = candidate.saved_fingerprint
        definition = candidate.definition
        self._updating = True
        self.name_edit.setText(definition.name)
        start = QDate.fromString(candidate.snapshot["leave_year_start"], "yyyy-MM-dd")
        end = QDate.fromString(candidate.snapshot["leave_year_end"], "yyyy-MM-dd")
        self.cutoff_edit.setDateRange(start, end)
        self.horizon_edit.setDateRange(start, end)
        self.cutoff_edit.setDate(QDate.fromString(definition.cutoff, "yyyy-MM-dd"))
        self.horizon_edit.setDate(QDate.fromString(definition.horizon, "yyyy-MM-dd"))
        self._definition_source = deepcopy(definition.source)
        self._draft_reserves = deepcopy(definition.reserves)
        self.scenario_table.setRowCount(0)
        self._fingerprints.clear()
        self._updating = False
        self._refresh_scheduled()
        for operation in definition.operations:
            self._append_operation(operation, notify=False)
        self.modified_label.setText("Unchanged since import")
        self.source_loaded.emit(candidate.snapshot)
        self._category_changed()
        if candidate.result is None:
            self.recalculate()

    def start_import(self, path: Path, *, mode: str):
        """Read the file and recheck identities against a fresh CLI snapshot."""
        if self.session is None:
            return
        active = deepcopy(self._collect_definition()) if mode == "merge" else None
        backend, data_dir, year, today = self.backend, self.data_dir, self.year, self.today
        self._timer.stop()
        self._set_loading(True)
        self.status_label.setText("Validating the import against the current read-only source snapshot...")

        def load_import():
            text = path.read_text(encoding="utf-8")
            fresh = load_planning_snapshot(backend, data_dir, year)
            candidate = PlanningSession(fresh, today=today, definition=active)
            candidate.import_json(text, mode=mode)
            candidate.calculate()
            return candidate

        self._launch("import", load_import)

    def import_json(self):
        if self.session is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import scenario definition", self.pdf_folder, "Scenario JSON (*.json)"
        )
        if not path:
            return
        question = QMessageBox(self)
        question.setWindowTitle("Import scenario")
        question.setText(
            "Replace the current scenario or merge its operations? This changes only the in-memory scenario."
        )
        replace_button = question.addButton("Replace scenario", QMessageBox.AcceptRole)
        merge_button = question.addButton("Merge operations", QMessageBox.ActionRole)
        question.addButton(QMessageBox.Cancel)
        question.exec()
        choice = question.clickedButton()
        if choice not in {replace_button, merge_button}:
            return
        try:
            self.start_import(Path(path), mode="replace" if choice == replace_button else "merge")
        except PlanningValidationError as exc:
            self._show_errors(exc.errors)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import scenario", str(exc))

    def _save_csv_for(self, session, category, table):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save planning results as CSV", self._default_path("csv"), "CSV files (*.csv)"
        )
        if path:
            try:
                session.export_csv(Path(path), category, table)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Save planning results", str(exc))

    def save_csv(self):
        if self.session and self.session.result:
            self._save_csv_for(
                self.session,
                self.category_combo.currentData(),
                self.detail_tabs.tabText(self.detail_tabs.currentIndex()),
            )

    def open_chart(self):
        if self.session is None or self.session.result is None:
            return
        category = self.category_combo.currentData()
        rows = self._views["Daily closing balances"][0]
        frozen = PlanningSession(self.session.snapshot, today=self.today, definition=self.session.definition)
        frozen.result = self.session.result
        window = AnalyticsChartWindow(
            f"What-if Planner — {self.category_combo.currentText()}",
            self.chart_image.source_pixmap(),
            rows,
            DAILY_COLUMNS,
            self.pdf_folder,
            f"fedleave-what-if-{self.year}-{category}",
            csv_export=lambda: self._save_csv_for(frozen, category, "Daily closing balances"),
            export_target=lambda path: export_destination(Path(path), frozen.snapshot),
        )
        self._charts.append(window)
        window.destroyed.connect(lambda: self._charts.remove(window) if window in self._charts else None)
        window.show()
