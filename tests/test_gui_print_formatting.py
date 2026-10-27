import os
import xml.etree.ElementTree as ET
from math import ceil, floor

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QFileDialog

from fedleave.ledger import TRANSACTION_CATEGORIES
from fedleave_gui.main_window import MainWindow
from fedleave_month_report_graphic.report import CATEGORY_LABELS, render_svg


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _month_json() -> dict:
    return {
        "year": 2026,
        "month": 7,
        "days": [
            {
                "date": "2026-07-01",
                "in_display_month": True,
                "holiday_name": None,
                "entries": [],
                "display_lines": [],
            }
        ],
        "pay_periods": [
            {
                "number": 14,
                "start": "2026-06-28",
                "end": "2026-07-11",
                "pay_date": "2026-07-17",
                "totals": {
                    "annual": {"earned": 6.0, "used": 2.0, "worked": 0.0, "net": 4.0},
                },
                "ending_balances": {"annual": 14.0},
            }
        ],
        "balance_as_of_today": {"balances": {"annual": 124.0}},
        "projected_balance": {"balances": {"annual": 180.0}, "use_or_lose": {"use_or_lose": 0.0}},
    }


def test_print_document_uses_landscape_svg_layout(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    window.month_json = _month_json()
    window.today = window.today.replace(year=2026, month=7, day=1)

    output = tmp_path / "month.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output))

    window._print_document(printer)

    assert printer.pageLayout().orientation() == QPageLayout.Landscape
    assert output.exists()
    assert output.stat().st_size > 0


def test_save_pdf_delegates_to_print_document(monkeypatch, tmp_path):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    window.month_json = _month_json()
    window.today = window.today.replace(year=2026, month=7, day=1)

    captured: dict[str, object] = {}

    def fake_print_document(printer: QPrinter) -> None:
        captured["printer"] = printer

    monkeypatch.setattr(window, "_print_document", fake_print_document)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(tmp_path / "month.pdf"), "PDF files (*.pdf)")
    )

    window.save_pdf()

    printer = captured["printer"]
    assert isinstance(printer, QPrinter)
    assert printer.outputFileName() == str(tmp_path / "month.pdf")
    assert printer.outputFormat() == QPrinter.PdfFormat


@pytest.mark.parametrize("page_size", [QPageSize.A4, QPageSize.Letter])
def test_exported_pdf_keeps_complete_abbreviations_inside_panel(monkeypatch, tmp_path, page_size):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()
    window.month_json = _month_json()

    # Inspect Qt's actual text geometry rather than PDF text extraction, which
    # varies with the platform's font embedding and encoding.
    root = ET.fromstring(render_svg(window._month_report_data(), 1920))
    labels = [
        element
        for element in root.findall("{http://www.w3.org/2000/svg}text")
        if float(element.get("x")) >= 1224 and float(element.get("y")) > 790
    ]
    for index, element in enumerate(labels):
        element.set("id", f"abbreviation-{index}")
    renderer = QSvgRenderer(QByteArray(ET.tostring(root)))
    panel = QRectF(1224, 790, 668, 250)
    bounds = []
    for element in labels:
        box = renderer.boundsOnElement(element.get("id"))
        assert not box.isEmpty(), element.text
        assert panel.contains(box), element.text
        assert not any(box.intersects(other) for other in bounds), element.text
        bounds.append(box)
    values = [element.text for element in labels]
    for category in TRANSACTION_CATEGORIES:
        assert CATEGORY_LABELS[category][0] in values
        assert CATEGORY_LABELS[category][1] in values
    for marker in ("Holiday", "Pay Day", "Pay Period End", "Today"):
        assert marker in values

    output = tmp_path / "month.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPageSize(page_size))
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output))

    window._print_document(printer)

    document = QPdfDocument()
    assert document.load(str(output)) == QPdfDocument.Error.None_
    assert document.pageCount() == 1
    image = document.render(0, document.pagePointSize(0).toSize() * 2)
    assert not image.isNull()
    page = printer.pageLayout().paintRectPoints()
    pdf_panel = QRectF(
        page.x() + 1224 / 1920 * page.width(),
        page.y() + 790 / 1080 * page.height(),
        668 / 1920 * page.width(),
        250 / 1080 * page.height(),
    )
    # A non-full-page QPrinter already translates the painter to the printable
    # origin before _print_document supplies its paint rectangle to QtSvg.
    if not printer.fullPage():
        pdf_panel.translate(page.topLeft())
    scale_x = image.width() / document.pagePointSize(0).width()
    scale_y = image.height() / document.pagePointSize(0).height()
    # The actual exported page must keep the margin to the panel's right white.
    # A little padding excludes antialiasing on the panel border itself.
    for x in range(ceil(pdf_panel.right() * scale_x) + 3, image.width()):
        for y in range(ceil(pdf_panel.top() * scale_y) + 3, floor(pdf_panel.bottom() * scale_y) - 3):
            assert image.pixelColor(x, y).lightness() == 255
    document.close()
    window.close()
