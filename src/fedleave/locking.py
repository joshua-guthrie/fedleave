"""OS-backed transaction locks shared by CLI, GUI backends, and MCP callers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import portalocker
import typer
from typer.core import TyperCommand


@contextmanager
def datastore_lock(data_dir: Path | str, timeout: float | None = None):
    """Hold an advisory OS lock for a complete read/modify/write operation.

    Never unlink the lock file: replacing its inode could let two writers lock
    different files. The OS releases ownership when a process exits or crashes.
    """
    # Typer may defer Path conversion until its callback wrapper, after invoke.
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / ".fedleave.lock").is_symlink():
        raise RuntimeError("Datastore lock must not be a symbolic link")
    timeout = float(os.environ.get("FEDLEAVE_LOCK_TIMEOUT", "30")) if timeout is None else timeout
    with portalocker.Lock(str(data_dir / ".fedleave.lock"), timeout=timeout):
        yield


class LockedCommand(TyperCommand):
    """Serialize every CLI leaf, including reports that migrate/backfill data."""

    def invoke(self, ctx):
        from .config import get_default_data_dir
        from .cross_year import AccountingError, preflight_creation

        readonly = (
            ctx.info_name
            in {
                "snapshot",
                "balance",
                "use-or-lose",
                "use-or-loose",
                "expirations",
                "years",
                "list",
                "month",
                "pay-period",
                "pay-periods",
                "daily-activity",
                "activity",
                "compare-leave-balances",
                "types",
                "help",
                "export-data",
            }
            or ctx.params.get("preview")
            or (ctx.info_name == "validate" and not ctx.params.get("apply"))
        )
        try:
            if ctx.info_name in {"init", "rollover"}:
                preflight_creation(Path(get_default_data_dir(ctx.params.get("data_dir"))), ctx.info_name, ctx.params)
            if readonly:
                # An existing shared lock avoids racing writers without
                # creating any file or directory during a query or preview.
                lock_path = Path(get_default_data_dir(ctx.params.get("data_dir"))) / ".fedleave.lock"
                if lock_path.exists():
                    with portalocker.Lock(
                        str(lock_path),
                        mode="r",
                        flags=portalocker.LOCK_SH | portalocker.LOCK_NB,
                        timeout=float(os.environ.get("FEDLEAVE_LOCK_TIMEOUT", "30")),
                    ):
                        return super().invoke(ctx)
                return super().invoke(ctx)
            with datastore_lock(get_default_data_dir(ctx.params.get("data_dir"))):
                return super().invoke(ctx)
        except portalocker.exceptions.LockException:
            typer.echo("Datastore busy: lock wait timed out; retry the command.", err=True)
            raise typer.Exit(75) from None
        except (AccountingError, ValueError, OSError, TypeError, KeyError) as exc:
            from .commands.rollover import report_error

            report_error(exc, bool(ctx.params.get("json_output")))


def coordinate_commands(application) -> None:
    """Apply the same lock to all registered and nested CLI commands."""
    for command in application.registered_commands:
        # Newer Typer versions store their default class explicitly rather
        # than leaving it unset. Both forms must receive the transaction lock.
        if command.cls is None or command.cls is TyperCommand:
            command.cls = LockedCommand
    for group in application.registered_groups:
        coordinate_commands(group.typer_instance)
