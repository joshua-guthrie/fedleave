from fedleave.ledger import validate_leave_year, apply_fixes_to_leave_year
import json


def make_bad_leave_year():
    return {
        "starting_balances": {"annual": 40.0},
        "transactions": [
            {"date": "2026-1-32", "category": "annual", "direction": "used", "hours": 4.0},
            {"date": "2026-01-11", "category": "badcat", "direction": "used", "hours": 4.0},
            {"date": "2026-01-12", "category": "annual", "direction": "nonsense", "hours": -3},
        ],
    }


def test_validate_find_issues():
    ly = make_bad_leave_year()
    issues = validate_leave_year(ly)
    assert any(i["type"] == "date" for i in issues)
    assert any(i["type"] == "category" for i in issues)
    assert any(i["type"] == "direction" for i in issues)


def test_apply_fixes_normalizes_dates():
    ly = {"transactions": [{"date": "2026-1-11", "category": "annual", "direction": "used", "hours": 4.0}]}
    issues = validate_leave_year(ly)
    fixed = apply_fixes_to_leave_year(ly, issues)
    assert fixed["transactions"][0]["date"] == "2026-01-11"
