"""Locate sibling executables in source, virtualenv, and frozen layouts."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterator


def is_executable(candidate: Path) -> bool:
    """Return whether a path is runnable on the current platform."""
    if not candidate.is_file():
        return False
    if sys.platform.startswith("win"):
        return candidate.suffix.lower() == candidate.resolve().suffix.lower() == ".exe"
    return os.access(candidate, os.X_OK)


def _executable_names(app_name: str) -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return (f"{app_name}.exe",)
    return (app_name,)


def validate_backend(path: Path | str) -> Path:
    """Windows batch files introduce a shell even with subprocess shell=False."""
    candidate = Path(path).expanduser()
    if sys.platform.startswith("win"):
        if candidate.parent == Path(".") and not candidate.is_absolute() and not is_executable(candidate):
            name = candidate.name if candidate.suffix else candidate.with_suffix(".exe").name
            located = shutil.which(name) if Path(name).suffix.lower() == ".exe" else None
            if located:
                candidate = Path(located)
        if not is_executable(candidate):
            raise ValueError("Windows backends require an existing native .exe; select the installed fedleave.exe.")
        return candidate.resolve()
    return candidate


def _candidate_roots() -> Iterator[Path]:
    roots: list[Path] = []
    for raw in (Path(sys.argv[0]), Path(sys.executable)):
        path = raw.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        root = path if path.is_dir() else path.parent
        roots.append(root)
        roots.append(root.parent)

    package_root = Path(__file__).resolve().parents[2]
    roots.extend(
        [
            package_root,
        ]
    )

    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve() if root.exists() else root
        if resolved in seen:
            continue
        seen.add(resolved)
        # Preserve the logical directory. Resolving a virtual-environment
        # interpreter symlink can jump to the system Python directory and
        # skip companion executables installed beside that interpreter.
        yield root


def iter_executable_candidates(app_name: str) -> Iterator[Path]:
    """Yield ordered candidate paths without requiring that they exist."""
    names = _executable_names(app_name)
    for root in _candidate_roots():
        for name in names:
            yield root / name
        for name in names:
            yield root / app_name / name
