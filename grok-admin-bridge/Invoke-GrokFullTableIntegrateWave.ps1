[CmdletBinding()]
param(
    [string]$WaveId = "full-table-integrate-20260708",
    [string]$ContextFile = "D:\XINAO_RESEARCH_RUNTIME\state\full_table_integrate_wave\context_20260708.txt",
    [int]$Throttle = 12
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$bridgeRoot = $PSScriptRoot
$invokeScript = Join-Path $bridgeRoot "Invoke-GrokCodexSDirectWorkerLane.ps1"
if (-not (Test-Path -LiteralPath $invokeScript)) { throw "Missing $invokeScript" }
if (-not (Test-Path -LiteralPath $ContextFile)) { throw "Missing context: $ContextFile" }

$lanes = @(
    @{ LaneId = "BUS-G0-mature-arch";        Objective = "全局成熟架构总线：Temporal+LangGraphPlugin+temporal-ai-agent 作外壳，整条 StateGraph+Worker 注册表，禁手搓orchestrator；输出一张总架构图+模块边界" },
    @{ LaneId = "BUS-L0-intake-index";       Objective = "L0 intake bus: markitdown+watchdog+duckdb 集成进 integrated_bus_graph 节点，参数only，禁一对一胶水" },
    @{ LaneId = "BUS-L1-validate";           Objective = "L1 validate bus: Pydantic必过节点+Instructor可选，接入LangGraph restore_state，禁dict手搓" },
    @{ LaneId = "BUS-L2-spine-expand";       Objective = "L2 spine bus: LangGraphPlugin图扩展 planner+checkpoint+Send内扇出，Temporal续跑，禁新driver" },
    @{ LaneId = "BUS-L3-exec-mcp";           Objective = "L3 exec bus: LiteLLM dispatch+Docker+FastMCP tool node+GitPython，模块化非贴缝" },
    @{ LaneId = "BUS-L4-search";             Objective = "L4 search bus: ripgrep+SearXNG+Crawl4AI 作 LangGraph tool nodes，替换 light_research facade" },
    @{ LaneId = "BUS-L5-fanin-observe";      Objective = "L5 fan-in bus: SourceLedger+AAQ+PromotionGate+Langfuse+OTel+diff-cover 一条总线" },
    @{ LaneId = "BUS-L6-heal";               Objective = "L6 heal bus: Temporal retry policy+LangGraph critic cond edge，替换 pre_pass_audit facade" },
    @{ LaneId = "BUS-L8-token-readback";     Objective = "L8 token bus: RTK+Caveman+Jinja readback 薄绑进 gateway 后链路" },
    @{ LaneId = "BUS-L9-parallel-width";     Objective = "L9 parallel bus: Temporal parallel Activity+ChildWF+Worker Pool常驻+Signals，算N在父WF" },
    @{ LaneId = "BUS-L7-memory-policy";      Objective = "L7 memory bus: ReplayCase→MemCand→Letta/Mem0薄试，PromotionGate后，Phase0过重则skip" },
    @{ LaneId = "BUS-sunset-legacy";         Objective = "sunset bus: facade→integrated_bus硬redirect，root_intent_driver移出默认import，清单+顺序" },
    @{ LaneId = "BUS-worker-daemon";         Objective = "worker daemon bus: 单Temporal Worker注册 integrated_bus+thin_glue+root_intent_tick，CLI改守护进程" }
)

$scriptBlock = {
    param($InvokeScript, $BridgeRoot, $WaveId, $LaneId, $Objective, $ContextFile)
    Set-Location $BridgeRoot
    try {
        & $InvokeScript `
            -Mode extraction `
            -Provider qwen `
            -WaveId $WaveId `
            -LaneId $LaneId `
            -Objective $Objective `
            -InputFile $ContextFile
        $exit = $LASTEXITCODE
        return [pscustomobject]@{ LaneId = $LaneId; ExitCode = $exit; Ok = ($exit -eq 0) }
    }
    catch {
        return [pscustomobject]@{ LaneId = $LaneId; ExitCode = 1; Ok = $false; Error = $_.Exception.Message }
    }
}

$jobs = @()
foreach ($lane in $lanes) {
    $jobs += Start-Job -ScriptBlock $scriptBlock -ArgumentList $invokeScript, $bridgeRoot, $WaveId, $lane.LaneId, $lane.Objective, $ContextFile
}
while (@($jobs | Where-Object { $_.State -eq 'Running' }).Count -gt $Throttle) {
    Start-Sleep -Milliseconds 500
}
$results = $jobs | Wait-Job | ForEach-Object {
    $r = Receive-Job $_
    Remove-Job $_
    $r
}

$summaryDir = "D:\XINAO_RESEARCH_RUNTIME\state\full_table_integrate_wave"
New-Item -ItemType Directory -Force -Path $summaryDir | Out-Null
$summary = [ordered]@{
    schema_version = "xinao.grok.full_table_integrate_wave.v1"
    sentinel       = "SENTINEL:GROK_FULL_TABLE_INTEGRATE_WAVE"
    generated_at   = (Get-Date).ToString("o")
    wave_id        = $WaveId
    not_333_mainline = $true
    completion_claim_allowed = $false
    lane_count     = $lanes.Count
    succeeded      = @($results | Where-Object { $_.Ok }).Count
    failed         = @($results | Where-Object { -not $_.Ok }).Count
    lanes          = @($results | Sort-Object LaneId)
    user_intent_cn = "模块化总线一次调度；千问云并行 extraction；晋升须 fan-in+AAQ+S仓落地"
    next_step_cn   = "fan-in 合并各 lane artifact → 写 integrated_bus_graph 扩展 + 桌面施工包 → 用户投 Codex S 一次闭合"
}
$summaryPath = Join-Path $summaryDir "wave_summary_$WaveId.json"
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-Output ($summary | ConvertTo-Json -Depth 8 -Compress)
exit $(if ($summary.failed -gt 0) { 1 } else { 0 })