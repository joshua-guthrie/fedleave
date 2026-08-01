import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QFileDialog

from fedleave_analytics.analytics import analyze_leave_year
from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.charts import render_bar_chart, render_heatmap, render_horizontal_bar_chart, table_widget


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _data():
    return analyze_leave_year(
        {
            "year": 2026,
            "leave_year_start": "2026-01-01",
            "leave_year_end": "2026-12-31",
            "starting_balances": {"annual": 100},
            "carryover_from_previous_year": {},
            "available_leave_years": [2025, 2026],
            "pay_periods": [{"pay_period_number": 1, "start_date": "2026-01-01", "end_date": "2026-01-14"}],
            "transactions": [
                {
                    "id": "1",
                    "date": "2026-02-03",
                    "category": "annual",
                    "direction": "used",
                    "hours": 8,
                    "status": "approved",
                    "description": "Leave",
                    "source": "manual",
                },
                {
                    "id": "2",
                    "date": "2026-10-03",
                    "category": "sick",
                    "direction": "used",
                    "hours": 4,
                    "status": "planned",
                    "description": "Appointment",
                    "source": "manual",
                },
            ],
        },
        date(2026, 6, 1),
    )


def test_main_window_has_required_pages_controls_without_backend_diagnostics():
    _application()
    window = AnalyticsWindow(
        Path("/opt/fedleave/fedleave"),
        "/data/fedleave",
        2026,
        auto_load=False,
    )
    window.set_data(_data())

    assert [window.pages.tabText(index) for index in range(window.pages.count())] == [
        "Summary",
        "Seasonality",
        "Calendar Heatmap",
        "Overtime, Comp, and Credit",
    ]
    assert window.summary_table.rowCount() == 15
    assert window.refresh_button.text() == "Refresh"
    assert window.open_chart_button.text() == "Open Chart"
    assert window.csv_button.text() == "Save Table as CSV..."
    assert not hasattr(window, "source_label")
    assert "/data/fedleave" not in window.notice_label.text()
    assert "/opt/fedleave" not in window.notice_label.text()
    assert [window.year_combo.itemData(index) for index in range(window.year_combo.count())] == [2025, 2026]


def test_seasonality_views_are_explained_and_populated():
    _application()
    window = AnalyticsWindow(Path("fedleave"), "/data", 2026, auto_load=False)
    window.set_data(_data())
    window.pages.setCurrentIndex(1)

    assert window.seasonality_table.rowCount() == 12
    assert "absence grouped by calendar month" in window.seasonality_description.text()
    assert window.seasonality_table.columnWidth(0) >= 180
    assert window.seasonality_table.columnWidth(1) >= 180
    assert window.seasonality_table.columnWidth(2) >= 180
    assert not window.seasonality_chart_image.pixmap().isNull()
    window.seasonality_selector.setCurrentText("Leave Used by Day of Week")
    assert window.seasonality_table.rowCount() == 7
    assert not window.seasonality_chart_image.source_pixmap().isNull()
    assert window.open_chart_button.isEnabled()
    assert "Final-Quarter Leave Concentration" not in [
        window.seasonality_selector.itemText(index) for index in range(window.seasonality_selector.count())
    ]


def test_chart_renderers_create_full_size_graphics():
    _application()
    data = _data()
    bars = render_bar_chart(
        "Leave Used by Month",
        data["months"],
        "month",
        [("through_today", "Through Today"), ("future_scheduled", "Future Scheduled")],
    )
    heatmap = render_heatmap("Calendar Heatmap", data["heatmap"])
    horizontal = render_horizontal_bar_chart(
        "Net Leave by Month",
        [{"month": "Jan 2026", "net": -4}, {"month": "Feb 2026", "net": 8}],
        "month",
        [("net", "Net")],
    )

    assert bars.width() == 1610
    assert bars.height() == 1000
    assert heatmap.width() == 1610
    assert heatmap.height() < 450
    assert horizontal.width() == 1610
    assert horizontal.height() == 700


def test_table_headers_match_data_alignment_and_have_role_based_widths():
    _application()
    table = table_widget(
        [{"month": "Jan 2026", "earned": 2.0, "used": 1.0, "description": "Entry"}],
        [("month", "Month"), ("earned", "Earned"), ("used", "Used"), ("description", "Description")],
    )

    assert table.horizontalHeaderItem(0).textAlignment() & Qt.AlignLeft
    assert table.item(0, 0).textAlignment() & Qt.AlignLeft
    for column in (1, 2):
        assert table.horizontalHeaderItem(column).textAlignment() & Qt.AlignRight
        assert table.item(0, column).textAlignment() & Qt.AlignRight
    assert table.columnWidth(0) >= 180
    assert table.columnWidth(1) >= 180
    assert table.columnWidth(2) >= 180

    long_headers = table_widget(
        [{"month": "Jan 2026", "credit_earned": 2, "combined_additional_work": 3}],
        [
            ("month", "Month"),
            ("credit_earned", "Credit Earned or Worked"),
            ("combined_additional_work", "Combined Additional Work"),
        ],
    )
    metrics = QFontMetrics(long_headers.horizontalHeader().font())
    for column in (1, 2):
        label = long_headers.horizontalHeaderItem(column).text()
        assert long_headers.columnWidth(column) >= metrics.horizontalAdvance(label) + 64


def test_dynamic_heatmaps_and_monthly_lifecycle_charts_are_populated():
    _application()
    window = AnalyticsWindow(Path("fedleave"), "/data", 2026, auto_load=False)
    window.set_data(_data())

    assert [window.heatmap_selector.itemText(index) for index in range(window.heatmap_selector.count())] == [
        "All Leave Used",
        "Annual — Used",
        "Sick — Used",
    ]
    window.pages.setCurrentIndex(2)
    assert window.heatmap_table.rowCount() == 2
    assert "future scheduled" not in window.heatmap_description.text().lower()
    assert window.lifecycle_tabs.count() == 7
    assert not window.overtime_comp_image.pixmap().isNull()
    assert not window.comp_month_image.pixmap().isNull()
    assert not window.credit_month_image.pixmap().isNull()
    credit_headers = [
        window.credit_month_table.horizontalHeaderItem(index).text()
        for index in range(window.credit_month_table.columnCount())
    ]
    assert "Credit Worked" not in credit_headers


def test_current_analytics_table_can_be_exported_as_csv(monkeypatch, tmp_path):
    _application()
    window = AnalyticsWindow(Path("fedleave"), "/data", 2026, auto_load=False)
    window.set_data(_data())
    output = tmp_path / "summary.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(output), "CSV files (*.csv)"))

    window.save_csv()

    content = output.read_text(encoding="utf-8")
    assert "Leave Year,2026" in content
    assert "Metric,Value,Units,Period or Date,Basis" in content
    assert "Total Leave Used or Scheduled" in content


def test_open_chart_creates_popup_with_graphic_and_data_table():
    _application()
    window = AnalyticsWindow(Path("fedleave"), "/data", 2026, auto_load=False)
    window.set_data(_data())
    window.pages.setCurrentIndex(1)

    window.open_chart()

    assert len(window._chart_windows) == 1
    chart = window._chart_windows[0]
    assert "Leave Used by Month" in chart.windowTitle()
    assert chart.centralWidget().count() == 2
    assert chart._pixmap.toImage() == window.seasonality_chart_image.source_pixmap().toImage()


def test_embedded_and_opened_charts_fit_their_available_space():
    app = _application()
    window = AnalyticsWindow(Path("fedleave"), "/data", 2026, auto_load=False)
    window.set_data(_data())
    window.pages.setCurrentIndex(1)
    window.resize(900, 700)
    window.show()
    app.processEvents()

    embedded = window.seasonality_chart_image.pixmap().size()
    assert embedded.width() <= window.seasonality_chart_image.width()
    assert embedded.height() <= window.seasonality_chart_image.height()
    sizes = window.seasonality_splitter.sizes()
    assert sizes[0] > sizes[1]

    window.open_chart()
    chart = window._chart_windows[0]
    chart.resize(500, 400)
    app.processEvents()
    first = chart.image_label.pixmap().size()
    chart.resize(900, 500)
    app.processEvents()
    second = chart.image_label.pixmap().size()

    assert first.width() <= chart.scroll_area.viewport().width()
    assert first.height() <= chart.scroll_area.viewport().height()
    assert second.width() <= chart.scroll_area.viewport().width()
    assert second.height() <= chart.scroll_area.viewport().height()
    assert second != first
