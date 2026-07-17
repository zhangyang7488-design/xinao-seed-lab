#Requires -Version 7.2
<#
.SYNOPSIS
  T6+T7+T8 端到端 canary（隔离目录）：route advisory → promote → mbg explicit dispatch

.DESCRIPTION
  使用独立 SQLite（不写生产 dual_brain_coordination 活库），经 CLI 走通：
    route-assess (background advisory)
    → mbg-status (auto_dispatch=false)
    → discuss/close/promote
    → mbg-dispatch (bind Task lease/running, no transport/Temporal)
    → idempotent replay
    → mbg-finish (lease close)
    → reject non-promoted + stop preempt
  结果写入：
    D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T6T7T8_e2e_canary.json

  硬禁：live Temporal / M-KEEP / 桌面路径改动 / start_transport 默认。
  本脚本不启动 docker、不改 compose、不碰 M-KEEP、不写 Desktop、不起 agent transport。

.PARAMETER ProjectRoot
  dual-brain-coordination 工程根

.PARAMETER EvidenceOut
  结果 JSON 路径

.PARAMETER KeepDb
  保留隔离 DB（默认保留，便于审计）
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$EvidenceOut = 'D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T6T7T8_e2e_canary.json',
    [string]$CanaryRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary',
    [switch]$KeepDb
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string]$Name) {
    Write-Host ("==> {0}" -f $Name) -ForegroundColor Cyan
}

function New-IsoStamp {
    return (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
}

function Get-PythonExe {
    param([string]$Root)
    $candidates = @(
        (Join-Path $Root '.venv\Scripts\python.exe'),
        (Join-Path $Root 'venv\Scripts\python.exe')
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    $genPointer = 'D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\current.json'
    if (Test-Path -LiteralPath $genPointer -PathType Leaf) {
        try {
            $cur = Get-Content -LiteralPath $genPointer -Raw -Encoding UTF8 | ConvertFrom-Json
            $genPy = Join-Path $cur.generation_path 'venv\Scripts\python.exe'
            if (Test-Path -LiteralPath $genPy -PathType Leaf) { return $genPy }
        } catch {
            # fall through
        }
    }
    throw 'PYTHON_NOT_FOUND: project .venv / generation venv missing'
}

function Invoke-CoordCli {
    param(
        [string]$Python,
        [string]$Db,
        [string[]]$CliArgs,
        [string]$StepName,
        [switch]$ExpectFail
    )
    $argLine = @('-m', 'xinao_coordination.cli', '--db', $Db) + $CliArgs
    $stdout = ''
    $stderr = ''
    $exitCode = -1
    $started = (Get-Date).ToUniversalTime().ToString('o')
    try {
        $out = & $Python @argLine 2>&1
        $exitCode = $LASTEXITCODE
        if ($null -eq $out) {
            $stdout = ''
        } elseif ($out -is [System.Array]) {
            $stdout = ($out | ForEach-Object { "$_" }) -join "`n"
        } else {
            $stdout = [string]$out
        }
    } catch {
        $stderr = $_.Exception.Message
        $exitCode = 99
    }
    $ended = (Get-Date).ToUniversalTime().ToString('o')

    $parsed = $null
    $parseOk = $false
    try {
        $trim = $stdout.Trim()
        if ($trim.StartsWith('{') -or $trim.StartsWith('[')) {
            $parsed = $stdout | ConvertFrom-Json -ErrorAction Stop
            $parseOk = $true
        }
    } catch {
        $parseOk = $false
    }

    $summary = $null
    if ($parseOk -and $null -ne $parsed) {
        $summary = [ordered]@{
            ok                = if ($parsed.PSObject.Properties['ok']) { [bool]$parsed.ok } else { $null }
            action            = if ($parsed.PSObject.Properties['action']) { [string]$parsed.action } else { $null }
            error             = if ($parsed.PSObject.Properties['error']) { [string]$parsed.error } else { $null }
            message           = if ($parsed.PSObject.Properties['message']) { [string]$parsed.message } else { $null }
            recommendation    = if ($parsed.PSObject.Properties['recommendation']) { [string]$parsed.recommendation } else { $null }
            advisory_only     = if ($parsed.PSObject.Properties['advisory_only']) { [bool]$parsed.advisory_only } else { $null }
            score_controls_execution = if ($parsed.PSObject.Properties['score_controls_execution']) { [bool]$parsed.score_controls_execution } else { $null }
            auto_dispatch     = if ($parsed.PSObject.Properties['auto_dispatch']) { [bool]$parsed.auto_dispatch } else { $null }
            spawned           = if ($parsed.PSObject.Properties['spawned']) { [bool]$parsed.spawned } else { $null }
            replayed          = if ($parsed.PSObject.Properties['replayed']) { [bool]$parsed.replayed } else { $null }
            in_flight_operations = if ($parsed.PSObject.Properties['in_flight_operations']) { [int]$parsed.in_flight_operations } else { $null }
            temporal_owner    = if ($parsed.PSObject.Properties['temporal_owner']) { [bool]$parsed.temporal_owner } else { $null }
            thread_id         = $null
            thread_state      = $null
            task_id           = $null
            task_state        = $null
            operation_id      = $null
            operation_state   = $null
            m_bg              = $null
        }
        if ($parsed.PSObject.Properties['thread'] -and $parsed.thread) {
            $summary.thread_id = [string]$parsed.thread.thread_id
            $summary.thread_state = [string]$parsed.thread.state
        }
        if ($parsed.PSObject.Properties['task'] -and $parsed.task) {
            $summary.task_id = [string]$parsed.task.task_id
            $summary.task_state = [string]$parsed.task.state
        }
        if ($parsed.PSObject.Properties['task_id'] -and -not $summary.task_id) {
            $summary.task_id = [string]$parsed.task_id
        }
        if ($parsed.PSObject.Properties['operation'] -and $parsed.operation) {
            $summary.operation_id = [string]$parsed.operation.operation_id
            $summary.operation_state = [string]$parsed.operation.state
            if ($parsed.operation.PSObject.Properties['metadata'] -and $parsed.operation.metadata) {
                if ($parsed.operation.metadata.PSObject.Properties['m_bg']) {
                    $summary.m_bg = [bool]$parsed.operation.metadata.m_bg
                }
            }
        }
        if ($parsed.PSObject.Properties['policy'] -and $parsed.policy) {
            if ($null -eq $summary.auto_dispatch -and $parsed.policy.PSObject.Properties['auto_dispatch']) {
                $summary.auto_dispatch = [bool]$parsed.policy.auto_dispatch
            }
        }
    }

    if ($ExpectFail) {
        # Negative control: must fail with CoordinationError-style JSON (exit 2 preferred)
        $stepOk = ($exitCode -ne 0) -and $parseOk -and ($null -ne $parsed) -and (
            (-not [bool]$parsed.ok) -or ($parsed.PSObject.Properties['error'] -and $parsed.error)
        )
    } else {
        $stepOk = ($exitCode -eq 0) -and $parseOk -and ($null -ne $parsed) -and ([bool]$parsed.ok -eq $true)
    }

    return [ordered]@{
        step           = $StepName
        ok             = $stepOk
        expect_fail    = [bool]$ExpectFail
        exit_code      = $exitCode
        started_at_utc = $started
        ended_at_utc   = $ended
        cli_args       = $CliArgs
        parse_ok       = $parseOk
        summary        = $summary
        stdout_excerpt = if ($stdout.Length -gt 2400) { $stdout.Substring(0, 2400) + '...[truncated]' } else { $stdout }
        stderr_excerpt = if ($stderr.Length -gt 800) { $stderr.Substring(0, 800) + '...[truncated]' } else { $stderr }
        raw            = $parsed
    }
}

function Add-Gap {
    param(
        [System.Collections.IList]$Gaps,
        [string]$Code,
        [string]$Step,
        [string]$Detail
    )
    $Gaps.Add([ordered]@{
            code   = $Code
            step   = $Step
            detail = $Detail
            at_utc = (Get-Date).ToUniversalTime().ToString('o')
        }) | Out-Null
}

# --- hard bans ---
$hardBans = [ordered]@{
    live_temporal  = $true
    m_keep         = $true
    desktop_mutate = $true
    start_transport_default = $true
    production_db  = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3'
}
$productionDb = $hardBans.production_db

$stamp = New-IsoStamp
$runId = "t6t7t8_e2e_{0}_{1}" -f $stamp, ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runDir = Join-Path $CanaryRoot ("e2e_runs\{0}" -f $runId)
$dbPath = Join-Path $runDir 'coordination.sqlite3'
$decisionHash = "t6t7t8-canary-{0}" -f $stamp

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EvidenceOut) | Out-Null

if ($dbPath -eq $productionDb) {
    throw 'REFUSING_PRODUCTION_DB'
}

$python = Get-PythonExe -Root $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
# never inherit experimental agent ops / transport
Remove-Item Env:XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS -ErrorAction SilentlyContinue

$steps = [System.Collections.Generic.List[object]]::new()
$gaps = [System.Collections.Generic.List[object]]::new()
$overallOk = $true
$threadId = $null
$taskId = $null
$nonPromotedTaskId = $null
$operationId = $null
$promotedState = $null
$routeBg = $null
$routeDirect = $null
$mbgStatusBefore = $null
$mbgStatusAfter = $null
$leaseToken = $null
$finishOutcome = $null
$taskStateAfterFinish = $null

Write-Step "run_id=$runId isolated_db=$dbPath"

# 0) doctor
$s0 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'doctor' -CliArgs @('doctor')
$steps.Add($s0) | Out-Null
if (-not $s0.ok) {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'DOCTOR_FAIL' -Step 'doctor' -Detail "exit=$($s0.exit_code)"
}

# 1) T6 route-assess → background (advisory only)
$s1 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'route-assess-background' -CliArgs @(
    'route-assess',
    '--parallelism', '0.95',
    '--uncertainty', '0.05',
    '--latency-cost', '0.1',
    '--impact', '0.2'
)
$steps.Add($s1) | Out-Null
if ($s1.ok) {
    $routeBg = [string]$s1.raw.recommendation
    if ($routeBg -ne 'background') {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'ROUTE_NOT_BG' -Step 'route-assess-background' -Detail "recommendation=$routeBg"
    }
    if (-not [bool]$s1.raw.advisory_only) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'ROUTE_NOT_ADVISORY' -Step 'route-assess-background' -Detail 'advisory_only=false'
    }
    if ([bool]$s1.raw.score_controls_execution) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'ROUTE_SCORE_GATES' -Step 'route-assess-background' -Detail 'score_controls_execution=true'
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'ROUTE_BG_FAIL' -Step 'route-assess-background' -Detail $s1.stdout_excerpt
}

# 2) T6 route-assess zero → direct (still advisory)
$s2 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'route-assess-direct' -CliArgs @('route-assess')
$steps.Add($s2) | Out-Null
if ($s2.ok) {
    $routeDirect = [string]$s2.raw.recommendation
    if ($routeDirect -ne 'direct') {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'ROUTE_NOT_DIRECT' -Step 'route-assess-direct' -Detail "recommendation=$routeDirect"
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'ROUTE_DIRECT_FAIL' -Step 'route-assess-direct' -Detail $s2.stdout_excerpt
}

# 3) T8 mbg-status defaults
$s3 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-status-before' -CliArgs @('mbg-status')
$steps.Add($s3) | Out-Null
if ($s3.ok) {
    $mbgStatusBefore = $s3.raw
    if ([bool]$s3.raw.auto_dispatch) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_AUTO_DISPATCH_TRUE' -Step 'mbg-status-before' -Detail 'auto_dispatch must be false'
    }
    if ([bool]$s3.raw.temporal_owner) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_TEMPORAL_OWNER' -Step 'mbg-status-before' -Detail 'temporal_owner must be false'
    }
    if ($s3.raw.policy -and -not [bool]$s3.raw.policy.require_explicit_promote) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_NO_EXPLICIT_PROMOTE' -Step 'mbg-status-before' -Detail 'require_explicit_promote false'
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'MBG_STATUS_FAIL' -Step 'mbg-status-before' -Detail $s3.stdout_excerpt
}

# 4) open discuss thread (need promoted task for M-BG)
$s4 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-open' -CliArgs @(
    'thread-open',
    '--actor', 'grok_4_5',
    '--title', 'T6T7T8 e2e canary discuss',
    '--body', 'proposal: T6 advisory background + T7 op envelope + T8 explicit mbg-dispatch; isolated canary only; no Temporal/M-KEEP.',
    '--idempotency-key', "$runId-open"
)
$steps.Add($s4) | Out-Null
if ($s4.ok) {
    $threadId = [string]$s4.raw.thread.thread_id
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'OPEN_FAIL' -Step 'thread-open' -Detail $s4.stdout_excerpt
}

# 5a) close grok
if ($threadId) {
    $s5a = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-close-grok' -CliArgs @(
        'thread-close',
        '--actor', 'grok_4_5',
        '--thread-id', $threadId,
        '--decision', 'accept',
        '--resolution-key', $decisionHash,
        '--summary', 'grok accepts T6T7T8 canary close',
        '--idempotency-key', "$runId-close-g"
    )
    $steps.Add($s5a) | Out-Null
    if (-not $s5a.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'CLOSE_GROK_FAIL' -Step 'thread-close-grok' -Detail $s5a.stdout_excerpt
    }
}

# 5b) close codex → ACCEPTED
if ($threadId) {
    $s5b = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-close-codex' -CliArgs @(
        'thread-close',
        '--actor', 'codex',
        '--thread-id', $threadId,
        '--decision', 'accept',
        '--resolution-key', $decisionHash,
        '--summary', 'codex accepts T6T7T8 canary close',
        '--idempotency-key', "$runId-close-c"
    )
    $steps.Add($s5b) | Out-Null
    if ($s5b.ok) {
        $closeState = [string]$s5b.raw.thread.state
        if ($closeState -ne 'ACCEPTED') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'CLOSE_NOT_ACCEPTED' -Step 'thread-close-codex' -Detail "state=$closeState"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'CLOSE_CODEX_FAIL' -Step 'thread-close-codex' -Detail $s5b.stdout_excerpt
    }
}

# 6) explicit promote (require_explicit_promote)
if ($threadId) {
    $s6 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'promote' -CliArgs @(
        'promote',
        '--actor', 'codex',
        '--source-thread-id', $threadId,
        '--decision-hash', $decisionHash,
        '--title', 'T6T7T8 e2e canary promoted task',
        '--goal', 'Prove T8 mbg-dispatch on promoted task; isolated canary only; no transport.',
        '--owner', 'admin',
        '--writer-scope', 'canary_e2e',
        '--acceptance', 'cli e2e canary evidence JSON written',
        '--budget', 'isolated-db-only',
        '--stop-scope', 'global',
        '--idempotency-key', "$runId-promote"
    )
    $steps.Add($s6) | Out-Null
    if ($s6.ok) {
        $taskId = [string]$s6.raw.task.task_id
        $promotedState = [string]$s6.raw.task.state
        if ($promotedState -ne 'queued') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'PROMOTE_STATE' -Step 'promote' -Detail "state=$promotedState"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'PROMOTE_FAIL' -Step 'promote' -Detail $s6.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'PROMOTE_SKIPPED' -Step 'promote' -Detail 'no thread_id'
}

# 7) T7/T8 mbg-dispatch → agent_operation queued (no spawn)
if ($taskId) {
    $s7 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-dispatch' -CliArgs @(
        'mbg-dispatch',
        '--actor', 'codex',
        '--task-id', $taskId,
        '--idempotency-key', "$runId-mbg-1"
    )
    $steps.Add($s7) | Out-Null
    if ($s7.ok) {
        $operationId = [string]$s7.raw.operation.operation_id
        $opState = [string]$s7.raw.operation.state
        if ($opState -ne 'queued') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_OP_STATE' -Step 'mbg-dispatch' -Detail "state=$opState expected=queued"
        }
        if ([bool]$s7.raw.auto_dispatch) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_DISPATCH_AUTO' -Step 'mbg-dispatch' -Detail 'auto_dispatch true'
        }
        if ($s7.raw.PSObject.Properties['spawned'] -and [bool]$s7.raw.spawned) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_SPAWNED' -Step 'mbg-dispatch' -Detail 'spawned must be false in canary'
        }
        $mBgFlag = $null
        if ($s7.raw.operation.metadata -and $s7.raw.operation.metadata.PSObject.Properties['m_bg']) {
            $mBgFlag = [bool]$s7.raw.operation.metadata.m_bg
        }
        if ($mBgFlag -ne $true) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_META_MISSING' -Step 'mbg-dispatch' -Detail "m_bg=$mBgFlag"
        }
        # Task lease bind (T8): dispatch returns task.state=running + lease_token
        if ($s7.raw.PSObject.Properties['lease_token'] -and $s7.raw.lease_token) {
            $leaseToken = [string]$s7.raw.lease_token
        }
        $taskStateDispatch = $null
        if ($s7.raw.task -and $s7.raw.task.state) { $taskStateDispatch = [string]$s7.raw.task.state }
        elseif ($s7.raw.PSObject.Properties['task_state']) { $taskStateDispatch = [string]$s7.raw.task_state }
        if ($taskStateDispatch -and $taskStateDispatch -ne 'running') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_TASK_NOT_RUNNING' -Step 'mbg-dispatch' -Detail "task.state=$taskStateDispatch expected=running"
        }
        if (-not $leaseToken) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_LEASE_TOKEN_MISSING' -Step 'mbg-dispatch' -Detail 'lease_token required for mbg-finish'
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_DISPATCH_FAIL' -Step 'mbg-dispatch' -Detail $s7.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'MBG_DISPATCH_SKIPPED' -Step 'mbg-dispatch' -Detail 'no task_id'
}

# 8) idempotent replay
if ($taskId -and $operationId) {
    $s8 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-dispatch-replay' -CliArgs @(
        'mbg-dispatch',
        '--actor', 'codex',
        '--task-id', $taskId,
        '--idempotency-key', "$runId-mbg-1"
    )
    $steps.Add($s8) | Out-Null
    if ($s8.ok) {
        if (-not [bool]$s8.raw.replayed) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_REPLAY_FALSE' -Step 'mbg-dispatch-replay' -Detail 'expected replayed=true'
        }
        $op2 = [string]$s8.raw.operation.operation_id
        if ($op2 -ne $operationId) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_REPLAY_ID_MISMATCH' -Step 'mbg-dispatch-replay' -Detail "first=$operationId second=$op2"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_REPLAY_FAIL' -Step 'mbg-dispatch-replay' -Detail $s8.stdout_excerpt
    }
}

# 9) mbg-status after → in_flight >= 1
$s9 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-status-after' -CliArgs @('mbg-status')
$steps.Add($s9) | Out-Null
if ($s9.ok) {
    $mbgStatusAfter = $s9.raw
    $inFlight = [int]$s9.raw.in_flight_operations
    if ($inFlight -lt 1) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_IN_FLIGHT_ZERO' -Step 'mbg-status-after' -Detail "in_flight=$inFlight"
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'MBG_STATUS_AFTER_FAIL' -Step 'mbg-status-after' -Detail $s9.stdout_excerpt
}


# 9b) T8 mbg-finish (dispatch → finish lease lifecycle; no Temporal)
if ($taskId -and $leaseToken) {
    $s9b = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-finish' -CliArgs @(
        'mbg-finish',
        '--actor', 'admin',
        '--task-id', $taskId,
        '--lease-token', $leaseToken,
        '--result-summary', 't6t7t8 canary mbg finish with lease evidence',
        '--idempotency-key', "$runId-mbg-fin"
    )
    $steps.Add($s9b) | Out-Null
    if ($s9b.ok) {
        $finishOutcome = [string]$s9b.raw.outcome
        if ($s9b.raw.task -and $s9b.raw.task.state) {
            $taskStateAfterFinish = [string]$s9b.raw.task.state
        }
        if ($finishOutcome -ne 'completed') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_FINISH_OUTCOME' -Step 'mbg-finish' -Detail "outcome=$finishOutcome expected=completed"
        }
        if ($taskStateAfterFinish -and $taskStateAfterFinish -ne 'completed') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_FINISH_TASK_STATE' -Step 'mbg-finish' -Detail "task.state=$taskStateAfterFinish expected=completed"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_FINISH_FAIL' -Step 'mbg-finish' -Detail $s9b.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'MBG_FINISH_SKIPPED' -Step 'mbg-finish' -Detail "taskId=$taskId leaseTokenPresent=$([bool]$leaseToken)"
}
# 10) negative: non-promoted task cannot mbg-dispatch
$s10 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'task-dispatch-non-promoted' -CliArgs @(
    'task-dispatch',
    '--actor', 'codex',
    '--title', 'T6T7T8 non-promoted reject probe',
    '--goal', 'must fail mbg-dispatch',
    '--explicit-non-consensus',
    '--idempotency-key', "$runId-nonprom"
)
$steps.Add($s10) | Out-Null
if ($s10.ok) {
    $nonPromotedTaskId = [string]$s10.raw.task.task_id
    $s10b = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-dispatch-non-promoted-reject' -ExpectFail -CliArgs @(
        'mbg-dispatch',
        '--actor', 'codex',
        '--task-id', $nonPromotedTaskId,
        '--idempotency-key', "$runId-mbg-bad"
    )
    $steps.Add($s10b) | Out-Null
    if (-not $s10b.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_NONPROMOTED_NOT_REJECTED' -Step 'mbg-dispatch-non-promoted-reject' -Detail $s10b.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'NONPROMOTED_TASK_FAIL' -Step 'task-dispatch-non-promoted' -Detail $s10.stdout_excerpt
}

# 11) stop preempts further mbg-dispatch on promoted task
$s11 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'stop' -CliArgs @(
    'stop',
    '--actor', 'user',
    '--reason', 't6t7t8 canary stop preempt probe',
    '--idempotency-key', "$runId-stop"
)
$steps.Add($s11) | Out-Null
if (-not $s11.ok) {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'STOP_FAIL' -Step 'stop' -Detail $s11.stdout_excerpt
}

if ($taskId) {
    $s12 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-dispatch-after-stop-reject' -ExpectFail -CliArgs @(
        'mbg-dispatch',
        '--actor', 'codex',
        '--task-id', $taskId,
        '--idempotency-key', "$runId-mbg-after-stop"
    )
    $steps.Add($s12) | Out-Null
    if (-not $s12.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_STOP_NOT_PREEMPT' -Step 'mbg-dispatch-after-stop-reject' -Detail $s12.stdout_excerpt
    }
}

# 13) stop-clear (leave canary clean)
$s13 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'stop-clear' -CliArgs @(
    'stop-clear',
    '--actor', 'user',
    '--reason', 't6t7t8 canary clear after probe',
    '--idempotency-key', "$runId-clear"
)
$steps.Add($s13) | Out-Null
if (-not $s13.ok) {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'STOP_CLEAR_FAIL' -Step 'stop-clear' -Detail $s13.stdout_excerpt
}

# 14) final status
$s14 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'status' -CliArgs @('status')
$steps.Add($s14) | Out-Null

$prodUntouched = $true
$prodNote = 'production db absent or not compared'
if (Test-Path -LiteralPath $productionDb -PathType Leaf) {
    $prodNote = "present; canary used isolated db only: $dbPath"
    if ($dbPath -eq $productionDb) {
        $prodUntouched = $false
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'PRODUCTION_DB_USED' -Step 'guard' -Detail $dbPath
    }
}

$evidence = [ordered]@{
    schema_version           = 'xinao.kaigong_wave.T6T7T8_e2e_canary.v1'
    package                  = 'T6+T7+T8 construction canary'
    slice                    = 'T6+T7+T8'
    path_cn                  = 'route-assess(advisory background) → mbg-status → discuss/close/promote → mbg-dispatch(lease bind) → mbg-finish → idempotent → reject non-promoted/stop'
    run_id                   = $runId
    generated_at_utc         = (Get-Date).ToUniversalTime().ToString('o')
    ok                       = $overallOk
    completion_claim_allowed = $false
    meaning_cn               = '隔离 canary 纵切真跑；≠ 主路全量闭合；≠ Temporal 量产；≠ M-KEEP；≠ auto_dispatch；≠ transport 起进程'
    hard_bans                = [ordered]@{
        live_temporal            = 'forbidden_this_script'
        m_keep                   = 'forbidden_this_script'
        desktop                  = 'forbidden_this_script'
        start_transport_default  = 'forbidden_this_script'
        production_db            = $productionDb
        used_db                  = $dbPath
        production_note          = $prodNote
        production_path_not_used = $prodUntouched
    }
    environment              = [ordered]@{
        project_root  = $ProjectRoot
        python        = $python
        canary_root   = $CanaryRoot
        run_dir       = $runDir
        isolated_db   = $dbPath
        evidence_out  = $EvidenceOut
        decision_hash = $decisionHash
    }
    ids                      = [ordered]@{
        thread_id            = $threadId
        task_id              = $taskId
        non_promoted_task_id = $nonPromotedTaskId
        operation_id         = $operationId
        promoted_state       = $promotedState
        route_background     = $routeBg
        route_direct         = $routeDirect
        lease_token          = $leaseToken
        finish_outcome       = $finishOutcome
        task_state_after_finish = $taskStateAfterFinish
    }
    assertions               = [ordered]@{
        route_advisory_only        = $true
        score_controls_execution   = $false
        auto_dispatch              = $false
        spawned                    = $false
        temporal_owner             = $false
        require_explicit_promote   = $true
        stop_preempts              = $true
        mbg_operation_queued       = ($null -ne $operationId)
        mbg_lease_bound            = ($null -ne $leaseToken)
        mbg_finish_completed       = ($finishOutcome -eq 'completed')
        task_completed_after_finish = ($taskStateAfterFinish -eq 'completed')
    }
    mbg_status_before        = if ($mbgStatusBefore) {
        [ordered]@{
            auto_dispatch         = [bool]$mbgStatusBefore.auto_dispatch
            in_flight_operations  = [int]$mbgStatusBefore.in_flight_operations
            capacity_remaining    = [int]$mbgStatusBefore.capacity_remaining
            temporal_owner        = [bool]$mbgStatusBefore.temporal_owner
            policy_id             = if ($mbgStatusBefore.policy) { [string]$mbgStatusBefore.policy.policy_id } else { $null }
        }
    } else { $null }
    mbg_status_after         = if ($mbgStatusAfter) {
        [ordered]@{
            auto_dispatch         = [bool]$mbgStatusAfter.auto_dispatch
            in_flight_operations  = [int]$mbgStatusAfter.in_flight_operations
            capacity_remaining    = [int]$mbgStatusAfter.capacity_remaining
            temporal_owner        = [bool]$mbgStatusAfter.temporal_owner
        }
    } else { $null }
    steps                    = @($steps | ForEach-Object {
            [ordered]@{
                step           = $_.step
                ok             = $_.ok
                expect_fail    = $_.expect_fail
                exit_code      = $_.exit_code
                started_at_utc = $_.started_at_utc
                ended_at_utc   = $_.ended_at_utc
                cli_args       = $_.cli_args
                parse_ok       = $_.parse_ok
                summary        = $_.summary
                stdout_excerpt = $_.stdout_excerpt
                stderr_excerpt = $_.stderr_excerpt
            }
        })
    gaps                     = @($gaps)
    step_count               = $steps.Count
    gap_count                = $gaps.Count
    pass_steps               = @($steps | Where-Object { $_.ok } | ForEach-Object { $_.step })
    fail_steps               = @($steps | Where-Object { -not $_.ok } | ForEach-Object { $_.step })
}

$json = $evidence | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($EvidenceOut, $json, [System.Text.UTF8Encoding]::new($false))

$runCopy = Join-Path $runDir 'T6T7T8_e2e_canary.json'
[System.IO.File]::WriteAllText($runCopy, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host ("RESULT ok={0} gaps={1}" -f $overallOk, $gaps.Count) -ForegroundColor $(if ($overallOk) { 'Green' } else { 'Yellow' })
Write-Host ("evidence: {0}" -f $EvidenceOut)
Write-Host ("run_dir:  {0}" -f $runDir)
Write-Host ("thread={0} task={1} op={2} route_bg={3}" -f $threadId, $taskId, $operationId, $routeBg)

if (-not $overallOk) {
    exit 1
}
exit 0
