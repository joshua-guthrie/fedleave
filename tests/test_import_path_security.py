import json
import os
import subprocess
from pathlib import Path

import pytest
import typer

from fedleave.commands.data import import_data


@pytest.mark.parametrize("name", ["C:outside", "D:outside", "file:stream", "../escape", "..\\escape"])
def test_import_rejects_nonportable_cache_key_before_any_data_write(tmp_path, name):
    archive = tmp_path / "archive.json"
    archive.write_text(
        json.dumps(
            {"schema_version": 1, "config": {"marker": "new-config"}, "leave_years": {}, "holiday_cache": {name: {}}}
        )
    )
    target = tmp_path / "store"
    with pytest.raises(typer.Exit):
        import_data(input=archive, overwrite=False, merge=False, data_dir=target)
    assert not target.exists()


def test_import_preserves_safe_unicode_cache_names(tmp_path):
    archive = tmp_path / "archive.json"
    archive.write_text(
        json.dumps({"schema_version": 1, "leave_years": {}, "holiday_cache": {"custom-café": {"holidays": []}}})
    )
    target = tmp_path / "store"
    import_data(input=archive, overwrite=False, merge=False, data_dir=target)
    assert (target / "holiday_cache" / "custom-café.json").exists()


def test_import_preflights_all_targets_before_writing_config(tmp_path):
    archive = tmp_path / "archive.json"
    archive.write_text(
        json.dumps(
            {"schema_version": 1, "config": {"marker": "new-config"}, "leave_years": {}, "holiday_cache": {"safe": {}}}
        )
    )
    target = tmp_path / "store"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (target / "holiday_cache").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Local symlink creation unavailable; portable-name tests still run")
    with pytest.raises(typer.Exit):
        import_data(input=archive, overwrite=False, merge=False, data_dir=target)
    assert not (target / "config.json").exists()
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Native Windows drive semantics run in Windows CI")
def test_native_windows_import_cannot_escape_a_different_datastore_drive(tmp_path, monkeypatch):
    target = tmp_path / "mapped-store"
    target.mkdir()
    drive = next(letter for letter in "ZYXWVUTSRQPONMLKJIHGFED" if not Path(f"{letter}:/").exists())
    subprocess.run(["subst", f"{drive}:", str(target)], check=True, capture_output=True)
    try:
        # The process retains the real drive's disposable cwd while the selected
        # datastore is on another drive, reproducing the vulnerable join layout.
        monkeypatch.chdir(tmp_path)
        escaped = tmp_path / "outside.json"
        escaped.write_text("preserve")
        original_drive = tmp_path.drive
        assert original_drive.casefold() != f"{drive}:".casefold()
        archive = tmp_path / "archive.json"
        archive.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "config": {"marker": "new"},
                    "leave_years": {},
                    "holiday_cache": {original_drive + "outside": {}},
                }
            )
        )
        with pytest.raises(typer.Exit):
            import_data(input=archive, overwrite=True, merge=False, data_dir=Path(f"{drive}:/"))
        assert escaped.read_text() == "preserve"
        assert list(target.iterdir()) == []
    finally:
        subprocess.run(["subst", f"{drive}:", "/D"], check=True, capture_output=True)
