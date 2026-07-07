param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
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

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Assert-True (Test-Path -LiteralPath $python -PathType Leaf) "Missing repo venv python."

Push-Location $RepoRoot
try {
    & $python -m services.agent_runtime.post_continue_as_new_status_refresh --runtime-root $RuntimeRoot --repo-root $RepoRoot
    Assert-True ($LASTEXITCODE -eq 0) "post_continue_as_new_status_refresh CLI failed."
}
finally {
    Pop-Location
}

$latestPath = Join-Path $RuntimeRoot "state\post_continue_as_new_status_refresh\latest.json"
$currentPath = Join-Path $RuntimeRoot "state\current_333_run_index\latest.json"
$boundedPath = Join-Path $RuntimeRoot "state\bounded_result_wait\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\post_continue_as_new_status_refresh_20260707.md"
$workflowPath = Join-Path $RepoRoot "services\agent_runtime\temporal_codex_task_workflow.py"

$latest = Read-JsonFile $latestPath
$current = Read-JsonFile $currentPath
$bounded = Read-JsonFile $boundedPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
$workflowSource = Get-Content -LiteralPath $workflowPath -Raw -Encoding UTF8

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.post_continue_as_new_status_refresh.v1") "Schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_POST_CONTINUE_AS_NEW_STATUS_REFRESH_READY") "Sentinel mismatch."
Assert-True ([string]$latest.task_id -eq "p0_010_post_continue_as_new_status_refresh") "task_id mismatch."
Assert-True ([string]$latest.status -eq "post_continue_as_new_status_refresh_ready") "Status is not ready."
Assert-True ($latest.post_continue_as_new_status_refresh_ready -eq $true) "Ready field false."
Assert-True ($latest.validation.passed -eq $true) "Validation failed."
Assert-True ([string]$latest.current_workflow_run_id -eq [string]$current.workflow_run_id) "Current run drift."
Assert-True ([string]$latest.bounded_result_wait_run_id -eq [string]$bounded.current_workflow_run_id) "Bounded run drift."
Assert-True ([string]$current.workflow_run_id -eq [string]$bounded.current_workflow_run_id) "current_333_run_index and bounded_result_wait are not aligned."
Assert-True ($readback -match "SENTINEL:XINAO_POST_CONTINUE_AS_NEW_STATUS_REFRESH_READY") "Readback sentinel missing."
Assert-True ($workflowSource -match "post_continue_as_new_status_refresh_activity") "Temporal workflow missing refresh activity."
Assert-True ($workflowSource -match "TEMPORAL_PATCH_SEED_CORTEX_POST_CONTINUE_STATUS_REFRESH") "Temporal workflow missing refresh patch marker."
Assert-True ($workflowSource -match "default_loop_continue_as_new_resume_state") "Temporal workflow missing Continue-As-New resume state."

Write-Output "post_continue_as_new_status_refresh_latest=$latestPath"
Write-Output "bounded_result_wait_latest=$boundedPath"
Write-Output "current_333_run_index_latest=$currentPath"
Write-Output "SENTINEL:XINAO_POST_CONTINUE_AS_NEW_STATUS_REFRESH_VERIFY_PASS"
