Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$INSTALL_DIR = Join-Path $env:LOCALAPPDATA "Programs\FedLeaveCalendar"
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FedLeave Calendar.lnk"
$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "FedLeave Calendar.lnk"

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $INSTALL_DIR
Remove-Item -Force -ErrorAction SilentlyContinue $startMenu
Remove-Item -Force -ErrorAction SilentlyContinue $desktop

Write-Host "Removed FedLeave Calendar application files. Leave data and GUI settings were preserved."
