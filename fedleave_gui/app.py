from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("FedLeave Calendar")
    app.setOrganizationName("fedleave")
    window = MainWindow()
    window.show()
    return app.exec()
