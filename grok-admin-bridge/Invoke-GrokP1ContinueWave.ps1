[CmdletBinding()]
param(
    [string]$WaveId = "p1-continue-20260708"
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$ctx = "D:\XINAO_RESEARCH_RUNTIME\state\p1_continue_wave\context_20260708.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $ctx) | Out-Null
@(
    "P1 continue wave — user: 没喊停不要停",
    "integrated_bus_v2 landed; expand FastMCP/L9/crawl4ai/diff-cover/otel/planner",
    "证据: D:\XINAO_RESEARCH_RUNTIME\readback\integrated_bus_*.json",
    "S: E:\XINAO_RESEARCH_WORKSPACES\S",
    "输出: bus节点+params+sunset顺序; JSON友好"
) | Set-Content -LiteralPath $ctx -Encoding UTF8

$qwenLanes = @(
    @{ LaneId = "P1-L3-fastmcp-weld"; Objective = "FastMCP LangGraph tool node 薄绑参数草案; replaces v4pro_tool_bearing" },
    @{ LaneId = "P1-L9-parallel-child"; Objective = "Temporal parallel Activity+ChildWF 焊进 integrated_bus_v2; 父WF算N" },
    @{ LaneId = "P1-L4-crawl4ai"; Objective = "Crawl4AI 可选 tool node 薄绑; 接 search_bus 后" },
    @{ LaneId = "P1-L5-diff-otel"; Objective = "diff-cover+OTel 进 fanin_bus; 副产品非停点" },
    @{ LaneId = "P1-L2-planner-checkpoint"; Objective = "planner Pydantic节点+LangGraph sqlite checkpoint 扩图" }
)
$dpLanes = @(
    @{ LaneId = "P1-DP-post-v2-gap"; Objective = "审计 integrated_bus_v2 焊后缺口: 表行/手搓/镜像/假进展" },
    @{ LaneId = "P1-DP-sunset-order"; Objective = "审计 facade×5+driver 日落顺序; 默认热路不可达验收" }
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
$results = $jobs | Wait-Job | ForEach-Object { Receive-Job $_; Remove-Job $_ }
$ok = @($results | Where-Object { $_.Ok }).Count
$summary = [ordered]@{
    wave_id = $WaveId
    succeeded = $ok
    total = $results.Count
    lanes = $results
}
$out = "D:\XINAO_RESEARCH_RUNTIME\state\p1_continue_wave\wave_summary_$WaveId.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Output ($summary | ConvertTo-Json -Compress)
exit $(if ($ok -lt $results.Count) { 1 } else { 0 })