#Requires -Version 5.1
<#
.SYNOPSIS
  Single-shot provider-neutral OpenAI-compatible cognitive worker.
.DESCRIPTION
  A host supervisor calls this with explicit provider, model and key-file
  bindings. Auth is a swappable key FILE HANDLE; the worker has no local tool
  authority and never hardcodes secrets.
.EXAMPLE
  .\Invoke-OpenAiCompatibleRelayWorker.ps1 -Prompt "Reply only: RELAY_OK" -Model gpt-5.6-sol -MinResultChars 1 -RequiredResultMarkers RELAY_OK
  .\Invoke-OpenAiCompatibleRelayWorker.ps1 -PromptFile .\task.md -Model gpt-5.4 -ApiStyle responses
#>
param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [ValidateSet("general_cognitive", "cognitive_audit")]
    [string]$WorkClass = "general_cognitive",
    [Parameter(Mandatory=$true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProviderContractPath,
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedProviderContractSha256,
    [string]$ContextManifestFile = "",
    [string]$ExpectedContextManifestSha256 = "",
    [string]$JsonSchemaPath = "",
    [string]$ExpectedJsonSchemaSha256 = "",
    [Parameter(Mandatory=$true)]
    [ValidateNotNullOrEmpty()]
    [string]$Model,
    [ValidateSet("chat_completions", "responses")]
    [string]$ApiStyle = "chat_completions",
    [Parameter(Mandatory=$true)]
    [ValidateNotNullOrEmpty()]
    [string]$BaseUrl,
    [Parameter(Mandatory=$true)]
    [ValidateNotNullOrEmpty()]
    [string]$KeyPath,
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

function Get-FileSha256Lower([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-BytesSha256Lower([byte[]]$Bytes) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($hasher.ComputeHash($Bytes))) -replace "-", "").ToLowerInvariant()
    }
    finally { $hasher.Dispose() }
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

$resolvedProviderContract = [IO.Path]::GetFullPath($ProviderContractPath)
if (-not (Test-Path -LiteralPath $resolvedProviderContract -PathType Leaf)) {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_MISSING: $resolvedProviderContract"
}
$providerContractSha256 = Get-FileSha256Lower $resolvedProviderContract
if (-not [string]::Equals(
    $providerContractSha256,
    $ExpectedProviderContractSha256.ToLowerInvariant(),
    [StringComparison]::Ordinal
)) {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_HASH_MISMATCH"
}
try {
    $providerContract = Read-Utf8Text $resolvedProviderContract | ConvertFrom-Json
}
catch {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_INVALID_JSON"
}
if ([string]$providerContract.module_role -cne "replaceable_provider_binding") {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_ROLE_INVALID"
}
$providerId = [string]$providerContract.provider_id
if ([string]::IsNullOrWhiteSpace($providerId)) {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_ID_MISSING"
}
$admittedExactBaseUrls = @($providerContract.admission.exact_https_base_urls)
$admittedHostPatterns = @($providerContract.admission.https_host_patterns)
if ($admittedExactBaseUrls.Count -eq 0 -and $admittedHostPatterns.Count -eq 0) {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_ADMISSION_EMPTY"
}
if ($providerContract.model_identity.allow_version_suffix_prefix_match -notin @($true, $false)) {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_MODEL_IDENTITY_INVALID"
}
if ($null -eq $providerContract.model_identity.accepted_alias_pairs) {
    throw "RELAY_WORKER_PROVIDER_CONTRACT_MODEL_ALIASES_MISSING"
}

$cognitiveAudit = $WorkClass -ceq "cognitive_audit"
$resolvedContextManifest = ""
$contextManifestSha256 = ""
$contextSha256 = ""
$resolvedJsonSchema = ""
$jsonSchemaSha256 = ""
$schemaInstanceValid = $null
if ($cognitiveAudit) {
    if ([string]::IsNullOrWhiteSpace($ContextManifestFile) -or
        [string]::IsNullOrWhiteSpace($ExpectedContextManifestSha256) -or
        [string]::IsNullOrWhiteSpace($JsonSchemaPath) -or
        [string]::IsNullOrWhiteSpace($ExpectedJsonSchemaSha256)) {
        throw "RELAY_WORKER_COGNITIVE_AUDIT_CONTRACT_INCOMPLETE"
    }
    $resolvedContextManifest = [IO.Path]::GetFullPath($ContextManifestFile)
    if (-not (Test-Path -LiteralPath $resolvedContextManifest -PathType Leaf)) {
        throw "RELAY_WORKER_CONTEXT_MANIFEST_MISSING"
    }
    $contextManifestSha256 = Get-FileSha256Lower $resolvedContextManifest
    if ($ExpectedContextManifestSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        $contextManifestSha256 -cne $ExpectedContextManifestSha256.ToLowerInvariant()) {
        throw "RELAY_WORKER_CONTEXT_MANIFEST_HASH_MISMATCH"
    }
    $contextRaw = [IO.File]::ReadAllText($resolvedContextManifest, $utf8)
    try { $contextManifest = $contextRaw | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "RELAY_WORKER_CONTEXT_MANIFEST_INVALID_JSON" }
    if ([string]$contextManifest.schema_version -cne "xinao.context_slice_manifest.v1" -or
        $contextManifest.authority -ne $false -or
        $contextManifest.completion_claim_allowed -ne $false -or
        @($contextManifest.sources).Count -lt 1 -or
        [string]$contextManifest.context_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "RELAY_WORKER_CONTEXT_MANIFEST_CONTRACT_INVALID"
    }
    $contextSha256 = [string]$contextManifest.context_sha256

    $resolvedJsonSchema = [IO.Path]::GetFullPath($JsonSchemaPath)
    if (-not (Test-Path -LiteralPath $resolvedJsonSchema -PathType Leaf)) {
        throw "RELAY_WORKER_JSON_SCHEMA_MISSING"
    }
    $jsonSchemaSha256 = Get-FileSha256Lower $resolvedJsonSchema
    if ($ExpectedJsonSchemaSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
        $jsonSchemaSha256 -cne $ExpectedJsonSchemaSha256.ToLowerInvariant()) {
        throw "RELAY_WORKER_JSON_SCHEMA_HASH_MISMATCH"
    }
    try { $null = [IO.File]::ReadAllText($resolvedJsonSchema, $utf8) | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "RELAY_WORKER_JSON_SCHEMA_INVALID_JSON" }

    $roleContract = @"
XINAO_COGNITIVE_AUDIT_CONTRACT_V1
WORK_CLASS=cognitive_audit
CANNOT_ACCESS_FS=true
TOOL_EXECUTION_ALLOWED=false
INPUT_MODE=host_embedded_hash_bound
OUTPUT_AUTHORITY=candidate_only
INDEPENDENT_VALIDATION_CLAIM_ALLOWED=false
REPAIR_AUTHORIZED=false
Base every claim only on the embedded evidence package. Cite its exact path, source sha256, line range, and content sha256. If the package is insufficient, return EVIDENCE_INCOMPLETE. Return only one JSON object conforming to the bound output schema. Never emit REPAIR_REQUIRED or a worktree mutation instruction as authority.
"@
    $Prompt = $roleContract.Trim() + "`n`nTASK`n" + $Prompt.Trim() + "`n`nHASH_BOUND_EVIDENCE_PACKAGE`n" + $contextRaw.Trim()
}
elseif (-not [string]::IsNullOrWhiteSpace($ContextManifestFile) -or
        -not [string]::IsNullOrWhiteSpace($ExpectedContextManifestSha256)) {
    throw "RELAY_WORKER_CONTEXT_MANIFEST_REQUIRES_COGNITIVE_AUDIT"
}
$promptSha256 = Get-BytesSha256Lower $utf8.GetBytes($Prompt)
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
}
# allow "KEY=sk-..." or pure sk- / sk-ws- (DashScope workspace keys)
if ($apiKey -match '(?im)^\s*(?:OPENAI_API_KEY|API_KEY|KEY|apiKey)\s*=\s*(.+)\s*$') {
    $apiKey = $Matches[1].Trim().Trim('"').Trim("'")
}
if ($apiKey -notmatch '^sk-') {
    throw "RELAY_WORKER_KEY_SHAPE_UNEXPECTED: expected sk-... in $KeyPath"
}

$BaseUrl = $BaseUrl.TrimEnd('/')
$baseUri = $null
if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$baseUri)) {
    throw "RELAY_WORKER_BASE_URL_INVALID"
}
$pathNorm = $baseUri.AbsolutePath.TrimEnd('/')
$isSecureBaseShape = (
    $baseUri.Scheme -ceq "https" -and
    $baseUri.Port -eq 443 -and
    [string]::IsNullOrEmpty($baseUri.UserInfo) -and
    $baseUri.Query.Length -eq 0 -and
    $baseUri.Fragment.Length -eq 0
)
$isApprovedProductionProfile = $false
if ($isSecureBaseShape) {
    foreach ($exactBaseUrl in $admittedExactBaseUrls) {
        if ([string]::Equals(
            $BaseUrl,
            ([string]$exactBaseUrl).TrimEnd('/'),
            [StringComparison]::Ordinal
        )) {
            $isApprovedProductionProfile = $true
            break
        }
    }
    if (-not $isApprovedProductionProfile) {
        foreach ($pattern in $admittedHostPatterns) {
            $hostRegex = [string]$pattern.host_regex
            $requiredPath = ([string]$pattern.path).TrimEnd('/')
            if ([string]::IsNullOrWhiteSpace($hostRegex) -or [string]::IsNullOrWhiteSpace($requiredPath)) {
                throw "RELAY_WORKER_PROVIDER_CONTRACT_ADMISSION_PATTERN_INVALID"
            }
            try {
                $hostMatches = [regex]::IsMatch(
                    $baseUri.Host,
                    $hostRegex,
                    [Text.RegularExpressions.RegexOptions]::CultureInvariant
                )
            }
            catch {
                throw "RELAY_WORKER_PROVIDER_CONTRACT_HOST_REGEX_INVALID"
            }
            if ($hostMatches -and $pathNorm -ceq $requiredPath) {
                $isApprovedProductionProfile = $true
                break
            }
        }
    }
}
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

$profileRef = $resolvedProviderContract + "#" + $providerContractSha256

$sdkWire = Join-Path $PSScriptRoot "openai_sdk_wire.py"
if (-not (Test-Path -LiteralPath $sdkWire -PathType Leaf)) {
    throw "RELAY_WORKER_SDK_WIRE_MISSING: $sdkWire"
}
$cognitiveValidator = Join-Path $PSScriptRoot "validate_cognitive_audit_contract.py"
if ($cognitiveAudit -and -not (Test-Path -LiteralPath $cognitiveValidator -PathType Leaf)) {
    throw "RELAY_WORKER_COGNITIVE_VALIDATOR_MISSING"
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

if ($cognitiveAudit) {
    $schemaCheckOutput = @(
        & $PythonExe $cognitiveValidator `
            --context $resolvedContextManifest `
            --expected-context-sha256 $contextManifestSha256 `
            --schema $resolvedJsonSchema `
            --expected-schema-sha256 $jsonSchemaSha256 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "RELAY_WORKER_COGNITIVE_CONTRACT_PREFLIGHT_FAILED"
    }
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
    provider_contract_path = $resolvedProviderContract
    provider_contract_sha256 = $providerContractSha256
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
    prompt_sha256 = $promptSha256
    work_class = $WorkClass
    cognitive_audit_contract_active = [bool]$cognitiveAudit
    cannot_access_filesystem = $true
    tool_execution_allowed = $false
    input_mode = if ($cognitiveAudit) { "host_embedded_hash_bound" } else { "caller_prompt" }
    context_manifest_path = $resolvedContextManifest
    context_manifest_sha256 = $contextManifestSha256
    context_sha256 = $contextSha256
    json_schema_path = $resolvedJsonSchema
    json_schema_sha256 = $jsonSchemaSha256
    schema_instance_valid = $schemaInstanceValid
    evaluator_output_authority = "candidate_only"
    independent_validation_claim_allowed = $false
    repair_authorized = $false
    status = $status
    note_cn = "固定中性认知入口；provider 由哈希绑定的可替换合同注入，结果始终是候选。"
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
    # Exact identity remains separately observable. Any allowed alias is data
    # in the hash-bound provider contract, never a provider branch in core.
    $aliasPairs = @($providerContract.model_identity.accepted_alias_pairs)
    $aliasOk = $false
    foreach ($pair in $aliasPairs) {
        if (@($pair).Count -ne 2) {
            throw "RELAY_WORKER_PROVIDER_CONTRACT_MODEL_ALIAS_INVALID"
        }
        if (($Model -ceq [string]$pair[0] -and $observedModel -ceq [string]$pair[1]) -or
            ($Model -ceq [string]$pair[1] -and $observedModel -ceq [string]$pair[0])) {
            $aliasOk = $true
            break
        }
    }
    $selectedEqualsObserved = $observedModel -ceq $Model
    $prefixMatchAllowed = $providerContract.model_identity.allow_version_suffix_prefix_match -eq $true
    $prefixMatch = $prefixMatchAllowed -and (
        ($observedModel.StartsWith($Model + "-", [StringComparison]::Ordinal)) -or
        ($Model.StartsWith($observedModel + "-", [StringComparison]::Ordinal))
    )
    $modelIdentityAccepted = $aliasOk -or $selectedEqualsObserved -or $prefixMatch
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
    if ($cognitiveAudit) {
        $schemaValidationOutput = @(
            & $PythonExe $cognitiveValidator `
                --context $resolvedContextManifest `
                --expected-context-sha256 $contextManifestSha256 `
                --schema $resolvedJsonSchema `
                --expected-schema-sha256 $jsonSchemaSha256 `
                --result $resultPath 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            throw "RELAY_WORKER_JSON_SCHEMA_VALIDATION_FAILED"
        }
        $schemaInstanceValid = $true
    }
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
$meta.schema_instance_valid = $schemaInstanceValid
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
