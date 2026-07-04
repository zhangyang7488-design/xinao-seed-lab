param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$taskId = "temporal_activity_no_window_dp_worker_pool_phase3_20260704"
$stateDir = Join-Path $RuntimeRoot "state\$taskId"
$latestPath = Join-Path $stateDir "latest.json"
$canonicalLoopStatePath = Join-Path $RuntimeRoot "state\loop_runtime_state\latest.json"
$activityTracePath = Join-Path $stateDir "activity_trace\latest.json"
$legacyRunnerPath = Join-Path $stateDir "legacy_runner_downgrade\latest.json"
$noWindowPath = Join-Path $stateDir "no_window_execution\latest.json"
$eventQueuePath = Join-Path $stateDir "event_queue\latest.json"
$workerLedgerPath = Join-Path $RuntimeRoot "state\worker_dispatch_ledger\$taskId.latest.json"
$toolTracePath = Join-Path $RuntimeRoot "state\tool_trace_evidence\$taskId.latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\$taskId.md"
$startWorkerScript = Join-Path $RepoRoot "scripts\Start-XinaoTemporalCodexWorker.ps1"

$latest = Read-JsonFile $latestPath
$canonical = Read-JsonFile $canonicalLoopStatePath
$activityTrace = Read-JsonFile $activityTracePath
$legacyRunner = Read-JsonFile $legacyRunnerPath
$noWindow = Read-JsonFile $noWindowPath
$eventQueue = Read-JsonFile $eventQueuePath
$workerLedger = Read-JsonFile $workerLedgerPath
$toolTrace = Read-JsonFile $toolTracePath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
$startWorkerText = Get-Content -LiteralPath $startWorkerScript -Raw -Encoding UTF8

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.temporal_activity_no_window_dp_worker_pool_phase3.v1") "latest schema mismatch."
Assert-True ([string]$canonical.schema_version -eq "xinao.codex_s.temporal_activity_no_window_dp_worker_pool_phase3.v1") "canonical loop runtime schema mismatch."
Assert-True ([string]$latest.identity.task_id -eq $taskId) "latest task_id mismatch."
Assert-True ([string]$canonical.identity.task_id -eq $taskId) "canonical task_id mismatch."

Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.temporal.workflow_id)) "workflow_id missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.temporal.run_id)) "run_id missing."
Assert-True ([string]$latest.temporal.activity_name -eq "loop_runtime_state_update_activity") "loop state activity name mismatch."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.temporal.task_queue)) "task_queue missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.temporal.worker_identity)) "worker_identity missing."
Assert-True ($latest.temporal.temporal_owner -eq $true) "Temporal owner flag missing."
Assert-True ($latest.temporal.foreground_s_direct_runner -eq $false) "Foreground S incorrectly marked as backend runner."
Assert-True ($latest.temporal.event_queue_self_chain_enabled -eq $true) "Temporal event queue self-chain is not enabled."
Assert-True ([int]$latest.temporal.max_event_waves_per_run -ge 1) "max_event_waves_per_run missing."
Assert-True ([string]$activityTrace.activity -eq "dp_worker_pool_wave_activity") "DP activity trace missing."

Assert-True ($latest.background.event_queue_driven -eq $true) "Background is not event queue driven."
Assert-True ([string]$latest.background.main_loop -eq "temporal_activity_event_queue_loop") "Main loop is not Temporal activity event queue."
Assert-True ($latest.background.not_30_minute_runner -eq $true) "Main loop marked as 30 minute runner."
Assert-True ($latest.background.sleep_seconds_1800_default_main_loop_allowed -eq $false) "sleep 1800 allowed as default."
Assert-True ($latest.background.fixed_interval_default_loop_allowed -eq $false) "fixed interval loop allowed."
Assert-True ($eventQueue.not_30_minute_runner -eq $true) "Event queue marked as 30 minute runner."
Assert-True ($eventQueue.sleep_seconds_1800_default_main_loop_allowed -eq $false) "Event queue allows sleep 1800 default."

Assert-True ($legacyRunner.runner_30min_cancelled_or_frozen -eq $true) "30min runner was not frozen."
Assert-True ($legacyRunner.sleep_1800_default_main_loop_allowed -eq $false) "legacy downgrade allows sleep 1800."
Assert-True ($legacyRunner.same_default_loop_reference_only -eq $true) "same_default loop not reference-only."
Assert-True ($legacyRunner.overnight_runner_reference_only -eq $true) "overnight runner not reference-only."
foreach ($runner in @($legacyRunner.observed)) {
    Assert-True ($runner.not_main_loop -eq $true) "legacy runner not_main_loop missing."
    Assert-True ($runner.not_task_owner -eq $true) "legacy runner not_task_owner missing."
    Assert-True ($runner.not_watch_owner -eq $true) "legacy runner not_watch_owner missing."
    Assert-True ($runner.not_completion_boundary -eq $true) "legacy runner not_completion_boundary missing."
    Assert-True ($runner.reference_only -eq $true) "legacy runner reference_only missing."
}

Assert-True ($noWindow.windows_no_window_required -eq $true) "No-window contract missing."
Assert-True ($noWindow.powershell_start_process_windowstyle_hidden_required -eq $true) "PowerShell hidden requirement missing."
Assert-True ($noWindow.start_worker_script_hidden -eq $true) "Start worker script not recognized as hidden."
Assert-True ($startWorkerText.Contains("-WindowStyle Hidden")) "Start worker script does not use -WindowStyle Hidden."

$summary = $latest.phase1_payload_summary
Assert-True ([int]$summary.actual_dispatched_width -ge 3) "actual_dispatched_width < 3."
Assert-True ([int]$summary.actual_completed_width -ge 1) "actual_completed_width < 1."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$summary.target_width_source)) "target_width_source missing."
Assert-True ([string]$summary.target_width_source -like "dynamic_width_scheduler*") "target_width_source is not dynamic."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$summary.width_decision_reason)) "width_decision_reason missing."
Assert-True ($summary.recomputed_each_wave -eq $true) "width was not marked recomputed_each_wave."
Assert-True ([int]$summary.draft_count -gt 0) "draft_count is not positive."
Assert-True ([int]$summary.staged_count -gt 0) "staged_count is not positive."
Assert-True (([int]$summary.merged_count -ge 1) -or ([string]$summary.named_blocker)) "Neither merged artifact nor named blocker is present."
Assert-True (([int]$summary.true_dp_draft_count -gt [int]$summary.local_stub_draft_count) -or ([string]$summary.named_blocker)) "local stub appears to count as DP success."

Assert-True ($latest.draft_staging.staged_count -gt 0) "LoopRuntimeState staged_count missing."
Assert-True (($latest.draft_staging.merged_count -gt 0) -or ([string]$summary.named_blocker)) "LoopRuntimeState merged_count missing without blocker."
Assert-True ($latest.stop.derived -eq $true) "stop_allowed is not derived."
Assert-True ($latest.stop.computed_from_refs.Count -gt 0) "stop computed_from_refs missing."
Assert-True ([string]$latest.capacity_by_lane_class.dynamic_width_record.target_width_source -like "dynamic_width_scheduler*") "capacity dynamic width source missing."
Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.capacity_by_lane_class.dynamic_width_record.width_decision_reason)) "capacity width_decision_reason missing."
Assert-True ($latest.capacity_by_lane_class.dynamic_width_record.recomputed_each_wave -eq $true) "capacity width not recomputed."
Assert-True ($latest.capacity_by_lane_class.dynamic_width_record.fixed_20_or_50_used -eq $false) "capacity still flags fixed 20/50."
if (@($latest.task_backlog).Count -gt 0 -or @($latest.ready_frontier).Count -gt 0 -or @($latest.next_frontier).Count -gt 0) {
    Assert-True ($latest.stop.stop_allowed -eq $false) "stop_allowed must be false with backlog/frontier."
}

Assert-True ($workerLedger.dispatch_entries.Count -ge 3) "worker dispatch ledger has too few entries."
Assert-True ($toolTrace.provider_invocation_ref_count -ge 1) "tool trace provider invocation refs missing."
Assert-True ([string]$latest.evidence_ledger.loop_runtime_state_ref -eq $canonicalLoopStatePath) "loop runtime ref mismatch."

foreach ($needle in @("event_queue_self_chain", "runner_30min", "main_trigger", "backend_has_work_immediate_consume", "black_window", "dp_wave", "width_decision", "stop_allowed", "next_machine_action")) {
    Assert-True ($readback.Contains($needle)) "readback missing $needle."
}

Write-Output "temporal_activity_phase3_latest=$latestPath"
Write-Output "loop_runtime_state_latest=$canonicalLoopStatePath"
Write-Output "event_queue_latest=$eventQueuePath"
Write-Output "legacy_runner_downgrade=$legacyRunnerPath"
Write-Output "worker_dispatch_ledger=$workerLedgerPath"
Write-Output "tool_trace_evidence=$toolTracePath"
Write-Output "readback=$readbackPath"
Write-Output "phase3_temporal_activity_no_window_dp_worker_pool=PASS"
