"""Planner context comes through the canonical CLI and never writes a store."""

import json

from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.cli_helpers import read_snapshot_payload
from leave_year_support import save, store, tree, tx


def test_snapshot_adds_schedule_rules_and_cached_holidays_without_writing(tmp_path):
    ledger, config = store(tmp_path)
    (tmp_path / "holiday_cache").mkdir()
    cache = tmp_path / "holiday_cache/federal_holidays_2026.json"
    cache.write_text(json.dumps({"holidays": [{"observed_date": "2026-07-03", "name": "Observed holiday"}]}))
    ledger["annual_leave_accrual_hours"] = 4
    ledger["transactions"] = [tx("old", "2026-02-02", "annual", "used", 2, history=[{"old": True}], void=True)]
    save(tmp_path, 2026, ledger)
    before = tree(tmp_path)
    result = CliRunner().invoke(app, ["snapshot", "--year", "2026", "--json", "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    context = payload["calculation_context"]
    assert context["data_store"] == str(tmp_path.resolve())
    assert context["work_schedule"]["normal_workdays"] == config["defaults"]["normal_workdays"]
    assert context["holiday_coverage"] == [2026]
    assert context["holidays"][0]["observed_date"] == "2026-07-03"
    assert payload["snapshot_rules"] == config
    assert any(row["source"] == "auto_accrual" for row in payload["transactions"])
    assert context["synthetic_accrual_ids"]
    assert all(row["id"] != "old" for row in payload["transactions"])
    assert tree(tmp_path) == before
    assert read_snapshot_payload(2026, tmp_path) == payload
    assert tree(tmp_path) == before


def test_snapshot_does_not_initialize_missing_store(tmp_path):
    missing = tmp_path / "missing"
    result = CliRunner().invoke(app, ["snapshot", "--year", "2026", "--json", "--data-dir", str(missing)])
    assert result.exit_code != 0
    assert not missing.exists()


def test_missing_context_and_invalid_holiday_cache_are_explicit(tmp_path):
    store(tmp_path)
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "holiday_cache").mkdir()
    (tmp_path / "holiday_cache/federal_holidays_2026.json").write_text("not json")
    before = tree(tmp_path)
    payload = read_snapshot_payload(2026, tmp_path)
    codes = {row["code"] for row in payload["calculation_context"]["warnings"]}
    assert {"MISSING_SCHEDULE_CONTEXT", "INVALID_HOLIDAY_CACHE", "MISSING_HOLIDAY_CONTEXT"} <= codes
    assert payload["calculation_context"]["holiday_coverage"] == []
    assert tree(tmp_path) == before


def test_snapshot_reads_os_read_only_files_and_existing_read_lock(tmp_path):
    store(tmp_path)
    lock = tmp_path / ".fedleave.lock"
    lock.write_text("")
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    before = tree(tmp_path)
    try:
        for path in files:
            path.chmod(0o444)
        result = CliRunner().invoke(app, ["snapshot", "--year", "2026", "--json", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert tree(tmp_path) == before
    finally:
        for path in files:
            path.chmod(0o644)
