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
$core = Read-Json "grok-admin-bridge/grok_island_core_index.v1.json"
$p0 = Read-Json "grok-admin-bridge/grok_p0_autonomous_background_base.v1.json"
$checkpointContract = Read-Json "grok-admin-bridge/grok_session_context_checkpoint.v1.json"
$governanceLoop = Read-Json "grok-admin-bridge/grok_mature_first_governance_loop.v1.json"
$runtimeRoots = Read-Json "grok-admin-bridge/grok_runtime_roots.v1.json"
$brain = Read-Json "grok-admin-bridge/grok_brain_and_executor.v1.json"

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
Assert-Contract (@($p0.stop_conditions) -contains "user_changes_continuous_mode") "p0_mode_change_stop"
Assert-Contract (@($p0.stop_conditions) -contains "whole_mainline_frontier_unavoidably_blocked_after_alternatives") "p0_global_frontier_stop"
Assert-Contract (@($p0.stop_conditions) -notcontains "whole_named_objective_verified") "p0_local_milestone_not_stop"
Assert-Contract ([string]$p0.model_worker_routing -eq "bridge.config.json#model_worker_routing") "p0_dynamic_worker_pointer"
Assert-Contract ([string]$checkpointContract.model_worker_routing -eq "bridge.config.json#model_worker_routing") "checkpoint_dynamic_worker_pointer"
Assert-Contract ([string]$governanceLoop.activation -match "current_external_facts_can_change") "governance_dynamic_activation"
Assert-Contract ([string]$governanceLoop.local_live_direct -match "do_not_require_external_search_or_adr") "governance_local_live_direct"
Assert-Contract ([string]$runtimeRoots.coordination -eq "E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination") "coordination_root_migrated"
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
Assert-Contract ($checkpointText -match 'worker_selection = "dynamic_positive_net_benefit"') "checkpoint_dynamic_workers"
Assert-Contract ($checkpointText -notmatch 'default_model_worker') "checkpoint_no_fixed_default_worker"

$governanceSkillText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/skills/mature-first-governance/SKILL.md") -Raw
$governanceGateText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokMatureFirstGovernanceGate.ps1") -Raw
Assert-Contract ($governanceSkillText -notmatch 'Use on EVERY|治理环（必须按序）|Desktop\\Grok_Admin_Isolated') "governance_not_universal_template"
Assert-Contract ($governanceSkillText -match '本地事实盘点、状态读取、已确定路线内的普通可回滚动作') "governance_local_direct_path"
Assert-Contract ($governanceGateText -match 'Class -eq "research_external"') "governance_external_is_conditional"
Assert-Contract ($governanceGateText -notmatch '\$required = @\("0_classify", "1_external_first", "3_choose_carrier", "4_plan_artifact"\)') "governance_no_universal_external_adr_gate"
Assert-Contract ($governanceGateText -notmatch '平台/运维/焊路事务开头运行') "governance_read_hint_not_universal"

$adaptiveRuleText = @(
    ".grok/rules/22-grok-rollback-domain-max-auth.md",
    ".grok/rules/23-grok-brain-and-executor.md",
    ".grok/rules/26-grok-mature-first-isomorphic-execution.md",
    ".grok/rules/29-grok-admin-isolated-window-boundary.md",
    ".grok/rules/36-grok-live-field-intent-decode.md",
    ".grok/rules-on-demand/warm/27-grok-p0-autonomous-background-base.md",
    ".grok/rules-on-demand/warm/28-grok-mature-first-governance-loop.md"
) | ForEach-Object { Get-Content -LiteralPath (Join-Path $repoRoot $_) -Raw } | Out-String
Assert-Contract ($adaptiveRuleText -notmatch 'Grok 是唯一默认模型工人|Grok heavy / 4[.]5.+唯一默认模型工人|非 Grok 模型.+默认冻结|只有用户显式点名才可调用|任何事务默认走治理环|0–4.+落盘后方可|未规划就改 ps1/compose|先短外搜成熟') "active_rules_no_rigid_worker_or_external_template"
Assert-Contract ($adaptiveRuleText -match '局部.+continuous.+主线全局') "active_rules_preserve_continuous_parent"

$overlayText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/config.toml") -Raw
Assert-Contract ($overlayText -notmatch 'profile\s*=\s*"off"') "sandbox_off_override_absent"
Assert-Contract ($overlayText -notmatch 'auto_allow_bash\s*=\s*true') "auto_allow_bash_absent"
Assert-Contract ($overlayText -notmatch '\[toolset[.]bash\]') "bash_toolset_override_absent"
Assert-Contract ($overlayText -notmatch 'permission_mode\s*=\s*"always-approve"') "always_approve_absent"

$poolFiles = @(
    "grok-admin-bridge/GrokAuthenticatedCatalogTime.ps1",
    "grok-admin-bridge/GrokWorkerProcessRuntime.ps1",
    "grok-admin-bridge/GrokWorkerSelectionReceipt.ps1",
    "grok-admin-bridge/Invoke-GrokWorkerPool.ps1",
    "grok-admin-bridge/Invoke-GrokComposer25Worker.ps1",
    "grok-admin-bridge/Invoke-CodexDispatchGrokWorkerPool.ps1",
    "grok-admin-bridge/Invoke-GrokHostWorkerPoolFromTemporal.ps1",
    "grok-admin-bridge/Invoke-GrokTemporalHostPoolTrigger.ps1",
    "grok-admin-bridge/Test-GrokAuthenticatedCatalogTime.ps1",
    "grok-admin-bridge/Test-GrokWorkerProcessRuntime.ps1",
    "grok-admin-bridge/Test-GrokWorkerSelectionReceiptContract.ps1"
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
$hostTriggerText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokHostWorkerPoolFromTemporal.ps1") -Raw
$hostAliasText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Invoke-GrokTemporalHostPoolTrigger.ps1") -Raw
$effectiveValidatorText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Test-GrokCliEffectiveOutput.ps1") -Raw
$processRuntimeText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/GrokWorkerProcessRuntime.ps1") -Raw
$catalogTimeText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/GrokAuthenticatedCatalogTime.ps1") -Raw
$selectionReceiptText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/GrokWorkerSelectionReceipt.ps1") -Raw
$selectionResolverText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/resolve_grok_worker_selection_receipt.py") -Raw
$pathIdentityText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/GrokWindowsPathIdentity.ps1") -Raw
$poolAccountingText = Get-Content -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/GrokWorkerPoolAccounting.ps1") -Raw
$codexLauncherPath = "C:\Users\xx363\CodexLaunchers\Invoke-Codex-GrokWorkerPool.ps1"
Assert-Contract (Test-Path -LiteralPath $codexLauncherPath -PathType Leaf) "codex_worker_pool_launcher_present"
$codexLauncherText = Get-Content -LiteralPath $codexLauncherPath -Raw
$readmeText = Get-Content -LiteralPath (Join-Path $repoRoot "README.md") -Raw
$intentRuleText = Get-Content -LiteralPath (Join-Path $repoRoot ".grok/rules/36-grok-live-field-intent-decode.md") -Raw
Assert-Contract ($readmeText -notmatch 'Grok is the only default model worker') "readme_not_grok_only"
Assert-Contract ($readmeText -match 'selected by positive net benefit') "readme_dynamic_worker_selection"
Assert-Contract ($intentRuleText -notmatch 'grok_live_field_intent_decode[.]v1[.]json') "intent_rule_has_no_missing_external_first_contract"
Assert-Contract ($intentRuleText -match '状态/进度/对账/inventory.+本机现状') "intent_rule_local_state_first"
Assert-Contract ($workerText -notmatch '[.]grok-4[.]5-lane') "worker_has_no_stale_profile"
Assert-Contract ($workerText -notmatch 'GROK_COMPOSER25_EXACT_MODEL_REQUIRED') "worker_has_no_static_composer_only_gate"
Assert-Contract ($workerText -match '\$cliModelIds -notcontains \$Model') "worker_exact_profile_models_admission"
Assert-Contract ($workerText -match '\$cliModelIds -contains \$Model\s+-and \$serverModelIds -contains \$Model') "worker_exact_provider_catalog_intersection"
Assert-Contract ($workerText.Contains('$argsList.Add($Model)')) "worker_passes_requested_model_exactly"
Assert-Contract ($workerText -match 'GrokHome\s*=\s*\$GrokHome') "worker_binds_session_evidence_home"
Assert-Contract ($workerText -match 'ExpectedCwd\s*=\s*\$Cwd') "worker_binds_session_evidence_cwd"
Assert-Contract ($effectiveValidatorText -match 'exact_session_model_plus_explicit_backend_usage_binding') "effective_output_dual_identity_binding"
Assert-Contract ($effectiveValidatorText -match 'Test-OrdinalEquals \$RequestedModel "grok-4[.]5"') "effective_output_public_model_binding_exact"
Assert-Contract ($effectiveValidatorText -match '\$allowedBackendModels \+= "grok-4[.]5-build"') "effective_output_backend_variant_binding_explicit"
Assert-Contract ($effectiveValidatorText -notmatch 'EndsWith\(.+build|TrimEnd\(.+build|replace.+build') "effective_output_has_no_suffix_normalization"
Assert-Contract ($pathIdentityText -match 'GetFileInformationByHandle') "path_identity_uses_windows_file_identity"
Assert-Contract ($pathIdentityText -match 'GetFinalPathNameByHandleW') "path_identity_records_final_path"
Assert-Contract ($pathIdentityText -match 'PATH_IDENTITY_JUNCTION_RETARGET') "path_identity_has_retarget_guard"
Assert-Contract ($effectiveValidatorText -match 'Test-GrokDirectoryObjectIdentityEqual') "effective_output_cwd_uses_object_identity"
Assert-Contract ($effectiveValidatorText -notmatch 'sessionCwdBindingOk\s*=\s*Test-OrdinalIgnoreCaseEquals') "effective_output_cwd_has_no_string_equality"
Assert-Contract ($dispatchText -match 'Test-GrokDirectoryObjectIdentityEqual') "dispatch_pool_cwd_uses_object_identity"
Assert-Contract ($dispatchText -notmatch 'GetFullPath\(\[string\]\$poolSummary[.]cwd\)\s+-ne') "dispatch_pool_cwd_has_no_string_equality"
Assert-Contract ($dispatchText -match '(?s)\$dispatchCwdLease\s*=\s*Open-GrokDirectoryIdentityLease.+?try\s*\{.+?finally\s*\{\s*Close-GrokDirectoryIdentityLease\s+-Lease\s+\$dispatchCwdLease') "dispatch_cwd_identity_lease_closed_in_finally"
Assert-Contract ($poolText -notmatch '[.]grok-4[.]5-lane') "pool_has_no_stale_profile"
Assert-Contract ($dispatchText -notmatch 'explicit user|explicit_user') "dispatch_not_explicit_only"
foreach ($entry in ([ordered]@{
    codex_launcher = $codexLauncherText
    dispatch = $dispatchText
    pool = $poolText
    temporal_host = $hostTriggerText
    temporal_alias = $hostAliasText
}).GetEnumerator()) {
    Assert-Contract ($entry.Value -match '\[string\]\$SelectionPath') ("selection_path_parameter_missing:" + $entry.Key)
    Assert-Contract ($entry.Value -notmatch '\[string\]\$Model\s*=\s*"grok-composer-2[.]5-fast"') ("implicit_composer_default_present:" + $entry.Key)
    Assert-Contract ($entry.Value -notmatch 'if\s*\(-not\s+\$Cwd\)\s*\{\s*\$Cwd\s*=\s*\(Get-Location\)') ("implicit_get_location_cwd_present:" + $entry.Key)
}
Assert-Contract ($codexLauncherText -match 'SelectionPath\s*=\s*\$SelectionPath') "launcher_forwards_selection_path"
Assert-Contract ($dispatchText -match 'Read-GrokWorkerSelectionReceipt') "dispatch_validates_selection_receipt"
Assert-Contract ($dispatchText -match 'resolve_grok_worker_selection_receipt[.]py') "dispatch_generates_missing_selection_receipt"
Assert-Contract ($dispatchText -match 'state\\grok_worker_selection') "dispatch_selection_receipt_is_per_dispatch_state"
Assert-Contract ($dispatchText -notmatch 'grok_worker_selection\\latest[.]json') "dispatch_does_not_reuse_latest_selection"
Assert-Contract ($selectionResolverText -match 'resolve_supervisor_worker_decision') "selection_adapter_reuses_canonical_selector"
Assert-Contract ($selectionResolverText -notmatch 'select_supervisor_worker') "selection_adapter_does_not_reimplement_selector"
Assert-Contract ($dispatchText -match 'ExpectedSelectionDecisionSha256\s*=\s*\[string\]\$selection[.]decision_sha256') "dispatch_binds_decision_hash_to_pool"
Assert-Contract ($dispatchText -match 'CODEX_GROK_POOL_SELECTION_RECEIPT_MISMATCH') "dispatch_fanin_binds_selection_receipt"
Assert-Contract ($poolText -match 'Read-GrokWorkerSelectionReceipt') "pool_revalidates_selection_receipt"
Assert-Contract ($poolText -match 'GROK_WORKER_POOL_SELECTION_DECISION_CHANGED') "pool_rejects_decision_toctou"
Assert-Contract ($hostTriggerText -match 'ExpectedSelectionDecisionSha256\s*=\s*\[string\]\$selection[.]decision_sha256') "temporal_host_binds_decision_hash_to_dispatch"
Assert-Contract ($hostAliasText -match 'SelectionPath\s*=\s*\$SelectionPath') "temporal_alias_forwards_selection_path"
Assert-Contract ($selectionReceiptText -match 'xinao[.]supervisor_worker_decision_receipt[.]v1') "selection_receipt_schema_exact"
Assert-Contract ($selectionReceiptText -match 'ConvertTo-GrokCanonicalJson') "selection_receipt_canonical_hash_recomputed"
Assert-Contract ($selectionReceiptText -match 'GROK_SELECTION_DECISION_HASH_MISMATCH') "selection_receipt_hash_mismatch_rejected"
Assert-Contract ($selectionReceiptText -match 'grok_acpx_headless') "selection_receipt_provider_exact"
Assert-Contract ($selectionReceiptText -match 'grok[.]com[.]cached_profile') "selection_receipt_profile_exact"
Assert-Contract ($selectionReceiptText -match 'direct-grok-worker-pool') "selection_receipt_transport_exact"
Assert-Contract ($workerText -match 'effective_output_accepted') "worker_effective_output_gate"
Assert-Contract ($workerText -match 'max_turns_cli_applied') "worker_auto_turn_evidence"
Assert-Contract ($workerText.Contains('$meta.validation = $validation')) "sync_validation_nested"
Assert-Contract ($workerText -match 'xinao[.]grok_worker_background_invocation[.]v1') "background_hash_bound_invocation"
Assert-Contract ($workerText -match 'background[.]claim[.]json') "background_drain_claim"
Assert-Contract ($workerText -match 'independent_pwsh_process') "background_independent_process"
Assert-Contract ($workerText -notmatch 'BeginInvoke\(') "background_has_no_ephemeral_runspace"
Assert-Contract ($workerText -match 'RedirectStandardOutput\s*=\s*\$true') "background_drain_has_independent_stdout"
Assert-Contract ($workerText -match 'GROK_INTERNAL_EXECUTION_REQUIRES_HASH_BOUND_INVOCATION') "background_internal_identity_guarded"
Assert-Contract ($workerText -match 'GROK_BACKGROUND_DEADLINE_EXPIRED_BEFORE_MODEL_START') "background_deadline_rechecked_before_model"
Assert-Contract ($workerText -notmatch '\$psi[.]Arguments\s*=') "worker_has_no_manual_arguments_string"
Assert-Contract ($processRuntimeText -match 'ArgumentList[.]Add') "worker_uses_argument_list"
Assert-Contract ($processRuntimeText -match 'GROK_PROCESS_ARGUMENT_LIST_UNAVAILABLE') "worker_argument_list_fail_closed"
Assert-Contract ($workerText.Contains('$meta.finished_at = (Get-Date).ToString("o")')) "sync_finished_at"
Assert-Contract ($workerText -match 'schema_version.+continue') "worker_schema_version_not_overwritten"
Assert-Contract ($workerText -match '\[int\]\$TimeoutSec') "worker_hard_timeout_parameter"
Assert-Contract ($workerText -match 'GROK_CLI_VERSION_TOO_OLD') "worker_cli_version_admission"
Assert-Contract ($workerText -match 'no-auto-update') "worker_pin_auto_update_disabled"
Assert-Contract ($workerText -match 'models_cache[.]json') "worker_authenticated_catalog_cache"
Assert-Contract ($workerText -match 'ConvertTo-GrokCatalogFetchedAtUtc') "worker_uses_catalog_timestamp_compatibility_seam"
Assert-Contract ($catalogTimeText -match 'AssumeUniversal') "zone_less_catalog_timestamp_assumes_utc"
Assert-Contract ($catalogTimeText -match 'AdjustToUniversal') "catalog_timestamp_normalized_to_utc"
Assert-Contract ($catalogTimeText -match 'InvariantCulture') "catalog_timestamp_parse_is_culture_independent"
Assert-Contract ($workerText -match 'Test-GrokCatalogAgeWithinWindow') "worker_uses_executable_catalog_freshness_gate"
Assert-Contract ($catalogTimeText -match 'Test-GrokCatalogAgeWithinWindow') "catalog_freshness_gate_is_pure_shared_seam"
Assert-Contract ($catalogTimeText -match 'IsInfinity') "catalog_infinite_age_rejected"
Assert-Contract ($catalogTimeText -match 'IsNaN') "catalog_nan_age_rejected"
Assert-Contract ($workerText -match 'GROK_REQUESTED_MODEL_NOT_IN_AUTHENTICATED_CATALOG') "worker_rejects_custom_alias_model_drift_before_token_use"
Assert-Contract ($workerText -match 'model_tokens_consumed = \$false') "worker_preflight_zero_token_receipt"
Assert-Contract ($workerText -match 'server_model_ids') "worker_server_catalog_evidence"
Assert-Contract ($workerText -match 'cli_model_ids') "worker_effective_cli_catalog_evidence"
Assert-Contract ($workerText -match 'availability_authority = "exact_profile_cli_and_authenticated_server_catalog"') "worker_exact_provider_catalog_authority"
Assert-Contract ($workerText -match 'Stop-ExactProcessTree') "worker_exact_process_tree_stop"
Assert-Contract ($workerText -match '\$meta[.]status = "running"') "worker_pending_pid_meta"
Assert-Contract ($poolText -match 'TimeoutSec = \$TimeoutSec') "pool_passes_worker_timeout"
Assert-Contract ($poolText -match '\[string\]\$PoolId') "pool_accepts_exact_pool_id"
Assert-Contract ($dispatchText -match '\[string\]\$DispatchId') "dispatch_accepts_exact_dispatch_id"
Assert-Contract ($dispatchText -match 'PoolId\s*=\s*\$poolId') "dispatch_forwards_exact_pool_id"
Assert-Contract ($dispatchText -match 'pool_summary_path') "dispatch_records_exact_pool_summary"
Assert-Contract ($hostTriggerText -match 'TEMPORAL_HOST_EXACT_DISPATCH_RECEIPT') "host_requires_exact_dispatch_receipt"
Assert-Contract ($hostTriggerText -match 'TEMPORAL_HOST_EXACT_POOL_SUMMARY') "host_requires_exact_pool_summary"
Assert-Contract ($hostTriggerText -notmatch 'Get-Content\s+-LiteralPath\s+\$poolLatest') "host_does_not_accept_shared_pool_latest"
Assert-Contract ($codexLauncherText -match 'DispatchId\s*=\s*\$DispatchId') "launcher_forwards_exact_dispatch_id"
Assert-Contract ($codexLauncherText -match 'PoolId\s*=\s*\$PoolId') "launcher_forwards_exact_pool_id"
foreach ($entry in ([ordered]@{
    codex_launcher = $codexLauncherText
    dispatch = $dispatchText
    pool = $poolText
    temporal_host = $hostTriggerText
    temporal_alias = $hostAliasText
}).GetEnumerator()) {
    Assert-Contract ($entry.Value -match '\[string\]\$JsonSchemaPath') ("json_schema_parameter_missing:" + $entry.Key)
    Assert-Contract ($entry.Value -match 'JsonSchemaPath\s*=\s*\$JsonSchemaPath') ("json_schema_forwarding_missing:" + $entry.Key)
}
Assert-Contract ($workerText -match '\[string\]\$JsonSchemaPath') "worker_json_schema_parameter"
Assert-Contract ($workerText -match 'GROK_JSON_SCHEMA_MISSING') "worker_json_schema_missing_fail_closed"
Assert-Contract ($workerText -match 'GROK_JSON_SCHEMA_INVALID_UTF8') "worker_json_schema_utf8_fail_closed"
Assert-Contract ($workerText -match 'GROK_JSON_SCHEMA_INVALID_JSON') "worker_json_schema_json_fail_closed"
Assert-Contract ($workerText -match 'GROK_JSON_SCHEMA_TOP_LEVEL_NOT_OBJECT') "worker_json_schema_object_fail_closed"
Assert-Contract ($workerText.Contains('$argsList.Add("--json-schema")')) "worker_cli_json_schema_flag"
Assert-Contract ($workerText.Contains('$argsList.Add($jsonSchemaCompact)')) "worker_cli_json_schema_compact_payload"
Assert-Contract ($workerText -match 'json_schema_path\s*=\s*\$resolvedJsonSchemaPath') "worker_json_schema_path_evidence"
Assert-Contract ($workerText -match 'json_schema_sha256\s*=\s*\$jsonSchemaSha256') "worker_json_schema_hash_evidence"
Assert-Contract ($workerText -match 'json_schema_source_path') "worker_json_schema_source_evidence"
Assert-Contract ($workerText -match 'json_schema_snapshot_path') "worker_json_schema_snapshot_evidence"
Assert-Contract ($workerText -match 'FileMode\]::CreateNew') "worker_json_schema_snapshot_create_new"
Assert-Contract ($workerText -match 'RequireJsonObject\s*-or\s*-not \[string\]::IsNullOrWhiteSpace\(\$JsonSchemaPath\)') "worker_json_schema_keeps_local_validator"
Assert-Contract ($workerText -match 'Get-Command Test-Json') "worker_prefers_native_json_schema_validator"
Assert-Contract ($workerText -match 'python_jsonschema') "worker_has_winps_jsonschema_fallback"
Assert-Contract ($workerText -match 'GROK_JSON_SCHEMA_LOCAL_VALIDATOR_UNAVAILABLE') "worker_validator_admission_fail_closed"
Assert-Contract ($workerText -match 'GROK_JSON_SCHEMA_LOCAL_COMPILATION_FAILED') "worker_schema_compilation_fail_closed"
Assert-Contract ($workerText -match 'json_schema_validator\s*=\s*\$localJsonSchemaValidator') "worker_validator_identity_evidence"
Assert-Contract ($effectiveValidatorText -match '\[string\]\$JsonSchemaPath') "effective_validator_schema_parameter"
Assert-Contract ($effectiveValidatorText -match 'Test-Json\s+-Json\s+\$text\s+-Schema\s+\$jsonSchemaCompact') "effective_validator_native_schema_check"
Assert-Contract ($effectiveValidatorText -match 'import jsonschema') "effective_validator_python_jsonschema_fallback"
Assert-Contract ($effectiveValidatorText -match 'result_json_schema_mismatch') "effective_validator_schema_mismatch_rejected"
Assert-Contract ($effectiveValidatorText -match '\[string\]\$ExpectedJsonSchemaSha256') "effective_validator_expected_schema_hash_parameter"
Assert-Contract ($effectiveValidatorText -match 'json_schema_snapshot_hash_mismatch') "effective_validator_snapshot_hash_fail_closed"
Assert-Contract ($effectiveValidatorText -match 'schema_instance_valid') "effective_validator_schema_result_evidence"
Assert-Contract ($effectiveValidatorText -match 'structuredOutput') "effective_validator_uses_provider_structured_output"
Assert-Contract ($effectiveValidatorText -match 'structured_output_missing') "effective_validator_requires_provider_structured_output"
Assert-Contract ($workerText -match 'structuredOutput') "worker_persists_provider_structured_output"
Assert-Contract ($poolText -match 'effective_output_source') "pool_reports_effective_output_source"
Assert-Contract ($poolText -match 'structured_output_present') "pool_reports_structured_output_presence"
Assert-Contract ($poolText -match 'outer_terminated_process_ids') "pool_timeout_fallback_stop"
Assert-Contract ($poolText -notmatch 'status -eq "ok" -or') "pool_has_no_exit_only_success"
Assert-Contract ($poolText -match 'Get-GrokWorkerPoolUsageAccounting') "pool_uses_partitioned_usage_accounting"
Assert-Contract ($poolAccountingText -match 'accepted.+rejected.+timeout.+incomplete') "pool_accounting_has_four_outcomes"
Assert-Contract ($poolAccountingText -match 'cache_read_input_tokens') "pool_accounting_preserves_cache_tokens"
Assert-Contract ($poolAccountingText -match 'reasoning_tokens') "pool_accounting_preserves_reasoning_tokens"
Assert-Contract ($workerText.Contains('$argsList.Add("--rules")')) "canonical_worker_injects_short_contract_rules"
Assert-Contract ($workerText -match 'short_execution_contract_sha256') "canonical_worker_records_short_contract_hash"
Assert-Contract ($workerText -match '软件工具胶水宪法_当前有效[.]txt') "canonical_worker_points_to_formal_contract"
Assert-Contract ($workerText -match 'private Codex conversation, Plan') "canonical_worker_excludes_private_plan"
Assert-Contract (Test-Path -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Test-GrokWindowsPathIdentity.ps1") -PathType Leaf) "path_identity_test_present"
Assert-Contract (Test-Path -LiteralPath (Join-Path $repoRoot "grok-admin-bridge/Test-GrokWorkerPoolAccounting.ps1") -PathType Leaf) "pool_accounting_test_present"
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
