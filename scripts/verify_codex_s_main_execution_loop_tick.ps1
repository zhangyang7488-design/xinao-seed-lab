$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
$anchorRoot = Join-Path (Join-Path $env:USERPROFILE "Desktop") (
    [string]([char]0x65B0) + [string]([char]0x7CFB) + [string]([char]0x7EDF)
)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\codex_s_main_execution_loop_tick.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_codex_s_main_execution_loop_tick.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_main_execution_loop_tick.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "Main execution loop tick py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "Main execution loop tick pytest failed."

$output = python $modulePath `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --anchor-package-root $anchorRoot `
    --codex-subagent "019f22a3-13b1-73d3-8f81-1b36cc635c23:worker_dispatch_ledger" `
    --codex-subagent "019f22a3-141d-7311-bf78-69a37f9db88e:hot_path_probe"
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "Main execution loop tick generation failed."
$text = $output -join "`n"
Assert-True ($text.Contains("SENTINEL:XINAO_CODEX_S_MAIN_EXECUTION_LOOP_TICK_READY")) "Main loop tick sentinel missing."

$latestPath = Join-Path $runtimeRoot "state\codex_s_main_execution_loop_tick\latest.json"
$readbackPath = Join-Path $runtimeRoot "readback\zh\codex_s_main_execution_loop_tick_20260702.md"

foreach ($path in @($schemaPath, $latestPath, $readbackPath)) {
    Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing main loop tick evidence: $path"
}

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.main_execution_loop_tick.v1") "Schema mismatch."
Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_MAIN_EXECUTION_LOOP_TICK_READY") "Payload sentinel mismatch."
Assert-True ($payload.status -eq "main_execution_loop_tick_ready") "Main loop tick not ready."
Assert-True ($payload.adoption_state -eq "verifier_ready_but_not_hooked") "Main loop tick overclaimed adoption."
Assert-True ($payload.ordinary_discussion_can_stop -eq $true) "Ordinary discussion stop boundary missing."
Assert-True ($payload.current_four_text_same_source_task_no_stop -eq $true) "Current no-stop task was not marked active."
Assert-True ($payload.stop_guard_layers_are_main_execution_loop -eq $false) "Stop guards became main execution loop."

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

Assert-True ($payload.invoked_runners.live_backend_watch.not_execution_controller -eq $true) "Live backend watch became an execution controller."
Assert-True ($payload.invoked_runners.durable_parallel_wave_packet.poll_refs.poll_blocks_dispatch -eq $false) "Live backend poll still blocks source-frontier dispatch."
Assert-True ($payload.invoked_runners.source_anchor_gap_continuation.continue_dispatch_expected -eq $false) "Source anchor slicing freeze boundary changed unexpectedly."
Assert-True ($payload.invoked_runners.durable_parallel_wave_packet.continue_dispatch_expected -eq $true) "Durable packet did not allow continuation."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_evidence_only -eq $true) "Runtime preflight refs were not evidence-only."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_not_stop_guard_layers -eq $true) "Runtime preflight refs became Stop guard layers."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_not_completion_gates -eq $true) "Runtime preflight refs became completion gates."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_not_execution_controllers -eq $true) "Runtime preflight refs became execution controllers."
$sourceSurface = $payload.runtime_preflight_refs.source_frontier_fanin_acceptance_surface
Assert-True ($sourceSurface.task_id -eq "wave3_20260702_absorption_slice_20260704") "Source frontier slice task_id mismatch."
Assert-True ($sourceSurface.parent_task_id -eq "xinao_seed_cortex_phase0_20260701") "Source frontier parent_task_id mismatch."
Assert-True ($sourceSurface.routing -eq "continue_same_task") "Source frontier routing mismatch."
Assert-True ($sourceSurface.fan_in_acceptance_queue_default_heart -eq $true) "Source frontier did not bind FanIn as default heart."
Assert-True ($sourceSurface.provider_scheduler_main_task -eq $false) "Source frontier still treats ProviderScheduler as main task."
Assert-True (($sourceSurface.source_package_gap_open -is [bool]) -or ($sourceSurface.source_package_gap_open -is [System.Boolean])) "Source frontier gap was not a boolean."
Assert-True ($sourceSurface.runtime_enforced -eq $false) "Source frontier overclaimed runtime enforcement."
Assert-True ($sourceSurface.trigger_installed -eq $false) "Source frontier installed trigger."
Assert-True ($sourceSurface.validation_passed -eq $true) "Source frontier surface validation failed."
Assert-True ($sourceSurface.not_execution_controller -eq $true) "Source frontier surface became execution controller."
$correctionSurface = $payload.runtime_preflight_refs.seed_lab_user_correction_runtime_surface
$allocationSurface = $payload.runtime_preflight_refs.allocation_plan
$prePassSurface = $payload.runtime_preflight_refs.pre_pass_audit_loop
Assert-True ($correctionSurface.invoked_by_main_execution_loop_tick -eq $true) "User correction runtime surface was not prepared by main loop tick."
Assert-True ($correctionSurface.refs_ready_for_durable_packet -eq $true) "User correction runtime refs are not ready for durable packet."
Assert-True ($correctionSurface.runtime_enforced -eq $false) "User correction runtime surface overclaimed runtime enforcement."
Assert-True ($correctionSurface.trigger_installed -eq $false) "User correction runtime surface installed trigger."
Assert-True ($correctionSurface.memory_promotion_allowed -eq $false) "User correction runtime surface allowed memory promotion."
Assert-True ($correctionSurface.policy_promotion_allowed -eq $false) "User correction runtime surface allowed policy promotion."
Assert-True ($correctionSurface.completion_claim_allowed -eq $false) "User correction runtime surface allowed completion claim."
Assert-True ($correctionSurface.not_execution_controller -eq $true) "User correction runtime surface became execution controller."
Assert-True ($allocationSurface.invoked_by_main_execution_loop_tick -eq $true) "AllocationPlan was not invoked by main loop tick."
Assert-True ($allocationSurface.target_width_source -eq "derived_from_runtime_feedback_inputs") "AllocationPlan width was not derived."
Assert-True ($allocationSurface.fixed_20_or_50_used -eq $false) "AllocationPlan used fixed 20/50 width."
Assert-True ($allocationSurface.completion_claim_allowed -eq $false) "AllocationPlan allowed completion claim."
Assert-True ($allocationSurface.not_execution_controller -eq $true) "AllocationPlan became execution controller."
Assert-True ($allocationSurface.validation_passed -eq $true) "AllocationPlan validation failed."
Assert-True ($prePassSurface.invoked_by_main_execution_loop_tick -eq $true) "Pre-PASS audit loop was not invoked by main loop tick."
Assert-True ($prePassSurface.completion_claim_allowed -eq $false) "Pre-PASS audit loop allowed completion claim."
Assert-True ($prePassSurface.not_execution_controller -eq $true) "Pre-PASS audit loop became execution controller."
Assert-True ($prePassSurface.validation_passed -eq $true) "Pre-PASS audit loop validation failed."
Assert-True ($payload.actual_dispatch_refs.codex_subagents.Count -ge 2) "Subagent refs were not bound."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution.default_lane_count -eq 20) "DP sidecar default lane count was not 20."
Assert-True ($payload.fan_in_refs.Count -ge 2) "Fan-in refs missing."
Assert-True ($payload.evidence_refs.Count -ge 4) "Evidence refs missing."
Assert-True ($payload.next_wave_decision.continue_main_loop -eq $true) "Main loop did not preserve continuation."
Assert-True ($payload.next_wave_decision.decision -eq "dispatch_repair_plan") "Pre-PASS repair plan did not take the next wave."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.next_wave_decision.pre_pass_repair_plan_ref)) "Pre-PASS repair plan ref missing."
if ($sourceSurface.source_package_gap_open -eq $false) {
    $sourceFamilySurface = $payload.runtime_preflight_refs.source_family_wave_scheduler_surface
    Assert-True ($sourceFamilySurface.task_id -eq "wave4_20260701_frontier_source_family_20260704") "Source family wave task_id mismatch."
    Assert-True ($sourceFamilySurface.validation_passed -eq $true) "Source family wave scheduler surface validation failed."
    Assert-True ([int]$sourceFamilySurface.source_family_count -ge 5) "Source family wave did not cover enough source families."
}
Assert-True ([string]::IsNullOrWhiteSpace([string]$payload.next_wave_decision.named_blocker)) "Main loop still reports a poll blocker."
Assert-True ($payload.validation.passed -eq $true) "Main loop tick validation failed."
Assert-True ($payload.validation.checks.source_frontier_fanin_acceptance_surface_prepared -eq $true) "Source frontier fan-in surface validation failed."
Assert-True ($payload.validation.checks.seed_lab_user_correction_runtime_surface_prepared -eq $true) "User correction runtime surface validation failed."
Assert-True ($payload.validation.checks.allocation_plan_prepared -eq $true) "AllocationPlan validation failed."
Assert-True ($payload.validation.checks.pre_pass_audit_loop_prepared -eq $true) "Pre-PASS audit loop validation failed."
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
Assert-True ($readbackText.Contains("source_frontier_fanin_acceptance_surface_prepared")) "Readback missing source frontier surface."
Assert-True ($readbackText.Contains("allocation_plan_prepared")) "Readback missing AllocationPlan surface."
Assert-True ($readbackText.Contains("pre_pass_audit_loop_prepared")) "Readback missing Pre-PASS surface."
Assert-True ($readbackText.Contains("SENTINEL:XINAO_CODEX_S_MAIN_EXECUTION_LOOP_TICK_READY")) "Readback missing sentinel."

Write-Output "codex_s_main_execution_loop_tick_latest=$latestPath"
Write-Output "codex_s_main_execution_loop_tick_readback=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_CODEX_S_MAIN_EXECUTION_LOOP_TICK_READY"
