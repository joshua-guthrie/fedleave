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
from test_analytics import seasonal_payload, seasonal_tx


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
        "Planning",
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


def _seasonality_window(qtbot):
    data = analyze_leave_year(
        seasonal_payload(
            [
                seasonal_tx("comp-new", direction="earned", hours=10),
                seasonal_tx("comp-future", direction="earned", hours=2, day="2026-07-01"),
                seasonal_tx("comp-use", hours=4),
                seasonal_tx("annual-use", "annual", hours=8),
                seasonal_tx("carry", direction="earned", hours=100, source="expiration-rollover"),
            ]
        ),
        date(2026, 6, 1),
    )
    window = AnalyticsWindow(Path("fedleave"), "/exact selected data", 2026, auto_load=False)
    qtbot.addWidget(window)
    window.set_data(data)
    window.pages.setCurrentIndex(1)
    return window


def test_seasonality_exactly_two_selectors_preserve_analysis_and_option_state(qtbot, monkeypatch):
    from PySide6.QtWidgets import QComboBox

    import fedleave_analytics.app as module

    window = _seasonality_window(qtbot)
    assert len(window.seasonality_page.findChildren(QComboBox)) == 2
    assert window.seasonality_selector.currentText() == "Leave Used by Month"
    assert window.leave_type_selector.currentData() == "all-used"
    names = [window.seasonality_selector.itemText(index) for index in range(5)]
    assert names == [
        "Leave Used by Month",
        "Leave Used by Day of Week",
        "Leave Used by Pay Period",
        "Overtime Worked by Month",
        "Net Leave Accumulation by Month",
    ]
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Dropdown must not call CLI"))
    )
    window.leave_type_selector.setCurrentIndex(window.leave_type_selector.findData("comp:earned"))
    for name in names[:3]:
        window.seasonality_selector.setCurrentText(name)
        assert window.leave_type_selector.isEnabled()
        assert window.leave_type_selector.currentData() == "comp:earned"
        assert window._seasonality_result["total_hours"] == 12
    for name, key in ((names[3], "overtime_months"), (names[4], "net_accumulation")):
        window.seasonality_selector.setCurrentText(name)
        assert not window.leave_type_selector.isEnabled()
        assert window._current_rows == window.data[key]
        assert window._seasonality_result is None
    window.seasonality_selector.setCurrentText(names[0])
    assert window.leave_type_selector.currentData() == "comp:earned"
    assert window._seasonality_title == "Comp Time Earned by Month — 2026"
    assert window.seasonality_table.horizontalHeaderItem(2).text() == "Future Dated"


def test_seasonality_refresh_and_backend_registry_fallback(qtbot):
    from copy import deepcopy

    window = _seasonality_window(qtbot)
    window.leave_type_selector.setCurrentIndex(window.leave_type_selector.findData("ppl:earned"))
    assert "No matching transactions" in window.seasonality_description.text()
    data = deepcopy(window.data)
    window.set_data(data)
    assert window.leave_type_selector.currentData() == "ppl:earned"
    data["seasonality_context"]["snapshot"]["category_definitions"].pop("ppl")
    window.set_data(data)
    assert window.leave_type_selector.currentData() == "all-used"
    keys = [window.leave_type_selector.itemData(index) for index in range(window.leave_type_selector.count())]
    assert "ppl:earned" not in keys
    assert not {"annual:earned", "sick:earned", "fmla:earned"} & set(keys)


def test_seasonality_zero_data_earned_view_and_other_pages_remain_unchanged(qtbot):
    from copy import deepcopy

    window = _seasonality_window(qtbot)
    baseline = deepcopy(window.data)
    window.heatmap_selector.setCurrentIndex(window.heatmap_selector.findData("comp:used"))
    for key in ("comp:earned", "travel_comp:earned", "annual:used", "ppl:earned"):
        window.leave_type_selector.setCurrentIndex(window.leave_type_selector.findData(key))
        assert not window.seasonality_chart_image.source_pixmap().isNull()
    assert "No matching transactions" in window.seasonality_description.text()
    assert window.pages.count() == 5
    assert window.heatmap_selector.currentData() == "comp:used"
    for key in (
        "summary",
        "months",
        "weekdays",
        "pay_periods",
        "heatmap",
        "heatmap_options",
        "heatmap_series",
        "lifecycle",
        "overtime_months",
        "net_accumulation",
    ):
        assert window.data[key] == baseline[key]


def test_seasonality_sorted_drilldown_uses_only_contributing_credits(qtbot, monkeypatch):
    import fedleave_analytics.app as module

    window = _seasonality_window(qtbot)
    captured = []

    class Capture:
        def __init__(self, rows, parent):
            captured[:] = rows

        def exec(self):
            pass

    monkeypatch.setattr(module, "TransactionDialog", Capture)
    window.leave_type_selector.setCurrentIndex(window.leave_type_selector.findData("comp:earned"))
    for name in ("Leave Used by Month", "Leave Used by Day of Week", "Leave Used by Pay Period"):
        window.seasonality_selector.setCurrentText(name)
        table = window.seasonality_table
        table.sortItems(table.columnCount() - 1, Qt.DescendingOrder)
        window._seasonality_drilldown(0, 0)
        assert [row["transaction_id"] for row in captured] == ["comp-new"]
        assert sum(row["hours"] for row in captured) == 10


def test_seasonality_csv_popup_and_image_use_exact_selection(qtbot, monkeypatch, tmp_path):
    import csv

    window = _seasonality_window(qtbot)
    window.leave_type_selector.setCurrentIndex(window.leave_type_selector.findData("comp:earned"))
    target = tmp_path / "selected.csv"
    suggested = []

    def choose(*args, **kwargs):
        suggested.append(args[2])
        return str(target), "CSV"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    window.save_csv()
    with target.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert ["Category", "comp"] in rows
    assert ["Activity", "earned"] in rows and ["Time Grouping", "month"] in rows
    assert ["Cutoff", "2026-06-01"] in rows and ["Units", "hours"] in rows
    header = next(index for index, row in enumerate(rows) if row[0] == "Month")
    assert len(rows[header + 1 :]) == len(window._current_rows)
    assert sum(float(row[-1]) for row in rows[header + 1 :]) == 12
    assert "comp-earned-month" in suggested[-1]
    window.open_chart()
    chart = window._chart_windows[-1]
    assert chart.windowTitle() == "Comp Time Earned by Month — 2026"
    assert "comp-time-earned-by-month" in chart._base_name
    assert chart._pixmap.toImage() == window.seasonality_chart_image.source_pixmap().toImage()
    png = tmp_path / "selected.png"
    assert chart._pixmap.save(str(png))
    assert png.stat().st_size > 1000


def test_seasonality_loaded_from_readonly_exact_datastore_never_writes(qtbot, tmp_path, monkeypatch):
    import sysconfig

    import fedleave_analytics.app as module
    from leave_year_support import store, tree

    base = tmp_path / "selected datastore with spaces"
    store(base, transactions=[seasonal_tx("new", direction="earned", hours=10), seasonal_tx("used", hours=4)])
    backend = Path(sysconfig.get_path("scripts")) / ("fedleave.exe" if os.name == "nt" else "fedleave")
    real_run = module.subprocess.run
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", run)
    real_analyze = analyze_leave_year
    monkeypatch.setattr(module, "analyze_leave_year", lambda value: real_analyze(value, date(2026, 6, 1)))
    year_file = base / "leave_years/2026.json"
    before = tree(base)
    year_file.chmod(0o444)
    year_file.parent.chmod(0o555)
    try:
        data = module.load_analytics_data(backend, str(base), 2026)
        window = AnalyticsWindow(backend, str(base), 2026, auto_load=False)
        qtbot.addWidget(window)
        window.set_data(data)
        window.pages.setCurrentIndex(1)
        for name in list(module.SEASONALITY_GROUPINGS):
            window.seasonality_selector.setCurrentText(name)
            for key in ("all-used", "comp:earned", "comp:used", "travel_comp:earned"):
                window.leave_type_selector.setCurrentIndex(window.leave_type_selector.findData(key))
        assert calls == [[str(backend), "list", "--year", "2026", "--json", "--data-dir", str(base)]]
        assert tree(base) == before
    finally:
        year_file.parent.chmod(0o755)
        year_file.chmod(0o644)
