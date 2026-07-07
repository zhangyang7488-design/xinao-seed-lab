# XINAO overnight glue research — Qwen search/draft + Docker sandbox heartbeat
# not_333_mainline · staging only · evidence to D:\XINAO_RESEARCH_RUNTIME\overnight
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$ItemsFile = "",
    [int]$IntervalMinutes = 20,
    [int]$MaxCycles = 0,
    [switch]$Once
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $ItemsFile) {
    $ItemsFile = Join-Path $RepoRoot "materials\overnight_glue_items.v1.json"
}
$WorkerLane = Join-Path $RepoRoot "scripts\hardmode\Invoke-CodexSWorkerLane.ps1"
$Bootstrap = Join-Path $RepoRoot "scripts\Invoke-XinaoThinBootstrap.ps1"
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$GlueDir = Join-Path $RepoRoot "materials\authority_glue"
if (-not (Test-Path -LiteralPath $GlueDir)) { $GlueDir = "C:\Users\xx363\Desktop\仓库胶水" }

$wave = (Get-Content -LiteralPath $ItemsFile -Raw -Encoding UTF8 | ConvertFrom-Json).wave_id
if (-not $wave) { $wave = "overnight-glue-$(Get-Date -Format yyyyMMdd)" }

$outRoot = Join-Path $RuntimeRoot "overnight\$wave"
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null
$logPath = Join-Path $outRoot "run_log.jsonl"
$heartbeatPath = Join-Path $outRoot "heartbeat.json"
$summaryPath = Join-Path $outRoot "overnight_summary.json"

function Write-Heartbeat($status, $extra) {
    $hb = [ordered]@{
        schema_version = "xinao.overnight.heartbeat.v1"
        updated_at     = (Get-Date).ToString("o")
        wave_id        = $wave
        status         = $status
        cycles_done    = $script:CycleCount
        items_done     = $script:ItemIndex
        last_item_id   = $script:LastItemId
        empty_spin_guard = "each_cycle_must_write_item_json"
    }
    if ($extra) { $extra.GetEnumerator() | ForEach-Object { $hb[$_.Key] = $_.Value } }
    ($hb | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $heartbeatPath -Encoding UTF8
}

function Invoke-DockerSmoke {
    try {
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return @{ ok = $false; backend = "docker_off"; detail = "daemon down" } }
        $img = "python:3.12-slim"
        docker image inspect $img 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            docker pull $img 2>&1 | Out-Null
        }
        $out = docker run --rm $img python -c "print('sandbox_ok')" 2>&1
        return @{ ok = ($LASTEXITCODE -eq 0); backend = "docker:$img"; detail = ($out | Out-String).Trim() }
    }
    catch {
        return @{ ok = $false; backend = "docker_error"; detail = $_.Exception.Message }
    }
}

function Invoke-WorkerLanePass($item, $provider, $mode, $objective, $inputFile) {
    $laneArgs = @{
        RuntimeRoot = $RuntimeRoot
        RepoRoot    = $RepoRoot
        Mode        = $mode
        Provider    = $provider
        Objective   = $objective
        InputFile   = $inputFile
    }
    $exit = 0
    try {
        & $WorkerLane @laneArgs 2>&1 | Out-Null
        $exit = $LASTEXITCODE
    }
    catch { $exit = 1 }
    $latestPath = Join-Path $RuntimeRoot "state\codex_s_direct_worker_lane\latest.json"
    $lane = $null
    if (Test-Path -LiteralPath $latestPath) {
        $lane = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    return @{ exit = $exit; lane = $lane; lr = $lane.worker_lane_result }
}

function Invoke-ItemResearch($item) {
    $script:LastItemId = $item.id
    $queries = ($item.github_queries -join "; ")
    $objective = @"
仓库胶水替换研究（必须对照 authority_glue 总图）。目标: $($item.sunset_target)。替换: $($item.replace_with)。
本地搜索 hits 已在 InputFile.local_search。请基于 hits + 胶水地图输出 JSON:
mature_repos[{name,url,why}], thin_bind_steps[max5], delete_safe_after[], sandbox_smoke_cmd, risks[]。
不要手搓大脑。queries: $queries
"@.Trim()

    $contextPath = ""
    try {
        $contextPath = & $Py -m services.agent_runtime.overnight_local_search `
            --items-file $ItemsFile `
            --item-id $item.id `
            --glue-dir $GlueDir `
            --runtime-root $RuntimeRoot `
            --wave-id $wave 2>&1 | Select-Object -Last 1
    }
    catch { $contextPath = "" }

    $passes = @(
        @{ provider = "qwen"; mode = "draft"; label = "qwen_draft" }
        @{ provider = "auto"; mode = "draft"; label = "auto_local_or_qwen" }
    )
    $chosen = $null
    foreach ($p in $passes) {
        if (-not $contextPath -or -not (Test-Path -LiteralPath $contextPath)) { break }
        $chosen = Invoke-WorkerLanePass $item $p.provider $p.mode $objective $contextPath
        if ($chosen.lr -and $chosen.lr.model_invocation_performed -and $chosen.lr.status -eq "succeeded") { break }
    }
    if (-not $chosen -or -not ($chosen.lr -and $chosen.lr.status -eq "succeeded")) {
        if ($contextPath -and (Test-Path -LiteralPath $contextPath)) {
            $chosen = Invoke-WorkerLanePass $item "dp" "extraction" $objective $contextPath
        }
    }

    $laneExit = if ($chosen) { $chosen.exit } else { 1 }
    $lr = if ($chosen) { $chosen.lr } else { $null }
    $sandbox = Invoke-DockerSmoke

    $record = [ordered]@{
        schema_version              = "xinao.overnight.item_result.v2"
        wave_id                     = $wave
        item_id                     = $item.id
        layer                       = $item.layer
        sunset_target               = $item.sunset_target
        replace_with                = $item.replace_with
        glue_authority_dir          = $GlueDir
        local_search_context        = $contextPath
        completed_at                = (Get-Date).ToString("o")
        worker_lane_exit            = $laneExit
        worker_status               = if ($lr) { $lr.status } else { "missing" }
        worker_provider             = if ($lr) { $lr.provider } else { "" }
        model_invocation_performed  = if ($lr) { $lr.model_invocation_performed } else { $false }
        artifact_ref                = if ($lr) { $lr.artifact_ref } else { "" }
        draft_ref                   = if ($lr) { $lr.draft_ref } else { "" }
        usage_total_tokens          = if ($lr -and $lr.usage) { $lr.usage.total_tokens } else { 0 }
        usage_cost_usd              = if ($lr -and $lr.usage) { $lr.usage.cost_usd } else { 0 }
        sandbox                     = $sandbox
        sandbox_passed              = [bool]$sandbox.ok
        not_333_mainline            = $true
        staging_only                = $true
        routing                     = "local_ddgs(+exa_if_key)_then_qwen_then_auto_then_dp_sparing"
        empty_spin_check            = "local_search_context_and_artifact_or_blocker_required"
    }
    if (-not $record.model_invocation_performed) {
        $record.named_blocker = if ($lr -and $lr.named_blocker) { $lr.named_blocker } else { "WORKER_LANE_NOT_SUCCEEDED" }
    }

    $itemPath = Join-Path $outRoot "$($item.id).json"
    ($record | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $itemPath -Encoding UTF8
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ($record | ConvertTo-Json -Compress -Depth 8)
    return $record
}

function Invoke-BootstrapHeartbeat {
    if (-not (Test-Path -LiteralPath $Bootstrap)) { return @{ ok = $false; detail = "bootstrap script missing" } }
    try {
        & $Bootstrap 2>&1 | Out-Null
        return @{ ok = ($LASTEXITCODE -eq 0); detail = "thin_bootstrap exit=$LASTEXITCODE" }
    }
    catch { return @{ ok = $false; detail = $_.Exception.Message } }
}

$items = (Get-Content -LiteralPath $ItemsFile -Raw -Encoding UTF8 | ConvertFrom-Json).items
$script:CycleCount = 0
$script:ItemIndex = 0
$script:LastItemId = ""

Write-Heartbeat "started" @{ items_total = $items.Count; items_file = $ItemsFile }

do {
    $script:CycleCount++
    foreach ($item in $items) {
        $script:ItemIndex++
        Write-Heartbeat "item_running" @{ current_item = $item.id }
        $null = Invoke-ItemResearch $item
        if (-not $Once) { Start-Sleep -Seconds 30 }
    }
    $boot = Invoke-BootstrapHeartbeat
    $summary = [ordered]@{
        schema_version       = "xinao.overnight.summary.v1"
        wave_id              = $wave
        updated_at           = (Get-Date).ToString("o")
        cycles_done          = $script:CycleCount
        items_per_cycle      = $items.Count
        item_json_count      = (Get-ChildItem -LiteralPath $outRoot -Filter "*.json" | Where-Object { $_.Name -notmatch 'heartbeat|summary' }).Count
        bootstrap_last       = $boot
        verification_due     = "2026-07-09"
        acceptance_rule      = "item_json_count>0 AND any model_invocation_performed AND any sandbox_passed"
        not_user_completion  = $true
    }
    ($summary | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Heartbeat "cycle_done" @{ bootstrap = $boot; item_json_count = $summary.item_json_count }

    if ($Once) { break }
    if ($MaxCycles -gt 0 -and $script:CycleCount -ge $MaxCycles) { break }
    Start-Sleep -Seconds ($IntervalMinutes * 60)
} while ($true)

Write-Heartbeat "finished" @{ summary_path = $summaryPath }
Write-Host "OK overnight wave=$wave out=$outRoot"