$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$python = "python"
$temporalPath = Join-Path $repoRoot "services\agent_runtime\temporal_codex_task_workflow.py"
$ledgerPath = Join-Path $repoRoot "services\agent_runtime\worker_dispatch_ledger.py"

& $python -m py_compile $temporalPath $ledgerPath
Assert-True ($LASTEXITCODE -eq 0) "Temporal worker dispatch ledger py_compile failed."

& $python -m pytest -q `
    (Join-Path $repoRoot "tests\seedcortex\test_worker_dispatch_ledger.py") `
    (Join-Path $repoRoot "tests\test_temporal_codex_task_workflow.py") `
    -k "worker_dispatch_ledger"
Assert-True ($LASTEXITCODE -eq 0) "Temporal worker dispatch ledger focused pytest failed."

$smokeRoot = Join-Path $runtimeRoot "state\temporal_worker_dispatch_ledger_activity_smoke"
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
$env:XINAO_WORKER_JSONL = $jsonl
$env:XINAO_WORKER_FINAL = $final
$env:XINAO_WORKER_RAW_FINAL = $rawFinal
$py = @'
import asyncio
import json
import os

from services.agent_runtime import temporal_codex_task_workflow as t

payload = asyncio.run(t.worker_dispatch_ledger_activity({
    "runtime_root": os.environ["XINAO_RUNTIME_ROOT"],
    "task_id": t.SEED_CORTEX_WORK_ID,
    "route_profile": t.SEED_CORTEX_ROUTE_PROFILE,
    "workflow_id": "verify-temporal-worker-dispatch-ledger-activity-20260702",
    "worker_dispatch_evidence": {
        "activity": "codex_worker_turn",
        "status": "activity_gate_checked",
        "task_id": t.SEED_CORTEX_WORK_ID,
        "worker_task_id": "verify-seed-cortex-temporal-worker-dispatch-ledger.worker.1",
        "jsonl_path": os.environ["XINAO_WORKER_JSONL"],
        "final_path": os.environ["XINAO_WORKER_FINAL"],
        "raw_final_path": os.environ["XINAO_WORKER_RAW_FINAL"],
        "task_bound_worker": True,
        "expected_marker_seen": True,
        "jsonl_exists": True,
        "command_surface": "Temporal activity -> codex_activator -> codex exec --json",
        "mature_execution_carrier": t.MATURE_EXECUTION_CARRIER,
    },
}))
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if payload.get("status") == "activity_gate_checked" and payload.get("runtime_enforced") is True else 1)
'@
$activityOutput = $py | & $python -
Assert-True ($LASTEXITCODE -eq 0) "Temporal worker dispatch ledger activity smoke failed."

$latest = Join-Path $runtimeRoot "state\worker_dispatch_ledger\latest.json"
$temporalActivityLatest = Join-Path $runtimeRoot "state\worker_dispatch_ledger\temporal_activity_latest.json"
$readback = Join-Path $runtimeRoot "readback\zh\worker_dispatch_ledger_20260702.md"
Assert-True (Test-Path -LiteralPath $latest -PathType Leaf) "Temporal worker dispatch ledger latest missing."
Assert-True (Test-Path -LiteralPath $temporalActivityLatest -PathType Leaf) "Temporal worker dispatch ledger activity latest missing."
Assert-True (Test-Path -LiteralPath $readback -PathType Leaf) "Temporal worker dispatch ledger readback missing."

$payload = Get-Content -LiteralPath $temporalActivityLatest -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.worker_dispatch_ledger.v1") "Worker dispatch ledger schema mismatch."
Assert-True ($payload.work_id -eq "xinao_seed_cortex_phase0_20260701") "Worker dispatch ledger work_id mismatch."
Assert-True ($payload.validation.passed -eq $true) "Worker dispatch ledger validation failed."
Assert-True ($payload.runtime_entrypoint_invocation.invoked -eq $true) "Worker dispatch ledger runtime invocation not recorded."
Assert-True ($payload.runtime_entrypoint_invocation.runtime_enforced -eq $true) "Worker dispatch ledger runtime invocation not marked enforced."
Assert-True ($payload.runtime_entrypoint_invocation.not_execution_controller -eq $true) "Worker dispatch ledger became execution controller."
Assert-True ($payload.runtime_entrypoint_invocation.not_completion_gate -eq $true) "Worker dispatch ledger became completion gate."
Assert-True ($payload.summary.hooked_runtime_entrypoint_count -eq 1) "Worker dispatch ledger hooked runtime entrypoint count mismatch."
$entries = @($payload.dispatch_entries)
$temporalEntries = @($entries | Where-Object { $_.provider -eq "temporal.codex_worker_turn_activity" })
Assert-True ($temporalEntries.Count -ge 1) "Worker dispatch ledger missing temporal worker activity entry."
$expectedWorkerMatches = @($temporalEntries | Where-Object { $_.agent_id -eq "verify-seed-cortex-temporal-worker-dispatch-ledger.worker.1" })
Assert-True ($expectedWorkerMatches.Count -eq 1) "Temporal worker dispatch ledger missing expected worker_task_id."
foreach ($entry in $temporalEntries) {
    Assert-True ($entry.fan_in_decision -eq "accepted_for_ledger_evidence_only") "Temporal worker dispatch ledger fan-in was not evidence-only."
    Assert-True ($entry.legacy_5d33_owner_reused -eq $false) "Temporal worker dispatch ledger reused old 5d33 owner."
    Assert-True ($entry.legacy_5d33_pass_reused -eq $false) "Temporal worker dispatch ledger reused old 5d33 PASS."
    Assert-True ($entry.legacy_5d33_latest_authority_reused -eq $false) "Temporal worker dispatch ledger reused old 5d33 latest authority."
}

Write-Output "temporal_worker_dispatch_ledger_latest=$latest"
Write-Output "temporal_worker_dispatch_ledger_activity_latest=$temporalActivityLatest"
Write-Output "temporal_worker_dispatch_ledger_readback=$readback"
Write-Output "runtime_enforced_scope=seed_cortex_temporal_worker_dispatch_ledger_write_activity"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_TEMPORAL_WORKER_DISPATCH_LEDGER_ACTIVITY_READY"
