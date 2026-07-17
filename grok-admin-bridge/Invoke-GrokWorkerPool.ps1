#Requires -Version 5.1
<#
.SYNOPSIS
  Codex -> N x Grok headless worker pool (CREATE_NO_WINDOW).
.DESCRIPTION
  Bounded dynamic lane: a caller dispatches Grok Composer workers on the
  Windows host when that has positive net benefit or the canonical route needs
  a temporary fallback. Not TUI inject, not Docker desktop .lnk, and not a
  second owner beside Temporal + houtai-gongren + LangGraph.
.EXAMPLE
  .\Invoke-GrokWorkerPool.ps1 -N 2 -Prompt "Reply only: POOL_OK" -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json -MaxTurns 1 -MinResultChars 1 -RequiredResultMarkers POOL_OK
  .\Invoke-GrokWorkerPool.ps1 -N 4 -PromptFile .\task.md -Cwd E:\repo -Model grok-4.5 -SelectionPath D:\decision.json
#>
param(
    [ValidateRange(1, 32)]
    [int]$N = 2,
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "",
    [string]$SelectionPath = "",
    [string]$ExpectedSelectionDecisionSha256 = "",
    [string]$MaxTurns = "auto",
    [int]$TimeoutSec = 600,
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [string]$EvidenceRoot = "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool",
    [string]$PoolId = "",
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [switch]$SkipPauseGate,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false

function Stop-ExactProcessTree([int]$RootProcessId) {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Select-Object ProcessId, ParentProcessId)
    $ids = [System.Collections.Generic.List[int]]::new()
    [void]$ids.Add($RootProcessId)
    do {
        $added = $false
        foreach ($entry in $processes) {
            $childId = [int]$entry.ProcessId
            if ($ids.Contains([int]$entry.ParentProcessId) -and -not $ids.Contains($childId)) {
                [void]$ids.Add($childId)
                $added = $true
            }
        }
    } while ($added)
    $ordered = $ids.ToArray()
    [array]::Reverse($ordered)
    foreach ($processId in $ordered) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    return @($ordered)
}
$bridge = $PSScriptRoot
$workerScript = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
if (-not (Test-Path -LiteralPath $workerScript)) {
    throw "WORKER_SCRIPT_MISSING: $workerScript"
}
$selectionHelper = Join-Path $bridge "GrokWorkerSelectionReceipt.ps1"
if (-not (Test-Path -LiteralPath $selectionHelper -PathType Leaf)) {
    throw "GROK_WORKER_POOL_SELECTION_HELPER_MISSING: $selectionHelper"
}
. $selectionHelper
$selection = Read-GrokWorkerSelectionReceipt `
    -SelectionPath $SelectionPath `
    -Model $Model `
    -Cwd $Cwd `
    -RequiredPrefix "GROK_WORKER_POOL"
$SelectionPath = [string]$selection.selection_path
$Model = [string]$selection.model_id
$Cwd = [string]$selection.cwd
if (
    -not [string]::IsNullOrWhiteSpace($ExpectedSelectionDecisionSha256) -and
    -not [string]::Equals(
        $ExpectedSelectionDecisionSha256,
        [string]$selection.decision_sha256,
        [StringComparison]::Ordinal
    )
) {
    throw "GROK_WORKER_POOL_SELECTION_DECISION_CHANGED"
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
$poolId = if ([string]::IsNullOrWhiteSpace($PoolId)) {
    "gwp_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $PoolId
}
if ($poolId -notmatch '^gwp_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
    throw "GROK_WORKER_POOL_ID_INVALID: $poolId"
}
$poolDir = Join-Path $EvidenceRoot $poolId
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
if (Test-Path -LiteralPath $poolDir) {
    throw "GROK_WORKER_POOL_ID_ALREADY_EXISTS: $poolId"
}
New-Item -ItemType Directory -Path $poolDir | Out-Null
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
selection_decision_sha256=$($selection.decision_sha256)

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
        param(
            $WorkerScript, $PromptFile, $Cwd, $Model, $MaxTurns, $GrokHome,
            $EvidenceDir, $MinChars, $Markers, $RequireJson, $JsonSchemaPath, $TimeoutSec
        )
        $ErrorActionPreference = "Continue"
        $workerArgs = @{
            PromptFile = $PromptFile
            Cwd = $Cwd
            Model = $Model
            MaxTurns = $MaxTurns
            GrokHome = $GrokHome
            EvidenceDir = $EvidenceDir
            MinResultChars = $MinChars
            RequiredResultMarkers = @($Markers)
            TimeoutSec = $TimeoutSec
            Quiet = $true
        }
        if ($RequireJson) { $workerArgs.RequireJsonObject = $true }
        if ($JsonSchemaPath) { $workerArgs.JsonSchemaPath = $JsonSchemaPath }
        & $WorkerScript @workerArgs
        return @{
            exit_code = $LASTEXITCODE
            evidence_dir = $EvidenceDir
        }
    }
    [void]$ps.AddScript($script).AddArgument($workerScript).AddArgument($promptLane).AddArgument($Cwd).AddArgument($Model).AddArgument($MaxTurns).AddArgument($GrokHome).AddArgument($laneDir).AddArgument($MinResultChars).AddArgument(@($RequiredResultMarkers)).AddArgument([bool]$RequireJsonObject).AddArgument($JsonSchemaPath).AddArgument($TimeoutSec)
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

$deadline = (Get-Date).AddSeconds($TimeoutSec + 30)
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
        $laneLatest = Join-Path $j.dir "latest.json"
        if (Test-Path -LiteralPath $laneLatest) {
            try {
                $pending = Get-Content -LiteralPath $laneLatest -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($pending.pid) {
                    $item.outer_terminated_process_ids = @(Stop-ExactProcessTree -RootProcessId ([int]$pending.pid))
                }
            } catch { }
        }
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
            $item.effective_output_accepted = $m.effective_output_accepted -eq $true
            $item.requested_model = [string]$m.requested_model
            $item.observed_models = @($m.observed_models)
            $item.model_identity_ok = $m.model_identity_ok -eq $true
            $item.stop_reason = [string]$m.stop_reason
            $item.usage = $m.usage
            $item.usage_accounting_complete = $m.usage_accounting_complete -eq $true
            $item.result_text_chars = [int]$m.result_text_chars
            $item.max_turns_cli_applied = $m.max_turns_cli_applied -eq $true
            $item.worker_timed_out = $m.timed_out -eq $true
            $item.json_schema_path = [string]$m.json_schema_path
            $item.json_schema_source_path = [string]$m.json_schema_source_path
            $item.json_schema_snapshot_path = [string]$m.json_schema_snapshot_path
            $item.json_schema_sha256 = [string]$m.json_schema_sha256
            $item.json_schema_expected_sha256 = [string]$m.json_schema_expected_sha256
            $item.json_schema_observed_sha256 = [string]$m.json_schema_observed_sha256
            $item.json_schema_validator = [string]$m.json_schema_validator
            $item.schema_instance_valid = $m.schema_instance_valid -eq $true
            $item.effective_output_source = [string]$m.effective_output_source
            $item.structured_output_present = $m.structured_output_present -eq $true
            $item.status = if ($item.timed_out -or $item.worker_timed_out) {
                "timeout"
            } elseif (
                $item.exit_code -eq 0 -and
                $item.worker_status -eq "accepted" -and
                $item.effective_output_accepted
            ) { "accepted" } else { "rejected" }
        } catch { }
    }
    $results += [pscustomobject]$item
}

$okCount = @($results | Where-Object {
    $_.status -eq "accepted" -and
    $_.exit_code -eq 0 -and
    $_.effective_output_accepted -eq $true
}).Count
$inputTokens = [long](($results | ForEach-Object { [long]$_.usage.input_tokens } | Measure-Object -Sum).Sum)
$outputTokens = [long](($results | ForEach-Object { [long]$_.usage.output_tokens } | Measure-Object -Sum).Sum)
$totalTokens = [long](($results | ForEach-Object { [long]$_.usage.total_tokens } | Measure-Object -Sum).Sum)
$usageAccountingComplete = (@($results | Where-Object { $_.usage_accounting_complete -ne $true }).Count -eq 0)
$summary = [ordered]@{
    schema_version = "xinao.grok_worker_pool.v2"
    execution_contract_version = "xinao.grok.shared_execution_contract.v1"
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
    selection_path = $SelectionPath
    selection_decision_sha256 = [string]$selection.decision_sha256
    selected_provider_id = [string]$selection.provider_id
    selected_profile_ref = [string]$selection.profile_ref
    selected_transport_id = [string]$selection.transport_id
    cwd = $Cwd
    max_turns = $MaxTurns
    timeout_sec = $TimeoutSec
    min_result_chars = $MinResultChars
    required_result_markers = @($RequiredResultMarkers)
    require_json_object = [bool]($RequireJsonObject -or -not [string]::IsNullOrWhiteSpace($JsonSchemaPath))
    json_schema_path = $JsonSchemaPath
    ok_count = $okCount
    fail_count = $N - $okCount
    usage = [ordered]@{
        input_tokens = $inputTokens
        output_tokens = $outputTokens
        total_tokens = $totalTokens
    }
    usage_accounting_complete = $usageAccountingComplete
    all_ok = ($okCount -eq $N)
    acceptance_contract_ok = ($okCount -eq $N)
    pool_dir = $poolDir
    results = $results
    completion_claim_allowed = $false
    invoke_cn = ".\Invoke-GrokWorkerPool.ps1 -N $N -Prompt '...' -Cwd '<explicit>' -Model '$Model' -SelectionPath '<decision-receipt.json>' -MaxTurns auto"
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
