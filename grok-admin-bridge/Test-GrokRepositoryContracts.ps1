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
Assert-Contract ([string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit") "dynamic_worker_selection"
Assert-Contract (@($config.model_worker_routing.available_workers) -contains "grok") "grok_available"
Assert-Contract (@($config.model_worker_routing.available_workers) -contains "codex_agents") "codex_agents_available"
Assert-Contract ([string]$config.model_worker_routing.soft_preference_when_close -eq "grok") "grok_soft_preference"
Assert-Contract ([string]$config.model_worker_routing.quota_role -eq "scheduling_telemetry_not_dispatch_gate") "quota_not_gate"
Assert-Contract (-not [bool]$config.model_worker_routing.empty_burn) "no_empty_burn"
Assert-Contract ([string]$config.model_worker_routing.width_policy -eq "dynamic_ready_frontier_quota_latency_evidence") "dynamic_width"
Assert-Contract ([string]$config.grok_lane.scope -eq "this_grok_endpoint_only_not_global_router") "lane_scope"
Assert-Contract ([string]$config.grok_lane.model -eq "grok-composer-2.5-fast") "composer_2_5_lane"
Assert-Contract ([string]$config.grok_lane.grok_home -eq "C:\Users\xx363\.grok-bg-workers") "composer_profile"
Assert-Contract (-not [bool]$config.bounded_worker_pool.is_default_durable_route) "worker_pool_not_default_durable_route"
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
    "grok-admin-bridge/grok_burn_token_reflect_close_discourse.v1.json",
    "grok-admin-bridge/Invoke-GrokWorkerPoolOrchestrator.ps1"
)
foreach ($relative in $forbiddenPaths) {
    Assert-Contract (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relative))) ("forbidden_path:" + $relative)
}
Assert-Contract (@(Get-ChildItem -LiteralPath (Join-Path $repoRoot "grok-admin-bridge") -Filter "Invoke-Handoff-*.ps1" -File -ErrorAction SilentlyContinue).Count -eq 0) "handoff_scripts_absent"
Assert-Contract (@(Get-ChildItem -LiteralPath (Join-Path $repoRoot "grok-admin-bridge") -Filter "run_grok_*worker.py" -File -ErrorAction SilentlyContinue).Count -eq 0) "retired_audit_worker_scripts_absent"

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
Assert-Contract ([string]$poolContract.activation -match "positive_net_benefit") "pool_contract_dynamic_benefit"
Assert-Contract ([string]$poolContract.execution_contract_version -eq "xinao.grok.shared_execution_contract.v1") "pool_execution_contract"

$workerText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokComposer25Worker.ps1") -Raw
$poolText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokWorkerPool.ps1") -Raw
$dispatchText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-CodexDispatchGrokWorkerPool.ps1") -Raw
$readmeText = Get-Content -LiteralPath (Join-Path $repoRoot "README.md") -Raw
$intentRuleText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/rules/36-grok-live-field-intent-decode.md") -Raw
Assert-Contract ($readmeText -notmatch 'Grok is the only default model worker') "readme_not_grok_only"
Assert-Contract ($readmeText -match 'selected by positive net benefit') "readme_dynamic_worker_selection"
Assert-Contract ($intentRuleText -notmatch 'grok_live_field_intent_decode[.]v1[.]json') "intent_rule_has_no_missing_external_first_contract"
Assert-Contract ($intentRuleText -match '状态/进度/对账/inventory.+本机现状') "intent_rule_local_state_first"
Assert-Contract ($workerText -notmatch '[.]grok-4[.]5-lane') "worker_has_no_stale_profile"
Assert-Contract ($poolText -notmatch '[.]grok-4[.]5-lane') "pool_has_no_stale_profile"
Assert-Contract ($dispatchText -notmatch 'explicit user|explicit_user') "dispatch_not_explicit_only"
Assert-Contract ($workerText -match 'effective_output_accepted') "worker_effective_output_gate"
Assert-Contract ($workerText -match 'max_turns_cli_applied') "worker_auto_turn_evidence"
Assert-Contract ($workerText.Contains('$MetaObj.validation = $validation')) "background_validation_nested"
Assert-Contract ($workerText.Contains('$meta.validation = $validation')) "sync_validation_nested"
Assert-Contract ($workerText.Contains('$meta.finished_at = (Get-Date).ToString("o")')) "sync_finished_at"
Assert-Contract ($workerText -match 'schema_version.+continue') "worker_schema_version_not_overwritten"
Assert-Contract ($workerText -match '\[int\]\$TimeoutSec') "worker_hard_timeout_parameter"
Assert-Contract ($workerText -match 'GROK_CLI_VERSION_TOO_OLD') "worker_cli_version_admission"
Assert-Contract ($workerText -match 'no-auto-update') "worker_pin_auto_update_disabled"
Assert-Contract ($workerText -match 'models_cache[.]json') "worker_authenticated_catalog_cache"
Assert-Contract ($workerText -match 'GROK_REQUESTED_MODEL_NOT_IN_AUTHENTICATED_CATALOG') "worker_server_catalog_admission"
Assert-Contract ($workerText -match 'model_tokens_consumed = \$false') "worker_preflight_zero_token_receipt"
Assert-Contract ($workerText -match 'server_model_ids') "worker_server_catalog_evidence"
Assert-Contract ($workerText -match 'Stop-ExactProcessTree') "worker_exact_process_tree_stop"
Assert-Contract ($workerText -match '\$meta[.]status = "running"') "worker_pending_pid_meta"
Assert-Contract ($poolText -match 'TimeoutSec = \$TimeoutSec') "pool_passes_worker_timeout"
Assert-Contract ($poolText -match 'outer_terminated_process_ids') "pool_timeout_fallback_stop"
Assert-Contract ($poolText -notmatch 'status -eq "ok" -or') "pool_has_no_exit_only_success"
Assert-Contract (Test-Path -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Test-GrokCliEffectiveOutput.ps1") -PathType Leaf) "effective_output_validator_present"

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
    worker_selection = [string]$config.model_worker_routing.selection
    available_workers = @($config.model_worker_routing.available_workers)
    soft_preference_when_close = [string]$config.model_worker_routing.soft_preference_when_close
    grok_lane_model = [string]$config.grok_lane.model
    dynamic_width_policy = [string]$config.model_worker_routing.width_policy
    worker_pool_default = $false
    resident_control_plane_default = $false
    visible_terminal_default = $false
    endpoint_canaries_checked = [bool]$isGrok45
} | ConvertTo-Json -Depth 5
