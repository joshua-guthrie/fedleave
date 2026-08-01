from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "scripts" / "lib" / "common" / "installer_engine.py"


def _load_engine_module():
    spec = importlib.util.spec_from_file_location("shared_bundle_engine", ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _engine(module, platform: str = "linux"):
    engine = module.InstallerEngine.__new__(module.InstallerEngine)
    engine.options = SimpleNamespace(platform=platform)
    engine.log = lambda message: None
    return engine


def test_linux_bundle_deduplicates_large_identical_runtime_files(tmp_path: Path) -> None:
    module = _load_engine_module()
    engine = _engine(module)
    bundle = tmp_path / "fedleave-Ubuntu"
    support = bundle / "_internal"
    nested = support / "PySide6" / "Qt" / "lib"
    nested.mkdir(parents=True)
    canonical = support / "libQt6Core.so.6"
    duplicate = nested / canonical.name
    payload = b"shared Qt runtime" * 70_000
    canonical.write_bytes(payload)
    duplicate.write_bytes(payload)

    engine._deduplicate_linux_bundle(bundle)

    assert canonical.is_file() and not canonical.is_symlink()
    assert duplicate.is_symlink()
    assert duplicate.read_bytes() == payload


@pytest.mark.skipif(os.name == "nt", reason="Linux runtime symlinks are POSIX-only")
def test_publish_preserves_internal_deduplication_links(tmp_path: Path) -> None:
    module = _load_engine_module()
    engine = _engine(module)
    completed = tmp_path / "completed" / "fedleave-Ubuntu"
    support = completed / "_internal"
    nested = support / "nested"
    nested.mkdir(parents=True)
    canonical = support / "runtime.so"
    canonical.write_bytes(b"runtime")
    (nested / "runtime.so").symlink_to("../runtime.so")
    published = tmp_path / "published" / "fedleave-Ubuntu"

    engine._publish_build(completed, published)

    published_link = published / "_internal" / "nested" / "runtime.so"
    assert published_link.is_symlink()
    assert published_link.read_bytes() == b"runtime"


def test_windows_bundle_does_not_create_symlinks(tmp_path: Path) -> None:
    module = _load_engine_module()
    engine = _engine(module, platform="windows")
    support = tmp_path / "fedleave-Windows" / "_internal"
    support.mkdir(parents=True)
    first = support / "first.dll"
    second = support / "second.dll"
    payload = b"shared Windows runtime" * 60_000
    first.write_bytes(payload)
    second.write_bytes(payload)

    engine._deduplicate_linux_bundle(support.parent)

    assert not first.is_symlink()
    assert not second.is_symlink()
