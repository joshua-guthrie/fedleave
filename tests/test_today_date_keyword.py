import json
from datetime import date
from pathlib import Path

from fedleave.cli import add, balance, daily_activity, pay_period_summary
from fedleave.cli_helpers import parse_iso_date
from fedleave.config import init_config


def _init_today_data_dir(data_dir: Path) -> tuple[int, str]:
    today = date.today()
    init_config(
        year=today.year,
        leave_year_start=today.isoformat(),
        annual_accrual=6.0,
        starting_balances={
            "annual": 10.0,
            "sick": 20.0,
            "comp": 0.0,
            "credit": 0.0,
            "travel_comp": 0.0,
            "time_off_award": 0.0,
            "religious_comp": 0.0,
            "restored_annual": 0.0,
        },
        data_dir=data_dir,
    )
    return today.year, today.isoformat()


def _json_output(capsys):
    return json.loads(capsys.readouterr().out)


def test_parse_iso_date_accepts_today_keyword():
    assert parse_iso_date("today") == date.today()
    assert parse_iso_date("TODAY") == date.today()


def test_cli_date_options_accept_today_keyword(tmp_path: Path, capsys):
    data_dir = tmp_path / "data"
    year, today = _init_today_data_dir(data_dir)
    capsys.readouterr()

    add(
        year=year,
        date="today",
        category="annual",
        earned=None,
        used=2.0,
        worked=None,
        adjusted=None,
        description="Today keyword",
        json_output=True,
        data_dir=data_dir,
    )
    added = _json_output(capsys)
    assert added["transaction"]["date"] == today

    balance(year=year, as_of="today", json_output=True, data_dir=data_dir)
    balances = _json_output(capsys)
    assert balances["as_of"] == today
    assert balances["automatic_accruals_posted_through"] == today

    pay_period_summary(year=year, date="today", daily=False, json_output=True, data_dir=data_dir)
    period = _json_output(capsys)
    assert period["date"] == today

    daily_activity(year=year, date="today", json_output=True, data_dir=data_dir)
    activity = _json_output(capsys)
    assert activity["date"] == today
    assert activity["has_activity"] is True
