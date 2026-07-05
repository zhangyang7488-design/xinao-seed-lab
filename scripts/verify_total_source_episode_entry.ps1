[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "",
    [string]$SourcePackage = "C:\Users\xx363\Desktop\新系统\新系统独立并行_自由发散外部研究总稿_20260701.txt",
    [string]$WaveId = "total-source-episode-entry-20260705",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

Assert-True (Test-Path -LiteralPath $SourcePackage -PathType Leaf) "SourcePackage missing: $SourcePackage"
if ([string]::IsNullOrWhiteSpace($Python)) {
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $Python = $venvPython
    } else {
        $Python = "python"
    }
}
$srcRoot = Join-Path $RepoRoot "src"
$oldPythonPath = [string]$env:PYTHONPATH
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
    "$srcRoot;$RepoRoot"
} else {
    "$srcRoot;$RepoRoot;$oldPythonPath"
}

$module = Join-Path $RepoRoot "services\agent_runtime\total_source_episode_entry.py"
$cli = Join-Path $RepoRoot "src\xinao_seedlab\cli\__main__.py"
$test = Join-Path $RepoRoot "tests\seedcortex\test_total_source_episode_entry.py"

& $Python -m py_compile $module $cli
Assert-True ($LASTEXITCODE -eq 0) "py_compile failed."

& $Python -m pytest -q $test
Assert-True ($LASTEXITCODE -eq 0) "pytest failed."

$output = & $Python -m xinao_seedlab.cli.__main__ `
    --runtime-root $RuntimeRoot `
    --repo-root $RepoRoot `
    total-source-episode-entry `
    --source-package $SourcePackage `
    --wave-id $WaveId
Assert-True ($LASTEXITCODE -eq 0) "CLI invoke failed."
$payload = ($output -join [Environment]::NewLine) | ConvertFrom-Json

Assert-True ($payload.schema_version -eq "xinao.codex_s.total_source_episode_entry.v1") "schema mismatch."
Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_TOTAL_SOURCE_EPISODE_ENTRY_READY") "sentinel mismatch."
Assert-True ($payload.theme_family -eq "episode_entry") "theme family mismatch."
Assert-True ($payload.validation.passed -eq $true) "validation failed."
Assert-True ($payload.workflow_entry.validation.checks.post_episodes_anchor_found -eq $true) "POST /episodes anchor missing."
Assert-True ($payload.workflow_entry.validation.checks.workflow_port_anchor_found -eq $true) "WorkflowPort anchor missing."
Assert-True ($payload.phase1_research_episode_started -eq $false) "Phase1 was started."
Assert-True ($payload.completion_claim_allowed -eq $false) "completion claim allowed."

foreach ($path in @(
    $payload.output_paths.runtime_latest,
    $payload.output_paths.wave_record,
    $payload.output_paths.workflow_entry,
    $payload.output_paths.episode_trace,
    $payload.output_paths.capability_manifest,
    $payload.output_paths.capability_invoke_latest,
    $payload.output_paths.readback_zh
)) {
    Assert-True (Test-Path -LiteralPath ([string]$path) -PathType Leaf) "Missing evidence: $path"
}

Write-Output "total_source_episode_entry_latest=$($payload.output_paths.runtime_latest)"
Write-Output "total_source_episode_entry_wave=$($payload.output_paths.wave_record)"
Write-Output "workflow_entry=$($payload.output_paths.workflow_entry)"
Write-Output "episode_trace=$($payload.output_paths.episode_trace)"
Write-Output "capability_invoke=$($payload.output_paths.capability_invoke_latest)"
Write-Output "readback_zh=$($payload.output_paths.readback_zh)"
Write-Output "validation_result=TOTAL_SOURCE_EPISODE_ENTRY_READY"
Write-Output "SENTINEL:XINAO_TOTAL_SOURCE_EPISODE_ENTRY_READY"
