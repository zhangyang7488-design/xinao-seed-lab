# SUNSET: L9_ledger — archived to scripts/_retired/verify_marathon/verify_worker_dispatch_ledger.ps1
param([string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME")
$ErrorActionPreference = "Stop"
$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
$py = "E:\XINAO_RESEARCH_WORKSPACES\S\.venv\Scripts\python.exe"
& $py -m xinao_seedlab.cli.__main__ thin-glue-status --runtime-root $RuntimeRoot --repo-root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m xinao_seedlab.cli.__main__ thin-glue-status --runtime-root $RuntimeRoot --repo-root $RepoRoot
exit $LASTEXITCODE

