$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
$anchorRoot = Join-Path (Join-Path $env:USERPROFILE "Desktop") (
    [string]([char]0x65B0) + [string]([char]0x7CFB) + [string]([char]0x7EDF)
)
$env:PYTHONPATH = "$repoRoot\src;$repoRoot"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\default_main_loop_trigger_candidate.py"
$servicePath = Join-Path $repoRoot "src\xinao_seedlab\application\seed_cortex.py"
$cliPath = Join-Path $repoRoot "src\xinao_seedlab\cli\__main__.py"
$apiPath = Join-Path $repoRoot "src\xinao_seedlab\adapters\fastapi_app.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_default_main_loop_trigger_candidate.py"
$fastApiTestPath = Join-Path $repoRoot "tests\seedcortex\test_fastapi_api_contract.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_default_main_loop_trigger_candidate.v1.json"

$compileTargets = @($modulePath, $servicePath, $cliPath)
if (Test-Path -LiteralPath $apiPath -PathType Leaf) {
    $compileTargets += $apiPath
}
python -m py_compile $compileTargets
Assert-True ($LASTEXITCODE -eq 0) "Default main loop trigger candidate py_compile failed."

$pytestTargets = @($testPath)
if (Test-Path -LiteralPath $fastApiTestPath -PathType Leaf) {
    $pytestTargets += "$fastApiTestPath::test_fastapi_routes_match_contract_when_dependency_is_installed"
    $pytestTargets += "$fastApiTestPath::test_fastapi_adapter_delegates_to_service_without_toy_defaults"
}
python -m pytest -q $pytestTargets
Assert-True ($LASTEXITCODE -eq 0) "Default main loop trigger candidate pytest failed."

$schemaCheck = @'
from pathlib import Path
import json
schema = json.loads(Path("contracts/schemas/codex_s_default_main_loop_trigger_candidate.v1.json").read_text(encoding="utf-8"))
assert schema["properties"]["schema_version"]["const"] == "xinao.codex_s.default_main_loop_trigger_candidate.v1"
assert schema["properties"]["sentinel"]["const"] == "SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY"
assert schema["properties"]["adoption_state"]["const"] == "runtime_trigger_candidate_verifier_ready"
assert "adoption_state_boundary" in schema["required"]
assert "user_correction_runtime_refs" in schema["required"]
assert "scheduler_lane_evidence_refs" in schema["required"]
assert "scheduler_spawned_lane_evidence_refs" in schema["required"]
assert schema["properties"]["target_user_correction_runtime_service_method"]["const"] == "SeedCortexService.seed_lab_user_correction_runtime"
assert schema["properties"]["target_user_correction_runtime_fastapi_route"]["const"] == "POST /runtime/seed-lab-user-correction-runtime"
assert schema["properties"]["target_user_correction_runtime_cli_command"]["const"].endswith("seed-lab-user-correction-runtime")
assert schema["properties"]["user_correction_runtime_api_cli_adoption_state"]["const"] == "api_cli_verifier_ready_not_hook_enforced"
user_correction = schema["properties"]["user_correction_runtime_refs"]["properties"]
assert user_correction["invoked_by_default_trigger"]["const"] is False
assert user_correction["runtime_enforced"]["const"] is False
assert user_correction["trigger_installed"]["const"] is False
assert user_correction["memory_promotion_allowed"]["const"] is False
assert user_correction["policy_promotion_allowed"]["const"] is False
assert user_correction["completion_claim_allowed"]["const"] is False
assert user_correction["refs_are_not_execution_controllers"]["const"] is True
scheduler_refs = schema["properties"]["scheduler_lane_evidence_refs"]["properties"]
assert scheduler_refs["bound_for_discovery_only"]["const"] is True
assert scheduler_refs["spawned_by_this_runner"]["const"] is False
assert scheduler_refs["default_runtime_scheduler_invoked"]["const"] is False
assert scheduler_refs["runtime_enforced"]["const"] is False
assert scheduler_refs["trigger_installed"]["const"] is False
assert scheduler_refs["refs_are_evidence_only"]["const"] is True
assert scheduler_refs["refs_are_not_completion_gates"]["const"] is True
assert scheduler_refs["refs_are_not_execution_controllers"]["const"] is True
actual_dispatch = schema["properties"]["actual_dispatch_refs"]
for field in (
    "dp_sidecar_execution_port_runner_ref",
    "dp_sidecar_execution_provider_ref",
    "dp_sidecar_execution_provider_manifest_ref",
    "dp_sidecar_execution_callable_entrypoint_bound",
):
    assert field in actual_dispatch["required"]
assert actual_dispatch["properties"]["dp_sidecar_execution_callable_entrypoint_bound"]["const"] is True
spawned_refs = schema["properties"]["scheduler_spawned_lane_evidence_refs"]["properties"]
assert spawned_refs["candidate_discovery_scope"]["const"] == "default_main_loop_trigger_candidate_ref_discovery_only"
assert spawned_refs["current_wave_lane_evidence_state"]["const"] == "parent_scheduler_invoked_with_lane_refs_not_default_runtime"
assert spawned_refs["activity_scoped_lane_evidence_state"]["const"] == "activity_scheduler_invoked_with_lane_refs_not_default_runtime"
assert spawned_refs["codex_lane_evidence_discovered"]["const"] is True
assert spawned_refs["dp_sidecar_execution_modes_discovered"]["const"] is True
assert spawned_refs["current_wave_dp_sidecar_execution_lanes_present"]["const"] is True
assert spawned_refs["current_wave_immutable_ref_exists"]["const"] is True
assert spawned_refs["current_wave_immutable_digest_bound"]["const"] is True
for field in (
    "current_wave_runtime_wave_record",
    "current_wave_runtime_wave_record_digest_sha256",
    "current_wave_selected_runtime_latest",
):
    assert field in schema["properties"]["scheduler_spawned_lane_evidence_refs"]["required"]
assert spawned_refs["dp_sidecar_execution_lanes_spawned"]["const"] is False
assert spawned_refs["default_runtime_scheduler_invoked"]["const"] is False
assert spawned_refs["runtime_enforced"]["const"] is False
assert spawned_refs["trigger_installed"]["const"] is False
assert spawned_refs["refs_are_evidence_only"]["const"] is True
assert spawned_refs["refs_are_not_completion_gates"]["const"] is True
assert spawned_refs["refs_are_not_execution_controllers"]["const"] is True
boundary = schema["properties"]["adoption_state_boundary"]["properties"]
assert boundary["adoption_state"]["const"] == "runtime_trigger_candidate_verifier_ready"
assert boundary["scope"]["const"] == "default_main_loop_trigger_candidate_only"
assert boundary["state_is_scoped_candidate"]["const"] is True
assert boundary["not_global_runtime_enforcement"]["const"] is True
assert boundary["not_global_default_trigger"]["const"] is True
assert boundary["runtime_enforced"]["const"] is False
assert boundary["trigger_installed"]["const"] is False
assert schema["properties"]["runtime_enforced"]["const"] is False
assert schema["properties"]["temporal_enforced"]["const"] is False
assert schema["properties"]["trigger_installed"]["const"] is False
assert schema["properties"]["stop_guard_layers_are_main_execution_loop"]["const"] is False
assert schema["properties"]["not_execution_controller"]["const"] is True
for field in (
    "scheduler_spawned_lane_evidence_current_wave_immutable",
    "scheduler_spawned_lane_evidence_current_wave_immutable_digest_sha256",
    "dp_sidecar_execution_port_runner_latest",
    "dp_sidecar_execution_provider_latest",
    "dp_sidecar_execution_provider_manifest",
):
    assert field in schema["properties"]["evidence_refs"]["required"]
print("default_main_loop_trigger_candidate_schema=OK")
'@
$schemaCheck | python -
Assert-True ($LASTEXITCODE -eq 0) "Default main loop trigger candidate schema check failed."

& (Join-Path $repoRoot "scripts\verify_dp_sidecar_execution_provider.ps1") | Out-Host
Assert-True ($LASTEXITCODE -eq 0) "DP sidecar execution provider prerequisite failed."

$dpPortRunnerVerifier = Join-Path $repoRoot "scripts\verify_dp_sidecar_execution_port_runner.ps1"
if (Test-Path -LiteralPath $dpPortRunnerVerifier -PathType Leaf) {
    & $dpPortRunnerVerifier | Out-Host
    Assert-True ($LASTEXITCODE -eq 0) "DP sidecar execution port runner prerequisite failed."
}

$temporalSchedulerVerifier = Join-Path $repoRoot "scripts\verify_temporal_scheduler_invocation_packet_activity.ps1"
if (Test-Path -LiteralPath $temporalSchedulerVerifier -PathType Leaf) {
    & $temporalSchedulerVerifier | Out-Host
    Assert-True ($LASTEXITCODE -eq 0) "Temporal scheduler invocation packet activity prerequisite failed."
}

$schedulerOutput = python (Join-Path $repoRoot "services\agent_runtime\scheduler_invocation_packet.py") `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --spawned-lane "current_parent_codex_subagent:verify-default-trigger-codex-lane-001" `
    --spawned-lane "dp_sidecar_execution:verify-default-trigger-dp-lane-001" `
    --current-parent-codex-invocation-ref "current_parent_codex_dispatch:verify-default-trigger-wave" `
    --dp-launcher-ref "deepseek-dp-launcher:verify-default-trigger-wave"
$schedulerExitCode = $LASTEXITCODE
if ($schedulerExitCode -ne 0) {
    $schedulerOutput | ForEach-Object { Write-Output $_ }
}
Assert-True ($schedulerExitCode -eq 0) "Scheduler invocation packet current-wave generation failed."
$schedulerLatest = Join-Path $runtimeRoot "state\scheduler_invocation_packet\latest.json"
$currentWaveLatest = Join-Path $runtimeRoot "state\scheduler_spawned_lane_evidence\current_wave_latest.json"
$laneEvidenceOutput = python (Join-Path $repoRoot "services\agent_runtime\scheduler_spawned_lane_evidence.py") `
    --repo-root $repoRoot `
    --runtime-root $runtimeRoot `
    --scheduler-invocation-ref $schedulerLatest `
    --output-latest $currentWaveLatest
$laneEvidenceExitCode = $LASTEXITCODE
if ($laneEvidenceExitCode -ne 0) {
    $laneEvidenceOutput | ForEach-Object { Write-Output $_ }
}
Assert-True ($laneEvidenceExitCode -eq 0) "Scheduler current-wave lane evidence generation failed."
Assert-True (Test-Path -LiteralPath $currentWaveLatest -PathType Leaf) "Scheduler current-wave latest missing."

$output = python -m xinao_seedlab.cli.__main__ default-main-loop-trigger-candidate `
    --runtime-root $runtimeRoot `
    --anchor-package-root $anchorRoot `
    --codex-subagent "019f22a3-13b1-73d3-8f81-1b36cc635c23:worker_dispatch_ledger" `
    --codex-subagent "019f22a3-141d-7311-bf78-69a37f9db88e:hot_path_probe"
$generationExitCode = $LASTEXITCODE
if ($generationExitCode -ne 0) {
    $output | ForEach-Object { Write-Output $_ }
}
Assert-True ($generationExitCode -eq 0) "Default main loop trigger candidate CLI generation failed."
$text = $output -join "`n"
Assert-True ($text.Contains("SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY")) "Trigger candidate sentinel missing."
Assert-True ($text.Contains("runtime_trigger_candidate_verifier_ready")) "Trigger candidate adoption state missing."

$latest = Join-Path $runtimeRoot "state\default_main_loop_trigger_candidate\latest.json"
$serviceLatest = Join-Path $runtimeRoot "state\default_main_loop_trigger_candidate\service_entrypoint_latest.json"
$readback = Join-Path $runtimeRoot "readback\zh\default_main_loop_trigger_candidate_20260702.md"
$serviceReadback = Join-Path $runtimeRoot "readback\zh\default_main_loop_trigger_candidate_service_entrypoint_20260702.md"
Assert-True (Test-Path -LiteralPath $latest -PathType Leaf) "Default trigger candidate latest missing."
Assert-True (Test-Path -LiteralPath $serviceLatest -PathType Leaf) "Default trigger candidate service latest missing."
Assert-True (Test-Path -LiteralPath $readback -PathType Leaf) "Default trigger candidate readback missing."
Assert-True (Test-Path -LiteralPath $serviceReadback -PathType Leaf) "Default trigger candidate service readback missing."

$payload = Get-Content -LiteralPath $serviceLatest -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.default_main_loop_trigger_candidate.v1") "Trigger candidate schema mismatch."
Assert-True ($payload.status -eq "default_main_loop_trigger_candidate_verifier_ready") "Trigger candidate not verifier ready."
Assert-True ($payload.adoption_state -eq "runtime_trigger_candidate_verifier_ready") "Trigger candidate adoption mismatch."
Assert-True ($payload.adoption_state_boundary.adoption_state -eq "runtime_trigger_candidate_verifier_ready") "Trigger candidate adoption boundary mismatch."
Assert-True ($payload.adoption_state_boundary.scope -eq "default_main_loop_trigger_candidate_only") "Trigger candidate adoption boundary scope mismatch."
Assert-True ($payload.adoption_state_boundary.state_is_scoped_candidate -eq $true) "Trigger candidate adoption boundary did not mark scoped candidate."
Assert-True ($payload.adoption_state_boundary.not_global_runtime_enforcement -eq $true) "Trigger candidate adoption boundary overclaimed global runtime enforcement."
Assert-True ($payload.adoption_state_boundary.not_global_default_trigger -eq $true) "Trigger candidate adoption boundary overclaimed global default trigger."
Assert-True ($payload.adoption_state_boundary.runtime_enforced -eq $false) "Trigger candidate adoption boundary overclaimed runtime enforcement."
Assert-True ($payload.adoption_state_boundary.trigger_installed -eq $false) "Trigger candidate adoption boundary overclaimed trigger installation."
Assert-True ($payload.runtime_enforced -eq $false) "Trigger candidate overclaimed runtime enforcement."
Assert-True ($payload.temporal_enforced -eq $false) "Trigger candidate overclaimed Temporal enforcement."
Assert-True ($payload.trigger_installed -eq $false) "Trigger candidate claimed trigger installed."
Assert-True ($payload.stop_hook_controller -eq $false) "Trigger candidate became Stop hook controller."
Assert-True ($payload.stop_hook_dispatches_main_execution_loop -eq $false) "Stop hook dispatch overclaim."
Assert-True ($payload.is_stop_guard_layer -eq $false) "Trigger candidate became Stop guard layer."
Assert-True ($payload.is_completion_gate -eq $false) "Trigger candidate became completion gate."
Assert-True ($payload.stop_guard_layers_are_main_execution_loop -eq $false) "Stop guard layers became main execution loop."
Assert-True ($payload.base_tick_adoption_state -eq "verifier_ready_but_not_hooked") "Base tick adoption state changed."
Assert-True ($payload.api_cli_adoption_state -eq "api_cli_verifier_ready_not_hook_enforced") "API/CLI adoption state mismatch."
Assert-True ($payload.target_user_correction_runtime_service_method -eq "SeedCortexService.seed_lab_user_correction_runtime") "User correction runtime target service method mismatch."
Assert-True ($payload.target_user_correction_runtime_fastapi_route -eq "POST /runtime/seed-lab-user-correction-runtime") "User correction runtime target FastAPI route mismatch."
Assert-True ($payload.target_user_correction_runtime_cli_command -like "*seed-lab-user-correction-runtime") "User correction runtime target CLI command mismatch."
Assert-True ($payload.user_correction_runtime_api_cli_adoption_state -eq "api_cli_verifier_ready_not_hook_enforced") "User correction runtime API/CLI adoption state mismatch."
Assert-True ($payload.service_entrypoint.caller -eq "SeedCortexService.default_main_loop_trigger_candidate") "Service caller missing."
Assert-True ($payload.service_entrypoint.api_cli_adoption_state -eq "api_cli_verifier_ready_not_hook_enforced") "Service API/CLI adoption mismatch."
Assert-True ($payload.service_entrypoint.runtime_enforced -eq $false) "Service overclaimed runtime enforcement."
Assert-True ($payload.service_entrypoint.temporal_enforced -eq $false) "Service overclaimed Temporal enforcement."
Assert-True ($payload.service_entrypoint.trigger_installed -eq $false) "Service claimed trigger installed."
Assert-True ($payload.service_entrypoint.shared_latest_ref_is_base_runner_view -eq $true) "Service latest boundary missing."
Assert-True ($payload.actual_dispatch_refs.codex_subagent_count -ge 2) "Actual dispatch refs missing subagents."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_callable_entrypoint_bound -eq $true) "Actual dispatch refs missing DP callable entrypoint binding."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_port_runner_ref.exists -eq $true) "Actual dispatch refs missing DP runner ref."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_provider_ref.exists -eq $true) "Actual dispatch refs missing DP provider ref."
Assert-True ($payload.actual_dispatch_refs.dp_sidecar_execution_provider_manifest_ref.exists -eq $true) "Actual dispatch refs missing DP provider manifest ref."
Assert-True ($payload.actual_dispatch_refs.refs_are_not_execution_controllers -eq $true) "Actual dispatch refs became controller."
Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.gateway_provider_id -eq "codex_s.modular_dynamic_worker_pool_phase1") "Phase1 Gateway provider id mismatch."
Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.gateway_provider_visible -eq $true) "Phase1 Gateway provider not visible."
Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.hot_path_shape -eq "parallel_draft->merge->writer") "Phase1 hot path shape mismatch."
Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.dp_worker_role -eq "draft_main_worker_pool") "Phase1 DP worker role mismatch."
$phase1GlobalDefaultPath = Join-Path $runtimeRoot "state\modular_dynamic_worker_pool_phase1\global_default\latest.json"
$phase1GlobalDefault = $null
if (Test-Path -LiteralPath $phase1GlobalDefaultPath -PathType Leaf) {
    $phase1GlobalDefault = Get-Content -LiteralPath $phase1GlobalDefaultPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
$phase1GlobalDefaultPassed = (
    $null -ne $phase1GlobalDefault `
    -and $phase1GlobalDefault.validation.passed -eq $true `
    -and $phase1GlobalDefault.runtime_enforced -eq $true
)
if ($phase1GlobalDefaultPassed) {
    Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.gateway_provider_runtime_enforced -eq $true) "Phase1 Gateway provider should be runtime_enforced after global default freeze."
    Assert-True ([string]$payload.modular_dynamic_worker_pool_phase1_trigger_binding.gateway_provider_adoption_state -eq "runtime_enforced_global_default") "Phase1 Gateway adoption state mismatch after global default freeze."
    Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.runtime_enforced -eq $true) "Phase1 trigger binding did not reflect runtime enforcement."
    Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.trigger_installed -eq $true) "Phase1 trigger binding did not reflect installed trigger."
} else {
    Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.runtime_enforced -eq $false) "Phase1 trigger binding overclaimed runtime enforcement."
    Assert-True ($payload.modular_dynamic_worker_pool_phase1_trigger_binding.trigger_installed -eq $false) "Phase1 trigger binding overclaimed trigger installation."
}
Assert-True ($payload.poll_refs.live_backend_watch_ref.exists -eq $true) "Poll ref missing live backend watch."
Assert-True ($payload.fan_in_refs.artifact_acceptance_queue_ref.exists -eq $true) "Fan-in ref missing artifact acceptance queue."
Assert-True ($payload.validation.passed -eq $true) "Trigger candidate validation failed."
Assert-True ($payload.validation.checks.metaminute_before_new_parallel_wave_invoked -eq $true) "MetaMinute trigger missing."
Assert-True ($payload.validation.checks.main_loop_service_invoked -eq $true) "Main loop service invocation missing."
Assert-True ($payload.validation.checks.durable_packet_service_invoked -eq $true) "Durable packet service invocation missing."
Assert-True ($payload.validation.checks.user_correction_runtime_refs_bound -eq $true) "User correction runtime refs not bound."
Assert-True ($payload.validation.checks.user_correction_runtime_not_enforced -eq $true) "User correction runtime non-enforcement validation failed."
Assert-True ($payload.validation.checks.capability_gateway_providers_visible -eq $true) "Gateway provider refs missing."
Assert-True ($payload.validation.checks.modular_dynamic_worker_pool_phase1_provider_visible -eq $true) "Modular dynamic worker pool phase1 provider missing from Gateway."
Assert-True ($payload.validation.checks.scheduler_gateway_capabilities_visible -eq $true) "Scheduler Gateway capability refs missing."
Assert-True ($payload.validation.checks.scheduler_current_wave_evidence_bound -eq $true) "Scheduler current-wave evidence not bound."
Assert-True ($payload.validation.checks.scheduler_activity_scoped_evidence_bound -eq $true) "Scheduler activity-scoped evidence not bound."
Assert-True ($payload.validation.checks.scheduler_lane_refs_non_overclaiming -eq $true) "Scheduler lane refs overclaimed runtime/default state."
Assert-True ($payload.validation.checks.scheduler_spawned_lane_evidence_refs_bound -eq $true) "Scheduler spawned lane evidence refs alias not bound."
Assert-True ($payload.validation.checks.scheduler_current_wave_immutable_ref_bound -eq $true) "Scheduler current-wave immutable evidence ref not bound."
Assert-True ($payload.validation.checks.scheduler_spawned_lane_current_wave_found -eq $true) "Scheduler current-wave alias state missing."
Assert-True ($payload.validation.checks.scheduler_spawned_lane_activity_scoped_found -eq $true) "Scheduler activity-scoped alias state missing."
Assert-True ($payload.validation.checks.codex_lane_evidence_discovered_by_candidate -eq $true) "Codex lane evidence alias not discovered."
Assert-True ($payload.validation.checks.dp_sidecar_execution_modes_discovered_by_candidate -eq $true) "DP sidecar modes alias not discovered."
Assert-True ($payload.validation.checks.dp_sidecar_execution_callable_refs_bound -eq $true) "DP callable refs not bound."
Assert-True ($payload.validation.checks.scheduler_spawned_lane_evidence_not_default_runtime -eq $true) "Scheduler spawned lane alias overclaimed default runtime."
Assert-True ($payload.validation.checks.max_benefit_refs_visible -eq $true) "Max benefit refs missing."
Assert-True ($payload.validation.checks.actual_dispatch_refs_bound -eq $true) "Actual dispatch refs not bound."
Assert-True ($payload.validation.checks.poll_refs_bound -eq $true) "Poll refs not bound."
Assert-True ($payload.validation.checks.fan_in_refs_bound -eq $true) "Fan-in refs not bound."
Assert-True ($payload.validation.checks.adoption_state_boundary_scoped_candidate -eq $true) "Adoption boundary scoped-candidate check failed."
Assert-True ($payload.user_correction_runtime_refs.service_entrypoint_ref.exists -eq $true) "User correction runtime service ref missing."
Assert-True ($payload.user_correction_runtime_refs.service_entrypoint_ref.schema_version -eq "xinao.codex_s.seed_lab_user_correction_runtime.v1") "User correction runtime schema mismatch."
Assert-True ($payload.user_correction_runtime_refs.correction_intake_ref.exists -eq $true) "CorrectionIntake ref missing."
Assert-True ($payload.user_correction_runtime_refs.experiment_review_view_ref.exists -eq $true) "ExperimentReviewView ref missing."
Assert-True ($payload.user_correction_runtime_refs.replay_court_ref.exists -eq $true) "ReplayCourt ref missing."
Assert-True ($payload.user_correction_runtime_refs.explicit_service_api_candidate -eq $true) "User correction runtime explicit service/API candidate missing."
Assert-True ($payload.user_correction_runtime_refs.invoked_by_default_trigger -eq $false) "Default trigger invoked user correction runtime."
Assert-True ($payload.user_correction_runtime_refs.runtime_enforced -eq $false) "User correction runtime overclaimed runtime enforcement."
Assert-True ($payload.user_correction_runtime_refs.trigger_installed -eq $false) "User correction runtime installed a trigger."
Assert-True ($payload.user_correction_runtime_refs.memory_promotion_allowed -eq $false) "User correction runtime allowed memory promotion."
Assert-True ($payload.user_correction_runtime_refs.policy_promotion_allowed -eq $false) "User correction runtime allowed policy promotion."
Assert-True ($payload.user_correction_runtime_refs.completion_claim_allowed -eq $false) "User correction runtime allowed completion claim."
Assert-True ($payload.user_correction_runtime_refs.refs_are_not_execution_controllers -eq $true) "User correction runtime refs became controllers."
Assert-True ($payload.scheduler_lane_evidence_refs.bound_for_discovery_only -eq $true) "Scheduler lane refs were not discovery-only."
Assert-True ($payload.scheduler_lane_evidence_refs.spawned_by_this_runner -eq $false) "Default trigger claimed it spawned scheduler lanes."
Assert-True ($payload.scheduler_lane_evidence_refs.runtime_enforced -eq $false) "Scheduler lane refs overclaimed runtime enforcement."
Assert-True ($payload.scheduler_lane_evidence_refs.default_runtime_scheduler_invoked -eq $false) "Scheduler lane refs overclaimed default runtime scheduler."
Assert-True ($payload.scheduler_lane_evidence_refs.trigger_installed -eq $false) "Scheduler lane refs installed trigger."
Assert-True ($payload.scheduler_lane_evidence_refs.refs_are_not_execution_controllers -eq $true) "Scheduler lane refs became controllers."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_invocation_packet_latest.exists -eq $true) "Scheduler invocation packet ref missing."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_invocation_packet_service_latest.exists -eq $true) "Scheduler invocation packet service ref missing."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.exists -eq $true) "Scheduler current-wave evidence ref missing."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.scheduler_invoked -eq $true) "Scheduler current-wave evidence did not record invocation."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.parent_dispatch_invoked -eq $true) "Scheduler current-wave evidence did not record parent dispatch."
Assert-True ([int]$payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.scheduler_spawned_lane_count -ge 2) "Scheduler current-wave evidence lane count too low."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.dp_sidecar_execution_lanes_spawned -eq $true) "Scheduler current-wave evidence missing DP execution lane."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.default_runtime_scheduler_invoked -eq $false) "Scheduler current-wave evidence overclaimed default runtime scheduler."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_current_wave.runtime_enforced -eq $false) "Scheduler current-wave evidence overclaimed runtime enforcement."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_activity_scoped.exists -eq $true) "Scheduler activity-scoped evidence ref missing."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_activity_scoped.activity_scope_scheduler_invoked -eq $true) "Scheduler activity-scoped evidence did not record activity scope."
Assert-True ($payload.scheduler_lane_evidence_refs.scheduler_spawned_lane_evidence_activity_scoped.default_runtime_scheduler_invoked -eq $false) "Scheduler activity evidence overclaimed default scheduler."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.current_wave_latest_ref.path -eq $currentWaveLatest) "Current-wave scheduler lane evidence alias ref mismatch."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.activity_scoped_latest_ref.path -like "*scheduler_spawned_lane_evidence*activity_scoped_latest.json") "Activity-scoped scheduler lane evidence alias ref missing."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.candidate_discovery_scope -eq "default_main_loop_trigger_candidate_ref_discovery_only") "Scheduler spawned lane alias discovery scope mismatch."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.current_wave_lane_evidence_state -eq "parent_scheduler_invoked_with_lane_refs_not_default_runtime") "Scheduler current-wave alias state mismatch."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.activity_scoped_lane_evidence_state -eq "activity_scheduler_invoked_with_lane_refs_not_default_runtime") "Scheduler activity alias state mismatch."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.codex_lane_evidence_discovered -eq $true) "Codex lane evidence alias missing."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.dp_sidecar_execution_modes_discovered -eq $true) "DP sidecar mode alias missing."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.current_wave_dp_sidecar_execution_lanes_present -eq $true) "DP sidecar current-wave lane alias missing."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.current_wave_immutable_ref_exists -eq $true) "Scheduler current-wave immutable ref missing."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.current_wave_immutable_digest_bound -eq $true) "Scheduler current-wave immutable digest missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$payload.scheduler_spawned_lane_evidence_refs.current_wave_runtime_wave_record)) "Scheduler current-wave runtime wave record missing."
Assert-True (([string]$payload.scheduler_spawned_lane_evidence_refs.current_wave_runtime_wave_record_digest_sha256).Length -eq 64) "Scheduler current-wave runtime wave digest malformed."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.current_wave_selected_runtime_latest -eq $currentWaveLatest) "Scheduler current-wave selected runtime latest mismatch."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.dp_sidecar_execution_lanes_spawned -eq $false) "Default trigger alias claimed DP lanes spawned by trigger."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.default_runtime_scheduler_invoked -eq $false) "Scheduler spawned lane alias overclaimed default scheduler."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.runtime_enforced -eq $false) "Scheduler spawned lane alias overclaimed runtime enforcement."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.trigger_installed -eq $false) "Scheduler spawned lane alias installed trigger."
Assert-True ($payload.scheduler_spawned_lane_evidence_refs.refs_are_not_execution_controllers -eq $true) "Scheduler spawned lane alias became controller."
$schedulerProviderKinds = @()
foreach ($provider in @($payload.scheduler_lane_evidence_refs.capability_gateway_scheduler_lane_providers)) {
    $schedulerProviderKinds += @($provider.matched_capability_kinds)
    Assert-True ($provider.runtime_enforced -ne $true) "Scheduler Gateway provider overclaimed runtime enforcement."
    Assert-True ($provider.default_runtime_scheduler_invoked -ne $true) "Scheduler Gateway provider overclaimed default runtime scheduler."
    Assert-True ($provider.provider_invocation_performed -ne $true) "Scheduler Gateway provider invoked provider during discovery."
}
Assert-True ($schedulerProviderKinds -contains "activity_scoped_scheduler_lane_evidence") "Gateway missing activity-scoped scheduler lane capability."
Assert-True ($schedulerProviderKinds -contains "actual_subagent_dispatch_evidence") "Gateway missing actual subagent dispatch evidence capability."
Assert-True ($payload.evidence_refs.seed_lab_user_correction_runtime_service_latest -like "*seed_lab_user_correction_runtime*service_entrypoint_latest.json") "User correction runtime evidence ref missing."
Assert-True ($payload.evidence_refs.seed_lab_replay_court_latest -like "*seed_lab_replay_court*latest.json") "ReplayCourt evidence ref missing."
Assert-True ($payload.evidence_refs.scheduler_invocation_packet_latest -like "*scheduler_invocation_packet*latest.json") "Scheduler invocation evidence ref missing."
Assert-True ($payload.evidence_refs.scheduler_spawned_lane_evidence_current_wave_latest -like "*scheduler_spawned_lane_evidence*current_wave_latest.json") "Scheduler current-wave evidence ref path missing."
Assert-True ($payload.evidence_refs.scheduler_spawned_lane_evidence_current_wave_immutable -like "*scheduler_spawned_lane_evidence*waves*") "Scheduler current-wave immutable evidence ref path missing."
Assert-True (([string]$payload.evidence_refs.scheduler_spawned_lane_evidence_current_wave_immutable_digest_sha256).Length -eq 64) "Scheduler current-wave immutable digest evidence missing."
Assert-True ($payload.evidence_refs.scheduler_spawned_lane_evidence_activity_scoped_latest -like "*scheduler_spawned_lane_evidence*activity_scoped_latest.json") "Scheduler activity evidence ref path missing."
Assert-True ($payload.evidence_refs.dp_sidecar_execution_port_runner_latest -like "*dp_sidecar_execution_port*latest.json") "DP runner latest evidence ref missing."
Assert-True ($payload.evidence_refs.dp_sidecar_execution_provider_latest -like "*dp_sidecar_execution_provider*latest.json") "DP provider latest evidence ref missing."
Assert-True ($payload.evidence_refs.dp_sidecar_execution_provider_manifest -like "*legacy.deepseek_dp_sidecar.dp_sidecar_execution_port*manifest.json") "DP provider manifest evidence ref missing."
Assert-True ($payload.readback_refs.seed_lab_user_correction_runtime_service_readback -like "*seed_lab_user_correction_runtime_service_entrypoint_20260702.md") "User correction runtime readback ref missing."
Assert-True ($payload.completion_claim_allowed -eq $false) "Completion claim was allowed."
Assert-True ($payload.phase1_data_chain_allowed -eq $false) "Phase1 data chain was allowed."
Assert-True ($payload.positive_ev_claim_allowed -eq $false) "Positive-EV claim was allowed."
Assert-True ($payload.not_execution_controller -eq $true) "Trigger candidate became execution controller."

$baseReadbackText = Get-Content -LiteralPath $readback -Raw -Encoding UTF8
Assert-True ($baseReadbackText.Contains("scoped candidate")) "Base readback missing scoped candidate boundary."
Assert-True ($baseReadbackText.Contains("global runtime enforcement")) "Base readback missing global runtime enforcement boundary."
Assert-True ($baseReadbackText.Contains("user_correction_runtime_refs_bound: True")) "Base readback missing user correction runtime refs binding."
Assert-True ($baseReadbackText.Contains("user_correction_runtime_not_enforced: True")) "Base readback missing user correction runtime non-enforcement."
Assert-True ($baseReadbackText.Contains("modular_dynamic_worker_pool_phase1_provider_visible: True")) "Base readback missing phase1 Gateway provider visibility."
Assert-True ($baseReadbackText.Contains("scheduler_current_wave_evidence_bound: True")) "Base readback missing scheduler current-wave evidence binding."
Assert-True ($baseReadbackText.Contains("scheduler_activity_scoped_evidence_bound: True")) "Base readback missing scheduler activity evidence binding."
Assert-True ($baseReadbackText.Contains("scheduler_lane_refs_non_overclaiming: True")) "Base readback missing scheduler non-overclaim boundary."
Assert-True ($baseReadbackText.Contains("scheduler_spawned_lane_evidence_refs_bound: True")) "Base readback missing scheduler spawned lane alias binding."
Assert-True ($baseReadbackText.Contains("scheduler_current_wave_immutable_ref_bound: True")) "Base readback missing scheduler immutable current-wave binding."
Assert-True ($baseReadbackText.Contains("codex_lane_evidence_discovered_by_candidate: True")) "Base readback missing Codex lane alias discovery."
Assert-True ($baseReadbackText.Contains("dp_sidecar_execution_modes_discovered_by_candidate: True")) "Base readback missing DP mode alias discovery."
Assert-True ($baseReadbackText.Contains("dp_sidecar_execution_callable_refs_bound: True")) "Base readback missing DP callable refs binding."
Assert-True ($baseReadbackText.Contains([System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6IO95Yqb6YeH57qz54q25oCB")))) "Base readback missing adoption state readback."

$readbackText = Get-Content -LiteralPath $serviceReadback -Raw -Encoding UTF8
Assert-True ($readbackText.Contains([System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6IO95Yqb6YeH57qz54q25oCB")))) "Service readback missing adoption state text."
Assert-True ($readbackText.Contains([System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5LiN5pivIFN0b3AgZ3VhcmQ=")))) "Service readback missing Stop guard boundary."
Assert-True ($readbackText.Contains([System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5LiN5pivIGNvbXBsZXRpb24gZ2F0ZQ==")))) "Service readback missing completion gate boundary."
Assert-True ($readbackText.Contains([System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("cnVudGltZSDlvLrliLbmiafooYw=")))) "Service readback missing runtime enforcement boundary."
Assert-True ($readbackText.Contains("scheduler_current_wave_evidence_bound: True")) "Service readback missing scheduler current-wave evidence."
Assert-True ($readbackText.Contains("modular_dynamic_worker_pool_phase1_provider_visible: True")) "Service readback missing phase1 Gateway provider visibility."
Assert-True ($readbackText.Contains("default_runtime_scheduler_invoked: False")) "Service readback missing scheduler default runtime boundary."
Assert-True ($readbackText.Contains("scheduler_lane_runtime_enforced: False")) "Service readback missing scheduler runtime boundary."

Write-Output "default_main_loop_trigger_candidate_latest=$latest"
Write-Output "default_main_loop_trigger_candidate_service_latest=$serviceLatest"
Write-Output "default_main_loop_trigger_candidate_service_readback=$serviceReadback"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY"
