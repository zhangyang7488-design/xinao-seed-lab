#Requires -Version 5.1
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$CliJsonPath,
    [Parameter(Mandatory = $true)]
    [string]$RequestedModel,
    [int]$ProcessExitCode = 0,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject
)

$ErrorActionPreference = "Stop"

function Get-TextSha256([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

$errors = [Collections.Generic.List[string]]::new()
$payload = $null
try {
    $payload = Get-Content -LiteralPath $CliJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
}
catch {
    $errors.Add("cli_json_invalid")
}

$text = if ($null -ne $payload) { [string]$payload.text } else { "" }
$sessionId = if ($null -ne $payload) { [string]$payload.sessionId } else { "" }
$stopReason = if ($null -ne $payload) { [string]$payload.stopReason } else { "" }
$usage = [ordered]@{
    input_tokens = 0
    cache_read_input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    total_tokens = 0
}
if ($null -ne $payload -and $null -ne $payload.usage) {
    foreach ($name in @($usage.Keys)) {
        $value = $payload.usage.$name
        if ($null -ne $value) { $usage[$name] = [int64]$value }
    }
}

$observedModels = @()
if ($null -ne $payload -and $null -ne $payload.modelUsage) {
    $observedModels = @(
        $payload.modelUsage.PSObject.Properties |
            Where-Object { $null -ne $_.Value -and [int64]$_.Value.modelCalls -gt 0 } |
            ForEach-Object { [string]$_.Name } |
            Sort-Object -Unique
    )
}
$usageIsIncomplete = ($null -ne $payload -and $payload.usage_is_incomplete -eq $true)
$usageAccountingComplete = (
    $null -ne $payload -and
    $null -ne $payload.usage -and
    -not $usageIsIncomplete
)

if ($ProcessExitCode -ne 0) { $errors.Add("process_exit_nonzero") }
if ($stopReason.ToLowerInvariant() -ne "endturn") { $errors.Add("stop_reason_not_endturn") }
if ([string]::IsNullOrWhiteSpace($sessionId)) { $errors.Add("session_id_missing") }
if ($observedModels.Count -ne 1 -or $observedModels[0] -ne $RequestedModel) {
    $errors.Add("model_identity_mismatch")
}
if ([int64]$usage.total_tokens -le 0) { $errors.Add("positive_token_usage_missing") }
if (-not $usageAccountingComplete) { $errors.Add("usage_accounting_incomplete") }
if ($text.Trim().Length -lt $MinResultChars) { $errors.Add("result_not_substantive") }
foreach ($marker in $RequiredResultMarkers) {
    if (-not [string]::IsNullOrWhiteSpace($marker) -and -not $text.Contains($marker)) {
        $errors.Add("required_marker_missing")
        break
    }
}
if ($RequireJsonObject) {
    try {
        $typed = $text | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $typed -or $typed -is [Array] -or $typed -is [string] -or $typed -is [ValueType]) {
            $errors.Add("result_json_not_object")
        }
    }
    catch {
        $errors.Add("result_json_invalid")
    }
}

$accepted = $errors.Count -eq 0
$result = [ordered]@{
    schema_version = "xinao.grok_cli_effective_output.v1"
    execution_contract_version = "xinao.grok.shared_execution_contract.v1"
    effective_output_accepted = $accepted
    requested_model = $RequestedModel
    observed_models = $observedModels
    model_identity_ok = ($observedModels.Count -eq 1 -and $observedModels[0] -eq $RequestedModel)
    stop_reason = $stopReason
    session_id_present = -not [string]::IsNullOrWhiteSpace($sessionId)
    usage = $usage
    usage_is_incomplete = $usageIsIncomplete
    usage_accounting_complete = $usageAccountingComplete
    result_text_chars = $text.Trim().Length
    result_text_sha256 = if ($text) { Get-TextSha256 $text } else { "" }
    min_result_chars = $MinResultChars
    required_result_markers = @($RequiredResultMarkers)
    require_json_object = [bool]$RequireJsonObject
    validation_errors = @($errors)
}
$result | ConvertTo-Json -Depth 8 -Compress
if ($accepted) { exit 0 }
exit 3
