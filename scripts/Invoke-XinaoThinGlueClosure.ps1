# Run full thin-glue closure loop
param(
    [string]$Input = "",
    [switch]$NoDocker,
    [switch]$SkipGatewayProbe
)

$ErrorActionPreference = "Stop"
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$args = @("-m", "xinao_seedlab.cli.__main__", "thin-glue-closure")
if ($Input) { $args += @("--input", $Input) }
if ($NoDocker) { $args += "--no-docker" }
if ($SkipGatewayProbe) { $args += "--skip-gateway-probe" }
Set-Location $RepoRoot
& $py @args
exit $LASTEXITCODE