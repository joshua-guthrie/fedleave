from pathlib import Path
import json

from fedleave.ledger import calculate_balances, calculate_daily_activity


def test_calculate_balances_as_of_date(tmp_path: Path):
    leave_year = {
        "starting_balances": {"annual": 40.0, "sick": 20.0},
        "transactions": [
            {"date": "2026-01-10", "category": "annual", "direction": "used", "hours": 4.0},
            {"date": "2026-01-11", "category": "sick", "direction": "used", "hours": 8.0},
            {"date": "2026-01-12", "category": "annual", "direction": "earned", "hours": 6.0},
        ],
    }

    balances = calculate_balances(leave_year, until_date="2026-01-11")
    assert balances["annual"] == 36.0
    assert balances["sick"] == 12.0


def test_calculate_daily_activity(tmp_path: Path):
    leave_year = {
        "transactions": [
            {"date": "2026-01-11", "category": "annual", "direction": "used", "hours": 4.0},
            {"date": "2026-01-11", "category": "comp", "direction": "earned", "hours": 2.0},
            {"date": "2026-01-12", "category": "sick", "direction": "used", "hours": 8.0},
        ],
    }

    activity = calculate_daily_activity(leave_year, "2026-01-11")
    assert activity["earned"]["comp"] == 2.0
    assert activity["used"]["annual"] == 4.0
    assert activity["net"]["annual"] == -4.0
    assert activity["net"]["comp"] == 2.0
