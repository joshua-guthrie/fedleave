"""CLI entry points for the common carryover and reconciliation service."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.models import OptionInfo

from ..cli_app import _print_json, app, console
from ..config import get_default_data_dir
from ..cross_year import (
    AccountingError,
    apply_creation,
    apply_reconciliation,
    creation_plan,
    reconciliation_plan,
    recover_reconciliation,
)


def report_error(exc: Exception, json_output: bool) -> None:
    code = getattr(exc, "code", str(exc).split(":", 1)[0] if ":" in str(exc) else "INVALID_LEDGER")
    if json_output:
        _print_json({"ok": False, "error": {"code": code, "message": str(exc)}})
    else:
        console.print(f"[red]ERROR:[/red] {exc}")
    raise typer.Exit(8)


def create_from_previous(
    from_year: int,
    to_year: int,
    base: Path,
    *,
    preview: bool = False,
    json_output: bool = False,
    start: str | None = None,
    pay_periods: int | None = None,
    expected: str | None = None,
) -> None:
    try:
        target, summary = creation_plan(base, from_year, to_year, start=start, pay_periods=pay_periods)
        result = {**summary, "action": "preview"}
        if not preview:
            result = apply_creation(base, target, summary, expected)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        report_error(exc, json_output)
    if json_output:
        _print_json(result)
    else:
        console.print(f"Carryover {from_year} to {to_year}: {result['action']}")
        console.print(
            f"  {result['leave_year_start']} through {result['leave_year_end']} ({result['pay_period_count']} periods)"
        )
        for category, amount in result["opening_balances"].items():
            console.print(f"  {category}: {amount:.2f}")
        for adjustment in result["adjustments"]:
            console.print(f"  Reduction: {adjustment['category']} {adjustment['hours']:.2f} ({adjustment['reason']})")
        for warning in result["warnings"]:
            console.print(f"  {warning['code']}: {warning.get('message', '')}")
        console.print(f"Preview fingerprint: {result['preview_fingerprint']}")


@app.command()
def rollover(
    from_year: int = typer.Option(..., help="Explicit immediately previous leave year."),
    to_year: int = typer.Option(..., help="New destination leave year (create only)."),
    preview: bool = typer.Option(False, help="Read-only carryover preview."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    data_dir: Path | None = typer.Option(None, help="Data directory override."),
    pay_periods: int | None = typer.Option(None, help="Explicit agency schedule: 26 or 27 periods."),
    expected_fingerprint: str | None = typer.Option(None, help="Require the fingerprint returned by preview."),
) -> None:
    """Create from the prior year using the same service as init --from-year."""
    create_from_previous(
        from_year,
        to_year,
        get_default_data_dir(None if isinstance(data_dir, OptionInfo) else data_dir),
        preview=preview is True,
        json_output=json_output is True,
        pay_periods=None if isinstance(pay_periods, OptionInfo) else pay_periods,
        expected=None if isinstance(expected_fingerprint, OptionInfo) else expected_fingerprint,
    )


@app.command("carryover-reconcile")
def carryover_reconcile(
    year: int = typer.Option(..., help="First linked year to reconcile; includes all dependent successors."),
    preview: bool = typer.Option(False, help="Preview all changes without writing."),
    expected_fingerprint: str | None = typer.Option(None, help="Fingerprint from the reviewed preview."),
    repair_openings: bool = typer.Option(
        False, help="Explicitly remove legacy mirrored opening rows without changing metadata."
    ),
    recover: bool = typer.Option(False, help="Restore originals from an interrupted reconciliation journal."),
    json_output: bool = typer.Option(False, "--json"),
    data_dir: Path | None = typer.Option(None),
) -> None:
    """Explicitly refresh generated carryovers, preserving genuine activity.

    Backups and a recoverable journal protect multi-year apply. --recover rolls
    an interrupted operation back; preview and ordinary reads never repair files.
    """
    base = get_default_data_dir(data_dir)
    try:
        if recover:
            if preview:
                raise AccountingError("INVALID_OPTIONS", "--recover cannot be combined with --preview")
            result = recover_reconciliation(base)
        else:
            changes, result = reconciliation_plan(base, year, repair_openings=repair_openings)
            if not preview:
                result = apply_reconciliation(base, changes, result, expected_fingerprint)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        report_error(exc, json_output)
    if json_output:
        _print_json(result)
    else:
        console.print(result)
