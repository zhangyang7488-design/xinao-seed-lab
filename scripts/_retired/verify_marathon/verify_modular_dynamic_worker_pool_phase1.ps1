[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-SafeStem {
    param([string]$Value)
    $chars = New-Object System.Collections.Generic.List[char]
    foreach ($ch in $Value.Trim().ToCharArray()) {
        if ([char]::IsLetterOrDigit($ch) -or $ch -eq '-' -or $ch -eq '_') {
            $chars.Add($ch)
        } else {
            $chars.Add('-')
        }
    }
    $cleaned = (-join $chars).Trim('-')
    if ([string]::IsNullOrWhiteSpace($cleaned)) { $cleaned = "wave" }
    if ($cleaned.Length -le 120) { return $cleaned }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($cleaned)
    $digest = (($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") }) -join "").Substring(0, 16)
    $prefix = $cleaned.Substring(0, 103).TrimEnd('-', '_')
    if ([string]::IsNullOrWhiteSpace($prefix)) { $prefix = "wave" }
    return "$prefix-$digest"
}

function Resolve-WaveScopedJson {
    param(
        [string]$LatestAliasPath,
        [string]$RecordsDir,
        [string]$WaveId,
        [string]$Suffix
    )
    Assert-True (-not [string]::IsNullOrWhiteSpace($WaveId)) "Missing wave_id; latest-only verifier is not allowed for $Suffix."
    $safeWaveId = Get-SafeStem $WaveId
    $recordPath = Join-Path $RecordsDir "$safeWaveId.$Suffix.json"
    Assert-True (Test-Path -LiteralPath $recordPath -PathType Leaf) "Missing wave-specific JSON for $Suffix at $recordPath; latest alias is not accepted: $LatestAliasPath"
    $payload = Read-JsonFile $recordPath
    Assert-True ([string]$payload.wave_id -eq $WaveId) "Wave-specific $Suffix wave_id mismatch: expected $WaveId got $($payload.wave_id)"
    return $payload
}

$stateDir = Join-Path $RuntimeRoot "state\modular_dynamic_worker_pool_phase1"
$latestPath = Join-Path $stateDir "latest.json"
$recordsDir = Join-Path $stateDir "records"
$draftQueuePath = Join-Path $stateDir "draft_staging_queue\latest.json"
$mergeConsumerPath = Join-Path $stateDir "merge_consumer\latest.json"
$spendLedgerPath = Join-Path $stateDir "spend_ledger\latest.json"
$fanInStagingMergeSpendPath = Join-Path $stateDir "fan_in_staging_merge_spend\latest.json"
$dynamicWidthPath = Join-Path $RuntimeRoot "state\dynamic_width_policy\latest.json"
$widthBlockerPath = Join-Path $RuntimeRoot "state\width_blocker\latest.json"
$brainProviderPath = Join-Path $RuntimeRoot "state\brain_provider\latest.json"
$workerProviderPath = Join-Path $RuntimeRoot "state\worker_provider\latest.json"
$modelGatewayRoutePath = Join-Path $RuntimeRoot "state\model_gateway_route\latest.json"
$executorAdapterPath = Join-Path $RuntimeRoot "state\executor_adapter\latest.json"
$workerBriefPath = Join-Path $RuntimeRoot "state\worker_brief\latest.json"
$foregroundBrainDecisionPath = Join-Path $stateDir "foreground_brain_decision\latest.json"
$triggerBindingPath = Join-Path $stateDir "trigger_binding\latest.json"
$watchdogPath = Join-Path $stateDir "watchdog_downgrade\latest.json"
$defaultRouteBindingPath = Join-Path $stateDir "default_route_binding\latest.json"
$globalDefaultPath = Join-Path $stateDir "global_default\latest.json"
$whileChainPath = Join-Path $stateDir "while_chain\latest.json"
$phase3DurablePath = Join-Path $RuntimeRoot "state\temporal_activity_no_window_dp_worker_pool_phase3_20260704\latest.json"
$parallelDraftBatchLatestPath = Join-Path $RuntimeRoot "state\parallel_draft_batch\latest.json"
$workerDispatchLedgerPath = Join-Path $RuntimeRoot "state\worker_dispatch_ledger\latest.json"
$workerAssignmentPath = Join-Path $RuntimeRoot "state\worker_assignment\modular_dynamic_worker_pool_phase1_20260704.json"
$globalWorkerAssignmentPath = Join-Path $RuntimeRoot "state\worker_assignment\xinao_seed_cortex_phase0_20260701.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\modular_dynamic_worker_pool_phase1_20260704.md"
$capabilityManifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.modular_dynamic_worker_pool_phase1\manifest.json"
$cheapWorkerPoolCapabilityManifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.modular_cheap_worker_pool.parallel_draft\manifest.json"
$parallelDraftCapabilityManifestPath = Join-Path $RuntimeRoot "capabilities\legacy.deepseek_dp_sidecar.parallel_draft\manifest.json"
$capabilityInvokePath = Join-Path $RuntimeRoot "capabilities\codex_s.modular_dynamic_worker_pool_phase1\invoke_evidence\latest.json"

$latest = Read-JsonFile $latestPath
$latestWaveId = [string]$latest.wave_id
$explicitWorkPackageBound = (
    $latest.explicit_work_package_bound -eq $true `
    -or @($latest.explicit_work_package_lane_ids).Count -gt 0
)
$brainProvider = Read-JsonFile $brainProviderPath
$workerProvider = Read-JsonFile $workerProviderPath
$modelGatewayRoute = Read-JsonFile $modelGatewayRoutePath
$executorAdapter = Read-JsonFile $executorAdapterPath
$workerBrief = Read-JsonFile $workerBriefPath
$foregroundBrainDecision = Read-JsonFile $foregroundBrainDecisionPath
$draftQueue = Resolve-WaveScopedJson $draftQueuePath $recordsDir $latestWaveId "draft_staging_queue"
$mergeConsumer = Resolve-WaveScopedJson $mergeConsumerPath $recordsDir $latestWaveId "merge_consumer"
$spendLedger = Resolve-WaveScopedJson $spendLedgerPath $recordsDir $latestWaveId "spend_ledger"
$fanInStagingMergeSpend = Resolve-WaveScopedJson $fanInStagingMergeSpendPath $recordsDir $latestWaveId "fan_in_staging_merge_spend"
$dynamicWidth = Read-JsonFile $dynamicWidthPath
$widthBlocker = Read-JsonFile $widthBlockerPath
$triggerBinding = Read-JsonFile $triggerBindingPath
$watchdog = Read-JsonFile $watchdogPath
$defaultRouteBinding = Read-JsonFile $defaultRouteBindingPath
$globalDefault = Read-JsonFile $globalDefaultPath
$whileChain = Read-JsonFile $whileChainPath
$phase3Durable = $null
if (Test-Path -LiteralPath $phase3DurablePath -PathType Leaf) {
    $phase3Durable = Read-JsonFile $phase3DurablePath
}
$parallelDraftBatch = Read-JsonFile $parallelDraftBatchLatestPath
$workerDispatchLedger = Read-JsonFile $workerDispatchLedgerPath
$workerAssignment = Read-JsonFile $workerAssignmentPath
$globalWorkerAssignment = Read-JsonFile $globalWorkerAssignmentPath
$capabilityManifest = Read-JsonFile $capabilityManifestPath
$cheapWorkerPoolCapabilityManifest = Read-JsonFile $cheapWorkerPoolCapabilityManifestPath
$parallelDraftCapabilityManifest = Read-JsonFile $parallelDraftCapabilityManifestPath
$capabilityInvoke = Read-JsonFile $capabilityInvokePath

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1") "schema_version mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_CODEX_S_MODULAR_DYNAMIC_WORKER_POOL_PHASE1") "sentinel mismatch."
Assert-True ([string]$latest.task_id -eq "modular_dynamic_worker_pool_phase1_20260704") "task_id mismatch."
Assert-True ([int]$latest.target_width -ge 3) "target_width below 3."
Assert-True ([int]$latest.actual_dispatched_width -ge 3) "actual_dispatched_width below 3."
Assert-True ([int]$latest.actual_completed_width -ge 3) "actual_completed_width below 3."
Assert-True ($latest.progress_counts.planned_is_progress -eq $false) "planned lanes are still counted as progress."
Assert-True ([string]$workerDispatchLedger.schema_version -eq "xinao.codex_s.worker_dispatch_ledger.v1") "worker_dispatch_ledger schema mismatch."
Assert-True ([string]$workerDispatchLedger.wave_id -eq [string]$latest.wave_id) "worker_dispatch_ledger wave_id does not match phase1 latest."
Assert-True ([int]$workerDispatchLedger.succeeded_count -eq [int]$latest.actual_completed_width) "ledger succeeded_count does not match phase1 actual_completed_width."
Assert-True ([int]$latest.worker_dispatch_ledger_succeeded_count -eq [int]$latest.actual_completed_width) "phase1 did not persist ledger/completed alignment."
Assert-True ($latest.worker_dispatch_ledger_succeeded_matches_completed -eq $true) "phase1 ledger/completed alignment flag is false."
Assert-True ($workerDispatchLedger.phase1_binding.ledger_succeeded_matches_completed -eq $true) "worker_dispatch_ledger phase1 binding is not aligned."
Assert-True ([int]$latest.mode_counts.draft -gt 0) "draft mode count missing."
if (-not $explicitWorkPackageBound) {
    Assert-True ([int]$latest.mode_counts.draft -gt [int]$latest.mode_counts.eval) "draft is not primary over eval."
    Assert-True ([int]$latest.mode_counts.draft -gt [int]$latest.mode_counts.contradiction) "draft is not primary over contradiction."
} else {
    Assert-True ([int]$latest.mode_counts.draft -ge 1) "explicit work package has no draft lane."
    Assert-True ([int]$latest.mode_counts.eval -ge 1) "explicit work package has no eval lane."
    Assert-True ([int]$latest.mode_counts.contradiction -ge 1) "explicit work package has no contradiction lane."
}
Assert-True ([int]$latest.mode_counts.search -eq 0) "search must not be a main worker mode."
Assert-True ([int]$latest.mode_counts.provider_probe -eq 0) "provider_probe must not be a main worker mode."
Assert-True ([int]$latest.draft_count -gt 0) "draft_count missing."
Assert-True ([int]$latest.external_cheap_draft_count -gt 0) "external_cheap_draft_count missing; local stub cannot satisfy cheap worker draft pool."
Assert-True ([int]$latest.external_cheap_draft_count -gt [int]$latest.local_stub_draft_count) "local stub draft count is not below external cheap draft count."
Assert-True ([string]$latest.qwen_first_applies_only_to -eq "cheap_worker_lane") "Qwen-first is not scoped to cheap_worker_lane."
Assert-True (@($latest.qwen_first_must_not_override) -contains "engineering_executor_lane") "Qwen-first can override engineering executor lane."
Assert-True (@($latest.qwen_first_must_not_override) -contains "final_merge_lane") "Qwen-first can override final merge lane."
if ($latest.qwen_prepaid_cheap_worker_ready -eq $true) {
    Assert-True ([int]$latest.qwen_prepaid_first_required_count -gt 0) "Qwen ready but no cheap lanes require Qwen-first."
    Assert-True ([int]$latest.qwen_prepaid_first_attempted_count -eq [int]$latest.qwen_prepaid_first_required_count) "Qwen ready but not every cheap lane attempted Qwen-first."
    Assert-True ((([int]$latest.qwen_prepaid_first_succeeded_count + [int]$latest.qwen_fallback_allowed_count) -eq [int]$latest.qwen_prepaid_first_required_count)) "Qwen ready but cheap lanes neither succeeded nor used an allowed fallback."
}
Assert-True ([int]$latest.eval_count -gt 0) "eval_count missing."
Assert-True ([int]$latest.audit_count -gt 0) "audit_count missing."
Assert-True ([int]$latest.staged_count -gt 0) "staged_count missing."
Assert-True ([int]$latest.merged_count -gt 0) "merged_count missing."
Assert-True ([int]$latest.spend_entry_count -eq [int]$latest.actual_dispatched_width) "spend entry count does not match dispatch width."
Assert-True ([int]$latest.token_cost_spend.total_tokens -gt 0) "token_cost_spend total_tokens missing."
Assert-True ([int]$latest.token_cost_spend.metered_usage_entry_count -eq [int]$latest.actual_dispatched_width) "latest is not fully metered."
Assert-True ([int]$latest.token_cost_spend.estimated_usage_entry_count -eq 0) "latest still has estimated usage entries."
Assert-True ($latest.metered -eq $true) "latest metered flag is not true."
Assert-True ($latest.runtime_enforced -eq $true) "latest is not runtime_enforced."
Assert-True ($latest.runtime_enforced_requested -eq $true) "runtime_enforced request flag missing."
Assert-True ($latest.runtime_enforcement_truth_chain.ready -eq $true) "runtime_enforcement truth chain is not ready."
Assert-True ($latest.runtime_enforcement_truth_chain.checks.worker_dispatch_ledger_succeeded_matches_completed -eq $true) "runtime gate did not require ledger alignment."
Assert-True ($latest.runtime_enforcement_truth_chain.checks.artifact_acceptance_count_is_unique -eq $true) "runtime gate did not require unique AAQ."
Assert-True ([string]$latest.python_carrier.expected_python -like "*.venv\Scripts\python.exe") "expected S .venv python carrier missing."
Assert-True ([string]$latest.can_invoke_now.direct_module -like "*.venv\Scripts\python.exe*") "direct invoke does not use S .venv python."
$allowedRuntimeScopes = @(
    "seed_cortex_global_default_modular_dynamic_worker_pool_phase1",
    "seed_cortex_parent_overnight_same_default_phase1_loop",
    "seed_cortex_loop_runtime_state_supervisor_worker_pool_phase2",
    "seed_cortex_temporal_activity_no_window_dp_worker_pool_phase3"
)
Assert-True ([string]$latest.runtime_enforced_scope -in $allowedRuntimeScopes) "latest runtime_enforced_scope mismatch."
Assert-True ($latest.global_default_enforced -eq $true) "latest global_default_enforced missing."
Assert-True ($null -ne $latest.provider_tier_usage) "provider_tier_usage missing."
$failedLatestValidationChecks = @(
    $latest.validation.checks.PSObject.Properties |
        Where-Object { $_.Value -eq $false } |
        ForEach-Object { $_.Name }
)
$onlyExplicitDraftPrimaryGap = (
    $explicitWorkPackageBound `
    -and $failedLatestValidationChecks.Count -eq 1 `
    -and $failedLatestValidationChecks[0] -eq "draft_is_primary"
)
Assert-True (($latest.validation.passed -eq $true) -or $onlyExplicitDraftPrimaryGap) "validation did not pass."
Assert-True ($latest.search_as_main_task -eq $false) "search_as_main_task must be false."
Assert-True ($latest.provider_probe_used_as_progress -eq $false) "provider_probe_used_as_progress must be false."
Assert-True (($latest.stage_order -join "->") -eq "parallel_draft->merge->writer") "stage order mismatch."
Assert-True ([string]$latest.source_entry.source_entry_root -like "C:\Users\xx363\Desktop\*") "source entry root mismatch."
Assert-True ([int]$latest.source_entry.sampled_count -gt 0) "source entry was not dynamically sampled."
Assert-True ([string]$latest.user_latest_correction_digest.task_id -eq "foreground_brain_dp_worker_pool_correction_20260704") "latest user correction digest missing."
Assert-True ($null -ne $latest.foreground_brain_decision) "latest missing foreground_brain_decision."
Assert-True ([string]$latest.foreground_brain_decision.owner -eq "foreground_codex_brain") "foreground brain is not owner."
Assert-True ([string]$latest.foreground_brain_decision.source_entry_read_at -ne "") "foreground brain source_entry_read_at missing."
Assert-True ([string]$latest.foreground_brain_decision.user_latest_correction_digest.task_id -eq "foreground_brain_dp_worker_pool_correction_20260704") "foreground brain correction digest mismatch."
Assert-True ($latest.foreground_brain_decision."333_alignment"."333_is_owner_semantic_line" -eq $true) "333 alignment missing from foreground decision."
Assert-True ([int]$latest.foreground_brain_decision.worker_briefs_generated.draft_brief_count -gt 0) "foreground decision missing draft briefs."
Assert-True ([int]$latest.foreground_brain_decision.draft_artifacts_consumed.Count -gt 0) "foreground decision did not consume drafts."
Assert-True ([int]$latest.foreground_brain_decision.merge_decision.adopted_draft_count -gt 0) "foreground decision did not adopt drafts."
Assert-True ($latest.foreground_brain_decision.next_wave_decision.should_continue -eq $true) "foreground decision did not continue next wave."
Assert-True ([string]$latest.foreground_brain_decision.blocker_or_continue_reason -ne "") "foreground decision missing blocker_or_continue_reason."
Assert-True ($latest.validation.checks.foreground_brain_decision_has_required_fields -eq $true) "foreground brain required fields check failed."
Assert-True ($latest.validation.checks.source_entry_dynamic_read -eq $true) "source_entry_dynamic_read check failed."
Assert-True ($latest.validation.checks.latest_user_correction_digest_bound -eq $true) "latest correction digest check failed."
Assert-True ($latest.validation.checks."333_alignment_bound" -eq $true) "333 alignment check failed."
Assert-True ($latest.validation.checks.foreground_brain_owner_not_background_runner -eq $true) "foreground brain/background runner boundary failed."

Assert-True ([string]$brainProvider.provider_role -eq "SupervisorBrainProvider") "BrainProvider schema missing."
Assert-True ([string]$workerProvider.provider_role -eq "CheapWorkerProvider") "WorkerProvider schema missing."
Assert-True ([string]$modelGatewayRoute.gateway_role -eq "ModelGatewayPort") "ModelGateway route schema missing."
Assert-True ([string]$executorAdapter.adapter_role -eq "ExecutorAdapterPort") "ExecutorAdapter schema missing."
Assert-True ([int]$workerBrief.draft_brief_count -gt 0) "WorkerBrief queue missing draft briefs."
Assert-True ([int]$dynamicWidth.target_width -eq [int]$latest.target_width) "DynamicWidthPolicy target mismatch."
Assert-True ([string]$foregroundBrainDecision.task_id -eq "modular_dynamic_worker_pool_phase1_20260704") "foreground decision task mismatch."
Assert-True ([string]$foregroundBrainDecision.owner -eq "foreground_codex_brain") "foreground decision owner mismatch."
Assert-True ($foregroundBrainDecision.required_fields_present -eq $true) "foreground decision required fields missing."
Assert-True ($foregroundBrainDecision.same_default_loop_semantics.background_runner_only -eq $true) "same_default_loop was not downgraded in foreground decision."

Assert-True ([int]$draftQueue.draft_count -gt 0) "draft staging queue is empty."
Assert-True ([int]$mergeConsumer.merged_count -gt 0) "merge consumer has no merged output."
Assert-True (Test-Path -LiteralPath ([string]$mergeConsumer.merge_artifact) -PathType Leaf) "merge artifact missing."
$mergeArtifactText = Get-Content -LiteralPath ([string]$mergeConsumer.merge_artifact) -Raw -Encoding UTF8
Assert-True ($mergeArtifactText.Contains("Progress This Wave")) "merge artifact missing progress section."
Assert-True ($mergeArtifactText.Contains("Adopted Drafts")) "merge artifact missing adopted drafts section."
Assert-True ($mergeArtifactText.Contains("Rejected Or Deferred Drafts")) "merge artifact missing rejected drafts section."
Assert-True ($mergeArtifactText.Contains("Current Gaps")) "merge artifact missing gap section."
Assert-True ($mergeArtifactText.Contains("Next Dispatch")) "merge artifact missing next dispatch section."
Assert-True ([int]$spendLedger.spend_entry_count -eq [int]$latest.actual_dispatched_width) "spend ledger incomplete."
Assert-True ([int]$spendLedger.token_cost_spend.total_tokens -gt 0) "spend ledger token fields missing."
Assert-True ([int]$spendLedger.token_cost_spend.metered_usage_entry_count -eq [int]$latest.actual_dispatched_width) "spend ledger not fully metered."
Assert-True ([int]$spendLedger.token_cost_spend.estimated_usage_entry_count -eq 0) "spend ledger still has estimated entries."
Assert-True ([string]$fanInStagingMergeSpend.status -eq "fan_in_staging_merge_spend_ready") "fan_in_staging_merge_spend is not ready."
Assert-True ([string]$fanInStagingMergeSpend.wave_id -eq [string]$latest.wave_id) "fan_in_staging_merge_spend wave mismatch."
Assert-True ([string]$fanInStagingMergeSpend.workflow_id -eq [string]$latest.workflow_id) "fan_in_staging_merge_spend workflow_id mismatch."
Assert-True ([string]$fanInStagingMergeSpend.workflow_run_id -eq [string]$latest.workflow_run_id) "fan_in_staging_merge_spend workflow_run_id mismatch."
Assert-True ([string]$fanInStagingMergeSpend.staging_ref -eq $draftQueuePath) "fan_in_staging_merge_spend staging_ref mismatch."
Assert-True ([string]$fanInStagingMergeSpend.merge_ref -eq $mergeConsumerPath) "fan_in_staging_merge_spend merge_ref mismatch."
Assert-True ([string]$fanInStagingMergeSpend.spend_ref -eq $spendLedgerPath) "fan_in_staging_merge_spend spend_ref mismatch."
Assert-True ([int]$fanInStagingMergeSpend.staged_count -eq [int]$draftQueue.staged_count) "fan_in_staging_merge_spend staged_count mismatch."
Assert-True ([int]$fanInStagingMergeSpend.merged_count -eq [int]$mergeConsumer.merged_count) "fan_in_staging_merge_spend merged_count mismatch."
Assert-True ([int]$fanInStagingMergeSpend.spend_entry_count -eq [int]$spendLedger.spend_entry_count) "fan_in_staging_merge_spend spend_entry_count mismatch."
Assert-True ([int]$fanInStagingMergeSpend.accepted_artifact_count -gt 0) "fan_in_staging_merge_spend AAQ acceptance missing."
Assert-True ($fanInStagingMergeSpend.next_frontier.should_continue -eq $true) "fan_in_staging_merge_spend next frontier did not continue."
Assert-True ($fanInStagingMergeSpend.validation.passed -eq $true) "fan_in_staging_merge_spend validation did not pass."
Assert-True ($latest.validation.checks.fan_in_staging_merge_spend_written -eq $true) "latest validation did not require fan_in_staging_merge_spend."
Assert-True ([string]$widthBlocker.status -eq "width_blocker_clear") "width blocker not clear."
Assert-True ([string]$triggerBinding.status -eq "parallel_draft_to_merge_hot_path_bound") "trigger binding status mismatch."
Assert-True ([string]$triggerBinding.hot_path -eq "parallel_draft->merge->writer") "trigger hot path mismatch."
Assert-True ([string]$triggerBinding.dp_worker_role -eq "draft_main_worker_pool") "DP worker role mismatch."
Assert-True ($triggerBinding.search_is_main_task -eq $false) "trigger binding lets search be main task."
Assert-True ($triggerBinding.provider_probe_used_as_progress -eq $false) "trigger binding lets provider_probe count as progress."
Assert-True ($triggerBinding.runtime_enforced -eq $true) "trigger binding is not runtime_enforced."
Assert-True ([string]$watchdog.status -eq "watchdog_downgraded_for_phase1_fast_path") "watchdog was not downgraded for phase1."
Assert-True ([string]$defaultRouteBinding.adoption_state -eq "runtime_enforced_global_default") "default route binding not runtime_enforced_global_default."
Assert-True ($defaultRouteBinding.runtime_enforced -eq $true) "default route binding is not runtime_enforced."
Assert-True ([string]$defaultRouteBinding.provider_scheduler_default_layer.provider_id -eq "codex_s.provider_scheduler") "default route missing ProviderScheduler layer."
Assert-True ([string]$defaultRouteBinding.provider_scheduler_default_layer.status -eq "ready") "ProviderScheduler layer is not ready."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.qwen_prepaid_cheap_worker_default_first -eq $true) "Qwen prepaid cheap worker is not default-first in ProviderScheduler layer."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.qwen_dashscope_canary_ready -eq $true) "Qwen DashScope canary is not ready in ProviderScheduler layer."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.codex_native_default_primary -eq $false) "ProviderScheduler layer still treats Codex as bulk primary."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.codex_brain_only_default -eq $true) "ProviderScheduler layer missing Codex brain-only default."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.codex_bulk_worker_default_paused -eq $true) "ProviderScheduler layer did not pause Codex bulk worker."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.default_token_saving_worker_route -eq $true) "ProviderScheduler layer missing token-saving route."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.outputs_to_staging_only -eq $true) "ProviderScheduler layer does not preserve staging-only output."
Assert-True ($defaultRouteBinding.provider_scheduler_default_layer.direct_repo_write_allowed -eq $false) "ProviderScheduler layer allows direct repo write."
Assert-True ([int]$parallelDraftBatch.draft_lanes.Count -gt 0) "parallel_draft_batch latest missing draft lanes."
Assert-True ([string]$workerAssignment.source_intent_package_id -eq "grok_faithful_modular_dynamic_worker_pool_20260704") "task worker assignment not rebound."
Assert-True ([string]$globalWorkerAssignment.task_id -eq "modular_dynamic_worker_pool_phase1_20260704") "global worker assignment not rebound."
Assert-True ([string]$capabilityManifest.provider_id -eq "codex_s.modular_dynamic_worker_pool_phase1") "capability manifest provider mismatch."
Assert-True ($capabilityManifest.runtime_enforced -eq $true) "capability manifest is not runtime_enforced."
Assert-True ([string]$capabilityManifest.adoption_state -eq "runtime_enforced_global_default") "capability manifest adoption state mismatch."
Assert-True ([string]$cheapWorkerPoolCapabilityManifest.provider_id -eq "codex_s.modular_cheap_worker_pool.parallel_draft") "cheap worker pool capability manifest mismatch."
Assert-True ([string]$cheapWorkerPoolCapabilityManifest.qwen_first_applies_only_to -eq "cheap_worker_lane") "cheap worker pool manifest does not scope Qwen-first."
Assert-True (@($cheapWorkerPoolCapabilityManifest.qwen_first_must_not_override) -contains "final_merge_lane") "cheap worker pool manifest lets Qwen override final merge."
Assert-True ([string]$parallelDraftCapabilityManifest.provider_id -eq "legacy.deepseek_dp_sidecar.parallel_draft") "parallel draft capability manifest mismatch."
Assert-True ($parallelDraftCapabilityManifest.reference_only_fallback_provider -eq $true) "legacy DP parallel draft manifest is not marked fallback/reference."
Assert-True ($capabilityInvoke.invoke_performed -eq $true) "capability invoke missing."
Assert-True ($capabilityInvoke.runtime_enforced -eq $true) "capability invoke is not runtime_enforced."

$legacyGlobalDefaultOk = (
    [string]$globalDefault.status -eq "global_default_runtime_enforced_while_self_chain_pop_ready" `
    -and $globalDefault.runtime_enforced -eq $true `
    -and [int]$globalDefault.enforced_wave_count -ge 3 `
    -and [int]$globalDefault.metered_wave_count -ge 3 `
    -and [int]$globalDefault.self_chain_wave_count -ge 3 `
    -and $globalDefault.while_pop.pop_ready -eq $true `
    -and $globalDefault.validation.passed -eq $true `
    -and $globalDefault.validation.checks.three_waves_enforced -eq $true `
    -and $globalDefault.validation.checks.three_waves_metered -eq $true `
    -and $globalDefault.validation.checks.three_waves_self_chained -eq $true `
    -and $globalDefault.validation.checks.capability_gateway_phase1_runtime_enforced -eq $true `
    -and [string]$whileChain.status -eq [string]$globalDefault.status
)

$temporalDurableDefaultOk = (
    $null -ne $phase3Durable `
    -and [string]$phase3Durable.status -eq "phase3_temporal_activity_event_queue_wave_ready" `
    -and $phase3Durable.validation.passed -eq $true `
    -and $phase3Durable.temporal.temporal_owner -eq $true `
    -and $phase3Durable.temporal.event_queue_self_chain_enabled -eq $true `
    -and [int]$phase3Durable.temporal.continue_generation -ge 1 `
    -and [string]$phase3Durable.background.main_loop -eq "temporal_activity_event_queue_loop" `
    -and $phase3Durable.background.event_queue_driven -eq $true `
    -and $phase3Durable.background.not_30_minute_runner -eq $true `
    -and $phase3Durable.background.sleep_seconds_1800_default_main_loop_allowed -eq $false `
    -and [int]$phase3Durable.phase1_payload_summary.actual_dispatched_width -ge 3 `
    -and [int]$phase3Durable.phase1_payload_summary.actual_completed_width -ge 3 `
    -and [int]$phase3Durable.phase1_payload_summary.external_cheap_draft_count -gt 0 `
    -and [int]$phase3Durable.phase1_payload_summary.qwen_prepaid_draft_count -gt 0 `
    -and [int]$phase3Durable.phase1_payload_summary.staged_count -gt 0 `
    -and [int]$phase3Durable.phase1_payload_summary.merged_count -gt 0 `
    -and [string]$phase3Durable.phase1_payload_summary.target_width_source -eq "dynamic_width_scheduler" `
    -and $phase3Durable.stop.derived -eq $true `
    -and $phase3Durable.stop.stop_allowed -eq $false `
    -and $phase3Durable.validation.checks.event_queue_driven_not_30min -eq $true `
    -and $phase3Durable.validation.checks.dynamic_width_decision_explained -eq $true
)

Assert-True ($legacyGlobalDefaultOk -or $temporalDurableDefaultOk) "default route is neither legacy pop-ready nor current Temporal durable event-queue enforced."

Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
Assert-True ($readback.Contains("invoke")) "readback does not answer invoke."
Assert-True ($readback.Contains("parallel_draft -> merge -> writer")) "readback missing wave shape."
Assert-True ($readback.Contains("search/provider_probe")) "readback missing DP role boundary."
Assert-True ($readback.Contains("foreground_brain_decision")) "readback missing foreground brain decision."

Write-Output "modular_dynamic_worker_pool_phase1_latest=$latestPath"
Write-Output "modular_dynamic_worker_pool_phase1_merge_artifact=$($mergeConsumer.merge_artifact)"
Write-Output "modular_dynamic_worker_pool_phase1_foreground_brain_decision=$foregroundBrainDecisionPath"
Write-Output "modular_dynamic_worker_pool_phase1_fan_in_staging_merge_spend=$fanInStagingMergeSpendPath"
Write-Output "modular_dynamic_worker_pool_phase1_readback=$readbackPath"
Write-Output "modular_dynamic_worker_pool_phase1_capability_manifest=$capabilityManifestPath"
Write-Output "modular_dynamic_worker_pool_phase1_cheap_worker_pool_manifest=$cheapWorkerPoolCapabilityManifestPath"
Write-Output "modular_dynamic_worker_pool_phase1_global_default=$globalDefaultPath"
Write-Output "modular_dynamic_worker_pool_phase1_while_chain=$whileChainPath"
Write-Output "modular_dynamic_worker_pool_phase1_temporal_durable_default=$phase3DurablePath"
Write-Output "validation_result=ok"
