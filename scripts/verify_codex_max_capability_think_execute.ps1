param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskId = "xinao_seed_cortex_phase0_20260701",
    [string]$IntentPackage = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge\intent_packages\grok_333_continue_root_intent_loop_20260703.json",
    [string]$WaveId = "codex-max-loop-boot-default-20260703",
    [string]$WorkflowId = "333-sleep-watch-source-package-20260705-r1",
    [string]$WorkflowRunId = "",
    [string]$PhaseScope = "assignment_dag_auto_continue",
    [string]$ContinuationAuthorizationLane = "codex_a_brain_dispatch",
    [string]$WorkerAssignmentRef = "D:\XINAO_RESEARCH_RUNTIME\state\worker_assignment\xinao_seed_cortex_phase0_20260701.json",
    [string]$WorkerKind = "implementation_worker",
    [string]$ProviderRoutingMode = "runtime_default",
    [ValidateSet("true", "false", "unset")]
    [string]$DefaultTokenSavingWorkerRoute = "unset",
    [string]$WorkPackageJson = "",
    [string]$ExpectedWorkPackageNodeId = ""
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

function Resolve-ExpectedWorkPackageNodeId {
    param([string]$Value, [string]$Fallback)
    if (-not $Value) { return $Fallback }
    try {
        $raw = $Value
        if (Test-Path -LiteralPath $Value -PathType Leaf) {
            $raw = Get-Content -LiteralPath $Value -Raw -Encoding UTF8
        }
        $package = $raw | ConvertFrom-Json
        if ($package.next_ready_node_id) {
            return [string]$package.next_ready_node_id
        }
        if ($package.work_items -and $package.work_items.Count -gt 0 -and $package.work_items[0].id) {
            return [string]$package.work_items[0].id
        }
    }
    catch {
        return $Fallback
    }
    return $Fallback
}

Push-Location $RepoRoot
try {
    $expectedNodeId = $ExpectedWorkPackageNodeId
    if (-not $expectedNodeId) {
        $expectedNodeId = Resolve-ExpectedWorkPackageNodeId -Value $WorkPackageJson -Fallback "codex_max_capability_think_execute"
    }

    python -m pytest -q tests\seedcortex\test_codex_max_capability_think_execute.py
    Assert-True ($LASTEXITCODE -eq 0) "focused pytest failed."

    $driverArgs = @(
        "services\agent_runtime\codex_max_capability_think_execute.py",
        "--runtime-root", $RuntimeRoot,
        "--repo-root", $RepoRoot,
        "--task-id", $TaskId,
        "--intent-package", $IntentPackage,
        "--wave-id", $WaveId,
        "--workflow-id", $WorkflowId,
        "--workflow-run-id=$WorkflowRunId",
        "--phase-scope", $PhaseScope,
        "--continuation-authorization-lane", $ContinuationAuthorizationLane,
        "--worker-assignment-ref", $WorkerAssignmentRef,
        "--worker-kind", $WorkerKind,
        "--provider-routing-mode", $ProviderRoutingMode,
        "--default-token-saving-worker-route", $DefaultTokenSavingWorkerRoute,
        "--think-subagent", "019f25b6-d322-7381-a41b-91bfdfe31396:dp_router_audit:succeeded",
        "--think-subagent", "019f25b6-e66c-7912-ad27-84599487252b:worker_assignment_audit:succeeded",
        "--think-subagent", "019f25b6-f745-7853-bd84-2beba570b941:temporal_durable_audit:succeeded"
    )
    if ($WorkPackageJson) {
        $driverArgs += @("--work-package-json", $WorkPackageJson)
    }
    python @driverArgs
    Assert-True ($LASTEXITCODE -eq 0) "runtime driver failed."

    $latestPath = Join-Path $RuntimeRoot "state\codex_max_capability_think_execute\latest.json"
    $readbackPath = Join-Path $RuntimeRoot "readback\zh\worker_assignment_$TaskId`_20260703.md"
    $specPath = Join-Path $RuntimeRoot "specs\max_benefit_dynamic_loop_authority_20260702.v1.md"
    Assert-True (Test-Path -LiteralPath $latestPath -PathType Leaf) "latest evidence missing."
    Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "Chinese readback missing."
    Assert-True (Test-Path -LiteralPath $specPath -PathType Leaf) "total draft spec missing."

    $payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($payload.validation.passed -eq $true) "payload validation did not pass."
    Assert-True ([string]$payload.workflow_binding.workflow_id -eq $WorkflowId) "workflow_id was not bound."
    Assert-True ([string]$payload.workflow_binding.phase_scope -eq $PhaseScope) "phase_scope was not bound."
    Assert-True ([string]$payload.workflow_binding.continuation_authorization_lane -eq $ContinuationAuthorizationLane) "continuation authorization lane was not bound."
    Assert-True ($payload.workflow_binding.new_owner_created -eq $false) "new owner was created."
    Assert-True ($payload.workflow_binding.codex_a_intent_ingress_called -eq $false) "codex-a intent ingress was called."
    Assert-True ($payload.workflow_binding.pump_default_used -eq $false) "pump default was used."
    Assert-True ($payload.WORKER_ASSIGNMENT.scope_level_target -eq "L3") "WORKER_ASSIGNMENT scope_level_target is not L3."
    Assert-True ([string]$payload.WORKER_ASSIGNMENT.workflow_id -eq $WorkflowId) "WORKER_ASSIGNMENT workflow_id mismatch."
    Assert-True ($payload.WORKER_ASSIGNMENT.primary_authority_rank -eq 0) "current Grok authority proxy rank is not 0."
    Assert-True ($payload.WORKER_ASSIGNMENT.current_grok_package_authority_proxy -eq $true) "current Grok authority proxy is not bound."
    Assert-True ($payload.hook_binding.adoption_state -eq "hooked_runtime_entrypoint") "ledger effective adoption_state is not hooked."
    Assert-True ($payload.hook_binding.temporal_worker_dispatch_ledger_activity_hooked -eq $true) "Temporal worker dispatch ledger activity is not hooked."
    Assert-True ($payload.summary.provider_probe_invocation_count -eq 0) "provider_probe was invoked by default."
    Assert-True (($payload.summary.dp_nonprobe_attempted_count -ge 1) -or ($payload.summary.named_serial_exception_present -eq $true)) "non-probe DP lane was neither attempted nor named as serial_exception."
    Assert-True (($payload.summary.dp_nonprobe_succeeded_count -ge 1) -or ($payload.summary.named_serial_exception_present -eq $true)) "non-probe DP neither succeeded nor wrote named serial_exception."
    Assert-True ($payload.summary.synthetic_succeeded_count -eq 0) "synthetic succeeded detected."
    Assert-True ($payload.fan_in.lane_results.source_kind -eq "worker_dispatch_ledger_poll") "fan-in source is not worker_dispatch_ledger_poll."
    Assert-True ([string]$payload.fan_in.lane_results.workflow_id -eq $WorkflowId) "fan-in workflow_id mismatch."
    Assert-True ($payload.phase0_closure_dag.status -eq "ready") "Phase0 closure DAG not ready."
    Assert-True ($payload.phase0_closure_dag.ledger_adoption_state -eq "hooked_runtime_entrypoint") "Phase0 DAG ledger adoption state not hooked."
    Assert-True ($payload.phase0_closure_dag.should_continue_loop -eq $true) "Phase0 DAG does not continue loop."
    Assert-True ($payload.continuity_envelope.should_continue_loop -eq $true) "Continuity envelope does not continue loop."
    Assert-True ([string]$payload.task_bound_assignment_dag_evidence.workflow_id -eq $WorkflowId) "task-bound evidence workflow_id mismatch."
    Assert-True ([string]$payload.task_bound_assignment_dag_evidence.phase_scope -eq $PhaseScope) "task-bound evidence phase_scope mismatch."
    if ($WorkPackageJson) {
        Assert-True ($payload.task_bound_assignment_dag_evidence.explicit_work_package_bound -eq $true) "explicit work package was not bound."
        Assert-True ([string]$payload.task_bound_assignment_dag_evidence.work_package_next_ready_node_id -eq $expectedNodeId) "work package next_ready_node_id mismatch."
        Assert-True ([string]$payload.task_bound_assignment_dag_evidence.node_id -eq $expectedNodeId) "task-bound evidence node_id mismatch."
        Assert-True (Test-Path -LiteralPath ([string]$payload.task_bound_assignment_dag_evidence.node_latest_ref) -PathType Leaf) "task-bound node latest missing."
        Assert-True (Test-Path -LiteralPath ([string]$payload.task_bound_assignment_dag_evidence.jsonl_ref) -PathType Leaf) "task-bound jsonl missing."
    }

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
