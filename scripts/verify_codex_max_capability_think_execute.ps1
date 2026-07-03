param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskId = "xinao_seed_cortex_phase0_20260701",
    [string]$IntentPackage = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge\intent_packages\grok_333_continue_root_intent_loop_20260703.json"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Join-Chars {
    param([int[]]$Codes)
    return -join ($Codes | ForEach-Object { [string]([char]$_) })
}

Push-Location $RepoRoot
try {
    python -m pytest -q tests\seedcortex\test_codex_max_capability_think_execute.py
    Assert-True ($LASTEXITCODE -eq 0) "focused pytest failed."

    python services\agent_runtime\codex_max_capability_think_execute.py `
        --runtime-root $RuntimeRoot `
        --repo-root $RepoRoot `
        --task-id $TaskId `
        --intent-package $IntentPackage `
        --wave-id "codex-max-loop-boot-default-20260703" `
        --think-subagent "019f25b6-d322-7381-a41b-91bfdfe31396:dp_router_audit:succeeded" `
        --think-subagent "019f25b6-e66c-7912-ad27-84599487252b:worker_assignment_audit:succeeded" `
        --think-subagent "019f25b6-f745-7853-bd84-2beba570b941:temporal_durable_audit:succeeded"
    Assert-True ($LASTEXITCODE -eq 0) "runtime driver failed."

    $latestPath = Join-Path $RuntimeRoot "state\codex_max_capability_think_execute\latest.json"
    $readbackPath = Join-Path $RuntimeRoot "readback\zh\worker_assignment_$TaskId`_20260703.md"
    $specPath = Join-Path $RuntimeRoot "specs\max_benefit_dynamic_loop_authority_20260702.v1.md"
    Assert-True (Test-Path -LiteralPath $latestPath -PathType Leaf) "latest evidence missing."
    Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "Chinese readback missing."
    Assert-True (Test-Path -LiteralPath $specPath -PathType Leaf) "total draft spec missing."

    $payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($payload.validation.passed -eq $true) "payload validation did not pass."
    Assert-True ($payload.WORKER_ASSIGNMENT.scope_level_target -eq "L3") "WORKER_ASSIGNMENT scope_level_target is not L3."
    Assert-True ($payload.WORKER_ASSIGNMENT.primary_authority_rank -eq 0) "current Grok authority proxy rank is not 0."
    Assert-True ($payload.WORKER_ASSIGNMENT.current_grok_package_authority_proxy -eq $true) "current Grok authority proxy is not bound."
    Assert-True ($payload.hook_binding.adoption_state -eq "hooked_runtime_entrypoint") "ledger effective adoption_state is not hooked."
    Assert-True ($payload.hook_binding.temporal_worker_dispatch_ledger_activity_hooked -eq $true) "Temporal worker dispatch ledger activity is not hooked."
    Assert-True ($payload.summary.provider_probe_invocation_count -eq 0) "provider_probe was invoked by default."
    Assert-True (($payload.summary.dp_nonprobe_attempted_count -ge 1) -or ($payload.summary.named_serial_exception_present -eq $true)) "non-probe DP lane was neither attempted nor named as serial_exception."
    Assert-True (($payload.summary.dp_nonprobe_succeeded_count -ge 1) -or ($payload.summary.named_serial_exception_present -eq $true)) "non-probe DP neither succeeded nor wrote named serial_exception."
    Assert-True ($payload.summary.synthetic_succeeded_count -eq 0) "synthetic succeeded detected."
    Assert-True ($payload.fan_in.lane_results.source_kind -eq "worker_dispatch_ledger_poll") "fan-in source is not worker_dispatch_ledger_poll."
    Assert-True ($payload.phase0_closure_dag.status -eq "ready") "Phase0 closure DAG not ready."
    Assert-True ($payload.phase0_closure_dag.ledger_adoption_state -eq "hooked_runtime_entrypoint") "Phase0 DAG ledger adoption state not hooked."
    Assert-True ($payload.phase0_closure_dag.should_continue_loop -eq $true) "Phase0 DAG does not continue loop."
    Assert-True ($payload.continuity_envelope.should_continue_loop -eq $true) "Continuity envelope does not continue loop."

    $readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
    $lLayerSection = "L " + (Join-Chars @(0x5C42, 0x4E0E, 0x603B, 0x7A3F))
    $totalDraftGapSection = Join-Chars @(0x603B, 0x7A3F, 0x5DEE, 0x8DDD, 0x4E0E, 0x4E0B, 0x4E00, 0x673A, 0x5668, 0x52A8, 0x4F5C)
    $currentCapabilitySection = Join-Chars @(0x73B0, 0x5728, 0x80FD, 0x5E72, 0x4EC0, 0x4E48)
    Assert-True ($readback.Contains($lLayerSection)) "readback missing L layer section."
    Assert-True ($readback.Contains($totalDraftGapSection)) "readback missing total draft gap section."
    Assert-True ($readback.Contains("ledger hooked")) "readback missing ledger hook/blocker line."
    Assert-True ($readback.Contains("WP_HOOK -> THINK -> EXECUTE -> READBACK -> VERIFY")) "readback missing full DAG section."
    Assert-True ($readback.Contains($currentCapabilitySection)) "readback missing capability section."
    Assert-True ($readback.Contains("should_continue_loop")) "readback missing continuation line."

    Write-Output "codex_max_capability_think_execute_latest=$latestPath"
    Write-Output "codex_max_capability_think_execute_readback=$readbackPath"
    Write-Output "total_draft_spec=$specPath"
    Write-Output "worker_assignment=$($payload.output_paths.worker_assignment)"
    Write-Output "scope_level_current=$($payload.WORKER_ASSIGNMENT.scope_level_current)"
    Write-Output "ledger_hook_blocker=$($payload.hook_binding.named_blocker)"
    Write-Output "ledger_adoption_state=$($payload.hook_binding.adoption_state)"
    Write-Output "phase0_closure_dag_status=$($payload.phase0_closure_dag.status)"
    Write-Output "should_continue_loop=$($payload.continuity_envelope.should_continue_loop)"
}
finally {
    Pop-Location
}
