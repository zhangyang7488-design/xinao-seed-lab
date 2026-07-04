param(
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$TaskId = "pre_pass_audit_loop_20260704",
    [string]$WaveId = "pre-pass-audit-loop-hardmode",
    [string]$CandidateJson = ""
)

$ErrorActionPreference = "Stop"

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = (Get-Command python).Source
}

$args = @(
    "-m",
    "services.agent_runtime.pre_pass_audit_loop",
    "--repo-root",
    $RepoRoot,
    "--runtime-root",
    $RuntimeRoot,
    "--task-id",
    $TaskId,
    "--wave-id",
    $WaveId
)
if ($CandidateJson.Trim()) {
    $args += @("--candidate-json", $CandidateJson)
}

& $python @args
exit $LASTEXITCODE
