# SUNSET: L9_worker_pool — archived to scripts/_retired/verify_marathon/verify_modular_dynamic_worker_pool_phase1.ps1
param([string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME")
$ErrorActionPreference = "Stop"
$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
$py = "E:\XINAO_RESEARCH_WORKSPACES\S\.venv\Scripts\python.exe"
& $py -m xinao_seedlab.cli.__main__ thin-glue-worker-pool --runtime-root $RuntimeRoot --repo-root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m xinao_seedlab.cli.__main__ thin-glue-status --runtime-root $RuntimeRoot --repo-root $RepoRoot
exit $LASTEXITCODE

