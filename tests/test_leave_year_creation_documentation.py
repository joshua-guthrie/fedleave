"""Executable README examples and packaging discovery for issue #134."""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fedleave.cli import app
from leave_year_support import store

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "text",
    [
        "## Creating a New Leave Year",
        "Manual Starting Balances",
        "Carry Over From Previous Leave Year",
        "--annual-start 120",
        "init --from-year 2026 --year 2027 --preview --json",
        "GUI only",
        "independent baseline",
        "source end plus one day",
        "max_carryover_hours",
        "MISSING_LOT_PROVENANCE",
        "carryover-reconcile --year 2027 --preview --json",
        "DESTINATION_EXISTS",
        "sole writer",
        "--expected-fingerprint",
        "Original stored deadlines",
    ],
    ids=[f"DOC-{i:03}" for i in range(1, 16)],
)
def test_readme_explains_contract(text):
    assert text in (ROOT / "README.md").read_text()


def test_DOC_014_documented_examples_execute_in_isolated_store(tmp_path):
    manual = CliRunner().invoke(
        app,
        [
            "init",
            "--year",
            "2027",
            "--leave-year-start",
            "2027-01-10",
            "--annual-start",
            "120",
            "--sick-start",
            "600",
            "--travel-comp-start",
            "40",
            "--json",
            "--data-dir",
            str(tmp_path / "manual"),
        ],
    )
    assert manual.exit_code == 0, manual.output
    store(tmp_path / "linked")
    for command in (
        ["init", "--from-year", "2026", "--year", "2027", "--preview"],
        ["rollover", "--from-year", "2026", "--to-year", "2027", "--preview"],
    ):
        result = CliRunner().invoke(app, [*command, "--json", "--data-dir", str(tmp_path / "linked")])
        assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "command,terms",
    [
        ("init", ["from-year", "manual", "preview", "pay-periods", "expected-fingerprint"]),
        ("carryover-reconcile", ["preview", "repair-openings", "recover", "expected-fingerprint"]),
        ("snapshot", ["year", "data-dir"]),
    ],
    ids=["CLI-001-init", "CLI-001-reconcile", "PKG-003"],
)
def test_cli_help_exposes_modes_and_review_options(command, terms):
    result = CliRunner().invoke(app, [command, "--help"], terminal_width=200, env={"COLUMNS": "200"})
    assert result.exit_code == 0
    # Actions forces colored Rich output, including styling inside option
    # names. Assert the visible help text independently of terminal styling.
    visible_help = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.output)
    for term in terms:
        assert term in visible_help


def test_DOC_015_GUI_help_and_architecture_agree():
    gui = (ROOT / "help/fedleave-calendar-help.html").read_text()
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text()
    assert "Manual Starting Balances" in gui and "Carry Over From Previous Leave Year" in gui
    assert "GUI warns" in gui and "carryover-reconcile" in gui
    assert "cross_year.py" in architecture and "categories.py" in architecture
    assert "sole canonical ledger writer" in architecture


def test_GUI_025_PKG_005_no_GUI_ledger_writer():
    # New-year workflow and adapter must contain only CLI calls, never raw store
    # access. Settings/report export writes elsewhere in Qt remain legitimate.
    main = (ROOT / "src/fedleave_gui/main_window.py").read_text()
    dialog = main[main.index("class StartYearDialog") : main.index("class SelectMonthDialog")]
    create = main[main.index("    def new_leave_year") : main.index("    def validate_data")]
    backend = (ROOT / "src/fedleave_gui/backend.py").read_text()
    for source in (dialog, create, backend):
        assert "write_json" not in source and "leave_years/" not in source
        assert "write_text" not in source
    assert "self.backend.create_carryover_year" in create
    assert "self.backend.init_year" in create


def test_PKG_001_002_core_modules_are_in_discovered_packages():
    import setuptools

    packages = setuptools.find_packages(where=str(ROOT / "src"))
    assert "fedleave" in packages
    for filename in ("categories.py", "cross_year.py"):
        assert (ROOT / "src/fedleave" / filename).is_file()
