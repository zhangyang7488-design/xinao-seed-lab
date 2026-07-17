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
