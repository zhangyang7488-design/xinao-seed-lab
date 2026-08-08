# Prime Codex-compatible test entry. The durable conversation and behavior core
# are stable; the active account binding is resolved inside the S-owned launcher.
$ErrorActionPreference = 'Stop'
$launcher = 'E:\XINAO_RESEARCH_WORKSPACES\S\infra\prime_codex_parity_test\v1\scripts\Start-PrimeCodexParityTest.ps1'
$prepared = 'D:\XINAO_RESEARCH_RUNTIME\state\prime-agent\parity-test\codex-compatible\conversation-binding.json'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "PRIME_CODEX_PARITY_LAUNCHER_MISSING: $launcher"
}
if (-not (Test-Path -LiteralPath $prepared -PathType Leaf)) {
    Write-Host 'Prime Codex parity 入口已经创建；运行投影仍在等待当前 Prime 整棵 RLM 会话树空闲。' -ForegroundColor Yellow
    Write-Host '没有切换、复制或停止当前会话。完成验收后此入口会直接接管同一 durable session。' -ForegroundColor DarkGray
    exit 75
}
& $launcher
exit $LASTEXITCODE
