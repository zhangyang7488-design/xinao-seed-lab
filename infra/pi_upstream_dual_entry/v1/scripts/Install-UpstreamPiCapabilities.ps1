#Requires -Version 5.1
[CmdletBinding()]
param([ValidateSet('prime-b','prime-s')][string[]]$Profile = @('prime-s'))

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PiDualEntry.Common.ps1')

Remove-Item Env:XINAO_PI_NATIVE_CONTINUATION_ABORT_FENCE -ErrorAction SilentlyContinue
Clear-PiSubagentCapacityEnvironment
$maintenanceLocks = Enter-PiDualEntryMaintenanceLocks -Profile $Profile -IncludeHighCapacity:('prime-s' -in @($Profile))
try {
& (Join-Path $PSScriptRoot 'Initialize-UpstreamPiProfiles.ps1') -Profile $Profile | Out-Null

$receipts = @()
foreach ($profileName in $Profile) {
    $spec = Get-PiDualEntrySpec -Profile $profileName
    $capacityProfile = Get-PiSubagentCapacityProfile -Profile $profileName
    $subagentCapacityStaticPolicy = Get-PiSubagentCapacityStaticPolicy -Profile $profileName
    $subagentCapacity = Assert-PiSubagentCapacityProjection -Profile $profileName -AgentDir $spec.AgentDir
    Assert-PiDualEntryBinary -Spec $spec
    & (Join-Path $PSScriptRoot 'Set-PiSBodyConfiguration.ps1') -AgentDir $spec.AgentDir | Out-Null
    $env:PI_CODING_AGENT_DIR = $spec.AgentDir
    $env:PI_CODING_AGENT_SESSION_DIR = $spec.SessionDir
    $env:PI_SKIP_VERSION_CHECK = '1'
    $env:PI_TELEMETRY = '0'
    $env:PI_SUBAGENT_MAX_DEPTH = [string]$capacityProfile.MaxSubagentDepth
    $env:CODEX_HOME = $spec.CodexHome

    foreach ($package in @($spec.Packages)) {
        $install = Invoke-PiDualEntryNativeCommand -FilePath $spec.PiCommand -ArgumentList @('install',$package,'--no-approve')
        if ($install.exit_code -ne 0) {
            throw "PI_CAPABILITY_INSTALL_FAILED: profile=$profileName package=$package output=$($install.output -join ' ')"
        }
    }
    $subagentsCompatibility = $null
    $subagentsOwnerSessionStopCompatibility = $null
    $subagentsFilesystemPolicyCompatibility = $null
    $hermesSessionCompatibility = $null
    $midTurnCompactionCompatibility = $null
    $nativeContinuationCompatibility = $null
    $highCapacityCompatibility = $null
    $subagentsCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsWindowsCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
    if ($profileName -eq 'prime-s') {
        $subagentsOwnerSessionStopCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsSessionStopCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
        $subagentsFilesystemPolicyCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSSubagentsFilesystemPolicy.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
    }
    $hermesSessionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSHermesSessionCompatibility.ps1') -AgentDir $spec.AgentDir) | ConvertFrom-Json
    $midTurnCompactionCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSMidTurnCompactionCompatibility.ps1') -PiToolRoot $spec.PiToolRoot) | ConvertFrom-Json
    $post0841UpstreamCompatibility = $null
    if ($profileName -eq 'prime-s') {
        $nativeContinuationCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSNativeContinuationCompatibility.ps1') -PiToolRoot $spec.PiToolRoot) | ConvertFrom-Json
        $highCapacityCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSHighCapacityCompatibility.ps1') -AgentDir $spec.AgentDir -PiToolRoot $spec.PiToolRoot) | ConvertFrom-Json
        $post0841UpstreamCompatibility = (& (Join-Path $PSScriptRoot 'Apply-PiSPost0841UpstreamCompatibility.ps1') -PiToolRoot $spec.PiToolRoot) | ConvertFrom-Json
    }
    $list = @(& $spec.PiCommand list 2>&1)
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
        pi_tool_root = $spec.PiToolRoot
        packages = @($spec.Packages)
        package_list_verified = $true
        subagent_capacity = $subagentCapacity
        subagent_capacity_static_policy = $subagentCapacityStaticPolicy
        scheduled_runs_enabled = $false
        missions_enabled = $false
        automatic_autoresearch_loop_started = $false
        subagents_windows_compatibility = $subagentsCompatibility
        subagents_owner_session_stop_compatibility = $subagentsOwnerSessionStopCompatibility
        subagents_filesystem_policy_compatibility = $subagentsFilesystemPolicyCompatibility
        hermes_session_compatibility = $hermesSessionCompatibility
        midturn_compaction_compatibility = $midTurnCompactionCompatibility
        native_continuation_compatibility = $nativeContinuationCompatibility
        high_capacity_compatibility = $highCapacityCompatibility
        post_0841_upstream_compatibility = $post0841UpstreamCompatibility
    }
}
$receipts | ConvertTo-Json -Depth 6
} finally {
    Exit-PiDualEntryMaintenanceLocks -Handle $maintenanceLocks
}
