from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .resources import window_icon
from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("FedLeave Calendar")
    app.setOrganizationName("fedleave")
    app.setWindowIcon(window_icon())
    window = MainWindow()
    window.show()
    window.start_background_checks()
    return app.exec()
