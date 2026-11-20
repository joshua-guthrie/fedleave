"""Exports must preserve canonical bytes through hostile output aliases."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from fedleave_analytics.charts import AnalyticsChartWindow
from fedleave_gui.chart_windows import LeaveChartDialog
from fedleave_gui.main_window import MainWindow
from fedleave_month_report_graphic import report
from test_month_report_graphic import _report_data


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def link_to_ledger(destination, ledger, kind="symlink"):
    if kind == "hardlink":
        os.link(ledger, destination)
        return
    try:
        destination.symlink_to(ledger)
    except OSError as exc:
        if os.name == "nt" and exc.winerror == 1314:
            pytest.skip("Windows symlink creation requires developer mode or privileges")
        raise


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
@pytest.mark.parametrize("window_type", ["calendar", "analytics"])
@pytest.mark.parametrize("format_name", ["png", "pdf"])
def test_graphic_exports_preserve_linked_ledger(application, tmp_path, monkeypatch, link, window_type, format_name):
    ledger = tmp_path / "leave_years" / "2026.json"
    ledger.parent.mkdir()
    ledger.write_text('{"leave_year":2026,"transactions":[]}')
    destination = tmp_path / ("chosen-report." + format_name)
    link_to_ledger(destination, ledger, link)
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("white"))
    if window_type == "calendar":
        window = LeaveChartDialog("Synthetic security audit", pixmap)
    else:
        window = AnalyticsChartWindow("Synthetic security audit", pixmap, [], [])
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), ""))
    try:
        getattr(window, "save_" + format_name)()
        assert ledger.read_text() == '{"leave_year":2026,"transactions":[]}'
    finally:
        window.close()


def test_month_pdf_preserves_linked_ledger(application, tmp_path, monkeypatch):
    ledger = tmp_path / "2026.json"
    ledger.write_text('{"leave_year":2026,"transactions":[]}')
    destination = tmp_path / "month.pdf"
    os.link(ledger, destination)

    def draw(printer):
        painter = QPainter(printer)
        painter.drawText(20, 20, "Synthetic local audit")
        painter.end()

    window = SimpleNamespace(
        settings=SimpleNamespace(pdf_export_folder=str(tmp_path)), year=2026, month=7, _print_document=draw
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), ""))
    MainWindow.save_pdf(window)
    assert ledger.read_text() == '{"leave_year":2026,"transactions":[]}'


def test_report_png_predictable_temp_follows_planted_symlink(tmp_path):
    ledger = tmp_path / "2026.json"
    ledger.write_text('{"leave_year":2026,"transactions":[]}')
    destination = tmp_path / "month.png"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    link_to_ledger(temporary, ledger)
    options = report.Options(
        output_file=destination,
        year=2026,
        month=7,
        resolution=400,
        data_dir=None,
        fedleave=None,
        overwrite=False,
        quiet=True,
        verbose=False,
    )
    report.write_output(_report_data(), options)
    assert ledger.read_text() == '{"leave_year":2026,"transactions":[]}'
    assert not destination.is_symlink()


def test_export_guard_rejects_datastore_destinations_and_preserves_previous_report(tmp_path):
    from fedleave.exporting import export_file

    store = tmp_path / "store"
    store.mkdir()
    ledger = store / "2026.json"
    ledger.write_text("canonical")
    with pytest.raises(ValueError, match="outside"):
        with export_file(ledger, store):
            pytest.fail("A datastore destination must be rejected before rendering")
    report = tmp_path / "report.csv"
    report.write_text("previous")
    with pytest.raises(RuntimeError, match="renderer failed"):
        with export_file(report, store) as temporary:
            temporary.write_text("incomplete")
            raise RuntimeError("renderer failed")
    assert ledger.read_text() == "canonical"
    assert report.read_text() == "previous"
    assert not list(tmp_path.glob(".fedleave-export-*"))


def test_create_only_export_does_not_replace_a_concurrent_creator(tmp_path):
    from fedleave.exporting import export_file

    report = tmp_path / "report.csv"
    with pytest.raises(FileExistsError):
        with export_file(report, overwrite=False) as temporary:
            temporary.write_text("ours")
            report.write_text("concurrent creator")
    assert report.read_text() == "concurrent creator"


@pytest.mark.parametrize("window_type", ["calendar", "analytics", "month"])
def test_pdf_renderer_failure_preserves_report_and_releases_staging(application, tmp_path, monkeypatch, window_type):
    destination = tmp_path / "report.pdf"
    destination.write_text("previous report")
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("white"))

    def failed(printer):
        painter = QPainter(printer)
        painter.drawText(20, 20, "partial")
        painter.end()
        raise OSError("synthetic renderer failure")

    if window_type == "calendar":
        window = LeaveChartDialog("Failure test", pixmap)
    elif window_type == "analytics":
        window = AnalyticsChartWindow("Failure test", pixmap, [], [])
    else:
        window = SimpleNamespace(settings=SimpleNamespace(pdf_export_folder=str(tmp_path)), year=2026, month=7)
    monkeypatch.setattr(window, "_print_document", failed, raising=False)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    try:
        MainWindow.save_pdf(window) if window_type == "month" else window.save_pdf()
        assert destination.read_text() == "previous report"
        assert not list(tmp_path.glob(".fedleave-export-*"))
    finally:
        if window_type != "month":
            window.close()


def test_export_workspace_is_private_on_the_running_platform(tmp_path):
    from fedleave.exporting import export_file

    with export_file(tmp_path / "report.csv") as temporary:
        if os.name == "nt":
            # Inspect real native ACLs. Python's maintained Windows releases
            # implement mkdtemp's 0700 directory using a restricted DACL.
            command = (
                "$ErrorActionPreference = 'Stop'; "
                "$directory = [System.IO.DirectoryInfo]::new($env:FEDLEAVE_TEST_WORKSPACE); "
                "$acl = $directory.GetAccessControl(); "
                "$allowed = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, "
                "'S-1-5-18', 'S-1-5-32-544', 'S-1-3-4'); "
                "$rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]); "
                "$unexpected = @($rules | Where-Object { $_.IdentityReference.Value -notin $allowed }); "
                "@{protected=$acl.AreAccessRulesProtected; unexpected=$unexpected.Count} | ConvertTo-Json -Compress"
            )
            result = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                env={**os.environ, "FEDLEAVE_TEST_WORKSPACE": str(temporary.parent)},
                text=True,
                timeout=30,
            )
            security = json.loads(result)
            assert security["protected"] and security["unexpected"] == 0
        else:
            assert temporary.parent.stat().st_mode & 0o077 == 0
        temporary.write_text("private export")


@pytest.mark.parametrize("version", [(3, 11, 9), (3, 12, 3)])
def test_windows_python_without_private_mkdir_fails_before_staging(tmp_path, monkeypatch, version):
    from fedleave import exporting

    with monkeypatch.context() as platform:
        platform.setattr(exporting.os, "name", "nt")
        platform.setattr(exporting.sys, "version_info", version)
        with pytest.raises(OSError, match="Secure exports require Python"):
            with exporting.export_file(tmp_path / "report.csv"):
                pytest.fail("The renderer must not see a staging filename")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("window_type", ["calendar", "analytics", "month"])
@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_print_to_file_preserves_linked_ledger(application, tmp_path, monkeypatch, window_type, link):
    import fedleave_analytics.charts as analytics_charts
    import fedleave_gui.chart_windows as calendar_charts
    import fedleave_gui.main_window as calendar_main

    ledger = tmp_path / "2026.json"
    ledger.write_text("canonical")
    destination = tmp_path / "print.pdf"
    link_to_ledger(destination, ledger, link)

    def dialog(printer, parent):
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(destination))
        return SimpleNamespace(exec=lambda: QDialog.Accepted)

    def draw(printer):
        painter = QPainter(printer)
        try:
            painter.drawText(20, 20, "synthetic print-to-file")
        finally:
            painter.end()

    pixmap = QPixmap(8, 8)
    if window_type == "calendar":
        module = calendar_charts
        window = LeaveChartDialog("Print test", pixmap)
    elif window_type == "analytics":
        module = analytics_charts
        window = AnalyticsChartWindow("Print test", pixmap, [], [])
    else:
        module = calendar_main
        window = SimpleNamespace(_print_document=draw)
        window._print_job = lambda printer: MainWindow._print_job(window, printer)
    monkeypatch.setattr(module, "QPrintDialog", dialog)
    monkeypatch.setattr(window, "_print_document", draw)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    try:
        MainWindow.print_month(window) if window_type == "month" else window.print_chart()
        assert ledger.read_text() == "canonical"
    finally:
        if window_type != "month":
            window.close()
