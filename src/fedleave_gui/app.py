"""Create the Qt application and start the FedLeave calendar window."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .resources import window_icon
from .settings import GuiSettings


def main(argv: list[str] | None = None) -> int:
    """Initialize Qt ownership, show the main window, and enter the event loop."""
    arguments = argv if argv is not None else sys.argv[1:]
    smoke = "--smoke-test" in arguments
    options = None
    if smoke:
        parser = argparse.ArgumentParser()
        parser.add_argument("--smoke-test", action="store_true")
        parser.add_argument("--backend", required=True)
        parser.add_argument("--data-dir", required=True)
        options = parser.parse_args(arguments)
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("FedLeave Calendar")
    app.setOrganizationName("fedleave")
    app.setWindowIcon(window_icon())
    window = (
        MainWindow(
            settings=GuiSettings(
                fedleave_path=options.backend, data_dir=options.data_dir, expiration_reminder_pay_periods=[]
            )
        )
        if options
        else MainWindow()
    )
    if smoke:
        # Fail before any error dialog can block unattended packaged tests.
        window.backend.load_month(window.year, window.month)
        window.refresh()
        if not window.month_json or not window.month_json.get("days"):
            raise RuntimeError("Calendar failed to load its selected CLI snapshot")
        window.show()
        app.processEvents()
        if window.grab().isNull():
            raise RuntimeError("Calendar failed to render")
        window.close()
        return 0
    window.show()
    window.start_initial_load()
    window.start_background_checks()
    return app.exec()
