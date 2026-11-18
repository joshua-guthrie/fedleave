import csv
import io
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog

from fedleave.usage_comparison import cumulative_usage
from fedleave_analytics.app import AnalyticsWindow
from fedleave_analytics.comparison_model import csv_document
from fedleave_analytics.planning_model import PlanningSession
from leave_year_support import source, tx
from test_planning import TODAY, scenario, snapshot


@pytest.mark.parametrize(
    "payload",
    [
        "=1+1",
        "+1+1",
        "-1+1",
        "@SUM(1,1)",
        "＝1+1",
        "＋1",
        "－1",
        "＠SUM(1,1)",
        " \t=1+1",
        "\t=1+1",
        "\r=1+1",
        "\n=1+1",
        '=1+1,"quoted"\nnext',
    ],
)
def test_comparison_csv_marks_untrusted_text_without_changing_source(payload):
    ledger = source(transactions=[tx("one", "2026-02-01", "annual", "used", 4, description=payload)])
    result = cumulative_usage(ledger, ("annual",))
    rows = list(csv.reader(io.StringIO(csv_document(result, "Source transactions"))))
    assert rows[-1][-1] == "'" + payload
    assert ledger["transactions"][0]["description"] == payload


def test_planning_csv_marks_metadata_but_keeps_json_faithful(tmp_path):
    state = snapshot()
    session = PlanningSession(state, today=TODAY, definition=scenario(state, name="=1+1"))
    session.calculate()
    target = tmp_path / "planning.csv"
    session.export_csv(target, "annual", "Daily closing balances")
    assert ["Scenario", "'=1+1"] in list(csv.reader(io.StringIO(target.read_text(encoding="utf-8"))))
    assert '"name": "=1+1"' in session.export_json()


def test_actual_analytics_csv_preserves_numbers_and_marks_text(tmp_path, monkeypatch):
    target = tmp_path / "table.csv"
    page = object()
    window = SimpleNamespace(
        pages=SimpleNamespace(currentWidget=lambda: page, currentIndex=lambda: 0),
        comparer=object(),
        data={"year": 2026},
        data_dir=None,
        pdf_folder="",
        _current_rows=[{"description": "=1+1", "hours": -2, "ordinary": "café"}],
        _current_columns=[("description", "Description"), ("hours", "Hours"), ("ordinary", "Ordinary")],
    )
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    AnalyticsWindow.save_csv(window)
    rows = list(csv.reader(io.StringIO(target.read_text(encoding="utf-8"))))
    assert rows[-1] == ["'=1+1", "-2", "café"]
    assert window._current_rows[0]["description"] == "=1+1"
