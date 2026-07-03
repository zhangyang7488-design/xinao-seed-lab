[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$probeId = "probe_{0}" -f (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
$waveId = "wave_{0}" -f (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
$writer = Join-Path $RepoRoot "scripts\hardmode\Write-CodexProductivityBaseline.ps1"
$metaWriter = Join-Path $RepoRoot "scripts\hardmode\Write-MetaRsiWave.ps1"

if (-not (Test-Path -LiteralPath $writer -PathType Leaf)) {
    throw "PRODUCTIVITY_BASELINE_WRITER_MISSING"
}
if (-not (Test-Path -LiteralPath $metaWriter -PathType Leaf)) {
    throw "META_RSI_WAVE_WRITER_MISSING"
}

& $metaWriter `
    -TaskId "productivity_baseline_probe" `
    -WaveId $waveId `
    -Mode "productivity_v2" `
    -ModeReason "baseline_probe_invoke" `
    -ZhReadback "生产力基线探针：验证 writer 与 invoke 链可跑" | Out-Null

$result = & $writer `
    -ProbeId $probeId `
    -TaskId "productivity_baseline_probe" `
    -WaveId $waveId `
    -HadCodeDiff $false `
    -HadInvoke $true `
    -InvokePath "scripts/hardmode/Invoke-ProductivityBaselineProbe.ps1" `
    -GatekeeperSignals @("none_observed") `
    -ZhReadback "基线探针已跑：Write-MetaRsiWave + Write-CodexProductivityBaseline 可 invoke；验收看 D 盘 latest.json"

[ordered]@{
    status = "productivity_baseline_probe_pass"
    probe_id = $probeId
    wave_id = $waveId
    meta_rsi_wave = Join-Path $RuntimeRoot "state\meta_rsi_wave\latest.json"
    productivity_baseline = Join-Path $RuntimeRoot "state\codex_productivity_baseline\latest.json"
    zh_readback = "现在能 invoke：生产力基线双 writer + 本探针脚本"
    not_user_completion = $true
} | ConvertTo-Json -Depth 4