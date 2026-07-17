#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$validator = Join-Path $PSScriptRoot "Test-GrokCliEffectiveOutput.ps1"
$root = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_cli_validator_tests" ([guid]::NewGuid().ToString("N"))
[void][IO.Directory]::CreateDirectory($root)
$utf8 = New-Object Text.UTF8Encoding $false

function Assert-True([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "GROK_EFFECTIVE_OUTPUT_TEST_FAILED: $Name" }
}

function New-SessionEvidence(
    [string]$Name,
    [string]$SessionId,
    [string]$RequestedModel,
    [string]$SessionModel = "",
    [string]$TurnModel = "",
    [string]$SessionCwd = "",
    [string]$SummarySessionId = "",
    [string]$SummaryGrokHome = "",
    [switch]$SkipSessionEvidence
) {
    $grokHome = Join-Path $root ($Name + "_grok_home")
    $sessionsRoot = Join-Path $grokHome "sessions"
    [void][IO.Directory]::CreateDirectory($sessionsRoot)
    $expectedCwd = $root
    if ($SkipSessionEvidence) {
        return [pscustomobject]@{ GrokHome = $grokHome; ExpectedCwd = $expectedCwd }
    }
    if (-not $SessionModel) { $SessionModel = $RequestedModel }
    if (-not $TurnModel) { $TurnModel = $RequestedModel }
    if (-not $SessionCwd) { $SessionCwd = $expectedCwd }
    if (-not $SummarySessionId) { $SummarySessionId = $SessionId }
    if (-not $SummaryGrokHome) { $SummaryGrokHome = $grokHome }
    $sessionDir = Join-Path (Join-Path $sessionsRoot "fixture") $SessionId
    [void][IO.Directory]::CreateDirectory($sessionDir)
    $summary = [ordered]@{
        info = [ordered]@{ id = $SummarySessionId; cwd = $SessionCwd }
        current_model_id = $SessionModel
        grok_home = $SummaryGrokHome
    }
    $event = [ordered]@{
        ts = "2026-07-18T00:00:00.000Z"
        type = "turn_started"
        session_id = $SessionId
        turn_number = 0
        model_id = $TurnModel
    }
    [IO.File]::WriteAllText(
        (Join-Path $sessionDir "summary.json"),
        ($summary | ConvertTo-Json -Depth 8 -Compress),
        $utf8
    )
    [IO.File]::WriteAllText(
        (Join-Path $sessionDir "events.jsonl"),
        (($event | ConvertTo-Json -Depth 8 -Compress) + [Environment]::NewLine),
        $utf8
    )
    return [pscustomobject]@{ GrokHome = $grokHome; ExpectedCwd = $expectedCwd }
}

function Invoke-Case(
    [string]$Name,
    [hashtable]$Payload,
    [bool]$Expected,
    [switch]$RequireJson,
    [string]$RequestedModel = "grok-composer-2.5-fast",
    [string]$SessionModel = "",
    [string]$TurnModel = "",
    [string]$SessionCwd = "",
    [string]$SummarySessionId = "",
    [string]$SummaryGrokHome = "",
    [switch]$SkipSessionEvidence
) {
    $casePayload = Copy-Payload $Payload
    $casePayload.sessionId = [guid]::NewGuid().ToString()
    $session = New-SessionEvidence `
        -Name $Name `
        -SessionId $casePayload.sessionId `
        -RequestedModel $RequestedModel `
        -SessionModel $SessionModel `
        -TurnModel $TurnModel `
        -SessionCwd $SessionCwd `
        -SummarySessionId $SummarySessionId `
        -SummaryGrokHome $SummaryGrokHome `
        -SkipSessionEvidence:$SkipSessionEvidence
    $path = Join-Path $root ($Name + ".json")
    [IO.File]::WriteAllText($path, ($casePayload | ConvertTo-Json -Depth 8 -Compress), $utf8)
    $args = @{
        CliJsonPath = $path
        RequestedModel = $RequestedModel
        GrokHome = $session.GrokHome
        ExpectedCwd = $session.ExpectedCwd
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
    return $result
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
    $payload.sessionId = [guid]::NewGuid().ToString()
    $session = New-SessionEvidence `
        -Name $Name `
        -SessionId $payload.sessionId `
        -RequestedModel "grok-composer-2.5-fast"
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
        GrokHome = $session.GrokHome
        ExpectedCwd = $session.ExpectedCwd
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
    sessionId = "00000000-0000-0000-0000-000000000000"
    usage = @{ total_tokens = 1000; input_tokens = 800; output_tokens = 200 }
    modelUsage = @{ "grok-composer-2.5-fast" = @{ modelCalls = 1 } }
}
$null = Invoke-Case "valid" $base $true
$case = Copy-Payload $base; $case.stopReason = "Cancelled"; $null = Invoke-Case "cancelled" $case $false
$case = Copy-Payload $base; $case.modelUsage = @{ "grok-4.5" = @{ modelCalls = 1 } }; $null = Invoke-Case "wrong_model" $case $false
$case = Copy-Payload $base; $case.usage = @{ total_tokens = 0 }; $null = Invoke-Case "zero_tokens" $case $false
$case = Copy-Payload $base; $case.text = "CANARY_MARKER"; $null = Invoke-Case "short" $case $false
$case = Copy-Payload $base; $case.text = $longText; $null = Invoke-Case "malformed_typed" $case $false -RequireJson
$case = Copy-Payload $base; $case.usage_is_incomplete = $true; $null = Invoke-Case "incomplete_usage" $case $false

$grok45 = Copy-Payload $base
$grok45.modelUsage = @{ "grok-4.5-build" = @{ modelCalls = 1 } }
$buildResult = Invoke-Case "grok45_backend_build" $grok45 $true -RequestedModel "grok-4.5"
Assert-True ($buildResult.session_model_identity_ok -eq $true) "grok45_backend_build:session_identity"
Assert-True ($buildResult.backend_model_identity_ok -eq $true) "grok45_backend_build:backend_identity"
Assert-True ([string]$buildResult.session_model -eq "grok-4.5") "grok45_backend_build:session_model"
Assert-True ([string]$buildResult.observed_backend_models[0] -eq "grok-4.5-build") "grok45_backend_build:backend_model"

$case = Copy-Payload $grok45; $case.modelUsage = @{ "grok-4.5-arbitrary" = @{ modelCalls = 1 } }
$null = Invoke-Case "grok45_arbitrary_suffix" $case $false -RequestedModel "grok-4.5"
$case = Copy-Payload $grok45; $case.modelUsage = @{ "grok-4.5" = @{ modelCalls = 1 }; "grok-4.5-build" = @{ modelCalls = 1 } }
$null = Invoke-Case "grok45_mixed_backend" $case $false -RequestedModel "grok-4.5"
$null = Invoke-Case "wrong_session_model" $base $false -SessionModel "grok-4.5"
$null = Invoke-Case "wrong_turn_model" $base $false -TurnModel "grok-4.5"
$null = Invoke-Case "missing_session_evidence" $base $false -SkipSessionEvidence
$null = Invoke-Case "wrong_session_cwd" $base $false -SessionCwd ([IO.Path]::GetTempPath())

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
    cases = 20
    evidence_root = $root
} | ConvertTo-Json -Depth 4
