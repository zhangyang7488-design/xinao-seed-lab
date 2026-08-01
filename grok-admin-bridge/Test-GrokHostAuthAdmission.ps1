#Requires -Version 7.0

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) {
        throw "GROK_HOST_AUTH_ADMISSION_TEST_FAILED: $Name"
    }
}

$bridge = $PSScriptRoot
$worker = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_tests" (
    "host-auth-admission-" + [guid]::NewGuid().ToString("N")
)
$profileRoot = Join-Path $testRoot "profile"
$candidateRoot = Join-Path $testRoot "candidate"
$evidenceRoot = Join-Path $testRoot "evidence"
$fakeGrok = Join-Path $testRoot "fake-grok.cmd"
$providerMarker = Join-Path $testRoot "provider-invoked.txt"

New-Item -ItemType Directory -Path $profileRoot, $candidateRoot, $evidenceRoot -Force | Out-Null
[IO.File]::WriteAllText(
    $fakeGrok,
    "@echo off`r`n>>`"%XINAO_FAKE_GROK_PROVIDER_MARKER%`" echo invoked`r`nexit /b 99`r`n",
    [Text.ASCIIEncoding]::new()
)

$priorMarker = $env:XINAO_FAKE_GROK_PROVIDER_MARKER
$observedError = ""
try {
    $env:XINAO_FAKE_GROK_PROVIDER_MARKER = $providerMarker
    try {
        & $worker `
            -Prompt "This request must be rejected before provider contact." `
            -Cwd $candidateRoot `
            -GrokHome $profileRoot `
            -GrokExe $fakeGrok `
            -EvidenceDir $evidenceRoot `
            -Model "grok-4.5" `
            -MaxTurns 1 `
            -TimeoutSec 60 `
            -MinResultChars 1 `
            -ExecutionBackend "windows-host" `
            -Quiet | Out-Null
        throw "GROK_HOST_AUTH_ADMISSION_TEST_EXPECTED_REJECTION"
    }
    catch {
        $observedError = [string]$_.Exception.Message
    }

    Assert-Contract ($observedError -eq "GROK_AUTHENTICATED_PROFILE_AUTH_REQUIRED") "exact_auth_required_error"
    Assert-Contract (-not (Test-Path -LiteralPath $providerMarker -PathType Leaf)) "provider_not_contacted"
    Assert-Contract (@(Get-ChildItem -LiteralPath $evidenceRoot -Filter "*.cli.json" -File -ErrorAction SilentlyContinue).Count -eq 0) "no_cli_result"

    [ordered]@{
        status = "verified"
        execution_backend = "windows-host"
        auth_present = $false
        observed_error = $observedError
        provider_contacted = $false
        model_invocation_count = 0
        total_model_tokens = 0
    } | ConvertTo-Json -Depth 5
}
finally {
    if ($null -eq $priorMarker) {
        Remove-Item Env:XINAO_FAKE_GROK_PROVIDER_MARKER -ErrorAction SilentlyContinue
    }
    else {
        $env:XINAO_FAKE_GROK_PROVIDER_MARKER = $priorMarker
    }
    if (Test-Path -LiteralPath $testRoot -PathType Container) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
