# closure_test_v1 — 一次性全链测试闭环（§7 架构）
param(
    [string]$InputPath = "",
    [switch]$NoDocker,
    [switch]$Temporal
)

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Set-Location $RepoRoot

$cliArgs = @("-m", "services.agent_runtime.closure_test_workflow")
if ($InputPath) { $cliArgs += @("--input", $InputPath) }
else { $cliArgs += @("--input", (Join-Path $RepoRoot "materials\closure_test_input.md")) }
if ($NoDocker) { $cliArgs += "--no-docker" }
if ($Temporal) { $cliArgs += "--temporal" }

& $py @cliArgs
exit $LASTEXITCODE