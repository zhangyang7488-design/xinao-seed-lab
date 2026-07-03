param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TaskQueue = "xinao-codex-task-default",
    [string]$TemporalAddress = "127.0.0.1:7233",
    [string]$TaskName = "XINAO Seed Cortex S Temporal Worker"
)

$ErrorActionPreference = "Stop"

$stateDir = Join-Path $RuntimeRoot "state\temporal_codex_task_worker"
$pidPath = Join-Path $stateDir "worker.pid"
$evidencePath = Join-Path $stateDir "status.json"

$workerPid = $null
$processAlive = $false
if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $rawPid = (Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8).Trim()
    if ($rawPid -match '^\d+$') {
        $workerPid = [int]$rawPid
        $processAlive = [bool](Get-Process -Id $workerPid -ErrorAction SilentlyContinue)
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskQueueDescribe = $null
$taskQueueDescribeError = ""
try {
    $raw = & temporal task-queue describe --address $TemporalAddress --task-queue $TaskQueue --output json --command-timeout 10s 2>&1
    if ($LASTEXITCODE -eq 0) {
        $taskQueueDescribe = ($raw -join "`n") | ConvertFrom-Json
    } else {
        $taskQueueDescribeError = ($raw -join "`n")
    }
} catch {
    $taskQueueDescribeError = $_.Exception.Message
}

$pollerCount = 0
if ($taskQueueDescribe -and $taskQueueDescribe.pollers) {
    $pollerCount = @($taskQueueDescribe.pollers).Count
}

$workflowListRaw = ""
try {
    $workflowListRaw = (& temporal workflow list --address $TemporalAddress --query "TaskQueue='$TaskQueue'" 2>&1) -join "`n"
} catch {
    $workflowListRaw = $_.Exception.Message
}

$payload = [ordered]@{
    schema_version = "xinao.temporal_codex_task_worker.status.v1"
    status = if ($pollerCount -gt 0) { "polling" } elseif ($processAlive) { "process_alive_poller_not_seen" } else { "not_running" }
    runtime_root = $RuntimeRoot
    task_queue = $TaskQueue
    temporal_address = $TemporalAddress
    pid = $workerPid
    process_alive = $processAlive
    scheduled_task_name = $TaskName
    scheduled_task_registered = [bool]$task
    pollers_seen = $pollerCount
    worker_polling_verify_command = "temporal task-queue describe --address $TemporalAddress --task-queue $TaskQueue --output json"
    workflow_list_verify_command = "temporal workflow list --address $TemporalAddress --query `"TaskQueue='$TaskQueue'`""
    task_queue_describe_error = $taskQueueDescribeError
    workflow_list_tail = if ($workflowListRaw.Length -gt 2000) { $workflowListRaw.Substring($workflowListRaw.Length - 2000) } else { $workflowListRaw }
    generated_at = (Get-Date).ToString("o")
    route_profile = "seed_cortex_phase0"
    old_clean_runtime_authority = $false
    not_source_of_truth = $true
    not_user_completion = $true
    not_completion_decision = $true
}

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidencePath -Encoding UTF8
$payload | ConvertTo-Json -Depth 10
