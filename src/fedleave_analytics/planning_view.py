"""Session-only What-if Planner with cancellable, generation-bound workers."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QDate, QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
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

from fedleave.planning import (
    PlanningValidationError,
    scheduled_transactions,
    source_identity,
    transaction_fingerprint,
    validate_scenario,
)

from .action_help import ACTION_HELP
from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, render_planning_chart, table_widget
from .planning_controls import ScenarioDateDialog
from .planning_model import (
    DAILY_COLUMNS,
    PlanningSession,
    category_label,
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
        self._preserved_operations = []
        self._legacy_operations = []
        self._daily_work_hours = None
        self._pending_definition = None
        self._pending_source_hash = None
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
            edit.dateChanged.connect(self._period_changed)
        self.category_combo = QComboBox()
        for key, label in category_options():
            self.category_combo.addItem(label, key)
        self.reserve_edit = QLineEdit()
        self.reserve_edit.setPlaceholderText("Optional hours")
        self.reserve_edit.setMaximumWidth(130)
        self.name_edit.setToolTip("Name this in-memory plan. Export scenario JSON to save a copy.")
        self.cutoff_edit.setToolTip(
            "Starting date for the scenario balance. Tentative use must be strictly after this date."
        )
        self.horizon_edit.setToolTip("Last inclusive projection date within this initialized leave year.")
        self.category_combo.setToolTip(
            "Choose the category shown in charts and tables and used for new tentative entries. Categories keep separate balances."
        )
        self.reserve_edit.setToolTip(
            "Optional warning threshold for this category. A lower projected balance is reported; this does not block draft entries."
        )
        for index, (label, widget) in enumerate(
            (
                ("Scenario", self.name_edit),
                ("Starting Date", self.cutoff_edit),
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
        self.delete_button = self._button(actions, "Undo selected changes", self.delete_selected)
        self.reset_button = self._button(actions, "Reset all changes", self.reset_scenario)
        layout.addLayout(actions)
        explanation = QLabel(
            "Scheduled rows default to Unchanged; choose Remove or Replace in the row's Operation column. "
            "Add creates a Proposed row. Undo resets selected Scheduled rows or discards selected Proposed rows; "
            "Reset clears all draft changes. File > Help explains each operation."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
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
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status_label.setMinimumHeight(3 * self.status_label.fontMetrics().lineSpacing())
        status_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        status_policy.setHeightForWidth(True)
        self.status_label.setSizePolicy(status_policy)
        self.status_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.splitter = QSplitter(Qt.Vertical)
        self.editor_tabs = QTabWidget()
        self.scenario_table = QTableWidget(0, 7)
        self.scenario_table.setHorizontalHeaderLabels(
            [
                "Source",
                "Date",
                "Leave Type",
                "Hours",
                "Operation",
                "Replacement Leave Type",
                "Note",
            ]
        )
        self.scenario_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scenario_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.scenario_table.cellChanged.connect(self._cell_changed)
        self.scenario_table.cellClicked.connect(self.pick_date)
        self.scenario_table.installEventFilter(self)
        self.scenario_table.horizontalHeaderItem(0).setToolTip(
            "Scheduled rows are existing bookings. Proposed rows are tentative additions."
        )
        self.scenario_table.horizontalHeaderItem(1).setToolTip(
            "Scheduled dates are fixed. Click a Proposed Date cell, or press Space/Enter, to open a calendar."
        )
        self.scenario_table.horizontalHeaderItem(4).setToolTip(
            "Scheduled: Unchanged, Remove or Replace. Proposed: Add or Remove."
        )
        self.scenario_table.horizontalHeaderItem(5).setToolTip(
            "Enabled only for a Scheduled Replace; chooses the scenario's leave category while date and hours stay fixed."
        )
        for column, width in enumerate((95, 120, 205, 85, 130, 210, 320)):
            self.scenario_table.setColumnWidth(column, width)
        self.scenario_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.editor_tabs.addTab(self.scenario_table, "Scenario rows")
        self.splitter.addWidget(self.editor_tabs)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current projection")
        scroll.setWidget(self.chart_image)
        self.splitter.addWidget(scroll)
        self.detail_tabs = QTabWidget()
        self.tables = {}
        for title in ("Summary", "Daily closing balances"):
            table = table_widget([], [])
            self.tables[title] = table
            self.detail_tabs.addTab(table, title)
        self.splitter.addWidget(self.detail_tabs)
        self.splitter.setSizes([210, 320, 230])
        layout.addWidget(self.splitter, 1)

    @staticmethod
    def _button(layout, label, callback):
        button = QPushButton(label)
        button.setToolTip(ACTION_HELP[label])
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
        self.scenario_table.setRowCount(0)
        self._preserved_operations = []
        self._legacy_operations = []
        self._daily_work_hours = None
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
        if self.session is not None:
            try:
                self._pending_definition = self._collect_definition()
            except PlanningValidationError:
                self._pending_definition = self.session.definition.to_dict()
            self._pending_source_hash = (self._definition_source or {}).get("snapshot_fingerprint")
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
            identity = source_identity(snapshot)
            preserved = (
                self._pending_definition
                if self._pending_source_hash is not None
                and self._pending_source_hash == identity.get("snapshot_fingerprint")
                else None
            )
            try:
                self.session = PlanningSession(
                    snapshot,
                    today=self.today,
                    definition=preserved,
                    saved_fingerprint=self._saved_fingerprint,
                )
            except PlanningValidationError:
                self.session = PlanningSession(snapshot, today=self.today, saved_fingerprint=self._saved_fingerprint)
            if self._saved_fingerprint is None:
                self._saved_fingerprint = self.session.saved_fingerprint
            initial = self._definition_source is None
            self._definition_source = identity
            start = QDate.fromString(snapshot["leave_year_start"], "yyyy-MM-dd")
            end = QDate.fromString(snapshot["leave_year_end"], "yyyy-MM-dd")
            for edit in (self.cutoff_edit, self.horizon_edit):
                edit.setDateRange(start, end)
            if initial:
                self.cutoff_edit.setDate(QDate.fromString(self.session.definition.cutoff, "yyyy-MM-dd"))
                self.horizon_edit.setDate(end)
        finally:
            self._updating = False
            self._pending_definition = None
            self._pending_source_hash = None
        self._rebuild_rows(self.session.definition.operations)
        self.source_loaded.emit(snapshot)
        self.recalculate()

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

    def _row_meta(self, row):
        item = self.scenario_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _find_row(self, key):
        for row in range(self.scenario_table.rowCount()):
            meta = self._row_meta(row)
            if meta and meta.get("key") == key:
                return row
        return -1

    def _cell_changed(self, row, column):
        if self._updating:
            return
        meta = self._row_meta(row)
        if meta and meta.get("kind") == "proposed" and column in {1, 3, 6}:
            self._changed()

    def eventFilter(self, watched, event):
        if (
            watched is self.scenario_table
            and event.type() == QEvent.KeyPress
            and event.key() in {Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter}
            and self.scenario_table.currentColumn() == 1
        ):
            self.pick_date(self.scenario_table.currentRow(), 1)
            return True
        return super().eventFilter(watched, event)

    def pick_date(self, row, column):
        if column != 1 or row < 0 or self.session is None or self._loading:
            return
        meta = self._row_meta(row)
        if not meta or meta.get("kind") != "proposed":
            return
        item = self.scenario_table.item(row, column)
        if item is None:
            return
        minimum, maximum = self.cutoff_edit.date().addDays(1), self.horizon_edit.date()
        if minimum > maximum:
            self.status_label.setText(
                "No tentative date is available after cutoff through horizon. Choose an earlier cutoff or later horizon."
            )
            return
        dialog = ScenarioDateDialog(item.text(), minimum, maximum, self)
        if dialog.exec() == QDialog.Accepted:
            item.setText(dialog.selected_date())
            item.setToolTip("Click or press Space/Enter to choose a date. " + item.text())
        dialog.deleteLater()

    def _operation_dict(self, operation):
        return {
            "row_id": operation.row_id,
            "operation": operation.operation,
            "date": operation.date,
            "category": operation.category,
            "hours": operation.hours,
            "note": operation.note,
            "original_ids": list(operation.original_ids),
            "original_fingerprints": deepcopy(operation.original_fingerprints),
            "earned_transaction_id": operation.earned_transaction_id,
        }

    def _collect_operations(self):
        if self.session is None:
            raise PlanningValidationError([{"field": "snapshot", "message": "Load the selected leave year first."}])
        operations = []
        represented = set()
        for row in range(self.scenario_table.rowCount()):
            meta = self._row_meta(row)
            if meta is None:
                continue
            if meta["kind"] == "scheduled":
                original = meta["original"]
                original_id = meta["original_id"]
                represented.add(original_id)
                if meta.get("legacy"):
                    continue
                operation = self.scenario_table.cellWidget(row, 4).currentData()
                if operation == "unchanged":
                    continue
                row_id = meta.get("row_id") or "scheduled-" + uuid4().hex[:12]
                meta["row_id"] = row_id
                self.scenario_table.item(row, 0).setData(Qt.UserRole, meta)
                fingerprints = {original_id: transaction_fingerprint(original)}
                if operation == "remove":
                    operations.append(
                        {
                            "row_id": row_id,
                            "operation": "remove",
                            "date": None,
                            "category": None,
                            "hours": 0,
                            "note": str(original.get("description", "")),
                            "original_ids": [original_id],
                            "original_fingerprints": fingerprints,
                            "earned_transaction_id": None,
                        }
                    )
                    continue
                if operation == "replace":
                    replacement = self.scenario_table.cellWidget(row, 5).currentData()
                    if not replacement:
                        raise PlanningValidationError(
                            [{"row_id": row_id, "field": "category", "message": "Choose a replacement leave type."}]
                        )
                    if replacement == original.get("category"):
                        raise PlanningValidationError(
                            [
                                {
                                    "row_id": row_id,
                                    "field": "category",
                                    "message": "Replacement leave type must differ from the scheduled leave type.",
                                }
                            ]
                        )
                    operations.append(
                        {
                            "row_id": row_id,
                            "operation": "replace",
                            "date": original["date"],
                            "category": replacement,
                            "hours": original["hours"],
                            "note": str(original.get("description", "")),
                            "original_ids": [original_id],
                            "original_fingerprints": fingerprints,
                            "earned_transaction_id": None,
                        }
                    )
                continue
            operation = self.scenario_table.cellWidget(row, 4).currentData()
            if operation == "remove":
                continue
            category = self.scenario_table.cellWidget(row, 2).currentData()
            if not category:
                raise PlanningValidationError(
                    [{"row_id": meta["row_id"], "field": "category", "message": "Choose a leave type."}]
                )
            operations.append(
                {
                    "row_id": meta["row_id"],
                    "operation": "add",
                    "date": self.scenario_table.item(row, 1).text(),
                    "category": category,
                    "hours": self.scenario_table.item(row, 3).text(),
                    "note": self.scenario_table.item(row, 6).text(),
                    "original_ids": [],
                    "original_fingerprints": {},
                    "earned_transaction_id": meta.get("earned_transaction_id"),
                }
            )
        row_ids = {operation["row_id"] for operation in operations}
        for operation in self._legacy_operations:
            normalized = self._operation_dict(operation)
            if normalized["row_id"] in row_ids:
                continue
            row_ids.add(normalized["row_id"])
            operations.append(normalized)
        for operation in self._preserved_operations:
            normalized = self._operation_dict(operation)
            if represented & set(normalized.get("original_ids", ())) or normalized["row_id"] in row_ids:
                continue
            row_ids.add(normalized["row_id"])
            operations.append(normalized)
        return operations

    def _collect_definition(self):
        rows = self._collect_operations()
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
        self._clear_row_errors()
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

    def _clear_row_errors(self):
        self._updating = True
        for row in range(self.scenario_table.rowCount()):
            self._apply_row_style(row)
        self._updating = False

    def _show_errors(self, errors):
        self.status_label.setText(
            "Invalid input: "
            + "; ".join(f"{item.get('row_id') or item.get('field')}: {item['message']}" for item in errors)
        )
        by_row = {}
        for item in errors:
            by_row.setdefault(str(item.get("row_id") or ""), []).append(f"{item.get('field')}: {item['message']}")
        self._updating = True
        for row in range(self.scenario_table.rowCount()):
            meta = self._row_meta(row)
            messages = by_row.get(str(meta.get("row_id") or "")) if meta else None
            source = self.scenario_table.item(row, 0)
            if messages and source is not None:
                source.setToolTip("; ".join(messages))
                source.setForeground(QBrush(QColor("#B00020")))
            else:
                self._apply_row_style(row)
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
            self.delete_button,
            self.reset_button,
            self.resolve_button,
            self.calculate_button,
            self.export_button,
            self.import_button,
        ):
            widget.setEnabled(not loading)

    def _period_changed(self, *_args):
        if self._updating or self._closed or self.session is None:
            return
        try:
            operations = self._collect_operations()
        except PlanningValidationError:
            operations = [self._operation_dict(operation) for operation in self.session.definition.operations]
        self._rebuild_rows(operations)
        self._changed()

    def _operation_dict(self, operation):
        if isinstance(operation, dict):
            return deepcopy(operation)
        return {
            "row_id": operation.row_id,
            "operation": operation.operation,
            "date": operation.date,
            "category": operation.category,
            "hours": operation.hours,
            "note": operation.note,
            "original_ids": list(operation.original_ids),
            "original_fingerprints": deepcopy(operation.original_fingerprints),
            "earned_transaction_id": operation.earned_transaction_id,
        }

    def _rebuild_rows(self, operations):
        if self.session is None:
            return
        normalized = [self._operation_dict(operation) for operation in operations]
        cutoff = self.cutoff_edit.date().toString("yyyy-MM-dd")
        horizon = self.horizon_edit.date().toString("yyyy-MM-dd")
        scheduled = sorted(
            scheduled_transactions(self.session.snapshot, cutoff, horizon),
            key=lambda transaction: (
                str(transaction.get("date", "")),
                str(transaction.get("category", "")),
                str(transaction.get("id", "")),
                float(transaction.get("hours", 0) or 0),
            ),
        )
        single, legacy, legacy_operations, adds, preserved = {}, {}, [], [], []
        for operation in normalized:
            original_ids = tuple(operation.get("original_ids", ()))
            if operation.get("operation") == "add":
                adds.append(operation)
            elif len(original_ids) > 1:
                for original_id in original_ids:
                    legacy[original_id] = operation
                if operation["row_id"] not in {row["row_id"] for row in legacy_operations}:
                    legacy_operations.append(operation)
            elif len(original_ids) == 1:
                single[original_ids[0]] = operation
            else:
                preserved.append(operation)
        scheduled_ids = {str(transaction["id"]) for transaction in scheduled}
        for original_id, operation in single.items():
            if original_id not in scheduled_ids:
                preserved.append(operation)
        self._preserved_operations = preserved
        self._legacy_operations = legacy_operations
        rows = []
        for transaction in scheduled:
            original_id = str(transaction["id"])
            operation = single.get(original_id)
            legacy_operation = legacy.get(original_id)
            selected = operation or legacy_operation
            state = selected.get("operation", "unchanged") if selected else "unchanged"
            rows.append(
                {
                    "kind": "scheduled",
                    "key": original_id,
                    "original_id": original_id,
                    "original": transaction,
                    "row_id": selected.get("row_id") if selected else None,
                    "operation": state,
                    "replacement": selected.get("category") if state == "replace" else None,
                    "legacy": legacy_operation is not None,
                    "date": str(transaction.get("date", "")),
                    "category": str(transaction.get("category", "")),
                    "hours": transaction.get("hours", ""),
                    "note": str(transaction.get("description", "")),
                    "earned_transaction_id": None,
                }
            )
        for operation in sorted(
            adds,
            key=lambda item: (str(item.get("date") or ""), str(item.get("category") or ""), item["row_id"]),
        ):
            rows.append(
                {
                    "kind": "proposed",
                    "key": operation["row_id"],
                    "row_id": operation["row_id"],
                    "operation": "add",
                    "date": str(operation.get("date") or ""),
                    "category": str(operation.get("category") or ""),
                    "hours": operation.get("hours", ""),
                    "note": str(operation.get("note") or ""),
                    "earned_transaction_id": operation.get("earned_transaction_id"),
                    "legacy": False,
                }
            )
        self._render_rows(rows)

    @staticmethod
    def _read_only(item):
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _render_rows(self, rows):
        self._updating = True
        try:
            self.scenario_table.setRowCount(0)
            for row in rows:
                self._render_row(row)
        finally:
            self._updating = False
        for index in range(self.scenario_table.rowCount()):
            self._apply_row_style(index)

    def _render_row(self, row):
        index = self.scenario_table.rowCount()
        self.scenario_table.insertRow(index)
        scheduled = row["kind"] == "scheduled"
        source = self._read_only(QTableWidgetItem("Scheduled" if scheduled else "Proposed"))
        source.setData(
            Qt.UserRole,
            {
                key: row.get(key)
                for key in ("kind", "key", "original_id", "original", "row_id", "legacy", "earned_transaction_id")
            },
        )
        source.setToolTip(
            "Existing Scheduled leave; the baseline always keeps this booking."
            if scheduled
            else "Proposed leave in this session-only scenario; nothing is booked."
        )
        self.scenario_table.setItem(index, 0, source)
        date_item = QTableWidgetItem(row["date"])
        if scheduled:
            self._read_only(date_item)
        else:
            date_item.setToolTip(
                "Click or press Space/Enter to choose a date after the Starting Date through the horizon."
            )
        self.scenario_table.setItem(index, 1, date_item)
        if scheduled:
            leave_item = self._read_only(QTableWidgetItem(category_label(row["category"])))
            leave_item.setData(Qt.UserRole, row["category"])
            self.scenario_table.setItem(index, 2, leave_item)
        else:
            leave_combo = QComboBox()
            for key, label in category_options():
                leave_combo.addItem(label, key)
            leave_combo.setCurrentIndex(max(0, leave_combo.findData(row["category"])))
            leave_combo.currentIndexChanged.connect(self._row_widget_changed)
            self.scenario_table.setCellWidget(index, 2, leave_combo)
        hours_item = QTableWidgetItem(str(row["hours"]))
        if scheduled:
            self._read_only(hours_item)
        self.scenario_table.setItem(index, 3, hours_item)
        operation_combo = QComboBox()
        if scheduled:
            for key, label in (("unchanged", "Unchanged"), ("remove", "Remove"), ("replace", "Replace")):
                operation_combo.addItem(label, key)
        else:
            for key, label in (("add", "Add"), ("remove", "Remove")):
                operation_combo.addItem(label, key)
        operation_combo.setCurrentIndex(max(0, operation_combo.findData(row["operation"])))
        if row.get("legacy"):
            operation_combo.setEnabled(False)
            operation_combo.setToolTip(
                "Legacy combined operation. Use Reset all changes or edit/import the scenario JSON to change it."
            )
        operation_combo.currentIndexChanged.connect(lambda _index, key=row["key"]: self._operation_changed(key))
        self.scenario_table.setCellWidget(index, 4, operation_combo)
        replacement_combo = QComboBox()
        replacement_combo.addItem("—", None)
        for key, label in category_options():
            replacement_combo.addItem(label, key)
        replacement_combo.setCurrentIndex(max(0, replacement_combo.findData(row.get("replacement"))))
        replacement_combo.setEnabled(bool(scheduled and row["operation"] == "replace" and not row.get("legacy")))
        replacement_combo.currentIndexChanged.connect(self._row_widget_changed)
        self.scenario_table.setCellWidget(index, 5, replacement_combo)
        note_item = QTableWidgetItem(row["note"])
        if scheduled:
            self._read_only(note_item)
        self.scenario_table.setItem(index, 6, note_item)

    def _apply_row_style(self, row):
        meta = self._row_meta(row)
        if meta is None:
            return
        operation_combo = self.scenario_table.cellWidget(row, 4)
        operation = operation_combo.currentData() if operation_combo is not None else None
        for column in (1, 2, 3, 6):
            item = self.scenario_table.item(row, column)
            if item is None:
                continue
            font = QFont(item.font())
            font.setStrikeOut(operation == "remove")
            item.setFont(font)
            item.setForeground(QBrush(QColor("#6B6B6B" if operation == "remove" else "#000000")))
        source = self.scenario_table.item(row, 0)
        if source is not None:
            font = QFont(source.font())
            font.setBold(meta["kind"] == "proposed")
            source.setFont(font)
            source.setForeground(QBrush(QColor("#1F4E79" if meta["kind"] == "proposed" else "#000000")))
        replacement = self.scenario_table.cellWidget(row, 5)
        if replacement is not None:
            font = QFont(replacement.font())
            font.setBold(operation == "replace")
            replacement.setFont(font)

    def _operation_changed(self, key):
        if self._updating:
            return
        row = self._find_row(key)
        if row < 0:
            return
        meta = self._row_meta(row)
        operation_combo = self.scenario_table.cellWidget(row, 4)
        if meta is None or operation_combo is None:
            return
        operation = operation_combo.currentData()
        if meta["kind"] == "proposed" and operation == "remove":
            self._updating = True
            self.scenario_table.removeRow(row)
            self._updating = False
            self._changed()
            return
        replacement = self.scenario_table.cellWidget(row, 5)
        if replacement is not None:
            replacement.setEnabled(meta["kind"] == "scheduled" and operation == "replace" and not meta.get("legacy"))
        self._apply_row_style(row)
        self._changed()

    def _row_widget_changed(self, *_args):
        if not self._updating:
            self._changed()

    def add_tentative(self):
        if self.session is None:
            self._show_errors([{"field": "snapshot", "message": "Load a leave year first."}])
            return
        cutoff = self.cutoff_edit.date().toPython()
        if cutoff >= self.horizon_edit.date().toPython():
            self.status_label.setText(
                "No tentative date is available after the Starting Date through the horizon. Choose an earlier Starting Date or later horizon."
            )
            return
        try:
            operations = self._collect_operations()
        except PlanningValidationError:
            operations = [self._operation_dict(operation) for operation in self.session.definition.operations]
        hours = self._daily_work_hours if self._daily_work_hours is not None else ""
        operations.append(
            {
                "row_id": "tentative-" + uuid4().hex[:12],
                "operation": "add",
                "date": (cutoff + timedelta(days=1)).isoformat(),
                "category": self.category_combo.currentData(),
                "hours": hours if hours is not None else "",
                "note": "",
                "original_ids": [],
                "original_fingerprints": {},
                "earned_transaction_id": None,
            }
        )
        self._rebuild_rows(operations)
        self.editor_tabs.setCurrentWidget(self.scenario_table)
        self._changed()

    def delete_selected(self):
        selected = sorted({index.row() for index in self.scenario_table.selectionModel().selectedRows()}, reverse=True)
        if not selected and self.scenario_table.currentRow() >= 0:
            selected = [self.scenario_table.currentRow()]
        if not selected:
            return
        cleared_legacy = set()
        self._updating = True
        for row in selected:
            meta = self._row_meta(row)
            if meta is None:
                continue
            if meta["kind"] == "proposed":
                self.scenario_table.removeRow(row)
                continue
            if meta.get("legacy"):
                cleared_legacy.add(str(meta.get("row_id")))
            operation_combo = self.scenario_table.cellWidget(row, 4)
            if operation_combo is not None:
                operation_combo.setCurrentIndex(max(0, operation_combo.findData("unchanged")))
            replacement = self.scenario_table.cellWidget(row, 5)
            if replacement is not None:
                replacement.setCurrentIndex(0)
                replacement.setEnabled(False)
            self._apply_row_style(row)
        self._updating = False
        if cleared_legacy:
            self._legacy_operations = [
                operation for operation in self._legacy_operations if str(operation.get("row_id")) not in cleared_legacy
            ]
            try:
                operations = self._collect_operations()
            except PlanningValidationError:
                operations = []
            self._rebuild_rows(operations)
        self._changed()

    def reset_scenario(self):
        self._updating = True
        self._fingerprints.clear()
        self._preserved_operations = []
        self._legacy_operations = []
        self._daily_work_hours = None
        if self.session:
            self.session.reset()
            self._definition_source = source_identity(self.session.snapshot)
        self._updating = False
        operations = (
            [self._operation_dict(operation) for operation in self.session.definition.operations]
            if self.session
            else []
        )
        self._rebuild_rows(operations)
        self._changed()

    def resolve_selected(self):
        selected = self.scenario_table.selectionModel().selectedRows()
        if not selected:
            self.status_label.setText(
                "Select Scenario rows to revalidate their originals against the current snapshot."
            )
            return
        try:
            operations = self._collect_operations()
        except PlanningValidationError as exc:
            self._show_errors(exc.errors)
            return
        self._rebuild_rows(operations)
        self._changed()

    def _render_result(self):
        if self.session is None or self.session.result is None:
            return
        category = self.category_combo.currentData()
        self._views = self.session.rows(category)
        current = self.detail_tabs.tabText(self.detail_tabs.currentIndex())
        for title in ("Summary", "Daily closing balances"):
            rows, columns = self._views[title]
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
        self._daily_work_hours = result.assumptions.get("daily_work_hours")
        daily = self._views["Daily closing balances"][0]
        events = self._views["Events and provenance"][0]
        selected = next(row for row in result.categories if row.category == category)
        summary = selected.scenario

        def fmt(value):
            return "N/A" if value is None else f"{value:g}"

        caption = (
            "Circles: scheduled absence. Squares: tentative absence. Same-day rows share a closing balance. "
            f"Scenario ending {self.category_combo.currentText()} balance: {fmt(summary.horizon_balance)} h."
        )
        self.chart_image.set_source_pixmap(
            render_planning_chart(
                f"What-if Planner — {self.category_combo.currentText()} — {result.scenario_name}",
                daily,
                events,
                self.session.definition.reserves.get(category),
                result.cutoff,
                result.horizon,
                caption=caption,
            )
        )

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
            text += f" {len(result.warnings)} warning(s): " + " ".join(
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

    def accept_budget(self, snapshot, result):
        self.accept_option(snapshot, result, label="Leave Budget")

    def accept_option(self, snapshot, result, *, label):
        """Explicit Replace/Merge/Cancel choice, followed by atomic worker validation."""
        from .budget_model import transfer_session

        mode, current = "replace", None
        if self.session is not None:
            question = QMessageBox(self)
            question.setWindowTitle(f"Send {label} to What-if")
            question.setText(
                f"Replace the current scenario, merge {label} suggestions into it, or cancel? Merge retains existing operations and adopts the option's projection assumptions and reserves; the combined result can differ from the option alone."
            )
            replace_button = question.addButton("Replace scenario", QMessageBox.AcceptRole)
            merge_button = question.addButton("Merge operations", QMessageBox.ActionRole)
            cancel_button = question.addButton(QMessageBox.Cancel)
            question.setDefaultButton(cancel_button)
            question.exec()
            if question.clickedButton() not in (replace_button, merge_button):
                return
            if question.clickedButton() is merge_button:
                mode = "merge"
                try:
                    current = deepcopy(self._collect_definition())
                except (ValueError, TypeError) as exc:
                    self.status_label.setText(str(exc))
                    return
        self._timer.stop()
        self._set_loading(True)
        self.status_label.setText(f"Validating {label} transfer against the fresh source snapshot...")
        today = self.today
        self._launch(
            "import", lambda: transfer_session(snapshot, result, today=today, current=current, mode=mode, label=label)
        )

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
        self._rebuild_rows(definition.operations)
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
