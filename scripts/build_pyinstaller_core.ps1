param(
    [string]$Dist = "$PSScriptRoot\..\dist\fedleave-Windows"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$VENV_DIR = Join-Path $HERE ".pyinstaller-venv"
$DIST_DIR = [System.IO.Path]::GetFullPath($Dist)
$DIST_PARENT = Split-Path -Parent $DIST_DIR
New-Item -ItemType Directory -Force -Path $DIST_PARENT | Out-Null
Get-ChildItem -Force -Path $DIST_PARENT -File | Remove-Item -Force
foreach ($BundlePath in @(
    (Join-Path $DIST_DIR "fedleave"),
    (Join-Path $DIST_DIR "AnnualLeaveChartForTheYear"),
    (Join-Path $DIST_DIR "SickLeaveChartForTheYear"),
    (Join-Path $DIST_DIR "CreditHoursChartForTheYear"),
    (Join-Path $DIST_DIR "CompTimeChartForTheYear"),
    (Join-Path $DIST_DIR "TravelCompChartForTheYear"),
    (Join-Path $DIST_DIR "TimeOffAwardChartForTheYear"),
    (Join-Path $DIST_DIR "fedleaveMonthReportGraphic")
)) {
    if (Test-Path $BundlePath) {
        Remove-Item -Recurse -Force $BundlePath
    }
}

function Build-App {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AppName,
        [Parameter(Mandatory = $true)]
        [string]$EntryPath,
        [Parameter(Mandatory = $true)]
        [string[]]$HiddenImports
    )

    $bundlePath = Join-Path $DIST_DIR $AppName
    if (Test-Path $bundlePath) {
        Remove-Item -Recurse -Force $bundlePath
    }

    $pyinstallerArgs = @(
        '--noconfirm'
        '--onedir'
        '--name', $AppName
        '--console'
        '--distpath', $DIST_DIR
        '--workpath', "$HERE\.pyinstaller-build"
        '--specpath', "$HERE\.pyinstaller-spec"
    )

    foreach ($hiddenImport in $HiddenImports) {
        $pyinstallerArgs += @('--hidden-import', $hiddenImport)
    }

    $pyinstallerArgs += $EntryPath

    & "$VENV_DIR\Scripts\python.exe" -m PyInstaller @pyinstallerArgs

    $expectedExe = Join-Path $bundlePath "$AppName.exe"
    if (-not (Test-Path $expectedExe)) {
        throw "Expected Windows executable was not created: $expectedExe"
    }
}

function Assert-AppBundle {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AppName
    )

    $expectedExe = Join-Path (Join-Path $DIST_DIR $AppName) "$AppName.exe"
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

Build-App -AppName "fedleave" -EntryPath $ENTRY -HiddenImports @('holidays', 'icalendar')

# Build AnnualLeaveChartForTheYear companion application
$CHART_ENTRY = Join-Path $HERE ".pyinstaller_chart_entry.py"
@"
from annual_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $CHART_ENTRY -Encoding utf8

Build-App -AppName "AnnualLeaveChartForTheYear" -EntryPath $CHART_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'numpy'
)

# Build SickLeaveChartForTheYear companion application
$SICK_CHART_ENTRY = Join-Path $HERE ".pyinstaller_sick_chart_entry.py"
@"
from sick_leave_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $SICK_CHART_ENTRY -Encoding utf8

Build-App -AppName "SickLeaveChartForTheYear" -EntryPath $SICK_CHART_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'numpy'
)

# Build CreditHoursChartForTheYear companion application
$CREDIT_CHART_ENTRY = Join-Path $HERE ".pyinstaller_credit_hours_chart_entry.py"
@"
from credit_hours_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $CREDIT_CHART_ENTRY -Encoding utf8

Build-App -AppName "CreditHoursChartForTheYear" -EntryPath $CREDIT_CHART_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'numpy'
)

# Build CompTimeChartForTheYear companion application
$COMP_CHART_ENTRY = Join-Path $HERE ".pyinstaller_comp_time_chart_entry.py"
@"
from comp_time_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $COMP_CHART_ENTRY -Encoding utf8

Build-App -AppName "CompTimeChartForTheYear" -EntryPath $COMP_CHART_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'numpy'
)

# Build TravelCompChartForTheYear companion application
$TRAVEL_CHART_ENTRY = Join-Path $HERE ".pyinstaller_travel_comp_chart_entry.py"
@"
from travel_comp_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $TRAVEL_CHART_ENTRY -Encoding utf8

Build-App -AppName "TravelCompChartForTheYear" -EntryPath $TRAVEL_CHART_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'numpy'
)

# Build TimeOffAwardChartForTheYear companion application
$TIME_OFF_CHART_ENTRY = Join-Path $HERE ".pyinstaller_time_off_award_chart_entry.py"
@"
from time_off_award_chart.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $TIME_OFF_CHART_ENTRY -Encoding utf8

Build-App -AppName "TimeOffAwardChartForTheYear" -EntryPath $TIME_OFF_CHART_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'numpy'
)

# Build fedleaveMonthReportGraphic companion application
$MONTH_REPORT_ENTRY = Join-Path $HERE ".pyinstaller_month_report_entry.py"
@"
from fedleave_month_report_graphic.__main__ import main

if __name__ == '__main__':
    main()
"@ | Set-Content -Path $MONTH_REPORT_ENTRY -Encoding utf8

Build-App -AppName "fedleaveMonthReportGraphic" -EntryPath $MONTH_REPORT_ENTRY -HiddenImports @(
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont'
)

Assert-AppBundle -AppName "fedleave"
Assert-AppBundle -AppName "AnnualLeaveChartForTheYear"
Assert-AppBundle -AppName "SickLeaveChartForTheYear"
Assert-AppBundle -AppName "CreditHoursChartForTheYear"
Assert-AppBundle -AppName "CompTimeChartForTheYear"
Assert-AppBundle -AppName "TravelCompChartForTheYear"
Assert-AppBundle -AppName "TimeOffAwardChartForTheYear"
Assert-AppBundle -AppName "fedleaveMonthReportGraphic"

Write-Host "Build complete. Binaries in $DIST_DIR"
Write-Host "  - fedleave\fedleave.exe"
Write-Host "  - AnnualLeaveChartForTheYear\AnnualLeaveChartForTheYear.exe"
Write-Host "  - SickLeaveChartForTheYear\SickLeaveChartForTheYear.exe"
Write-Host "  - CreditHoursChartForTheYear\CreditHoursChartForTheYear.exe"
Write-Host "  - CompTimeChartForTheYear\CompTimeChartForTheYear.exe"
Write-Host "  - TravelCompChartForTheYear\TravelCompChartForTheYear.exe"
Write-Host "  - TimeOffAwardChartForTheYear\TimeOffAwardChartForTheYear.exe"
Write-Host "  - fedleaveMonthReportGraphic\fedleaveMonthReportGraphic.exe"
