#Requires -Version 5.1
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [string]$CliJsonPath,
    [Parameter(Mandatory = $true)]
    [string]$RequestedModel,
    [Parameter(Mandatory = $true)]
    [string]$GrokHome,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedCwd,
    [int]$ProcessExitCode = 0,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [string]$ExpectedJsonSchemaSha256 = "",
    [string]$JsonSchemaValidator = "",
    [string]$JsonSchemaPythonExe = ""
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

function Get-FileSha256Lower([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-NormalizedPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    try {
        $full = [IO.Path]::GetFullPath($Value).Replace('/', '\')
        $root = [IO.Path]::GetPathRoot($full)
        while ($full.Length -gt $root.Length -and $full.EndsWith('\')) {
            $full = $full.Substring(0, $full.Length - 1)
        }
        return $full
    }
    catch {
        return ""
    }
}

function Test-OrdinalEquals([string]$Left, [string]$Right) {
    return [string]::Equals($Left, $Right, [StringComparison]::Ordinal)
}

function Test-OrdinalIgnoreCaseEquals([string]$Left, [string]$Right) {
    return [string]::Equals($Left, $Right, [StringComparison]::OrdinalIgnoreCase)
}

$errors = [Collections.Generic.List[string]]::new()
$payload = $null
try {
    $payload = Get-Content -LiteralPath $CliJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
}
catch {
    $errors.Add("cli_json_invalid")
}

$jsonSchemaRequested = -not [string]::IsNullOrWhiteSpace($JsonSchemaPath)
$cliText = if ($null -ne $payload) { [string]$payload.text } else { "" }
$structuredOutput = if ($null -ne $payload) { $payload.structuredOutput } else { $null }
$structuredOutputPresent = $null -ne $structuredOutput
$effectiveOutputSource = if ($jsonSchemaRequested) { "structuredOutput" } else { "text" }
$text = $cliText
if ($jsonSchemaRequested) {
    if (-not $structuredOutputPresent) {
        $text = ""
        $errors.Add("structured_output_missing")
    }
    elseif (
        $structuredOutput -is [Array] -or
        $structuredOutput -is [string] -or
        $structuredOutput -is [ValueType]
    ) {
        $text = ""
        $errors.Add("structured_output_not_object")
    }
    else {
        try {
            # Grok CLI aggregates schema-constrained intermediate turns in
            # `text`; the one provider-native final value is `structuredOutput`.
            $text = $structuredOutput | ConvertTo-Json -Depth 100 -Compress
        }
        catch {
            $text = ""
            $errors.Add("structured_output_serialization_failed")
        }
    }
}
$sessionId = if ($null -ne $payload) { [string]$payload.sessionId } else { "" }
$stopReason = if ($null -ne $payload) { [string]$payload.stopReason } else { "" }
$resolvedJsonSchemaPath = ""
$jsonSchemaCompact = ""
$jsonSchemaObservedSha256 = ""
$schemaInstanceValid = $null
$jsonSchemaValidatorOperational = -not $jsonSchemaRequested
$jsonSchemaValidationError = ""
$jsonSchemaInstancePath = ""
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
$observedBackendModels = @($observedModels)
$allowedBackendModels = @($RequestedModel)
# Grok Build exposes the public/session model as `grok-4.5`, while a tool-heavy
# session can account calls against both that public identity and the explicit
# Build backend below. Keep this closed set model-specific; never normalize
# arbitrary suffixes or treat backend usage identity as the session selector.
if (Test-OrdinalEquals $RequestedModel "grok-4.5") {
    $allowedBackendModels += "grok-4.5-build"
}
$backendModelIdentityOk = $observedBackendModels.Count -gt 0
foreach ($observedBackendModel in $observedBackendModels) {
    $observedBackendAllowed = $false
    foreach ($allowedBackendModel in $allowedBackendModels) {
        if (Test-OrdinalEquals $observedBackendModel $allowedBackendModel) {
            $observedBackendAllowed = $true
            break
        }
    }
    if (-not $observedBackendAllowed) {
        $backendModelIdentityOk = $false
        break
    }
}

$resolvedGrokHome = Get-NormalizedPath $GrokHome
$resolvedExpectedCwd = Get-NormalizedPath $ExpectedCwd
$sessionEvidenceRoot = if ($resolvedGrokHome) { Join-Path $resolvedGrokHome "sessions" } else { "" }
$sessionEvidenceDir = ""
$sessionSummaryPath = ""
$sessionEventsPath = ""
$sessionSummarySha256 = ""
$sessionEventsSha256 = ""
$sessionModel = ""
$observedSessionModels = @()
$sessionIdBindingOk = $false
$sessionCwdBindingOk = $false
$sessionHomeBindingOk = $false
$sessionModelIdentityOk = $false
$sessionTurnModelIdentityOk = $false
$sessionEvidenceFound = $false

$sessionIdShapeOk = $sessionId -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
if (-not $sessionIdShapeOk) {
    $errors.Add("session_id_invalid")
}
elseif (-not $resolvedGrokHome -or -not (Test-Path -LiteralPath $resolvedGrokHome -PathType Container)) {
    $errors.Add("grok_home_invalid")
}
elseif (-not $resolvedExpectedCwd -or -not (Test-Path -LiteralPath $resolvedExpectedCwd -PathType Container)) {
    $errors.Add("expected_cwd_invalid")
}
elseif (-not (Test-Path -LiteralPath $sessionEvidenceRoot -PathType Container)) {
    $errors.Add("session_evidence_root_missing")
}
else {
    $sessionMatches = @(
        Get-ChildItem -LiteralPath $sessionEvidenceRoot -Recurse -Directory -Filter $sessionId -ErrorAction SilentlyContinue |
            Where-Object { Test-OrdinalEquals $_.Name $sessionId }
    )
    if ($sessionMatches.Count -ne 1) {
        $sessionMatchError = if ($sessionMatches.Count -eq 0) {
            "session_evidence_missing"
        }
        else {
            "session_evidence_ambiguous"
        }
        $errors.Add($sessionMatchError)
    }
    else {
        $sessionEvidenceFound = $true
        $sessionEvidenceDir = $sessionMatches[0].FullName
        $sessionSummaryPath = Join-Path $sessionEvidenceDir "summary.json"
        $sessionEventsPath = Join-Path $sessionEvidenceDir "events.jsonl"
        if (
            -not (Test-Path -LiteralPath $sessionSummaryPath -PathType Leaf) -or
            -not (Test-Path -LiteralPath $sessionEventsPath -PathType Leaf)
        ) {
            $errors.Add("session_evidence_incomplete")
        }
        else {
            try {
                $sessionSummary = Get-Content -LiteralPath $sessionSummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
                $sessionSummarySha256 = Get-FileSha256Lower $sessionSummaryPath
                $summarySessionId = [string]$sessionSummary.info.id
                $summaryCwd = Get-NormalizedPath ([string]$sessionSummary.info.cwd)
                $summaryGrokHome = Get-NormalizedPath ([string]$sessionSummary.grok_home)
                $sessionModel = [string]$sessionSummary.current_model_id
                $sessionIdBindingOk = Test-OrdinalEquals $summarySessionId $sessionId
                $sessionCwdBindingOk = Test-OrdinalIgnoreCaseEquals $summaryCwd $resolvedExpectedCwd
                $sessionHomeBindingOk = Test-OrdinalIgnoreCaseEquals $summaryGrokHome $resolvedGrokHome
                $sessionModelIdentityOk = Test-OrdinalEquals $sessionModel $RequestedModel
                if (-not $sessionIdBindingOk) { $errors.Add("session_summary_id_mismatch") }
                if (-not $sessionCwdBindingOk) { $errors.Add("session_summary_cwd_mismatch") }
                if (-not $sessionHomeBindingOk) { $errors.Add("session_summary_grok_home_mismatch") }
                if (-not $sessionModelIdentityOk) { $errors.Add("session_model_identity_mismatch") }
            }
            catch {
                $errors.Add("session_summary_invalid")
            }

            try {
                $eventModels = [Collections.Generic.List[string]]::new()
                foreach ($eventLine in Get-Content -LiteralPath $sessionEventsPath -Encoding UTF8) {
                    if ([string]::IsNullOrWhiteSpace($eventLine)) { continue }
                    $event = $eventLine | ConvertFrom-Json -ErrorAction Stop
                    if (
                        [string]$event.type -eq "turn_started" -and
                        (Test-OrdinalEquals ([string]$event.session_id) $sessionId)
                    ) {
                        $eventModels.Add([string]$event.model_id)
                    }
                }
                $sessionEventsSha256 = Get-FileSha256Lower $sessionEventsPath
                $observedSessionModels = @($eventModels | Sort-Object -Unique)
                $sessionTurnModelIdentityOk = (
                    $observedSessionModels.Count -eq 1 -and
                    (Test-OrdinalEquals $observedSessionModels[0] $RequestedModel)
                )
                if (-not $sessionTurnModelIdentityOk) {
                    $errors.Add("session_turn_model_identity_mismatch")
                }
            }
            catch {
                $errors.Add("session_events_invalid")
            }
        }
    }
}

$sessionEvidenceOk = (
    $sessionEvidenceFound -and
    $sessionIdBindingOk -and
    $sessionCwdBindingOk -and
    $sessionHomeBindingOk -and
    $sessionModelIdentityOk -and
    $sessionTurnModelIdentityOk
)
$modelIdentityOk = $sessionEvidenceOk -and $backendModelIdentityOk
$usageIsIncomplete = ($null -ne $payload -and $payload.usage_is_incomplete -eq $true)
$usageAccountingComplete = (
    $null -ne $payload -and
    $null -ne $payload.usage -and
    -not $usageIsIncomplete
)

if ($ProcessExitCode -ne 0) { $errors.Add("process_exit_nonzero") }
if ($stopReason.ToLowerInvariant() -ne "endturn") { $errors.Add("stop_reason_not_endturn") }
if ([string]::IsNullOrWhiteSpace($sessionId)) { $errors.Add("session_id_missing") }
if (-not $backendModelIdentityOk) {
    $errors.Add("backend_model_identity_mismatch")
}
if (-not $modelIdentityOk) {
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
if ($jsonSchemaRequested) {
    try {
        $resolvedJsonSchemaPath = [IO.Path]::GetFullPath($JsonSchemaPath)
        if (-not (Test-Path -LiteralPath $resolvedJsonSchemaPath -PathType Leaf)) {
            throw "json_schema_snapshot_missing"
        }
        $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $jsonSchemaBytes = [IO.File]::ReadAllBytes($resolvedJsonSchemaPath)
        $schemaHasher = [Security.Cryptography.SHA256]::Create()
        try {
            $schemaHashText = [BitConverter]::ToString($schemaHasher.ComputeHash($jsonSchemaBytes))
            $jsonSchemaObservedSha256 = ($schemaHashText -replace "-", "").ToLowerInvariant()
        }
        finally {
            $schemaHasher.Dispose()
        }
        if (
            [string]::IsNullOrWhiteSpace($ExpectedJsonSchemaSha256) -or
            $jsonSchemaObservedSha256 -ne $ExpectedJsonSchemaSha256.ToLowerInvariant()
        ) {
            throw "json_schema_snapshot_hash_mismatch"
        }
        $jsonSchemaCompact = $strictUtf8.GetString($jsonSchemaBytes)
        $null = $jsonSchemaCompact | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        $jsonSchemaValidationError = if ($_.Exception.Message -eq "json_schema_snapshot_hash_mismatch") {
            "json_schema_snapshot_hash_mismatch"
        } else {
            "json_schema_snapshot_invalid"
        }
        $errors.Add($jsonSchemaValidationError)
    }

    if ($jsonSchemaCompact) {
        switch ($JsonSchemaValidator) {
            "powershell_test_json_schema" {
                $testJson = Get-Command Test-Json -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($null -eq $testJson -or -not $testJson.Parameters.ContainsKey("Schema")) {
                    $jsonSchemaValidationError = "json_schema_validator_unavailable"
                    $errors.Add($jsonSchemaValidationError)
                    break
                }
                $jsonSchemaValidatorOperational = $true
                try {
                    $schemaInstanceValid = [bool](Test-Json -Json $text -Schema $jsonSchemaCompact -ErrorAction Stop)
                }
                catch {
                    $schemaInstanceValid = $false
                }
            }
            "python_jsonschema" {
                if (-not $JsonSchemaPythonExe -or -not (Test-Path -LiteralPath $JsonSchemaPythonExe -PathType Leaf)) {
                    $jsonSchemaValidationError = "json_schema_validator_unavailable"
                    $errors.Add($jsonSchemaValidationError)
                    break
                }
                $pythonProgram = @'
import hashlib
import json
import sys
from pathlib import Path

import jsonschema

schema_bytes = Path(sys.argv[1]).read_bytes()
if hashlib.sha256(schema_bytes).hexdigest() != sys.argv[3]:
    raise RuntimeError("schema snapshot hash mismatch")
schema = json.loads(schema_bytes.decode("utf-8"))
instance = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
validator_class = jsonschema.validators.validator_for(schema)
validator_class.check_schema(schema)
validator_class(schema).validate(instance)
'@
                try {
                    $jsonSchemaInstancePath = $CliJsonPath + ".effective-instance.json"
                    [IO.File]::WriteAllText($jsonSchemaInstancePath, $text, [Text.UTF8Encoding]::new($false))
                    $pythonOutput = @(& $JsonSchemaPythonExe -c $pythonProgram $resolvedJsonSchemaPath $jsonSchemaInstancePath $ExpectedJsonSchemaSha256 2>&1)
                    $schemaInstanceValid = ($LASTEXITCODE -eq 0)
                    $jsonSchemaValidatorOperational = $true
                }
                catch {
                    $schemaInstanceValid = $false
                    $jsonSchemaValidationError = "json_schema_validator_execution_failed"
                    $errors.Add($jsonSchemaValidationError)
                }
            }
            default {
                $jsonSchemaValidationError = "json_schema_validator_unavailable"
                $errors.Add($jsonSchemaValidationError)
            }
        }
        if ($schemaInstanceValid -ne $true) {
            $errors.Add("result_json_schema_mismatch")
            if (-not $jsonSchemaValidationError) {
                $jsonSchemaValidationError = "result_json_schema_mismatch"
            }
        }
    }
}

$accepted = $errors.Count -eq 0
$result = [ordered]@{
    schema_version = "xinao.grok_cli_effective_output.v2"
    execution_contract_version = "xinao.grok.shared_execution_contract.v1"
    effective_output_accepted = $accepted
    requested_model = $RequestedModel
    observed_models = $observedModels
    observed_backend_models = $observedBackendModels
    allowed_backend_models = $allowedBackendModels
    observed_session_models = $observedSessionModels
    session_model = $sessionModel
    backend_model_identity_ok = $backendModelIdentityOk
    session_model_identity_ok = $sessionModelIdentityOk
    session_turn_model_identity_ok = $sessionTurnModelIdentityOk
    session_evidence_ok = $sessionEvidenceOk
    model_identity_ok = $modelIdentityOk
    model_identity_binding = "exact_session_model_plus_explicit_backend_usage_binding"
    grok_home = $resolvedGrokHome
    expected_cwd = $resolvedExpectedCwd
    session_evidence_root = $sessionEvidenceRoot
    session_evidence_dir = $sessionEvidenceDir
    session_summary_path = $sessionSummaryPath
    session_summary_sha256 = $sessionSummarySha256
    session_events_path = $sessionEventsPath
    session_events_sha256 = $sessionEventsSha256
    stop_reason = $stopReason
    session_id_present = -not [string]::IsNullOrWhiteSpace($sessionId)
    usage = $usage
    usage_is_incomplete = $usageIsIncomplete
    usage_accounting_complete = $usageAccountingComplete
    result_text_chars = $text.Trim().Length
    result_text_sha256 = if ($text) { Get-TextSha256 $text } else { "" }
    cli_text_chars = $cliText.Trim().Length
    effective_output_source = $effectiveOutputSource
    structured_output_present = $structuredOutputPresent
    min_result_chars = $MinResultChars
    required_result_markers = @($RequiredResultMarkers)
    require_json_object = [bool]$RequireJsonObject
    json_schema_requested = $jsonSchemaRequested
    json_schema_path = $resolvedJsonSchemaPath
    json_schema_snapshot_path = $resolvedJsonSchemaPath
    json_schema_sha256 = $jsonSchemaObservedSha256
    json_schema_expected_sha256 = $ExpectedJsonSchemaSha256
    json_schema_observed_sha256 = $jsonSchemaObservedSha256
    json_schema_validator = $JsonSchemaValidator
    json_schema_validator_operational = $jsonSchemaValidatorOperational
    schema_instance_valid = if ($jsonSchemaRequested) { [bool]$schemaInstanceValid } else { $null }
    json_schema_instance_path = $jsonSchemaInstancePath
    json_schema_validation_error = $jsonSchemaValidationError
    validation_errors = @($errors)
}
$result | ConvertTo-Json -Depth 8 -Compress
if ($accepted) { exit 0 }
exit 3
