from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_gui_build_uses_single_file_root_layout():
    script = (ROOT / "scripts" / "build_gui_pyinstaller.sh").read_text()

    assert "--skip-backend-build" in script
    assert "--onefile" in script
    assert 'build_pyinstaller_core.sh' in script
    assert 'cp "$DIST_ROOT/fedleave"' not in script
    assert 'APP_DIST="$DIST_ROOT/FedLeaveCalendar-Ubuntu"' not in script


def test_windows_gui_build_uses_single_file_root_layout():
    script = (ROOT / "scripts" / "build_gui_pyinstaller.ps1").read_text()

    assert "[switch]$SkipBackendBuild" in script
    assert "--onefile" in script
    assert "build_pyinstaller_core.ps1" in script
    assert "Copy-Item -Force (Join-Path $DIST_ROOT \"fedleave.exe\")" not in script
    assert 'APP_DIST = Join-Path $DIST_ROOT "FedLeaveCalendar-Windows"' not in script


def test_gui_installers_copy_the_shared_backend_from_dist_root():
    linux = (ROOT / "scripts" / "install_gui_ubuntu.sh").read_text()
    windows = (ROOT / "scripts" / "install_gui_windows.ps1").read_text()

    assert 'APP_SRC="$HERE/dist"' in linux
    assert 'cp "$APP_SRC/FedLeaveCalendar" "$APP_SRC/fedleave" "$INSTALL_DIR/"' in linux
    assert '$APP_SRC = Join-Path $HERE "dist"' in windows
    assert 'Join-Path $APP_SRC "FedLeaveCalendar.exe"' in windows
    assert 'Join-Path $APP_SRC "fedleave.exe"' in windows


def test_regular_build_scripts_include_gui_build():
    linux = (ROOT / "scripts" / "build_pyinstaller.sh").read_text()
    windows = (ROOT / "scripts" / "build_pyinstaller.ps1").read_text()

    assert "build_pyinstaller_core.sh" in linux
    assert "build_gui_pyinstaller.sh" in linux
    assert "--skip-backend-build" in linux
    assert "build_pyinstaller_core.ps1" in windows
    assert "build_gui_pyinstaller.ps1" in windows
    assert "-SkipBackendBuild" in windows
