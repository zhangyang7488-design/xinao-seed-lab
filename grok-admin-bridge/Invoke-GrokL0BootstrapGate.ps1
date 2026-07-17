#Requires -Version 5.1
<#
.SYNOPSIS
  Read-only L0 contract gate for the Grok 4.5 endpoint island.
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
    "grok-admin-bridge\Send-GrokIntentToCodexA.ps1",
    "grok-admin-bridge\Invoke-GrokComposer25Worker.ps1",
    "grok-admin-bridge\Invoke-GrokWorkerPool.ps1",
    "grok-admin-bridge\Invoke-CodexDispatchGrokWorkerPool.ps1",
    "grok-admin-bridge\Invoke-GrokHostWorkerPoolFromTemporal.ps1",
    "grok-admin-bridge\Invoke-GrokTemporalHostPoolTrigger.ps1"
)
$present = @($forbidden | Where-Object { Test-Path -LiteralPath (Join-Path $repoRoot $_) })
$workers = @($config.model_worker_routing.available_workers)
$ok = (
    [string]$config.canonical_route.shape -eq "Temporal + Docker houtai-gongren + worker-internal LangGraph" -and
    [string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit" -and
    [string]$config.model_worker_routing.width_policy -eq "dynamic_ready_frontier_quota_latency_evidence" -and
    $workers -contains "grok" -and
    $workers -contains "codex_agents" -and
    $workers -contains "combined" -and
    [string]$config.grok_endpoint_identity.model -eq "grok-4.5" -and
    -not [bool]$config.bounded_worker_pool.is_default_durable_route -and
    -not [bool]$config.bounded_worker_pool.local_duplicate_implementation -and
    [bool]$config.prohibited_surfaces.visible_terminal -and
    [bool]$config.prohibited_surfaces.resident_loop -and
    $present.Count -eq 0
)
$result = [ordered]@{
    schema_version = "xinao.grok_l0_bootstrap_gate.v3"
    ok = [bool]$ok
    canonical_route = [string]$config.canonical_route.shape
    worker_selection = [string]$config.model_worker_routing.selection
    available_workers = $workers
    endpoint_model = [string]$config.grok_endpoint_identity.model
    canonical_bounded_worker_pool = [string]$config.bounded_worker_pool.owner_bridge
    forbidden_paths_present = $present
    side_effects = "none_read_only"
}
if ($Quiet) {
    $result | ConvertTo-Json -Depth 4 -Compress
} else {
    $result | ConvertTo-Json -Depth 4
}
if (-not $ok) { exit 1 }
