# 薄胶全链冒烟 — L0/L4/L9/L3/L5 + closure + Temporal（不停，一条跑完）
param(
    [switch]$SkipTemporal,
    [switch]$NoDocker
)

$ErrorActionPreference = "Stop"
$env:LITELLM_MASTER_KEY = if ($env:LITELLM_MASTER_KEY) { $env:LITELLM_MASTER_KEY } else { "sk-xinao-thin-glue-local" }
$RepoRoot = if ($env:XINAO_CODEX_S_REPO_ROOT) { $env:XINAO_CODEX_S_REPO_ROOT } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }
$py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Set-Location $RepoRoot

Write-Host "== pytest thin-glue + closure =="
& $py -m pytest tests/test_thin_glue_stack.py tests/test_closure_test_workflow.py -q --tb=line
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== thin-glue local =="
$tgArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue")
if ($NoDocker) { $tgArgs += "--no-docker" }
& $py @tgArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== closure-test-v1 local =="
$ctArgs = @("-m", "xinao_seedlab.cli.__main__", "closure-test-v1")
if ($NoDocker) { $ctArgs += "--no-docker" }
& $py @ctArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipTemporal) {
    Write-Host "== thin-glue temporal =="
    $ttgArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue", "--temporal")
    if ($NoDocker) { $ttgArgs += "--no-docker" }
    & $py @ttgArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== closure-test-v1 temporal =="
    $tctArgs = @("-m", "xinao_seedlab.cli.__main__", "closure-test-v1", "--temporal")
    if ($NoDocker) { $tctArgs += "--no-docker" }
    & $py @tctArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "PASS thin-glue full smoke"
exit 0