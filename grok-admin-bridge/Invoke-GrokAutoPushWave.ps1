[CmdletBinding()]
param(
    [string]$WaveId = "auto-push-20260708"
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$ctx = "D:\XINAO_RESEARCH_RUNTIME\state\auto_push_wave\context_20260708.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $ctx) | Out-Null
@(
    "Auto push — integrated_bus_graph 全扩 + handroll_intact=false",
    "单 daemon 多队列；facade 默认不可达；D 盘 coverage/readback",
    "证据: D:\XINAO_RESEARCH_RUNTIME\readback\integrated_bus_*.json",
    "S: E:\XINAO_RESEARCH_WORKSPACES\S"
) | Set-Content -LiteralPath $ctx -Encoding UTF8

$qwenLanes = @(
    @{ LaneId = "AUTO-mirror-gap"; Objective = "镜像缺口补齐顺序: searxng/fastmcp/crawl4ai/temporal samples" },
    @{ LaneId = "AUTO-L9-temporal-gather"; Objective = "integrated_bus parallel_width 真 Temporal gather 焊法" },
    @{ LaneId = "AUTO-facade-sunset"; Objective = "facade×5+driver 默认不可达验收清单" },
    @{ LaneId = "AUTO-table-green"; Objective = "tool_table 绿行推进草案; 禁假进展" }
)
$dpLanes = @(
    @{ LaneId = "AUTO-DP-handroll-chain"; Objective = "全链路 handroll_intact 必须为 false; 手搓仍可达点" },
    @{ LaneId = "AUTO-DP-daemon-registry"; Objective = "单 worker daemon 注册全 workflow 缺口审计" }
)

$script = {
    param($Bridge, $LaneId, $Objective, $Ctx, $Wave, $Mode, $Provider)
    Set-Location $Bridge
    & "$Bridge\Invoke-GrokCodexSDirectWorkerLane.ps1" -Mode $Mode -Provider $Provider -WaveId $Wave -LaneId $LaneId -Objective $Objective -InputFile $Ctx
    return [pscustomobject]@{ LaneId = $LaneId; Ok = ($LASTEXITCODE -eq 0); Provider = $Provider }
}
$jobs = @()
foreach ($l in $qwenLanes) {
    $jobs += Start-Job -ScriptBlock $script -ArgumentList $bridge, $l.LaneId, $l.Objective, $ctx, $WaveId, "extraction", "qwen"
}
foreach ($l in $dpLanes) {
    $jobs += Start-Job -ScriptBlock $script -ArgumentList $bridge, $l.LaneId, $l.Objective, $ctx, $WaveId, "audit", "dp"
}
$results = @($jobs | Wait-Job | ForEach-Object { Receive-Job $_; Remove-Job $_ } | Where-Object { $_.PSObject.Properties.Name -contains 'LaneId' })
$ok = @($results | Where-Object { $_.Ok }).Count
$summary = [ordered]@{
    wave_id = $WaveId
    succeeded = $ok
    total = $results.Count
    lanes = $results
}
$out = "D:\XINAO_RESEARCH_RUNTIME\state\auto_push_wave\wave_summary_$WaveId.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Output ($summary | ConvertTo-Json -Compress)
exit $(if ($ok -lt $results.Count) { 1 } else { 0 })