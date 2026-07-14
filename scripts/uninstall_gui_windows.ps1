Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$INSTALL_ROOT = Join-Path $env:LOCALAPPDATA "Programs\FedLeave"
$FEDLEAVE_BUNDLE = Join-Path $INSTALL_ROOT "fedleave"
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FedLeave Calendar.lnk"
$desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "FedLeave Calendar.lnk"

function Remove-UserPathEntry {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Entry
    )

    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $current) {
        return
    }

    $normalized = $Entry.TrimEnd('\').ToLowerInvariant()
    $parts = $current -split ';' | Where-Object {
        $_ -and $_.TrimEnd('\').ToLowerInvariant() -ne $normalized
    }
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ';'), "User")
    $env:Path = ($env:Path -split ';' | Where-Object {
        $_ -and $_.TrimEnd('\').ToLowerInvariant() -ne $normalized
    }) -join ';'
}

Remove-UserPathEntry -Entry $FEDLEAVE_BUNDLE
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $INSTALL_ROOT
Remove-Item -Force -ErrorAction SilentlyContinue $startMenu
Remove-Item -Force -ErrorAction SilentlyContinue $desktop

Write-Host "Removed FedLeave application files. Leave data and GUI settings were preserved."
