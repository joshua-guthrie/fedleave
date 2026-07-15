param(
    [string]$Dist = "$PSScriptRoot\..\dist\fedleave-Windows",
    [switch]$SkipBackendBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$DIST_ROOT = [System.IO.Path]::GetFullPath($Dist)
$DIST_PARENT = Split-Path -Parent $DIST_ROOT
$VENV_DIR = Join-Path $HERE ".pyinstaller-gui-venv"

python -m venv "$VENV_DIR"
& "$VENV_DIR\Scripts\python.exe" -m pip install --upgrade pip
& "$VENV_DIR\Scripts\python.exe" -m pip install pyinstaller
& "$VENV_DIR\Scripts\python.exe" -m pip install -r "$HERE\requirements.txt"
& "$VENV_DIR\Scripts\python.exe" -m pip install -r "$HERE\requirements-gui.txt"

New-Item -ItemType Directory -Force -Path $DIST_PARENT | Out-Null

if (-not $SkipBackendBuild) {
    & "$HERE\scripts\build_pyinstaller_core.ps1" -Dist "$DIST_ROOT"
}

$backendExe = Join-Path $DIST_ROOT "fedleave\fedleave.exe"
if (-not (Test-Path $backendExe)) {
    throw "Expected backend bundle was not found: $backendExe`nRun scripts\build_pyinstaller_core.ps1 first or omit -SkipBackendBuild."
}

$guiBundle = Join-Path $DIST_ROOT "FedLeaveCalendar"
if (Test-Path $guiBundle) {
    Remove-Item -Recurse -Force $guiBundle
}

$ENTRY = Join-Path $HERE ".pyinstaller_gui_entry.py"
@"
from fedleave_gui.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $ENTRY -Encoding utf8

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --onedir `
    --windowed `
    --name FedLeaveCalendar `
    --icon "$HERE\assets\fedleave-icon.ico" `
    --add-data "$HERE\help;help" `
    --add-data "$HERE\assets;assets" `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --hidden-import PySide6.QtPrintSupport `
    --hidden-import shiboken6 `
    --hidden-import shiboken6.Shiboken `
    --collect-all shiboken6 `
    --distpath "$DIST_ROOT" `
    --workpath "$HERE\.pyinstaller-build" `
    --specpath "$HERE\.pyinstaller-spec" `
    "$ENTRY"

Write-Host "GUI build complete: $DIST_ROOT"
Write-Host "  - FedLeaveCalendar\FedLeaveCalendar.exe"
Write-Host "  - backend bundle is left in place or created by the core build"
