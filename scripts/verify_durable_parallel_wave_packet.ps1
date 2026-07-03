$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\durable_parallel_wave_packet.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_durable_parallel_wave_packet.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_durable_parallel_wave_packet.v1.json"
$schedulerPacketPath = Join-Path $repoRoot "services\agent_runtime\scheduler_invocation_packet.py"
$schedulerLaneEvidencePath = Join-Path $repoRoot "services\agent_runtime\scheduler_spawned_lane_evidence.py"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "Durable parallel wave packet py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "Durable parallel wave packet pytest failed."

$schedulerPacketOutput = python $schedulerPacketPath `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --current-parent-codex-invocation-ref "codex-parent-invocation:verify-durable-wave-packet" `
    --spawned-lane "current_parent_codex_subagent:019f22a3-13b1-73d3-8f81-1b36cc635c23" `
    --spawned-lane "current_parent_codex_subagent:019f22a3-141d-7311-bf78-69a37f9db88e"
Assert-True ($LASTEXITCODE -eq 0) "Scheduler invocation packet current-parent generation failed."
Assert-True (($schedulerPacketOutput -join "`n").Contains("SENTINEL:XINAO_SCHEDULER_INVOCATION_PACKET_READY")) "Scheduler invocation packet current-parent sentinel missing."

$schedulerPacketLatest = Join-Path $runtimeRoot "state\scheduler_invocation_packet\latest.json"
$schedulerCurrentParentLatest = Join-Path $runtimeRoot "state\scheduler_spawned_lane_evidence\current_parent_latest.json"
$schedulerLaneOutput = python $schedulerLaneEvidencePath `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --scheduler-invocation-ref $schedulerPacketLatest `
    --output-latest $schedulerCurrentParentLatest
Assert-True ($LASTEXITCODE -eq 0) "Scheduler spawned lane current-parent evidence generation failed."
Assert-True (($schedulerLaneOutput -join "`n").Contains("SENTINEL:XINAO_SCHEDULER_SPAWNED_LANE_EVIDENCE_READY")) "Scheduler spawned lane current-parent sentinel missing."

$output = python $modulePath `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --codex-subagent "019f22a3-13b1-73d3-8f81-1b36cc635c23:worker_dispatch_ledger" `
    --codex-subagent "019f22a3-141d-7311-bf78-69a37f9db88e:hot_path_probe"
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "Durable parallel wave packet generation failed."
$text = $output -join "`n"
Assert-True ($text.Contains("SENTINEL:XINAO_DURABLE_PARALLEL_WAVE_PACKET_READY")) "Durable packet sentinel missing."

$latestPath = Join-Path $runtimeRoot "state\durable_parallel_wave_packet\latest.json"
$readbackPath = Join-Path $runtimeRoot "readback\zh\durable_parallel_wave_packet_20260702.md"

foreach ($path in @($schemaPath, $latestPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing durable packet evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.durable_parallel_wave_packet.v1") "Schema mismatch."
Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_DURABLE_PARALLEL_WAVE_PACKET_READY") "Payload sentinel mismatch."
Assert-True ($payload.status -eq "durable_parallel_wave_packet_ready") "Durable packet not ready."
Assert-True ($payload.adoption_state -eq "verifier_ready_but_not_hooked") "Durable packet overclaimed adoption."
Assert-True ($payload.continue_dispatch_expected -eq $true) "Durable packet did not allow next dispatch."
Assert-True ($payload.validation.passed -eq $true) "Durable packet validation failed."
Assert-True ($payload.stop_guard_layers_are_main_execution_loop -eq $false) "Stop guard layers became main loop."

$expectedLoop = @(
    "restore",
    "dispatch",
    "poll",
    "fan_in",
    "verify_evidence_readback",
    "recompute_capacity",
    "next_wave"
)
$actualLoop = @($payload.main_execution_loop)
Assert-True (($actualLoop -join "|") -eq ($expectedLoop -join "|")) "Main execution loop mismatch."

Assert-True ($payload.codex_subagent_dispatch.recorded_subagent_count -ge 2) "Subagent refs were not recorded."
Assert-True ($payload.codex_subagent_dispatch.spawned_by_this_runner -eq $false) "Durable packet claimed to spawn agents."
Assert-True ($payload.dp_sidecar_execution.port_id -eq "dp_sidecar_execution_port") "Wrong DP execution port."
Assert-True ($payload.dp_sidecar_execution.default_lane_count -eq 20) "DP lane count was not 20."
Assert-True ($payload.dp_sidecar_execution.dp_search_is_mode_not_port_definition -eq $true) "dp_search was treated as port definition."
Assert-True ($payload.dp_sidecar_execution.runner_latest_ref.exists -eq $true) "DP sidecar runner latest ref missing."
Assert-True ($payload.dp_sidecar_execution.provider_latest_ref.exists -eq $true) "DP sidecar provider latest ref missing."
Assert-True ($payload.dp_sidecar_execution.provider_manifest_ref.exists -eq $true) "DP sidecar provider manifest ref missing."
Assert-True ($payload.dp_sidecar_execution.callable_entrypoint_bound -eq $true) "DP sidecar callable entrypoint not bound."
$modeTotal = 0
$payload.dp_sidecar_execution.mode_counts.PSObject.Properties | ForEach-Object { $modeTotal += [int]$_.Value }
Assert-True ($modeTotal -eq 20) "DP mode total was not 20."

Assert-True ($payload.fan_in_policy.fan_in_required_before_fact_promotion -eq $true) "Fan-in was not required."
Assert-True ($payload.fan_in_policy.artifact_acceptance_queue_required -eq $true) "Artifact acceptance queue was not required."
Assert-True ($payload.fan_in_policy.direct_fact_promotion_allowed -eq $false) "Direct fact promotion was allowed."
Assert-True ($payload.temporal_activity_refs.activity_refs_are_evidence_only -eq $true) "Temporal activity refs were not evidence-only."
Assert-True ($payload.temporal_activity_refs.activity_refs_are_not_stop_guard_layers -eq $true) "Temporal activity refs became stop guard layers."
Assert-True ($payload.temporal_activity_refs.activity_refs_are_not_completion_gates -eq $true) "Temporal activity refs became completion gates."
Assert-True ($payload.temporal_activity_refs.activity_refs_are_not_execution_controllers -eq $true) "Temporal activity refs became execution controllers."
Assert-True ($payload.temporal_activity_refs.worker_dispatch_ledger_activity.exists -eq $true) "Missing temporal worker dispatch ledger activity ref."
Assert-True ($payload.temporal_activity_refs.main_execution_loop_tick_activity.exists -eq $true) "Missing temporal main execution loop tick activity ref."
Assert-True ($payload.actual_dispatch_refs.codex_subagent_count -ge 1) "Actual dispatch worker/subagent refs were not recorded."
Assert-True (@($payload.actual_dispatch_refs.codex_subagents).Count -ge 1) "Actual dispatch codex worker/subagent list missing."
Assert-True ($payload.actual_dispatch_refs.parallel_dispatch_plan_ref.exists -eq $true) "Actual dispatch missing parallel dispatch plan ref."
Assert-True ($payload.actual_dispatch_refs.worker_dispatch_ledger_activity_ref.exists -eq $true) "Actual dispatch missing worker activity ref."
Assert-True ($payload.actual_dispatch_refs.main_execution_loop_tick_activity_ref.exists -eq $true) "Actual dispatch missing main tick activity ref."
Assert-True ($payload.scheduler_invocation_refs.scheduler_invocation_packet_latest.exists -eq $true) "Scheduler invocation packet ref missing."
Assert-True ($payload.scheduler_invocation_refs.scheduler_spawned_lane_evidence_current_parent.exists -eq $true) "Scheduler current-parent lane evidence ref missing."
Assert-True ($payload.scheduler_invocation_refs.scheduler_invocation_status -eq "spawned_lane_refs_recorded") "Scheduler invocation packet status mismatch."
Assert-True ($payload.scheduler_invocation_refs.scheduler_invoked -eq $true) "Scheduler invocation flag missing."
Assert-True ($payload.scheduler_invocation_refs.parent_dispatch_invoked -eq $true) "Scheduler parent dispatch flag missing."
Assert-True ($payload.scheduler_invocation_refs.current_parent_lane_evidence_state -eq "parent_scheduler_invoked_with_lane_refs_not_default_runtime") "Scheduler current-parent lane state mismatch."
Assert-True ([int]$payload.scheduler_invocation_refs.current_parent_scheduler_spawned_lane_count -ge 1) "Scheduler current-parent spawned lane count missing."
Assert-True ($payload.scheduler_invocation_refs.default_runtime_scheduler_invoked -eq $false) "Scheduler refs overclaimed default runtime scheduler."
Assert-True ($payload.scheduler_invocation_refs.runtime_enforced -eq $false) "Scheduler refs overclaimed runtime enforcement."
Assert-True ($payload.scheduler_invocation_refs.refs_are_not_execution_controllers -eq $true) "Scheduler refs became execution controllers."
Assert-True ($payload.actual_dispatch_refs.scheduler_invocation_packet_ref.exists -eq $true) "Actual dispatch missing scheduler invocation packet ref."
Assert-True ($payload.actual_dispatch_refs.scheduler_spawned_lane_evidence_current_parent_ref.exists -eq $true) "Actual dispatch missing scheduler current-parent evidence ref."
Assert-True ($payload.actual_dispatch_refs.scheduler_current_parent_lane_evidence_state -eq "parent_scheduler_invoked_with_lane_refs_not_default_runtime") "Actual dispatch scheduler lane state mismatch."
Assert-True ([int]$payload.actual_dispatch_refs.scheduler_current_parent_spawned_lane_count -ge 1) "Actual dispatch scheduler current-parent count missing."
Assert-True ($payload.actual_dispatch_refs.scheduler_current_parent_refs_bound -eq $true) "Actual dispatch scheduler refs not bound."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_port -eq "dp_sidecar_execution_port") "Actual dispatch DP port mismatch."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_port_runner_ref.exists -eq $true) "Actual dispatch missing DP runner ref."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_provider_ref.exists -eq $true) "Actual dispatch missing DP provider ref."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_provider_manifest_ref.exists -eq $true) "Actual dispatch missing DP provider manifest ref."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_callable_entrypoint_bound -eq $true) "Actual dispatch DP callable entrypoint not bound."
Assert-True ($payload.actual_dispatch_refs.spawned_by_this_runner -eq $false) "Durable packet claimed to spawn subagents."
Assert-True ($payload.actual_dispatch_refs.refs_are_evidence_only -eq $true) "Actual dispatch refs were not evidence-only."
Assert-True ($payload.actual_dispatch_refs.refs_are_not_completion_gates -eq $true) "Actual dispatch refs became completion gates."
Assert-True ($payload.actual_dispatch_refs.refs_are_not_execution_controllers -eq $true) "Actual dispatch refs became execution controllers."
Assert-True ($payload.poll_refs.live_backend_watch_ref.exists -eq $true) "Poll refs missing live backend watch."
Assert-True ($payload.poll_refs.poll_policy -eq "poll_live_backend_watch_first") "Poll policy mismatch."
Assert-True ($payload.poll_refs.worker_jsonl_non_terminal_blocks_stop -eq $true) "Poll refs missing worker jsonl non-terminal stop block."
Assert-True ($payload.poll_refs.output_growth_blocks_stop -eq $true) "Poll refs missing output growth stop block."
Assert-True ($payload.fan_in_refs.parallel_fan_in_acceptance_ref.exists -eq $true) "Fan-in refs missing parallel fan-in acceptance."
Assert-True ($payload.fan_in_refs.artifact_acceptance_queue_ref.exists -eq $true) "Fan-in refs missing artifact acceptance queue."
Assert-True ($payload.fan_in_refs.fan_in_required_before_fact_promotion -eq $true) "Fan-in refs did not require fan-in before fact promotion."
Assert-True ($payload.fan_in_refs.artifact_acceptance_queue_required -eq $true) "Fan-in refs did not require artifact acceptance queue."
Assert-True ($payload.fan_in_refs.direct_fact_promotion_allowed -eq $false) "Fan-in refs allowed direct fact promotion."
Assert-True ($payload.user_correction_runtime_refs.service_entrypoint_ref.exists -eq $true) "User correction runtime service ref missing."
Assert-True ($payload.user_correction_runtime_refs.service_entrypoint_ref.schema_version -eq "xinao.codex_s.seed_lab_user_correction_runtime.v1") "User correction runtime service schema mismatch."
Assert-True ($payload.user_correction_runtime_refs.correction_intake_ref.exists -eq $true) "CorrectionIntake ref missing."
Assert-True ($payload.user_correction_runtime_refs.experiment_review_view_ref.exists -eq $true) "ExperimentReviewView ref missing."
Assert-True ($payload.user_correction_runtime_refs.replay_court_ref.exists -eq $true) "ReplayCourt ref missing."
Assert-True ($payload.user_correction_runtime_refs.explicit_service_api_candidate -eq $true) "User correction runtime explicit service/API candidate missing."
Assert-True ($payload.user_correction_runtime_refs.runtime_enforced -eq $false) "User correction runtime overclaimed runtime enforcement."
Assert-True ($payload.user_correction_runtime_refs.trigger_installed -eq $false) "User correction runtime trigger was installed."
Assert-True ($payload.user_correction_runtime_refs.memory_promotion_allowed -eq $false) "User correction runtime allowed memory promotion."
Assert-True ($payload.user_correction_runtime_refs.policy_promotion_allowed -eq $false) "User correction runtime allowed policy promotion."
Assert-True ($payload.user_correction_runtime_refs.completion_claim_allowed -eq $false) "User correction runtime allowed completion claim."
Assert-True ($payload.user_correction_runtime_refs.refs_are_not_execution_controllers -eq $true) "User correction runtime refs became controllers."
Assert-True (-not [string]::IsNullOrWhiteSpace($payload.evidence_refs.runtime_latest)) "Evidence refs missing runtime latest."
Assert-True ($payload.evidence_refs.verifier -like "*verify_durable_parallel_wave_packet.ps1") "Evidence refs missing verifier."
Assert-True ($payload.evidence_refs.seed_lab_user_correction_runtime_service_latest -like "*seed_lab_user_correction_runtime*service_entrypoint_latest.json") "Evidence refs missing user correction runtime service latest."
Assert-True ($payload.evidence_refs.seed_lab_replay_court_latest -like "*seed_lab_replay_court*latest.json") "Evidence refs missing ReplayCourt latest."
Assert-True ($payload.evidence_refs.scheduler_invocation_packet_latest -like "*scheduler_invocation_packet*latest.json") "Evidence refs missing scheduler invocation packet latest."
Assert-True ($payload.evidence_refs.scheduler_spawned_lane_evidence_current_parent_latest -like "*scheduler_spawned_lane_evidence*current_parent_latest.json") "Evidence refs missing scheduler current-parent latest."
Assert-True ($payload.evidence_refs.dp_sidecar_execution_port_runner_latest -like "*dp_sidecar_execution_port*latest.json") "Evidence refs missing DP runner latest."
Assert-True ($payload.evidence_refs.dp_sidecar_execution_provider_latest -like "*dp_sidecar_execution_provider*latest.json") "Evidence refs missing DP provider latest."
Assert-True ($payload.evidence_refs.dp_sidecar_execution_provider_manifest -like "*legacy.deepseek_dp_sidecar.dp_sidecar_execution_port*manifest.json") "Evidence refs missing DP provider manifest."
Assert-True (-not [string]::IsNullOrWhiteSpace($payload.readback_refs.runtime_readback_zh)) "Readback refs missing zh readback."
Assert-True ($payload.readback_refs.seed_lab_user_correction_runtime_service_readback -like "*seed_lab_user_correction_runtime_service_entrypoint_20260702.md") "Readback refs missing user correction runtime service readback."
Assert-True ($payload.readback_refs.human_visible_readback_required -eq $true) "Readback refs missing human-visible requirement."
Assert-True ($payload.service_entrypoint.api_cli_adoption_state -eq "api_cli_verifier_ready_not_hook_enforced") "Durable packet missing API/CLI adoption state."
Assert-True ($payload.service_entrypoint.runtime_enforced -eq $false) "Durable packet API/CLI entrypoint overclaimed runtime enforcement."
Assert-True ($payload.service_entrypoint.temporal_enforced -eq $false) "Durable packet API/CLI entrypoint overclaimed Temporal enforcement."
Assert-True ($payload.service_entrypoint.stop_hook_controller -eq $false) "Durable packet API/CLI entrypoint became Stop hook controller."
Assert-True ($payload.service_entrypoint.main_execution_loop_packet_entrypoint -eq $true) "Durable packet API/CLI entrypoint flag missing."
Assert-True ($payload.api_surface.fastapi_route -eq "POST /runtime/durable-parallel-wave-packet") "Durable packet FastAPI route missing."
Assert-True ($payload.api_surface.openapi_ref -eq "contracts/openapi/seedlab.v1.yaml") "Durable packet OpenAPI ref missing."
Assert-True ($payload.api_surface.cli_command -like "*durable-parallel-wave-packet") "Durable packet CLI command missing."
Assert-True ($payload.validation.checks.temporal_worker_dispatch_ledger_activity_ref_present -eq $true) "Worker dispatch activity ref validation missing."
Assert-True ($payload.validation.checks.temporal_main_execution_loop_tick_activity_ref_present -eq $true) "Main tick activity ref validation missing."
Assert-True ($payload.validation.checks.temporal_activity_refs_are_not_execution_controllers -eq $true) "Temporal activity refs controller boundary validation failed."
Assert-True ($payload.validation.checks.actual_dispatch_refs_bound -eq $true) "Actual dispatch refs validation failed."
Assert-True ($payload.validation.checks.actual_codex_subagent_or_worker_refs_present -eq $true) "Actual worker/subagent refs were not validated."
Assert-True ($payload.validation.checks.poll_refs_bound -eq $true) "Poll refs validation failed."
Assert-True ($payload.validation.checks.fan_in_refs_bound -eq $true) "Fan-in refs validation failed."
Assert-True ($payload.validation.checks.user_correction_runtime_refs_bound -eq $true) "User correction runtime refs validation failed."
Assert-True ($payload.validation.checks.user_correction_runtime_not_enforced -eq $true) "User correction runtime non-enforcement validation failed."
Assert-True ($payload.validation.checks.scheduler_invocation_packet_ref_present -eq $true) "Scheduler invocation packet ref validation failed."
Assert-True ($payload.validation.checks.scheduler_spawned_lane_current_parent_ref_present -eq $true) "Scheduler current-parent ref validation failed."
Assert-True ($payload.validation.checks.scheduler_current_parent_lane_refs_bound_no_overclaim -eq $true) "Scheduler current-parent no-overclaim validation failed."
Assert-True ($payload.validation.checks.scheduler_refs_not_runtime_enforced -eq $true) "Scheduler refs runtime enforcement boundary failed."
Assert-True ($payload.validation.checks.dp_sidecar_execution_callable_refs_bound -eq $true) "DP sidecar callable refs validation failed."
Assert-True ($payload.validation.checks.evidence_and_readback_refs_bound -eq $true) "Evidence/readback refs validation failed."
Assert-True ($payload.legacy_5d33_transport_pattern.task_scoped_durable_owner_pattern_allowed -eq $true) "5d33 transport pattern was not retained."
Assert-True ($payload.legacy_5d33_transport_pattern.old_5d33_owner_allowed -eq $false) "Old 5d33 owner leaked."
Assert-True ($payload.legacy_5d33_transport_pattern.old_pass_allowed -eq $false) "Old PASS leaked."
Assert-True ($payload.legacy_5d33_transport_pattern.old_latest_json_authority_allowed -eq $false) "Old latest authority leaked."
Assert-True ($payload.legacy_5d33_transport_pattern.old_completion_gate_allowed -eq $false) "Old completion gate leaked."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
Assert-True ($payload.phase1_data_chain_allowed -eq $false) "Phase1 data chain was allowed."
Assert-True ($payload.positive_ev_claim_allowed -eq $false) "Positive EV claim was allowed."
Assert-True ($payload.not_source_of_truth -eq $true) "Boundary not_source_of_truth missing."
Assert-True ($payload.not_user_completion -eq $true) "Boundary not_user_completion missing."
Assert-True ($payload.not_completion_decision -eq $true) "Boundary not_completion_decision missing."
Assert-True ($payload.not_execution_controller -eq $true) "Boundary not_execution_controller missing."

$readbackText = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
Assert-True ($readbackText.Contains("restore -> dispatch -> poll -> fan-in")) "Readback missing main loop."
Assert-True ($readbackText.Contains("temporal_activity_refs_bound: True")) "Readback missing temporal activity refs binding."
Assert-True ($readbackText.Contains("actual_dispatch_refs_bound: True")) "Readback missing actual dispatch refs binding."
Assert-True ($readbackText.Contains("fan_in_refs_bound: True")) "Readback missing fan-in refs binding."
Assert-True ($readbackText.Contains("user_correction_runtime_refs_bound: True")) "Readback missing user correction runtime refs binding."
Assert-True ($readbackText.Contains("user_correction_runtime_enforced: False")) "Readback overclaimed user correction runtime enforcement."
Assert-True ($readbackText.Contains("scheduler_invocation_packet_ref_bound: True")) "Readback missing scheduler invocation packet binding."
Assert-True ($readbackText.Contains("scheduler_current_parent_lane_refs_bound: True")) "Readback missing scheduler current-parent lane binding."
Assert-True ($readbackText.Contains("scheduler_refs_runtime_enforced: False")) "Readback overclaimed scheduler runtime enforcement."
Assert-True ($readbackText.Contains("dp_sidecar_execution_callable_refs_bound: True")) "Readback missing DP callable refs binding."
Assert-True ($readbackText.Contains("SENTINEL:XINAO_DURABLE_PARALLEL_WAVE_PACKET_READY")) "Readback missing sentinel."

Write-Output "durable_parallel_wave_packet_latest=$latestPath"
Write-Output "durable_parallel_wave_packet_readback=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_DURABLE_PARALLEL_WAVE_PACKET_READY"
