"""Manual creation retains its legacy independence and exact input values."""

import json
from copy import deepcopy

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from fedleave.cross_year import manual_ledger, resolve_snapshot
from fedleave.expirations import expiration_report
from fedleave.ledger import calculate_balances
from leave_year_support import store, tree

CATEGORIES = ["annual", "sick", "comp", "credit", "travel_comp", "time_off_award", "religious_comp", "restored_annual"]


@pytest.mark.parametrize("explicit", [False, True], ids=["MAN-001-019-020", "MAN-021"])
@pytest.mark.parametrize("older", ["absent", "valid", "corrupt"], ids=["MAN-007", "MAN-004-005", "MAN-008"])
def test_manual_cli_independent(tmp_path, explicit, older):
    base = tmp_path / "selected"
    if older != "absent":
        store(base, balances={"annual": 999, "travel_comp": 40})
        if older == "corrupt":
            (base / "leave_years/2026.json").write_text("invalid JSON")
    args = [
        "init",
        "--year",
        "2027",
        "--leave-year-start",
        "2027-01-10",
        "--annual-start",
        "1.25",
        "--json",
        "--data-dir",
        str(base),
    ]
    if explicit:
        args.append("--manual")
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    response = json.loads(result.output)
    assert response["initialization_mode"] == "manual" and response["source_leave_year"] is None
    assert response["warnings"] == []
    ledger = json.loads((base / "leave_years/2027.json").read_text())
    assert ledger["initialization"] == {"mode": "manual", "method": "manual", "source_leave_year": None}
    assert ledger["starting_balances"]["annual"] == 1.25
    assert ledger["starting_balances"]["travel_comp"] == 0
    assert "expiration-rollover" not in {tx["source"] for tx in ledger["transactions"]}
    assert calculate_balances(ledger, until_date="2027-01-10")["annual"] == 1.25


@pytest.mark.parametrize("category", CATEGORIES, ids=[f"MAN-002-{cat}" for cat in CATEGORIES])
@pytest.mark.parametrize(
    "hours", [0, 0.25, 0.5, 1, 40], ids=["MAN-014", "MAN-015-quarter", "MAN-015-half", "MAN-015-whole", "MAN-012"]
)
def test_manual_exact_opening(category, hours):
    ledger = manual_ledger(2027, "2027-01-10", 0, {category: hours})
    assert calculate_balances(ledger, until_date="2027-01-10")[category] == hours
    assert not [tx for tx in ledger["transactions"] if tx["category"] == category and tx["source"] != "auto_accrual"]


@pytest.mark.parametrize(
    "value",
    [-0.25, float("nan"), float("inf"), 0.1],
    ids=["MAN-016", "MAN-017-nan", "MAN-017-inf", "MAN-017-increment"],
)
def test_manual_invalid_values(value):
    with pytest.raises(ValueError):
        manual_ledger(2027, "2027-01-10", 6, {"annual": value})


def test_MAN_010_011_012_013_manual_boundary_and_unknown_expiration(tmp_path):
    store(tmp_path, year=2027, start="2027-01-10", balances={"travel_comp": 40})
    original = resolve_snapshot(tmp_path, 2027)
    store(tmp_path, year=2026, balances={"travel_comp": 999})
    snapshot = resolve_snapshot(tmp_path, 2027)
    assert snapshot == original
    before = deepcopy(snapshot)
    report = expiration_report(snapshot, snapshot.config)
    assert report["lots"] == []
    assert any(w["code"] == "MISSING_LOT_PROVENANCE" and w["hours"] == 40 for w in report["warnings"])
    assert calculate_balances(snapshot, until_date="2027-01-10")["travel_comp"] == 40
    assert snapshot["starting_balances"] == before["starting_balances"]


def test_MAN_018_existing_destination_unchanged(tmp_path):
    ledger, _ = store(tmp_path, year=2027, start="2027-01-10", balances={"annual": 13})
    before = tree(tmp_path)
    result = CliRunner().invoke(
        app, ["init", "--year", "2027", "--leave-year-start", "2027-01-10", "--json", "--data-dir", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert json.loads(result.output)["error"]["code"] == "DESTINATION_EXISTS"
    assert json.loads((tmp_path / "leave_years/2027.json").read_text()) == ledger
    assert not (tmp_path / "backups").exists()
    assert tree(tmp_path) == before


def test_MAN_022_explicit_store_wins(tmp_path, monkeypatch):
    older = tmp_path / "default"
    store(older, balances={"annual": 999})
    monkeypatch.setenv("FEDLEAVE_MCP_DATA_DIR", str(older))
    before = tree(older)
    selected = tmp_path / "selected"
    result = CliRunner().invoke(
        app,
        [
            "init",
            "--year",
            "2027",
            "--leave-year-start",
            "2027-01-10",
            "--annual-start",
            "2",
            "--json",
            "--data-dir",
            str(selected),
        ],
    )
    assert result.exit_code == 0, result.output
    assert tree(older) == before
    assert json.loads((selected / "leave_years/2027.json").read_text())["starting_balances"]["annual"] == 2
