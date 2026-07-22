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
    [int]$HttpStatus = 200,
    [hashtable]$ExtraWorkerArgs = @{}
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
        $workerArgs = @{
            Prompt = "Return RELAY_CONTRACT_OK"
            Model = $selectedModel
            ApiStyle = "chat_completions"
            BaseUrl = "http://127.0.0.1:$port/v1"
            KeyPath = $keyPath
            EvidenceDir = $evidence
            RunId = $CaseId
            MaxTokens = 32
            TimeoutSec = 15
            MinResultChars = 1
            RequiredResultMarkers = @("RELAY_CONTRACT_OK")
            WorkKey = "relay-test:" + $CaseId
            LogicalOperationId = "relay-op:" + $CaseId
            ProviderContractPath = $script:testProviderContractPath
            ExpectedProviderContractSha256 = $script:testProviderContractSha256
            AllowInsecureLoopbackForTest = $true
            Quiet = $true
        }
        foreach ($key in $ExtraWorkerArgs.Keys) { $workerArgs[$key] = $ExtraWorkerArgs[$key] }
        & $worker @workerArgs
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
            -ProviderContractPath $script:testProviderContractPath `
            -ExpectedProviderContractSha256 $script:testProviderContractSha256 `
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
$sdkWire = Join-Path $PSScriptRoot "openai_sdk_wire.py"
Assert-Relay (Test-Path -LiteralPath $sdkWire -PathType Leaf) "official SDK wire helper exists"
$workerSource = Get-Content -LiteralPath $worker -Raw -Encoding UTF8
Assert-Relay ($workerSource -notmatch '\bInvoke-WebRequest\b') "worker no longer hand-builds model HTTP"
$root = Join-Path ([IO.Path]::GetTempPath()) ("xinao-relay-worker-test-" + [guid]::NewGuid().ToString("N"))
[IO.Directory]::CreateDirectory($root) | Out-Null
$dummySecret = "sk-test-only-not-a-real-secret"
$keyPath = Join-Path $root "test-key.txt"
[IO.File]::WriteAllText($keyPath, $dummySecret, $utf8)
$script:testProviderContractPath = Join-Path $root "loopback-provider-binding.json"
$testProviderContract = [ordered]@{
    schema_version = "xinao.test_relay_adapter.v1"
    status = "test_only"
    module_role = "replaceable_provider_binding"
    core_entry = "Invoke-CodexDispatchOpenAiRelayWorker.ps1"
    provider_id = "loopback_openai_compatible_test"
    transport_id = "direct-openai-compatible-relay"
    completion_claim_allowed = $false
    admission = [ordered]@{
        exact_https_base_urls = @("https://api.ssstoken.net/v1")
        https_host_patterns = @()
    }
    model_identity = [ordered]@{
        allow_version_suffix_prefix_match = $true
        accepted_alias_pairs = @()
    }
    auth = [ordered]@{ mode = "key_file_handle"; default_key_path = $keyPath }
    defaults = [ordered]@{
        base_url = "https://api.ssstoken.net/v1"
        model = "gpt-5.6-sol"
        package_width = 1
        global_concurrency = "dynamic_external_supervisor_not_fixed_here"
    }
    recovery_metadata = [ordered]@{
        rate_limit_semantics = "test_failure_degrades_only_this_binding"
    }
    deletion_semantics = "removes_only_this_provider_binding_not_core_contract_owner_authority_or_other_adapters"
}
[IO.File]::WriteAllText(
    $script:testProviderContractPath,
    ($testProviderContract | ConvertTo-Json -Depth 8),
    $utf8
)
$script:testProviderContractSha256 = (Get-FileHash -LiteralPath $script:testProviderContractPath -Algorithm SHA256).Hash.ToLowerInvariant()

try {
    $success = Invoke-StubbedCase -Root $root -CaseId "success" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true
    Assert-Relay ($success.exit_code -eq 0) ("success exit: " + [string]$success.meta.error)
    Assert-Relay ($success.meta.status -eq "ok") "success status"
    Assert-Relay ($success.meta.selected_equals_observed -eq $true) "selected equals observed"
    Assert-Relay ($success.meta.model_identity_accepted -eq $true) "model identity accepted"
    Assert-Relay ($success.meta.model_invocation_observed -eq $true) "model invocation observed"
    Assert-Relay ($success.meta.provider_id -eq "loopback_openai_compatible_test") "provider identity bound"
    Assert-Relay ($success.meta.wire_client -eq "openai-python") "official SDK wire client"
    Assert-Relay ([int]$success.meta.sdk_max_retries -eq 0) "SDK retries disabled"
    Assert-Relay ([string]$success.meta.sdk_version -match '^2\.') "SDK version recorded"
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

    $unicodeEnvelope = Invoke-StubbedCase -Root $root -CaseId "unicode-envelope" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true -ResponseText "RELAY_CONTRACT_OK 🚀"
    Assert-Relay ($unicodeEnvelope.exit_code -eq 0) "SDK envelope survives narrow Windows stdout encoding"
    Assert-Relay ($unicodeEnvelope.meta.status -eq "ok") "unicode envelope status"

    $contextPath = Join-Path $root "cognitive-context.json"
    $contentHash = "7c79fdaafabb53992adaf9bef24e87a7a5d05cdc2f74ffae2578dc531131966c"
    $contextPayload = [ordered]@{
        schema_version = "xinao.context_slice_manifest.v1"
        authority = $false
        completion_claim_allowed = $false
        spec_sha256 = ("d" * 64)
        source_manifest_sha256 = "352dab0226f9f65a70e86831823ef47729a03ae84cff0e68d17ab6bba5e67e48"
        context_sha256 = "83571856b8134a9b0a80fcbee0a9744e1c56938cc5adc9114ae403ed3f08cb62"
        total_content_bytes = 11
        sources = @(
            [ordered]@{
                path = "src/example.py"
                source_sha256 = $contentHash
                source_bytes = 11
                slices = @(
                    [ordered]@{
                        kind = "line_range"
                        start = 1
                        end = 1
                        line_start = 1
                        line_end = 1
                        content_bytes = 11
                        content_sha256 = $contentHash
                        content = "safe = True"
                    }
                )
            }
        )
        false_green_deny = "input only"
    }
    [IO.File]::WriteAllText($contextPath, ($contextPayload | ConvertTo-Json -Depth 8), $utf8)
    $contextHash = (Get-FileHash -LiteralPath $contextPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $schemaPath = Join-Path $root "cognitive-output.schema.json"
    $schemaPayload = [ordered]@{
        '$schema' = "https://json-schema.org/draft/2020-12/schema"
        '$id' = "https://xinao.local/schemas/audit_candidate_findings.v1.schema.json"
        type = "object"
        additionalProperties = $false
        required = @("schema_version", "verdict", "summary", "findings", "limitations", "authority", "completion_claim_allowed", "repair_authorized")
        properties = [ordered]@{
            schema_version = [ordered]@{ const = "xinao.audit_candidate_findings.v1" }
            verdict = [ordered]@{ enum = @("ACCEPT_HOLD_CANDIDATE", "CANDIDATE_FINDINGS", "EVIDENCE_INCOMPLETE") }
            summary = [ordered]@{ type = "string" }
            findings = [ordered]@{ type = "array" }
            limitations = [ordered]@{ type = "array" }
            authority = [ordered]@{ const = $false }
            completion_claim_allowed = [ordered]@{ const = $false }
            repair_authorized = [ordered]@{ const = $false }
        }
    }
    [IO.File]::WriteAllText($schemaPath, ($schemaPayload | ConvertTo-Json -Depth 8), $utf8)
    $schemaHash = (Get-FileHash -LiteralPath $schemaPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $cognitiveArgs = @{
        WorkClass = "cognitive_audit"
        ContextManifestFile = $contextPath
        ExpectedContextManifestSha256 = $contextHash
        JsonSchemaPath = $schemaPath
        ExpectedJsonSchemaSha256 = $schemaHash
        RequiredResultMarkers = @("RELAY_CONTRACT_OK")
    }
    $validCandidate = '{"schema_version":"xinao.audit_candidate_findings.v1","verdict":"CANDIDATE_FINDINGS","summary":"RELAY_CONTRACT_OK candidate","findings":[{"finding_id":"F-1","family":"example","title":"candidate","claim":"candidate claim","severity_claim":"high","evidence_citations":[{"path":"src/example.py","source_sha256":"' + $contentHash + '","line_start":1,"line_end":1,"content_sha256":"' + $contentHash + '"}],"reproduction_conditions":["Owner reproduces locally"],"finding_kind":"CANDIDATE_FINDING"}],"limitations":[],"authority":false,"completion_claim_allowed":false,"repair_authorized":false}'
    $cognitive = Invoke-StubbedCase -Root $root -CaseId "cognitive-audit" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true -ResponseText $validCandidate -ExtraWorkerArgs $cognitiveArgs
    Assert-Relay ($cognitive.exit_code -eq 0) ("cognitive audit exit: " + [string]$cognitive.meta.error)
    Assert-Relay ($cognitive.meta.cognitive_audit_contract_active -eq $true) "cognitive contract active"
    Assert-Relay ($cognitive.meta.cannot_access_filesystem -eq $true) "cognitive no filesystem"
    Assert-Relay ($cognitive.meta.tool_execution_allowed -eq $false) "cognitive no tools"
    Assert-Relay ($cognitive.meta.schema_instance_valid -eq $true) "cognitive output schema valid"
    Assert-Relay ([string]$cognitive.meta.prompt_sha256 -match '^[0-9a-f]{64}$') "cognitive prompt hash"
    Assert-Relay ([string]$cognitive.meta.context_manifest_sha256 -eq $contextHash) "cognitive context hash"
    Assert-Relay ([string]$cognitive.meta.json_schema_sha256 -eq $schemaHash) "cognitive schema hash"

    $invalidCandidate = $validCandidate.Replace('"authority":false', '"authority":true').Replace('"repair_authorized":false', '"repair_authorized":true')
    $invalidCognitive = Invoke-StubbedCase -Root $root -CaseId "cognitive-invalid-output" -ObservedModel "gpt-5.6-sol" -IncludeUsage $true -ResponseText $invalidCandidate -ExtraWorkerArgs $cognitiveArgs
    Assert-Relay ($invalidCognitive.exit_code -ne 0) "invalid cognitive output rejected"
    Assert-Relay ([string]$invalidCognitive.meta.error -eq "RELAY_WORKER_JSON_SCHEMA_VALIDATION_FAILED") "invalid cognitive schema reason"

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
            -ProviderContractPath $script:testProviderContractPath `
            -ExpectedProviderContractSha256 $script:testProviderContractSha256 `
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
            -ProviderContractPath $script:testProviderContractPath `
            -ExpectedProviderContractSha256 $script:testProviderContractSha256 `
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
        & $worker -Prompt "x" -ProviderContractPath $script:testProviderContractPath -ExpectedProviderContractSha256 $script:testProviderContractSha256 -Model "gpt-5.6-sol" -BaseUrl "https://user@api.ssstoken.net/v1" -KeyPath $keyPath -EvidenceDir (Join-Path $root "userinfo") -RunId "userinfo" -WorkKey "relay-test:userinfo" -Quiet
    }
    catch { $userinfoRejected = $_.Exception.Message -match "RELAY_WORKER_BASE_URL_NOT_ADMITTED" }
    Assert-Relay $userinfoRejected "userinfo base url rejected"

    $portRejected = $false
    try {
        & $worker -Prompt "x" -ProviderContractPath $script:testProviderContractPath -ExpectedProviderContractSha256 $script:testProviderContractSha256 -Model "gpt-5.6-sol" -BaseUrl "https://api.ssstoken.net:444/v1" -KeyPath $keyPath -EvidenceDir (Join-Path $root "port") -RunId "port" -WorkKey "relay-test:port" -Quiet
    }
    catch { $portRejected = $_.Exception.Message -match "RELAY_WORKER_BASE_URL_NOT_ADMITTED" }
    Assert-Relay $portRejected "non-default production port rejected"

    [ordered]@{
        ok = $true
        cases = @("success", "unicode_envelope", "cognitive_audit", "cognitive_invalid_output", "observed_model_mismatch", "missing_usage", "truncated_terminal", "responses_completed", "responses_incomplete", "secret_reflection", "http_error_scrub", "duplicate_id", "unapproved_base_url", "userinfo_url", "nondefault_port")
        secret_material_recorded = $false
    } | ConvertTo-Json -Compress
}
finally {
    if ($root.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}
