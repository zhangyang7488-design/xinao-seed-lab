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

[ordered]@{
    schema_version = "xinao.grok_cli_effective_output.tests.v1"
    ok = $true
    cases = 7
    evidence_root = $root
} | ConvertTo-Json -Depth 4
