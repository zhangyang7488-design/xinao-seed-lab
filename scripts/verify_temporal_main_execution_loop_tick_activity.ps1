$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
$anchorFolder = ([string][char]0x65B0) + ([string][char]0x7CFB) + ([string][char]0x7EDF)
$anchorRoot = Join-Path ([Environment]::GetFolderPath("Desktop")) $anchorFolder

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$python = "python"
& $python -m py_compile `
    (Join-Path $repoRoot "services\agent_runtime\temporal_codex_task_workflow.py") `
    (Join-Path $repoRoot "services\agent_runtime\codex_s_main_execution_loop_tick.py") `
    (Join-Path $repoRoot "services\agent_runtime\worker_dispatch_ledger.py")
Assert-True ($LASTEXITCODE -eq 0) "Temporal main execution loop tick py_compile failed."

& $python -m pytest -q `
    (Join-Path $repoRoot "tests\seedcortex\test_codex_s_main_execution_loop_tick.py") `
    (Join-Path $repoRoot "tests\test_temporal_codex_task_workflow.py") `
    -k "main_execution_loop_tick or worker_dispatch_ledger"
Assert-True ($LASTEXITCODE -eq 0) "Temporal main execution loop tick focused pytest failed."

Assert-True (Test-Path -LiteralPath $anchorRoot -PathType Container) "Desktop anchor package missing: $anchorRoot"

$smokeRoot = Join-Path $runtimeRoot "state\temporal_main_execution_loop_tick_activity_smoke"
New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null
$jsonl = Join-Path $smokeRoot "codex-events.jsonl"
$final = Join-Path $smokeRoot "final.md"
$rawFinal = Join-Path $smokeRoot "raw-final.md"
$marker = "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK"
Set-Content -LiteralPath $jsonl -Encoding UTF8 -Value @(
    '{"type":"thread.started"}'
    '{"type":"turn.completed"}'
)
Set-Content -LiteralPath $final -Encoding UTF8 -Value $marker
Set-Content -LiteralPath $rawFinal -Encoding UTF8 -Value $marker

$env:XINAO_RUNTIME_ROOT = $runtimeRoot
$env:XINAO_ANCHOR_ROOT = $anchorRoot
$env:XINAO_WORKER_JSONL = $jsonl
$env:XINAO_WORKER_FINAL = $final
$env:XINAO_WORKER_RAW_FINAL = $rawFinal
$py = @'
import asyncio
import json
import os

from services.agent_runtime import temporal_codex_task_workflow as t

worker = asyncio.run(t.worker_dispatch_ledger_activity({
    "runtime_root": os.environ["XINAO_RUNTIME_ROOT"],
    "task_id": t.SEED_CORTEX_WORK_ID,
    "route_profile": t.SEED_CORTEX_ROUTE_PROFILE,
    "workflow_id": "verify-temporal-main-execution-loop-tick-activity-20260702",
    "worker_dispatch_evidence": {
        "activity": "codex_worker_turn",
        "status": "activity_gate_checked",
        "task_id": t.SEED_CORTEX_WORK_ID,
        "worker_task_id": "verify-seed-cortex-main-loop.worker.1",
        "jsonl_path": os.environ["XINAO_WORKER_JSONL"],
        "final_path": os.environ["XINAO_WORKER_FINAL"],
        "raw_final_path": os.environ["XINAO_WORKER_RAW_FINAL"],
        "task_bound_worker": True,
        "expected_marker_seen": True,
        "jsonl_exists": True,
    },
}))
main = asyncio.run(t.main_execution_loop_tick_activity({
    "runtime_root": os.environ["XINAO_RUNTIME_ROOT"],
    "task_id": t.SEED_CORTEX_WORK_ID,
    "route_profile": t.SEED_CORTEX_ROUTE_PROFILE,
    "workflow_id": "verify-temporal-main-execution-loop-tick-activity-20260702",
    "anchor_package_root": os.environ["XINAO_ANCHOR_ROOT"],
    "worker_dispatch_ledger_activity": worker,
}))
print(json.dumps({"worker": worker, "main": main}, ensure_ascii=False, indent=2))
ok = (
    worker.get("status") == "activity_gate_checked"
    and worker.get("runtime_enforced") is True
    and main.get("status") == "activity_gate_checked"
    and main.get("runtime_enforced") is True
    and main.get("tick_validation_passed") is True
)
raise SystemExit(0 if ok else 1)
'@
$activityOutput = $py | & $python -
$activityText = $activityOutput -join [Environment]::NewLine
Assert-True ($LASTEXITCODE -eq 0) "Temporal main execution loop tick activity smoke failed."

$tickLatest = Join-Path $runtimeRoot "state\codex_s_main_execution_loop_tick\latest.json"
$tickTemporalLatest = Join-Path $runtimeRoot "state\codex_s_main_execution_loop_tick\temporal_activity_latest.json"
$tickReadback = Join-Path $runtimeRoot "readback\zh\codex_s_main_execution_loop_tick_20260702.md"
$workerTemporalLatest = Join-Path $runtimeRoot "state\worker_dispatch_ledger\temporal_activity_latest.json"
Assert-True (Test-Path -LiteralPath $tickLatest -PathType Leaf) "Main execution loop tick latest missing."
Assert-True (Test-Path -LiteralPath $tickTemporalLatest -PathType Leaf) "Main execution loop tick activity latest missing."
Assert-True (Test-Path -LiteralPath $tickReadback -PathType Leaf) "Main execution loop tick readback missing."
Assert-True (Test-Path -LiteralPath $workerTemporalLatest -PathType Leaf) "Worker dispatch ledger activity latest missing."

$payload = Get-Content -LiteralPath $tickTemporalLatest -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.main_execution_loop_tick.v1") "Main execution loop tick schema mismatch."
Assert-True ($payload.validation.passed -eq $true) "Main execution loop tick validation failed."
Assert-True ($payload.runtime_entrypoint_invocation.invoked -eq $true) "Main execution loop tick runtime invocation missing."
Assert-True ($payload.runtime_entrypoint_invocation.runtime_enforced -eq $true) "Main execution loop tick runtime invocation not enforced."
Assert-True ($payload.runtime_entrypoint_invocation.not_execution_controller -eq $true) "Main execution loop tick became execution controller."
Assert-True ($payload.runtime_entrypoint_invocation.not_completion_gate -eq $true) "Main execution loop tick became completion gate."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_evidence_only -eq $true) "Runtime preflight refs were not evidence-only."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_not_stop_guard_layers -eq $true) "Runtime preflight refs became Stop guard layers."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_not_completion_gates -eq $true) "Runtime preflight refs became completion gates."
Assert-True ($payload.runtime_preflight_refs.preflight_refs_are_not_execution_controllers -eq $true) "Runtime preflight refs became execution controllers."
$correctionSurface = $payload.runtime_preflight_refs.seed_lab_user_correction_runtime_surface
Assert-True ($correctionSurface.invoked_by_main_execution_loop_tick -eq $true) "User correction runtime surface was not prepared by temporal main loop tick."
Assert-True ($correctionSurface.refs_ready_for_durable_packet -eq $true) "User correction runtime refs are not ready for durable packet."
Assert-True ($correctionSurface.runtime_enforced -eq $false) "User correction runtime surface overclaimed runtime enforcement."
Assert-True ($correctionSurface.trigger_installed -eq $false) "User correction runtime surface installed trigger."
Assert-True ($correctionSurface.memory_promotion_allowed -eq $false) "User correction runtime surface allowed memory promotion."
Assert-True ($correctionSurface.policy_promotion_allowed -eq $false) "User correction runtime surface allowed policy promotion."
Assert-True ($correctionSurface.completion_claim_allowed -eq $false) "User correction runtime surface allowed completion claim."
Assert-True ($correctionSurface.not_execution_controller -eq $true) "User correction runtime surface became execution controller."
Assert-True ($payload.validation.checks.seed_lab_user_correction_runtime_surface_prepared -eq $true) "User correction runtime surface validation failed."
Assert-True ($payload.actual_dispatch_refs.worker_dispatch_ledger_activity_ref.runtime_enforced -eq $true) "Main execution loop tick missing worker ledger activity ref."
Assert-True ($payload.next_wave_decision.continue_main_loop -eq $true) "Main execution loop tick did not preserve continuation."
Assert-True ($payload.next_wave_decision.decision -eq "fan_in_or_next_wave_ready") "Main execution loop tick did not reach fan-in/next-wave ready state."
Assert-True ($payload.completion_claim_allowed -eq $false) "Main execution loop tick allowed completion claim."
Assert-True ($payload.not_execution_controller -eq $true) "Main execution loop tick payload became execution controller."
$readbackText = Get-Content -LiteralPath $tickReadback -Raw -Encoding UTF8
Assert-True ($readbackText.Contains("seed_cortex_temporal_main_execution_loop_tick_activity")) "Main execution loop tick readback missing runtime scope."

Write-Output "temporal_main_execution_loop_tick_latest=$tickLatest"
Write-Output "temporal_main_execution_loop_tick_activity_latest=$tickTemporalLatest"
Write-Output "temporal_worker_dispatch_ledger_activity_latest=$workerTemporalLatest"
Write-Output "runtime_enforced_scope=seed_cortex_temporal_main_execution_loop_tick_activity"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_TEMPORAL_MAIN_EXECUTION_LOOP_TICK_ACTIVITY_READY"
