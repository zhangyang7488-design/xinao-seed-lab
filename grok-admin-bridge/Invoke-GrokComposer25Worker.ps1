#Requires -Version 5.1
<#
.SYNOPSIS
  Headless Grok provider worker; Composer 2.5 remains the caller default.
.DESCRIPTION
  Thin entry for a Grok main session. The explicitly requested model is admitted
  only when the current authenticated provider catalog exposes that exact model,
  then the CLI result is checked against the same requested identity.
.EXAMPLE
  .\Invoke-GrokComposer25Worker.ps1 -Prompt "Reply COMPOSER25_OK" -MaxTurns 1
  .\Invoke-GrokComposer25Worker.ps1 -PromptFile .\task.md -Cwd E:\repo -Background
#>
param(
    [string]$Prompt = "",
    [string]$PromptFile = "",
    [string]$Cwd = "",
    [string]$Model = "grok-composer-2.5-fast",
    [string]$MaxTurns = "auto",
    [ValidateSet("plain", "json", "streaming-json")]
    [string]$OutputFormat = "json",
    [string]$GrokHome = "C:\Users\xx363\.grok-bg-workers",
    [string]$GrokExe = "",
    [string]$EvidenceDir = "D:\XINAO_RESEARCH_RUNTIME\state\composer25_worker",
    [ValidateRange(1, 86400)]
    [int]$TimeoutSec = 600,
    [ValidateRange(1, 200000)]
    [int]$MinResultChars = 256,
    [string[]]$RequiredResultMarkers = @(),
    [switch]$RequireJsonObject,
    [string]$JsonSchemaPath = "",
    [switch]$Background,
    [switch]$NoAlwaysApprove,
    [switch]$Quiet,
    [string]$InternalRunId = "",
    [string]$BackgroundInvocationPath = "",
    [string]$BackgroundInvocationSha256 = "",
    [switch]$DetachedDrain
)

$ErrorActionPreference = "Stop"

$processRuntime = Join-Path $PSScriptRoot "GrokWorkerProcessRuntime.ps1"
if (-not (Test-Path -LiteralPath $processRuntime -PathType Leaf)) {
    throw "GROK_PROCESS_RUNTIME_MISSING: $processRuntime"
}
. $processRuntime

$catalogTimeRuntime = Join-Path $PSScriptRoot "GrokAuthenticatedCatalogTime.ps1"
if (-not (Test-Path -LiteralPath $catalogTimeRuntime -PathType Leaf)) {
    throw "GROK_AUTHENTICATED_CATALOG_TIME_RUNTIME_MISSING: $catalogTimeRuntime"
}
. $catalogTimeRuntime

function Get-FileSha256Lower([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Utf8CreateNew([string]$Path, [string]$Text) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
    }
    finally {
        $stream.Dispose()
    }
}

$backgroundInvocationObservedSha256 = ""
$backgroundDrainPid = $null
$backgroundAbsoluteDeadline = $null
if (-not [string]::IsNullOrWhiteSpace($BackgroundInvocationPath)) {
    try {
        $BackgroundInvocationPath = [IO.Path]::GetFullPath($BackgroundInvocationPath)
        if (-not (Test-Path -LiteralPath $BackgroundInvocationPath -PathType Leaf)) {
            throw "GROK_BACKGROUND_INVOCATION_MISSING: $BackgroundInvocationPath"
        }
        if ($BackgroundInvocationSha256 -notmatch '^[0-9a-fA-F]{64}$') {
            throw "GROK_BACKGROUND_INVOCATION_HASH_INVALID"
        }
        $backgroundInvocationObservedSha256 = Get-FileSha256Lower $BackgroundInvocationPath
        if ($backgroundInvocationObservedSha256 -ne $BackgroundInvocationSha256.ToLowerInvariant()) {
            throw "GROK_BACKGROUND_INVOCATION_HASH_MISMATCH"
        }
        $strictInvocationUtf8 = [Text.UTF8Encoding]::new($false, $true)
        $backgroundInvocation = [IO.File]::ReadAllText(
            $BackgroundInvocationPath,
            $strictInvocationUtf8
        ) | ConvertFrom-Json -ErrorAction Stop
        if ($backgroundInvocation.schema_version -ne 'xinao.grok_worker_background_invocation.v1') {
            throw "GROK_BACKGROUND_INVOCATION_SCHEMA_MISMATCH"
        }
        $currentWorkerSha256 = Get-FileSha256Lower $PSCommandPath
        if ([string]$backgroundInvocation.worker_script_sha256 -ne $currentWorkerSha256) {
            throw "GROK_BACKGROUND_WORKER_HASH_MISMATCH"
        }
        $candidateRunId = [string]$backgroundInvocation.run_id
        if ($candidateRunId -notmatch '^c25_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
            throw "GROK_BACKGROUND_RUN_ID_INVALID"
        }
        $candidatePromptFile = [IO.Path]::GetFullPath([string]$backgroundInvocation.prompt_file)
        if (-not (Test-Path -LiteralPath $candidatePromptFile -PathType Leaf)) {
            throw "GROK_BACKGROUND_PROMPT_SNAPSHOT_MISSING"
        }
        if ((Get-FileSha256Lower $candidatePromptFile) -ne [string]$backgroundInvocation.prompt_sha256) {
            throw "GROK_BACKGROUND_PROMPT_SNAPSHOT_HASH_MISMATCH"
        }
        $candidateEvidenceDir = [IO.Path]::GetFullPath([string]$backgroundInvocation.evidence_dir)
        if ([IO.Path]::GetDirectoryName($BackgroundInvocationPath) -ne $candidateEvidenceDir) {
            throw "GROK_BACKGROUND_INVOCATION_EVIDENCE_DIR_MISMATCH"
        }
        if ((Get-FileSha256Lower $processRuntime) -ne [string]$backgroundInvocation.process_runtime_sha256) {
            throw "GROK_BACKGROUND_PROCESS_RUNTIME_HASH_MISMATCH"
        }
        $candidateValidatorScript = Join-Path $PSScriptRoot "Test-GrokCliEffectiveOutput.ps1"
        if (
            -not (Test-Path -LiteralPath $candidateValidatorScript -PathType Leaf) -or
            (Get-FileSha256Lower $candidateValidatorScript) -ne [string]$backgroundInvocation.validator_script_sha256
        ) {
            throw "GROK_BACKGROUND_VALIDATOR_HASH_MISMATCH"
        }
        $candidateSchemaPath = [string]$backgroundInvocation.json_schema_path
        if (-not [string]::IsNullOrWhiteSpace($candidateSchemaPath)) {
            $candidateSchemaPath = [IO.Path]::GetFullPath($candidateSchemaPath)
            if (-not (Test-Path -LiteralPath $candidateSchemaPath -PathType Leaf)) {
                throw "GROK_BACKGROUND_SCHEMA_SNAPSHOT_MISSING"
            }
            if ((Get-FileSha256Lower $candidateSchemaPath) -ne [string]$backgroundInvocation.json_schema_source_sha256) {
                throw "GROK_BACKGROUND_SCHEMA_SNAPSHOT_HASH_MISMATCH"
            }
        }
        $absoluteDeadline = [DateTimeOffset]::MinValue
        if (-not [DateTimeOffset]::TryParse([string]$backgroundInvocation.deadline_utc, [ref]$absoluteDeadline)) {
            throw "GROK_BACKGROUND_DEADLINE_INVALID"
        }
        $remainingTimeoutSec = [int][Math]::Floor(
            ($absoluteDeadline.ToUniversalTime() - [DateTimeOffset]::UtcNow).TotalSeconds
        )
        if ($remainingTimeoutSec -lt 1) {
            throw "GROK_BACKGROUND_DEADLINE_EXPIRED"
        }
        $backgroundAbsoluteDeadline = $absoluteDeadline.ToUniversalTime()

        $Prompt = ""
        $PromptFile = $candidatePromptFile
        $Cwd = [string]$backgroundInvocation.cwd
        $Model = [string]$backgroundInvocation.model
        $MaxTurns = [string]$backgroundInvocation.max_turns
        $OutputFormat = [string]$backgroundInvocation.output_format
        $GrokHome = [string]$backgroundInvocation.grok_home
        $GrokExe = [string]$backgroundInvocation.grok_exe
        $EvidenceDir = $candidateEvidenceDir
        $TimeoutSec = [Math]::Min([int]$backgroundInvocation.timeout_sec, $remainingTimeoutSec)
        $MinResultChars = [int]$backgroundInvocation.min_result_chars
        $RequiredResultMarkers = @($backgroundInvocation.required_result_markers | ForEach-Object { [string]$_ })
        $RequireJsonObject = [bool]$backgroundInvocation.require_json_object
        $JsonSchemaPath = $candidateSchemaPath
        $NoAlwaysApprove = [bool]$backgroundInvocation.no_always_approve
        $Quiet = $true
        $Background = $false
        $DetachedDrain = $true
        $InternalRunId = $candidateRunId
        $backgroundDrainPid = $PID
        $backgroundClaimPath = Join-Path $candidateEvidenceDir ($candidateRunId + ".background.claim.json")
        Write-Utf8CreateNew -Path $backgroundClaimPath -Text (([ordered]@{
            schema_version = "xinao.grok_worker_background_claim.v1"
            run_id = $candidateRunId
            status = "claimed"
            claimed_at = (Get-Date).ToString("o")
            drain_pid = $PID
            invocation_path = $BackgroundInvocationPath
            invocation_sha256 = $backgroundInvocationObservedSha256
            worker_script_sha256 = $currentWorkerSha256
            process_runtime_sha256 = (Get-FileSha256Lower $processRuntime)
            validator_script_sha256 = (Get-FileSha256Lower $candidateValidatorScript)
        }) | ConvertTo-Json -Depth 5 -Compress)
    }
    catch {
        throw "GROK_BACKGROUND_INVOCATION_REJECTED: $($_.Exception.Message)"
    }
}
if (
    ($DetachedDrain -or -not [string]::IsNullOrWhiteSpace($InternalRunId)) -and
    [string]::IsNullOrWhiteSpace($BackgroundInvocationPath)
) {
    throw "GROK_INTERNAL_EXECUTION_REQUIRES_HASH_BOUND_INVOCATION"
}

function Stop-ExactProcessTree([int]$RootProcessId) {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Select-Object ProcessId, ParentProcessId)
    $ids = [System.Collections.Generic.List[int]]::new()
    [void]$ids.Add($RootProcessId)
    do {
        $added = $false
        foreach ($entry in $processes) {
            $childId = [int]$entry.ProcessId
            if ($ids.Contains([int]$entry.ParentProcessId) -and -not $ids.Contains($childId)) {
                [void]$ids.Add($childId)
                $added = $true
            }
        }
    } while ($added)
    $ordered = $ids.ToArray()
    [array]::Reverse($ordered)
    foreach ($processId in $ordered) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    return @($ordered)
}

if (-not $GrokExe) {
    $cand = @(
        (Get-Command grok.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "C:\Users\xx363\.grok\bin\grok.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if (-not $cand) { throw "GROK_CLI_NOT_FOUND: install Grok Build CLI (https://x.ai/cli)" }
    $GrokExe = $cand
}

if ($PromptFile) {
    if (-not (Test-Path -LiteralPath $PromptFile)) { throw "PromptFile missing: $PromptFile" }
    $Prompt = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8
}
if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "Prompt or PromptFile required"
}
if (-not $Cwd) { $Cwd = (Get-Location).Path }
$Cwd = [IO.Path]::GetFullPath($Cwd)
$GrokHome = [IO.Path]::GetFullPath($GrokHome)
$EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
if (-not (Test-Path -LiteralPath $Cwd -PathType Container)) { throw "GROK_CWD_MISSING: $Cwd" }
if (-not (Test-Path -LiteralPath $GrokHome -PathType Container)) { throw "GROK_HOME_MISSING: $GrokHome" }
if ($OutputFormat -ne "json") { throw "GROK_EFFECTIVE_OUTPUT_REQUIRES_JSON" }

$maxTurnsValue = $null
$maxTurnsText = ([string]$MaxTurns).Trim()
if ($maxTurnsText -and $maxTurnsText.ToLowerInvariant() -ne "auto") {
    $parsedMaxTurns = 0
    if (-not [int]::TryParse($maxTurnsText, [ref]$parsedMaxTurns) -or $parsedMaxTurns -lt 1 -or $parsedMaxTurns -gt 40) {
        throw "GROK_MAX_TURNS_INVALID: use auto or 1..40"
    }
    $maxTurnsValue = $parsedMaxTurns
}

$validatorScript = Join-Path $PSScriptRoot "Test-GrokCliEffectiveOutput.ps1"
if (-not (Test-Path -LiteralPath $validatorScript -PathType Leaf)) {
    throw "GROK_EFFECTIVE_OUTPUT_VALIDATOR_MISSING: $validatorScript"
}

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$runId = if (-not [string]::IsNullOrWhiteSpace($InternalRunId)) {
    if ($InternalRunId -notmatch '^c25_[0-9]{8}T[0-9]{6}_[0-9a-f]{8}$') {
        throw "GROK_INTERNAL_RUN_ID_INVALID"
    }
    $InternalRunId
} else {
    "c25_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
}
$outLog = Join-Path $EvidenceDir ($runId + ".out.log")
$errLog = Join-Path $EvidenceDir ($runId + ".err.log")
$cliJsonPath = Join-Path $EvidenceDir ($runId + ".cli.json")
$metaPath = Join-Path $EvidenceDir ($runId + ".json")
$latest = Join-Path $EvidenceDir "latest.json"
$resolvedJsonSchemaPath = ""
$jsonSchemaSnapshotPath = ""
$jsonSchemaCompact = ""
$jsonSchemaSha256 = ""
$jsonSchemaRequested = -not [string]::IsNullOrWhiteSpace($JsonSchemaPath)
$effectiveRequireJsonObject = [bool]($RequireJsonObject -or -not [string]::IsNullOrWhiteSpace($JsonSchemaPath))
$localJsonSchemaValidator = ""
$localJsonSchemaValidatorVersion = ""
$localJsonSchemaPythonExe = ""
$localJsonSchemaCompiler = ""
$localJsonSchemaCompilerVersion = ""
$powerShellVersion = $PSVersionTable.PSVersion.ToString()
$dotnetVersion = [Runtime.InteropServices.RuntimeInformation]::FrameworkDescription
$processArgumentListAvailable = $null -ne ([Diagnostics.ProcessStartInfo]::new()).PSObject.Properties['ArgumentList']
if (-not $processArgumentListAvailable) {
    $argumentTransportFailure = [ordered]@{
        schema_version = "xinao.grok_composer25_worker_preflight.v1"
        sentinel = "SENTINEL:GROK_COMPOSER25_WORKER_PREFLIGHT"
        generated_at = (Get-Date).ToString("o")
        finished_at = (Get-Date).ToString("o")
        run_id = $runId
        status = "preflight_rejected"
        requested_model = $Model
        grok_home = $GrokHome
        cwd = $Cwd
        argv_transport = "unavailable"
        powershell_version = $powerShellVersion
        dotnet_version = $dotnetVersion
        model_tokens_consumed = $false
        error = "GROK_PROCESS_ARGUMENT_LIST_UNAVAILABLE: PowerShell 7 / modern .NET required"
    }
    $argumentTransportFailure | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
    Copy-Item -LiteralPath $metaPath -Destination $latest -Force
    throw $argumentTransportFailure.error
}

if ($Background -and -not $DetachedDrain) {
    $drainProcess = $null
    $drainStarted = $false
    try {
        $backgroundPromptPath = Join-Path $EvidenceDir ($runId + ".background.prompt.md")
        Write-Utf8CreateNew -Path $backgroundPromptPath -Text $Prompt
        $resolvedBackgroundSchemaPath = ""
        $backgroundSchemaSourceSha256 = ""
        if (-not [string]::IsNullOrWhiteSpace($JsonSchemaPath)) {
            $backgroundSchemaSource = [IO.Path]::GetFullPath($JsonSchemaPath)
            if (-not (Test-Path -LiteralPath $backgroundSchemaSource -PathType Leaf)) {
                throw "GROK_JSON_SCHEMA_MISSING: $backgroundSchemaSource"
            }
            $strictBackgroundSchemaUtf8 = [Text.UTF8Encoding]::new($false, $true)
            $backgroundSchemaText = [IO.File]::ReadAllText(
                $backgroundSchemaSource,
                $strictBackgroundSchemaUtf8
            )
            $resolvedBackgroundSchemaPath = Join-Path $EvidenceDir ($runId + ".background.schema.source.json")
            Write-Utf8CreateNew -Path $resolvedBackgroundSchemaPath -Text $backgroundSchemaText
            $backgroundSchemaSourceSha256 = Get-FileSha256Lower $resolvedBackgroundSchemaPath
        }
        $backgroundDeadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSec)
    $backgroundInvocationBody = [ordered]@{
        schema_version = "xinao.grok_worker_background_invocation.v1"
        run_id = $runId
        worker_script_sha256 = (Get-FileSha256Lower $PSCommandPath)
        process_runtime_sha256 = (Get-FileSha256Lower $processRuntime)
        validator_script_sha256 = (Get-FileSha256Lower $validatorScript)
        prompt_file = $backgroundPromptPath
        prompt_sha256 = (Get-FileSha256Lower $backgroundPromptPath)
        cwd = $Cwd
        model = $Model
        max_turns = $MaxTurns
        output_format = $OutputFormat
        grok_home = $GrokHome
        grok_exe = [IO.Path]::GetFullPath($GrokExe)
        evidence_dir = $EvidenceDir
        timeout_sec = $TimeoutSec
        deadline_utc = $backgroundDeadline.ToString("o")
        min_result_chars = $MinResultChars
        required_result_markers = @($RequiredResultMarkers)
        require_json_object = [bool]$RequireJsonObject
        json_schema_path = $resolvedBackgroundSchemaPath
        json_schema_source_sha256 = $backgroundSchemaSourceSha256
        no_always_approve = [bool]$NoAlwaysApprove
    }
    $backgroundInvocationPath = Join-Path $EvidenceDir ($runId + ".background.invocation.json")
    Write-Utf8CreateNew -Path $backgroundInvocationPath -Text (
        $backgroundInvocationBody | ConvertTo-Json -Depth 8 -Compress
    )
    $backgroundInvocationHash = Get-FileSha256Lower $backgroundInvocationPath

    $drainExe = @(
        (Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        (Get-Process -Id $PID -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path -First 1)
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -Unique -First 1
    if (-not $drainExe) {
        throw "GROK_BACKGROUND_DRAIN_PWSH_UNAVAILABLE"
    }
    $drainArguments = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        $PSCommandPath,
        "-BackgroundInvocationPath",
        $backgroundInvocationPath,
        "-BackgroundInvocationSha256",
        $backgroundInvocationHash
    )
    $drainStartInfo = [Diagnostics.ProcessStartInfo]::new()
    $drainStartInfo.FileName = $drainExe
    $drainStartInfo.WorkingDirectory = $Cwd
    $drainStartInfo.UseShellExecute = $false
    $drainStartInfo.CreateNoWindow = $true
    # Give the detached drain its own pipes so it never keeps the caller's
    # redirected stdout/stderr handles open after this launcher exits.
    $drainStartInfo.RedirectStandardOutput = $true
    $drainStartInfo.RedirectStandardError = $true
    $drainArgvTransport = Set-XinaoProcessArguments -StartInfo $drainStartInfo -Arguments $drainArguments
    $drainProcess = [Diagnostics.Process]::new()
    $drainProcess.StartInfo = $drainStartInfo
    [void]$drainProcess.Start()
    $drainStarted = $true
    $drainStdoutTask = $drainProcess.StandardOutput.ReadToEndAsync()
    $drainStderrTask = $drainProcess.StandardError.ReadToEndAsync()

    $backgroundClaimPath = Join-Path $EvidenceDir ($runId + ".background.claim.json")
    $claimDeadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
    while (
        -not (Test-Path -LiteralPath $backgroundClaimPath -PathType Leaf) -and
        -not $drainProcess.HasExited -and
        [DateTimeOffset]::UtcNow -lt $claimDeadline
    ) {
        Start-Sleep -Milliseconds 50
    }
    if (-not (Test-Path -LiteralPath $backgroundClaimPath -PathType Leaf)) {
        if (-not $drainProcess.HasExited) {
            [void](Stop-ExactProcessTree -RootProcessId $drainProcess.Id)
        }
        throw "GROK_BACKGROUND_DRAIN_CLAIM_MISSING"
    }
    $backgroundClaim = Get-Content -LiteralPath $backgroundClaimPath -Raw -Encoding UTF8 |
        ConvertFrom-Json -ErrorAction Stop
    if (
        $backgroundClaim.status -ne "claimed" -or
        [string]$backgroundClaim.run_id -ne $runId -or
        [int]$backgroundClaim.drain_pid -ne $drainProcess.Id -or
        [string]$backgroundClaim.invocation_sha256 -ne $backgroundInvocationHash
    ) {
        if (-not $drainProcess.HasExited) {
            [void](Stop-ExactProcessTree -RootProcessId $drainProcess.Id)
        }
        throw "GROK_BACKGROUND_DRAIN_CLAIM_INVALID"
    }

    $backgroundLaunchPath = Join-Path $EvidenceDir ($runId + ".background.launch.json")
    $backgroundLaunch = [ordered]@{
        schema_version = "xinao.grok_worker_background_launch.v1"
        sentinel = "SENTINEL:GROK_COMPOSER25_WORKER_BACKGROUND"
        generated_at = (Get-Date).ToString("o")
        run_id = $runId
        status = "pending_background"
        effective_output_accepted = $false
        completion_claim_allowed = $false
        drain_pid = $drainProcess.Id
        drain_exe = $drainExe
        argv_transport = $drainArgvTransport
        invocation_path = $backgroundInvocationPath
        invocation_sha256 = $backgroundInvocationHash
        claim_path = $backgroundClaimPath
        claim_sha256 = (Get-FileSha256Lower $backgroundClaimPath)
        prompt_snapshot_path = $backgroundPromptPath
        json_schema_source_snapshot_path = $resolvedBackgroundSchemaPath
        json_schema_source_sha256 = $backgroundSchemaSourceSha256
        deadline_utc = $backgroundDeadline.ToString("o")
        worker_meta_path = $metaPath
        latest_path = $latest
        create_no_window = $true
    }
    Write-Utf8CreateNew -Path $backgroundLaunchPath -Text (
        $backgroundLaunch | ConvertTo-Json -Depth 6
    )
    if (-not $Quiet) {
        $backgroundLaunch | ConvertTo-Json -Depth 6 -Compress
    }
    exit 0
    }
    catch {
        if ($drainStarted -and -not $drainProcess.HasExited) {
            [void](Stop-ExactProcessTree -RootProcessId $drainProcess.Id)
        }
        $backgroundFailure = [ordered]@{
            schema_version = "xinao.grok_composer25_worker_preflight.v1"
            sentinel = "SENTINEL:GROK_COMPOSER25_WORKER_PREFLIGHT"
            generated_at = (Get-Date).ToString("o")
            finished_at = (Get-Date).ToString("o")
            run_id = $runId
            status = "drain_error"
            requested_model = $Model
            background = $true
            effective_output_accepted = $false
            usage_accounting_complete = $false
            model_tokens_consumed = $false
            error = [string]$_.Exception.Message
        }
        $backgroundFailure | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
        Copy-Item -LiteralPath $metaPath -Destination $latest -Force
        throw
    }
}

# Refresh the profile, then distinguish the authenticated server catalog from
# locally configured aliases before consuming any model tokens.
$catalogSnapshot = $null
$catalogTtlSeconds = 300
$priorGrokHome = $env:GROK_HOME
try {
    if ($jsonSchemaRequested) {
        try {
            $resolvedJsonSchemaPath = [IO.Path]::GetFullPath($JsonSchemaPath)
        } catch {
            throw "GROK_JSON_SCHEMA_PATH_INVALID: $JsonSchemaPath"
        }
        if (-not (Test-Path -LiteralPath $resolvedJsonSchemaPath -PathType Leaf)) {
            throw "GROK_JSON_SCHEMA_MISSING: $resolvedJsonSchemaPath"
        }
        try {
            $strictUtf8 = [Text.UTF8Encoding]::new($false, $true)
            $jsonSchemaSource = [IO.File]::ReadAllText($resolvedJsonSchemaPath, $strictUtf8)
        } catch [Text.DecoderFallbackException] {
            throw "GROK_JSON_SCHEMA_INVALID_UTF8: $resolvedJsonSchemaPath"
        } catch {
            throw "GROK_JSON_SCHEMA_READ_FAILED: $resolvedJsonSchemaPath"
        }
        try {
            $jsonSchemaObject = $jsonSchemaSource | ConvertFrom-Json -ErrorAction Stop
        } catch {
            throw "GROK_JSON_SCHEMA_INVALID_JSON: $resolvedJsonSchemaPath"
        }
        if (
            $null -eq $jsonSchemaObject -or
            $jsonSchemaObject -is [Array] -or
            $jsonSchemaObject -is [string] -or
            $jsonSchemaObject -is [ValueType]
        ) {
            throw "GROK_JSON_SCHEMA_TOP_LEVEL_NOT_OBJECT: $resolvedJsonSchemaPath"
        }
        $jsonSchemaCompact = $jsonSchemaObject | ConvertTo-Json -Depth 100 -Compress
        $jsonSchemaBytes = [Text.Encoding]::UTF8.GetBytes($jsonSchemaCompact)
        $schemaHasher = [Security.Cryptography.SHA256]::Create()
        try {
            $schemaHashText = [BitConverter]::ToString(
                $schemaHasher.ComputeHash($jsonSchemaBytes)
            )
            $jsonSchemaSha256 = ($schemaHashText -replace "-", "").ToLowerInvariant()
        } finally {
            $schemaHasher.Dispose()
        }
        $jsonSchemaSnapshotPath = Join-Path $EvidenceDir ($runId + ".schema.json")
        try {
            $schemaSnapshotStream = [IO.File]::Open(
                $jsonSchemaSnapshotPath,
                [IO.FileMode]::CreateNew,
                [IO.FileAccess]::Write,
                [IO.FileShare]::None
            )
            try {
                $schemaSnapshotStream.Write($jsonSchemaBytes, 0, $jsonSchemaBytes.Length)
                $schemaSnapshotStream.Flush()
            } finally {
                $schemaSnapshotStream.Dispose()
            }
        } catch {
            throw "GROK_JSON_SCHEMA_SNAPSHOT_CREATE_FAILED: $jsonSchemaSnapshotPath"
        }

        $nativeValidatorReady = $false
        $testJsonCommand = Get-Command Test-Json -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $testJsonCommand -and $testJsonCommand.Parameters.ContainsKey("Schema")) {
            try {
                $nativeProbe = Test-Json -Json '{}' -Schema '{}' -ErrorAction Stop
                if ($nativeProbe -eq $true) {
                    $nativeValidatorReady = $true
                }
            } catch { }
        }

        $pythonCandidates = @(
            (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
            (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
        ) | Where-Object { $_ } | Select-Object -Unique
        foreach ($pythonCandidate in $pythonCandidates) {
            $pythonProbe = @(& $pythonCandidate -c "import importlib.metadata; print(importlib.metadata.version('jsonschema'))" 2>&1)
            $pythonProbeExit = $LASTEXITCODE
            if ($pythonProbeExit -eq 0 -and -not [string]::IsNullOrWhiteSpace(($pythonProbe -join ""))) {
                $localJsonSchemaPythonExe = $pythonCandidate
                $localJsonSchemaCompiler = "python_jsonschema"
                $localJsonSchemaCompilerVersion = ($pythonProbe -join "").Trim()
                break
            }
        }
        if (-not $localJsonSchemaCompiler) {
            throw "GROK_JSON_SCHEMA_LOCAL_COMPILER_UNAVAILABLE: python jsonschema is required for pre-token schema compilation"
        }
$pythonCompileProgram = @'
import hashlib
import json
import sys
from pathlib import Path

import jsonschema

schema_bytes = Path(sys.argv[1]).read_bytes()
if hashlib.sha256(schema_bytes).hexdigest() != sys.argv[2]:
    raise RuntimeError("schema snapshot hash mismatch")
schema = json.loads(schema_bytes.decode("utf-8"))
validator_class = jsonschema.validators.validator_for(schema)
validator_class.check_schema(schema)
'@
        $pythonCompileOutput = @(& $localJsonSchemaPythonExe -c $pythonCompileProgram $jsonSchemaSnapshotPath $jsonSchemaSha256 2>&1)
        if ($LASTEXITCODE -ne 0) {
            throw "GROK_JSON_SCHEMA_LOCAL_COMPILATION_FAILED: $resolvedJsonSchemaPath"
        }

        if ($nativeValidatorReady) {
            $localJsonSchemaValidator = "powershell_test_json_schema"
            $localJsonSchemaValidatorVersion = [string]$testJsonCommand.Version
        } elseif ($localJsonSchemaPythonExe) {
            $localJsonSchemaValidator = "python_jsonschema"
            $localJsonSchemaValidatorVersion = $localJsonSchemaCompilerVersion
        } else {
            throw "GROK_JSON_SCHEMA_LOCAL_VALIDATOR_UNAVAILABLE: require Test-Json -Schema or python jsonschema"
        }
    }
    $env:GROK_HOME = $GrokHome
    $versionOutput = @(& $GrokExe version 2>&1 | ForEach-Object { [string]$_ })
    $versionExit = $LASTEXITCODE
    $versionText = $versionOutput -join "`n"
    $versionMatch = [regex]::Match($versionText, '(\d+)[.](\d+)[.](\d+)')
    if ($versionExit -ne 0 -or -not $versionMatch.Success) {
        throw "GROK_CLI_VERSION_DISCOVERY_FAILED"
    }
    $cliVersion = [version]$versionMatch.Value
    if ($cliVersion -lt [version]'0.2.85') {
        throw "GROK_CLI_VERSION_TOO_OLD: observed=$cliVersion required=0.2.85"
    }
    $modelsOutput = @(& $GrokExe models 2>&1 | ForEach-Object { [string]$_ })
    $modelsExit = $LASTEXITCODE
    $modelsText = $modelsOutput -join "`n"
    $cliModelIds = @(
        [regex]::Matches(
            $modelsText,
            '(?m)^\s*[-*]\s+([A-Za-z0-9_.-]+)(?:\s+\(default\))?\s*$'
        ) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    )
    if ($modelsExit -ne 0 -or $cliModelIds -notcontains $Model) {
        throw "GROK_REQUESTED_MODEL_UNAVAILABLE: requested=$Model profile=$GrokHome"
    }

    $catalogPath = Join-Path $GrokHome "models_cache.json"
    if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_MISSING: profile=$GrokHome"
    }
    try {
        $catalog = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_INVALID: profile=$GrokHome"
    }
    $catalogOrigin = [string]$catalog.origin
    $catalogUri = $null
    if (-not [uri]::TryCreate($catalogOrigin, [UriKind]::Absolute, [ref]$catalogUri) -or
        $catalogUri.Scheme -ne "https" -or $catalogUri.Host -ne "cli-chat-proxy.grok.com") {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_ORIGIN_INVALID: origin=$catalogOrigin"
    }
    $catalogFetchedAt = ConvertTo-GrokCatalogFetchedAtUtc ([string]$catalog.fetched_at)
    $catalogAgeSeconds = ([DateTimeOffset]::UtcNow - $catalogFetchedAt).TotalSeconds
    if (-not (Test-GrokCatalogAgeWithinWindow `
        -AgeSeconds $catalogAgeSeconds `
        -TtlSeconds $catalogTtlSeconds `
        -MaxFutureSkewSeconds 30)) {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_STALE: fetched_at=$($catalog.fetched_at)"
    }
    if ([string]$catalog.grok_version -ne $cliVersion.ToString()) {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_VERSION_MISMATCH: catalog=$($catalog.grok_version) cli=$cliVersion"
    }
    if ([string]$catalog.auth_method -ne "session") {
        throw "GROK_AUTHENTICATED_MODEL_CATALOG_AUTH_MISMATCH: observed=$($catalog.auth_method) required=session"
    }
    $serverModelIds = @()
    if ($null -ne $catalog.models) {
        $serverModelIds = @($catalog.models.PSObject.Properties.Name | Sort-Object -Unique)
    }
    $catalogSnapshot = [ordered]@{
        schema_version = "xinao.grok.authenticated_model_catalog.v2"
        origin = $catalogOrigin
        fetched_at = $catalogFetchedAt.ToString("o")
        age_seconds = [math]::Round($catalogAgeSeconds, 3)
        ttl_seconds = $catalogTtlSeconds
        grok_version = [string]$catalog.grok_version
        auth_method = [string]$catalog.auth_method
        server_model_ids = @($serverModelIds)
        cli_model_ids = @($cliModelIds)
        requested_model_available = (
            $cliModelIds -contains $Model -and $serverModelIds -contains $Model
        )
        availability_authority = "exact_profile_cli_and_authenticated_server_catalog"
        cache_sha256 = (Get-FileHash -LiteralPath $catalogPath -Algorithm SHA256).Hash.ToLowerInvariant()
        merged_cli_stdout_sha256 = ([BitConverter]::ToString(
            [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($modelsText))
        ) -replace '-', '').ToLowerInvariant()
    }
    if (-not $catalogSnapshot.requested_model_available) {
        throw "GROK_REQUESTED_MODEL_NOT_IN_AUTHENTICATED_CATALOG: requested=$Model available=$($serverModelIds -join ',')"
    }
} catch {
    $preflightFailure = [ordered]@{
        schema_version = "xinao.grok_composer25_worker_preflight.v1"
        sentinel = "SENTINEL:GROK_COMPOSER25_WORKER_PREFLIGHT"
        generated_at = (Get-Date).ToString("o")
        finished_at = (Get-Date).ToString("o")
        run_id = $runId
        status = "preflight_rejected"
        requested_model = $Model
        grok_home = $GrokHome
        cwd = $Cwd
        json_schema_requested = $jsonSchemaRequested
        json_schema_path = if ($resolvedJsonSchemaPath) { $resolvedJsonSchemaPath } else { $JsonSchemaPath }
        json_schema_source_path = if ($resolvedJsonSchemaPath) { $resolvedJsonSchemaPath } else { $JsonSchemaPath }
        json_schema_snapshot_path = $jsonSchemaSnapshotPath
        json_schema_sha256 = $jsonSchemaSha256
        json_schema_expected_sha256 = $jsonSchemaSha256
        json_schema_observed_sha256 = $jsonSchemaSha256
        json_schema_validator = $localJsonSchemaValidator
        json_schema_validator_version = $localJsonSchemaValidatorVersion
        json_schema_python_exe = $localJsonSchemaPythonExe
        json_schema_compiler = $localJsonSchemaCompiler
        json_schema_compiler_version = $localJsonSchemaCompilerVersion
        schema_instance_valid = $null
        require_json_object = $effectiveRequireJsonObject
        argv_transport = "process_start_info_argument_list"
        powershell_version = $powerShellVersion
        dotnet_version = $dotnetVersion
        background = [bool]$DetachedDrain
        drain = if ($DetachedDrain) { "independent_pwsh_process" } else { "synchronous_process" }
        drain_pid = $backgroundDrainPid
        background_invocation_path = $BackgroundInvocationPath
        background_invocation_expected_sha256 = $BackgroundInvocationSha256
        background_invocation_observed_sha256 = $backgroundInvocationObservedSha256
        model_tokens_consumed = $false
        model_catalog = $catalogSnapshot
        error = [string]$_.Exception.Message
    }
    $preflightFailure | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metaPath -Encoding UTF8
    Copy-Item -LiteralPath $metaPath -Destination $latest -Force
    throw
}
finally {
    if ($null -eq $priorGrokHome) { Remove-Item Env:GROK_HOME -ErrorAction SilentlyContinue }
    else { $env:GROK_HOME = $priorGrokHome }
}

# Prefer --prompt-file so long prompts are not split by Start-Process on Windows.
$promptForFile = Join-Path $EvidenceDir ($runId + ".prompt.md")
if ($PromptFile -and (Test-Path -LiteralPath $PromptFile)) {
    Copy-Item -LiteralPath $PromptFile -Destination $promptForFile -Force
} else {
    $Prompt | Set-Content -LiteralPath $promptForFile -Encoding UTF8
}

$shortExecutionContractSource = ""
$shortExecutionContractSha256 = ""
$shortExecutionContractRules = ""
$canonicalWorkerHome = [IO.Path]::GetFullPath("C:\Users\xx363\.grok-bg-workers").TrimEnd('\')
$isCanonicalWorkerPool = [string]::Equals(
    $GrokHome.TrimEnd('\'),
    $canonicalWorkerHome,
    [StringComparison]::OrdinalIgnoreCase
)
if ($isCanonicalWorkerPool) {
    $shortExecutionContractSource = "C:\Users\xx363\Desktop\主线\工具胶水宪法\软件工具胶水宪法_当前有效.txt"
    if (-not (Test-Path -LiteralPath $shortExecutionContractSource -PathType Leaf)) {
        throw "GROK_CANONICAL_SHORT_CONTRACT_SOURCE_MISSING: $shortExecutionContractSource"
    }
    $shortExecutionContractSha256 = Get-FileSha256Lower $shortExecutionContractSource
    $shortExecutionContractRules = @"
Canonical local worker contract source: $shortExecutionContractSource
source_sha256=$shortExecutionContractSha256
Before substantive work, read the current section 七、并发与角色 from that source and follow the task prompt's bounded scope. Return only a non-authoritative candidate and verifiable D evidence; never infer or copy a private Codex conversation, Plan, or private translation TUI. Keep the terminal acceptance envelope concise and leave full artifacts at their referenced evidence root.
"@
}

$argsList = [System.Collections.Generic.List[string]]::new()
[void]$argsList.Add("-m"); [void]$argsList.Add($Model)
[void]$argsList.Add("--cwd"); [void]$argsList.Add($Cwd)
if ($null -ne $maxTurnsValue) {
    [void]$argsList.Add("--max-turns"); [void]$argsList.Add("$maxTurnsValue")
}
[void]$argsList.Add("--output-format"); [void]$argsList.Add("json")
if ($jsonSchemaCompact) {
    [void]$argsList.Add("--json-schema")
    [void]$argsList.Add($jsonSchemaCompact)
}
[void]$argsList.Add("--no-auto-update")
[void]$argsList.Add("--prompt-file"); [void]$argsList.Add($promptForFile)
if ($shortExecutionContractRules) {
    [void]$argsList.Add("--rules")
    [void]$argsList.Add($shortExecutionContractRules)
}
if (-not $NoAlwaysApprove) {
    [void]$argsList.Add("--always-approve")
}

if ($DetachedDrain) {
    $remainingBeforeModelSec = [int][Math]::Floor(
        ($backgroundAbsoluteDeadline - [DateTimeOffset]::UtcNow).TotalSeconds
    )
    if ($remainingBeforeModelSec -lt 1) {
        $deadlineFailure = [ordered]@{
            schema_version = "xinao.grok_composer25_worker_preflight.v1"
            sentinel = "SENTINEL:GROK_COMPOSER25_WORKER_PREFLIGHT"
            generated_at = (Get-Date).ToString("o")
            finished_at = (Get-Date).ToString("o")
            run_id = $runId
            status = "preflight_rejected"
            requested_model = $Model
            background = $true
            drain = "independent_pwsh_process"
            drain_pid = $backgroundDrainPid
            deadline_utc = $backgroundAbsoluteDeadline.ToString("o")
            model_tokens_consumed = $false
            error = "GROK_BACKGROUND_DEADLINE_EXPIRED_BEFORE_MODEL_START"
        }
        $deadlineFailure | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
        Copy-Item -LiteralPath $metaPath -Destination $latest -Force
        throw $deadlineFailure.error
    }
    $TimeoutSec = [Math]::Min($TimeoutSec, $remainingBeforeModelSec)
}

$meta = [ordered]@{
    schema_version = "xinao.grok_composer25_worker.v2"
    execution_contract_version = "xinao.grok.shared_execution_contract.v1"
    sentinel = "SENTINEL:GROK_COMPOSER25_WORKER"
    generated_at = (Get-Date).ToString("o")
    run_id = $runId
    requested_model = $Model
    grok_exe = $GrokExe
    grok_home = $GrokHome
    cwd = $Cwd
    max_turns = if ($null -eq $maxTurnsValue) { "auto" } else { $maxTurnsValue }
    max_turns_cli_applied = ($null -ne $maxTurnsValue)
    cli_version = $cliVersion.ToString()
    model_catalog_verified = $true
    model_catalog = $catalogSnapshot
    min_result_chars = $MinResultChars
    required_result_markers = @($RequiredResultMarkers)
    require_json_object = $effectiveRequireJsonObject
    json_schema_requested = $jsonSchemaRequested
    json_schema_path = $resolvedJsonSchemaPath
    json_schema_source_path = $resolvedJsonSchemaPath
    json_schema_snapshot_path = $jsonSchemaSnapshotPath
    json_schema_sha256 = $jsonSchemaSha256
    json_schema_expected_sha256 = $jsonSchemaSha256
    json_schema_observed_sha256 = $jsonSchemaSha256
    json_schema_cli_applied = [bool]$jsonSchemaCompact
    json_schema_validator = $localJsonSchemaValidator
    json_schema_validator_version = $localJsonSchemaValidatorVersion
    json_schema_python_exe = $localJsonSchemaPythonExe
    json_schema_compiler = $localJsonSchemaCompiler
    json_schema_compiler_version = $localJsonSchemaCompilerVersion
    schema_instance_valid = $null
    argv_transport = "process_start_info_argument_list"
    powershell_version = $powerShellVersion
    dotnet_version = $dotnetVersion
    timeout_sec = $TimeoutSec
    background = [bool]($Background -or $DetachedDrain)
    drain = if ($DetachedDrain) { "independent_pwsh_process" } else { "synchronous_process" }
    drain_pid = $backgroundDrainPid
    background_invocation_path = $BackgroundInvocationPath
    background_invocation_expected_sha256 = $BackgroundInvocationSha256
    background_invocation_observed_sha256 = $backgroundInvocationObservedSha256
    deadline_utc = if ($DetachedDrain) { $backgroundAbsoluteDeadline.ToString("o") } else { "" }
    out_log = $outLog
    err_log = $errLog
    cli_json = $cliJsonPath
    create_no_window = $true
    completion_claim_allowed = $false
    canonical_worker_pool = $isCanonicalWorkerPool
    short_execution_contract_source = $shortExecutionContractSource
    short_execution_contract_sha256 = $shortExecutionContractSha256
    usage_accounting_complete = $false
    note_cn = "Authenticated-catalog exact-model Grok worker; default Composer 2.5; SuperGrok Build quota; CREATE_NO_WINDOW"
    hot_path_cn = "Codex->Grok headless worker (not visible TUI inject; not Docker desktop .lnk)"
}

# Mature Windows spawn: ArgumentList owns Windows quoting; the worker fails
# pre-token on runtimes that do not expose this API.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $GrokExe
$argvTransport = Set-XinaoProcessArguments -StartInfo $psi -Arguments $argsList.ToArray()
$psi.WorkingDirectory = $Cwd
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
if ($GrokHome) {
    $psi.EnvironmentVariables["GROK_HOME"] = $GrokHome
}

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
[void]$proc.Start()
$meta.argv_transport = $argvTransport
$meta.pid = $proc.Id
$meta.status = "running"
$meta.timed_out = $false
$meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
Copy-Item -LiteralPath $metaPath -Destination $latest -Force

$stdoutTask = $proc.StandardOutput.ReadToEndAsync()
$stderrTask = $proc.StandardError.ReadToEndAsync()
$completed = $proc.WaitForExit($TimeoutSec * 1000)
$timedOut = -not $completed
$terminatedPids = @()
if ($timedOut) {
    $terminatedPids = @(Stop-ExactProcessTree -RootProcessId $proc.Id)
    [void]$proc.WaitForExit(10000)
}
$stdout = $stdoutTask.GetAwaiter().GetResult()
$stderr = $stderrTask.GetAwaiter().GetResult()
[IO.File]::WriteAllText($cliJsonPath, $stdout, [Text.UTF8Encoding]::new($false))
$resultText = ""
try {
    $cliPayload = $stdout | ConvertFrom-Json -ErrorAction Stop
    if ($jsonSchemaSnapshotPath -and $null -ne $cliPayload.structuredOutput) {
        $resultText = $cliPayload.structuredOutput | ConvertTo-Json -Depth 100 -Compress
    } else {
        $resultText = [string]$cliPayload.text
    }
} catch { }
[IO.File]::WriteAllText($outLog, $resultText, [Text.UTF8Encoding]::new($false))
if ($stderr) { $stderr | Set-Content -LiteralPath $errLog -Encoding UTF8 }

$validatorArgs = @{
    CliJsonPath = $cliJsonPath
    RequestedModel = $Model
    GrokHome = $GrokHome
    ExpectedCwd = $Cwd
    ProcessExitCode = $proc.ExitCode
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
}
if ($effectiveRequireJsonObject) { $validatorArgs.RequireJsonObject = $true }
if ($jsonSchemaSnapshotPath) {
    $validatorArgs.JsonSchemaPath = $jsonSchemaSnapshotPath
    $validatorArgs.ExpectedJsonSchemaSha256 = $jsonSchemaSha256
    $validatorArgs.JsonSchemaValidator = $localJsonSchemaValidator
    if ($localJsonSchemaPythonExe) { $validatorArgs.JsonSchemaPythonExe = $localJsonSchemaPythonExe }
}
$validationText = [string](& $validatorScript @validatorArgs)
$validatorExit = $LASTEXITCODE
$validation = $validationText | ConvertFrom-Json -ErrorAction Stop
$meta.validation = $validation
foreach ($property in $validation.PSObject.Properties) {
    if ($property.Name -in @("schema_version", "sentinel", "generated_at", "run_id")) { continue }
    $meta[$property.Name] = $property.Value
}
$meta.status = if ($validation.effective_output_accepted) { "accepted" } else { "rejected" }
if ($timedOut) {
    $meta.status = "timeout"
    $meta.effective_output_accepted = $false
    if ($null -eq $meta.usage -or $meta.usage_is_incomplete -eq $true) {
        $meta.usage_accounting_complete = $false
    }
}
$meta.outcome = $meta.status
$meta.exit_code = $proc.ExitCode
$meta.validator_exit_code = $validatorExit
$meta.pid = $proc.Id
$meta.timed_out = $timedOut
$meta.terminated_process_ids = @($terminatedPids)
$meta.finished_at = (Get-Date).ToString("o")
$meta | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $metaPath -Encoding UTF8
Copy-Item $metaPath $latest -Force

if (-not $Quiet) {
    Write-Output $resultText
    if ($stderr) { Write-Error $stderr }
}
if ($timedOut) { exit 124 }
if ($validation.effective_output_accepted) { exit 0 }
if ($proc.ExitCode -ne 0) { exit $proc.ExitCode }
exit 3
