#Requires -Version 5.1
<#
.SYNOPSIS
  Single-shot OpenAI-compatible relay worker (A-leg peer, not Grok pool, not Temporal).
.DESCRIPTION
  Codex (or Grok 4.5) can direct-call this like a bounded host worker.
  Auth is a swappable key FILE HANDLE — never hardcode secrets in the script.
  Default: ssstoken OpenAI-compatible gateway. Not 333 mainline. Not Docker houtai-gongren.
.EXAMPLE
  .\Invoke-OpenAiCompatibleRelayWorker.ps1 -Prompt "Reply only: RELAY_OK" -Model gpt-5.6-sol -MinResultChars 1 -RequiredResultMarkers RELAY_OK
  .\Invoke-OpenAiCompatibleRelayWorker.ps1 -PromptFile .\task.md -Model gpt-5.4 -ApiStyle responses
#>
param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Model = "gpt-5.6-sol",
    [ValidateSet("chat_completions", "responses")]
    [string]$ApiStyle = "chat_completions",
    [string]$BaseUrl = "https://api.ssstoken.net/v1",
    [string]$KeyPath = "C:\Users\xx363\私钥\Codex-api.txt",
    [string]$EvidenceDir = "D:\XINAO_RESEARCH_RUNTIME\state\openai_relay_worker",
    [ValidateRange(1, 200000)]
    [int]$MaxTokens = 2048,
    [ValidateRange(1, 86400)]
    [int]$TimeoutSec = 120,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 1,
    [string[]]$RequiredResultMarkers = @(),
    [string]$RunId = "",
    [string]$WorkKey = "",
    [ValidateRange(1, 2147483647)]
    [int]$Attempt = 1,
    [string]$LogicalOperationId = "",
    [switch]$AllowInsecureLoopbackForTest,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false

function Read-Utf8Text([string]$Path) {
    return [IO.File]::ReadAllText($Path, $utf8).Trim()
}

function Write-Utf8File([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, $utf8)
}

function Get-RelayFailureCode([System.Management.Automation.ErrorRecord]$Record) {
    $message = [string]$Record.Exception.Message
    $owned = [regex]::Match($message, 'RELAY_WORKER_[A-Z0-9_]+')
    if ($owned.Success) { return $owned.Value }
    if ($Record.Exception -is [System.TimeoutException] -or $message -match '(?i)timed?\s*out|timeout') {
        return "RELAY_WORKER_TIMEOUT"
    }
    if ($Record.Exception.Response) {
        try { return "RELAY_WORKER_HTTP_" + [int]$Record.Exception.Response.StatusCode } catch {}
    }
    return "RELAY_WORKER_REQUEST_FAILED"
}

if ([string]::IsNullOrWhiteSpace($Prompt) -and [string]::IsNullOrWhiteSpace($PromptFile)) {
    throw "RELAY_WORKER_PROMPT_REQUIRED"
}
if (-not [string]::IsNullOrWhiteSpace($PromptFile)) {
    if (-not (Test-Path -LiteralPath $PromptFile -PathType Leaf)) {
        throw "RELAY_WORKER_PROMPT_FILE_MISSING: $PromptFile"
    }
    $Prompt = Read-Utf8Text $PromptFile
}
if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "RELAY_WORKER_PROMPT_EMPTY"
}
if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
    throw "RELAY_WORKER_KEY_PATH_MISSING: $KeyPath"
}

$apiKey = Read-Utf8Text $KeyPath
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "RELAY_WORKER_KEY_EMPTY: $KeyPath"
}
# allow "KEY=sk-..." or pure sk-
if ($apiKey -match '(?im)^\s*(?:OPENAI_API_KEY|API_KEY|KEY)\s*=\s*(.+)\s*$') {
    $apiKey = $Matches[1].Trim().Trim('"').Trim("'")
}
if ($apiKey -notmatch '^sk-') {
    throw "RELAY_WORKER_KEY_SHAPE_UNEXPECTED: expected sk-... in $KeyPath"
}

$BaseUrl = $BaseUrl.TrimEnd('/')
if ($BaseUrl -notmatch '/v1$') {
    # accept root gateway; normalize to /v1 for OpenAI-compatible paths
    if ($BaseUrl -match 'ssstoken\.net/?$') {
        $BaseUrl = "https://api.ssstoken.net/v1"
    }
}
$baseUri = $null
if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$baseUri)) {
    throw "RELAY_WORKER_BASE_URL_INVALID"
}
$isApprovedProductionProfile = (
    $baseUri.Scheme -ceq "https" -and
    $baseUri.Host -ceq "api.ssstoken.net" -and
    $baseUri.Port -eq 443 -and
    [string]::IsNullOrEmpty($baseUri.UserInfo) -and
    $baseUri.AbsolutePath.TrimEnd('/') -ceq "/v1" -and
    $baseUri.Query.Length -eq 0 -and
    $baseUri.Fragment.Length -eq 0
)
$isLoopbackTestProfile = (
    $AllowInsecureLoopbackForTest.IsPresent -and
    $baseUri.Scheme -ceq "http" -and
    $baseUri.Host -ceq "127.0.0.1" -and
    [string]::IsNullOrEmpty($baseUri.UserInfo) -and
    $baseUri.AbsolutePath.TrimEnd('/') -ceq "/v1"
)
if (-not $isApprovedProductionProfile -and -not $isLoopbackTestProfile) {
    throw "RELAY_WORKER_BASE_URL_NOT_ADMITTED"
}

$runId = if ([string]::IsNullOrWhiteSpace($RunId)) {
    "orw_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
} else {
    $RunId
}
if ($runId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
    throw "RELAY_WORKER_RUN_ID_INVALID"
}
if ([string]::IsNullOrWhiteSpace($WorkKey)) { $WorkKey = "relay:$runId" }
if ([string]::IsNullOrWhiteSpace($LogicalOperationId)) { $LogicalOperationId = $runId }

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$runDir = Join-Path $EvidenceDir $runId
if (Test-Path -LiteralPath $runDir) {
    throw "RELAY_WORKER_EVIDENCE_ID_CONFLICT"
}
New-Item -ItemType Directory -Path $runDir | Out-Null
$metaPath = Join-Path $runDir "meta.json"
$resultPath = Join-Path $runDir "result.txt"
$rawPath = Join-Path $runDir "raw_response.json"
$latest = Join-Path $EvidenceDir "latest.json"

$started = Get-Date
$status = "running"
$errorCode = ""
$textOut = ""
$usage = $null
$httpStatus = 0
$endpoint = ""
$requestDispatched = $false
$modelInvocationObserved = $false
$observedModel = ""
$responseId = ""
$terminalState = ""
$stopReason = ""
$resultSha256 = ""
$rawResponseSha256 = ""

$meta = [ordered]@{
    schema_version = "xinao.openai_compatible_relay_worker.v1"
    sentinel = "SENTINEL:OPENAI_COMPATIBLE_RELAY_WORKER"
    generated_at = $started.ToString("o")
    run_id = $runId
    work_key = $WorkKey
    logical_operation_id = $LogicalOperationId
    attempt = $Attempt
    transport_id = "direct-openai-compatible-relay"
    route_role = "a_leg_peer_not_grok_pool_not_temporal"
    not_333_mainline = $true
    completion_claim_allowed = $false
    provider_id = "ssstoken_openai_compatible_relay"
    profile_ref = "api.ssstoken.net/v1"
    selected_model = $Model
    api_style = $ApiStyle
    base_url = $BaseUrl
    auth_source = "key_file_handle"
    secret_material_recorded = $false
    max_tokens = $MaxTokens
    timeout_sec = $TimeoutSec
    min_result_chars = $MinResultChars
    required_result_markers = @($RequiredResultMarkers)
    prompt_chars = $Prompt.Length
    status = $status
    note_cn = "A腿同级 peer：Codex可直调；密钥只读文件句柄可热换；非 Grok WorkerPool、非 Temporal/houtai-gongren"
}

Write-Utf8File $metaPath ($meta | ConvertTo-Json -Depth 8)
Copy-Item -LiteralPath $metaPath -Destination $latest -Force

try {
    $headers = @{
        Authorization = "Bearer $apiKey"
        "Content-Type" = "application/json"
    }

    if ($ApiStyle -eq "chat_completions") {
        $endpoint = "$BaseUrl/chat/completions"
        $bodyObj = [ordered]@{
            model = $Model
            messages = @(
                [ordered]@{ role = "user"; content = $Prompt }
            )
            max_tokens = $MaxTokens
        }
    }
    else {
        $endpoint = "$BaseUrl/responses"
        $bodyObj = [ordered]@{
            model = $Model
            input = $Prompt
            max_output_tokens = $MaxTokens
        }
    }

    $bodyJson = $bodyObj | ConvertTo-Json -Depth 8 -Compress
    $meta.endpoint = $endpoint
    $meta.request_body_chars = $bodyJson.Length

    $requestDispatched = $true
    $resp = Invoke-WebRequest -Uri $endpoint -Method POST -Headers $headers -Body $bodyJson -UseBasicParsing -TimeoutSec $TimeoutSec -MaximumRedirection 0
    $httpStatus = [int]$resp.StatusCode
    $raw = $resp.Content
    if (-not [string]::IsNullOrWhiteSpace($apiKey) -and $raw.Contains($apiKey)) {
        throw "RELAY_WORKER_SECRET_REFLECTION_DETECTED"
    }
    Write-Utf8File $rawPath $raw
    $rawResponseSha256 = (Get-FileHash -LiteralPath $rawPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $j = $raw | ConvertFrom-Json
    $observedModel = [string]$j.model
    $responseId = [string]$j.id
    if ([string]::IsNullOrWhiteSpace($observedModel)) {
        throw "RELAY_WORKER_OBSERVED_MODEL_MISSING"
    }
    if ($observedModel -cne $Model) {
        throw "RELAY_WORKER_MODEL_IDENTITY_MISMATCH: selected=$Model observed=$observedModel"
    }
    if ($ApiStyle -eq "chat_completions") {
        if ($j.choices -and $j.choices.Count -gt 0) {
            $textOut = [string]$j.choices[0].message.content
            $stopReason = [string]$j.choices[0].finish_reason
        }
        if ($stopReason -cne "stop") {
            throw "RELAY_WORKER_CHAT_TERMINAL_NOT_ACCEPTED"
        }
        $terminalState = "completed"
        if ($j.usage) {
            $usage = [ordered]@{
                prompt_tokens = $j.usage.prompt_tokens
                completion_tokens = $j.usage.completion_tokens
                total_tokens = $j.usage.total_tokens
            }
        }
    }

    else {
        $terminalState = [string]$j.status
        $stopReason = if ($j.incomplete_details -and $j.incomplete_details.reason) {
            [string]$j.incomplete_details.reason
        } else {
            $terminalState
        }
        if ($terminalState -cne "completed") {
            throw "RELAY_WORKER_RESPONSES_TERMINAL_NOT_ACCEPTED"
        }
        if ($j.output_text) {
            $textOut = [string]$j.output_text
        }
        elseif ($j.output) {
            $parts = New-Object System.Collections.Generic.List[string]
            foreach ($o in @($j.output)) {
                if ($null -eq $o.content) { continue }
                foreach ($c in @($o.content)) {
                    if ($c.text) { [void]$parts.Add([string]$c.text) }
                }
            }
            $textOut = [string]::Join("", $parts)
        }
        if ($j.usage) {
            $usage = [ordered]@{
                input_tokens = $j.usage.input_tokens
                output_tokens = $j.usage.output_tokens
                total_tokens = $j.usage.total_tokens
                cached_tokens = if ($j.usage.input_tokens_details) { $j.usage.input_tokens_details.cached_tokens } else { $null }
            }
        }
    }

    if ($null -eq $usage -or $null -eq $usage.total_tokens -or [int64]$usage.total_tokens -le 0) {
        throw "RELAY_WORKER_POSITIVE_USAGE_REQUIRED"
    }
    $modelInvocationObserved = $true

    if ([string]::IsNullOrWhiteSpace($textOut)) {
        throw "RELAY_WORKER_EMPTY_MODEL_TEXT"
    }
    if ($textOut.Length -lt $MinResultChars) {
        throw "RELAY_WORKER_MIN_RESULT_CHARS: got=$($textOut.Length) need=$MinResultChars"
    }
    foreach ($marker in @($RequiredResultMarkers)) {
        if (-not [string]::IsNullOrWhiteSpace($marker) -and $textOut -notlike "*$marker*") {
            throw "RELAY_WORKER_MARKER_MISSING: $marker"
        }
    }

    Write-Utf8File $resultPath $textOut
    $resultSha256 = (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $status = "ok"
}
catch {
    $errorCode = Get-RelayFailureCode $_
    $status = if ($errorCode -eq "RELAY_WORKER_TIMEOUT") { "timed_out" } else { "failed" }
    if ($_.Exception.Response -and -not $httpStatus) {
        try { $httpStatus = [int]$_.Exception.Response.StatusCode } catch {}
    }
    if (-not [string]::IsNullOrWhiteSpace($textOut)) {
        Write-Utf8File $resultPath $textOut
    }
}

$finished = Get-Date
$meta.status = $status
$meta.finished_at = $finished.ToString("o")
$meta.duration_ms = [int](($finished - $started).TotalMilliseconds)
$meta.http_status = $httpStatus
$meta.endpoint = $endpoint
$meta.error = $errorCode
$meta.usage = $usage
$meta.request_dispatched = $requestDispatched
$meta.model_invocation_observed = $modelInvocationObserved
$meta.observed_model = $observedModel
$meta.selected_equals_observed = (
    -not [string]::IsNullOrWhiteSpace($observedModel) -and $observedModel -ceq $Model
)
$meta.response_id = $responseId
$meta.terminal_state = $terminalState
$meta.stop_reason = $stopReason
$meta.result_chars = if ($textOut) { $textOut.Length } else { 0 }
$meta.result_path = $resultPath
$meta.result_sha256 = $resultSha256
$meta.raw_response_path = $rawPath
$meta.raw_response_sha256 = $rawResponseSha256
$meta.result_excerpt = if ($textOut.Length -gt 500) { $textOut.Substring(0, 500) } else { $textOut }

Write-Utf8File $metaPath ($meta | ConvertTo-Json -Depth 10)
Copy-Item -LiteralPath $metaPath -Destination $latest -Force

if (-not $Quiet) {
    Write-Output ($meta | ConvertTo-Json -Depth 10 -Compress)
}

if ($status -ne "ok") {
    exit 1
}
exit 0
