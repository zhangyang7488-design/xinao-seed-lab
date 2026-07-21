#Requires -Version 7.0
<#
.SYNOPSIS
  Deterministic contract checks for the OpenAI-compatible A-leg peer.
#>

$ErrorActionPreference = "Stop"
$worker = Join-Path $PSScriptRoot "Invoke-OpenAiCompatibleRelayWorker.ps1"
$utf8 = [Text.UTF8Encoding]::new($false)

function Assert-Relay([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "OPENAI_RELAY_WORKER_TEST_FAILED: $Name" }
}

function Get-FreeTcpPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port }
    finally { $listener.Stop() }
}

function Start-OneShotRelayStub([int]$Port, [string]$ResponseJson, [int]$StatusCode = 200) {
    $job = Start-ThreadJob -ArgumentList $Port, $ResponseJson, $StatusCode -ScriptBlock {
        param([int]$ListenerPort, [string]$Payload, [int]$ResponseStatus)
        $listener = [Net.HttpListener]::new()
        $listener.Prefixes.Add("http://127.0.0.1:$ListenerPort/")
        try {
            $listener.Start()
            $context = $listener.GetContext()
            $reader = [IO.StreamReader]::new($context.Request.InputStream, $context.Request.ContentEncoding)
            try { [void]$reader.ReadToEnd() }
            finally { $reader.Dispose() }
            $bytes = [Text.Encoding]::UTF8.GetBytes($Payload)
            $context.Response.StatusCode = $ResponseStatus
            $context.Response.ContentType = "application/json"
            $context.Response.ContentLength64 = $bytes.Length
            $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
            $context.Response.OutputStream.Close()
        }
        finally {
            if ($listener.IsListening) { $listener.Stop() }
            $listener.Close()
        }
    }
    Start-Sleep -Milliseconds 200
    return $job
}

function Invoke-StubbedCase(
    [string]$Root,
    [string]$CaseId,
    [string]$ObservedModel,
    [bool]$IncludeUsage,
    [string]$FinishReason = "stop",
    [string]$ResponseText = "",
    [int]$HttpStatus = 200
) {
    $port = Get-FreeTcpPort
    $response = [ordered]@{
        id = "chatcmpl-$CaseId"
        object = "chat.completion"
        model = $ObservedModel
        choices = @(
            [ordered]@{
                index = 0
                message = [ordered]@{ role = "assistant"; content = $(if ($ResponseText) { $ResponseText } else { "RELAY_CONTRACT_OK $CaseId" }) }
                finish_reason = $FinishReason
            }
        )
    }
    if ($IncludeUsage) {
        $response.usage = [ordered]@{ prompt_tokens = 2; completion_tokens = 3; total_tokens = 5 }
    }
    $responseJson = $response | ConvertTo-Json -Depth 8 -Compress
    $job = Start-OneShotRelayStub -Port $port -ResponseJson $responseJson -StatusCode $HttpStatus
    $evidence = Join-Path $Root $CaseId
    $keyPath = Join-Path $Root "test-key.txt"
    $selectedModel = "gpt-5.6-sol"
    try {
        & $worker `
            -Prompt "Return RELAY_CONTRACT_OK" `
            -Model $selectedModel `
            -ApiStyle chat_completions `
            -BaseUrl "http://127.0.0.1:$port/v1" `
            -KeyPath $keyPath `
            -EvidenceDir $evidence `
            -RunId $CaseId `
            -MaxTokens 32 `
            -TimeoutSec 15 `
            -MinResultChars 1 `
            -RequiredResultMarkers RELAY_CONTRACT_OK `
            -WorkKey ("relay-test:" + $CaseId) `
            -LogicalOperationId ("relay-op:" + $CaseId) `
            -AllowInsecureLoopbackForTest `
            -Quiet
        $exitCode = $LASTEXITCODE
    }
    finally {
        Wait-Job -Job $job -Timeout 5 | Out-Null
        Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    $metaPath = Join-Path $evidence "$CaseId\meta.json"
    Assert-Relay (Test-Path -LiteralPath $metaPath -PathType Leaf) "$CaseId meta exists"
    $meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return [pscustomobject]@{ exit_code = $exitCode; meta = $meta; evidence = $evidence }
}

function Invoke-StubbedResponsesCase(
    [string]$Root,
    [string]$CaseId,
    [string]$ResponseStatus
) {
    $port = Get-FreeTcpPort
    $response = [ordered]@{
        id = "resp-$CaseId"
        object = "response"
        model = "gpt-5.6-sol"
        status = $ResponseStatus
        output_text = "RELAY_CONTRACT_OK $CaseId"
        usage = [ordered]@{ input_tokens = 2; output_tokens = 3; total_tokens = 5 }
    }
    if ($ResponseStatus -ne "completed") {
        $response.incomplete_details = [ordered]@{ reason = "max_output_tokens" }
    }
    $job = Start-OneShotRelayStub -Port $port -ResponseJson ($response | ConvertTo-Json -Depth 8 -Compress)
    $evidence = Join-Path $Root $CaseId
    $keyPath = Join-Path $Root "test-key.txt"
    try {
        & $worker `
            -Prompt "Return RELAY_CONTRACT_OK" `
            -Model "gpt-5.6-sol" `
            -ApiStyle responses `
            -BaseUrl "http://127.0.0.1:$port/v1" `
            -KeyPath $keyPath `
            -EvidenceDir $evidence `
            -RunId $CaseId `
            -WorkKey ("relay-test:" + $CaseId) `
            -LogicalOperationId ("relay-op:" + $CaseId) `
            -MaxTokens 32 `
            -TimeoutSec 15 `
            -MinResultChars 1 `
            -RequiredResultMarkers RELAY_CONTRACT_OK `
            -AllowInsecureLoopbackForTest `
            -Quiet
        $exitCode = $LASTEXITCODE
    }
    finally {
        Wait-Job -Job $job -Timeout 5 | Out-Null
        Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
    $meta = Get-Content -LiteralPath (Join-Path $evidence "$CaseId\meta.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    return [pscustomobject]@{ exit_code = $exitCode; meta = $meta }
}

Assert-Relay (Test-Path -LiteralPath $worker -PathType Leaf) "worker exists"
$root = Join-Path ([IO.Path]::GetTempPath()) ("xinao-relay-worker-test-" + [guid]::NewGuid().ToString("N"))
[IO.Directory]::CreateDirectory($root) | Out-Null
$dummySecret = "sk-test-only-not-a-real-secret"
$keyPath = Join-Path $root "test-key.txt"
[IO.File]::WriteAllText($keyPath, $dummySecret, $utf8)

try {
    $success = Invoke-StubbedCase -Root $root -CaseId "success" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true
    Assert-Relay ($success.exit_code -eq 0) ("success exit: " + [string]$success.meta.error)
    Assert-Relay ($success.meta.status -eq "ok") "success status"
    Assert-Relay ($success.meta.selected_equals_observed -eq $true) "selected equals observed"
    Assert-Relay ($success.meta.model_invocation_observed -eq $true) "model invocation observed"
    Assert-Relay ([int64]$success.meta.usage.total_tokens -eq 5) "positive usage"
    Assert-Relay ([string]$success.meta.result_sha256 -match '^[0-9a-f]{64}$') "result hash"
    Assert-Relay ([string]$success.meta.raw_response_sha256 -match '^[0-9a-f]{64}$') "raw response hash"
    Assert-Relay ($success.meta.terminal_state -eq "completed") "terminal completed"
    Assert-Relay ($success.meta.stop_reason -eq "stop") "terminal stop reason"
    Assert-Relay ($success.meta.work_key -eq "relay-test:success") "work key bound"
    Assert-Relay (-not ($success.meta.PSObject.Properties.Name -contains "key_fingerprint")) "no key fingerprint field"
    Assert-Relay (-not ($success.meta.PSObject.Properties.Name -contains "key_file_sha256")) "no key hash field"
    $recorded = Get-ChildItem -LiteralPath $success.evidence -File -Recurse | ForEach-Object {
        Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8
    }
    Assert-Relay (($recorded -join "`n") -notmatch [regex]::Escape($dummySecret)) "secret absent from evidence"

    $mismatch = Invoke-StubbedCase -Root $root -CaseId "mismatch" -ObservedModel "gpt-5.4" -IncludeUsage $true
    Assert-Relay ($mismatch.exit_code -ne 0) "mismatch exit"
    Assert-Relay ($mismatch.meta.status -eq "failed") "mismatch status"
    Assert-Relay ([string]$mismatch.meta.error -match "RELAY_WORKER_MODEL_IDENTITY_MISMATCH") "mismatch reason"

    $missingUsage = Invoke-StubbedCase -Root $root -CaseId "missing-usage" -ObservedModel "gpt-5.6-sol" -IncludeUsage $false
    Assert-Relay ($missingUsage.exit_code -ne 0) "missing usage exit"
    Assert-Relay ($missingUsage.meta.status -eq "failed") "missing usage status"
    Assert-Relay ([string]$missingUsage.meta.error -match "RELAY_WORKER_POSITIVE_USAGE_REQUIRED") "missing usage reason"

    $truncated = Invoke-StubbedCase -Root $root -CaseId "truncated" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true -FinishReason "length"
    Assert-Relay ($truncated.exit_code -ne 0) "truncated exit"
    Assert-Relay ($truncated.meta.status -eq "failed") "truncated status"
    Assert-Relay ([string]$truncated.meta.error -eq "RELAY_WORKER_CHAT_TERMINAL_NOT_ACCEPTED") "truncated reason"

    $responsesCompleted = Invoke-StubbedResponsesCase -Root $root -CaseId "responses-completed" -ResponseStatus "completed"
    Assert-Relay ($responsesCompleted.exit_code -eq 0) "responses completed exit"
    Assert-Relay ($responsesCompleted.meta.terminal_state -eq "completed") "responses completed terminal"

    $responsesIncomplete = Invoke-StubbedResponsesCase -Root $root -CaseId "responses-incomplete" -ResponseStatus "incomplete"
    Assert-Relay ($responsesIncomplete.exit_code -ne 0) "responses incomplete exit"
    Assert-Relay ([string]$responsesIncomplete.meta.error -eq "RELAY_WORKER_RESPONSES_TERMINAL_NOT_ACCEPTED") "responses incomplete reason"

    $reflected = Invoke-StubbedCase -Root $root -CaseId "secret-reflection" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true -ResponseText $dummySecret
    Assert-Relay ($reflected.exit_code -ne 0) "secret reflection exit"
    Assert-Relay ([string]$reflected.meta.error -eq "RELAY_WORKER_SECRET_REFLECTION_DETECTED") "secret reflection reason"
    $reflectedRecorded = Get-ChildItem -LiteralPath $reflected.evidence -File -Recurse | ForEach-Object {
        Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8
    }
    Assert-Relay (($reflectedRecorded -join "`n") -notmatch [regex]::Escape($dummySecret)) "reflected secret absent from evidence"

    $httpError = Invoke-StubbedCase -Root $root -CaseId "http-error" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true -ResponseText $dummySecret -HttpStatus 500
    Assert-Relay ($httpError.exit_code -ne 0) "http error exit"
    Assert-Relay ([string]$httpError.meta.error -match '^RELAY_WORKER_(HTTP_500|REQUEST_FAILED)$') "http error reduced to code"
    $httpRecorded = Get-ChildItem -LiteralPath $httpError.evidence -File -Recurse | ForEach-Object {
        Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8
    }
    Assert-Relay (($httpRecorded -join "`n") -notmatch [regex]::Escape($dummySecret)) "http error body absent from evidence"

    $duplicateConflict = $false
    try {
        & $worker `
            -Prompt "Return RELAY_CONTRACT_OK" `
            -Model "gpt-5.6-sol" `
            -ApiStyle chat_completions `
            -BaseUrl "http://127.0.0.1:1/v1" `
            -KeyPath $keyPath `
            -EvidenceDir $success.evidence `
            -RunId "success" `
            -WorkKey "relay-test:success" `
            -AllowInsecureLoopbackForTest `
            -Quiet
    }
    catch {
        $duplicateConflict = $_.Exception.Message -match "RELAY_WORKER_EVIDENCE_ID_CONFLICT"
    }
    Assert-Relay $duplicateConflict "duplicate run id rejected before request"

    $unapprovedBaseRejected = $false
    try {
        & $worker `
            -Prompt "Return RELAY_CONTRACT_OK" `
            -Model "gpt-5.6-sol" `
            -BaseUrl "https://example.invalid/v1" `
            -KeyPath $keyPath `
            -EvidenceDir (Join-Path $root "unapproved") `
            -RunId "unapproved" `
            -WorkKey "relay-test:unapproved" `
            -Quiet
    }
    catch {
        $unapprovedBaseRejected = $_.Exception.Message -match "RELAY_WORKER_BASE_URL_NOT_ADMITTED"
    }
    Assert-Relay $unapprovedBaseRejected "unapproved base url rejected before request"

    $userinfoRejected = $false
    try {
        & $worker -Prompt "x" -Model "gpt-5.6-sol" -BaseUrl "https://user@api.ssstoken.net/v1" -KeyPath $keyPath -EvidenceDir (Join-Path $root "userinfo") -RunId "userinfo" -WorkKey "relay-test:userinfo" -Quiet
    }
    catch { $userinfoRejected = $_.Exception.Message -match "RELAY_WORKER_BASE_URL_NOT_ADMITTED" }
    Assert-Relay $userinfoRejected "userinfo base url rejected"

    $portRejected = $false
    try {
        & $worker -Prompt "x" -Model "gpt-5.6-sol" -BaseUrl "https://api.ssstoken.net:444/v1" -KeyPath $keyPath -EvidenceDir (Join-Path $root "port") -RunId "port" -WorkKey "relay-test:port" -Quiet
    }
    catch { $portRejected = $_.Exception.Message -match "RELAY_WORKER_BASE_URL_NOT_ADMITTED" }
    Assert-Relay $portRejected "non-default production port rejected"

    [ordered]@{
        ok = $true
        cases = @("success", "observed_model_mismatch", "missing_usage", "truncated_terminal", "responses_completed", "responses_incomplete", "secret_reflection", "http_error_scrub", "duplicate_id", "unapproved_base_url", "userinfo_url", "nondefault_port")
        secret_material_recorded = $false
    } | ConvertTo-Json -Compress
}
finally {
    if ($root.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}
