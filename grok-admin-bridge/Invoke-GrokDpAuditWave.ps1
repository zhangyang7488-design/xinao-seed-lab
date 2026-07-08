[CmdletBinding()]
param(
    [string]$WaveId = "dp-audit-gapfill-20260708",
    [string]$ContextFile = "D:\XINAO_RESEARCH_RUNTIME\state\dp_audit_wave\context_20260708.txt",
    [int]$Throttle = 8
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$bridgeRoot = $PSScriptRoot
$invokeScript = Join-Path $bridgeRoot "Invoke-GrokCodexSDirectWorkerLane.ps1"
if (-not (Test-Path -LiteralPath $invokeScript)) { throw "Missing $invokeScript" }
if (-not (Test-Path -LiteralPath $ContextFile)) { throw "Missing context: $ContextFile" }

$lanes = @(
    @{ LaneId = "DP-AUDIT-handroll-residual";     Objective = "审计 S 仓手搓残留：默认热路仍可达的 facade/driver/while 循环；列路径+严重度+日落顺序" },
    @{ LaneId = "DP-AUDIT-tool-table-coverage";   Objective = "审计全链路工具表~50行：每行成熟度/invoke状态/缺什么外部载体；输出 coverage 矩阵草案" },
    @{ LaneId = "DP-AUDIT-mirror-registry-gap";   Objective = "审计 glue_mature_repo_registry vs 本地 official 镜像 vs 图内已焊；列 clone缺口+焊缺口" },
    @{ LaneId = "DP-AUDIT-integrated-bus-mature"; Objective = "审计 integrated_bus 成熟度：是否真总线还是窄 smoke；扩图清单+禁一对一patch" },
    @{ LaneId = "DP-AUDIT-capabilities-invoke";  Objective = "审计 D盘 capabilities/：哪些 legacy 无真 invoke；哪些应降级 candidate" },
    @{ LaneId = "DP-AUDIT-temporal-worker-gap";   Objective = "审计 Temporal Worker/L9并行：daemon/parallel/ChildWF/Signals 缺什么才算能跑" },
    @{ LaneId = "DP-AUDIT-false-progress";       Objective = "审计假进展信号：pytest PASS/repo绿/status矛盾/无token lane；真进展三把尺" },
    @{ LaneId = "DP-AUDIT-followup-waves";        Objective = "审计后续补足：按 P0/P1/P2 列并行波（DP审计/Qwen提取/S仓落地/镜像clone）；不限本案例" }
)

$scriptBlock = {
    param($InvokeScript, $BridgeRoot, $WaveId, $LaneId, $Objective, $ContextFile)
    Set-Location $BridgeRoot
    try {
        & $InvokeScript `
            -Mode audit `
            -Provider dp `
            -WaveId $WaveId `
            -LaneId $LaneId `
            -Objective $Objective `
            -InputFile $ContextFile
        return [pscustomobject]@{ LaneId = $LaneId; ExitCode = $LASTEXITCODE; Ok = ($LASTEXITCODE -eq 0) }
    }
    catch {
        return [pscustomobject]@{ LaneId = $LaneId; ExitCode = 1; Ok = $false; Error = $_.Exception.Message }
    }
}

$jobs = @()
foreach ($lane in $lanes) {
    $jobs += Start-Job -ScriptBlock $scriptBlock -ArgumentList $invokeScript, $bridgeRoot, $WaveId, $lane.LaneId, $lane.Objective, $ContextFile
}
$results = $jobs | Wait-Job | ForEach-Object {
    $r = Receive-Job $_
    Remove-Job $_
    $r
}

$ok = @($results | Where-Object { $_.Ok }).Count
$summaryDir = "D:\XINAO_RESEARCH_RUNTIME\state\dp_audit_wave"
New-Item -ItemType Directory -Force -Path $summaryDir | Out-Null
$summary = [ordered]@{
    schema_version = "xinao.grok.dp_audit_wave.v1"
    sentinel       = "SENTINEL:GROK_DP_AUDIT_WAVE"
    generated_at   = (Get-Date).ToString("o")
    wave_id        = $WaveId
    provider       = "deepseek_dp"
    mode           = "audit"
    not_333_mainline = $true
    completion_claim_allowed = $false
    lane_count     = $lanes.Count
    succeeded      = $ok
    failed         = $lanes.Count - $ok
    lanes          = @($results | Sort-Object LaneId)
    artifact_glob  = "D:\XINAO_RESEARCH_RUNTIME\state\modular_dynamic_worker_pool_phase1\qwen_worker_invocation\artifacts\DP-AUDIT-*.audit.json"
    user_intent_cn = "云DP并行查缺补漏：手搓/成熟度/本地遗漏/后续波；元模式非单案例"
}
$summaryPath = Join-Path $summaryDir "wave_summary_$WaveId.json"
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-Output ($summary | ConvertTo-Json -Depth 8 -Compress)
exit $(if ($summary.failed -gt 0) { 1 } else { 0 })