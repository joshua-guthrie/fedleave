param(
    [string]$Dist = "$PSScriptRoot\..\dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$DIST_ROOT = [System.IO.Path]::GetFullPath($Dist)
$APP_DIST = Join-Path $DIST_ROOT "FedLeaveCalendar-Windows"
$VENV_DIR = Join-Path $HERE ".pyinstaller-gui-venv"

python -m venv "$VENV_DIR"
& "$VENV_DIR\Scripts\python.exe" -m pip install --upgrade pip
& "$VENV_DIR\Scripts\python.exe" -m pip install pyinstaller
& "$VENV_DIR\Scripts\python.exe" -m pip install -r "$HERE\requirements.txt"
& "$VENV_DIR\Scripts\python.exe" -m pip install -r "$HERE\requirements-gui.txt"

& "$HERE\scripts\build_pyinstaller.ps1" -Dist "$DIST_ROOT"

$ENTRY = Join-Path $HERE ".pyinstaller_gui_entry.py"
@"
from fedleave_gui.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $ENTRY -Encoding utf8

if (Test-Path $APP_DIST) {
    Remove-Item -Recurse -Force $APP_DIST
}

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --onedir `
    --windowed `
    --name FedLeaveCalendar `
    --add-data "$HERE\help;help" `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --hidden-import PySide6.QtPrintSupport `
    --distpath "$DIST_ROOT" `
    --workpath "$HERE\.pyinstaller-build" `
    --specpath "$HERE\.pyinstaller-spec" `
    "$ENTRY"

Move-Item -Force (Join-Path $DIST_ROOT "FedLeaveCalendar") $APP_DIST
Copy-Item -Force (Join-Path $DIST_ROOT "fedleave.exe") (Join-Path $APP_DIST "fedleave.exe")
Copy-Item -Recurse -Force (Join-Path $HERE "help") (Join-Path $APP_DIST "help")

Write-Host "GUI build complete: $APP_DIST"
Write-Host "  - FedLeaveCalendar.exe"
Write-Host "  - fedleave.exe"
