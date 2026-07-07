param(
    [switch]$OneFile = $true,
    [string]$Dist = "$PSScriptRoot\..\dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$VENV_DIR = Join-Path $HERE ".pyinstaller-venv"
$DIST_DIR = [System.IO.Path]::GetFullPath($Dist)
New-Item -ItemType Directory -Force -Path $DIST_DIR | Out-Null

function Move-BuildOutputToDist {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AppName
    )

    $expectedExe = Join-Path $DIST_DIR "$AppName.exe"
    if (Test-Path $expectedExe) {
        return
    }

    $nestedExe = Join-Path (Join-Path $DIST_DIR $AppName) "$AppName.exe"
    if (Test-Path $nestedExe) {
        $nestedDir = Join-Path $DIST_DIR $AppName
        Get-ChildItem -Force -Path $nestedDir | ForEach-Object {
            if ($_.FullName -ne $nestedExe) {
                Move-Item -Force -Path $_.FullName -Destination (Join-Path $DIST_DIR $_.Name)
            }
        }
        Move-Item -Force -Path $nestedExe -Destination $expectedExe
        Remove-Item -Force -Recurse -Path $nestedDir
    }
}

function Assert-DistExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AppName
    )

    $expectedExe = Join-Path $DIST_DIR "$AppName.exe"
    if (-not (Test-Path $expectedExe)) {
        throw "Expected Windows executable was not created in dist: $expectedExe"
    }
}

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
    "$ENTRY"
)

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller @PYINSTALLER_ARGS
Move-BuildOutputToDist -AppName "fedleave"

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
    "$CHART_ENTRY"
)

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller @CHART_ARGS
Move-BuildOutputToDist -AppName "AnnualLeaveChartForTheYear"

# Build SickLeaveChartForTheYear companion application
$SICK_CHART_ENTRY = Join-Path $HERE ".pyinstaller_sick_chart_entry.py"
@"
from sick_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $SICK_CHART_ENTRY -Encoding utf8

$SICK_CHART_ARGS = @(
    if ($OneFile) { '--onefile' }
    '--name', 'SickLeaveChartForTheYear'
    '--console'
    '--hidden-import', 'PIL'
    '--hidden-import', 'PIL.Image'
    '--hidden-import', 'PIL.ImageDraw'
    '--hidden-import', 'PIL.ImageFont'
    '--hidden-import', 'numpy'
    '--distpath', "$DIST_DIR"
    '--workpath', "$HERE\.pyinstaller-build"
    '--specpath', "$HERE\.pyinstaller-spec"
    "$SICK_CHART_ENTRY"
)

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller @SICK_CHART_ARGS
Move-BuildOutputToDist -AppName "SickLeaveChartForTheYear"

# Build fedleaveMonthReportGraphic companion application
$MONTH_REPORT_ENTRY = Join-Path $HERE ".pyinstaller_month_report_entry.py"
@"
from fedleave_month_report_graphic.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $MONTH_REPORT_ENTRY -Encoding utf8

$MONTH_REPORT_ARGS = @(
    if ($OneFile) { '--onefile' }
    '--name', 'fedleaveMonthReportGraphic'
    '--console'
    '--hidden-import', 'PIL'
    '--hidden-import', 'PIL.Image'
    '--hidden-import', 'PIL.ImageDraw'
    '--hidden-import', 'PIL.ImageFont'
    '--distpath', "$DIST_DIR"
    '--workpath', "$HERE\.pyinstaller-build"
    '--specpath', "$HERE\.pyinstaller-spec"
    "$MONTH_REPORT_ENTRY"
)

& "$VENV_DIR\Scripts\python.exe" -m PyInstaller @MONTH_REPORT_ARGS
Move-BuildOutputToDist -AppName "fedleaveMonthReportGraphic"

Assert-DistExecutable -AppName "fedleave"
Assert-DistExecutable -AppName "AnnualLeaveChartForTheYear"
Assert-DistExecutable -AppName "SickLeaveChartForTheYear"
Assert-DistExecutable -AppName "fedleaveMonthReportGraphic"

Write-Host "Build complete. Binaries in $DIST_DIR"
Write-Host "  - fedleave.exe"
Write-Host "  - AnnualLeaveChartForTheYear.exe"
Write-Host "  - SickLeaveChartForTheYear.exe"
Write-Host "  - fedleaveMonthReportGraphic.exe"
