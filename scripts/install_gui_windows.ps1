param(
    [switch]$DesktopShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$APP_SRC = Join-Path $HERE "dist\fedleave-Windows"
$INSTALL_DIR = Join-Path $env:LOCALAPPDATA "Programs\FedLeaveCalendar"

if (-not (Test-Path (Join-Path $APP_SRC "FedLeaveCalendar.exe"))) {
    throw "Build the GUI first with scripts\build_gui_pyinstaller.ps1"
}

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Copy-Item -Force (Join-Path $APP_SRC "FedLeaveCalendar.exe") $INSTALL_DIR
Copy-Item -Force (Join-Path $APP_SRC "fedleave.exe") $INSTALL_DIR

$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FedLeave Calendar.lnk"
$shortcut = $shell.CreateShortcut($startMenu)
$shortcut.TargetPath = Join-Path $INSTALL_DIR "FedLeaveCalendar.exe"
$shortcut.WorkingDirectory = $INSTALL_DIR
$shortcut.Save()

if ($DesktopShortcut) {
    $desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "FedLeave Calendar.lnk"
    $shortcut = $shell.CreateShortcut($desktop)
    $shortcut.TargetPath = Join-Path $INSTALL_DIR "FedLeaveCalendar.exe"
    $shortcut.WorkingDirectory = $INSTALL_DIR
    $shortcut.Save()
}

Write-Host "Installed FedLeave Calendar to $INSTALL_DIR"
