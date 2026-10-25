"""Independent workweek conservation and overlap invariants across year files."""

from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from fedleave.config import Config
from fedleave.cross_year import Snapshot, derive_carryover, manual_ledger
from fedleave.ledger import calculate_balances
from fedleave.parental import history, parental_report
from leave_year_support import tx


@given(st.integers(0, 1920), st.integers(0, 1920), st.integers(0, 1920))
def test_overlap_and_single_fmla_charge_survive_carryover(a, b, c):
    before = a / 4
    overlap = min(b / 4, 480 - before)
    after = min(c / 4, 480 - before - overlap)
    config = Config().model_dump()
    config["defaults"]["sick_leave_accrual_hours"] = 0
    config["rules"]["fmla"]["history_complete_from"] = "2026-01-01"
    source = manual_ledger(2026, "2026-01-11", 0, {}, config=config)
    source["transactions"] = [
        tx("first", "2026-07-01", "ppl", "earned", 480, scheduled_weekly_hours=40),
        tx("before", "2026-08-01", "ppl", "used", before, scheduled_weekly_hours=40),
        tx("second", "2026-10-01", "ppl", "earned", 480, scheduled_weekly_hours=40),
        tx("overlap", "2026-11-01", "ppl", "used", overlap, scheduled_weekly_hours=40),
    ]
    carried, _ = derive_carryover(source, 2027, config)
    snapshot = Snapshot(carried)
    snapshot.config, snapshot.warnings = config, []
    snapshot.entitlement_history = history(source)
    snapshot["transactions"].append(tx("after", "2027-02-01", "ppl", "used", after, scheduled_weekly_hours=40))
    total = before + overlap + after
    balances = calculate_balances(snapshot, until_date="2027-02-01")
    assert balances["ppl"] == 480 - total
    assert balances["fmla"] == -total
    report = parental_report(snapshot, config, as_of=date(2027, 2, 1))
    first, second = sorted(report["ppl_windows"], key=lambda row: row["earned_date"])
    assert first["remaining_hours"] == 480 - total
    assert second["remaining_hours"] == 480 - overlap - after
    assert calculate_balances(snapshot, until_date="2027-07-01")["ppl"] == 480 - overlap - after
    assert calculate_balances(snapshot, until_date="2027-10-01")["ppl"] == 0
