from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_gui_build_uses_single_file_root_layout():
    script = (ROOT / "scripts" / "build_gui_pyinstaller.sh").read_text()

    assert "--skip-backend-build" in script
    assert "--onefile" in script
    assert 'build_pyinstaller_core.sh' in script
    assert 'fedleave-Ubuntu' in script
    assert 'find "$DIST_ROOT" -maxdepth 1 -type f -delete' in script
    assert 'rm -rf "$DIST_ROOT/FedLeaveCalendar-Ubuntu" "$DIST_ROOT/FedLeaveCalendar-Windows"' in script
    assert 'rm -rf "$DIST_DIR"' in script
    assert 'rm -f "$DIST_DIR/FedLeaveCalendar"' in script


def test_windows_gui_build_uses_single_file_root_layout():
    script = (ROOT / "scripts" / "build_gui_pyinstaller.ps1").read_text()

    assert "[switch]$SkipBackendBuild" in script
    assert "--onefile" in script
    assert "build_pyinstaller_core.ps1" in script
    assert "fedleave-Windows" in script
    assert 'Get-ChildItem -Force -Path $DIST_PARENT -File | Remove-Item -Force' in script
    assert '(Join-Path $DIST_PARENT "FedLeaveCalendar-Ubuntu")' in script
    assert '(Join-Path $DIST_PARENT "FedLeaveCalendar-Windows")' in script
    assert 'Remove-Item -Recurse -Force $DIST_ROOT' in script
    assert '$guiExe = Join-Path $DIST_ROOT "FedLeaveCalendar.exe"' in script


def test_gui_installers_copy_the_shared_backend_from_dist_root():
    linux = (ROOT / "scripts" / "install_gui_ubuntu.sh").read_text()
    windows = (ROOT / "scripts" / "install_gui_windows.ps1").read_text()

    assert 'APP_SRC="$HERE/dist/fedleave-Ubuntu"' in linux
    assert 'cp "$APP_SRC/FedLeaveCalendar" "$APP_SRC/fedleave" "$INSTALL_DIR/"' in linux
    assert '$APP_SRC = Join-Path $HERE "dist\\fedleave-Windows"' in windows
    assert 'Join-Path $APP_SRC "FedLeaveCalendar.exe"' in windows
    assert 'Join-Path $APP_SRC "fedleave.exe"' in windows


def test_regular_build_scripts_include_gui_build():
    linux = (ROOT / "scripts" / "build_pyinstaller.sh").read_text()
    windows = (ROOT / "scripts" / "build_pyinstaller.ps1").read_text()

    assert "fedleave-Ubuntu" in linux
    assert "build_pyinstaller_core.sh" in linux
    assert "build_gui_pyinstaller.sh" in linux
    assert "--skip-backend-build" in linux
    assert "fedleave-Windows" in windows
    assert "build_pyinstaller_core.ps1" in windows
    assert "build_gui_pyinstaller.ps1" in windows
    assert "-SkipBackendBuild" in windows
