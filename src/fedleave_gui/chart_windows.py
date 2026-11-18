"""Display, export, and print chart images from the calendar GUI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from fedleave.exporting import export_file, render_print_job


class LeaveChartDialog(QDialog):
    """Show one full-quality chart with viewport fitting and export actions."""

    def __init__(self, title: str, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._pixmap = pixmap
        self._base_name = "-".join(part for part in title.lower().split()) or "leave-chart"
        backend = getattr(parent, "backend", None)
        self._data_dir = backend.data_directory() if backend else None
        self.setWindowTitle(f"{title} Chart")
        self.resize(1120, 840)

        layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area, 1)

        button_row = QHBoxLayout()
        self.save_png_button = QPushButton("Save PNG...")
        self.save_png_button.clicked.connect(self.save_png)
        button_row.addWidget(self.save_png_button)
        self.save_pdf_button = QPushButton("Save PDF...")
        self.save_pdf_button.clicked.connect(self.save_pdf)
        button_row.addWidget(self.save_pdf_button)
        self.print_button = QPushButton("Print...")
        self.print_button.clicked.connect(self.print_chart)
        button_row.addWidget(self.print_button)
        button_row.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)
        QTimer.singleShot(0, self._fit_pixmap_to_viewport)

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_pixmap_to_viewport)

    def resizeEvent(self, event: QEvent) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_pixmap_to_viewport)

    def _fit_pixmap_to_viewport(self) -> None:
        viewport_size = self.scroll_area.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return
        self.image_label.setPixmap(self._pixmap.scaled(viewport_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def save_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Chart as PNG",
            f"{self._base_name}.png",
            "PNG files (*.png)",
        )
        if not path:
            return
        try:
            with export_file(Path(path), self._data_dir) as destination:
                if not self._pixmap.save(str(destination), "PNG"):
                    raise OSError(f"Could not save PNG to {path}.")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Save Chart", str(exc))

    def save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Chart as PDF",
            f"{self._base_name}.pdf",
            "PDF files (*.pdf)",
        )
        if not path:
            return
        try:
            with export_file(Path(path), self._data_dir) as destination:
                printer = QPrinter(QPrinter.HighResolution)
                printer.setOutputFormat(QPrinter.PdfFormat)
                printer.setOutputFileName(str(destination))
                try:
                    self._print_document(printer)
                finally:
                    del printer
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Save Chart", str(exc))

    def print_chart(self) -> None:
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QDialog.Accepted:
            try:
                render_print_job(printer, self._print_document, self._data_dir)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "Print Chart", str(exc))

    def _print_document(self, printer: QPrinter) -> None:
        painter = QPainter(printer)
        try:
            painter.fillRect(printer.pageLayout().paintRectPixels(printer.resolution()), QColor("white"))
            target = printer.pageLayout().paintRectPixels(printer.resolution())
            scaled = self._pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = target.x() + max(0, (target.width() - scaled.width()) // 2)
            y = target.y() + max(0, (target.height() - scaled.height()) // 2)
            painter.drawPixmap(x, y, scaled)
        finally:
            painter.end()
