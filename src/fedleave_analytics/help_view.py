"""Offline Analytics instructions using the suite's shared resource lookup."""

from importlib.resources import files

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout


class AnalyticsHelpDialog(QDialog):
    def __init__(self, section="overview", parent=None):
        super().__init__(parent)
        self.setWindowTitle("FedLeave Analytics Help")
        self.resize(950, 730)
        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        try:
            document = files("fedleave_analytics").joinpath("help.html")
            self.browser.setHtml(document.read_text(encoding="utf-8"))
            self.browser.scrollToAnchor(section)
            self.available = True
        except FileNotFoundError:
            self.available = False
            self.browser.setHtml(
                "<h1>FedLeave Analytics Help</h1><p>The bundled help file is missing. Reinstall the complete FedLeave suite.</p>"
            )
        layout.addWidget(self.browser)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setToolTip("Close help and return to the unchanged plan.")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
