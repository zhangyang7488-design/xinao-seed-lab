#Requires -Version 5.1
<#
.SYNOPSIS
  Read-only Grok 4.5 endpoint capability probe.
.DESCRIPTION
  Reads local files only. It does not dispatch workers, invoke models, start
  services, inspect interactive sessions, or mutate runtime state.
#>
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "bridge.config.json"),
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$repoRoot = Split-Path -Parent $PSScriptRoot
$checkpoint = "D:\XINAO_RESEARCH_RUNTIME\state\grok_4_5\session_context\latest.json"

$localDuplicateRelatives = @(
    "grok-admin-bridge\Invoke-GrokComposer25Worker.ps1",
    "grok-admin-bridge\Invoke-GrokWorkerPool.ps1",
    "grok-admin-bridge\Invoke-CodexDispatchGrokWorkerPool.ps1",
    "grok-admin-bridge\Invoke-GrokHostWorkerPoolFromTemporal.ps1",
    "grok-admin-bridge\Invoke-GrokTemporalHostPoolTrigger.ps1",
    "grok-admin-bridge\grok_codex_grok_worker_pool_hot_path.v1.json",
    "grok-admin-bridge\grok_temporal_host_grok_pool.v1.json"
)
$localDuplicates = @($localDuplicateRelatives | Where-Object {
    Test-Path -LiteralPath (Join-Path $repoRoot $_)
})

$required = [ordered]@{
    bridge_config = $ConfigPath
    compose_file = [string]$config.grok_codex_s_native_temporal_route.compose
    checkpoint_script = (Join-Path $PSScriptRoot "Invoke-GrokSessionContextCheckpoint.ps1")
    contract_test = (Join-Path $PSScriptRoot "Test-GrokRepositoryContracts.ps1")
    shell_capability = (Join-Path $PSScriptRoot "Invoke-GrokAcpxTerminalCapabilityEnforce.ps1")
    hidden_stdio = (Join-Path $PSScriptRoot "Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1")
    intent_decode = (Join-Path $PSScriptRoot "Invoke-GrokEngineeringIntentDecode.ps1")
    canonical_admin_dispatch = [string]$config.bounded_worker_pool.dispatch_script
    canonical_admin_pool = [string]$config.bounded_worker_pool.pool_script
    canonical_admin_worker = [string]$config.bounded_worker_pool.worker_script
    canonical_admin_effective_output_test = [string]$config.bounded_worker_pool.effective_output_test
}

$files = [ordered]@{}
foreach ($entry in $required.GetEnumerator()) {
    $files[$entry.Key] = [bool](Test-Path -LiteralPath ([string]$entry.Value) -PathType Leaf)
}
$workers = @($config.model_worker_routing.available_workers)
$ok = (
    [string]$config.canonical_route.shape -eq "Temporal + Docker houtai-gongren + worker-internal LangGraph" -and
    [string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit" -and
    $workers -contains "grok" -and
    $workers -contains "codex_agents" -and
    $workers -contains "combined" -and
    [string]$config.grok_endpoint_identity.model -eq "grok-4.5" -and
    -not [bool]$config.bounded_worker_pool.local_duplicate_implementation -and
    [bool]$config.prohibited_surfaces.visible_terminal -and
    [bool]$config.prohibited_surfaces.resident_loop -and
    $localDuplicates.Count -eq 0 -and
    @($files.Values | Where-Object { -not $_ }).Count -eq 0
)

$result = [ordered]@{
    schema_version = "xinao.grok_local_capability_status.v3"
    ok = [bool]$ok
    repository_root = $repoRoot
    repository_role = [string]$config.repository_role
    canonical_route = [string]$config.canonical_route.shape
    worker_selection = [string]$config.model_worker_routing.selection
    available_workers = $workers
    soft_preference_when_close = [string]$config.model_worker_routing.soft_preference_when_close
    endpoint_model = [string]$config.grok_endpoint_identity.model
    checkpoint_exists = [bool](Test-Path -LiteralPath $checkpoint -PathType Leaf)
    local_worker_pool_duplicates = $localDuplicates
    files = $files
    side_effects = "none_read_only"
}
if ($Quiet) {
    $result | ConvertTo-Json -Depth 6 -Compress
} else {
    $result | ConvertTo-Json -Depth 6
}
if (-not $ok) { exit 1 }
