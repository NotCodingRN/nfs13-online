param([string]$AwsInstaller)
$ErrorActionPreference = 'Stop'
$awsPresent = (Get-Command aws.exe -ErrorAction SilentlyContinue) -or
    (Test-Path "$env:LOCALAPPDATA\Programs\Amazon\AWSCLIV2\aws.exe") -or
    (Test-Path "$env:ProgramFiles\Amazon\AWSCLIV2\aws.exe")
if (-not $awsPresent) {
    if (-not (Test-Path -LiteralPath $AwsInstaller)) { throw 'The bundled AWS CLI installer is missing' }
    $signature = Get-AuthenticodeSignature -LiteralPath $AwsInstaller
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Amazon Web Services') {
        throw 'AWS CLI installer signature validation failed'
    }
    $result = Start-Process msiexec.exe -ArgumentList @('/i',('"'+$AwsInstaller+'"'),'/qb','/norestart') -Wait -PassThru -WindowStyle Hidden
    if ($result.ExitCode -notin @(0,3010)) { throw "AWS CLI installation failed: $($result.ExitCode)" }
}
if (-not (Test-Path "$env:WINDIR\System32\OpenSSH\ssh.exe")) {
    Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0 | Out-Null
}
