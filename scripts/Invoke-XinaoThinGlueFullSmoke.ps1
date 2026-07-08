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

Write-Host "== thin-glue-worker-pool local =="
$wpArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue-worker-pool", "--width", "3")
& $py @wpArgs
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

    Write-Host "== thin-glue-root-intent temporal =="
    & $py -m xinao_seedlab.cli.__main__ thin-glue-root-intent --temporal
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== thin-glue-worker-pool temporal =="
    $twpArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue-worker-pool", "--width", "3", "--temporal")
    & $py @twpArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== thin-glue-spawn mainline seam =="
    $spawnArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue-spawn")
    if ($NoDocker) { $spawnArgs += "--no-docker" }
    & $py @spawnArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "== thin-glue-mainline-orch (main queue seam) =="
    $orchArgs = @("-m", "xinao_seedlab.cli.__main__", "thin-glue-mainline-orch", "--force")
    if ($NoDocker) { $orchArgs += "--no-docker" }
    & $py @orchArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "== thin-glue-root-intent local =="
& $py -m xinao_seedlab.cli.__main__ thin-glue-root-intent
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== phase0-minimal-weld (smoke, not mainline) =="
$p0Args = @("-m", "xinao_seedlab.cli.__main__", "phase0-minimal-weld", "--no-e2b")
if ($NoDocker) { $p0Args += "--no-docker" }
& $py @p0Args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "PASS thin-glue full smoke"
exit 0