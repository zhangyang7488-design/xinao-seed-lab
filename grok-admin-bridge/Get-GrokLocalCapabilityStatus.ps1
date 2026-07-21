#Requires -Version 5.1
<#
.SYNOPSIS
  Read-only repository capability probe.
.DESCRIPTION
  Reads local files only. It does not start services, invoke models, inspect
  interactive processes, dispatch workers, or mutate runtime state.
#>
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json"),
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$repoRoot = Split-Path -Parent $PSScriptRoot
$isGrok45 = $repoRoot -match 'workspace-grok-4[.]5-island'
$checkpoint = if ($isGrok45) {
    "D:\XINAO_RESEARCH_RUNTIME\state\grok_4_5\session_context\latest.json"
} else {
    "D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json"
}

$required = [ordered]@{
    bridge_config = $ConfigPath
    compose_file = [string]$config.grok_codex_s_native_temporal_route.compose
    checkpoint_script = (Join-Path $PSScriptRoot "Invoke-GrokSessionContextCheckpoint.ps1")
    contract_test = (Join-Path $PSScriptRoot "Test-GrokRepositoryContracts.ps1")
    bounded_worker_pool = (Join-Path $PSScriptRoot "Invoke-GrokWorkerPool.ps1")
}
if ($isGrok45) {
    $required.shell_capability = Join-Path $PSScriptRoot "Invoke-GrokAcpxTerminalCapabilityEnforce.ps1"
    $required.hidden_stdio = Join-Path $PSScriptRoot "Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1"
    $required.intent_decode = Join-Path $PSScriptRoot "Invoke-GrokEngineeringIntentDecode.ps1"
}

$files = [ordered]@{}
foreach ($entry in $required.GetEnumerator()) {
    $files[$entry.Key] = [bool](Test-Path -LiteralPath ([string]$entry.Value) -PathType Leaf)
}
$ok = (
    [string]$config.canonical_route.shape -eq "A/B dual-leg selected by task fit or existing route receipt" -and
    [string]$config.canonical_route.selection -eq "selected_by_task_fit_or_existing_route_receipt" -and
    [string]$config.canonical_route.leg_a.transport_id -eq "direct-grok-worker-pool" -and
    [string]$config.canonical_route.leg_b.transport_id -eq "temporal-docker-langgraph" -and
    [bool]$config.canonical_route.continuity.existing_route_receipt_precedence -and
    -not [bool]$config.canonical_route.continuity.continuous_or_resume_switches_leg -and
    [string]$config.bounded_worker_pool.route_role -eq "normal_leg_a" -and
    -not [bool]$config.bounded_worker_pool.is_unconditional_default -and
    [string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit" -and
    @($config.model_worker_routing.available_workers) -contains "codex_agents" -and
    [string]$config.grok_lane.provider -eq "grok" -and
    [bool]$config.prohibited_surfaces.visible_terminal -and
    [bool]$config.prohibited_surfaces.resident_loop -and
    @($files.Values | Where-Object { -not $_ }).Count -eq 0
)

$result = [ordered]@{
    schema_version = "xinao.grok_local_capability_status.v3"
    ok = [bool]$ok
    repository_root = $repoRoot
    repository_role = [string]$config.repository_role
    route_topology = [string]$config.canonical_route.shape
    route_selection = [string]$config.canonical_route.selection
    leg_a_transport = [string]$config.canonical_route.leg_a.transport_id
    leg_b_transport = [string]$config.canonical_route.leg_b.transport_id
    existing_route_receipt_precedence = [bool]$config.canonical_route.continuity.existing_route_receipt_precedence
    continuous_or_resume_switches_leg = [bool]$config.canonical_route.continuity.continuous_or_resume_switches_leg
    worker_selection = [string]$config.model_worker_routing.selection
    available_workers = @($config.model_worker_routing.available_workers)
    grok_lane_model = [string]$config.grok_lane.model
    width_policy = [string]$config.model_worker_routing.width_policy
    checkpoint_exists = [bool](Test-Path -LiteralPath $checkpoint -PathType Leaf)
    files = $files
    side_effects = "none_read_only"
}
if ($Quiet) {
    $result | ConvertTo-Json -Depth 6 -Compress
} else {
    $result | ConvertTo-Json -Depth 6
}
if (-not $ok) { exit 1 }
