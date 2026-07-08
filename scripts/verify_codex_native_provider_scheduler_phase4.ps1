# SUNSET: L9_gateway — archived to scripts/_retired/verify_marathon/verify_codex_native_provider_scheduler_phase4.ps1
param([string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME")
$ErrorActionPreference = "Stop"
$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
$py = "E:\XINAO_RESEARCH_WORKSPACES\S\.venv\Scripts\python.exe"
& $py -m xinao_seedlab.cli.__main__ thin-glue-provider --runtime-root $RuntimeRoot --repo-root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m xinao_seedlab.cli.__main__ thin-glue-status --runtime-root $RuntimeRoot --repo-root $RepoRoot
exit $LASTEXITCODE

