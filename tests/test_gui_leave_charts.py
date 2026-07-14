import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication, QFileDialog

from fedleave_gui.chart_windows import LeaveChartDialog
from fedleave_gui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_view_menu_includes_leave_charts_submenu(monkeypatch):
    _application()
    monkeypatch.setattr(MainWindow, "refresh", lambda self: None)
    window = MainWindow()

    view_action = next(action for action in window.menuBar().actions() if action.text() == "View")
    leave_charts_action = next(
        action for action in view_action.menu().actions() if action.menu() and action.text() == "Leave Charts"
    )
    labels = [action.text() for action in leave_charts_action.menu().actions()]

    assert labels == [
        "Annual Leave Balance",
        "Sick Leave Balance",
        "Credit Hours Balance",
        "Comp Time Balance",
        "Travel Comp Balance",
        "Time Off Award Balance",
    ]


def test_leave_chart_dialog_can_save_png(monkeypatch, tmp_path):
    _application()
    pixmap = QPixmap(320, 180)
    pixmap.fill(Qt.white)
    dialog = LeaveChartDialog("Credit Hours Balance", pixmap)

    output = tmp_path / "chart.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(output), "PNG files (*.png)"))

    dialog.save_png()

    assert output.exists()
    assert output.stat().st_size > 0


def test_leave_chart_dialog_prints_landscape_pdf(tmp_path):
    _application()
    pixmap = QPixmap(320, 180)
    pixmap.fill(Qt.white)
    dialog = LeaveChartDialog("Credit Hours Balance", pixmap)

    output = tmp_path / "chart.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output))

    dialog._print_document(printer)

    assert output.exists()
    assert output.stat().st_size > 0
