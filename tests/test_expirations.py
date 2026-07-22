from __future__ import annotations

from datetime import date

import json
from pathlib import Path

from fedleave.commands.expirations import expiration_extend
from fedleave.config import Config
from fedleave.expirations import expiration_report, synchronize_expirations
from fedleave.storage import write_json


def _transaction(id: str, day: str, category: str, direction: str, hours: float) -> dict:
    return {
        "id": id,
        "date": day,
        "category": category,
        "direction": direction,
        "hours": hours,
        "description": "test",
        "status": "reconciled",
        "source": "manual",
        "created_at": f"{day}T00:00:00",
        "updated_at": f"{day}T00:00:00",
        "expiration_date": None,
        "expiration_pay_period": None,
        "earned_transaction_id": None,
    }


def _year(transactions: list[dict]) -> dict:
    return {
        "leave_year": 2026,
        "leave_year_start": "2026-01-11",
        "leave_year_end": "2027-01-09",
        "transactions": transactions,
    }


def test_expiration_engine_assigns_dates_and_fifo_links_usage() -> None:
    first = _transaction("20260120-001", "2026-01-20", "comp", "earned", 4)
    second = _transaction("20260220-001", "2026-02-20", "comp", "earned", 5)
    usage = _transaction("20260301-001", "2026-03-01", "comp", "used", 6)
    leave_year = _year([first, second, usage])

    state = synchronize_expirations(leave_year, Config().model_dump(), as_of=date(2026, 3, 2))

    assert state["changed"] is True
    assert first["expiration_date"] == "2027-01-19"
    linked_uses = [tx for tx in leave_year["transactions"] if tx["direction"] == "used"]
    assert [(tx["hours"], tx["earned_transaction_id"]) for tx in linked_uses] == [
        (4.0, first["id"]),
        (2.0, second["id"]),
    ]
    assert state["remaining"][first["id"]] == 0
    assert state["remaining"][second["id"]] == 3


def test_expiration_report_posts_configured_travel_comp_forfeiture() -> None:
    lot = _transaction("20260120-001", "2026-01-20", "travel_comp", "earned", 8)
    leave_year = _year([lot])

    report = expiration_report(leave_year, Config().model_dump(), as_of=date(2027, 2, 1))

    forfeitures = [tx for tx in leave_year["transactions"] if tx["direction"] == "forfeited"]
    assert len(forfeitures) == 1
    assert forfeitures[0]["hours"] == 8
    assert forfeitures[0]["earned_transaction_id"] == lot["id"]
    assert report["expired_or_forfeited_this_leave_year"] == 8


def test_non_expiring_time_off_award_is_not_listed() -> None:
    lot = _transaction("20260120-001", "2026-01-20", "time_off_award", "earned", 8)
    leave_year = _year([lot])

    report = expiration_report(leave_year, Config().model_dump(), as_of=date(2026, 2, 1))

    assert report["lots"] == []
    assert "time_off_award" not in report["enabled_categories"]


def test_expiration_extension_records_new_date_and_reason(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    year_dir = data_dir / "leave_years"
    year_dir.mkdir(parents=True)
    lot = _transaction("20260120-001", "2026-01-20", "travel_comp", "earned", 8)
    payload = _year([lot])
    payload["pay_periods"] = []
    write_json(year_dir / "2026.json", payload, backup=False)
    write_json(data_dir / "config.json", Config().model_dump(), backup=False)

    expiration_extend(
        id=lot["id"],
        new_date="2027-06-01",
        reason="Approved deployment extension",
        json_output=False,
        data_dir=data_dir,
    )

    saved = json.loads((year_dir / "2026.json").read_text(encoding="utf-8"))
    saved_lot = saved["transactions"][0]
    assert saved_lot["expiration_date"] == "2027-06-01"
    assert saved_lot["expiration_extension_reason"] == "Approved deployment extension"
