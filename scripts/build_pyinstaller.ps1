param(
    [string]$Dist = "$PSScriptRoot\..\dist"
)

$HERE = Resolve-Path "$PSScriptRoot\.."
$DIST_DIR = [System.IO.Path]::GetFullPath($Dist)
$PLATFORM_DIR = Join-Path $DIST_DIR "fedleave-Windows"
New-Item -ItemType Directory -Force -Path $DIST_DIR | Out-Null
Get-ChildItem -Force -Path $DIST_DIR -File | Remove-Item -Force
foreach ($LegacyPath in @(
    (Join-Path $DIST_DIR "FedLeaveCalendar-Windows"),
    (Join-Path $DIST_DIR "FedLeaveCalendar"),
    $PLATFORM_DIR
)) {
    if (Test-Path $LegacyPath) {
        Remove-Item -Recurse -Force $LegacyPath
    }
}

& "$HERE\scripts\build_pyinstaller_core.ps1" -Dist $PLATFORM_DIR
& "$HERE\scripts\build_gui_pyinstaller.ps1" -Dist $PLATFORM_DIR -SkipBackendBuild
