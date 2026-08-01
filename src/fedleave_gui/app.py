"""Create the Qt application and start the FedLeave calendar window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .resources import window_icon


def main(argv: list[str] | None = None) -> int:
    """Initialize Qt ownership, show the main window, and enter the event loop."""
    app = QApplication(argv or sys.argv)
    app.setApplicationName("FedLeave Calendar")
    app.setOrganizationName("fedleave")
    app.setWindowIcon(window_icon())
    window = MainWindow()
    window.show()
    window.start_initial_load()
    window.start_background_checks()
    return app.exec()
