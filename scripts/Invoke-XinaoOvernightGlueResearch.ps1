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

function Invoke-ItemResearch($item) {
    $script:LastItemId = $item.id
    $queries = ($item.github_queries -join "; ")
    $objective = @"
仓库胶水替换研究。目标模块: $($item.sunset_target)。替换方向: $($item.replace_with)。
必须输出JSON字段: mature_repos[{name,url,why}], thin_bind_steps[max5], delete_safe_after[], sandbox_smoke_cmd, risks[]。
搜 GitHub 成熟开源，不要手搓大脑。queries: $queries
"@.Trim()

    $laneArgs = @{
        RuntimeRoot = $RuntimeRoot
        RepoRoot    = $RepoRoot
        Mode        = "draft"
        Provider    = "qwen"
        Objective   = $objective
        InputText   = "layer=$($item.layer); id=$($item.id); wave=$wave"
    }
    $laneExit = 0
    try {
        & $WorkerLane @laneArgs 2>&1 | Out-Null
        $laneExit = $LASTEXITCODE
    }
    catch { $laneExit = 1 }

    $latestPath = Join-Path $RuntimeRoot "state\codex_s_direct_worker_lane\latest.json"
    $lane = $null
    if (Test-Path -LiteralPath $latestPath) {
        $lane = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $lr = $lane.worker_lane_result
    $sandbox = Invoke-DockerSmoke

    $record = [ordered]@{
        schema_version              = "xinao.overnight.item_result.v1"
        wave_id                     = $wave
        item_id                     = $item.id
        layer                       = $item.layer
        sunset_target               = $item.sunset_target
        replace_with                = $item.replace_with
        completed_at                = (Get-Date).ToString("o")
        qwen_lane_exit              = $laneExit
        qwen_status                 = if ($lr) { $lr.status } else { "missing" }
        model_invocation_performed  = if ($lr) { $lr.model_invocation_performed } else { $false }
        artifact_ref                = if ($lr) { $lr.artifact_ref } else { "" }
        draft_ref                   = if ($lr) { $lr.draft_ref } else { "" }
        usage_total_tokens          = if ($lr -and $lr.usage) { $lr.usage.total_tokens } else { 0 }
        usage_cost_usd              = if ($lr -and $lr.usage) { $lr.usage.cost_usd } else { 0 }
        sandbox                     = $sandbox
        sandbox_passed              = [bool]$sandbox.ok
        not_333_mainline            = $true
        staging_only                = $true
        empty_spin_check            = "artifact_or_blocker_required"
    }
    if (-not $record.model_invocation_performed -and $record.qwen_status -ne "succeeded") {
        $record.named_blocker = "QWEN_LANE_NOT_SUCCEEDED"
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