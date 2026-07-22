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
    [string]$PythonExe = "",
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

$rawKeyMaterial = Read-Utf8Text $KeyPath
if ([string]::IsNullOrWhiteSpace($rawKeyMaterial)) {
    throw "RELAY_WORKER_KEY_EMPTY: $KeyPath"
}
$apiKey = $rawKeyMaterial
$csvOpenAiCompatible = ""
# Aliyun Bailian / DashScope export CSV: id,apiKey,apiHost,openAiCompatible,...
if ($KeyPath -match '(?i)\.csv$') {
    $csvKey = ""
    foreach ($line in ($rawKeyMaterial -split "`r?`n")) {
        if ($line -match '^\s*apiKey\s*,\s*(.+)\s*$') {
            $csvKey = $Matches[1].Trim().Trim('"').Trim("'")
        }
        elseif ($line -match '^\s*openAiCompatible\s*,\s*(.+)\s*$') {
            $csvOpenAiCompatible = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    if ([string]::IsNullOrWhiteSpace($csvKey)) {
        throw "RELAY_WORKER_CSV_APIKEY_MISSING: $KeyPath"
    }
    $apiKey = $csvKey
    if ([string]::IsNullOrWhiteSpace($BaseUrl) -or $BaseUrl -eq "https://api.ssstoken.net/v1") {
        if (-not [string]::IsNullOrWhiteSpace($csvOpenAiCompatible)) {
            $BaseUrl = $csvOpenAiCompatible
        }
    }
}
# allow "KEY=sk-..." or pure sk- / sk-ws- (DashScope workspace keys)
if ($apiKey -match '(?im)^\s*(?:OPENAI_API_KEY|API_KEY|KEY|apiKey)\s*=\s*(.+)\s*$') {
    $apiKey = $Matches[1].Trim().Trim('"').Trim("'")
}
if ($apiKey -notmatch '^sk-') {
    throw "RELAY_WORKER_KEY_SHAPE_UNEXPECTED: expected sk-... in $KeyPath"
}

$BaseUrl = $BaseUrl.TrimEnd('/')
if ($BaseUrl -notmatch '/v1$' -and $BaseUrl -notmatch '/compatible-mode/v1$') {
    # accept root gateway; normalize known hosts to OpenAI-compatible paths
    if ($BaseUrl -match 'ssstoken\.net/?$') {
        $BaseUrl = "https://api.ssstoken.net/v1"
    }
    elseif ($BaseUrl -match 'lucisapi\.ai/?$') {
        $BaseUrl = "https://lucisapi.ai/v1"
    }
    elseif ($BaseUrl -match 'api\.deepseek\.com/?$') {
        $BaseUrl = "https://api.deepseek.com/v1"
    }
}
$baseUri = $null
if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$baseUri)) {
    throw "RELAY_WORKER_BASE_URL_INVALID"
}
function Test-RelayAdmittedHttpsBase([Uri]$Uri, [string]$HostExact, [string]$PathExact) {
    return (
        $Uri.Scheme -ceq "https" -and
        $Uri.Host -ceq $HostExact -and
        $Uri.Port -eq 443 -and
        [string]::IsNullOrEmpty($Uri.UserInfo) -and
        $Uri.AbsolutePath.TrimEnd('/') -ceq $PathExact -and
        $Uri.Query.Length -eq 0 -and
        $Uri.Fragment.Length -eq 0
    )
}
$pathNorm = $baseUri.AbsolutePath.TrimEnd('/')
$isSss = Test-RelayAdmittedHttpsBase $baseUri "api.ssstoken.net" "/v1"
$isLucis = (Test-RelayAdmittedHttpsBase $baseUri "lucisapi.ai" "/v1") -or (Test-RelayAdmittedHttpsBase $baseUri "www.lucisapi.ai" "/v1")
$isDeepSeek = (Test-RelayAdmittedHttpsBase $baseUri "api.deepseek.com" "/v1") -or (
    $baseUri.Scheme -ceq "https" -and
    $baseUri.Host -ceq "api.deepseek.com" -and
    $baseUri.Port -eq 443 -and
    [string]::IsNullOrEmpty($baseUri.UserInfo) -and
    ($pathNorm -ceq "" -or $pathNorm -ceq "/" -or $pathNorm -ceq "/v1") -and
    $baseUri.Query.Length -eq 0 -and
    $baseUri.Fragment.Length -eq 0
)
$isDashScopeDefault = Test-RelayAdmittedHttpsBase $baseUri "dashscope.aliyuncs.com" "/compatible-mode/v1"
$isBailianWorkspace = (
    $baseUri.Scheme -ceq "https" -and
    $baseUri.Port -eq 443 -and
    [string]::IsNullOrEmpty($baseUri.UserInfo) -and
    $baseUri.Query.Length -eq 0 -and
    $baseUri.Fragment.Length -eq 0 -and
    $pathNorm -ceq "/compatible-mode/v1" -and
    $baseUri.Host -match '^[a-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com$'
)
$isApprovedProductionProfile = $isSss -or $isLucis -or $isDeepSeek -or $isDashScopeDefault -or $isBailianWorkspace
$isLoopbackTestProfile = (
    $AllowInsecureLoopbackForTest.IsPresent -and
    $baseUri.Scheme -ceq "http" -and
    $baseUri.Host -ceq "127.0.0.1" -and
    [string]::IsNullOrEmpty($baseUri.UserInfo) -and
    $baseUri.AbsolutePath.TrimEnd('/') -ceq "/v1"
)
if (-not $isApprovedProductionProfile -and -not $isLoopbackTestProfile) {
    throw "RELAY_WORKER_BASE_URL_NOT_ADMITTED: $BaseUrl"
}

$providerId = "openai_compatible_relay"
$profileRef = $baseUri.Host + $pathNorm
if ($isSss) { $providerId = "ssstoken_openai_compatible_relay" }
elseif ($isLucis) { $providerId = "lucis_openai_compatible_relay" }
elseif ($isDeepSeek) { $providerId = "deepseek_openai_compatible" }
elseif ($isDashScopeDefault -or $isBailianWorkspace) { $providerId = "qwen_bailian_openai_compatible" }
elseif ($isLoopbackTestProfile) { $providerId = "loopback_openai_compatible_test" }

$sdkWire = Join-Path $PSScriptRoot "openai_sdk_wire.py"
if (-not (Test-Path -LiteralPath $sdkWire -PathType Leaf)) {
    throw "RELAY_WORKER_SDK_WIRE_MISSING: $sdkWire"
}
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    if (-not [string]::IsNullOrWhiteSpace($env:XINAO_OPENAI_SDK_PYTHON)) {
        $PythonExe = $env:XINAO_OPENAI_SDK_PYTHON
    }
    else {
        $PythonExe = "E:\XINAO_RESEARCH_WORKSPACES\S\.venv\Scripts\python.exe"
    }
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    $pythonCommand = Get-Command $PythonExe -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "RELAY_WORKER_SDK_PYTHON_MISSING: $PythonExe"
    }
    $PythonExe = $pythonCommand.Source
}

function Invoke-RelaySdk([string]$RequestJson) {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $PythonExe
    $startInfo.Arguments = '"' + $sdkWire + '"'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "RELAY_WORKER_SDK_PROCESS_START_FAILED"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write($RequestJson)
        $process.StandardInput.Close()
        $waitMilliseconds = [Math]::Min([int64]::MaxValue, ([int64]$TimeoutSec + 15) * 1000)
        if (-not $process.WaitForExit([int]$waitMilliseconds)) {
            try { $process.Kill() } catch {}
            throw "RELAY_WORKER_TIMEOUT"
        }
        $stdout = [string]$stdoutTask.Result
        [void]$stderrTask.Result
        if ([string]::IsNullOrWhiteSpace($stdout)) {
            throw "RELAY_WORKER_SDK_EMPTY_ENVELOPE"
        }
        try { $sdkResult = $stdout | ConvertFrom-Json }
        catch { throw "RELAY_WORKER_SDK_INVALID_ENVELOPE" }
        if ($sdkResult.ok -ne $true -or $process.ExitCode -ne 0) {
            $sdkStatus = [int]$sdkResult.status_code
            $sdkErrorType = [string]$sdkResult.error_type
            if ($sdkErrorType -match '(?i)timeout') {
                throw "RELAY_WORKER_TIMEOUT"
            }
            if ($sdkStatus -gt 0) {
                throw "RELAY_WORKER_HTTP_$sdkStatus"
            }
            $safeErrorType = [regex]::Replace($sdkErrorType.ToUpperInvariant(), '[^A-Z0-9_]', '_')
            if ([string]::IsNullOrWhiteSpace($safeErrorType)) { $safeErrorType = "REQUEST_FAILED" }
            throw "RELAY_WORKER_SDK_$safeErrorType"
        }
        return $sdkResult
    }
    finally {
        $process.Dispose()
    }
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
$modelIdentityAccepted = $false
$selectedEqualsObserved = $false
$modelAliasAccepted = $false
$observedModel = ""
$responseId = ""
$sdkRequestId = ""
$sdkVersion = ""
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
    provider_id = $providerId
    profile_ref = $profileRef
    selected_model = $Model
    api_style = $ApiStyle
    base_url = $BaseUrl
    auth_source = "key_file_handle"
    secret_material_recorded = $false
    wire_client = "openai-python"
    sdk_max_retries = 0
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
    if ($ApiStyle -eq "chat_completions") {
        $endpoint = "$BaseUrl/chat/completions"
    }
    else {
        $endpoint = "$BaseUrl/responses"
    }

    $meta.endpoint = $endpoint
    $sdkRequest = [ordered]@{
        api_key = $apiKey
        base_url = $BaseUrl
        api_style = $ApiStyle
        model = $Model
        prompt = $Prompt
        max_tokens = $MaxTokens
        timeout_seconds = $TimeoutSec
    }
    $sdkRequestJson = $sdkRequest | ConvertTo-Json -Depth 8 -Compress

    $requestDispatched = $true
    $sdkResult = Invoke-RelaySdk $sdkRequestJson
    $httpStatus = [int]$sdkResult.status_code
    $sdkRequestId = [string]$sdkResult.request_id
    $sdkVersion = [string]$sdkResult.sdk_version
    $raw = [string]$sdkResult.raw_response
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
    # Exact identity remains separately observable. Provider-specific aliases
    # may satisfy the acceptance contract without falsifying exact equality.
    $aliasPairs = @(
        @("deepseek-chat", "deepseek-v4-flash"),
        @("deepseek-reasoner", "deepseek-v4-pro"),
        @("deepseek-reasoner", "deepseek-reasoner")
    )
    $aliasOk = $false
    if ($isDeepSeek) {
        foreach ($pair in $aliasPairs) {
            if (($Model -ceq $pair[0] -and $observedModel -ceq $pair[1]) -or
                ($Model -ceq $pair[1] -and $observedModel -ceq $pair[0])) {
                $aliasOk = $true
                break
            }
        }
    }
    $selectedEqualsObserved = $observedModel -ceq $Model
    $modelIdentityAccepted = $aliasOk -or $selectedEqualsObserved -or
        ($observedModel.StartsWith($Model + "-", [StringComparison]::Ordinal)) -or
        ($Model.StartsWith($observedModel + "-", [StringComparison]::Ordinal))
    if (-not $modelIdentityAccepted) {
        throw "RELAY_WORKER_MODEL_IDENTITY_MISMATCH: selected=$Model observed=$observedModel"
    }
    $modelAliasAccepted = $modelIdentityAccepted -and -not $selectedEqualsObserved
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
    if ($errorCode -match '^RELAY_WORKER_HTTP_([0-9]{3})$') {
        $httpStatus = [int]$Matches[1]
    }
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
$meta.selected_equals_observed = [bool]$selectedEqualsObserved
$meta.model_identity_accepted = [bool]$modelIdentityAccepted
$meta.model_alias_accepted = [bool]$modelAliasAccepted
$meta.response_id = $responseId
$meta.sdk_request_id = $sdkRequestId
$meta.sdk_version = $sdkVersion
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
