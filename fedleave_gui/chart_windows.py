from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPixmap, QPainter
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


class LeaveChartDialog(QDialog):
    def __init__(self, title: str, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._pixmap = pixmap
        self._base_name = "-".join(part for part in title.lower().split()) or "leave-chart"
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
        self._fit_pixmap_to_viewport()

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        self._fit_pixmap_to_viewport()

    def resizeEvent(self, event: QEvent) -> None:
        super().resizeEvent(event)
        self._fit_pixmap_to_viewport()

    def _fit_pixmap_to_viewport(self) -> None:
        viewport_size = self.scroll_area.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return
        self.image_label.setPixmap(
            self._pixmap.scaled(viewport_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def save_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Chart as PNG",
            f"{self._base_name}.png",
            "PNG files (*.png)",
        )
        if not path:
            return
        if not self._pixmap.save(path, "PNG"):
            QMessageBox.warning(self, "Save Chart", f"Could not save PNG to {path}.")

    def save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Chart as PDF",
            f"{self._base_name}.pdf",
            "PDF files (*.pdf)",
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
            painter.fillRect(printer.pageLayout().paintRectPixels(printer.resolution()), QColor("white"))
            target = printer.pageLayout().paintRectPixels(printer.resolution())
            scaled = self._pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = target.x() + max(0, (target.width() - scaled.width()) // 2)
            y = target.y() + max(0, (target.height() - scaled.height()) // 2)
            painter.drawPixmap(x, y, scaled)
        finally:
            painter.end()
