from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"
BACKEND = ROOT / "bin" / "fedleave"


def _run(command: list[str]) -> None:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(ROOT / "bin"), env.get("PATH", "")])
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(
            f"Screenshot command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stderr or result.stdout}"
        )


def _sample_data(data_dir: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from fedleave.config import init_config
    from fedleave.ledger import add_transaction_to_leave_year, create_transaction
    from fedleave.storage import load_json, write_json

    years = [(2024, "2024-01-14"), (2025, "2025-01-12"), (2026, "2026-01-11")]
    for index, (year, start) in enumerate(years):
        init_config(
            year=year,
            leave_year_start=start,
            annual_accrual=6,
            starting_balances={
                "annual": 150 + index * 18,
                "sick": 260 + index * 24,
                "comp": 6 + index * 2,
                "credit": 8 + index * 2,
                "travel_comp": 4 + index * 2,
                "time_off_award": 8 + index * 4,
                "religious_comp": 0,
                "restored_annual": 12 if year == 2026 else 0,
            },
            data_dir=data_dir,
        )
        path = data_dir / "leave_years" / f"{year}.json"
        leave_year = load_json(path)
        entries = [
            (f"{year}-02-06", "annual", "used", 8, "Winter annual leave"),
            (f"{year}-03-17", "sick", "used", 4, "Medical appointment"),
            (f"{year}-04-11", "credit", "earned", 3 + index, "Project support"),
            (f"{year}-04-18", "credit", "used", 2, "Credit hours used"),
            (f"{year}-05-09", "comp", "earned", 6 + index, "Release support"),
            (f"{year}-05-22", "overtime", "worked", 5 + index, "Overtime worked"),
            (f"{year}-06-12", "travel_comp", "earned", 8, "Official travel"),
            (f"{year}-06-26", "time_off_award", "earned", 8, "Time-off award"),
            (f"{year}-07-03", "annual", "used", 16 + index * 2, "Summer leave"),
            (f"{year}-07-17", "comp", "used", 3, "Comp time used"),
            (f"{year}-08-14", "annual", "used", 8, "Scheduled annual leave"),
            (f"{year}-09-04", "sick", "used", 8, "Scheduled medical leave"),
            (f"{year}-10-09", "overtime", "worked", 7 + index, "Quarter-end support"),
            (f"{year}-11-20", "annual", "used", 24, "Holiday leave"),
            (f"{year}-12-18", "annual", "used", 16, "Year-end leave"),
        ]
        existing_ids = [str(tx.get("id", "")) for tx in leave_year.get("transactions", [])]
        for day, category, direction, hours, description in entries:
            transaction = create_transaction(
                date=day,
                category=category,
                direction=direction,
                hours=hours,
                description=description,
                status="reconciled" if day <= "2026-07-22" or year < 2026 else "approved",
                source="screenshot-sample",
                existing_ids=existing_ids,
            )
            add_transaction_to_leave_year(leave_year, transaction)
            existing_ids.append(transaction.id)
        write_json(path, leave_year, backup=False)


def _chart_screenshots(data_dir: Path) -> None:
    chart_apps = {
        "annual_leave_chart": "annual-leave-chart-sample.png",
        "sick_leave_chart": "sick-leave-chart-sample.png",
        "credit_hours_chart": "credit-hours-chart-sample.png",
        "comp_time_chart": "comp-time-chart-sample.png",
        "travel_comp_chart": "travel-comp-chart-sample.png",
        "time_off_award_chart": "time-off-award-chart-sample.png",
    }
    for module, filename in chart_apps.items():
        _run(
            [
                sys.executable,
                "-m",
                module,
                "--year",
                "2026",
                "--outputFile",
                str(EXAMPLES / filename),
                "--resolution",
                "2560",
                "--data-dir",
                str(data_dir),
            ]
        )

    comparison_apps = {
        "annual": "annual-leave-yearly-comparison-sample.png",
        "sick": "sick-leave-yearly-comparison-sample.png",
        "credit": "credit-hours-yearly-comparison-sample.png",
        "comp": "comp-time-yearly-comparison-sample.png",
        "travel_comp": "travel-comp-yearly-comparison-sample.png",
        "time_off_award": "time-off-award-yearly-comparison-sample.png",
        "overtime": "overtime-yearly-comparison-sample.png",
    }
    for module, filename in comparison_apps.items():
        _run(
            [
                sys.executable,
                "-c",
                f"from yearly_leave_comparison_chart.{module} import main; main()",
                "--as-of",
                "2026-07-22",
                "--outputFile",
                str(EXAMPLES / filename),
                "--resolution",
                "2560",
                "--data-dir",
                str(data_dir),
            ]
        )

    _run(
        [
            sys.executable,
            "-m",
            "fedleave_month_report_graphic",
            "--year",
            "2026",
            "--month",
            "July",
            "--outputFile",
            str(EXAMPLES / "month-report-sample.png"),
            "--resolution",
            "2560",
            "--overwrite",
            "--data-dir",
            str(data_dir),
        ]
    )


def _capture(widget: Any, path: Path, width: int, height: int, app: Any) -> None:
    widget.resize(width, height)
    widget.show()
    for _ in range(5):
        app.processEvents()
    image = widget.grab()
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save screenshot: {path}")
    widget.close()
    app.processEvents()


def _gui_screenshots(data_dir: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication

    from fedleave_analytics.analytics import analyze_leave_year
    from fedleave.storage import load_json
    from fedleave_analytics.app import AnalyticsWindow, TransactionDialog
    import fedleave_gui.main_window as calendar_ui
    from fedleave_gui.settings import GuiSettings

    app = QApplication.instance() or QApplication([])
    settings = GuiSettings(
        fedleave_path=str(BACKEND),
        data_dir=str(data_dir),
        show_auto_accruals=False,
        font_size=11,
    )
    calendar_ui.load_settings = lambda: settings
    calendar_ui.save_settings = lambda _settings: None
    window = calendar_ui.MainWindow()
    window.year = 2026
    window.month = 7
    window.balance_as_of = window.today
    window.refresh()
    _capture(window, EXAMPLES / "fedleave-calendar-main-screen.png", 1920, 1080, app)

    day = {
        "date": "2026-07-17",
        "entries": [
            {"category": "annual", "direction": "used", "hours": 8, "description": "Summer leave"},
            {"category": "credit", "direction": "earned", "hours": 2, "description": "Late meeting"},
        ],
    }
    _capture(calendar_ui.DayEditDialog(day), EXAMPLES / "fedleave-calendar-edit-leave.png", 1200, 820, app)
    _capture(calendar_ui.PreferencesDialog(settings), EXAMPLES / "fedleave-calendar-preferences.png", 1200, 900, app)

    force_dialog = calendar_ui.ForceBalanceDialog()
    force_dialog.date_input.setDate(QDate(2026, 7, 22))
    force_dialog.hours_input.setValue(184.5)
    force_dialog.comment_input.setText("Match official payroll balance")
    _capture(force_dialog, EXAMPLES / "fedleave-calendar-force-balance.png", 1200, 720, app)

    expiration_payload = {
        "as_of": "2026-07-22",
        "earliest_expiration_date": "2026-09-12",
        "expired_or_forfeited_this_leave_year": 2,
        "lots": [
            {
                "category": "travel_comp", "earned_date": "2025-09-13", "earned_hours": 8,
                "remaining_hours": 5.5, "expiration_date": "2026-09-12",
                "pay_periods_remaining": 4, "hours_per_pay_period_to_use": 1.38,
                "transaction_id": "20250913-001",
            },
            {
                "category": "comp", "earned_date": "2026-05-09", "earned_hours": 7,
                "remaining_hours": 4, "expiration_date": "2027-05-08",
                "pay_periods_remaining": 21, "hours_per_pay_period_to_use": 0.19,
                "transaction_id": "20260509-001",
            },
        ],
    }
    _capture(
        calendar_ui.ExpirationStatusDialog(expiration_payload, [1, 3, 6, 12]),
        EXAMPLES / "fedleave-calendar-expiring-leave.png",
        1600,
        900,
        app,
    )

    transactions = [
        {
            "id": "20260703-001", "date": "2026-07-03", "category": "annual",
            "direction": "used", "hours": 20, "status": "reconciled",
            "source": "screenshot-sample", "description": "Summer leave",
        },
        {
            "id": "20260717-001", "date": "2026-07-17", "category": "comp",
            "direction": "used", "hours": 3, "status": "reconciled",
            "source": "screenshot-sample", "description": "Comp time used",
        },
    ]
    _capture(
        calendar_ui.LeaveTransactionsDialog(
            calendar_ui.date(2026, 7, 1), calendar_ui.date(2026, 7, 31), transactions
        ),
        EXAMPLES / "fedleave-calendar-transactions.png",
        1600,
        900,
        app,
    )

    payload = load_json(data_dir / "leave_years" / "2026.json")
    analytics_data = analyze_leave_year(
        {
            "year": 2026,
            "leave_year_start": payload["leave_year_start"],
            "leave_year_end": payload["leave_year_end"],
            "transactions": payload["transactions"],
            "available_leave_years": [2024, 2025, 2026],
        }
    )
    analytics = AnalyticsWindow(BACKEND, str(data_dir), 2026, font_size=11, auto_load=False)
    analytics.set_data(analytics_data)
    _capture(analytics, EXAMPLES / "fedleave-analytics-main.png", 1920, 1080, app)

    detail_rows = analytics_data["transactions"][:8]
    _capture(
        TransactionDialog(detail_rows),
        EXAMPLES / "fedleave-analytics-supporting-transactions.png",
        1600,
        900,
        app,
    )


def main() -> int:
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fedleave-readme-") as temp_name:
        data_dir = Path(temp_name) / "data"
        _sample_data(data_dir)
        _chart_screenshots(data_dir)
        _gui_screenshots(data_dir)
    print(f"Updated README screenshots in {EXAMPLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
