"""Verify atomic writes and backups preserve data under failure and collision."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import fedleave.storage as storage
from fedleave.storage import atomic_write_json, backup_file


def test_atomic_write_json_rejects_overwrite_without_creating_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"original": true}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        atomic_write_json(path, {"updated": True}, overwrite=False)

    assert path.read_text(encoding="utf-8") == '{"original": true}\n'
    assert sorted(item.name for item in tmp_path.iterdir()) == ["payload.json"]


def test_atomic_write_json_cleans_temp_file_on_serialization_failure(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"

    with pytest.raises(TypeError):
        atomic_write_json(path, {"bad": {1, 2, 3}})

    assert not any(tmp_path.iterdir())


def test_atomic_write_json_cleans_temp_file_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "payload.json"

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_json(path, {"updated": True})

    assert not any(tmp_path.iterdir())


def test_backup_file_uses_unique_names_within_same_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "data" / "leave_years" / "2026.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"a": 1}\n', encoding="utf-8")

    frozen = datetime(2026, 7, 16, 12, 0, 0, 123456)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen

    monkeypatch.setattr(storage, "datetime", FrozenDateTime)

    first = backup_file(source)
    second = backup_file(source)

    assert first != second
    assert first.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert second.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert len(list(source.parent.parent.joinpath("backups").iterdir())) == 2


def test_config_backup_stays_inside_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "fedleave-data"
    data_dir.mkdir()
    config = data_dir / "config.json"
    config.write_text('{"schema_version": 1}\n', encoding="utf-8")

    backup = backup_file(config)

    assert backup.parent == data_dir / "backups"
    assert backup.read_text(encoding="utf-8") == config.read_text(encoding="utf-8")
    assert not (tmp_path / "backups").exists()
