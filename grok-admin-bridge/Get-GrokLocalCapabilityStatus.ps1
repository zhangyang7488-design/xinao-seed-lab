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
    compose = [string]$config.canonical_route.shape
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
    if ($entry.Key -eq "compose") { continue }
    $files[$entry.Key] = [bool](Test-Path -LiteralPath ([string]$entry.Value) -PathType Leaf)
}
$ok = (
    [string]$config.canonical_route.shape -eq "Temporal + Docker houtai-gongren + worker-internal LangGraph" -and
    [string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit" -and
    @($config.model_worker_routing.available_workers) -contains "codex_agents" -and
    [string]$config.grok_lane.provider -eq "grok" -and
    [bool]$config.prohibited_surfaces.visible_terminal -and
    [bool]$config.prohibited_surfaces.resident_loop -and
    @($files.Values | Where-Object { -not $_ }).Count -eq 0
)

$result = [ordered]@{
    schema_version = "xinao.grok_local_capability_status.v2"
    ok = [bool]$ok
    repository_root = $repoRoot
    repository_role = [string]$config.repository_role
    canonical_route = [string]$config.canonical_route.shape
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
