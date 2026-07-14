param(
    [switch]$DesktopShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HERE = Resolve-Path "$PSScriptRoot\.."
$APP_SRC = Join-Path $HERE "dist\fedleave-Windows"
$INSTALL_ROOT = Join-Path $env:LOCALAPPDATA "Programs\FedLeave"
$FEDLEAVE_BUNDLE = Join-Path $INSTALL_ROOT "fedleave"

if (-not (Test-Path (Join-Path $APP_SRC "FedLeaveCalendar\FedLeaveCalendar.exe"))) {
    throw "Build the GUI first with scripts\build_gui_pyinstaller.ps1"
}
if (-not (Test-Path (Join-Path $APP_SRC "fedleave\fedleave.exe"))) {
    throw "Build the core executables first with scripts\build_pyinstaller_core.ps1"
}

if (Test-Path $INSTALL_ROOT) {
    Remove-Item -Recurse -Force $INSTALL_ROOT
}

New-Item -ItemType Directory -Force -Path $INSTALL_ROOT | Out-Null
Get-ChildItem -Force -Path $APP_SRC -Directory | ForEach-Object {
    Copy-Item -Recurse -Force $_.FullName $INSTALL_ROOT
}

function Add-UserPathEntry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Entry
    )

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @()
    if ($current) {
        $parts = $current -split ';' | Where-Object { $_ }
    }
    $normalized = $Entry.TrimEnd('\').ToLowerInvariant()
    if ($parts | Where-Object { $_.TrimEnd('\').ToLowerInvariant() -eq $normalized }) {
        return
    }

    $updated = @($Entry) + $parts
    [Environment]::SetEnvironmentVariable("Path", ($updated -join ';'), "User")
    if ($env:Path) {
        $env:Path = "$Entry;$env:Path"
    } else {
        $env:Path = $Entry
    }
}

Get-ChildItem -Force -Path $INSTALL_ROOT -Directory | ForEach-Object {
    Add-UserPathEntry -Entry $_.FullName
}

$shell = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FedLeave Calendar.lnk"
$shortcut = $shell.CreateShortcut($startMenu)
$shortcut.TargetPath = Join-Path $INSTALL_ROOT "FedLeaveCalendar\FedLeaveCalendar.exe"
$shortcut.WorkingDirectory = Join-Path $INSTALL_ROOT "FedLeaveCalendar"
$shortcut.Save()

if ($DesktopShortcut) {
    $desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "FedLeave Calendar.lnk"
    $shortcut = $shell.CreateShortcut($desktop)
    $shortcut.TargetPath = Join-Path $INSTALL_ROOT "FedLeaveCalendar\FedLeaveCalendar.exe"
    $shortcut.WorkingDirectory = Join-Path $INSTALL_ROOT "FedLeaveCalendar"
    $shortcut.Save()
}

Write-Host "Installed FedLeave to $INSTALL_ROOT"
