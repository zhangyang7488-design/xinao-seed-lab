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
[IO.File]::WriteAllText($backgroundSchema, '{"type":"object"}', $utf8)
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
    winps_fail_closed = $true
    detached_child_survived_parent_exit = $true
    background_worker_terminal = $workerMeta.status
    background_model_tokens_consumed = $workerMeta.model_tokens_consumed
    background_parent_exited_at = $workerParentExitedAt.ToString("o")
    background_drain_alive_at_parent_exit = $drainAliveAtParentExit
    background_terminal_present_at_parent_exit = $terminalPresentAtParentExit
} | ConvertTo-Json -Depth 6
