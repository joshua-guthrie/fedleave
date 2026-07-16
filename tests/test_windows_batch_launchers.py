from pathlib import Path


def test_windows_install_batch_calls_installer_engine_without_powershell():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    text = (scripts_dir / "WindowsInstall.bat").read_text(encoding="utf-8")
    assert text.startswith("@echo off")
    assert "installer_engine.py" in text
    assert "--platform windows" in text
    assert "powershell" not in text.lower()
