param(
    [string]$Dist = "$PSScriptRoot\..\dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$DIST_ROOT = [System.IO.Path]::GetFullPath($Dist)
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

foreach ($LegacyPath in @(
    (Join-Path $DIST_ROOT "FedLeaveCalendar-Windows"),
    (Join-Path $DIST_ROOT "FedLeaveCalendar")
)) {
    if (Test-Path $LegacyPath) {
        Remove-Item -Recurse -Force $LegacyPath
    }
}

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --onefile `
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

Write-Host "GUI build complete: $DIST_ROOT"
Write-Host "  - FedLeaveCalendar.exe"
Write-Host "  - fedleave.exe (shared backend; not duplicated)"
