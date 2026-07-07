param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$TaskPackageRoot = "",
    [switch]$DispatchWorkers
)

if ([string]::IsNullOrWhiteSpace($TaskPackageRoot)) {
    $TaskPackageRoot = [Environment]::GetEnvironmentVariable("XINAO_TASK_PACKAGE_ROOT")
}
if ([string]::IsNullOrWhiteSpace($TaskPackageRoot)) {
    $TaskPackageRoot = Join-Path $env:USERPROFILE "Desktop"
    $TaskPackageRoot = Join-Path $TaskPackageRoot ([char]0x65B0 + [string][char]0x7CFB + [string][char]0x7EDF)
}

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

$pythonArgs = @(
    "-m", "services.agent_runtime.v4pro_supervisor_orchestrator",
    "--runtime-root", $RuntimeRoot,
    "--repo-root", $RepoRoot,
    "--task-package-root", $TaskPackageRoot
)
if ($DispatchWorkers) { $pythonArgs += "--dispatch-workers" }

Push-Location $RepoRoot
try {
    & $python @pythonArgs
    Assert-True ($LASTEXITCODE -eq 0) "v4pro_supervisor_orchestrator CLI failed."
}
finally {
    Pop-Location
}

$taskId = "p0_014_v4pro_supervisor_orchestrator"
$latestPath = Join-Path $RuntimeRoot "state\v4pro_supervisor_orchestrator\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\v4pro_supervisor_orchestrator_20260707.md"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.v4pro_supervisor_orchestrator\manifest.json"
$latest = Read-JsonFile $latestPath
$manifest = Read-JsonFile $manifestPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.v4pro_supervisor_orchestrator.v1") "Schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_V4PRO_SUPERVISOR_ORCHESTRATOR_READY") "Sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "task_id mismatch."
Assert-True ($latest.is_execution_controller -eq $true) "Must be execution controller."
Assert-True ($latest.not_execution_controller -eq $false) "not_execution_controller must be false."
Assert-True ($latest.dp_is_second_brain -eq $false) "DP must not be second brain."
Assert-True ($latest.v4pro_supervisor_orchestrator_ready -eq $true) "Orchestrator not ready."
Assert-True (@($latest.mature_architecture_refs).Count -ge 3) "Mature architecture refs missing."
Assert-True (@($latest.orchestration_plan).Count -ge 2) "Orchestration plan missing."
Assert-True ([string]$latest.execution_controller.submit_status -in @("submitted", "not_submitted")) "submit_status must be explicit."

if ([string]$latest.execution_controller.submit_status -ne "submitted") {
    Assert-True ($latest.execution_controller.submitted -eq $false) "Must not claim submitted without closure."
}

Assert-True ([string]$manifest.provider_id -eq "codex_s.v4pro_supervisor_orchestrator") "Manifest provider mismatch."
Assert-True ($readback -match "SENTINEL:XINAO_V4PRO_SUPERVISOR_ORCHESTRATOR_READY") "Readback sentinel missing."

Write-Output "v4pro_supervisor_orchestrator_latest=$latestPath"
Write-Output "readback=$readbackPath"
Write-Output "SENTINEL:XINAO_V4PRO_SUPERVISOR_ORCHESTRATOR_VERIFY_PASS"