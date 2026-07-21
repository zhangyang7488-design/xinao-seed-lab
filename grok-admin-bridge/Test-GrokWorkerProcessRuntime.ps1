#Requires -Version 7.0
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Name) {
    if (-not $Condition) { throw "CONTRACT_FAILED: $Name" }
}

$bridge = $PSScriptRoot
$processRuntime = Join-Path $bridge "GrokWorkerProcessRuntime.ps1"
$workerScript = Join-Path $bridge "Invoke-GrokComposer25Worker.ps1"
. $processRuntime

$pwshExe = Get-Command pwsh.exe -ErrorAction Stop | Select-Object -ExpandProperty Source -First 1
$testId = "grok-process-runtime-" + (Get-Date -Format "yyyyMMddTHHmmss") + "-" +
    ([guid]::NewGuid().ToString("N").Substring(0, 8))
$testRoot = Join-Path "D:\XINAO_RESEARCH_RUNTIME\tmp" $testId
New-Item -ItemType Directory -Force -Path $testRoot | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)

$receiverPath = Join-Path $testRoot "argv-receiver.ps1"
$receiverSource = @'
param([string]$OutputPath)
$records = @(
    foreach ($value in @($args)) {
        $bytes = [Text.Encoding]::UTF8.GetBytes([string]$value)
        [ordered]@{
            value = [string]$value
            utf8_base64 = [Convert]::ToBase64String($bytes)
            byte_count = $bytes.Length
        }
    }
)
[IO.File]::WriteAllText(
    $OutputPath,
    ($records | ConvertTo-Json -Depth 5 -Compress -AsArray),
    [Text.UTF8Encoding]::new($false)
)
'@
[IO.File]::WriteAllText($receiverPath, $receiverSource, $utf8)

$complexSchema = '{"type":"object","description":"quote \" and slash \\","patternProperties":{"^a\\s+$":{"type":"string"}}}'
$null = $complexSchema | ConvertFrom-Json -ErrorAction Stop
$matrix = @(
    "",
    "plain",
    "with space",
    'quote " inside',
    'trailing slash \',
    'one \"',
    'two \\"',
    "中文 café Ω 😀",
    $complexSchema
)
$receiverOutput = Join-Path $testRoot "argv-observed.json"
$receiverInfo = [Diagnostics.ProcessStartInfo]::new()
$receiverInfo.FileName = $pwshExe
$receiverInfo.UseShellExecute = $false
$receiverInfo.CreateNoWindow = $true
$receiverInfo.RedirectStandardOutput = $true
$receiverInfo.RedirectStandardError = $true
$transport = Set-XinaoProcessArguments -StartInfo $receiverInfo -Arguments (@(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $receiverPath, $receiverOutput
) + $matrix)
$receiver = [Diagnostics.Process]::new()
$receiver.StartInfo = $receiverInfo
[void]$receiver.Start()
$receiverStdout = $receiver.StandardOutput.ReadToEndAsync()
$receiverStderr = $receiver.StandardError.ReadToEndAsync()
Assert-Contract ($receiver.WaitForExit(30000)) "argv_receiver_timeout"
$receiverOutText = $receiverStdout.GetAwaiter().GetResult()
$receiverErrText = $receiverStderr.GetAwaiter().GetResult()
Assert-Contract ($receiver.ExitCode -eq 0) "argv_receiver_exit:$receiverOutText|$receiverErrText"
$observed = @(Get-Content -LiteralPath $receiverOutput -Raw -Encoding UTF8 | ConvertFrom-Json)
Assert-Contract ($transport -eq "process_start_info_argument_list") "argument_list_transport"
Assert-Contract ($observed.Count -eq $matrix.Count) "argv_count"
for ($index = 0; $index -lt $matrix.Count; $index++) {
    $expectedBytes = [Text.Encoding]::UTF8.GetBytes([string]$matrix[$index])
    Assert-Contract (
        [string]$observed[$index].utf8_base64 -eq [Convert]::ToBase64String($expectedBytes)
    ) "argv_bytes_$index"
}

# Capture the exact provider argv with a compiled no-model probe.  The probe
# satisfies version/catalog discovery, records the final invocation, and never
# contacts a provider or consumes model tokens.
$sandboxCapture = Join-Path $testRoot "sandbox-argv.base64"
$fakeGrokExe = Get-Command python.exe -ErrorAction Stop | Select-Object -ExpandProperty Source -First 1
$fakeVersion = Join-Path $testRoot "version"
$fakeModels = Join-Path $testRoot "models"
$fakeModule = Join-Path $testRoot "fakegrok.py"
[IO.File]::WriteAllText($fakeVersion, 'print("grok 0.2.85")', $utf8)
[IO.File]::WriteAllText($fakeModels, 'print("- fakegrok")', $utf8)
$fakeModuleSource = @'
import base64
import json
import os
import sys

with open(os.environ["XINAO_FAKE_GROK_CAPTURE"], "w", encoding="utf-8", newline="\n") as stream:
    for value in sys.argv[1:]:
        stream.write(base64.b64encode(value.encode("utf-8")).decode("ascii") + "\n")
print(json.dumps({"text": "SANDBOX_CAPTURE_NO_MODEL"}, separators=(",", ":")))
'@
[IO.File]::WriteAllText($fakeModule, $fakeModuleSource, $utf8)
$sandboxHome = Join-Path $testRoot "sandbox-home"
$sandboxEvidence = Join-Path $testRoot "sandbox-evidence"
$sandboxCwd = Join-Path $testRoot "sandbox-candidate-cwd"
New-Item -ItemType Directory -Force -Path $sandboxHome, $sandboxEvidence, $sandboxCwd | Out-Null
Copy-Item -LiteralPath $fakeModule -Destination (Join-Path $sandboxCwd "fakegrok.py")
$catalog = [ordered]@{
    origin = "https://cli-chat-proxy.grok.com/v1/models"
    # PowerShell 7.6 ConvertFrom-Json materializes ISO dates as local DateTime;
    # compensate so the worker's legacy string seam observes the current UTC clock.
    fetched_at = [DateTimeOffset]::UtcNow.Subtract(
        [TimeZoneInfo]::Local.GetUtcOffset([DateTime]::Now)
    ).ToString("o")
    grok_version = "0.2.85"
    auth_method = "session"
    models = [ordered]@{ "fakegrok" = [ordered]@{} }
}
[IO.File]::WriteAllText(
    (Join-Path $sandboxHome "models_cache.json"),
    ($catalog | ConvertTo-Json -Depth 6 -Compress),
    $utf8
)
$sandboxProbeInfo = [Diagnostics.ProcessStartInfo]::new()
$sandboxProbeInfo.FileName = $pwshExe
$sandboxProbeInfo.WorkingDirectory = $testRoot
$sandboxProbeInfo.UseShellExecute = $false
$sandboxProbeInfo.CreateNoWindow = $true
$sandboxProbeInfo.RedirectStandardOutput = $true
$sandboxProbeInfo.RedirectStandardError = $true
$sandboxProbeInfo.EnvironmentVariables["XINAO_FAKE_GROK_CAPTURE"] = $sandboxCapture
$null = Set-XinaoProcessArguments -StartInfo $sandboxProbeInfo -Arguments @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $workerScript,
    "-Prompt", "SANDBOX_CAPTURE_NO_MODEL",
    "-Cwd", $sandboxCwd,
    "-Model", "fakegrok",
    "-GrokHome", $sandboxHome,
    "-GrokExe", $fakeGrokExe,
    "-EvidenceDir", $sandboxEvidence,
    "-TimeoutSec", "30",
    "-MinResultChars", "1",
    "-Quiet"
)
$sandboxProbe = [Diagnostics.Process]::new()
$sandboxProbe.StartInfo = $sandboxProbeInfo
[void]$sandboxProbe.Start()
$sandboxProbeStdout = $sandboxProbe.StandardOutput.ReadToEndAsync()
$sandboxProbeStderr = $sandboxProbe.StandardError.ReadToEndAsync()
Assert-Contract ($sandboxProbe.WaitForExit(30000)) "sandbox_no_model_probe_timeout"
$sandboxProbeOutput = $sandboxProbeStdout.GetAwaiter().GetResult()
$sandboxProbeError = $sandboxProbeStderr.GetAwaiter().GetResult()
Assert-Contract (Test-Path -LiteralPath $sandboxCapture -PathType Leaf) "sandbox_no_model_argv_captured:$sandboxProbeOutput|$sandboxProbeError"
$sandboxArguments = @(
    Get-Content -LiteralPath $sandboxCapture -Encoding UTF8 |
        ForEach-Object { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
)
$sandboxIndex = [Array]::IndexOf($sandboxArguments, "--sandbox")
$cwdIndex = [Array]::IndexOf($sandboxArguments, "--cwd")
Assert-Contract ($sandboxIndex -ge 0 -and $sandboxIndex + 1 -lt $sandboxArguments.Count) "sandbox_flag_present"
Assert-Contract ([string]$sandboxArguments[$sandboxIndex + 1] -eq "workspace") "sandbox_profile_workspace"
Assert-Contract ($cwdIndex -ge 0 -and [string]$sandboxArguments[$cwdIndex + 1] -eq [IO.Path]::GetFullPath($sandboxCwd)) "sandbox_probe_exact_candidate_cwd"
Assert-Contract (-not (@($sandboxArguments) -contains "off")) "sandbox_off_absent_from_model_command"

$negativePath = Join-Path $testRoot "winps-negative.ps1"
$escapedRuntime = $processRuntime.Replace("'", "''")
$negativeSource = @"
. '$escapedRuntime'
`$psi = New-Object Diagnostics.ProcessStartInfo
try {
    `$null = Set-XinaoProcessArguments -StartInfo `$psi -Arguments @('probe')
    exit 2
}
catch {
    if (`$_.Exception.Message -eq 'GROK_PROCESS_ARGUMENT_LIST_UNAVAILABLE: PowerShell 7 / modern .NET required') { exit 0 }
    Write-Error `$_
    exit 3
}
"@
[IO.File]::WriteAllText($negativePath, $negativeSource, $utf8)
$windowsPowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
& $windowsPowerShell -NoLogo -NoProfile -NonInteractive -File $negativePath
Assert-Contract ($LASTEXITCODE -eq 0) "winps_argument_list_fail_closed"

$detachedMarker = Join-Path $testRoot "detached-child.json"
$detachedChildPath = Join-Path $testRoot "detached-child.ps1"
$escapedDetachedMarker = $detachedMarker.Replace("'", "''")
$detachedChildSource = @"
Start-Sleep -Milliseconds 3000
[IO.File]::WriteAllText(
    '$escapedDetachedMarker',
    ([ordered]@{ pid = `$PID; finished_at = (Get-Date).ToString('o') } | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new(`$false)
)
"@
[IO.File]::WriteAllText($detachedChildPath, $detachedChildSource, $utf8)

$detachedLauncherPath = Join-Path $testRoot "detached-launcher.ps1"
$detachedReceipt = Join-Path $testRoot "detached-launch.json"
$escapedPwsh = $pwshExe.Replace("'", "''")
$escapedDetachedChild = $detachedChildPath.Replace("'", "''")
$escapedDetachedReceipt = $detachedReceipt.Replace("'", "''")
$detachedLauncherSource = @"
. '$escapedRuntime'
`$psi = New-Object Diagnostics.ProcessStartInfo
`$psi.FileName = '$escapedPwsh'
`$psi.UseShellExecute = `$false
`$psi.CreateNoWindow = `$true
`$transport = Set-XinaoProcessArguments -StartInfo `$psi -Arguments @('-NoLogo','-NoProfile','-NonInteractive','-File','$escapedDetachedChild')
`$process = New-Object Diagnostics.Process
`$process.StartInfo = `$psi
[void]`$process.Start()
[IO.File]::WriteAllText(
    '$escapedDetachedReceipt',
    ([ordered]@{ child_pid = `$process.Id; transport = `$transport } | ConvertTo-Json -Compress),
    [Text.UTF8Encoding]::new(`$false)
)
exit 0
"@
[IO.File]::WriteAllText($detachedLauncherPath, $detachedLauncherSource, $utf8)
$detachedLauncherInfo = [Diagnostics.ProcessStartInfo]::new()
$detachedLauncherInfo.FileName = $pwshExe
$detachedLauncherInfo.UseShellExecute = $false
$detachedLauncherInfo.CreateNoWindow = $true
$null = Set-XinaoProcessArguments -StartInfo $detachedLauncherInfo -Arguments @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $detachedLauncherPath
)
$detachedLauncher = [Diagnostics.Process]::new()
$detachedLauncher.StartInfo = $detachedLauncherInfo
[void]$detachedLauncher.Start()
Assert-Contract ($detachedLauncher.WaitForExit(30000)) "detached_launcher_timeout"
Assert-Contract ($detachedLauncher.ExitCode -eq 0) "detached_launcher_exit"
Assert-Contract (-not (Test-Path -LiteralPath $detachedMarker)) "detached_child_finished_before_parent_exit"
$detachedDeadline = [DateTimeOffset]::UtcNow.AddSeconds(15)
while (-not (Test-Path -LiteralPath $detachedMarker) -and [DateTimeOffset]::UtcNow -lt $detachedDeadline) {
    Start-Sleep -Milliseconds 50
}
Assert-Contract (Test-Path -LiteralPath $detachedMarker -PathType Leaf) "detached_child_survives_parent_exit"

$backgroundEvidence = Join-Path $testRoot "worker-background"
$backgroundHome = Join-Path $testRoot "grok-home"
New-Item -ItemType Directory -Force -Path $backgroundEvidence, $backgroundHome | Out-Null
$backgroundSchema = Join-Path $testRoot "background-schema.json"
$backgroundSchemaBytes = [Text.Encoding]::UTF8.GetBytes("{`n  `"title`": `"原始字节`",`n  `"type`": `"object`"`n}")
[IO.File]::WriteAllBytes($backgroundSchema, $backgroundSchemaBytes)
$workerParentInfo = [Diagnostics.ProcessStartInfo]::new()
$workerParentInfo.FileName = $pwshExe
$workerParentInfo.UseShellExecute = $false
$workerParentInfo.CreateNoWindow = $true
$workerParentInfo.RedirectStandardOutput = $true
$workerParentInfo.RedirectStandardError = $true
$null = Set-XinaoProcessArguments -StartInfo $workerParentInfo -Arguments @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-File", $workerScript,
    "-Prompt", "BACKGROUND_LIFECYCLE_NO_MODEL",
    "-Cwd", $bridge,
    "-Model", "no-model-probe",
    "-GrokHome", $backgroundHome,
    "-GrokExe", $pwshExe,
    "-EvidenceDir", $backgroundEvidence,
    "-JsonSchemaPath", $backgroundSchema,
    "-TimeoutSec", "30",
    "-MinResultChars", "1",
    "-Background"
)
$workerParent = [Diagnostics.Process]::new()
$workerParent.StartInfo = $workerParentInfo
[void]$workerParent.Start()
$workerParentLaunchLine = $workerParent.StandardOutput.ReadLineAsync()
$workerParentStderr = $workerParent.StandardError.ReadToEndAsync()
Assert-Contract ($workerParent.WaitForExit(30000)) "background_parent_timeout"
$workerParentExitedAt = [DateTimeOffset]::UtcNow
$workerParentOutput = $workerParentLaunchLine.GetAwaiter().GetResult()
$workerParentError = $workerParentStderr.GetAwaiter().GetResult()
Assert-Contract ($workerParent.ExitCode -eq 0) "background_parent_exit:$workerParentError"
$launch = $workerParentOutput | ConvertFrom-Json -ErrorAction Stop
Assert-Contract ($launch.status -eq "pending_background") "background_launch_pending"
Assert-Contract ($launch.completion_claim_allowed -eq $false) "background_pending_is_not_completion"
Assert-Contract (Test-Path -LiteralPath $launch.claim_path -PathType Leaf) "background_claim_present"
Assert-Contract ([string]$launch.argv_transport -eq "process_start_info_argument_list") "background_argument_list"
$backgroundSchemaSnapshot = Get-ChildItem -LiteralPath $backgroundEvidence -Filter "*.background.schema.source.json" |
    Select-Object -First 1
Assert-Contract ($null -ne $backgroundSchemaSnapshot) "background_schema_snapshot_present"
$backgroundSchemaSnapshotBytes = [IO.File]::ReadAllBytes($backgroundSchemaSnapshot.FullName)
Assert-Contract (
    [Linq.Enumerable]::SequenceEqual[byte]($backgroundSchemaBytes, $backgroundSchemaSnapshotBytes)
) "background_schema_snapshot_exact_raw_bytes"
$backgroundInvocation = Get-ChildItem -LiteralPath $backgroundEvidence -Filter "*.background.invocation.json" |
    Select-Object -First 1 | ForEach-Object {
        Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    }
Assert-Contract ([string]$backgroundInvocation.json_schema_digest_profile -eq "raw-bytes-sha256-v1") "background_schema_digest_profile"
Assert-Contract ([string]$backgroundInvocation.json_schema_transformation_profile -eq "identity") "background_schema_identity_transform"
$workerMetaPath = [string]$launch.worker_meta_path
$drainAliveAtParentExit = $null -ne (Get-Process -Id ([int]$launch.drain_pid) -ErrorAction SilentlyContinue)
$terminalPresentAtParentExit = $false
if (Test-Path -LiteralPath $workerMetaPath -PathType Leaf) {
    $stateAtParentExit = Get-Content -LiteralPath $workerMetaPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $terminalPresentAtParentExit = [string]$stateAtParentExit.status -in @(
        "accepted", "rejected", "timeout", "preflight_rejected", "drain_error"
    )
}
Assert-Contract (
    $drainAliveAtParentExit -or $terminalPresentAtParentExit
) "background_claim_has_live_owner_or_exact_terminal"
$workerDeadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
while (-not (Test-Path -LiteralPath $workerMetaPath -PathType Leaf) -and [DateTimeOffset]::UtcNow -lt $workerDeadline) {
    Start-Sleep -Milliseconds 100
}
Assert-Contract (Test-Path -LiteralPath $workerMetaPath -PathType Leaf) "background_final_meta_present"
$workerMeta = Get-Content -LiteralPath $workerMetaPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Contract ($workerMeta.status -eq "preflight_rejected") "background_preflight_terminal"
Assert-Contract ($workerMeta.model_tokens_consumed -eq $false) "background_no_model_tokens"
Assert-Contract ($workerMeta.background -eq $true) "background_receipt"
Assert-Contract ([string]$workerMeta.drain -eq "independent_pwsh_process") "background_independent_drain"

[ordered]@{
    status = "verified"
    test_root = $testRoot
    argv_transport = $transport
    argv_case_count = $matrix.Count
    complex_schema_sha256 = (
        [BitConverter]::ToString(
            [Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($complexSchema))
        ) -replace '-', ''
    ).ToLowerInvariant()
    sandbox_no_model_command_captured = $true
    sandbox_profile = [string]$sandboxArguments[$sandboxIndex + 1]
    sandbox_candidate_cwd = [string]$sandboxArguments[$cwdIndex + 1]
    winps_fail_closed = $true
    detached_child_survived_parent_exit = $true
    background_worker_terminal = $workerMeta.status
    background_model_tokens_consumed = $workerMeta.model_tokens_consumed
    background_parent_exited_at = $workerParentExitedAt.ToString("o")
    background_drain_alive_at_parent_exit = $drainAliveAtParentExit
    background_terminal_present_at_parent_exit = $terminalPresentAtParentExit
} | ConvertTo-Json -Depth 6
