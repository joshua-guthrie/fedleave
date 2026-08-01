from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
)

from fedleave.chart_style import BACKGROUND, BLUE, BORDER, GRID_MAJOR, RED, TEXT

SERIES_COLORS = [BLUE, "#82A9D1", RED, "#D99694", "#8064A2", "#4BACC6"]
WIDTH = 1610
HEIGHT = 1000
HORIZONTAL_HEIGHT = 700
AXIS_FONT_SIZE = 10
NUMERIC_KEYS = {
    "value",
    "hours",
    "through_today",
    "future_scheduled",
    "full_leave_year",
    "full_day_total",
    "earned_or_added",
    "decreased",
    "used",
    "worked",
    "earned",
    "paid_out",
    "forfeited",
    "expired",
    "net_change",
    "leave_hours",
    "percentage",
    "original",
    "remaining_today",
    "projected_remaining",
    "age",
    "matured_lots",
    "earned_hours",
    "used_before_expiration",
    "percentage_consumed",
    "overtime_worked",
    "comp_earned",
    "credit_earned",
    "combined_additional_work",
    "pay_period",
}


class SortableTableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        own_value = self.data(Qt.UserRole)
        other_value = other.data(Qt.UserRole)
        if isinstance(own_value, (int, float)) and isinstance(other_value, (int, float)):
            return float(own_value) < float(other_value)
        return super().__lt__(other)


class ResponsivePixmapLabel(QLabel):
    """Display one source pixmap fitted to the label without losing export quality."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def set_source_pixmap(self, pixmap: QPixmap) -> None:
        self._source_pixmap = QPixmap(pixmap)
        self._fit_pixmap()

    def source_pixmap(self) -> QPixmap:
        return QPixmap(self._source_pixmap)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_pixmap()

    def _fit_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            return
        target = self.contentsRect().size()
        if target.width() < 2 or target.height() < 2:
            return
        super().setPixmap(self._source_pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))


def _display(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def table_widget(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> QTableWidget:
    table = QTableWidget(len(rows), len(columns))
    table.setMinimumHeight(1)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
    table.setHorizontalHeaderLabels([label for _key, label in columns])
    for column_index, (key, _label) in enumerate(columns):
        header = table.horizontalHeaderItem(column_index)
        if header is not None:
            header.setTextAlignment(
                Qt.AlignRight | Qt.AlignVCenter if key in NUMERIC_KEYS else Qt.AlignLeft | Qt.AlignVCenter
            )
    table.setSortingEnabled(False)
    for row_index, row in enumerate(rows):
        for column_index, (key, _label) in enumerate(columns):
            value = row.get(key)
            item = SortableTableItem(_display(value))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setData(Qt.UserRole, float(value))
            else:
                item.setTextAlignment(
                    Qt.AlignRight | Qt.AlignVCenter if key in NUMERIC_KEYS else Qt.AlignLeft | Qt.AlignVCenter
                )
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole + 1, row_index)
            table.setItem(row_index, column_index, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    font_metrics = QFontMetrics(table.horizontalHeader().font())
    for column_index, (key, label) in enumerate(columns):
        current = table.columnWidth(column_index)
        if key == "month":
            preferred = 180
        elif columns and columns[0][0] == "month" and column_index in {1, 2}:
            preferred = 180
        elif key in NUMERIC_KEYS:
            preferred = 125
        elif key in {"metric", "description", "message", "basis"}:
            preferred = 280
        elif key in {"date", "start_date", "end_date", "earned_date", "expiration", "period_or_date"}:
            preferred = 145
        elif key in {"category", "direction", "status", "timing", "source"}:
            preferred = 145
        else:
            preferred = 115
        header_width = font_metrics.horizontalAdvance(label) + 64
        table.setColumnWidth(column_index, max(current, preferred, header_width))
    table.horizontalHeader().sectionClicked.connect(lambda section, current=table: _enable_sorting(current, section))
    table.setAlternatingRowColors(True)
    return table


def _enable_sorting(table: QTableWidget, section: int) -> None:
    if table.isSortingEnabled():
        return
    table.setSortingEnabled(True)
    table.sortItems(section, Qt.AscendingOrder)


def render_bar_chart(
    title: str,
    rows: list[dict[str, Any]],
    label_key: str,
    series: list[tuple[str, str]],
) -> QPixmap:
    pixmap = QPixmap(WIDTH, HEIGHT)
    pixmap.fill(QColor(BACKGROUND))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        painter.setPen(QColor(TEXT))
        title_font = QFont(painter.font())
        title_font.setPointSize(24)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(60, 35, WIDTH - 120, 55, Qt.AlignCenter, title)

        axis_font = QFont(painter.font())
        axis_font.setPointSize(AXIS_FONT_SIZE)
        axis_font.setBold(False)
        painter.setFont(axis_font)

        left, top, right, bottom = 110, 150, WIDTH - 55, HEIGHT - 145
        values = [float(row.get(key) or 0) for row in rows for key, _label in series]
        minimum = min([0.0, *values])
        maximum = max([0.0, *values])
        if abs(maximum - minimum) < 1e-9:
            maximum = 1.0
        padding = (maximum - minimum) * 0.1
        minimum -= padding if minimum < 0 else 0
        maximum += padding

        painter.setPen(QPen(QColor(GRID_MAJOR), 1))
        for tick in range(6):
            y = top + (bottom - top) * tick / 5
            painter.drawLine(left, int(y), right, int(y))
            value = maximum - (maximum - minimum) * tick / 5
            painter.setPen(QColor(TEXT))
            painter.drawText(10, int(y) - 10, 90, 20, Qt.AlignRight | Qt.AlignVCenter, _display(value))
            painter.setPen(QPen(QColor(GRID_MAJOR), 1))

        zero_y = bottom - (0 - minimum) / (maximum - minimum) * (bottom - top)
        painter.setPen(QPen(QColor(BORDER), 2))
        painter.drawLine(left, int(zero_y), right, int(zero_y))
        painter.drawRect(left, top, right - left, bottom - top)

        count = max(1, len(rows))
        group_width = (right - left) / count
        bar_width = max(3.0, min(48.0, group_width * 0.72 / max(1, len(series))))
        for row_index, row in enumerate(rows):
            center = left + group_width * (row_index + 0.5)
            for series_index, (key, _label) in enumerate(series):
                value = float(row.get(key) or 0)
                value_y = bottom - (value - minimum) / (maximum - minimum) * (bottom - top)
                x = center + (series_index - (len(series) - 1) / 2) * bar_width - bar_width / 2
                y = min(zero_y, value_y)
                height = max(1.0, abs(zero_y - value_y))
                painter.fillRect(
                    int(x),
                    int(y),
                    max(1, int(bar_width - 2)),
                    int(height),
                    QColor(SERIES_COLORS[series_index % len(SERIES_COLORS)]),
                )
            label = str(row.get(label_key, ""))
            painter.save()
            painter.translate(int(center), bottom + 12)
            painter.rotate(-45 if count > 8 else 0)
            painter.setPen(QColor(TEXT))
            painter.drawText(-65, 0, 130, 55, Qt.AlignHCenter | Qt.AlignTop, label)
            painter.restore()

        legend_x = left
        for series_index, (_key, label) in enumerate(series):
            painter.fillRect(legend_x, 105, 22, 16, QColor(SERIES_COLORS[series_index % len(SERIES_COLORS)]))
            painter.setPen(QColor(TEXT))
            painter.drawText(legend_x + 29, 98, 210, 30, Qt.AlignLeft | Qt.AlignVCenter, label)
            legend_x += 245
    finally:
        painter.end()
    return pixmap


def render_horizontal_bar_chart(
    title: str,
    rows: list[dict[str, Any]],
    label_key: str,
    series: list[tuple[str, str]],
) -> QPixmap:
    pixmap = QPixmap(WIDTH, HORIZONTAL_HEIGHT)
    pixmap.fill(QColor(BACKGROUND))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        painter.setPen(QColor(TEXT))
        title_font = QFont(painter.font())
        title_font.setPointSize(24)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(60, 30, WIDTH - 120, 55, Qt.AlignCenter, title)

        body_font = QFont(painter.font())
        body_font.setPointSize(AXIS_FONT_SIZE)
        body_font.setBold(False)
        painter.setFont(body_font)

        left, top, right, bottom = 190, 145, WIDTH - 65, HORIZONTAL_HEIGHT - 80
        values = [float(row.get(key) or 0) for row in rows for key, _label in series]
        minimum = min([0.0, *values])
        maximum = max([0.0, *values])
        if abs(maximum - minimum) < 1e-9:
            maximum = 1.0
        padding = (maximum - minimum) * 0.08
        minimum -= padding if minimum < 0 else 0
        maximum += padding
        painter.setPen(QPen(QColor(GRID_MAJOR), 1))
        for tick in range(6):
            x = left + (right - left) * tick / 5
            painter.drawLine(int(x), top, int(x), bottom)
            painter.setPen(QColor(TEXT))
            tick_value = minimum + (maximum - minimum) * tick / 5
            painter.drawText(int(x) - 40, bottom + 8, 80, 24, Qt.AlignHCenter | Qt.AlignTop, _display(tick_value))
            painter.setPen(QPen(QColor(GRID_MAJOR), 1))

        zero_x = left + (0 - minimum) / (maximum - minimum) * (right - left)
        painter.setPen(QPen(QColor(BORDER), 2))
        painter.drawLine(int(zero_x), top, int(zero_x), bottom)

        row_height = (bottom - top) / max(1, len(rows))
        bar_height = max(3.0, min(22.0, row_height * 0.72 / max(1, len(series))))
        for row_index, row in enumerate(rows):
            center_y = top + row_height * (row_index + 0.5)
            painter.setPen(QColor(TEXT))
            painter.drawText(
                10,
                int(center_y - row_height / 2),
                left - 25,
                int(row_height),
                Qt.AlignRight | Qt.AlignVCenter,
                str(row.get(label_key, "")),
            )
            for series_index, (key, _label) in enumerate(series):
                value = float(row.get(key) or 0)
                y = center_y + (series_index - (len(series) - 1) / 2) * bar_height - bar_height / 2
                value_x = left + (value - minimum) / (maximum - minimum) * (right - left)
                bar_left = min(zero_x, value_x)
                width = max(1, int(abs(value_x - zero_x)))
                painter.fillRect(
                    int(bar_left),
                    int(y),
                    width,
                    max(1, int(bar_height - 2)),
                    QColor(SERIES_COLORS[series_index % len(SERIES_COLORS)]),
                )
                if abs(value) > 1e-9:
                    painter.setPen(QColor(TEXT))
                    label_x = int(value_x) + 5 if value >= 0 else int(value_x) - 80
                    alignment = Qt.AlignLeft if value >= 0 else Qt.AlignRight
                    painter.drawText(
                        label_x, int(y) - 2, 75, int(bar_height + 4), alignment | Qt.AlignVCenter, _display(value)
                    )

        legend_x = left
        for series_index, (_key, label) in enumerate(series):
            painter.fillRect(legend_x, 103, 22, 16, QColor(SERIES_COLORS[series_index % len(SERIES_COLORS)]))
            painter.setPen(QColor(TEXT))
            painter.drawText(legend_x + 29, 96, 210, 30, Qt.AlignLeft | Qt.AlignVCenter, label)
            legend_x += 245
        painter.setPen(QPen(QColor(BORDER), 2))
        painter.drawRect(left, top, right - left, bottom - top)
    finally:
        painter.end()
    return pixmap


def render_heatmap(title: str, rows: list[dict[str, Any]]) -> QPixmap:
    parsed = [(date.fromisoformat(str(row["date"])), row) for row in rows]
    if parsed:
        first = parsed[0][0]
        grid_start = first - timedelta(days=first.weekday())
        last = parsed[-1][0]
        weeks = ((last - grid_start).days // 7) + 1
        left, top, right = 120, 125, WIDTH - 55
        cell = min(24, max(10, int((right - left) / weeks)))
        height = top + 7 * cell + 30
    else:
        grid_start = date.today()
        left, top, right, cell, height = 120, 125, WIDTH - 55, 20, 340

    pixmap = QPixmap(WIDTH, height)
    pixmap.fill(QColor(BACKGROUND))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        painter.setPen(QColor(TEXT))
        title_font = QFont(painter.font())
        title_font.setPointSize(24)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(60, 30, WIDTH - 120, 55, Qt.AlignCenter, title)
        if not rows:
            painter.drawText(0, 0, WIDTH, height, Qt.AlignCenter, "No heatmap data")
            return pixmap

        maximum = max(float(row.get("full_day_total") or 0) for _day, row in parsed) or 1.0

        normal_font = QFont(painter.font())
        normal_font.setPointSize(9)
        painter.setFont(normal_font)
        for weekday_index, weekday in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            painter.setPen(QColor(TEXT))
            painter.drawText(25, top + weekday_index * cell, 80, cell, Qt.AlignRight | Qt.AlignVCenter, weekday)

        last_month = None
        for day, row in parsed:
            week = (day - grid_start).days // 7
            weekday = day.weekday()
            x, y = left + week * cell, top + weekday * cell
            value = float(row.get("full_day_total") or 0)
            if value <= 0:
                color = QColor(BACKGROUND)
            else:
                color = QColor(BLUE)
                color.setAlphaF(0.2 + 0.8 * min(1.0, value / maximum))
            painter.fillRect(x, y, cell - 2, cell - 2, color)
            future = float(row.get("future_scheduled") or 0) > 0
            painter.setPen(QPen(QColor(RED if future else BORDER), 2 if future else 1))
            painter.drawRect(x, y, cell - 2, cell - 2)
            if future:
                painter.setPen(QColor(RED))
                painter.drawText(x, y, cell - 2, cell - 2, Qt.AlignCenter, "F")
            month_key = day.strftime("%Y-%m")
            if month_key != last_month and day.day <= 7:
                painter.setPen(QColor(TEXT))
                painter.drawText(x, top - 26, 100, 20, Qt.AlignLeft, day.strftime("%b %Y"))
                last_month = month_key

    finally:
        painter.end()
    return pixmap


class AnalyticsChartWindow(QMainWindow):
    def __init__(
        self,
        title: str,
        pixmap: QPixmap,
        rows: list[dict[str, Any]],
        columns: list[tuple[str, str]],
        default_folder: str = "",
        base_name: str = "fedleave-analytics",
    ) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.resize(1200, 860)
        self._pixmap = pixmap
        self._default_folder = Path(default_folder).expanduser() if default_folder else Path()
        self._base_name = base_name

        tabs = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.image_label = ResponsivePixmapLabel()
        self.image_label.set_source_pixmap(pixmap)
        scroll.setWidget(self.image_label)
        self.scroll_area = scroll
        tabs.addTab(scroll, "Graphic")
        tabs.addTab(table_widget(rows, columns), "Data Table")
        self.setCentralWidget(tabs)

        file_menu = self.menuBar().addMenu("File")
        for label, callback in (
            ("Save Graphic as PNG...", self.save_png),
            ("Save Graphic as PDF...", self.save_pdf),
            ("Print...", self.print_chart),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            file_menu.addAction(action)
        file_menu.addSeparator()
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

    def _default_path(self, suffix: str) -> str:
        filename = f"{self._base_name}.{suffix}"
        return str(self._default_folder / filename) if str(self._default_folder) not in {"", "."} else filename

    def save_png(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save Graphic as PNG", self._default_path("png"), "PNG files (*.png)"
        )
        if path and not self._pixmap.save(path, "PNG"):
            QMessageBox.warning(self, "Save Graphic", f"Could not save PNG to {path}.")

    def save_pdf(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save Graphic as PDF", self._default_path("pdf"), "PDF files (*.pdf)"
        )
        if not path:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        self._print_document(printer)

    def print_chart(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.Accepted:
            self._print_document(printer)

    def _print_document(self, printer: QPrinter) -> None:
        painter = QPainter(printer)
        try:
            target = printer.pageLayout().paintRectPixels(printer.resolution())
            painter.fillRect(target, QColor(BACKGROUND))
            scaled = self._pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(
                target.x() + max(0, (target.width() - scaled.width()) // 2),
                target.y() + max(0, (target.height() - scaled.height()) // 2),
                scaled,
            )
        finally:
            painter.end()
