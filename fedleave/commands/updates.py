from __future__ import annotations

import typer

from ..cli_app import _print_json, app, console
from ..update_check import check_for_updates


@app.command("check-for-updates")
def check_for_updates_command(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    if not isinstance(json_output, bool):
        json_output = False
    result = check_for_updates()
    if json_output:
        _print_json(result)
        return
    if result["status"] != "ok":
        console.print(f"[yellow]{result['message']}[/yellow]")
        console.print(f"Master branch: {result['release_url']}")
        return
    if result["update_available"]:
        console.print(
            f"[green]FedLeave {result['latest_version']} is available[/green] "
            f"(installed: {result['current_version']})."
        )
        console.print(f"Master branch: {result['release_url']}")
        console.print(result["instructions"])
    else:
        console.print(f"FedLeave {result['current_version']} is current.")
