param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$RepoRoot\src;$RepoRoot;$RepoRoot\services\agent_runtime"

python (Join-Path $RepoRoot "services\agent_runtime\codex_333_p1_loop_frontier.py") `
    --runtime-root $RuntimeRoot `
    --repo-root $RepoRoot `
    --task-id "xinao_seed_cortex_phase0_20260701" `
    --base-wave-id "p1-333-loop-frontier-verify-20260703"

$latest = Join-Path $RuntimeRoot "state\codex_333_p1_loop_frontier\latest.json"
$payload = Get-Content -Raw -LiteralPath $latest | ConvertFrom-Json

if ($payload.validation.passed -ne $true) {
    throw "P1 loop frontier validation did not pass."
}
if ($payload.summary.while_wave_count -lt 2) {
    throw "Expected at least two while waves."
}
if ($payload.summary.execute_search_invocation_count_total -ne 0) {
    throw "execute_search_invocation_count_total must be 0."
}
if ($payload.summary.provider_probe_invocation_count_total -ne 0) {
    throw "provider_probe_invocation_count_total must be 0."
}
if ($payload.p2_episode_fan_in_hook.runtime_enforced -ne $true) {
    throw "P2 FanIn hook must be runtime_enforced."
}

Write-Output "codex_333_p1_loop_frontier_latest=$latest"
Write-Output "runtime_readback_zh=$($payload.output_paths.runtime_readback_zh)"
Write-Output "repo_frontier_readback=$($payload.output_paths.repo_frontier_readback)"
