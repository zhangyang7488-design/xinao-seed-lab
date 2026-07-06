[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$TemporalAddress = "127.0.0.1:7233",
    [string]$TaskQueue = "xinao-codex-task-default",
    [string]$WorkflowType = "TemporalCodexTaskWorkflow",
    [switch]$NoWrite,
    [switch]$NoCurrentIndexWrite
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = "python"
}

$argsList = @(
    "-m", "xinao_seedlab.cli.__main__",
    "--runtime-root", $RuntimeRoot,
    "--repo-root", $RepoRoot,
    "333-run-reconciler",
    "--runtime-root", $RuntimeRoot,
    "--repo-root", $RepoRoot,
    "--temporal-address", $TemporalAddress,
    "--task-queue", $TaskQueue,
    "--workflow-type", $WorkflowType
)
if ($NoWrite) {
    $argsList += "--no-write"
}
if ($NoCurrentIndexWrite) {
    $argsList += "--no-current-index-write"
}

& $python @argsList
exit $LASTEXITCODE
