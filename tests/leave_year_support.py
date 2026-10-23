"""Small dated stores with independent expected balances for issue #134."""

import hashlib
import json
from datetime import date, timedelta

from fedleave.config import Config
from fedleave.payperiods import generate_pay_periods


def tx(id, day, category, direction, hours, **extra):
    return {
        "id": id,
        "date": day,
        "category": category,
        "direction": direction,
        "hours": hours,
        "status": "reconciled",
        "source": "manual",
        **extra,
    }


def store(base, year=2026, start="2026-01-11", count=26, balances=None, transactions=None, rules=None):
    base.mkdir(parents=True, exist_ok=True)
    (base / "leave_years").mkdir(exist_ok=True)
    config = Config().model_dump()
    if rules:
        for category, values in rules.items():
            config["rules"].setdefault(category, {}).update(values)
    config["defaults"]["sick_leave_accrual_hours"] = 0
    (base / "config.json").write_text(json.dumps(config))
    source = {
        "schema_version": 1,
        "leave_year": year,
        "leave_year_start": start,
        "leave_year_end": (date.fromisoformat(start) + timedelta(days=count * 14 - 1)).isoformat(),
        "pay_period_count": count,
        "pay_periods": generate_pay_periods(date.fromisoformat(start), count),
        "annual_leave_accrual_hours": 0,
        "sick_leave_accrual_hours": 0,
        "starting_balances": {} if balances is None else balances,
        "transactions": [] if transactions is None else transactions,
        "initialization": {"mode": "manual", "method": "manual", "source_leave_year": None},
    }
    save(base, year, source)
    return source, config


def save(base, year, ledger):
    (base / "leave_years" / f"{year}.json").write_text(json.dumps(ledger, indent=2))


def tree(base):
    return {
        str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "directory"
        for p in sorted(base.rglob("*"))
    }
