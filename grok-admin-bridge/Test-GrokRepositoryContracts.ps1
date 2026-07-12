#Requires -Version 5.1
<#
.SYNOPSIS
  Fail-closed repository contract test for the thin Grok endpoint/config surface.
#>
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "GROK_REPOSITORY_CONTRACT_FAILED: $Name" }
}

function Read-Json([string]$RelativePath) {
    $path = Join-Path $repoRoot $RelativePath
    Assert-Contract (Test-Path -LiteralPath $path -PathType Leaf) ("missing:" + $RelativePath)
    Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$config = Read-Json "grok-admin-bridge/bridge.config.json"
$index = Read-Json "grok-admin-bridge/grok_operational_tools_index.v1.json"
$pointer = Read-Json "grok-admin-bridge/grok_admin_bridge_canonical_pointer.v1.json"

Assert-Contract ([string]$config.canonical_route.shape -eq "Temporal + Docker houtai-gongren + worker-internal LangGraph") "canonical_route"
Assert-Contract ([string]$config.default_model_worker.provider -eq "grok") "grok_only_provider"
Assert-Contract ([string]$config.default_model_worker.model -eq "grok-4.5") "grok_4_5_default"
Assert-Contract ([string]$config.default_model_worker.width_policy -eq "dynamic_ready_frontier_quota_latency_evidence") "dynamic_width"
Assert-Contract (-not [bool]$config.default_model_worker.non_grok_allowed) "non_grok_default_forbidden"
Assert-Contract (-not [bool]$config.explicit_worker_pool_fallback.enabled_default) "worker_pool_not_default"
Assert-Contract ([bool]$config.prohibited_surfaces.second_orchestrator) "second_orchestrator_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.visible_terminal) "visible_terminal_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.visible_injection) "visible_injection_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.scheduler) "scheduler_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.watchdog) "watchdog_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.keepalive) "keepalive_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.resident_loop) "resident_loop_prohibited"
Assert-Contract ([string]$index.status -eq "active_thin_surface") "thin_operational_index"
Assert-Contract ([string]$pointer.mirror_relationship -eq "none") "no_stale_mirror_identity"

$forbiddenPaths = @(
    ".grok/skills/gap-driven-progressor",
    ".grok/skills/codex-s-direct-worker-lane",
    ".grok/skills/task-entry",
    "grok-admin-bridge/Invoke-GrokLongWorkflowBootstrap.ps1",
    "grok-admin-bridge/Invoke-GrokLongWorkflowKeepalivePoll.ps1",
    "grok-admin-bridge/Invoke-GrokLongWorkflowRunNext.ps1",
    "grok-admin-bridge/Invoke-GrokFrontendPerpetualDrive.ps1",
    "grok-admin-bridge/Invoke-GrokPerpetualSeedLabDaemon.ps1",
    "grok-admin-bridge/Invoke-GrokWaveCycleRun.ps1",
    "grok-admin-bridge/Invoke-GrokSubagentPoolOrchestrator.ps1",
    "grok-admin-bridge/Invoke-GrokOrchestratorPulse.ps1",
    "grok-admin-bridge/Invoke-GrokSelfRotateLoop.ps1",
    "grok-admin-bridge/Invoke-GrokLoopGuardian.ps1",
    "grok-admin-bridge/Invoke-GrokGapDrivenProgressor.ps1",
    "grok-admin-bridge/Invoke-GrokManagedVisibleInject.ps1",
    "grok-admin-bridge/Send-GrokIntentToCodexA.ps1",
    "grok-admin-bridge/Invoke-GrokParallelGlobalAudit.ps1",
    "grok-admin-bridge/parallel_global_audit_auditors.json",
    "grok-admin-bridge/Invoke-GrokCodexSDirectWorkerLane.ps1",
    "grok-admin-bridge/grok_deepseek_v4_pro_review_node.v1.json",
    "grok-admin-bridge/grok_default_plus_dynamic_escalate_policy.v1.json",
    "grok-admin-bridge/grok_worker_pool_refill.v1.json",
    "grok-admin-bridge/Invoke-GrokWorkerPoolOrchestrator.ps1"
)
foreach ($relative in $forbiddenPaths) {
    Assert-Contract (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relative))) ("forbidden_path:" + $relative)
}
Assert-Contract (@(Get-ChildItem -LiteralPath (Join-Path $repoRoot "grok-admin-bridge") -Filter "Invoke-Handoff-*.ps1" -File -ErrorAction SilentlyContinue).Count -eq 0) "handoff_scripts_absent"
Assert-Contract (@(Get-ChildItem -LiteralPath (Join-Path $repoRoot "grok-admin-bridge") -Filter "run_grok_*worker.py" -File -ErrorAction SilentlyContinue).Count -eq 0) "non_grok_audit_workers_absent"

$checkpointText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokSessionContextCheckpoint.ps1") -Raw
Assert-Contract ($checkpointText -notmatch "SubagentPool|refill_required|Invoke-GrokWorkerPool|Start-Process|while\s*\(") "checkpoint_has_no_control_plane"
Assert-Contract ($checkpointText -match 'dispatch = \$false') "checkpoint_declares_no_dispatch"
Assert-Contract ($checkpointText -match 'visible_terminal = \$false') "checkpoint_declares_no_visible_terminal"

$overlayText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/config.toml") -Raw
Assert-Contract ($overlayText -notmatch 'profile\s*=\s*"off"') "sandbox_off_override_absent"
Assert-Contract ($overlayText -notmatch 'auto_allow_bash\s*=\s*true') "auto_allow_bash_absent"
Assert-Contract ($overlayText -notmatch '\[toolset[.]bash\]') "bash_toolset_override_absent"
Assert-Contract ($overlayText -notmatch 'permission_mode\s*=\s*"always-approve"') "always_approve_absent"

$poolFiles = @(
    "grok-admin-bridge/Invoke-GrokWorkerPool.ps1",
    "grok-admin-bridge/Invoke-GrokComposer25Worker.ps1",
    "grok-admin-bridge/Invoke-CodexDispatchGrokWorkerPool.ps1",
    "grok-admin-bridge/Invoke-GrokHostWorkerPoolFromTemporal.ps1",
    "grok-admin-bridge/Invoke-GrokTemporalHostPoolTrigger.ps1"
)
foreach ($relative in $poolFiles) {
    Assert-Contract (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) ("fallback_missing:" + $relative)
}
$poolContract = Read-Json "grok-admin-bridge/grok_codex_grok_worker_pool_hot_path.v1.json"
Assert-Contract (-not [bool]$poolContract.is_default_hot_path) "pool_contract_not_default"
Assert-Contract ([string]$poolContract.activation -match "explicit") "pool_contract_explicit"

$isGrok45 = $repoRoot -match 'workspace-grok-4[.]5-island'
if ($isGrok45) {
    foreach ($relative in @(
        "grok-admin-bridge/Invoke-GrokAcpxTerminalCapabilityEnforce.ps1",
        "grok-admin-bridge/Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1",
        "grok-admin-bridge/Invoke-GrokEngineeringIntentDecode.ps1",
        "grok-admin-bridge/grok_shell_capability_aliases.v1.json"
    )) {
        Assert-Contract (Test-Path -LiteralPath (Join-Path $repoRoot $relative) -PathType Leaf) ("endpoint_canary_missing:" + $relative)
    }
    $aliases = Read-Json "grok-admin-bridge/grok_shell_capability_aliases.v1.json"
    Assert-Contract (@($aliases.tool_ids) -contains "run_terminal_cmd") "terminal_alias_cmd"
    Assert-Contract (@($aliases.tool_ids) -contains "run_terminal_command") "terminal_alias_command"
    $weldText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1") -Raw
    Assert-Contract ($weldText -match 'scheduler_tick_default = \$false') "weld_scheduler_false"
    Assert-Contract ($weldText -match 'worker_pool_default = \$false') "weld_pool_false"
    Assert-Contract ($weldText -notmatch "WorkerPoolOrchestrator|SchedulerTick") "weld_has_no_retired_entry"
}

[ordered]@{
    schema_version = "xinao.grok_repository_contract_check.v2"
    ok = $true
    canonical_route = [string]$config.canonical_route.shape
    only_default_model_worker = [string]$config.default_model_worker.provider
    default_model = [string]$config.default_model_worker.model
    dynamic_width_policy = [string]$config.default_model_worker.width_policy
    worker_pool_default = $false
    resident_control_plane_default = $false
    visible_terminal_default = $false
    endpoint_canaries_checked = [bool]$isGrok45
} | ConvertTo-Json -Depth 5
