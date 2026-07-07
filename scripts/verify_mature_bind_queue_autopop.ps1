param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$TaskPackageRoot = "C:\Users\xx363\Desktop\新系统"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-AcceptedDecisionsForCandidate {
    param([string]$RuntimeRoot, [string]$CandidateId)
    $paths = @()
    $latest = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
    if (Test-Path -LiteralPath $latest -PathType Leaf) { $paths += $latest }
    $episodesRoot = Join-Path $RuntimeRoot "runs\episodes"
    if (Test-Path -LiteralPath $episodesRoot -PathType Container) {
        $paths += @(Get-ChildItem -LiteralPath $episodesRoot -Recurse -Filter artifact_acceptance.json -File | ForEach-Object { $_.FullName })
    }
    $matches = @()
    foreach ($path in $paths) {
        $payload = Read-JsonFile $path
        foreach ($decision in @($payload.decisions)) {
            if ([string]$decision.candidate_id -eq $CandidateId -and [string]$decision.status -eq "accepted") {
                $matches += $decision
            }
        }
    }
    return @($matches)
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Assert-True (Test-Path -LiteralPath $python -PathType Leaf) "Missing repo venv python."

& $python -m services.agent_runtime.mature_bind_queue_autopop --runtime-root $RuntimeRoot --repo-root $RepoRoot --task-package-root $TaskPackageRoot --exclude-task-id p0_012_mature_bind_queue_autopop_next_task
Assert-True ($LASTEXITCODE -eq 0) "mature_bind_queue_autopop CLI failed."

$taskId = "p0_012_mature_bind_queue_autopop_next_task"
$latestPath = Join-Path $RuntimeRoot "state\mature_bind_queue_autopop\latest.json"
$signalPath = Join-Path $RuntimeRoot "state\task_control_signals\mature_bind_queue_autopop_next_task.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.mature_bind_queue_autopop\manifest.json"
$currentPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$latest = Read-JsonFile $latestPath
$manifest = Read-JsonFile $manifestPath
$current = Read-JsonFile $currentPath
$accepted = @(Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId | Where-Object { [string]$_.artifact_acceptance_decision -eq "accepted_for_binding" })

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.mature_bind_queue_autopop.v1") "Schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_MATURE_BIND_QUEUE_AUTOPOP_READY") "Sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "task_id mismatch."
Assert-True ([string]$latest.status -eq "mature_bind_queue_autopop_ready") "Status is not ready."
Assert-True ($latest.mature_bind_queue_autopop_ready -eq $true) "Ready field false."
Assert-True ($latest.validation.passed -eq $true) "Validation failed."
Assert-True ([string]$manifest.provider_id -eq "codex_s.mature_bind_queue_autopop") "Manifest provider mismatch."
Assert-True ($accepted.Count -ge 1) "AAQ did not accept P0-012."
Assert-True ([string]$latest.workflow_ref.workflow_id -eq [string]$current.workflow_id) "Workflow id drift."

if ($latest.queue_empty -eq $false) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.next_mature_bind_task_id)) "Queue not empty but no next task."
    Assert-True (Test-Path -LiteralPath $signalPath -PathType Leaf) "Signal file missing."
    $signal = Read-JsonFile $signalPath
    Assert-True ([string]$signal.workflow_id -eq [string]$current.workflow_id) "Signal workflow id drift."
    Assert-True ([string]$signal.workflow_run_id -eq [string]$current.workflow_run_id) "Signal workflow run id drift."
    Assert-True ($signal.frontier_auto_continue_allowed -eq $false) "Signal enables frontier auto-continue."
    Assert-True ($signal.disable_next_frontier_continuation_supervisor -eq $true) "Signal does not disable next frontier supervisor."
    Assert-True ($signal.execute_worker_turn -eq $false) "Autopop signal directly enables worker turn."
    Assert-True ([string]$signal.mature_bind_task.task_id -eq [string]$latest.next_mature_bind_task_id) "Signal task mismatch."
}

Write-Output "mature_bind_queue_autopop_latest=$latestPath"
Write-Output "signal=$signalPath"
Write-Output "SENTINEL:XINAO_MATURE_BIND_QUEUE_AUTOPOP_VERIFY_PASS"
