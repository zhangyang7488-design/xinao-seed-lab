param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$TaskPackageRoot = ""
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

Push-Location $RepoRoot
try {
    & $python -m services.agent_runtime.v4pro_mature_bind_execution_controller `
        --runtime-root $RuntimeRoot `
        --repo-root $RepoRoot `
        --task-package-root $TaskPackageRoot
    Assert-True ($LASTEXITCODE -eq 0) "v4pro_mature_bind_execution_controller CLI failed."
}
finally {
    Pop-Location
}

$taskId = "p0_013_v4pro_mature_bind_execution_controller"
$latestPath = Join-Path $RuntimeRoot "state\v4pro_mature_bind_execution_controller\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\v4pro_mature_bind_execution_controller_20260707.md"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.v4pro_mature_bind_execution_controller\manifest.json"
$latest = Read-JsonFile $latestPath
$manifest = Read-JsonFile $manifestPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.v4pro_mature_bind_execution_controller.v1") "Schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_READY") "Sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "task_id mismatch."
Assert-True ($latest.is_execution_controller -eq $true) "Must be execution controller."
Assert-True ($latest.not_execution_controller -eq $false) "not_execution_controller must be false."
Assert-True ($latest.completion_claim_allowed -eq $false) "completion_claim_allowed must stay false."
Assert-True ($latest.v4pro_mature_bind_execution_controller_ready -eq $true) "Controller not ready."

if ($latest.queue_empty -eq $true) {
    Assert-True ([string]$latest.controller_state -eq "idle") "Empty queue must be idle."
} else {
    Assert-True ([string]$latest.submit_status -in @("submitted", "not_submitted")) "submit_status must be explicit."
    if ([string]$latest.submit_status -ne "submitted") {
        Assert-True ($latest.submitted -eq $false) "Must not claim submitted without closure."
        if ($latest.enqueue_ok -eq $true) {
            Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.named_blocker)) "Enqueued-but-not-submitted must name blocker."
        } else {
            Assert-True ([string]$latest.controller_state -eq "blocked") "Failed prerequisites must be blocked."
            Assert-True (-not [string]::IsNullOrWhiteSpace([string]$latest.named_blocker)) "Blocked controller must name blocker."
        }
    }
}

Assert-True ([string]$manifest.provider_id -eq "codex_s.v4pro_mature_bind_execution_controller") "Manifest provider mismatch."
Assert-True ($manifest.is_execution_controller -eq $true) "Manifest must mark execution controller."
Assert-True ($readback -match "SENTINEL:XINAO_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_READY") "Readback sentinel missing."
Assert-True ($readback -match "enqueue_ok") "Readback must distinguish queue vs submit."

Write-Output "v4pro_mature_bind_execution_controller_latest=$latestPath"
Write-Output "readback=$readbackPath"
Write-Output "SENTINEL:XINAO_V4PRO_MATURE_BIND_EXECUTION_CONTROLLER_VERIFY_PASS"