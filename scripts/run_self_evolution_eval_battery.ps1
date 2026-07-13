[CmdletBinding()]
param(
    [ValidateSet('all', 'domain', 'behavior')]
    [string]$Loop = 'all',
    [ValidateSet('smoke', 'core', 'deep')]
    [string]$Profile = 'smoke',
    [ValidateSet('auto', 'verify', 'fresh')]
    [string]$DomainMode = 'auto',
    [string]$RuntimeRoot = $(if ($env:XINAO_RUNTIME_ROOT) { $env:XINAO_RUNTIME_ROOT } else { 'D:\XINAO_RESEARCH_RUNTIME' }),
    [string]$CodexHome = $(Join-Path $HOME '.codex')
)

$ErrorActionPreference = 'Stop'
$batteryId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$batteryRoot = Join-Path $RuntimeRoot "state\human-capabilities\evals\self-evolution-battery\$batteryId"
New-Item -ItemType Directory -Path $batteryRoot -Force | Out-Null
$results = @()
$failed = $false

function Invoke-LoopRunner {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$ScriptName,
        [hashtable]$Parameters = @{}
    )
    $scriptPath = Join-Path $PSScriptRoot $ScriptName
    $consolePath = Join-Path $batteryRoot "$Name.console.log"
    $console = & $scriptPath @Parameters 2>&1
    $code = $LASTEXITCODE
    $console | Set-Content -LiteralPath $consolePath -Encoding utf8NoBOM
    return [ordered]@{
        loop = $Name
        runner = $ScriptName
        exit_code = $code
        ok = ($code -eq 0)
        evidence = if ($console) { [string](@($console)[-1]) } else { $null }
        console = $consolePath
    }
}

try {
    if ($Loop -in @('all', 'domain')) {
        $resolvedDomainMode = $DomainMode
        if ($resolvedDomainMode -eq 'auto') {
            $resolvedDomainMode = if ($Profile -eq 'deep') { 'fresh' } else { 'verify' }
        }
        $results += Invoke-LoopRunner -Name 'domain' -ScriptName 'run_domain_self_evolution.ps1' `
            -Parameters @{ Mode = $resolvedDomainMode; RuntimeRoot = $RuntimeRoot }
        if (-not $results[-1].ok) { $failed = $true }
    }
    if ($Loop -in @('all', 'behavior')) {
        $results += Invoke-LoopRunner -Name 'behavior' -ScriptName 'run_behavior_regression.ps1' `
            -Parameters @{ Profile = $Profile; RuntimeRoot = $RuntimeRoot; CodexHome = $CodexHome }
        if (-not $results[-1].ok) { $failed = $true }
    }
}
catch {
    $failed = $true
    $results += [ordered]@{
        loop = 'battery'
        runner = ''
        exit_code = 1
        ok = $false
        error = $_.Exception.Message
    }
}

$summary = [ordered]@{
    schema_version = 'xinao.dual_self_evolution_battery.v1'
    battery_id = $batteryId
    loop_filter = $Loop
    profile = $Profile
    generated_at = (Get-Date).ToString('o')
    repository_git_sha = (& git -C (Split-Path -Parent $PSScriptRoot) rev-parse HEAD 2>$null).Trim()
    repository_git_dirty = (@(& git -C (Split-Path -Parent $PSScriptRoot) status --porcelain=v1 2>$null).Count -gt 0)
    shared_shape = @('search', 'frozen_protocol', 'append_only_ledger', 'evidence_bound_promotion')
    loop_objects = [ordered]@{
        domain = 'candidate_model_rule_math_and_settlement'
        behavior = 'agent_instruction_routing_tool_and_preference_behavior'
    }
    admission_fixture_only = @('control_plane_incident', 'incident_response_lifecycle')
    cross_loop_completion_claim_allowed = $false
    results = $results
    ok = -not $failed
}
$summaryPath = Join-Path $batteryRoot 'summary.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding utf8NoBOM
$latest = Join-Path $RuntimeRoot 'state\human-capabilities\evals\self-evolution-battery\latest.json'
Copy-Item -LiteralPath $summaryPath -Destination $latest -Force
Write-Output $summaryPath
if ($failed) { exit 1 }
