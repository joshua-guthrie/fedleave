from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .analytics import analyze_leave_year


def _table(rows: list[dict[str, Any]]) -> QTableWidget:
    columns = list(rows[0]) if rows else ["No data"]
    table = QTableWidget(len(rows), len(columns))
    table.setHorizontalHeaderLabels([str(c).replace("_", " ").title() for c in columns])
    table.setSortingEnabled(True)
    for r, row in enumerate(rows):
        for c, column in enumerate(columns):
            item = QTableWidgetItem(str(row.get(column, "N/A")))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if isinstance(row.get(column), (int, float)) else Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(r, c, item)
    table.resizeColumnsToContents()
    return table


class AnalyticsWindow(QMainWindow):
    def __init__(self, data: dict[str, Any], font_size: int = 10) -> None:
        super().__init__()
        self.setWindowTitle("FedLeave Analytics")
        self.resize(1200, 760)
        font = self.font()
        font.setPointSize(font_size)
        self.setFont(font)
        tabs = QTabWidget()
        tabs.addTab(_table(data["months"]), "Seasonality")
        tabs.addTab(_table(data["heatmap"]), "Calendar Heatmap")
        summary = []
        for category, directions in data["lifecycle"].items():
            for direction, values in directions.items():
                summary.append({"category": category, "metric": direction, **values, "units": "hours"})
        summary.append({"category": "leave", "metric": "final quarter percentage", "through_today": data["final_quarter"]["percentage"], "future_scheduled": "N/A", "full_leave_year": data["final_quarter"]["percentage"], "units": "percent"})
        tabs.addTab(_table(summary), "Overtime and Comp")
        root = QWidget(); layout = QVBoxLayout(root); layout.addWidget(tabs); self.setCentralWidget(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only FedLeave seasonality and lifecycle analytics.")
    parser.add_argument("--backend", help="Path to the fedleave executable")
    parser.add_argument("--data-dir")
    parser.add_argument("--year", type=int)
    parser.add_argument("--font-size", type=int, default=10)
    parser.add_argument("--pdf-folder")
    args = parser.parse_args(argv)
    backend = Path(args.backend) if args.backend else Path("fedleave")
    year = args.year or __import__("datetime").date.today().year
    command = [str(backend), "list", "--year", str(year), "--json"]
    if args.data_dir: command += ["--data-dir", args.data_dir]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode: raise RuntimeError((result.stderr or result.stdout).strip())
        data = analyze_leave_year(json.loads(result.stdout))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "FedLeave Analytics", f"Could not load analytics data.\n\n{exc}")
        return 1
    app = QApplication.instance() or QApplication(sys.argv)
    window = AnalyticsWindow(data, args.font_size); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
