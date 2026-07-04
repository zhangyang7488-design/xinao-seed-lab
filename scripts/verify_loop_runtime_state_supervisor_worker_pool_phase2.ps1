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

$taskId = "loop_runtime_state_supervisor_worker_pool_phase2_20260704"
$stateDir = Join-Path $RuntimeRoot "state\$taskId"
$latestPath = Join-Path $stateDir "latest.json"
$queuePath = Join-Path $stateDir "task_queue\latest.json"
$backgroundPath = Join-Path $stateDir "background_latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\$taskId.md"
$phase1LatestPath = Join-Path $RuntimeRoot "state\modular_dynamic_worker_pool_phase1\latest.json"
$watchdogPath = Join-Path $RuntimeRoot "state\overnight_supervisor_loop_phase0_batch_20260704\same_default_loop\background_latest.json"

$latest = Read-JsonFile $latestPath
$queue = Read-JsonFile $queuePath
$phase1Latest = Read-JsonFile $phase1LatestPath
$watchdog = Read-JsonFile $watchdogPath

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.loop_runtime_state_supervisor_worker_pool_phase2.v1") "schema_version mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_CODEX_S_LOOP_RUNTIME_STATE_PHASE2_V1") "sentinel mismatch."
Assert-True ([string]$latest.identity.task_id -eq $taskId) "task id mismatch."
Assert-True ([string]$latest.phase -eq "queue_consume_fan_in_recompute_next_frontier") "phase mismatch."

Assert-True ($null -ne $latest.active_workers) "active_workers missing."
Assert-True ($null -ne $latest.task_backlog) "task_backlog missing."
Assert-True ($null -ne $latest.ready_frontier) "ready_frontier missing."
Assert-True ($null -ne $latest.draft_staging) "draft_staging missing."
Assert-True ($null -ne $latest.merge_backlog) "merge_backlog missing."
Assert-True ($null -ne $latest.fan_in_backlog) "fan_in_backlog missing."
Assert-True ($null -ne $latest.evidence_backlog) "evidence_backlog missing."
Assert-True ($null -ne $latest.source_gaps) "source_gaps missing."
Assert-True ($null -ne $latest.blockers) "blockers missing."
Assert-True ($null -ne $latest.next_frontier) "next_frontier missing."
Assert-True ($null -ne $latest.capacity_by_lane_class) "capacity_by_lane_class missing."

Assert-True ([string]$latest.background.main_loop -eq "task_queue_worker_pool_consumer") "background main loop is not queue consumer."
Assert-True ($latest.background.queue_consumer_main_loop -eq $true) "queue consumer main loop flag missing."
Assert-True ($latest.background.thirty_minute_runner_is_watchdog_only -eq $true) "30 minute runner not downgraded in loop state."
Assert-True ($watchdog.watchdog_only -eq $true) "same_default runner missing watchdog_only."
Assert-True ($watchdog.not_main_loop -eq $true) "same_default runner missing not_main_loop."
Assert-True ($watchdog.not_completion_boundary -eq $true) "same_default runner missing not_completion_boundary."

Assert-True ([int]$latest.phase1_payload_summary.draft_count -gt 0) "draft_count missing."
Assert-True ([int]$latest.phase1_payload_summary.true_dp_draft_count -gt 0) "true DP draft count missing."
Assert-True ([int]$latest.phase1_payload_summary.true_dp_draft_count -gt [int]$latest.phase1_payload_summary.local_stub_draft_count) "local stub is masquerading as DP."
Assert-True ([int]$latest.phase1_payload_summary.staged_count -gt 0) "staged_count missing."
Assert-True ([int]$latest.phase1_payload_summary.merged_count -gt 0) "merged_count missing."
Assert-True ([int]$latest.phase1_payload_summary.spend_entry_count -gt 0) "spend ledger missing."
Assert-True (Test-Path -LiteralPath ([string]$latest.phase1_payload_summary.merge_artifact) -PathType Leaf) "merge artifact missing."

$dynamic = $latest.capacity_by_lane_class.dynamic_width_record
Assert-True ([int]$dynamic.target_width -ge 3) "target_width below 3."
Assert-True ([int]$dynamic.actual_dispatched_width -ge 3) "actual_dispatched_width below 3."
Assert-True ([int]$dynamic.actual_completed_width -ge 3) "actual_completed_width below 3."
Assert-True ([int]$dynamic.independent_task_count -ge 1) "independent_task_count missing."
Assert-True ([string]$dynamic.provider -ne "") "provider missing."
Assert-True ([string]$dynamic.model -ne "") "model missing."
Assert-True ($null -ne $dynamic.token_cost_spend) "token/cost spend missing."
Assert-True ($null -ne $dynamic.latency_ms) "latency missing."
Assert-True ([int]$dynamic.queue_depth -ge 0) "queue_depth missing."
Assert-True ($null -ne $dynamic.rate_limit_error) "rate_limit_error missing."
Assert-True ($null -ne $dynamic.retry_after) "retry_after missing."
Assert-True ([int]$dynamic.staged_count -gt 0) "dynamic staged_count missing."
Assert-True ([int]$dynamic.merged_count -gt 0) "dynamic merged_count missing."
Assert-True ($null -ne $dynamic.named_blocker) "dynamic named_blocker missing."

Assert-True ($latest.capacity_by_lane_class.dp_draft.draft_is_primary -eq $true) "draft is not primary."
Assert-True ([int]$latest.capacity_by_lane_class.dp_draft.draft_target -gt 0) "DP draft target missing."
Assert-True ($latest.capacity_by_lane_class.dp_search.search_is_main_task -eq $false) "search is main task."
Assert-True ($latest.capacity_by_lane_class.local_tool.local_stub_counts_as_real_dp -eq $false) "local stub counts as real DP."
Assert-True ($latest.capacity_by_lane_class.merge_accept.fan_in_limits_acceptance_not_dispatch -eq $true) "fan-in limits dispatch."

Assert-True ($latest.stop.derived -eq $true) "stop_allowed is not derived."
Assert-True ($latest.stop.manual_override_allowed -eq $false) "manual stop override incorrectly allowed."
Assert-True ($latest.stop.stop_allowed -eq $false) "stop_allowed must be false while backlog/next frontier exists."
Assert-True ($latest.stop.reason_flags.task_backlog -eq $true -or $latest.stop.reason_flags.ready_frontier -eq $true -or $latest.stop.reason_flags.retry_or_backoff_can_continue -eq $true) "stop false is not derived from backlog/frontier/retry."
Assert-True ([string]$latest.stop.stop_reason -like "continue_required*") "stop_reason is not continue_required."

Assert-True ([int]@($latest.next_frontier).Count -gt 0) "next_frontier missing."
Assert-True ([int]@($queue.entries).Count -gt 0) "task queue entries missing."
Assert-True ([string]$queue.consumer_model -eq "competing_consumers_with_lease") "queue consumer model mismatch."
Assert-True ($queue.not_30_minute_runner -eq $true) "queue incorrectly marked as 30 minute runner."
Assert-True ($phase1Latest.runtime_enforced -eq $true) "phase1 latest not runtime_enforced."
Assert-True ([string]$phase1Latest.runtime_enforced_scope -eq "seed_cortex_loop_runtime_state_supervisor_worker_pool_phase2") "phase1 latest not called by phase2 scope."

Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
Assert-True ($readback.Contains("consumer_alive")) "readback missing backend alive answer."
Assert-True ($readback.Contains("backlog")) "readback missing backlog answer."
Assert-True ($readback.Contains("merged")) "readback missing merge answer."
Assert-True ($readback.Contains("source_gaps")) "readback missing source gap answer."
Assert-True ($readback.Contains("stop_allowed")) "readback missing stop_allowed answer."
Assert-True ($readback.Contains("consume queued next_frontier")) "readback missing next machine action."

if (Test-Path -LiteralPath $backgroundPath -PathType Leaf) {
    $background = Read-JsonFile $backgroundPath
    Assert-True ($background.queue_consumer_main_loop -eq $true) "background is not queue consumer."
    Assert-True ($background.not_30_minute_runner -eq $true) "background is a 30 minute runner."
    Assert-True ([int]$background.pid -gt 0) "background pid missing."
    $process = Get-Process -Id ([int]$background.pid) -ErrorAction SilentlyContinue
    Assert-True ($null -ne $process) "phase2 background process is not alive."
}

Write-Output "loop_runtime_state_phase2_latest=$latestPath"
Write-Output "loop_runtime_state_phase2_queue=$queuePath"
Write-Output "loop_runtime_state_phase2_readback=$readbackPath"
Write-Output "loop_runtime_state_phase2_phase1_latest=$phase1LatestPath"
Write-Output "validation_result=PASS"
