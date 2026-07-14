from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_gui_build_uses_onedir_bundle_layout():
    script = (ROOT / "scripts" / "build_gui_pyinstaller.sh").read_text()

    assert "--skip-backend-build" in script
    assert "--onedir" in script
    assert 'build_pyinstaller_core.sh' in script
    assert 'fedleave-Ubuntu' in script
    assert '--icon "$HERE/assets/fedleave-icon.ico"' in script
    assert '--add-data "$HERE/assets:assets"' in script
    assert 'rm -rf "$DIST_DIR/FedLeaveCalendar"' in script
    assert 'echo "  - FedLeaveCalendar/FedLeaveCalendar"' in script


def test_windows_gui_build_uses_onedir_bundle_layout():
    script = (ROOT / "scripts" / "build_gui_pyinstaller.ps1").read_text()

    assert "[switch]$SkipBackendBuild" in script
    assert "--onedir" in script
    assert "build_pyinstaller_core.ps1" in script
    assert "fedleave-Windows" in script
    assert '--icon "$HERE\\assets\\fedleave-icon.ico"' in script
    assert '--add-data "$HERE\\assets;assets"' in script
    assert 'Remove-Item -Recurse -Force $guiBundle' in script
    assert 'Write-Host "  - FedLeaveCalendar\\FedLeaveCalendar.exe"' in script


def test_gui_installers_copy_the_shared_backend_from_dist_root():
    linux = (ROOT / "scripts" / "install_gui_ubuntu.sh").read_text()
    windows = (ROOT / "scripts" / "install_gui_windows.ps1").read_text()

    assert 'APP_SRC="$HERE/dist/fedleave-Ubuntu"' in linux
    assert 'INSTALL_DIR="${HOME}/.local/share/fedleave-app"' in linux
    assert 'cp -a "$APP_SRC"/. "$INSTALL_DIR"/' in linux
    assert 'for app in fedleave FedLeaveCalendar AnnualLeaveChartForTheYear SickLeaveChartForTheYear fedleaveMonthReportGraphic; do' in linux
    assert 'Exec=$INSTALL_DIR/FedLeaveCalendar/FedLeaveCalendar' in linux
    assert '$APP_SRC = Join-Path $HERE "dist\\fedleave-Windows"' in windows
    assert '$INSTALL_ROOT = Join-Path $env:LOCALAPPDATA "Programs\\FedLeave"' in windows
    assert 'Get-ChildItem -Force -Path $APP_SRC -Directory | ForEach-Object {' in windows
    assert 'Add-UserPathEntry -Entry $FEDLEAVE_BUNDLE' in windows
    assert '$FEDLEAVE_BUNDLE = Join-Path $INSTALL_ROOT "fedleave"' in windows
    assert 'Join-Path $INSTALL_ROOT "FedLeaveCalendar\\FedLeaveCalendar.exe"' in windows
    assert 'Join-Path $APP_SRC "fedleave\\fedleave.exe"' in windows


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


def test_about_page_mentions_the_logo_asset():
    about = (ROOT / "help" / "about-fedleave-calendar.html").read_text()

    assert "../assets/fedleave-logo.png" in about
    assert "Version 0.2.0" in about
