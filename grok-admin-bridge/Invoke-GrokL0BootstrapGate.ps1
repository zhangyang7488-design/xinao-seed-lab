#Requires -Version 5.1
<#
.SYNOPSIS
  Read-only L0 contract gate for the current repository.
#>
param(
    [string]$BridgeConfigPath = (Join-Path $PSScriptRoot "bridge.config.json"),
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $BridgeConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$repoRoot = Split-Path -Parent $PSScriptRoot
$forbidden = @(
    "grok-admin-bridge\Invoke-GrokLongWorkflowRunNext.ps1",
    "grok-admin-bridge\Invoke-GrokSubagentPoolOrchestrator.ps1",
    "grok-admin-bridge\Invoke-GrokPerpetualSeedLabDaemon.ps1",
    "grok-admin-bridge\Invoke-GrokWaveCycleRun.ps1",
    "grok-admin-bridge\Invoke-GrokManagedVisibleInject.ps1",
    "grok-admin-bridge\Send-GrokIntentToCodexA.ps1"
)
$present = @($forbidden | Where-Object { Test-Path -LiteralPath (Join-Path $repoRoot $_) })
$ok = (
    [string]$config.canonical_route.shape -eq "A/B dual-leg selected by task fit or existing route receipt" -and
    [string]$config.canonical_route.selection -eq "selected_by_task_fit_or_existing_route_receipt" -and
    [string]$config.canonical_route.leg_a.transport_id -eq "direct-grok-worker-pool" -and
    [string]$config.canonical_route.leg_b.transport_id -eq "temporal-docker-langgraph" -and
    [bool]$config.canonical_route.continuity.existing_route_receipt_precedence -and
    -not [bool]$config.canonical_route.continuity.continuous_or_resume_switches_leg -and
    [string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit" -and
    @($config.model_worker_routing.available_workers) -contains "codex_agents" -and
    [string]$config.model_worker_routing.width_policy -eq "dynamic_ready_frontier_quota_latency_evidence" -and
    [string]$config.bounded_worker_pool.route_role -eq "normal_leg_a" -and
    -not [bool]$config.bounded_worker_pool.is_unconditional_default -and
    [bool]$config.prohibited_surfaces.visible_terminal -and
    [bool]$config.prohibited_surfaces.resident_loop -and
    $present.Count -eq 0
)
$result = [ordered]@{
    schema_version = "xinao.grok_l0_bootstrap_gate.v3"
    ok = [bool]$ok
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
    forbidden_paths_present = $present
    side_effects = "none_read_only"
}
if ($Quiet) {
    $result | ConvertTo-Json -Depth 4 -Compress
} else {
    $result | ConvertTo-Json -Depth 4
}
if (-not $ok) { exit 1 }
