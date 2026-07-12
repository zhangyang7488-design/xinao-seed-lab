#Requires -Version 5.1
<#
.SYNOPSIS
  Codex -> N x Grok headless worker pool (CREATE_NO_WINDOW).
.DESCRIPTION
  Explicit fallback: a caller dispatches bounded Grok Composer workers on the
  Windows host. Not TUI inject, not Docker desktop .lnk, and not the canonical
  Temporal + houtai-gongren + LangGraph route.
.EXAMPLE
  .\Invoke-GrokWorkerPool.ps1 -N 2 -Prompt "Reply only: POOL_OK" -MaxTurns 1
  .\Invoke-GrokWorkerPool.ps1 -N 4 -PromptFile .\task.md -Cwd E:\repo
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 2,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "grok-composer-2.5-fast",
    [int]$MaxTurns = 8,
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-4.5-lane",
    [string]$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$workerScript = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
if (-not (Test-Path -LiteralPath $workerScript)) {
    throw "WORKER_SCRIPT_MISSING: $workerScript"
}

# Pause gate: reconnect path requires explicit skip or cleared PAUSED_ALL
$pausePath = "D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\user_pause_all_latest.json"
if (-not $SkipPauseGate -and (Test-Path -LiteralPath $pausePath)) {
    try {
        $pause = Get-Content -LiteralPath $pausePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($pause.status -eq "PAUSED_ALL" -and $pause.subagent_spawn -eq $false) {
            throw "PAUSED_ALL: clear pause or pass -SkipPauseGate for grok_worker_pool reconnect"
        }
    } catch {
        if ("$_" -match "PAUSED_ALL") { throw }
    }
}

if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile missing: $PromptFile" }
    $Prompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
}
if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "Prompt or PromptFile required"
}
if (-not $Cwd) { $Cwd = (Get-Location).Path }

$poolId = "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$poolDir = Join-Path $EvidenceRoot $poolId
New-Item -ItemType Directory -Force -Path $poolDir, $EvidenceRoot | Out-Null
$latest = Join-Path $EvidenceRoot "latest.json"

$workers = New-Object System.Collections.Generic.List[object]
$jobs = @()

for ($i = 0; $i -lt $N; $i++) {
    $lane = $i
    $laneDir = Join-Path $poolDir ("lane_{0:D2}" -f $lane)
    New-Item -ItemType Directory -Force -Path $laneDir | Out-Null
    $promptLane = Join-Path $laneDir "prompt.md"
    $lanePrompt = @"
[grok_worker_pool]
pool_id=$poolId
lane=$lane
n=$N
model=$Model

$Prompt
"@
    [System.IO.File]::WriteAllText($promptLane, $lanePrompt, $utf8)

    # Each lane: separate process CreateNoWindow via worker script (sync wait inside job would flash job host).
    # Use runspace + call worker -Quiet so N workers run truly parallel without Start-Job conhost.
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    $script = {
        param($WorkerScript, $PromptFile, $Cwd, $Model, $MaxTurns, $GrokHome, $EvidenceDir)
        $ErrorActionPreference = "Continue"
        & $WorkerScript -PromptFile $PromptFile -Cwd $Cwd -Model $Model -MaxTurns $MaxTurns `
            -GrokHome $GrokHome -EvidenceDir $EvidenceDir -Quiet
        return @{
            exit_code = $LASTEXITCODE
            evidence_dir = $EvidenceDir
        }
    }
    [void]$ps.AddScript($script).AddArgument($workerScript).AddArgument($promptLane).AddArgument($Cwd).AddArgument($Model).AddArgument($MaxTurns).AddArgument($GrokHome).AddArgument($laneDir)
    $handle = $ps.BeginInvoke()
    $jobs += [pscustomobject]@{
        lane   = $lane
        ps     = $ps
        rs     = $rs
        handle = $handle
        dir    = $laneDir
        started_at = (Get-Date).ToString("o")
    }
    $workers.Add([ordered]@{
        lane = $lane
        evidence_dir = $laneDir
        prompt_file = $promptLane
        status = "started"
    }) | Out-Null
}

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$results = @()
foreach ($j in $jobs) {
    $remaining = [math]::Max(1, ($deadline - (Get-Date)).TotalMilliseconds)
    $ok = $j.handle.AsyncWaitHandle.WaitOne([int]$remaining)
    $item = [ordered]@{
        lane = $j.lane
        evidence_dir = $j.dir
        timed_out = (-not $ok)
    }
    if ($ok) {
        try {
            $out = $j.ps.EndInvoke($j.handle)
            $item.exit_code = $out.exit_code
            $item.status = if ($out.exit_code -eq 0) { "ok" } else { "failed" }
            $item.raw = $out
        } catch {
            $item.status = "invoke_error"
            $item.error = "$_"
        }
    } else {
        $item.status = "timeout"
        try { $j.ps.Stop() } catch { }
    }
    try { $j.ps.Dispose() } catch { }
    try { $j.rs.Close(); $j.rs.Dispose() } catch { }

    # Pull lane latest meta if any
    $laneLatest = Join-Path $j.dir "latest.json"
    if (-not (Test-Path -LiteralPath $laneLatest)) {
        $cand = Get-ChildItem -LiteralPath $j.dir -Filter "c25_*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($cand) { $laneLatest = $cand.FullName }
    }
    if (Test-Path -LiteralPath $laneLatest) {
        $item.meta_path = $laneLatest
        try {
            $m = Get-Content -LiteralPath $laneLatest -Raw -Encoding UTF8 | ConvertFrom-Json
            $item.run_id = $m.run_id
            $item.pid = $m.pid
            $item.worker_status = $m.status
            $item.create_no_window = $m.create_no_window
        } catch { }
    }
    $results += [pscustomobject]$item
}

$okCount = @($results | Where-Object { $_.status -eq "ok" -or $_.exit_code -eq 0 }).Count
$summary = [ordered]@{
    schema_version = "xinao.grok_worker_pool.v1"
    sentinel = "SENTINEL:GROK_WORKER_POOL"
    generated_at = (Get-Date).ToString("o")
    pool_id = $poolId
    hot_path_cn = "Codex->N Grok headless workers (CREATE_NO_WINDOW)"
    not_cn = @(
        "visible TUI typeahead inject as default",
        "Docker integrated_bus reading Desktop .lnk",
        "Dify docker-worker-1"
    )
    n = $N
    model = $Model
    cwd = $Cwd
    max_turns = $MaxTurns
    timeout_sec = $TimeoutSec
    ok_count = $okCount
    fail_count = $N - $okCount
    all_ok = ($okCount -eq $N)
    pool_dir = $poolDir
    results = $results
    completion_claim_allowed = $false
    invoke_cn = ".\Invoke-GrokWorkerPool.ps1 -N $N -Prompt '...' -MaxTurns 1"
}

$summaryPath = Join-Path $poolDir "pool_summary.json"
[System.IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 10), $utf8)
[System.IO.File]::WriteAllText($latest, ($summary | ConvertTo-Json -Depth 10), $utf8)

$zhDir = "D:\XINAO_RESEARCH_RUNTIME\readback\zh"
New-Item -ItemType Directory -Force -Path $zhDir | Out-Null
$zh = @"
# Grok worker pool $poolId

- hot_path: Codex -> N Grok headless (CREATE_NO_WINDOW)
- n=$N ok=$okCount fail=$($N - $okCount) all_ok=$($okCount -eq $N)
- model=$Model
- pool_dir=$poolDir
- latest=$latest
- completion_claim_allowed=false

## lanes
$($results | ForEach-Object { "- lane=$($_.lane) status=$($_.status) exit=$($_.exit_code) pid=$($_.pid)" } | Out-String)
"@
$zhPath = Join-Path $zhDir "grok_worker_pool_latest.md"
[System.IO.File]::WriteAllText($zhPath, $zh, $utf8)

if (-not $Quiet) {
    $summary | ConvertTo-Json -Depth 10
}

if ($okCount -eq $N) { exit 0 } else { exit 2 }
