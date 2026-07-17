#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$validator = Join-Path $PSScriptRoot "Test-GrokCliEffectiveOutput.ps1"
$root = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_cli_validator_tests" ([guid]::NewGuid().ToString("N"))
[void][IO.Directory]::CreateDirectory($root)
$utf8 = New-Object Text.UTF8Encoding $false

function Assert-True([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "GROK_EFFECTIVE_OUTPUT_TEST_FAILED: $Name" }
}

function Invoke-Case([string]$Name, [hashtable]$Payload, [bool]$Expected, [switch]$RequireJson) {
    $path = Join-Path $root ($Name + ".json")
    [IO.File]::WriteAllText($path, ($Payload | ConvertTo-Json -Depth 8 -Compress), $utf8)
    $args = @{
        CliJsonPath = $path
        RequestedModel = "grok-composer-2.5-fast"
        ProcessExitCode = 0
        MinResultChars = 256
        RequiredResultMarkers = @("CANARY_MARKER")
    }
    if ($RequireJson) { $args.RequireJsonObject = $true }
    $raw = [string](& $validator @args)
    $code = $LASTEXITCODE
    $result = $raw | ConvertFrom-Json
    Assert-True (($result.effective_output_accepted -eq $true) -eq $Expected) ($Name + ":accepted")
    Assert-True (($code -eq 0) -eq $Expected) ($Name + ":exit")
}

function Copy-Payload([hashtable]$Source) {
    $copy = @{}
    foreach ($key in $Source.Keys) { $copy[$key] = $Source[$key] }
    return $copy
}

function Invoke-SchemaCase(
    [string]$Name,
    [string]$Text,
    [bool]$Expected,
    [string]$ValidatorIdentity,
    [string]$SchemaPath,
    [string]$PythonExe = "",
    [string]$ExpectedSchemaSha256 = "",
    [switch]$OmitStructuredOutput
) {
    $payload = Copy-Payload $base
    # Real multi-turn Grok CLI output concatenates schema-shaped intermediate
    # turns in `text` and exposes the single final object in `structuredOutput`.
    $payload.text = '{"intermediate":"one"}{"intermediate":"two"}'
    if (-not $OmitStructuredOutput) {
        $payload.structuredOutput = $Text | ConvertFrom-Json -ErrorAction Stop
    }
    $path = Join-Path $root ($Name + ".json")
    [IO.File]::WriteAllText($path, ($payload | ConvertTo-Json -Depth 8 -Compress), $utf8)
    $args = @{
        CliJsonPath = $path
        RequestedModel = "grok-composer-2.5-fast"
        ProcessExitCode = 0
        MinResultChars = 1
        RequiredResultMarkers = @()
        RequireJsonObject = $true
        JsonSchemaPath = $SchemaPath
        ExpectedJsonSchemaSha256 = if ($ExpectedSchemaSha256) {
            $ExpectedSchemaSha256
        } else {
            (Get-FileHash -LiteralPath $SchemaPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        JsonSchemaValidator = $ValidatorIdentity
    }
    if ($PythonExe) { $args.JsonSchemaPythonExe = $PythonExe }
    $raw = [string](& $validator @args)
    $code = $LASTEXITCODE
    $result = $raw | ConvertFrom-Json
    Assert-True (($result.effective_output_accepted -eq $true) -eq $Expected) ($Name + ":accepted")
    Assert-True (($result.schema_instance_valid -eq $true) -eq $Expected) ($Name + ":schema_instance_valid")
    Assert-True ([string]$result.json_schema_validator -eq $ValidatorIdentity) ($Name + ":validator_identity")
    Assert-True ([string]$result.effective_output_source -eq "structuredOutput") ($Name + ":output_source")
    Assert-True ([string]$result.json_schema_sha256 -match '^[0-9a-f]{64}$') ($Name + ":schema_sha256")
    Assert-True (
        (([string]$result.json_schema_expected_sha256 -eq [string]$result.json_schema_observed_sha256) -eq (-not $ExpectedSchemaSha256))
    ) ($Name + ":schema_hash_binding")
    Assert-True (($code -eq 0) -eq $Expected) ($Name + ":exit")
}

$longText = ("X" * 300) + " CANARY_MARKER"
$base = @{
    text = $longText
    stopReason = "EndTurn"
    sessionId = "session-valid"
    usage = @{ total_tokens = 1000; input_tokens = 800; output_tokens = 200 }
    modelUsage = @{ "grok-composer-2.5-fast" = @{ modelCalls = 1 } }
}
Invoke-Case "valid" $base $true
$case = Copy-Payload $base; $case.stopReason = "Cancelled"; Invoke-Case "cancelled" $case $false
$case = Copy-Payload $base; $case.modelUsage = @{ "grok-4.5" = @{ modelCalls = 1 } }; Invoke-Case "wrong_model" $case $false
$case = Copy-Payload $base; $case.usage = @{ total_tokens = 0 }; Invoke-Case "zero_tokens" $case $false
$case = Copy-Payload $base; $case.text = "CANARY_MARKER"; Invoke-Case "short" $case $false
$case = Copy-Payload $base; $case.text = $longText; Invoke-Case "malformed_typed" $case $false -RequireJson
$case = Copy-Payload $base; $case.usage_is_incomplete = $true; Invoke-Case "incomplete_usage" $case $false

$schemaPath = Join-Path $root "result.schema.json"
$schema = [ordered]@{
    type = "object"
    required = @("answer")
    additionalProperties = $false
    properties = [ordered]@{
        answer = [ordered]@{ type = "string"; const = "SCHEMA_OK" }
    }
}
[IO.File]::WriteAllText($schemaPath, ($schema | ConvertTo-Json -Depth 8 -Compress), $utf8)
$testJson = Get-Command Test-Json -ErrorAction SilentlyContinue | Select-Object -First 1
Assert-True ($null -ne $testJson -and $testJson.Parameters.ContainsKey("Schema")) "native_schema_validator_available"
Invoke-SchemaCase "schema_native_valid" '{"answer":"SCHEMA_OK"}' $true "powershell_test_json_schema" $schemaPath
Invoke-SchemaCase "schema_native_invalid" '{"answer":"WRONG"}' $false "powershell_test_json_schema" $schemaPath
Invoke-SchemaCase "schema_hash_mismatch" '{"answer":"SCHEMA_OK"}' $false "powershell_test_json_schema" $schemaPath "" ("0" * 64)
Invoke-SchemaCase "schema_structured_output_missing" '{"answer":"SCHEMA_OK"}' $false "powershell_test_json_schema" $schemaPath "" "" -OmitStructuredOutput

$python = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 }
Assert-True ($null -ne $python) "python_schema_validator_available"
$pythonVersion = @(& $python.Source -c "import importlib.metadata; print(importlib.metadata.version('jsonschema'))" 2>&1)
Assert-True ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($pythonVersion -join ""))) "python_jsonschema_available"
Invoke-SchemaCase "schema_python_valid" '{"answer":"SCHEMA_OK"}' $true "python_jsonschema" $schemaPath $python.Source
Invoke-SchemaCase "schema_python_invalid" '{"answer":"WRONG"}' $false "python_jsonschema" $schemaPath $python.Source

[ordered]@{
    schema_version = "xinao.grok_cli_effective_output.tests.v1"
    ok = $true
    cases = 13
    evidence_root = $root
} | ConvertTo-Json -Depth 4
