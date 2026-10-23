"""Defense in depth for CLI children launched by a restricted MCP connector."""

from __future__ import annotations

import json
import os
from pathlib import Path


class RestrictedWriteError(RuntimeError):
    """A nominal read attempted a migration/backfill or a forbidden write."""


def same_file(first: Path, second: Path) -> bool:
    """Recognize protected hard-link aliases as well as canonical path names."""
    if first == second:
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False


def check_write(path: Path) -> None:
    resolved = path.resolve()
    protected = os.environ.get("FEDLEAVE_MCP_PROTECTED_PATHS")
    if protected and any(same_file(resolved, Path(p).resolve()) for p in json.loads(protected)):
        raise RestrictedWriteError("CLI write targets a protected configuration or executable file")
    if os.environ.get("FEDLEAVE_MCP_READ_ONLY") == "1":
        raise RestrictedWriteError(
            "Read-only invocation requires a datastore write (migration/backfill). "
            "Run the command with an authorized unattended connector or maintain the store using the CLI."
        )
    roots = os.environ.get("FEDLEAVE_MCP_WRITE_ROOTS")
    if roots is not None:
        allowed = [Path(p).resolve() for p in json.loads(roots)]
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed):
            raise RestrictedWriteError("CLI write escapes its authorized filesystem roots")
