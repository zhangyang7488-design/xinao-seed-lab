#Requires -Version 5.1
[CmdletBinding()]
param([ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'))

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
& (Join-Path $PSScriptRoot 'Initialize-UpstreamPiProfiles.ps1') -Profile $Profile | Out-Null

$receipts = @()
foreach ($profile in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profile
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'
    $env:PI_SUBAGENT_MAX_DEPTH = '2'
    $env:CODEX_HOME = $spec.CodexHome

    foreach ($package in @($spec.Packages)) {
        $output = @(& $script:PiDualEntryCommand install $package --no-approve 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "PI_CAPABILITY_INSTALL_FAILED: profile=$profile package=$package output=$($output -join ' ')"
        }
    }
    $list = @(& $script:PiDualEntryCommand list 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "PI_CAPABILITY_LIST_FAILED: profile=$profile output=$($list -join ' ')" }
    foreach ($package in @($spec.Packages)) {
        $name = ($package -replace '^npm:','') -replace '@\d+(?:\.\d+)*$',''
        if (-not (($list -join [Environment]::NewLine) -match [regex]::Escape($name))) {
            throw "PI_CAPABILITY_NOT_LISTED: profile=$profile package=$package"
        }
    }
    $receipts += [ordered]@{
        profile = $profile
        role = $spec.Role
        packages = @($spec.Packages)
        package_list_verified = $true
        scheduled_runs_enabled = $false
        missions_enabled = $false
        automatic_autoresearch_loop_started = $false
    }
}
$receipts | ConvertTo-Json -Depth 6
