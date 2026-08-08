#Requires -Version 5.1
[CmdletBinding()]
param([ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'))

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Assert-PiDualEntryBinary
& (Join-Path $PSScriptRoot 'Initialize-UpstreamPiProfiles.ps1') -Profile $Profile | Out-Null

$receipts = @()
foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    if ($profileName -eq 'prime-s') {
        & (Join-Path $PSScriptRoot 'Set-PiSBodyConfiguration.ps1') -AgentDir $spec.AgentDir | Out-Null
    }
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'
    $env:PI_SUBAGENT_MAX_DEPTH = '2'
    $env:CODEX_HOME = $spec.CodexHome

    foreach ($package in @($spec.Packages)) {
        $output = @(& $script:PiDualEntryCommand install $package --no-approve 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "PI_CAPABILITY_INSTALL_FAILED: profile=$profileName package=$package output=$($output -join ' ')"
        }
    }
    $subagentsCompatibility = $null
    $hermesSessionCompatibility = $null
    $midTurnCompactionCompatibility = $null
    if ($profileName -eq 'prime-s') {
        $subagentsCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
        $hermesSessionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSHermesSessionCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
        $midTurnCompactionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1')) | ConvertFrom-Json
    }
    $list = @(& $script:PiDualEntryCommand list 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "PI_CAPABILITY_LIST_FAILED: profile=$profileName output=$($list -join ' ')" }
    foreach ($package in @($spec.Packages)) {
        $name = ($package -replace '^npm:','') -replace '@\d+(?:\.\d+)*$',''
        if (-not (($list -join [Environment]::NewLine) -match [regex]::Escape($name))) {
            throw "PI_CAPABILITY_NOT_LISTED: profile=$profileName package=$package"
        }
    }
    $receipts += [ordered]@{
        profile = $profileName
        role = $spec.Role
        packages = @($spec.Packages)
        package_list_verified = $true
        scheduled_runs_enabled = $false
        missions_enabled = $false
        automatic_autoresearch_loop_started = $false
        subagents_windows_compatibility = $subagentsCompatibility
        hermes_session_compatibility = $hermesSessionCompatibility
        midturn_compaction_compatibility = $midTurnCompactionCompatibility
    }
}
$receipts | ConvertTo-Json -Depth 6
