param(
    [string]$Dist = "$PSScriptRoot\..\dist"
)

$HERE = Resolve-Path "$PSScriptRoot\.."
$DIST_DIR = [System.IO.Path]::GetFullPath($Dist)

& "$HERE\scripts\build_pyinstaller_core.ps1" -Dist $DIST_DIR
& "$HERE\scripts\build_gui_pyinstaller.ps1" -Dist $DIST_DIR -SkipBackendBuild
