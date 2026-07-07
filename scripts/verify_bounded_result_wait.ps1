param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
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
    if (Test-Path -LiteralPath $latest -PathType Leaf) {
        $paths += $latest
    }
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
    return $matches
}

$taskId = "p0_009_bounded_result_wait"
$latestPath = Join-Path $RuntimeRoot "state\bounded_result_wait\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\bounded_result_wait_20260707.md"
$continuityPath = Join-Path $RuntimeRoot "state\codex_333_stateful_continuity_router\latest.json"
$driverPath = Join-Path $RuntimeRoot "state\root_intent_loop_driver\latest.json"
$currentPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.bounded_result_wait\manifest.json"

$latest = Read-JsonFile $latestPath
$continuity = Read-JsonFile $continuityPath
$driver = Read-JsonFile $driverPath
$current = Read-JsonFile $currentPath
$manifest = Read-JsonFile $manifestPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
$aaqMatches = Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.bounded_result_wait.v1") "Schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_BOUNDED_RESULT_WAIT_READY") "Sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "task_id mismatch."
Assert-True ([string]$latest.status -eq "bounded_result_wait_ready") "Status is not ready."
Assert-True ($latest.bounded_result_wait_ready -eq $true) "bounded_result_wait_ready is false."
Assert-True ($latest.validation.passed -eq $true) "Validation did not pass."
Assert-True ($latest.completion_claim_allowed -eq $false) "Completion claim allowed."
Assert-True ([string]$latest.current_workflow_id -eq [string]$current.workflow_id) "Workflow id drift."
Assert-True ([string]$latest.current_workflow_run_id -eq [string]$current.workflow_run_id) "Workflow run id drift."
Assert-True ([string]$driver.workflow_id -eq [string]$current.workflow_id) "Driver workflow id drift."
Assert-True ([string]$driver.workflow_run_id -eq [string]$current.workflow_run_id) "Driver workflow run id drift."
Assert-True ($readback -match "SENTINEL:XINAO_BOUNDED_RESULT_WAIT_READY") "Readback sentinel missing."
Assert-True ($readback -match "current_state") "Readback missing current_state section."
Assert-True ($readback.Length -gt 120) "Readback too short for Chinese status answer."

$continuityText = Get-Content -LiteralPath $continuityPath -Raw -Encoding UTF8
$workerPolling = [string]$current.worker_status.status -eq "polling"
if ($workerPolling) {
    Assert-True ($continuityText -notmatch "TEMPORAL_WORKER_NOT_POLLING") "Continuity router still carries stale worker blocker."
}

if ($aaqMatches.Count -gt 0) {
    $accepted = $false
    foreach ($decision in $aaqMatches) {
        if ([string]$decision.artifact_acceptance_decision -eq "accepted_for_delivery") {
            $accepted = $true
        }
    }
    Assert-True $accepted "AAQ did not accept p0_009 as accepted_for_delivery."
}

Write-Host "SENTINEL:XINAO_BOUNDED_RESULT_WAIT_VERIFY_PASS"