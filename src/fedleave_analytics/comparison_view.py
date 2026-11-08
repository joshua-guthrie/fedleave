"""Read-only cumulative usage view in the existing Analytics companion."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from fedleave.usage_comparison import ABSENCE_CATEGORIES, cumulative_usage

from .charts import AnalyticsChartWindow, ResponsivePixmapLabel, render_cumulative_usage
from .comparison_model import cumulative_tables, export_csv
from .planning_model import export_destination
from .planning_view import _Task
from .seasonality import LABELS
from .snapshots import ReadOnlySnapshotSource


class ComparisonWidget(QWidget):
    source_loaded = Signal(object)
    progress_changed = Signal(int, str)

    def __init__(self, backend: Path, data_dir, year, pdf_folder="", *, today=None, parent=None):
        super().__init__(parent)
        self.backend, self.data_dir, self.year = backend, data_dir, year
        self.pdf_folder, self.today = pdf_folder, today or date.today()
        self.snapshot, self.result = None, None
        self._revision, self._closed, self._loading, self._updating = 0, False, False, False
        self._tasks, self._charts = {}, []
        self._cancel_event = Event()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.recalculate)
        self.progress_changed.connect(self._progress)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QHBoxLayout()
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
        label = QLabel("Absence categories")
        label.setBuddy(self.category_button)
        form.addWidget(label)
        form.addWidget(self.category_button)
        form.addStretch(1)
        layout.addLayout(form)
        explanation = QLabel(
            "Cumulative Usage sums effective used hours for the selected leave types across the whole leave year. "
            "Accruals, openings, corrections, expirations and forfeitures are not used hours. "
            "Future dated entries are included; planned or requested dates do not confirm leave was taken."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        actions = QHBoxLayout()
        self.calculate_button = self._button(
            actions, "Calculate", self.recalculate, "Recalculate from the cached read-only snapshot."
        )
        self._button(
            actions,
            "Cancel",
            self.cancel,
            "Discard the pending calculation; leave records are unchanged.",
        )
        self._button(
            actions,
            "Save Table as CSV...",
            self.save_csv,
            "Export the exact cumulative curve and its assumptions.",
        )
        actions.addStretch(1)
        layout.addLayout(actions)
        self.status_label = QLabel("Select a leave year and calculate the cumulative usage for a leave type.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.chart_image = ResponsivePixmapLabel("No current cumulative usage")
        scroll.setWidget(self.chart_image)
        layout.addWidget(scroll, 1)

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
        self.snapshot, self.result = None, None

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
        self.snapshot, self.result = None, None
        self._loading = True
        self._set_enabled(False)
        self._cancel_event = Event()
        canceled = self._cancel_event
        source = ReadOnlySnapshotSource(self.backend, self.data_dir)

        def load():
            if canceled.is_set():
                raise RuntimeError("Canceled loading.")
            return source.snapshot(self.year)

        self.status_label.setText("Loading the selected leave year read-only...")
        self._launch("load", load)

    def set_data(self, snapshot):
        self.snapshot = deepcopy(snapshot)
        self.year = snapshot["leave_year"]
        self._loading = False
        self._set_enabled(True)
        self.source_loaded.emit(snapshot)
        self.recalculate()

    def _parameters(self):
        return tuple(category for category, action in self.category_actions.items() if action.isChecked())

    def _clear_result(self):
        self.result = None
        self.chart_image.set_source_pixmap(QPixmap())
        self.chart_image.clear()

    def _changed(self, *_args):
        if self._updating or self._closed:
            return
        self._revision += 1
        self._clear_result()
        if self.snapshot is not None:
            self.status_label.setText("Calculating from the cached read-only snapshot...")
            self._timer.start()

    def recalculate(self):
        if self.snapshot is None or self._closed or self._updating:
            return
        self._timer.stop()
        self._clear_result()
        categories = self._parameters()
        snapshot = deepcopy(self.snapshot)

        def calculate():
            return cumulative_usage(snapshot, categories)

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
            self.set_data(value)
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
            message = "; ".join(row.get("message", str(row)) for row in errors)
            self.status_label.setText("Cumulative usage unavailable: " + message)

    def _render_result(self):
        self.chart_image.set_source_pixmap(render_cumulative_usage(self.result))
        summary = self.result.summary
        categories = ", ".join(self.result.parameters.categories)
        total = summary["total_hours"]
        malformed = summary["excluded_malformed"]
        self.status_label.setText(
            f"{categories} for {summary['source_year']}: {total:.6g} h cumulative from "
            f"{summary['start']} through {summary['end']}. {summary['transaction_count']} used record(s)"
            + (f"; {malformed} malformed record(s) excluded." if malformed else ".")
            + f" Warnings: {len(self.result.warnings)}. Open Chart or Save CSV for the exact curve."
        )

    def _export(self, snapshot, result, title, rows=None, columns=None):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Cumulative Usage Table",
            str(Path(self.pdf_folder or ".") / f"fedleave-cumulative-usage-{result.source['leave_year']}.csv"),
            "CSV files (*.csv)",
        )
        if path:
            try:
                export_csv(Path(path), snapshot, result, title, rows, columns)
            except (OSError, ValueError) as exc:
                self.status_label.setText(str(exc))

    def save_csv(self):
        if self.result is not None:
            self._export(self.snapshot, self.result, "Cumulative usage")

    def open_chart(self):
        if self.result is None:
            return
        snapshot, result = deepcopy((self.snapshot, self.result))
        rows, columns = cumulative_tables(result)["Cumulative usage"]
        chart = AnalyticsChartWindow(
            "Cumulative Usage",
            self.chart_image.source_pixmap(),
            rows,
            columns,
            self.pdf_folder,
            f"fedleave-cumulative-usage-{self.year}",
            csv_export=lambda: self._export(snapshot, result, "Cumulative usage"),
            export_target=lambda path: export_destination(Path(path), snapshot),
        )
        self._charts.append(chart)
        chart.destroyed.connect(lambda: self._charts.remove(chart) if chart in self._charts else None)
        chart.show()

    def _set_enabled(self, enabled):
        for widget in (self.category_button, self.calculate_button):
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
