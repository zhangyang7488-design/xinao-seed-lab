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
    [switch]$Background,
    [switch]$NoAlwaysApprove,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

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
$runId = "c25_" + (Get-Date -Format "yyyyMMddTHHmmss") + "_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
$outLog = Join-Path $EvidenceDir ($runId + ".out.log")
$errLog = Join-Path $EvidenceDir ($runId + ".err.log")
$cliJsonPath = Join-Path $EvidenceDir ($runId + ".cli.json")
$metaPath = Join-Path $EvidenceDir ($runId + ".json")
$latest = Join-Path $EvidenceDir "latest.json"

# Refresh the profile, then distinguish the authenticated server catalog from
# locally configured aliases before consuming any model tokens.
$catalogSnapshot = $null
$catalogTtlSeconds = 300
$priorGrokHome = $env:GROK_HOME
try {
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
    $modelPattern = '(?<![A-Za-z0-9_.-])' + [regex]::Escape($Model) + '(?![A-Za-z0-9_.-])'
    if ($modelsExit -ne 0 -or $modelsText -notmatch $modelPattern) {
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
    $catalogFetchedAt = [DateTimeOffset]::MinValue
    $catalogAgeSeconds = [double]::PositiveInfinity
    if ([DateTimeOffset]::TryParse([string]$catalog.fetched_at, [ref]$catalogFetchedAt)) {
        $catalogAgeSeconds = ([DateTimeOffset]::UtcNow - $catalogFetchedAt).TotalSeconds
    }
    if ([double]::IsInfinity($catalogAgeSeconds) -or $catalogAgeSeconds -lt -30 -or
        $catalogAgeSeconds -gt $catalogTtlSeconds) {
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
        schema_version = "xinao.grok.authenticated_model_catalog.v1"
        origin = $catalogOrigin
        fetched_at = $catalogFetchedAt.ToString("o")
        age_seconds = [math]::Round($catalogAgeSeconds, 3)
        ttl_seconds = $catalogTtlSeconds
        grok_version = [string]$catalog.grok_version
        auth_method = [string]$catalog.auth_method
        server_model_ids = @($serverModelIds)
        requested_model_available = ($serverModelIds -contains $Model)
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

$argsList = [System.Collections.Generic.List[string]]::new()
[void]$argsList.Add("-m"); [void]$argsList.Add($Model)
[void]$argsList.Add("--cwd"); [void]$argsList.Add($Cwd)
if ($null -ne $maxTurnsValue) {
    [void]$argsList.Add("--max-turns"); [void]$argsList.Add("$maxTurnsValue")
}
[void]$argsList.Add("--output-format"); [void]$argsList.Add("json")
[void]$argsList.Add("--no-auto-update")
[void]$argsList.Add("--prompt-file"); [void]$argsList.Add($promptForFile)
if (-not $NoAlwaysApprove) {
    [void]$argsList.Add("--always-approve")
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
    require_json_object = [bool]$RequireJsonObject
    timeout_sec = $TimeoutSec
    background = [bool]$Background
    out_log = $outLog
    err_log = $errLog
    cli_json = $cliJsonPath
    create_no_window = $true
    completion_claim_allowed = $false
    usage_accounting_complete = $false
    note_cn = "Authenticated-catalog exact-model Grok worker; default Composer 2.5; SuperGrok Build quota; CREATE_NO_WINDOW"
    hot_path_cn = "Codex->Grok headless worker (not visible TUI inject; not Docker desktop .lnk)"
}

# Mature Windows spawn: UseShellExecute=false + CreateNoWindow (not WindowStyle Hidden flash).
$argString = ($argsList | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $GrokExe
$psi.Arguments = $argString
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
$meta.pid = $proc.Id
$meta.status = "running"
$meta.timed_out = $false
$meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
Copy-Item -LiteralPath $metaPath -Destination $latest -Force

if ($Background) {
    # Drain stdio to files on a background runspace so parent can return without -WindowStyle Hidden flash.
    $drain = {
        param(
            $Process, $OutLog, $ErrLog, $CliJsonPath, $MetaPath, $LatestPath,
            $MetaObj, $ValidatorScript, $RequestedModel, $MinChars, $Markers,
            $RequireJson, $TimeoutSec
        )
        try {
            $stdoutTask = $Process.StandardOutput.ReadToEndAsync()
            $stderrTask = $Process.StandardError.ReadToEndAsync()
            $completed = $Process.WaitForExit($TimeoutSec * 1000)
            $timedOut = -not $completed
            $terminatedPids = @()
            if ($timedOut) {
                $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                    Select-Object ProcessId, ParentProcessId)
                $ids = [System.Collections.Generic.List[int]]::new()
                [void]$ids.Add([int]$Process.Id)
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
                $terminatedPids = $ids.ToArray()
                [array]::Reverse($terminatedPids)
                foreach ($processId in $terminatedPids) {
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                }
                [void]$Process.WaitForExit(10000)
            }
            $stdout = $stdoutTask.GetAwaiter().GetResult()
            $stderr = $stderrTask.GetAwaiter().GetResult()
            $utf8 = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($CliJsonPath, $stdout, $utf8)
            $resultText = ""
            try { $resultText = [string](($stdout | ConvertFrom-Json -ErrorAction Stop).text) } catch { }
            [System.IO.File]::WriteAllText($OutLog, $resultText, $utf8)
            if ($stderr) { [System.IO.File]::WriteAllText($ErrLog, $stderr, $utf8) }
            $validatorArgs = @{
                CliJsonPath = $CliJsonPath
                RequestedModel = $RequestedModel
                ProcessExitCode = $Process.ExitCode
                MinResultChars = $MinChars
                RequiredResultMarkers = @($Markers)
            }
            if ($RequireJson) { $validatorArgs.RequireJsonObject = $true }
            $validationText = [string](& $ValidatorScript @validatorArgs)
            $validatorExit = $LASTEXITCODE
            $validation = $validationText | ConvertFrom-Json -ErrorAction Stop
            $MetaObj.validation = $validation
            foreach ($property in $validation.PSObject.Properties) {
                if ($property.Name -in @("schema_version", "sentinel", "generated_at", "run_id")) { continue }
                $MetaObj[$property.Name] = $property.Value
            }
            $MetaObj.status = if ($validation.effective_output_accepted) {
                "accepted_background"
            } else {
                "rejected_background"
            }
            if ($timedOut) {
                $MetaObj.status = "timeout_background"
                $MetaObj.effective_output_accepted = $false
                $MetaObj.usage_accounting_complete = $false
            }
            $MetaObj.exit_code = $Process.ExitCode
            $MetaObj.validator_exit_code = $validatorExit
            $MetaObj.timed_out = $timedOut
            $MetaObj.terminated_process_ids = @($terminatedPids)
            $MetaObj.finished_at = (Get-Date).ToString("o")
            $json = ($MetaObj | ConvertTo-Json -Depth 10)
            [System.IO.File]::WriteAllText($MetaPath, $json, $utf8)
            Copy-Item -LiteralPath $MetaPath -Destination $LatestPath -Force
        } catch {
            try {
                $MetaObj.status = "drain_error"
                $MetaObj.error = "$_"
                $MetaObj.finished_at = (Get-Date).ToString("o")
                $MetaObj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $MetaPath -Encoding UTF8
            } catch { }
        }
    }
    $rs = [runspacefactory]::CreateRunspace()
    $rs.Open()
    $ps = [powershell]::Create()
    $ps.Runspace = $rs
    [void]$ps.AddScript($drain).AddArgument($proc).AddArgument($outLog).AddArgument($errLog).AddArgument($cliJsonPath).AddArgument($metaPath).AddArgument($latest).AddArgument($meta).AddArgument($validatorScript).AddArgument($Model).AddArgument($MinResultChars).AddArgument(@($RequiredResultMarkers)).AddArgument([bool]$RequireJsonObject).AddArgument($TimeoutSec)
    $meta.status = "pending_background"
    $meta.effective_output_accepted = $false
    $meta.pid = $proc.Id
    $meta.drain = "runspace_create_no_window"
    $meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding UTF8
    Copy-Item $metaPath $latest -Force
    [void]$ps.BeginInvoke()
    if (-not $Quiet) {
        @{ accepted = $false; status = "pending_background"; run_id = $runId; pid = $proc.Id; out_log = $outLog; latest = $latest; create_no_window = $true } | ConvertTo-Json
    }
    exit 0
}

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
try { $resultText = [string](($stdout | ConvertFrom-Json -ErrorAction Stop).text) } catch { }
[IO.File]::WriteAllText($outLog, $resultText, [Text.UTF8Encoding]::new($false))
if ($stderr) { $stderr | Set-Content -LiteralPath $errLog -Encoding UTF8 }

$validatorArgs = @{
    CliJsonPath = $cliJsonPath
    RequestedModel = $Model
    ProcessExitCode = $proc.ExitCode
    MinResultChars = $MinResultChars
    RequiredResultMarkers = @($RequiredResultMarkers)
}
if ($RequireJsonObject) { $validatorArgs.RequireJsonObject = $true }
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
    $meta.usage_accounting_complete = $false
}
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
