[CmdletBinding()]
param(
    [string]$WaveId = "p2-continue-20260708"
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$ctx = "D:\XINAO_RESEARCH_RUNTIME\state\p2_continue_wave\context_20260708.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $ctx) | Out-Null
@(
    "P2 continue — user: 没喊停不要停",
    "integrated_bus_v2 expanded: planner/crawl4ai/otel/checkpoint/diff-cover fix",
    "证据: D:\XINAO_RESEARCH_RUNTIME\readback\integrated_bus_*.json",
    "S: E:\XINAO_RESEARCH_WORKSPACES\S",
    "目标: 表行绿↑ facade日落 duckdb/watchdog 薄绑"
) | Set-Content -LiteralPath $ctx -Encoding UTF8

$qwenLanes = @(
    @{ LaneId = "P2-L0-duckdb-watchdog"; Objective = "duckdb+watchdog L0 节点薄绑参数; 接 intake 后可选" },
    @{ LaneId = "P2-L5-aaq-full"; Objective = "sourceledger AAQ 全 fan-in 焊进 fanin_bus; ClaimCard 硬门" },
    @{ LaneId = "P2-L3-fastmcp-invoke"; Objective = "FastMCP 从 probe 升级到 LangGraph tool invoke 薄绑" },
    @{ LaneId = "P2-L9-temporal-parallel"; Objective = "Temporal asyncio.gather Activity 真并行替换 ledger 记账" },
    @{ LaneId = "P2-sunset-facade"; Objective = "facade×5 硬重定向到 integrated_bus; driver 日落顺序" }
)
$dpLanes = @(
    @{ LaneId = "P2-DP-coverage-gap"; Objective = "审计 tool_table 绿=5→25 缺口; 假进展/手搓可达" },
    @{ LaneId = "P2-DP-mirror-registry"; Objective = "审计 SearXNG/Crawl4AI/FastMCP 镜像+registry 缺口" }
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
$out = "D:\XINAO_RESEARCH_RUNTIME\state\p2_continue_wave\wave_summary_$WaveId.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Output ($summary | ConvertTo-Json -Compress)
exit $(if ($ok -lt $results.Count) { 1 } else { 0 })