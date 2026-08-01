from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon


def _candidate_roots() -> list[Path]:
    candidate_roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate_roots.append(Path(meipass))
    for raw in (Path(sys.argv[0]), Path(sys.executable)):
        path = raw if raw.is_absolute() else Path.cwd() / raw
        resolved = path.resolve()
        candidate_roots.append(resolved if resolved.is_dir() else resolved.parent)
    project_root = Path(__file__).resolve().parents[2]
    candidate_roots.extend([project_root, project_root / "dist", project_root.parent / "dist"])

    seen: set[Path] = set()
    ordered: list[Path] = []
    for root in candidate_roots:
        if root in seen:
            continue
        seen.add(root)
        ordered.append(root)
    return ordered


def find_data_file(*parts: str) -> Path:
    for root in _candidate_roots():
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    raise FileNotFoundError("/".join(parts))


def help_file(filename: str) -> Path:
    return find_data_file("help", filename)


def asset_file(filename: str) -> Path:
    return find_data_file("assets", filename)


def window_icon() -> QIcon:
    try:
        return QIcon(str(asset_file("fedleave-icon.ico")))
    except FileNotFoundError:
        return QIcon()


def help_base_url(filename: str) -> QUrl:
    return QUrl.fromLocalFile(str(help_file(filename).parent))
