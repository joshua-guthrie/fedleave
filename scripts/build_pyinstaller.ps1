param(
    [switch]$OneFile = $true,
    [string]$Dist = "$PSScriptRoot\..\dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$VENV_DIR = Join-Path $HERE ".pyinstaller-venv"
$DIST_DIR = Resolve-Path -Path $Dist

Write-Host "Building fedleave with PyInstaller (venv: $VENV_DIR)"
python -m venv "$VENV_DIR"
& "$VENV_DIR\Scripts\python.exe" -m pip install --upgrade pip
& "$VENV_DIR\Scripts\python.exe" -m pip install pyinstaller
& "$VENV_DIR\Scripts\python.exe" -m pip install -r "$HERE\requirements.txt"

$ENTRY = Join-Path $HERE ".pyinstaller_entry.py"
@"
from fedleave.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $ENTRY -Encoding utf8

$PYINSTALLER_ARGS = @(
    if ($OneFile) { '--onefile' }
    '--name', 'fedleave'
    '--console'
    '--hidden-import', 'holidays'
    '--hidden-import', 'icalendar'
    '--distpath', "$DIST_DIR"
    '--workpath', "$HERE\.pyinstaller-build"
    '--specpath', "$HERE\.pyinstaller-spec"
    '-F', "$ENTRY"
)

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller @PYINSTALLER_ARGS

# Build AnnualLeaveChartForTheYear companion application
$CHART_ENTRY = Join-Path $HERE ".pyinstaller_chart_entry.py"
@"
from annual_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $CHART_ENTRY -Encoding utf8

$CHART_ARGS = @(
    if ($OneFile) { '--onefile' }
    '--name', 'AnnualLeaveChartForTheYear'
    '--console'
    '--hidden-import', 'PIL'
    '--hidden-import', 'PIL.Image'
    '--hidden-import', 'PIL.ImageDraw'
    '--hidden-import', 'PIL.ImageFont'
    '--hidden-import', 'numpy'
    '--distpath', "$DIST_DIR"
    '--workpath', "$HERE\.pyinstaller-build"
    '--specpath', "$HERE\.pyinstaller-spec"
    '-F', "$CHART_ENTRY"
)

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller @CHART_ARGS

Write-Host "Build complete. Binaries in $DIST_DIR"
Write-Host "  - fedleave"
Write-Host "  - AnnualLeaveChartForTheYear"
