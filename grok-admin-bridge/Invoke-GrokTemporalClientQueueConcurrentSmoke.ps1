#Requires -Version 5.1
<#
.SYNOPSIS
  双进程并发 integrated_bus_runner --temporal 真波烟测 · 验证 temporal_client_queue submit.lock 串行。
.DESCRIPTION
  S 仓起两路并发 --temporal；采样 submit.lock；解析 temporal_client_queue.waited_sec。
  证据落 D:\XINAO_RESEARCH_RUNTIME\readback\zh\ + evidence\ + state\integrated_bus_temporal_client_queue\
  completion_claim_allowed 由扫描器决定；本脚本不宣布闭合。
.EXAMPLE
  .\Invoke-GrokTemporalClientQueueConcurrentSmoke.ps1
  .\Invoke-GrokTemporalClientQueueConcurrentSmoke.ps1 -AllowEphemeralWorker
#>
param(
    [switch]$AllowEphemeralWorker,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
$configPath = Join-Path $bridge "bridge.config.json"
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1") -ConfigPath $configPath
$config = $null
try { $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
$sRepo = if ($config -and $config.repo_root) { [string]$config.repo_root } else { "E:\XINAO_RESEARCH_WORKSPACES\S" }

$ts = (Get-Date).ToString("o")
$runId = "tcq_smoke_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$zhDir = Join-Path $runtime "readback\zh"
$evidenceDir = Join-Path $runtime "evidence"
$stateDir = Join-Path $runtime "state\temporal_client_queue_concurrent_smoke"
$zhPath = Join-Path $zhDir ("temporal_client_queue_concurrent_smoke_{0}.md" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$zhLatest = Join-Path $zhDir "temporal_client_queue_concurrent_smoke_latest.md"
$evidenceJson = Join-Path $evidenceDir ("temporal_client_queue_concurrent_smoke_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
$stateLatest = Join-Path $stateDir "latest.json"
$workDir = Join-Path $stateDir $runId
New-Item -ItemType Directory -Force -Path $zhDir, $evidenceDir, $stateDir, $workDir | Out-Null

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 24), $utf8)
}

function Test-TcpOpen([int]$Port) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(1500, $false)
        if ($ok) { $c.EndConnect($iar); $c.Close(); return $true }
        $c.Close()
    } catch { }
    return $false
}

$taskQueue = "xinao-integrated-langgraph-plugin-queue"
$lockPath = Join-Path $runtime "state\integrated_bus_temporal_client_queue\$taskQueue\submit.lock"
$queueLatest = Join-Path $runtime "state\integrated_bus_temporal_client_queue\$taskQueue\latest.json"
$py = Join-Path $sRepo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { $py = "python" }

$temporalUp = Test-TcpOpen 7233
$preLockExists = Test-Path -LiteralPath $lockPath

$env:XINAO_RESEARCH_RUNTIME = $runtime
$env:PYTHONPATH = $sRepo
if ($AllowEphemeralWorker) {
    $env:XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER = "1"
    $workerMode = "ephemeral_host"
} else {
    $env:XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER = "0"
    $workerMode = "docker_daemon_preferred"
}
$env:XINAO_TEMPORAL_CLIENT_QUEUE = "1"

$verdict = [ordered]@{
    run_id = $runId
    schema_version = "xinao.temporal_client_queue_concurrent_smoke.v1"
    sentinel = "SENTINEL:XINAO_TEMPORAL_CLIENT_QUEUE_CONCURRENT_SMOKE"
    generated_at = $ts
    temporal_up = $temporalUp
    worker_mode = $workerMode
    pre_lock_exists = $preLockExists
    queue_enabled = $true
    lock_path = $lockPath
    queue_latest_path = $queueLatest
    completion_claim_allowed = $false
    smoke_passed = $false
    serialization_verified = $false
    no_dual_workflow_contention = $false
    max_concurrent_lock_holders_observed = 0
    runners = @()
    lock_samples = @()
    errors = @()
}

if (-not $temporalUp) {
    $verdict.errors += "TEMPORAL_7233_DOWN"
    Write-JsonFile $stateLatest $verdict
    Write-JsonFile $evidenceJson $verdict
    if (-not $Quiet) { Write-Host "BLOCKED: temporal 7233 down" }
    exit 2
}

if ($preLockExists) {
    $verdict.errors += "PREEXISTING_SUBMIT_LOCK"
}

# --- launch two concurrent runners ---
$outA = Join-Path $workDir "runner_a_stdout.json"
$outB = Join-Path $workDir "runner_b_stdout.json"
$errA = Join-Path $workDir "runner_a_stderr.txt"
$errB = Join-Path $workDir "runner_b_stderr.txt"
$metaA = Join-Path $workDir "runner_a_meta.json"
$metaB = Join-Path $workDir "runner_b_meta.json"

$pollScript = @'
param($LockPath, $SamplePath, $StopFile, $IntervalMs)
$max = 0
$active = 0
$samples = New-Object System.Collections.Generic.List[object]
while (-not (Test-Path -LiteralPath $StopFile)) {
    $holder = $null
    $exists = Test-Path -LiteralPath $LockPath
    if ($exists) {
        try {
            $raw = Get-Content -LiteralPath $LockPath -Raw -Encoding UTF8
            $holder = $raw | ConvertFrom-Json
        } catch { $holder = @{ parse_error = $true } }
        $active = 1
        if ($active -gt $max) { $max = $active }
    } else {
        $active = 0
    }
    $samples.Add([ordered]@{
        at = (Get-Date).ToString("o")
        lock_exists = $exists
        pid = if ($holder) { $holder.pid } else { $null }
        workflow_id = if ($holder) { $holder.workflow_id } else { $null }
        status = if ($holder) { $holder.status } else { $null }
    })
    Start-Sleep -Milliseconds $IntervalMs
}
@{ max_concurrent_holders = $max; samples = $samples } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $SamplePath -Encoding UTF8
'@

$pollScriptPath = Join-Path $workDir "poll_lock.ps1"
Set-Content -LiteralPath $pollScriptPath -Value $pollScript -Encoding UTF8
$stopPoll = Join-Path $workDir "poll_stop.flag"
$pollOut = Join-Path $workDir "lock_poll.json"
if (Test-Path -LiteralPath $stopPoll) { Remove-Item -LiteralPath $stopPoll -Force }

$pollJob = Start-Job -ScriptBlock {
    param($Script, $Lock, $Out, $Stop, $Ms)
    & $Script -LockPath $Lock -SamplePath $Out -StopFile $Stop -IntervalMs $Ms
} -ArgumentList $pollScriptPath, $lockPath, $pollOut, $stopPoll, 500

$parsePy = @'
import json, re, sys
from pathlib import Path
stdout = Path(sys.argv[1])
meta = Path(sys.argv[2])
tag = sys.argv[3]
started = sys.argv[4]
ended = sys.argv[5]
exit_code = int(sys.argv[6])
raw = stdout.read_text(encoding="utf-8", errors="replace") if stdout.is_file() else ""
workflow_id = None
queue_meta = {}
validation_passed = False
parse_error = ""
if raw.strip():
    try:
        start = raw.find("{")
        depth = 0
        end = None
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        payload = json.loads(raw[start:end])
        workflow_id = payload.get("workflow_id")
        queue_meta = payload.get("temporal_client_queue") or {}
        validation_passed = bool((payload.get("validation") or {}).get("passed"))
    except Exception as exc:
        parse_error = str(exc)
        mwf = re.search(r'"workflow_id": "(xinao-integrated-bus-[^"]+)"', raw)
        if mwf:
            workflow_id = mwf.group(1)
        block = raw[raw.rfind("temporal_client_queue"):]
        mwait = re.search(r'"waited_sec": ([0-9.]+)', block)
        if mwait:
            queue_meta = {"waited_sec": float(mwait.group(1)), "regex_fallback": True}
if parse_error:
    queue_meta = dict(queue_meta)
    queue_meta["parse_error"] = parse_error
meta.write_text(
    json.dumps(
        {
            "tag": tag,
            "started_at": started,
            "ended_at": ended,
            "exit_code": exit_code,
            "workflow_id": workflow_id,
            "validation_passed": validation_passed,
            "temporal_client_queue": queue_meta,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
'@
$parsePyPath = Join-Path $workDir "parse_runner_meta.py"
Set-Content -LiteralPath $parsePyPath -Value $parsePy -Encoding UTF8
$ephemeralFlag = if ($AllowEphemeralWorker) { "1" } else { "0" }

function Start-BusRunnerProcess(
    [string]$Tag,
    [string]$StdoutPath,
    [string]$StderrPath
) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $py
    $psi.Arguments = "-m services.agent_runtime.integrated_bus_runner --temporal"
    $psi.WorkingDirectory = $sRepo
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    $envMap = $psi.EnvironmentVariables
    $envMap["XINAO_RESEARCH_RUNTIME"] = $runtime
    $envMap["PYTHONPATH"] = $sRepo
    $envMap["XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER"] = $ephemeralFlag
    $envMap["XINAO_TEMPORAL_CLIENT_QUEUE"] = "1"
    $proc = [System.Diagnostics.Process]::Start($psi)
    return [ordered]@{
        tag = $Tag
        process = $proc
        stdout_path = $StdoutPath
        stderr_path = $StderrPath
        started_at = (Get-Date).ToString("o")
    }
}

$launchedAt = (Get-Date).ToString("o")

$runnerA = Start-BusRunnerProcess -Tag "a" -StdoutPath $outA -StderrPath $errA
Start-Sleep -Milliseconds 300
$runnerB = Start-BusRunnerProcess -Tag "b" -StdoutPath $outB -StderrPath $errB

if (-not $Quiet) {
    Write-Host "Launched concurrent runners a+b at $launchedAt (worker=$workerMode; pid_a=$($runnerA.process.Id) pid_b=$($runnerB.process.Id))"
    Write-Host "Polling submit.lock every 500ms ..."
}

$runnerA.process.WaitForExit()
$runnerB.process.WaitForExit()
[System.IO.File]::WriteAllText($errA, $runnerA.process.StandardError.ReadToEnd(), $utf8)
[System.IO.File]::WriteAllText($errB, $runnerB.process.StandardError.ReadToEnd(), $utf8)
[System.IO.File]::WriteAllText($outA, $runnerA.process.StandardOutput.ReadToEnd(), $utf8)
[System.IO.File]::WriteAllText($outB, $runnerB.process.StandardOutput.ReadToEnd(), $utf8)
$endedA = (Get-Date).ToString("o")
$endedB = $endedA
& $py $parsePyPath $outA $metaA "a" $runnerA.started_at $endedA $runnerA.process.ExitCode | Out-Null
& $py $parsePyPath $outB $metaB "b" $runnerB.started_at $endedB $runnerB.process.ExitCode | Out-Null
$verdict.runner_pids = @{ a = $runnerA.process.Id; b = $runnerB.process.Id }

New-Item -ItemType File -Path $stopPoll -Force | Out-Null
Wait-Job -Job $pollJob -Timeout 30 | Out-Null
$pollResult = $null
if (Test-Path -LiteralPath $pollOut) {
    try { $pollResult = Get-Content -LiteralPath $pollOut -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}
Remove-Job -Job $pollJob -Force -ErrorAction SilentlyContinue

$metaAObj = $null
$metaBObj = $null
try { $metaAObj = Get-Content -LiteralPath $metaA -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $verdict.errors += "META_A_PARSE_FAIL" }
try { $metaBObj = Get-Content -LiteralPath $metaB -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $verdict.errors += "META_B_PARSE_FAIL" }

$postLockExists = Test-Path -LiteralPath $lockPath
$queueLatestObj = $null
if (Test-Path -LiteralPath $queueLatest) {
    try { $queueLatestObj = Get-Content -LiteralPath $queueLatest -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}

if ($metaAObj) { $verdict.runners += $metaAObj }
if ($metaBObj) { $verdict.runners += $metaBObj }

$waitedSecs = @()
$workflowIds = @()
foreach ($r in $verdict.runners) {
    $q = $r.temporal_client_queue
    if ($q -and $null -ne $q.waited_sec) { $waitedSecs += [double]$q.waited_sec }
    if ($r.workflow_id) { $workflowIds += [string]$r.workflow_id }
}

$oneWaited = ($waitedSecs | Where-Object { $_ -gt 1.0 }).Count -ge 1
$bothAcquired = ($waitedSecs.Count -eq 2)
$distinctWf = ($workflowIds | Select-Object -Unique).Count -eq 2
$lockReleased = (-not $postLockExists)
$latestReleased = ($queueLatestObj -and $queueLatestObj.status -eq "released")

$maxHolders = 0
$pidASamples = 0
$pidBSamples = 0
$foreignHolderSamples = 0
if ($pollResult) {
    $verdict.lock_samples = @($pollResult.samples)
    $maxHolders = [int]$pollResult.max_concurrent_holders
    if ($maxHolders -le 0 -and $verdict.lock_samples.Count -gt 0) {
        $existsSamples = @($verdict.lock_samples | Where-Object { $_.lock_exists })
        $maxHolders = if ($existsSamples.Count -gt 0) { 1 } else { 0 }
    }
    $pidA = [int]$verdict.runner_pids.a
    $pidB = [int]$verdict.runner_pids.b
    foreach ($s in $verdict.lock_samples) {
        if (-not $s.lock_exists) { continue }
        $lpid = [int]$s.pid
        if ($lpid -eq $pidA) { $pidASamples++ }
        elseif ($lpid -eq $pidB) { $pidBSamples++ }
        else { $foreignHolderSamples++ }
    }
}
$verdict.max_concurrent_lock_holders_observed = $maxHolders
$verdict.lock_samples_pid_a = $pidASamples
$verdict.lock_samples_pid_b = $pidBSamples
$verdict.lock_samples_foreign_holder = $foreignHolderSamples
$bothHeldLock = ($pidASamples -gt 0 -and $pidBSamples -gt 0)
$noForeignHolder = ($foreignHolderSamples -eq 0)

$verdict.serialization_verified = (
    $bothAcquired -and $oneWaited -and $lockReleased -and $latestReleased -and
    $maxHolders -le 1 -and $bothHeldLock -and $noForeignHolder
)
$verdict.no_dual_workflow_contention = ($distinctWf -and $verdict.serialization_verified)
$verdict.smoke_passed = ($verdict.serialization_verified -and $verdict.no_dual_workflow_contention -and $verdict.errors.Count -eq 0)
$verdict.post_lock_exists = $postLockExists
$verdict.queue_latest_status = if ($queueLatestObj) { [string]$queueLatestObj.status } else { "missing" }
$verdict.exit_codes = @{ a = $metaAObj.exit_code; b = $metaBObj.exit_code }
$verdict.work_dir = $workDir

Write-JsonFile $stateLatest $verdict
Write-JsonFile $evidenceJson $verdict

$md = @"
# temporal_client_queue 双进程真波烟测

- 时间: $ts
- run_id: $runId
- completion_claim_allowed: **false**
- smoke_passed: **$($verdict.smoke_passed)**

## 前置

| 项 | 值 |
|---|---|
| Temporal 7233 | $($verdict.temporal_up) |
| worker_mode | $workerMode |
| 测前 submit.lock | $($verdict.pre_lock_exists) |
| 测后 submit.lock | $($verdict.post_lock_exists) |
| queue latest status | $($verdict.queue_latest_status) |

## 串行验证

| 断言 | 结果 |
|---|---|
| 两路均拿到 temporal_client_queue | $bothAcquired |
| 至少一路 waited_sec > 1s | $oneWaited (waited=@($waitedSecs -join ', ')) |
| max_concurrent_lock_holders | $maxHolders |
| lock 采样命中 pid_a / pid_b | $pidASamples / $pidBSamples |
| 外来 holder 采样 (docker 等) | $foreignHolderSamples |
| submit.lock 已释放 | $lockReleased |
| 两路 workflow_id 不同 | $distinctWf |
| serialization_verified | $($verdict.serialization_verified) |
| no_dual_workflow_contention | $($verdict.no_dual_workflow_contention) |

## Runner 摘要

### runner a
- exit: $($metaAObj.exit_code)
- workflow_id: $($metaAObj.workflow_id)
- waited_sec: $($metaAObj.temporal_client_queue.waited_sec)
- held_sec: $($metaAObj.temporal_client_queue.held_sec)
- validation_passed: $($metaAObj.validation_passed)

### runner b
- exit: $($metaBObj.exit_code)
- workflow_id: $($metaBObj.workflow_id)
- waited_sec: $($metaBObj.temporal_client_queue.waited_sec)
- held_sec: $($metaBObj.temporal_client_queue.held_sec)
- validation_passed: $($metaBObj.validation_passed)

## 路径

- 证据 JSON: ``$evidenceJson``
- state: ``$stateLatest``
- work_dir: ``$workDir``

## 说明

本烟测只验证 **submit.lock 串行 + 无双 client workflow 争用**；不宣布 333 shape_hot 或 P0 闭合。
"@

Set-Content -LiteralPath $zhPath -Value $md -Encoding UTF8
Set-Content -LiteralPath $zhLatest -Value $md -Encoding UTF8

if (-not $Quiet) {
    Write-Host "smoke_passed=$($verdict.smoke_passed) serialization=$($verdict.serialization_verified) max_holders=$maxHolders"
    Write-Host "zh=$zhPath"
}

if ($verdict.smoke_passed) { exit 0 }
exit 1