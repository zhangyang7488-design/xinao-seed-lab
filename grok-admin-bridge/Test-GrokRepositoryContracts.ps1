#Requires -Version 5.1
<#
.SYNOPSIS
  Fail-closed repository contract test for the thin Grok 4.5 endpoint surface.
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
$intent = Read-Json "grok-admin-bridge/grok_live_field_intent_decode.v1.json"
$core = Read-Json "grok-admin-bridge/grok_island_core_index.v1.json"
$p0 = Read-Json "grok-admin-bridge/grok_p0_autonomous_background_base.v1.json"
$checkpointContract = Read-Json "grok-admin-bridge/grok_session_context_checkpoint.v1.json"
$governanceLoop = Read-Json "grok-admin-bridge/grok_mature_first_governance_loop.v1.json"
$brain = Read-Json "grok-admin-bridge/grok_brain_and_executor.v1.json"
$workers = @($config.model_worker_routing.available_workers)

Assert-Contract ([string]$config.canonical_route.shape -eq "Temporal + Docker houtai-gongren + worker-internal LangGraph") "canonical_route"
Assert-Contract ([string]$config.model_worker_routing.selection -eq "dynamic_positive_net_benefit") "dynamic_worker_selection"
Assert-Contract ($workers -contains "grok") "grok_worker_available"
Assert-Contract ($workers -contains "codex_agents") "codex_agents_available"
Assert-Contract ($workers -contains "combined") "combined_workers_available"
Assert-Contract ([string]$config.model_worker_routing.soft_preference_when_close -eq "grok") "grok_soft_preference"
Assert-Contract ([string]$config.model_worker_routing.quota_role -eq "scheduling_telemetry_not_dispatch_gate") "quota_not_gate"
Assert-Contract ([string]$config.grok_endpoint_identity.model -eq "grok-4.5") "grok_4_5_endpoint_identity"
Assert-Contract (-not [bool]$config.bounded_worker_pool.is_default_durable_route) "bounded_pool_not_durable_default"
Assert-Contract (-not [bool]$config.bounded_worker_pool.local_duplicate_implementation) "no_local_pool_implementation"
Assert-Contract ([string]$config.bounded_worker_pool.owner_repository -eq "D:\Grok_Admin_Isolated\workspace") "admin_owns_bounded_pool"
Assert-Contract ([bool]$config.prohibited_surfaces.second_orchestrator) "second_orchestrator_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.visible_terminal) "visible_terminal_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.visible_injection) "visible_injection_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.scheduler) "scheduler_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.watchdog) "watchdog_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.keepalive) "keepalive_prohibited"
Assert-Contract ([bool]$config.prohibited_surfaces.resident_loop) "resident_loop_prohibited"
Assert-Contract ([string]$index.status -eq "active_thin_surface") "thin_operational_index"
Assert-Contract ([string]$index.canonical_route.worker_selection -eq "dynamic_positive_net_benefit") "index_dynamic_workers"
Assert-Contract ([string]$pointer.mirror_relationship -eq "none") "no_stale_mirror_identity"
Assert-Contract (-not [bool]$pointer.local_worker_pool_implementation) "pointer_no_local_pool"
Assert-Contract ([string]$intent.schema_version -eq "xinao.grok_live_field_intent_decode.v2") "intent_decode_v2"
Assert-Contract ([bool]$intent.agent_posture_cn.external_search_is_dynamic) "external_search_dynamic"
Assert-Contract (@($intent.aci_three_beats_cn).Count -eq 3) "aci_three_beats"
Assert-Contract (@($p0.stop_conditions) -contains "user_stop") "p0_user_stop"
Assert-Contract (@($p0.stop_conditions) -contains "user_changes_continuous_mode") "p0_mode_change_stop"
Assert-Contract (@($p0.stop_conditions) -contains "whole_mainline_frontier_unavoidably_blocked_after_alternatives") "p0_global_frontier_stop"
Assert-Contract (@($p0.stop_conditions) -notcontains "whole_named_objective_verified") "p0_local_milestone_not_stop"
Assert-Contract ([string]$p0.model_worker_routing -eq "bridge.config.json#model_worker_routing") "p0_dynamic_worker_pointer"
Assert-Contract ([string]$checkpointContract.model_worker_routing -eq "bridge.config.json#model_worker_routing") "checkpoint_dynamic_worker_pointer"
Assert-Contract ([string]$checkpointContract.soft_preference_when_close -eq "grok") "checkpoint_grok_soft_preference"
Assert-Contract ([string]$governanceLoop.activation -match "current_external_facts_can_change") "governance_dynamic_activation"
Assert-Contract ([string]$governanceLoop.local_live_direct -match "do_not_require_external_search_or_adr") "governance_local_live_direct"
Assert-Contract ([string]$brain.execution_boundary.durable_multiwave_work -eq "canonical_route_only") "durable_multiwave_uses_canonical_route"
Assert-Contract ($null -eq $brain.execution_boundary.durable_or_parallel_work) "bounded_parallel_not_forced_to_canonical_route"

foreach ($name in @($core.tier0) + @($core.control_contracts) + @($core.endpoint_contracts)) {
    Assert-Contract (Test-Path -LiteralPath (Join-Path $PSScriptRoot ([string]$name)) -PathType Leaf) ("core_index_target_missing:" + $name)
}

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
    "grok-admin-bridge/Invoke-GrokWorkerPoolOrchestrator.ps1",
    "grok-admin-bridge/Invoke-GrokComposer25Worker.ps1",
    "grok-admin-bridge/Invoke-GrokWorkerPool.ps1",
    "grok-admin-bridge/Invoke-CodexDispatchGrokWorkerPool.ps1",
    "grok-admin-bridge/Invoke-GrokHostWorkerPoolFromTemporal.ps1",
    "grok-admin-bridge/Invoke-GrokTemporalHostPoolTrigger.ps1",
    "grok-admin-bridge/grok_codex_grok_worker_pool_hot_path.v1.json",
    "grok-admin-bridge/grok_temporal_host_grok_pool.v1.json",
    "grok-admin-bridge/grok_burn_token_reflect_close_discourse.v1.json",
    "grok-admin-bridge/docs/temporal_host_grok_pool_activity.md"
)
foreach ($relative in $forbiddenPaths) {
    Assert-Contract (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relative))) ("forbidden_path:" + $relative)
}
Assert-Contract (@(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "Invoke-Handoff-*.ps1" -File -ErrorAction SilentlyContinue).Count -eq 0) "handoff_scripts_absent"
Assert-Contract (@(Get-ChildItem -LiteralPath $PSScriptRoot -Filter "run_grok_*worker.py" -File -ErrorAction SilentlyContinue).Count -eq 0) "legacy_audit_workers_absent"

foreach ($canonicalPath in @(
    [string]$config.bounded_worker_pool.dispatch_script,
    [string]$config.bounded_worker_pool.pool_script,
    [string]$config.bounded_worker_pool.worker_script,
    [string]$config.bounded_worker_pool.effective_output_test
)) {
    Assert-Contract (Test-Path -LiteralPath $canonicalPath -PathType Leaf) ("canonical_admin_surface_missing:" + $canonicalPath)
}

$checkpointText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Invoke-GrokSessionContextCheckpoint.ps1") -Raw
Assert-Contract ($checkpointText -notmatch "SubagentPool|refill_required|Invoke-GrokWorkerPool|Start-Process|while\s*\(") "checkpoint_has_no_control_plane"
Assert-Contract ($checkpointText -match 'dispatch = \$false') "checkpoint_declares_no_dispatch"
Assert-Contract ($checkpointText -match 'visible_terminal = \$false') "checkpoint_declares_no_visible_terminal"
Assert-Contract ($checkpointText -match 'worker_selection = "dynamic_positive_net_benefit"') "checkpoint_dynamic_workers"
Assert-Contract ($checkpointText -match 'available_workers = @\("grok", "codex_agents", "combined"\)') "checkpoint_all_workers_available"
Assert-Contract ($checkpointText -notmatch 'default_model_worker') "checkpoint_no_fixed_default_worker"

$governanceSkillText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/skills/mature-first-governance/SKILL.md") -Raw
$governanceGateText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Invoke-GrokMatureFirstGovernanceGate.ps1") -Raw
Assert-Contract ($governanceSkillText -notmatch 'Use on EVERY|治理环（必须按序）|Desktop\\Grok_Admin_Isolated') "governance_not_universal_template"
Assert-Contract ($governanceSkillText -match '本地事实盘点、状态读取、已确定路线内的普通可回滚动作') "governance_local_direct_path"
Assert-Contract ($governanceGateText -match 'Class -eq "research_external"') "governance_external_is_conditional"
Assert-Contract ($governanceGateText -notmatch '\$required = @\("0_classify", "1_external_first", "3_choose_carrier", "4_plan_artifact"\)') "governance_no_universal_external_adr_gate"
Assert-Contract ($governanceGateText -notmatch '平台/运维/焊路事务开头运行') "governance_read_hint_not_universal"

$adaptiveRuleText = @(
    ".grok/rules/22-grok-rollback-domain-max-auth.md",
    ".grok/rules/23-grok-brain-and-executor.md",
    ".grok/rules/26-grok-mature-first-isomorphic-execution.md",
    ".grok/rules/36-grok-live-field-intent-decode.md",
    ".grok/rules-on-demand/warm/27-grok-p0-autonomous-background-base.md",
    ".grok/rules-on-demand/warm/28-grok-mature-first-governance-loop.md"
) | ForEach-Object { Get-Content -LiteralPath (Join-Path $repoRoot $_) -Raw } | Out-String
Assert-Contract ($adaptiveRuleText -notmatch 'Grok 是唯一默认模型工人|Grok heavy / 4[.]5.+唯一默认模型工人|非 Grok 模型.+默认冻结|只有用户显式点名才可调用|任何事务默认走治理环|0–4.+落盘后方可|未规划就改 ps1/compose|先短外搜成熟') "active_rules_no_rigid_worker_or_external_template"
Assert-Contract ($adaptiveRuleText -match '局部.+continuous.+主线全局') "active_rules_preserve_continuous_parent"

$legacyRootLiteral = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination'
foreach ($relative in @(
    ".grok/hooks/session-start-amq-inbox.json",
    "grok-admin-bridge/grok_runtime_roots.v1.json",
    "grok-admin-bridge/grok_shell_capability_aliases.v1.json",
    "grok-admin-bridge/Invoke-XinaoCoord.ps1",
    "grok-admin-bridge/Invoke-GrokAcpxTerminalCapabilityEnforce.ps1",
    "grok-admin-bridge/Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1"
)) {
    $legacyText = Get-Content -LiteralPath (Join-Path $repoRoot $relative) -Raw
    $normalizedLegacyText = $legacyText.Replace('\\', '\')
    Assert-Contract (-not $normalizedLegacyText.Contains($legacyRootLiteral)) ("legacy_coordination_root_absent:" + $relative)
}

$overlayText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/config.toml") -Raw
Assert-Contract ($overlayText -notmatch 'grok-composer-2[.]5-fast') "endpoint_overlay_has_no_fake_composer_alias"
Assert-Contract ($overlayText -notmatch 'profile\s*=\s*"off"') "sandbox_off_override_absent"
Assert-Contract ($overlayText -notmatch 'auto_allow_bash\s*=\s*true') "auto_allow_bash_absent"

$policyFiles = @(
    "README.md",
    "AGENTS.md",
    ".grok/rules/00-grok-l0-bootstrap.md",
    ".grok/rules/23-grok-brain-and-executor.md",
    "grok-admin-bridge/GROK_L0_BOOTSTRAP.md",
    "grok-admin-bridge/grok_brain_and_executor.v1.json",
    "grok-admin-bridge/grok_user_standing_relationship.v1.json",
    "grok-admin-bridge/grok_preference_to_engineering_delta.v1.json",
    "grok-admin-bridge/grok_333_one_mature_system_mainline_grok_sideline.v1.json"
)
$policyText = ($policyFiles | ForEach-Object {
    Get-Content -LiteralPath (Join-Path $repoRoot $_) -Raw
}) -join "`n"
Assert-Contract ($policyText -notmatch 'Grok is the only default|only_default_model_worker|non_grok_allowed|explicit_user_batch|only when named by user|非 Grok 工人仅用户显式|默认工人 \*\*Grok\*\*') "stale_rigid_worker_policy_absent"
Assert-Contract ((Get-Content -LiteralPath (Join-Path $repoRoot "AGENTS.md") -Raw) -notmatch 'Install-GrokAdminBridge') "ghost_install_reference_absent"

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
$weldText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Invoke-GrokAcpSchedulerHiddenStdioWeld.ps1") -Raw
Assert-Contract ($weldText -match 'worker_selection = "dynamic_positive_net_benefit"') "weld_dynamic_workers"
Assert-Contract ($weldText -notmatch 'only_default_model_worker') "weld_no_grok_only_default"
Assert-Contract ($weldText -match 'scheduler_tick_default = \$false') "weld_scheduler_false"
Assert-Contract ($weldText -match 'worker_pool_default = \$false') "weld_pool_false"
Assert-Contract ($weldText -notmatch "WorkerPoolOrchestrator|SchedulerTick") "weld_has_no_retired_entry"

[ordered]@{
    schema_version = "xinao.grok_repository_contract_check.v3"
    ok = $true
    canonical_route = [string]$config.canonical_route.shape
    worker_selection = [string]$config.model_worker_routing.selection
    available_workers = $workers
    soft_preference_when_close = [string]$config.model_worker_routing.soft_preference_when_close
    endpoint_model = [string]$config.grok_endpoint_identity.model
    local_worker_pool_implementation = $false
    canonical_bounded_worker_pool = [string]$config.bounded_worker_pool.owner_bridge
    resident_control_plane_default = $false
    visible_terminal_default = $false
    endpoint_canaries_checked = $true
} | ConvertTo-Json -Depth 5
