# Copyright (C) 2026 sn0wd0wn (gregel, Dantiox, Alexes)
# SPDX-License-Identifier: AGPL-3.0-only
<#
.SYNOPSIS
    Install and start the nfs13 server on Windows.

.DESCRIPTION
    Windows counterpart of install/install_server.sh.

    The game only speaks SSLv3 (DirtySock ProtoSSL), which every current
    OpenSSL build has dropped. This script uses a stunnel that still ships
    OpenSSL 1.0.2 (stunnel 5.39), which has SSLv3 and RC4-SHA.

    Download it from:
        https://www.stunnel.org/archive/5.x/stunnel-5.39-win32-installer.exe
    and run it once (it installs to "C:\Program Files (x86)\stunnel").

.PARAMETER ServerIp
    The address the game clients use to reach this machine (LAN or VPN IP).

.PARAMETER InstallDir
    Where to put the server. Defaults to $HOME\nfs13-server.

.PARAMETER StunnelDir
    Where stunnel lives. Defaults to "C:\Program Files (x86)\stunnel".

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install\install_server_windows.ps1 192.168.1.50
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ServerIp,

    [string]$InstallDir = (Join-Path $HOME "nfs13-server"),
    [string]$StunnelDir = "C:\Program Files (x86)\stunnel",
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$StunnelExe = Join-Path $StunnelDir "bin\stunnel.exe"
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { throw "python was not found on PATH" }
if (-not (Test-Path $StunnelExe)) {
    throw "stunnel not found at $StunnelExe`n" +
          "Install stunnel 5.39 (OpenSSL 1.0.2, still has SSLv3):`n" +
          "  https://www.stunnel.org/archive/5.x/stunnel-5.39-win32-installer.exe"
}

New-Item -ItemType Directory -Force -Path $InstallDir, "$InstallDir\certs", "$InstallDir\frontend" | Out-Null
Copy-Item (Join-Path $Repo "server\server.py") (Join-Path $InstallDir "server.py") -Force
Copy-Item (Join-Path $Repo "server\admin_api.py") (Join-Path $InstallDir "admin_api.py") -Force

# The friend roster: the server's own friends list (roster friends plus every
# player that logged in).  An existing roster is kept, so the server's own
# friends survive a reinstall.
if (-not (Test-Path (Join-Path $InstallDir "friends.json"))) {
    Copy-Item (Join-Path $Repo "server\friends.json") (Join-Path $InstallDir "friends.json") -Force
}

# --- certificate ------------------------------------------------------------
# Same shape as the one used in testing: self-signed, SHA-1, RSA 2048, CN=*.ea.com
# The SHA-1 signature is not optional: the game's 2012-era ProtoSSL parser
# does not understand sha256WithRSAEncryption, rejects the certificate, drops
# the TLS connection and then crashes.  Regenerate anything else.
$certPath = Join-Path $InstallDir "certs\cert.pem"
$certOk = $false
if (Test-Path $certPath) {
    # Read the signature algorithm with python: the bundled openssl.exe writes a
    # warning about its missing configuration file to stderr, which would be a
    # fatal error under $ErrorActionPreference = "Stop".
    $algo = & $Python -c "import sys;from cryptography import x509;print(x509.load_pem_x509_certificate(open(sys.argv[1],'rb').read()).signature_algorithm_oid._name)" $certPath 2>$null
    $certOk = "$algo" -match "sha1"
}
if (-not $certOk) {
    if (Test-Path $certPath) {
        Write-Host "Existing certificate is not SHA-1 signed; regenerating it."
    }
    & $Python (Join-Path $Repo "tools\make_nfs13_cert.py") --out-dir "$InstallDir\certs" --cn "*.ea.com" --force
    if ($LASTEXITCODE -ne 0) { throw "certificate generation failed" }
}

# --- stunnel configuration --------------------------------------------------
# stunnel 5.39 ships OpenSSL 1.0.2, which has no security levels, so the
# @SECLEVEL=0 cipher string from the Linux frontend is not needed here.
#
# stunnel disables SSLv3 by default. "options = -NO_SSLv3" clears that flag
# (stunnel keeps a separate "clear" mask for it); SSLv2 stays off.
#
# "foreground" is Unix only, and "sslVersionMin"/"sslVersionMax" only exist
# from stunnel 5.46 on - older builds select the protocol with "options".
$versionLines = @()
$optionsLines = @("options = NO_SSLv2", "options = -NO_SSLv3")
$stunnelRaw = [System.IO.File]::ReadAllText($StunnelExe, [System.Text.Encoding]::ASCII)
if ($stunnelRaw -match 'stunnel\s+(\d+)\.(\d+)') {
    $sv = [version]::new([int]$Matches[1], [int]$Matches[2], 0)
    if ($sv -ge [version]::new(5, 46, 0)) {
        $versionLines = @("sslVersionMin = SSLv3", "sslVersionMax = TLSv1.2")
    }
}
$versionBlock = if ($versionLines) { $versionLines -join "`n" + "`n" } else { "" }
$optionsBlock = $optionsLines -join "`n"

$stunnelConf = @"
debug = info
output = $InstallDir\frontend\stunnel.log
socket = l:TCP_NODELAY=1
fips = no

[blaze]
accept = 0.0.0.0:42127
connect = 127.0.0.1:42128
cert = $InstallDir\certs\cert.pem
key = $InstallDir\certs\key.pem
$versionBlock$optionsBlock
ciphers = ALL:COMPLEMENTOFALL
verifyChain = no
; The Python backend trusts only loopback and consumes HAProxy PROXY v1.
; This preserves each player's LAN IP through TLS for stable persona IDs.
protocol = proxy

[https]
accept = 0.0.0.0:44125
connect = 127.0.0.1:44126
cert = $InstallDir\certs\cert.pem
key = $InstallDir\certs\key.pem
$versionBlock$optionsBlock
ciphers = ALL:COMPLEMENTOFALL
verifyChain = no
"@
Set-Content -Path "$InstallDir\frontend\stunnel.conf" -Value $stunnelConf -Encoding ASCII

if ($NoStart) {
    Write-Host "Installed in $InstallDir (not started)."
    exit 0
}

# --- start ------------------------------------------------------------------
# Stop a previously installed server first.  Get-Process does not expose the
# command line, so ask CIM for the processes that run this server.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$InstallDir\server.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# The stunnel frontend from a previous run still holds the ports.
Get-Process stunnel, tstunnel -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$StunnelDir*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Start both services detached from this shell.  Win32_Process.Create runs the
# command under WMI, so the services survive the shell that installed them
# (a plain Start-Process child is killed together with its parent).
$serverCmd = Join-Path $InstallDir "run-server.cmd"
Set-Content -Path $serverCmd -Encoding ASCII -Value @"
@echo off
cd /d "$InstallDir"
set NFS13_HOST=$ServerIp
set PYTHONUNBUFFERED=1
"$Python" "$InstallDir\server.py" >> "$InstallDir\server.log" 2>> "$InstallDir\server.err.log"
"@

$frontendCmd = Join-Path $InstallDir "run-frontend.cmd"
Set-Content -Path $frontendCmd -Encoding ASCII -Value @"
@echo off
cd /d "$InstallDir"
"$StunnelExe" "$InstallDir\frontend\stunnel.conf"
"@

Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "cmd.exe /c `"$serverCmd`""
    CurrentDirectory = $InstallDir
} | Out-Null

Start-Sleep -Seconds 2

Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "cmd.exe /c `"$frontendCmd`""
    CurrentDirectory = $InstallDir
} | Out-Null

Start-Sleep -Seconds 3

$listening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 42127, 44125, 8080, 17500, 42128, 44126 } |
    Sort-Object LocalPort | ForEach-Object { "  TCP $($_.LocalAddress):$($_.LocalPort)" }

Write-Host ""
Write-Host "nfs13 server installed in $InstallDir and started."
Write-Host ""
Write-Host "Listening:"
$listening
Write-Host ""
Write-Host "Point these names at $ServerIp (hosts file, needs admin):"
Get-Content (Join-Path $Repo "client\hosts.txt") | ForEach-Object { "  $_" }
Write-Host ""
Write-Host "Logs:"
Write-Host "  $InstallDir\server.log"
Write-Host "  $InstallDir\frontend\stunnel.log"
