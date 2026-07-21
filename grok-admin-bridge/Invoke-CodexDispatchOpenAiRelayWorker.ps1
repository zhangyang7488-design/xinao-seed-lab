#Requires -Version 5.1
<#
.SYNOPSIS
  Codex A-leg peer entry: dispatch OpenAI-compatible relay worker(s).
.DESCRIPTION
  Same call shape spirit as Invoke-CodexDispatchGrokWorkerPool, but provider is
  HTTP OpenAI-compatible relay (default ssstoken). Key is a file handle path
  (swap file contents anytime). Does NOT enter Grok WorkerPool. Does NOT start
  Temporal / Docker / second orchestrator.
.EXAMPLE
  .\Invoke-CodexDispatchOpenAiRelayWorker.ps1 -WorkKey relay:smoke -Prompt "Reply only: RELAY_OK" -Model gpt-5.6-sol -RequiredResultMarkers RELAY_OK
#>
param(
    [ValidateRange(1, 1)]
    [int]$N = 1,
    [Parameter(Mandatory=$true)]
    [ValidateNotNullOrEmpty()]
    [string]$WorkKey,
    [ValidateRange(1, 2147483647)]
    [int]$Attempt = 1,
    [string]$LogicalOperationId = "",
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Model = "gpt-5.6-sol",
    [ValidateSet("chat_completions", "responses")]
    [string]$ApiStyle = "chat_completions",
    [string]$BaseUrl = "https://api.ssstoken.net/v1",
    [string]$KeyPath = "C:\Users\xx363\私钥\Codex-api.txt",
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [ValidateRange(1, 200000)]
    [int]$MaxTokens = 2048,
    [ValidateRange(1, 86400)]
    [int]$TimeoutSec = 120,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 1,
    [string[]]$RequiredResultMarkers = @(),
    [string]$DispatchId = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$worker = Join-Path $bridge "Invoke-OpenAiCompatibleRelayWorker.ps1"
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) {
    throw "RELAY_WORKER_SCRIPT_MISSING: $worker"
}

if ([string]::IsNullOrWhiteSpace($Prompt) -and [string]::IsNullOrWhiteSpace($PromptFile)) {
    throw "RELAY_DISPATCH_PROMPT_REQUIRED"
}

$dispatchId = if ([string]::IsNullOrWhiteSpace($DispatchId)) {
    "cdx_orw_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $DispatchId
}
if ($dispatchId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
    throw "RELAY_DISPATCH_ID_INVALID"
}
if ([string]::IsNullOrWhiteSpace($LogicalOperationId)) { $LogicalOperationId = $dispatchId }

$evidenceRoot = Join-Path $RuntimeRoot "state\openai_relay_worker"
$dispatchDir = Join-Path $evidenceRoot ("dispatch_" + $dispatchId)
if (Test-Path -LiteralPath $dispatchDir) {
    throw "RELAY_DISPATCH_EVIDENCE_ID_CONFLICT"
}
New-Item -ItemType Directory -Path $dispatchDir | Out-Null

$started = Get-Date
$items = New-Object System.Collections.Generic.List[object]
$okCount = 0
$failCount = 0

for ($i = 0; $i -lt $N; $i++) {
    $laneId = "{0}_w{1:d2}" -f $dispatchId, ($i + 1)
    $args = @{
        Model = $Model
        ApiStyle = $ApiStyle
        BaseUrl = $BaseUrl
        KeyPath = $KeyPath
        EvidenceDir = $evidenceRoot
        MaxTokens = $MaxTokens
        TimeoutSec = $TimeoutSec
        MinResultChars = $MinResultChars
        RequiredResultMarkers = $RequiredResultMarkers
        RunId = $laneId
        WorkKey = $WorkKey
        Attempt = $Attempt
        LogicalOperationId = $LogicalOperationId
        Quiet = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($PromptFile)) {
        $args.PromptFile = $PromptFile
    }
    else {
        $args.Prompt = $Prompt
    }

    $laneStarted = Get-Date
    $exitCode = 0
    $stdout = ""
    try {
        $stdout = & $worker @args 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { $exitCode = $LASTEXITCODE }
    }
    catch {
        $exitCode = 1
        $stdout = $_.Exception.Message
    }

    $metaPath = Join-Path $evidenceRoot (Join-Path $laneId "meta.json")
    $laneMeta = $null
    if (Test-Path -LiteralPath $metaPath -PathType Leaf) {
        try { $laneMeta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
    }

    $positiveUsage = (
        $laneMeta -and $laneMeta.usage -and $null -ne $laneMeta.usage.total_tokens -and
        [int64]$laneMeta.usage.total_tokens -gt 0
    )
    $resultHashReadback = $false
    $rawHashReadback = $false
    if ($laneMeta) {
        $resultFile = [string]$laneMeta.result_path
        $rawFile = [string]$laneMeta.raw_response_path
        if ((Test-Path -LiteralPath $resultFile -PathType Leaf) -and [string]$laneMeta.result_sha256 -match '^[0-9a-f]{64}$') {
            $resultHashReadback = [string]::Equals(
                (Get-FileHash -LiteralPath $resultFile -Algorithm SHA256).Hash.ToLowerInvariant(),
                [string]$laneMeta.result_sha256,
                [StringComparison]::Ordinal
            )
        }
        if ((Test-Path -LiteralPath $rawFile -PathType Leaf) -and [string]$laneMeta.raw_response_sha256 -match '^[0-9a-f]{64}$') {
            $rawHashReadback = [string]::Equals(
                (Get-FileHash -LiteralPath $rawFile -Algorithm SHA256).Hash.ToLowerInvariant(),
                [string]$laneMeta.raw_response_sha256,
                [StringComparison]::Ordinal
            )
        }
    }
    $ok = (
        $exitCode -eq 0 -and $laneMeta -and $laneMeta.status -eq "ok" -and
        $laneMeta.http_status -eq 200 -and $laneMeta.selected_equals_observed -eq $true -and
        $laneMeta.model_invocation_observed -eq $true -and $positiveUsage -and
        $laneMeta.terminal_state -eq "completed" -and
        $resultHashReadback -and $rawHashReadback
    )
    if ($ok) { $okCount++ } else { $failCount++ }

    $items.Add([ordered]@{
        lane_id = $laneId
        exit_code = $exitCode
        ok = [bool]$ok
        status = if ($laneMeta) { [string]$laneMeta.status } else { "unknown" }
        terminal_state = if ($laneMeta) { [string]$laneMeta.terminal_state } else { "" }
        stop_reason = if ($laneMeta) { [string]$laneMeta.stop_reason } else { "" }
        work_key = $WorkKey
        logical_operation_id = $LogicalOperationId
        attempt = $Attempt
        selected_model = $Model
        observed_model = if ($laneMeta) { [string]$laneMeta.observed_model } else { "" }
        selected_equals_observed = if ($laneMeta) { [bool]$laneMeta.selected_equals_observed } else { $false }
        result_excerpt = if ($laneMeta) { [string]$laneMeta.result_excerpt } else { "" }
        usage = if ($laneMeta) { $laneMeta.usage } else { $null }
        meta_path = $metaPath
        duration_ms = [int]((Get-Date) - $laneStarted).TotalMilliseconds
        result_hash_readback = [bool]$resultHashReadback
        raw_hash_readback = [bool]$rawHashReadback
        worker_error_code = if ($laneMeta) { [string]$laneMeta.error } else { "RELAY_WORKER_META_MISSING" }
    }) | Out-Null
}

$finished = Get-Date
$dispatchStatus = "partial"
if ($failCount -eq 0) { $dispatchStatus = "ok" }
elseif ($okCount -eq 0) { $dispatchStatus = "failed" }

$summary = [ordered]@{
    schema_version = "xinao.codex_dispatch_openai_relay_worker.v1"
    sentinel = "SENTINEL:CODEX_DISPATCH_OPENAI_RELAY_WORKER"
    generated_at = $started.ToString("o")
    finished_at = $finished.ToString("o")
    duration_ms = [int](($finished - $started).TotalMilliseconds)
    dispatch_id = $dispatchId
    work_key = $WorkKey
    logical_operation_id = $LogicalOperationId
    attempt = $Attempt
    transport_id = "direct-openai-compatible-relay"
    route_role = "a_leg_peer_codex_direct_call"
    not_333_mainline = $true
    completion_claim_allowed = $false
    provider_id = "ssstoken_openai_compatible_relay"
    n = $N
    selected_model = $Model
    api_style = $ApiStyle
    base_url = $BaseUrl
    auth_source = "key_file_handle"
    secret_material_recorded = $false
    ok_count = $okCount
    fail_count = $failCount
    status = $dispatchStatus
    workers = @($items.ToArray())
    evidence_root = $evidenceRoot
    dispatch_dir = $dispatchDir
    boundary_cn = "A腿同级 peer：Codex 直调 OpenAI 兼容中转工人；密钥文件可热换；不进 Grok WorkerPool；不是 Temporal/333"
    hot_path_cn = "Codex -> Invoke-CodexDispatchOpenAiRelayWorker -> Invoke-OpenAiCompatibleRelayWorker (HTTP)"
    peer_of = "Invoke-CodexDispatchGrokWorkerPool / direct-grok-worker-pool"
}

$summaryPath = Join-Path $dispatchDir "dispatch_summary.json"
$latestDispatch = Join-Path $evidenceRoot "latest_dispatch.json"
$json = $summary | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($summaryPath, $json, (New-Object System.Text.UTF8Encoding $false))
Copy-Item -LiteralPath $summaryPath -Destination $latestDispatch -Force

if (-not $Quiet) {
    Write-Output ($summary | ConvertTo-Json -Depth 12 -Compress)
}

if ($summary.status -eq "failed") { exit 1 }
if ($summary.status -eq "partial") { exit 2 }
exit 0
