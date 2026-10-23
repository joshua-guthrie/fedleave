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

        try:
            with datastore_lock(get_default_data_dir(ctx.params.get("data_dir"))):
                return super().invoke(ctx)
        except portalocker.exceptions.LockException:
            typer.echo("Datastore busy: lock wait timed out; retry the command.", err=True)
            raise typer.Exit(75) from None


def coordinate_commands(application) -> None:
    """Apply the same lock to all registered and nested CLI commands."""
    for command in application.registered_commands:
        # Newer Typer versions store their default class explicitly rather
        # than leaving it unset. Both forms must receive the transaction lock.
        if command.cls is None or command.cls is TyperCommand:
            command.cls = LockedCommand
    for group in application.registered_groups:
        coordinate_commands(group.typer_instance)
