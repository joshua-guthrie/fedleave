"""Independent registry walks, argv round trips, and published identifier parity."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
import pytest
import typer
from typer.main import get_command

from fedleave.cli import app
from fedleave.mcp.catalog import CatalogError, discover, inventory
from fedleave.mcp.execution import Executor
from fedleave.mcp.policy import Policy

GOLDEN_NAMES = """accrual_change activity add balance check_for_updates compare_leave_balances correct
expiration_extend expirations export_data force_balance help holidays import_data import_wms_http init list
month pay_period pay_periods reconcile rollover set_day starting_balance_set types use_or_loose use_or_lose
validate version void years""".split()


def test_complete_registry_and_parameter_parity():
    root = get_command(app)
    actual = {}

    def walk(command, path, inherited):
        params = inherited + [(path, p) for p in command.params]
        children = getattr(command, "commands", {})
        if not children or getattr(command, "invoke_without_command", False):
            actual[path] = params
        for name, child in children.items():
            walk(child, path + (name,), params)

    walk(root, (), [])
    catalog = discover()
    assert set(catalog) == {f"fedleave_{name}" for name in GOLDEN_NAMES}
    leaves = {c.path: c for c in catalog.values() if not c.special}
    assert leaves.keys() == actual.keys()
    for path, params in actual.items():
        tool = leaves[path]
        for scope, p in params:
            matches = [v for v in tool.parameters if v.scope == scope and v.click.name == p.name]
            assert len(matches) == 1
            exposed = matches[0]
            assert exposed.click.opts == p.opts
            assert exposed.click.secondary_opts == p.secondary_opts
            assert exposed.click.nargs == p.nargs
            assert exposed.click.multiple == p.multiple
            assert exposed.click.required == p.required
            assert exposed.key in tool.schema["properties"]
    report = inventory(catalog)
    # Reviewed schema fingerprint: a CLI change still generates tools automatically,
    # but CI requires a deliberate review of metadata and restricted permissions.
    expected = json.loads((Path(__file__).parent / "fixtures" / "mcp-parity.json").read_text())
    assert {k: report[k] for k in expected} == expected


def test_all_set_day_fields_and_legacy_aliases():
    catalog = discover()
    props = catalog["fedleave_set_day"].schema["properties"]
    for name in [
        "annual",
        "sick",
        "credit",
        "comp",
        "travel_comp",
        "overtime",
        "admin",
        "lwop",
        "military",
        "court",
        "religious_comp",
        "time_off_award",
        "excused",
        "holiday",
        "flex",
        "other",
        "restored_annual",
    ]:
        assert name in props
        assert f"{name}_comment" in props
    command = catalog["fedleave_add"]
    arguments = {
        "date": "2026-07-01",
        "category": "annual",
        "used": 1,
        "authoritative": False,
        "show_transaction_ids": True,
        "_cli_aliases": {"show_transaction_ids": "--ShowTransactionIDs", "authoritative": "--no-authoritative"},
    }
    argv = command.argv(arguments)
    assert "--ShowTransactionIDs" in argv
    assert "--no-authoritative" in argv
    with pytest.raises(CatalogError):
        command.argv({**arguments, "_cli_aliases": {"used": "--overwrite"}})


def test_new_typer_commands_and_parameters_appear_without_tool_definitions():
    sample = typer.Typer()
    sub = typer.Typer()
    sample.add_typer(sub, name="new-group")

    @sub.command()
    def added(year: int, names: list[str] = typer.Option([], "--name", "-n")):
        pass

    catalog = discover(get_command(sample))
    tool = catalog["fedleave_new_group_added"]
    assert tool.schema["properties"]["year"]["type"] == "integer"
    assert tool.schema["properties"]["names"]["type"] == "array"
    assert tool.argv({"year": 2026, "names": ["--literal", "a b"]}) == [
        "new-group",
        "added",
        "--name=--literal",
        "--name=a b",
        "--",
        "2026",
    ]
    assert tool.inventory()["classification"]["kind"] == "unclassified"


def test_click_groups_tuples_repeated_flags_ranges_defaults_and_positional_values():
    observed = []

    @click.group()
    @click.option("--tenant", required=True)
    def group(tenant):
        observed.append(tenant)

    @group.command()
    @click.argument("items", nargs=-1, required=True)
    @click.option("--number", type=click.IntRange(1, 9), default=4)
    @click.option("--ratio", type=click.FloatRange(min=0, max=1, max_open=True))
    @click.option("--pair", type=(str, int), multiple=True)
    @click.option("--kind", type=click.Choice(["small", "LARGE"], case_sensitive=False))
    @click.option("--active/--inactive", default=True)
    @click.option("-v", "--verbose", count=True)
    @click.option("--path", type=click.Path())
    def leaf(**kwargs):
        observed.append(kwargs)

    tool = discover(group)["fedleave_leaf"]
    arguments = {
        "tenant": "--not-an-option",
        "items": ["--hello", "world"],
        "number": 3,
        "ratio": 0.5,
        "pair": [["a b", 2], ["--literal", 8]],
        "kind": "large",
        "active": False,
        "verbose": 2,
        "path": "a b/c",
    }
    group.main(tool.argv(arguments), standalone_mode=False)
    assert observed[0] == "--not-an-option"
    assert observed[1] == {
        "number": 3,
        "ratio": 0.5,
        "pair": (("a b", 2), ("--literal", 8)),
        "kind": "LARGE",
        "active": False,
        "verbose": 2,
        "path": "a b/c",
        "items": ("--hello", "world"),
    }
    for patch in [
        {"number": 10},
        {"number": True},
        {"ratio": 1},
        {"pair": [["x"]]},
        {"unknown": 1},
        {"ratio": float("nan")},
    ]:
        with pytest.raises(CatalogError):
            tool.argv({**arguments, **patch})


def test_invokable_groups_collision_safe_names_and_unsupported_types():
    @click.group(invoke_without_command=True)
    def root():
        pass

    @root.command("a-b")
    def one():
        pass

    @root.command("a_b")
    def two():
        pass

    catalog = discover(root)
    assert "fedleave_root" in catalog
    assert len(catalog) == 3
    assert sorted(catalog) == sorted(discover(root))
    assert len({c.name for c in catalog.values()}) == 3

    @click.command()
    @click.option("--value", type=click.UNPROCESSED)
    def unsupported(value):
        pass

    with pytest.raises(CatalogError, match="Unsupported CLI type"):
        discover(unsupported)


def test_eager_help_and_version_do_not_require_leaf_values():
    tool = discover()["fedleave_add"]
    assert tool.argv({"version": True}) == ["--version", "add"]
    assert tool.argv({"add__help": True}) == ["add", "--help"]


def test_unclassified_typer_command_executes_only_with_full_access(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    sample = typer.Typer()
    sample.callback()(lambda: None)

    @sample.command()
    def future(value: str, enabled: bool = typer.Option(True, "--enabled/--disabled")):
        typer.echo(json.dumps({"value": value, "enabled": enabled}))

    catalog = discover(get_command(sample))
    tool = catalog["fedleave_future"]
    invocations = []

    async def registered_cli(executable, argv, env, timeout, max_output):
        invocations.append(argv)
        result = CliRunner().invoke(sample, argv)
        return {"ok": result.exit_code == 0, "exit_code": result.exit_code, "stdout": result.stdout, "stderr": ""}

    monkeypatch.setattr("fedleave.mcp.execution.run_cli", registered_cli)
    arguments = {"value": "--literal ; $(ignored)", "enabled": False}
    executor = Executor(catalog, Policy())
    result = asyncio.run(executor.call(tool.name, arguments))
    assert result["ok"], result
    assert json.loads(result["stdout"]) == {"value": arguments["value"], "enabled": False}
    assert "--" in invocations[0] and "--disabled" in invocations[0]
    executor.policy = Policy(mode="unattended", data_dir=tmp_path)
    denied = asyncio.run(executor.call(tool.name, arguments))
    assert denied["error"] == "permission_denied" and "classification" in denied["message"]
    assert len(invocations) == 1
