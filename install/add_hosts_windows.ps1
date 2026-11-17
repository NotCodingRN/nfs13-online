# Copyright (C) 2026 sn0wd0wn (gregel, Dantiox, Alexes)
# SPDX-License-Identifier: AGPL-3.0-only
<#
.SYNOPSIS
    Add (or remove) the *.ea.com redirections the game needs, in the Windows hosts file.

.DESCRIPTION
    The game resolves the EA service names through the system resolver, so
    every name in client/hosts.txt has to point at the server.

    Editing C:\Windows\System32\drivers\etc\hosts needs administrator rights,
    so this script re-launches itself elevated and asks for the UAC prompt.

    Keep these names and UDP 3659 out of any fake-IP proxy (Clash, Mihomo, ...):
    a proxy that answers for *.ea.com with its own IP will break the redirect.

.PARAMETER ServerIp
    The address of the nfs13 server.

.PARAMETER Remove
    Delete the entries instead of adding them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install\add_hosts_windows.ps1 192.168.1.50
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ServerIp,

    [switch]$Remove,
    [switch]$Elevated,
    [string]$Log
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$HostsFile = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
$Names = Get-Content (Join-Path $Repo "client\hosts.txt") | Where-Object { $_.Trim() }

function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    if ($Elevated) { throw "still not elevated" }
    $log = Join-Path $env:TEMP "nfs13-hosts.log"
    "elevated run at $(Get-Date -Format s), elevating $PSCommandPath" | Out-File $log -Encoding utf8
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" $ServerIp -Elevated -Log `"$log`""
    if ($Remove) { $argList += " -Remove" }
    Write-Host "Requesting administrator rights for the hosts file..."
    try {
        Start-Process -FilePath "powershell.exe" -ArgumentList $argList -Verb RunAs -Wait -ErrorAction Stop
    } catch {
        "elevation failed: $($_.Exception.Message)" | Out-File $log -Append -Encoding utf8
        Write-Host "elevation failed: $($_.Exception.Message)"
        Write-Host "see $log"
        return
    }
    if (Test-Path $log) { Get-Content $log | ForEach-Object { Write-Host "  $_" } }
    return
}

$logFile = if ($Log) { $Log } else { Join-Path $env:TEMP "nfs13-hosts.log" }
try {
    $HostsFile = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
    $Names = Get-Content (Join-Path $Repo "client\hosts.txt") | Where-Object { $_.Trim() }

    $backup = "$HostsFile.nfs13.bak"
    if (-not (Test-Path $backup)) { Copy-Item $HostsFile $backup }

    $lines = Get-Content $HostsFile
    # Drop any previous nfs13 entries (they carry our marker)
    $lines = $lines | Where-Object { $_ -notmatch "#\s*nfs13" }

    if (-not $Remove) {
        $added = $Names | ForEach-Object { "$ServerIp`t$_`t# nfs13" }
        $lines = $lines + $added
    }

    Set-Content -Path $HostsFile -Value $lines -Encoding ASCII
    "OK: hosts file updated at $(Get-Date -Format s)" | Out-File $logFile -Append -Encoding utf8
    Write-Host ""
    Write-Host "hosts file updated ($HostsFile, backup at $backup)"
    if (-not $Remove) {
        Write-Host ""
        Write-Host "  $ServerIp -> $($Names -join ', ')"
    }
    Write-Host ""
    Write-Host "Flush the DNS cache:  ipconfig /flushdns"
} catch {
    "ERROR: $($_.Exception.Message)" | Out-File $logFile -Append -Encoding utf8
    Write-Host "ERROR: $($_.Exception.Message)"
    throw
}
