[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$RuntimeRoot = "",
    [string]$TargetTaskId = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-NativeCapture {
    param([scriptblock]$Command)
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $Command 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    return @{
        Output = @($output)
        ExitCode = $exitCode
    }
}

function Get-PollerCount {
    param($PollerPayload)
    if ($null -eq $PollerPayload -or $null -eq $PollerPayload.pollers) {
        return 0
    }
    return @($PollerPayload.pollers).Count
}

function Find-DurableParallelWavePacketActivity {
    param($Activities)
    foreach ($item in @($Activities)) {
        $activityName = [string]$item.activity
        $invokedBy = [string]$item.runtime_entrypoint_invocation.invoked_by
        if (
            $activityName -eq "durable_parallel_wave_packet_activity" -or
            $activityName -eq "durable_parallel_wave_packet" -or
            $invokedBy -eq "temporal_codex_task_workflow.durable_parallel_wave_packet_activity"
        ) {
            return $item
        }
    }
    return $null
}

function Find-DefaultMainLoopTriggerCandidateActivity {
    param($Activities)
    foreach ($item in @($Activities)) {
        $activityName = [string]$item.activity
        $invokedBy = [string]$item.runtime_entrypoint_invocation.invoked_by
        if (
            $activityName -eq "default_main_loop_trigger_candidate" -or
            $invokedBy -eq "temporal_codex_task_workflow.default_main_loop_trigger_candidate_activity"
        ) {
            return $item
        }
    }
    return $null
}

function Find-SchedulerInvocationPacketActivity {
    param($Activities)
    foreach ($item in @($Activities)) {
        $activityName = [string]$item.activity
        $invokedBy = [string]$item.runtime_entrypoint_invocation.invoked_by
        if (
            $activityName -eq "scheduler_invocation_packet" -or
            $invokedBy -eq "temporal_codex_task_workflow.scheduler_invocation_packet_activity"
        ) {
            return $item
        }
    }
    return $null
}

function Get-TemporalActivityTypeNames {
    param($Events)
    $names = @()
    foreach ($event in @($Events)) {
        $attrs = $event.activityTaskScheduledEventAttributes
        if ($null -eq $attrs) { continue }
        $typeName = [string]$attrs.activityType.name
        if (-not [string]::IsNullOrWhiteSpace($typeName)) {
            $names += $typeName
        }
    }
    return @($names)
}

function Convert-TemporalJsonPayload {
    param($Payload)
    $data = [string]$Payload.data
    if ([string]::IsNullOrWhiteSpace($data)) { return $null }
    $json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($data))
    if ([string]::IsNullOrWhiteSpace($json)) { return $null }
    return $json | ConvertFrom-Json
}

function Get-TemporalActivityCompletionResults {
    param($Events)
    $scheduledById = @{}
    foreach ($event in @($Events)) {
        $attrs = $event.activityTaskScheduledEventAttributes
        if ($null -eq $attrs) { continue }
        $activityType = [string]$attrs.activityType.name
        if (-not [string]::IsNullOrWhiteSpace($activityType)) {
            $scheduledById[[string]$event.eventId] = $activityType
        }
    }

    $results = @()
    foreach ($event in @($Events)) {
        $attrs = $event.activityTaskCompletedEventAttributes
        if ($null -eq $attrs) { continue }
        $scheduledEventId = [string]$attrs.scheduledEventId
        $activityType = ""
        if ($scheduledById.ContainsKey($scheduledEventId)) {
            $activityType = [string]$scheduledById[$scheduledEventId]
        }
        $payload = @($attrs.result.payloads) | Select-Object -First 1
        $result = Convert-TemporalJsonPayload $payload
        $results += [pscustomobject]@{
            ActivityType = $activityType
            Result = $result
        }
    }
    return @($results)
}

function Assert-DurableParallelWavePacketActivityResult {
    param($DurableActivity, [string]$ExpectedTemporalActivityLatestRef, [string]$Context)
    Assert-True ($null -ne $DurableActivity) "$Context durable_parallel_wave_packet_activity result missing."
    Assert-True ($DurableActivity.runtime_enforced -eq $true) "$Context durable packet activity must be runtime_enforced=true."
    Assert-True ($DurableActivity.runtime_enforced_scope -eq "seed_cortex_temporal_durable_parallel_wave_packet_activity") "$Context durable packet activity scope mismatch."
    $activityLatestRef = [string]$DurableActivity.durable_packet_temporal_activity_latest_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($activityLatestRef)) "$Context durable packet temporal activity latest ref missing."
    if (-not [string]::IsNullOrWhiteSpace($ExpectedTemporalActivityLatestRef)) {
        Assert-True ($activityLatestRef -eq $ExpectedTemporalActivityLatestRef) "$Context durable packet latest ref mismatch."
    }
    Assert-True (Test-Path -LiteralPath $activityLatestRef -PathType Leaf) "$Context durable packet temporal activity latest ref must exist."
    Assert-True ($DurableActivity.status -eq "activity_gate_checked") "$Context durable packet activity must be gate checked, not blocked."
    Assert-True ($DurableActivity.durable_packet_validation_passed -eq $true) "$Context durable packet validation_passed must be true."
    Assert-True ($DurableActivity.actual_dispatch_refs.codex_subagent_count -ge 1) "$Context durable packet actual worker/subagent refs missing."
    Assert-True ($DurableActivity.actual_dispatch_refs.derived_codex_subagent_refs_from_worker_activity -eq $true) "$Context durable packet did not derive worker refs."
    Assert-True (@($DurableActivity.actual_dispatch_refs.worker_dispatch_ledger_actual_entry_ids).Count -ge 1) "$Context durable packet actual worker entry ids missing."
    Assert-True ($DurableActivity.actual_dispatch_refs.dp_sidecar_execution_port -eq "dp_sidecar_execution_port") "$Context durable packet missing DP sidecar execution port."
    Assert-True ($DurableActivity.actual_dispatch_refs.dp_sidecar_execution_callable_entrypoint_bound -eq $true) "$Context durable packet missing DP callable entrypoint binding."
    Assert-True ($DurableActivity.actual_dispatch_refs.dp_sidecar_execution_port_runner_ref.exists -eq $true) "$Context durable packet missing DP runner ref."
    Assert-True ($DurableActivity.actual_dispatch_refs.dp_sidecar_execution_provider_ref.exists -eq $true) "$Context durable packet missing DP provider ref."
    Assert-True ($DurableActivity.actual_dispatch_refs.dp_sidecar_execution_provider_manifest_ref.exists -eq $true) "$Context durable packet missing DP provider manifest ref."
    Assert-True ($DurableActivity.not_execution_controller -eq $true) "$Context durable packet activity must keep not_execution_controller=true."
    Assert-True ($DurableActivity.runtime_entrypoint_invocation.not_completion_gate -eq $true) "$Context durable packet activity entrypoint must keep not_completion_gate=true."
    Assert-True ($DurableActivity.runtime_entrypoint_invocation.dp_sidecar_execution_bootstrap.not_execution_controller -eq $true) "$Context DP sidecar bootstrap must remain non-controller."
}

function Assert-DurableParallelWavePacketWorkflowResult {
    param($WorkflowResult, [string]$Context)
    $durableActivity = Find-DurableParallelWavePacketActivity $WorkflowResult.activities
    Assert-True ($null -ne $durableActivity) "$Context activities must include durable_parallel_wave_packet_activity."
    Assert-True ($null -ne $WorkflowResult.durable_parallel_wave_packet_activity) "$Context top-level durable_parallel_wave_packet_activity missing."
    Assert-True ($WorkflowResult.durable_parallel_wave_packet_runtime_enforced -eq $true) "$Context must mark durable_parallel_wave_packet_runtime_enforced=true."
    Assert-True ($WorkflowResult.durable_parallel_wave_packet_runtime_enforced_scope -eq "seed_cortex_temporal_durable_parallel_wave_packet_activity") "$Context durable packet runtime scope mismatch."
    $durableTemporalActivityLatestRef = [string]$WorkflowResult.durable_parallel_wave_packet_temporal_activity_latest_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($durableTemporalActivityLatestRef)) "$Context durable packet temporal activity latest ref missing."
    Assert-True (Test-Path -LiteralPath $durableTemporalActivityLatestRef -PathType Leaf) "$Context durable packet temporal activity latest ref must exist."
    Assert-True ($WorkflowResult.durable_parallel_wave_packet_not_execution_controller -eq $true) "$Context durable packet must keep not_execution_controller=true."
    Assert-True ($WorkflowResult.durable_parallel_wave_packet_not_completion_gate -eq $true) "$Context durable packet must keep not_completion_gate=true."
    Assert-True ($WorkflowResult.durable_parallel_wave_packet_validation_passed -eq $true) "$Context durable packet validation_passed must be true."
    Assert-DurableParallelWavePacketActivityResult $durableActivity $durableTemporalActivityLatestRef $Context
}

function Assert-DefaultMainLoopTriggerCandidateActivityResult {
    param($TriggerActivity, [string]$ExpectedTemporalActivityLatestRef, [string]$Context)
    Assert-True ($null -ne $TriggerActivity) "$Context default_main_loop_trigger_candidate_activity result missing."
    Assert-True ($TriggerActivity.runtime_enforced -eq $true) "$Context default trigger candidate activity must be runtime_enforced=true."
    Assert-True ($TriggerActivity.runtime_enforced_scope -eq "seed_cortex_temporal_default_main_loop_trigger_candidate_activity") "$Context default trigger candidate activity scope mismatch."
    $activityLatestRef = [string]$TriggerActivity.trigger_candidate_temporal_activity_latest_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($activityLatestRef)) "$Context default trigger candidate temporal activity latest ref missing."
    if (-not [string]::IsNullOrWhiteSpace($ExpectedTemporalActivityLatestRef)) {
        Assert-True ($activityLatestRef -eq $ExpectedTemporalActivityLatestRef) "$Context default trigger candidate latest ref mismatch."
    }
    Assert-True (Test-Path -LiteralPath $activityLatestRef -PathType Leaf) "$Context default trigger candidate temporal activity latest ref must exist."
    Assert-True ($TriggerActivity.status -eq "activity_gate_checked") "$Context default trigger candidate activity must be gate checked, not blocked."
    Assert-True ($TriggerActivity.trigger_candidate_validation_passed -eq $true) "$Context default trigger candidate validation_passed must be true."
    Assert-True ($TriggerActivity.main_execution_loop_tick_activity_ref.runtime_enforced -eq $true) "$Context default trigger candidate missing main tick activity ref."
    Assert-True ($TriggerActivity.durable_parallel_wave_packet_activity_ref.runtime_enforced -eq $true) "$Context default trigger candidate missing durable packet activity ref."
    Assert-True ($TriggerActivity.actual_dispatch_refs.dp_sidecar_execution_port -eq "dp_sidecar_execution_port") "$Context default trigger missing DP sidecar execution port."
    Assert-True ($TriggerActivity.actual_dispatch_refs.dp_sidecar_execution_callable_entrypoint_bound -eq $true) "$Context default trigger missing DP callable entrypoint binding."
    Assert-True ($TriggerActivity.actual_dispatch_refs.dp_sidecar_execution_port_runner_ref.exists -eq $true) "$Context default trigger missing DP runner ref."
    $triggerLatestPayload = Get-Content -LiteralPath $activityLatestRef -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($triggerLatestPayload.validation.checks.dp_sidecar_execution_callable_refs_bound -eq $true) "$Context default trigger DP callable refs validation missing."
    Assert-True ($TriggerActivity.not_execution_controller -eq $true) "$Context default trigger candidate activity must keep not_execution_controller=true."
    Assert-True ($TriggerActivity.runtime_entrypoint_invocation.not_completion_gate -eq $true) "$Context default trigger candidate entrypoint must keep not_completion_gate=true."
    Assert-True ($TriggerActivity.runtime_entrypoint_invocation.stop_hook_controller -eq $false) "$Context default trigger candidate must not become Stop hook controller."
}

function Assert-DefaultMainLoopTriggerCandidateWorkflowResult {
    param($WorkflowResult, [string]$Context)
    $triggerActivity = Find-DefaultMainLoopTriggerCandidateActivity $WorkflowResult.activities
    Assert-True ($null -ne $triggerActivity) "$Context activities must include default_main_loop_trigger_candidate_activity."
    Assert-True ($null -ne $WorkflowResult.default_main_loop_trigger_candidate_activity) "$Context top-level default_main_loop_trigger_candidate_activity missing."
    Assert-True ($WorkflowResult.default_main_loop_trigger_candidate_runtime_enforced -eq $true) "$Context must mark default_main_loop_trigger_candidate_runtime_enforced=true."
    Assert-True ($WorkflowResult.default_main_loop_trigger_candidate_runtime_enforced_scope -eq "seed_cortex_temporal_default_main_loop_trigger_candidate_activity") "$Context default trigger candidate runtime scope mismatch."
    $triggerTemporalActivityLatestRef = [string]$WorkflowResult.default_main_loop_trigger_candidate_temporal_activity_latest_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($triggerTemporalActivityLatestRef)) "$Context default trigger candidate temporal activity latest ref missing."
    Assert-True (Test-Path -LiteralPath $triggerTemporalActivityLatestRef -PathType Leaf) "$Context default trigger candidate temporal activity latest ref must exist."
    Assert-True ($WorkflowResult.default_main_loop_trigger_candidate_not_execution_controller -eq $true) "$Context default trigger candidate must keep not_execution_controller=true."
    Assert-True ($WorkflowResult.default_main_loop_trigger_candidate_not_completion_gate -eq $true) "$Context default trigger candidate must keep not_completion_gate=true."
    Assert-True ($WorkflowResult.default_main_loop_trigger_candidate_validation_passed -eq $true) "$Context default trigger candidate validation_passed must be true."
    Assert-DefaultMainLoopTriggerCandidateActivityResult $triggerActivity $triggerTemporalActivityLatestRef $Context
}

function Assert-SchedulerInvocationPacketActivityResult {
    param($SchedulerActivity, [string]$ExpectedTemporalActivityLatestRef, [string]$Context)
    Assert-True ($null -ne $SchedulerActivity) "$Context scheduler_invocation_packet_activity result missing."
    Assert-True ($SchedulerActivity.runtime_enforced -eq $true) "$Context scheduler packet activity must be runtime_enforced=true."
    Assert-True ($SchedulerActivity.runtime_enforced_scope -eq "seed_cortex_temporal_scheduler_invocation_packet_activity") "$Context scheduler packet activity scope mismatch."
    $activityLatestRef = [string]$SchedulerActivity.scheduler_invocation_packet_temporal_activity_latest_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($activityLatestRef)) "$Context scheduler packet temporal activity latest ref missing."
    if (-not [string]::IsNullOrWhiteSpace($ExpectedTemporalActivityLatestRef)) {
        Assert-True ($activityLatestRef -eq $ExpectedTemporalActivityLatestRef) "$Context scheduler packet latest ref mismatch."
    }
    Assert-True (Test-Path -LiteralPath $activityLatestRef -PathType Leaf) "$Context scheduler packet temporal activity latest ref must exist."
    Assert-True ($SchedulerActivity.status -eq "activity_gate_checked") "$Context scheduler packet activity must be gate checked, not blocked."
    Assert-True ($SchedulerActivity.scheduler_invocation_packet_validation_passed -eq $true) "$Context scheduler packet validation_passed must be true."
    Assert-True ($SchedulerActivity.main_execution_loop_tick_activity_ref.runtime_enforced -eq $true) "$Context scheduler packet missing main tick activity ref."
    Assert-True ($SchedulerActivity.durable_parallel_wave_packet_activity_ref.runtime_enforced -eq $true) "$Context scheduler packet missing durable packet activity ref."
    Assert-True ($SchedulerActivity.default_main_loop_trigger_candidate_activity_ref.runtime_enforced -eq $true) "$Context scheduler packet missing default trigger activity ref."
    Assert-True ($SchedulerActivity.durable_parallel_wave_packet_activity_ref.actual_dispatch_refs.dp_sidecar_execution_port -eq "dp_sidecar_execution_port") "$Context scheduler durable activity ref missing DP sidecar execution port."
    Assert-True ($SchedulerActivity.durable_parallel_wave_packet_activity_ref.actual_dispatch_refs.dp_sidecar_execution_callable_entrypoint_bound -eq $true) "$Context scheduler durable activity ref missing DP callable entrypoint binding."
    Assert-True ($SchedulerActivity.durable_parallel_wave_packet_activity_ref.actual_dispatch_refs.dp_sidecar_execution_port_runner_ref.exists -eq $true) "$Context scheduler durable activity ref missing DP runner ref."
    Assert-True ($SchedulerActivity.packet_runtime_enforced -eq $false) "$Context scheduler packet overclaimed base packet runtime enforcement."
    Assert-True ($SchedulerActivity.packet_default_runtime_scheduler_invoked -eq $false) "$Context scheduler packet overclaimed default runtime scheduler invocation."
    Assert-True ($SchedulerActivity.not_execution_controller -eq $true) "$Context scheduler packet activity must keep not_execution_controller=true."
    Assert-True ($SchedulerActivity.runtime_entrypoint_invocation.not_completion_gate -eq $true) "$Context scheduler packet entrypoint must keep not_completion_gate=true."
}

function Assert-SchedulerInvocationPacketWorkflowResult {
    param($WorkflowResult, [string]$Context)
    $schedulerActivity = Find-SchedulerInvocationPacketActivity $WorkflowResult.activities
    Assert-True ($null -ne $schedulerActivity) "$Context activities must include scheduler_invocation_packet_activity."
    Assert-True ($null -ne $WorkflowResult.scheduler_invocation_packet_activity) "$Context top-level scheduler_invocation_packet_activity missing."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_runtime_enforced -eq $true) "$Context must mark scheduler_invocation_packet_runtime_enforced=true."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_runtime_enforced_scope -eq "seed_cortex_temporal_scheduler_invocation_packet_activity") "$Context scheduler packet runtime scope mismatch."
    $schedulerTemporalActivityLatestRef = [string]$WorkflowResult.scheduler_invocation_packet_temporal_activity_latest_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($schedulerTemporalActivityLatestRef)) "$Context scheduler packet temporal activity latest ref missing."
    Assert-True (Test-Path -LiteralPath $schedulerTemporalActivityLatestRef -PathType Leaf) "$Context scheduler packet temporal activity latest ref must exist."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_not_execution_controller -eq $true) "$Context scheduler packet must keep not_execution_controller=true."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_not_completion_gate -eq $true) "$Context scheduler packet must keep not_completion_gate=true."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_validation_passed -eq $true) "$Context scheduler packet validation_passed must be true."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_packet_runtime_enforced -eq $false) "$Context scheduler packet result overclaimed base packet runtime enforcement."
    Assert-True ($WorkflowResult.scheduler_invocation_packet_packet_default_runtime_scheduler_invoked -eq $false) "$Context scheduler packet result overclaimed default runtime scheduler invocation."
    Assert-SchedulerInvocationPacketActivityResult $schedulerActivity $schedulerTemporalActivityLatestRef $Context
}

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if ([string]::IsNullOrWhiteSpace($python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if ([string]::IsNullOrWhiteSpace($python)) {
    $python = "D:\XINAO_CLEAN_RUNTIME\tool_envs\mature-runtime-py\Scripts\python.exe"
}
Assert-True (Test-Path -LiteralPath $python -PathType Leaf) "Python executable not found for Temporal Codex workflow verifier."
$seedCortexTaskId = "xinao_seed_cortex_phase0_20260701"

$unit = Invoke-NativeCapture { & $python -m unittest tests.test_temporal_codex_task_workflow }
$unit.Output | Write-Output
if ($unit.ExitCode -ne 0) { throw "Temporal Codex task workflow unit tests failed." }

$workflowSource = Get-Content -LiteralPath (Join-Path $RepoRoot "services\agent_runtime\temporal_codex_task_workflow.py") -Raw -Encoding UTF8
$workflowTests = Get-Content -LiteralPath (Join-Path $RepoRoot "tests\test_temporal_codex_task_workflow.py") -Raw -Encoding UTF8
Assert-True ($workflowSource.Contains("SEGMENT_PASS_WITHOUT_NEXT_BOUNDED_WORKER")) "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 must name SEGMENT_PASS_WITHOUT_NEXT_BOUNDED_WORKER when PASS lacks a next bounded worker."
Assert-True ($workflowTests.Contains("test_ring_regression_segment_pass_without_next_worker_is_blocked")) "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 pytest coverage missing."
$ringPassPanelAssertionSeen = (
    $workflowTests.Contains("assertNotIn") -and
    $workflowTests.Contains('panel_payload["panel_lines_cn"]["blocked_line_cn"]') -and
    $workflowTests.Contains('panel_payload["panel_lines_cn"]["next_line_cn"]')
)
Assert-True $ringPassPanelAssertionSeen "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 must assert PASS panel does not wait for Grok leg2 verdict."
Assert-True ($workflowTests.Contains("test_segment_pass_ring_regression_dispatches_same_workflow_worker_and_panel")) "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 must cover PASS -> same workflow next worker."
Assert-True ($workflowTests.Contains("same_workflow_next_worker_dispatched")) "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 must assert same workflow next worker dispatch evidence."
Assert-True ($workflowTests.Contains("mainline_next_hop") -and $workflowTests.Contains("same_workflow_segment_pass_next_bounded_worker")) "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 must assert the PASS panel next-worker wording."
Assert-True ($workflowTests.Contains("assertEqual") -and $workflowTests.Contains("segment_audit_status_cn")) "RING_REGRESSION_SEGMENT_PASS_CONTINUE_V1 must assert the PASS panel is no longer waiting for Grok."

if (-not (Test-NetConnection 127.0.0.1 -Port 7233).TcpTestSucceeded) {
    & (Join-Path $RepoRoot "scripts\start_temporal_dev_server.ps1") | Write-Output
    Start-Sleep -Seconds 3
}

$blocked = Invoke-NativeCapture { & $python -m services.agent_runtime.temporal_codex_task_workflow `
    --task-id "verify_temporal_default_blocked" `
    --user-goal "verify default local-run is blocked" `
    --mode "partial" `
    --runtime-root $RuntimeRoot }
$blockedOutput = $blocked.Output
Assert-True ($blocked.ExitCode -ne 0) "Default Temporal workflow CLI without --live-temporal must be blocked."
Assert-True (($blockedOutput -join "`n") -match "BLOCKED_TEMPORAL_LIVE_ROUTE_REQUIRED") "Default block must name BLOCKED_TEMPORAL_LIVE_ROUTE_REQUIRED."

$localCompat = Invoke-NativeCapture { & $python -m services.agent_runtime.temporal_codex_task_workflow `
    --task-id $seedCortexTaskId `
    --user-goal "verify Seed Cortex Temporal durable packet workflow result binding" `
    --mode "partial" `
    --runtime-root $RuntimeRoot `
    --local-temporal-compat-rescue `
    --simulate-transient-failure }
$output = $localCompat.Output
Assert-True ($localCompat.ExitCode -eq 0) "Local Temporal compatibility rescue verifier command failed: $($output -join "`n")"
Assert-True (($output -join "`n") -match "SENTINEL:XINAO_TEMPORAL_CODEX_TASK_WORKFLOW_PASS") "Temporal Codex workflow sentinel missing."
$latest = Join-Path $RuntimeRoot "state\temporal_codex_task_workflow\latest.json"
$localCompatPayload = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($null -ne $localCompatPayload.activities -and @($localCompatPayload.activities).Count -gt 0) {
    Assert-DurableParallelWavePacketWorkflowResult $localCompatPayload "Local Temporal compatibility workflow result"
    Assert-DefaultMainLoopTriggerCandidateWorkflowResult $localCompatPayload "Local Temporal compatibility workflow result"
    Assert-SchedulerInvocationPacketWorkflowResult $localCompatPayload "Local Temporal compatibility workflow result"
} else {
    Write-Output "Local Temporal compatibility latest is a read model without activities; durable activity is verified by unit tests and live Temporal history."
}

$verificationTaskQueue = "xinao-codex-task-verify-durable-" + [Guid]::NewGuid().ToString("N")
$workerStateDir = Join-Path $RuntimeRoot "state\temporal_codex_task_workflow_verifier_worker"
New-Item -ItemType Directory -Force -Path $workerStateDir | Out-Null
$workerLogPath = Join-Path $workerStateDir "$verificationTaskQueue.stdout.log"
$workerErrPath = Join-Path $workerStateDir "$verificationTaskQueue.stderr.log"
$workerArgs = @(
    "-m",
    "services.agent_runtime.temporal_codex_task_workflow",
    "--worker",
    "--task-queue",
    $verificationTaskQueue,
    "--runtime-root",
    $RuntimeRoot
)
$workerProc = $null
try {
    $workerProc = Start-Process -FilePath $python -ArgumentList $workerArgs -WorkingDirectory $RepoRoot -WindowStyle Hidden -RedirectStandardOutput $workerLogPath -RedirectStandardError $workerErrPath -PassThru
    $pollerCount = 0
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $pollerRaw = & temporal task-queue describe --address 127.0.0.1:7233 --task-queue $verificationTaskQueue --output json --command-timeout 3s
        $poller = ($pollerRaw -join "`n") | ConvertFrom-Json
        $pollerCount = Get-PollerCount $poller
        if ($pollerCount -ge 1) { break }
        Start-Sleep -Seconds 1
    }
    Assert-True ($pollerCount -ge 1) "Temporal task queue $verificationTaskQueue must have a polling worker."

    $liveTaskId = $seedCortexTaskId
    $liveWorkflowId = "xinao-codex-task-$liveTaskId-verify-durable-" + [Guid]::NewGuid().ToString("N")
    $live = Invoke-NativeCapture { & $python -m services.agent_runtime.temporal_codex_task_workflow `
        --task-id $liveTaskId `
        --user-goal "verify live Temporal durable packet activity binding" `
        --mode "partial" `
        --runtime-root $RuntimeRoot `
        --task-queue $verificationTaskQueue `
        --workflow-id $liveWorkflowId `
        --live-temporal }
    $liveOutput = $live.Output
    Assert-True ($live.ExitCode -eq 0) "Live Temporal Codex workflow command failed: $($liveOutput -join "`n")"
    Assert-True (($liveOutput -join "`n") -match "SENTINEL:XINAO_TEMPORAL_CODEX_TASK_WORKFLOW_PASS") "Live Temporal Codex workflow sentinel missing."

    $payload = Get-Content -LiteralPath $latest -Raw -Encoding UTF8 | ConvertFrom-Json
    $allowedVerificationLevels = @("read_model_seen", "server_history_verified", "workflow_open")
    Assert-True (($allowedVerificationLevels -contains [string]$payload.verification_level)) "Live Temporal workflow verification level must be a supported G2 level."
    Assert-True ($payload.temporal_live_route -eq $true) "Verifier latest must come from live Temporal route."
    Assert-True (-not [string]::IsNullOrWhiteSpace($payload.workflow_run_id)) "Live Temporal workflow run id missing."
    $payloadFrontierOpen = (
        $payload.workflow_open -eq $true -or
        $payload.partial_frontier_open -eq $true -or
        $payload.current_task_owner.workflow_open -eq $true
    )
    Assert-True $payloadFrontierOpen "Live partial workflow must expose open frontier evidence."
    Assert-True ($payload.workflow_completed_is_not_user_complete -eq $true) "Workflow completed must not equal user completion."
    Assert-True ($payload.not_source_of_truth -eq $true) "Temporal workflow latest readback must not be source of truth."
    Assert-True ($payload.not_user_completion -eq $true) "Temporal workflow latest readback must not be user completion."
    $authorityBoundary = if ($payload.authority_boundary) { $payload.authority_boundary } else { $payload.current_task_owner.authority_boundary }
    Assert-True ($authorityBoundary.source_of_truth -eq "external_mature_runtime") "Temporal workflow authority boundary must point to external mature runtime."
    Assert-True ($authorityBoundary.not_source_of_truth -eq $true) "Temporal workflow authority boundary must demote latest readback source of truth."
    Assert-True ($authorityBoundary.not_user_completion -eq $true) "Temporal workflow authority boundary must demote user completion."
    Assert-True ($authorityBoundary.workflow_completed_is_not_user_complete -eq $true) "Temporal workflow authority boundary must separate workflow and user completion."
    Assert-True ($payload.completion_decision.status -eq "partial") "Open frontier workflow must remain partial."
    Assert-True ($payload.user_task_complete -eq $false) "Partial completion decision must keep user_task_complete=false."
    Assert-True ($payload.current_task_owner.task_id -eq $liveTaskId) "Current task owner must bind the live task id."
    Assert-True ($payload.current_task_owner.workflow_id -eq $payload.workflow_id) "Current task owner workflow id mismatch."
    Assert-True ($payload.current_task_owner.workflow_run_id -eq $payload.workflow_run_id) "Current task owner run id mismatch."
    Assert-True ($payload.current_task_owner.stop_gate_scope -eq "current_task_id_only") "Stop gate must be scoped to current task id."
    Assert-True ($payload.current_task_owner.not_completion_decision -eq $true) "Current task owner must not be a completion decision."
    Assert-True ($payload.worker_service_polling -eq $true) "Live route must require an existing polling worker service."
    Assert-True ($payload.worker_service_evidence.status -eq "poller_seen") "Worker service evidence must show poller_seen."
    Assert-True ($payload.legacy_continuation_policy -eq "legacy_rescue_only_not_mainline") "continuation.N must remain legacy rescue only."
    Assert-True (($payload.retry_policy.non_retryable_error_types -contains "XINAO_OBJECT_REPLACEMENT_DENIED")) "Object replacement deny must be non-retryable."
    Assert-True (($payload.retry_policy.retryable_error_types -contains "XINAO_TRANSIENT_TOOL_ERROR")) "Transient tool error must be retryable."
    $g2Ref = $payload.g2_temporal_server_verification_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($g2Ref)) "G2 verifier reference must be written."
    Assert-True (Test-Path -LiteralPath $g2Ref -PathType Leaf) "G2 verifier summary file must be available."
    $g2Payload = Get-Content -LiteralPath $g2Ref -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($g2Payload.server_bound -eq $true) "G2 verifier must confirm server-bound verify inputs."
    $g2FrontierOpen = (
        $g2Payload.workflow_open -eq $true -or
        $g2Payload.workflow_completed -eq $false
    )
    Assert-True $g2FrontierOpen "G2 verifier must confirm non-terminal/open frontier evidence for partial frontier."
    Assert-True ($g2Payload.workflow_completed -eq $false) "G2 verifier must confirm workflow not terminal in partial frontier."
    Assert-True (($allowedVerificationLevels -contains [string]$g2Payload.verification_level)) "G2 verification_level must be one of read_model_seen/server_history_verified/workflow_open."

    $events = @()
    $historyActivityTypes = @()
    $historyCompletionResults = @()
    $durableHistoryCompletion = $null
    $defaultTriggerHistoryCompletion = $null
    $schedulerHistoryCompletion = $null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $historyRaw = & temporal workflow show --address 127.0.0.1:7233 --workflow-id $payload.workflow_id --run-id $payload.workflow_run_id --output json
        $history = ($historyRaw -join "`n") | ConvertFrom-Json
        $events = @($history.events)
        if ($events.Count -eq 0 -and $history.history.events) { $events = @($history.history.events) }
        $historyActivityTypes = Get-TemporalActivityTypeNames $events
        $historyCompletionResults = Get-TemporalActivityCompletionResults $events
        $durableHistoryCompletion = @($historyCompletionResults | Where-Object { $_.ActivityType -eq "durable_parallel_wave_packet_activity" }) | Select-Object -First 1
        $defaultTriggerHistoryCompletion = @($historyCompletionResults | Where-Object { $_.ActivityType -eq "default_main_loop_trigger_candidate_activity" }) | Select-Object -First 1
        $schedulerHistoryCompletion = @($historyCompletionResults | Where-Object { $_.ActivityType -eq "scheduler_invocation_packet_activity" }) | Select-Object -First 1
        if (
            ($historyActivityTypes -contains "durable_parallel_wave_packet_activity") -and
            ($historyActivityTypes -contains "default_main_loop_trigger_candidate_activity") -and
            ($historyActivityTypes -contains "scheduler_invocation_packet_activity") -and
            $null -ne $durableHistoryCompletion -and
            $null -ne $defaultTriggerHistoryCompletion -and
            $null -ne $schedulerHistoryCompletion
        ) { break }
        Start-Sleep -Seconds 1
    }
    Assert-True ($events.Count -ge 1) "Temporal workflow show must return event history."
    Assert-True ($historyActivityTypes -contains "durable_parallel_wave_packet_activity") "Temporal history must show durable_parallel_wave_packet_activity was scheduled."
    Assert-True ($historyActivityTypes -contains "default_main_loop_trigger_candidate_activity") "Temporal history must show default_main_loop_trigger_candidate_activity was scheduled."
    Assert-True ($historyActivityTypes -contains "scheduler_invocation_packet_activity") "Temporal history must show scheduler_invocation_packet_activity was scheduled."
    Assert-True ($null -ne $durableHistoryCompletion) "Temporal history must contain durable_parallel_wave_packet_activity completion result."
    Assert-True ($null -ne $defaultTriggerHistoryCompletion) "Temporal history must contain default_main_loop_trigger_candidate_activity completion result."
    Assert-True ($null -ne $schedulerHistoryCompletion) "Temporal history must contain scheduler_invocation_packet_activity completion result."
    Assert-DurableParallelWavePacketActivityResult $durableHistoryCompletion.Result "" "Live Temporal history"
    Assert-DefaultMainLoopTriggerCandidateActivityResult $defaultTriggerHistoryCompletion.Result "" "Live Temporal history"
    Assert-SchedulerInvocationPacketActivityResult $schedulerHistoryCompletion.Result "" "Live Temporal history"

    $listRaw = & temporal workflow list --address 127.0.0.1:7233 --query "WorkflowId='$($payload.workflow_id)'"
    Assert-True (($listRaw -join "`n") -match [regex]::Escape($payload.workflow_id)) "Temporal workflow list must show the live workflow id."

    Write-Output "SENTINEL:XINAO_TEMPORAL_CODEX_TASK_WORKFLOW_PASS"
}
finally {
    if ($null -ne $workerProc) {
        $workerProc.Refresh()
        if (-not $workerProc.HasExited) {
            Stop-Process -Id $workerProc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*$verificationTaskQueue*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if (-not [string]::IsNullOrWhiteSpace($TargetTaskId)) {
    $targetTaskId = $TargetTaskId.Trim()
    $targetRuntimeRoot = $RuntimeRoot
    $targetCurrentOwner = Join-Path $targetRuntimeRoot "state\current_task_owner\$targetTaskId.json"
    if (-not (Test-Path -LiteralPath $targetCurrentOwner -PathType Leaf)) {
        $targetRuntimeRoot = "D:\XINAO_CLEAN_RUNTIME"
        $targetCurrentOwner = Join-Path $targetRuntimeRoot "state\current_task_owner\$targetTaskId.json"
    }
    Assert-True (Test-Path -LiteralPath $targetCurrentOwner -PathType Leaf) "Target task current_task_owner must exist for G2 segment gate verification."
    $targetGateOutputRaw = & $python -m services.agent_runtime.g2_temporal_server_gate_verifier `
        --task-id $targetTaskId `
        --runtime-root $targetRuntimeRoot 2>&1
    Assert-True ($LASTEXITCODE -eq 0) "Target G2 gate verifier must complete successfully."
    Assert-True (($targetGateOutputRaw -join "`n") -match "SENTINEL:XINAO_G2_SERVER_GATE_VERIFICATION_PASS") "Target G2 gate verifier sentinel missing."
    $targetGateOutputLine = $targetGateOutputRaw | Select-Object -First 1
    $targetGateOutput = $targetGateOutputLine | ConvertFrom-Json
    $targetGateRef = [string]$targetGateOutput.summary_ref
    Assert-True (-not [string]::IsNullOrWhiteSpace($targetGateRef)) "Target G2 gate evidence ref must be written."
    Assert-True (Test-Path -LiteralPath $targetGateRef -PathType Leaf) "Target G2 gate evidence file must exist."
    $targetG2Payload = Get-Content -LiteralPath $targetGateRef -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($allowedVerificationLevels -contains [string]$targetG2Payload.verification_level) "Target G2 evidence verification level must be one of read_model_seen/server_history_verified/workflow_open."
    Assert-True ($targetG2Payload.server_bound -eq $true) "Target G2 evidence must confirm server-bound verification against Temporal CLI."
    $targetFrontierOpen = (
        $targetG2Payload.workflow_open -eq $true -or
        $targetG2Payload.workflow_completed -eq $false
    )
    Assert-True $targetFrontierOpen "Target workflow must expose non-terminal/open frontier evidence for partial frontier verification."
    Assert-True ($targetG2Payload.worker_service_polling -eq $true) "Target task must show worker polling in gate evidence."
    Assert-True ($targetG2Payload.local_run_observed -eq $false) "Target G2 evidence must confirm local-run was not observed."
    $segment = $targetG2Payload.segment_gate
    Assert-True ($segment.segment_gate_source -eq "task_file") "Target segment gate must be evaluated from state/grok_l1_l2_segment_gate/tasks/{task_id}.json."
    Assert-True ($segment.verdict_file_present -eq $true) "Target segment gate requires state/grok_l1_l2_segment_gate/tasks/{task_id}.json."
    Assert-True ($segment.segment_audit_loop_expressible -eq $true) "Target segment gate must express audit-ready and WAITING_GROK/verdict loop state."
    Assert-True ($segment.segment_audit_loop_state -in @("AUDIT_READY_WAITING_GROK", "AUDIT_READY_VERDICT")) "Target segment loop must be audit-ready -> WAITING_GROK / verdict."
    Assert-True ($segment.segment_audit_ready -eq $true) "Target segment audit must be readiness flagged."
    Assert-True ($segment.workflow_waiting_grok_segment_audit -eq $true -or $segment.segment_audit_status -like "GROK_SEGMENT_AUDIT_*") "Target segment gate must express audit_ready->WAITING_GROK->verdict."
    Assert-True ($segment.dual_visible_and_backend_verdict -eq $true) "Target segment verdict must be dual_visible_and_backend."
    Assert-True ($segment.verdict_delivery_mode -eq "dual_visible_and_backend") "Target verdict_delivery_mode must be dual_visible_and_backend."
    Assert-True ($segment.backend_only_verdict_seen -ne $true) "Target segment gate must reject backend-only verdict path."
    Assert-True ($segment.grok_gate_task_present -eq $true) "Target segment task-scoped gate file should be present."
    $targetGrokTaskRef = Join-Path $targetRuntimeRoot "state\grok_l1_l2_segment_gate\tasks\$targetTaskId.json"
    Assert-True (Test-Path -LiteralPath $targetGrokTaskRef -PathType Leaf) "Target segment gate task file must exist."
    $targetGrokTask = Get-Content -LiteralPath $targetGrokTaskRef -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($targetGrokTask.segment_audit_ready -eq $true) "Target segment task file must be audit-ready."
    Assert-True (
        ($targetGrokTask.segment_audit_status -eq "WAITING_GROK_SEGMENT_AUDIT") -or
        ($targetGrokTask.segment_audit_status -like "GROK_SEGMENT_AUDIT_*") -or
        ($targetGrokTask.status -like "GROK_SEGMENT_AUDIT_*") -or
        ([string]$targetGrokTask.grok_verdict -in @("pass", "fail", "hold"))
    ) "Target segment task file must express WAITING_GROK or verdict status."
    Assert-True ($targetGrokTask.verdict_delivery_mode -eq "dual_visible_and_backend") "Target segment task file must enforce dual_visible_and_backend delivery."
    $targetCurrentOwnerPayload = Get-Content -LiteralPath $targetCurrentOwner -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($targetCurrentOwnerPayload.not_source_of_truth -eq $true) "Target current_task_owner projection must keep not_source_of_truth."
    Assert-True ($targetCurrentOwnerPayload.g2_temporal_server_verification_ref -eq $targetGateRef) "Target current_task_owner g2 evidence reference must be rewritten."
    Assert-True ($targetCurrentOwnerPayload.verification_level -in $allowedVerificationLevels) "Target current_task_owner must use normalized verification_level."
}
