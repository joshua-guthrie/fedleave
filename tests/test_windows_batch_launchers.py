from pathlib import Path


def test_windows_batch_launchers_call_their_matching_powershell_scripts():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    expected = {
        "build_pyinstaller.bat": "build_pyinstaller.ps1",
        "build_gui_pyinstaller.bat": "build_gui_pyinstaller.ps1",
        "install_gui_windows.bat": "install_gui_windows.ps1",
        "uninstall_gui_windows.bat": "uninstall_gui_windows.ps1",
    }

    for batch_name, powershell_name in expected.items():
        text = (scripts_dir / batch_name).read_text(encoding="utf-8")
        assert text.startswith("@echo off")
        assert powershell_name in text
        assert '-NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%' in text
