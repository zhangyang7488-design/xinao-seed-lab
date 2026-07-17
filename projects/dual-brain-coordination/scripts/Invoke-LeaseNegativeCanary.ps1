#Requires -Version 7.2
<#
.SYNOPSIS
  G9 CLI lease negative canary：wrong lease_token 与 old token 必须失败。

.DESCRIPTION
  隔离 SQLite（不写生产 dual_brain_coordination 活库），经 CLI 走通：
    doctor → thread open/close → promote → mbg-dispatch
    → mbg-finish(wrong lease_token) MUST FAIL（task 仍 running）
    → mbg-finish(good lease_token) success
    → mbg-finish(old lease_token) MUST FAIL（fenced）
  证据写入：
    D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G9_lease_neg\

  硬禁：live Temporal / M-KEEP / 桌面路径改动 / start_transport / 改 service|cli|mcp 主源码。

.PARAMETER ProjectRoot
  dual-brain-coordination 工程根

.PARAMETER EvidenceDir
  G9 证据目录

.PARAMETER CanaryRoot
  隔离 canary 运行根
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$EvidenceDir = 'D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G9_lease_neg',
    [string]$CanaryRoot = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary'
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
            ok          = if ($parsed.PSObject.Properties['ok']) { [bool]$parsed.ok } else { $null }
            action      = if ($parsed.PSObject.Properties['action']) { [string]$parsed.action } else { $null }
            error       = if ($parsed.PSObject.Properties['error']) { [string]$parsed.error } else { $null }
            message     = if ($parsed.PSObject.Properties['message']) { [string]$parsed.message } else { $null }
            outcome     = if ($parsed.PSObject.Properties['outcome']) { [string]$parsed.outcome } else { $null }
            lease_token = if ($parsed.PSObject.Properties['lease_token'] -and $parsed.lease_token) { [string]$parsed.lease_token } else { $null }
            thread_id   = $null
            thread_state = $null
            task_id     = $null
            task_state  = $null
            operation_id = $null
            operation_state = $null
        }
        if ($parsed.PSObject.Properties['thread'] -and $parsed.thread) {
            $summary.thread_id = [string]$parsed.thread.thread_id
            $summary.thread_state = [string]$parsed.thread.state
        }
        if ($parsed.PSObject.Properties['task'] -and $parsed.task) {
            $summary.task_id = [string]$parsed.task.task_id
            $summary.task_state = [string]$parsed.task.state
            if (-not $summary.lease_token -and $parsed.task.PSObject.Properties['lease_token'] -and $parsed.task.lease_token) {
                $summary.lease_token = [string]$parsed.task.lease_token
            }
        }
        if ($parsed.PSObject.Properties['operation'] -and $parsed.operation) {
            $summary.operation_id = [string]$parsed.operation.operation_id
            $summary.operation_state = [string]$parsed.operation.state
        }
    }

    if ($ExpectFail) {
        # Negative: non-zero exit preferred; ok=false or error present also counts
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
$productionDb = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3'
$stamp = New-IsoStamp
$runId = "g9_lease_neg_{0}_{1}" -f $stamp, ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runDir = Join-Path $CanaryRoot ("e2e_runs\{0}" -f $runId)
$dbPath = Join-Path $runDir 'coordination.sqlite3'
$decisionHash = "g9-lease-neg-{0}" -f $stamp
$scratchRoot = Join-Path $runDir 'mbg_scratch'
$EvidenceOut = Join-Path $EvidenceDir 'G9_lease_neg_latest.json'
$EvidenceRun = Join-Path $EvidenceDir ("G9_lease_neg_{0}.json" -f $stamp)

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
New-Item -ItemType Directory -Force -Path $scratchRoot | Out-Null

if ($dbPath -eq $productionDb) {
    throw 'REFUSING_PRODUCTION_DB'
}

$python = Get-PythonExe -Root $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
$env:XINAO_MBG_SCRATCH_ROOT = $scratchRoot
Remove-Item Env:XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS -ErrorAction SilentlyContinue
Remove-Item Env:XINAO_TEMPORAL_LIVE -ErrorAction SilentlyContinue

$steps = [System.Collections.Generic.List[object]]::new()
$gaps = [System.Collections.Generic.List[object]]::new()
$overallOk = $true
$threadId = $null
$taskId = $null
$operationId = $null
$goodLease = $null
$wrongLease = $null
$taskStateAfterWrong = $null
$leaseAfterWrong = $null
$finishOutcome = $null
$taskStateAfterFinish = $null
$taskStateAfterOld = $null
$leaseAfterOld = $null

Write-Step "run_id=$runId isolated_db=$dbPath"

# 0) doctor
$s0 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'doctor' -CliArgs @('doctor')
$steps.Add($s0) | Out-Null
if (-not $s0.ok) {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'DOCTOR_FAIL' -Step 'doctor' -Detail "exit=$($s0.exit_code)"
}

# 1) open discuss
$s1 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-open' -CliArgs @(
    'thread-open',
    '--actor', 'grok_4_5',
    '--title', 'G9 lease negative canary',
    '--body', 'G9: wrong lease_token and old token after finish must fail via CLI.',
    '--idempotency-key', "$runId-open"
)
$steps.Add($s1) | Out-Null
if ($s1.ok) {
    $threadId = [string]$s1.raw.thread.thread_id
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'OPEN_FAIL' -Step 'thread-open' -Detail $s1.stdout_excerpt
}

# 2) close grok
if ($threadId) {
    $s2 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-close-grok' -CliArgs @(
        'thread-close',
        '--actor', 'grok_4_5',
        '--thread-id', $threadId,
        '--decision', 'accept',
        '--resolution-key', $decisionHash,
        '--summary', 'grok accepts G9 lease neg canary',
        '--idempotency-key', "$runId-close-g"
    )
    $steps.Add($s2) | Out-Null
    if (-not $s2.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'CLOSE_GROK_FAIL' -Step 'thread-close-grok' -Detail $s2.stdout_excerpt
    }
}

# 3) close codex → ACCEPTED
if ($threadId) {
    $s3 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-close-codex' -CliArgs @(
        'thread-close',
        '--actor', 'codex',
        '--thread-id', $threadId,
        '--decision', 'accept',
        '--resolution-key', $decisionHash,
        '--summary', 'codex accepts G9 lease neg canary',
        '--idempotency-key', "$runId-close-c"
    )
    $steps.Add($s3) | Out-Null
    if ($s3.ok) {
        $closeState = [string]$s3.raw.thread.state
        if ($closeState -ne 'ACCEPTED') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'CLOSE_NOT_ACCEPTED' -Step 'thread-close-codex' -Detail "state=$closeState"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'CLOSE_CODEX_FAIL' -Step 'thread-close-codex' -Detail $s3.stdout_excerpt
    }
}

# 4) promote
if ($threadId) {
    $s4 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'promote' -CliArgs @(
        'promote',
        '--actor', 'codex',
        '--source-thread-id', $threadId,
        '--decision-hash', $decisionHash,
        '--title', 'G9 lease negative canary task',
        '--goal', 'Prove wrong/old lease_token rejected on mbg-finish; isolated canary only.',
        '--owner', 'admin',
        '--writer-scope', 'canary_g9_lease_neg',
        '--acceptance', 'G9 lease neg evidence JSON',
        '--budget', 'isolated-db-only',
        '--stop-scope', 'global',
        '--idempotency-key', "$runId-promote"
    )
    $steps.Add($s4) | Out-Null
    if ($s4.ok) {
        $taskId = [string]$s4.raw.task.task_id
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'PROMOTE_FAIL' -Step 'promote' -Detail $s4.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'PROMOTE_SKIPPED' -Step 'promote' -Detail 'no thread_id'
}

# 5) mbg-dispatch → lease bind
if ($taskId) {
    $s5 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-dispatch' -CliArgs @(
        'mbg-dispatch',
        '--actor', 'codex',
        '--task-id', $taskId,
        '--idempotency-key', "$runId-mbg"
    )
    $steps.Add($s5) | Out-Null
    if ($s5.ok) {
        if ($s5.raw.PSObject.Properties['operation'] -and $s5.raw.operation) {
            $operationId = [string]$s5.raw.operation.operation_id
        }
        if ($s5.raw.PSObject.Properties['lease_token'] -and $s5.raw.lease_token) {
            $goodLease = [string]$s5.raw.lease_token
        } elseif ($s5.raw.task -and $s5.raw.task.lease_token) {
            $goodLease = [string]$s5.raw.task.lease_token
        }
        $taskStateDispatch = $null
        if ($s5.raw.task -and $s5.raw.task.state) { $taskStateDispatch = [string]$s5.raw.task.state }
        if ($taskStateDispatch -and $taskStateDispatch -ne 'running') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_TASK_NOT_RUNNING' -Step 'mbg-dispatch' -Detail "task.state=$taskStateDispatch"
        }
        if (-not $goodLease) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_LEASE_TOKEN_MISSING' -Step 'mbg-dispatch' -Detail 'lease_token required'
        } else {
            $wrongLease = "wrong-$goodLease"
        }
        if ($s5.raw.PSObject.Properties['spawned'] -and [bool]$s5.raw.spawned) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'MBG_SPAWNED' -Step 'mbg-dispatch' -Detail 'spawned must be false'
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'MBG_DISPATCH_FAIL' -Step 'mbg-dispatch' -Detail $s5.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'MBG_DISPATCH_SKIPPED' -Step 'mbg-dispatch' -Detail 'no task_id'
}

# 6) NEGATIVE: mbg-finish with wrong lease_token MUST FAIL
if ($taskId -and $wrongLease) {
    Write-Step 'mbg-finish-wrong-token (expect FAIL)'
    $s6 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-finish-wrong-token' -ExpectFail -CliArgs @(
        'mbg-finish',
        '--actor', 'admin',
        '--task-id', $taskId,
        '--lease-token', $wrongLease,
        '--result-summary', 'G9 wrong lease must be rejected',
        '--idempotency-key', "$runId-fin-wrong"
    )
    $steps.Add($s6) | Out-Null
    if (-not $s6.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'WRONG_TOKEN_NOT_REJECTED' -Step 'mbg-finish-wrong-token' -Detail $s6.stdout_excerpt
    } else {
        # Confirm LeaseError-ish wording when present
        $errText = ''
        if ($s6.summary -and $s6.summary.error) { $errText = [string]$s6.summary.error }
        elseif ($s6.summary -and $s6.summary.message) { $errText = [string]$s6.summary.message }
        else { $errText = [string]$s6.stdout_excerpt }
        if ($errText -and ($errText -notmatch '(?i)lease|token|fence|match|invalid')) {
            # still ok if exit non-zero + not ok — soft note only
            Write-Host ("WARN wrong-token error text weak: {0}" -f $errText) -ForegroundColor Yellow
        }
    }

    # task must still be running with good lease
    $s6b = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'task-get-after-wrong' -CliArgs @(
        'task-get',
        '--task-id', $taskId
    )
    $steps.Add($s6b) | Out-Null
    if ($s6b.ok) {
        if ($s6b.raw.task) {
            $taskStateAfterWrong = [string]$s6b.raw.task.state
            if ($s6b.raw.task.PSObject.Properties['lease_token'] -and $s6b.raw.task.lease_token) {
                $leaseAfterWrong = [string]$s6b.raw.task.lease_token
            }
        } elseif ($s6b.raw.PSObject.Properties['state']) {
            $taskStateAfterWrong = [string]$s6b.raw.state
        }
        if ($taskStateAfterWrong -ne 'running') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'WRONG_TOKEN_STATE_DRIFT' -Step 'task-get-after-wrong' -Detail "state=$taskStateAfterWrong expected=running"
        }
        if ($goodLease -and $leaseAfterWrong -and ($leaseAfterWrong -ne $goodLease)) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'WRONG_TOKEN_LEASE_DRIFT' -Step 'task-get-after-wrong' -Detail "lease mutated after wrong finish"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'TASK_GET_AFTER_WRONG_FAIL' -Step 'task-get-after-wrong' -Detail $s6b.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'WRONG_TOKEN_SKIPPED' -Step 'mbg-finish-wrong-token' -Detail "taskId=$taskId wrongLeasePresent=$([bool]$wrongLease)"
}

# 7) POSITIVE: mbg-finish with good lease succeeds
if ($taskId -and $goodLease) {
    Write-Step 'mbg-finish-good-token (expect OK)'
    $s7 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-finish-good-token' -CliArgs @(
        'mbg-finish',
        '--actor', 'admin',
        '--task-id', $taskId,
        '--lease-token', $goodLease,
        '--result-summary', 'G9 good lease finish after wrong-token probe',
        '--idempotency-key', "$runId-fin-good"
    )
    $steps.Add($s7) | Out-Null
    if ($s7.ok) {
        $finishOutcome = if ($s7.raw.PSObject.Properties['outcome']) { [string]$s7.raw.outcome } else { $null }
        if ($s7.raw.task -and $s7.raw.task.state) {
            $taskStateAfterFinish = [string]$s7.raw.task.state
        }
        if ($finishOutcome -ne 'completed') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'GOOD_FINISH_OUTCOME' -Step 'mbg-finish-good-token' -Detail "outcome=$finishOutcome"
        }
        if ($taskStateAfterFinish -and $taskStateAfterFinish -ne 'completed') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'GOOD_FINISH_TASK_STATE' -Step 'mbg-finish-good-token' -Detail "state=$taskStateAfterFinish"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'GOOD_FINISH_FAIL' -Step 'mbg-finish-good-token' -Detail $s7.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'GOOD_FINISH_SKIPPED' -Step 'mbg-finish-good-token' -Detail 'missing task/lease'
}

# 8) NEGATIVE: mbg-finish with OLD token after finish MUST FAIL (fenced)
if ($taskId -and $goodLease) {
    Write-Step 'mbg-finish-old-token (expect FAIL)'
    $s8 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-finish-old-token' -ExpectFail -CliArgs @(
        'mbg-finish',
        '--actor', 'admin',
        '--task-id', $taskId,
        '--lease-token', $goodLease,
        '--result-summary', 'G9 old lease reuse must be rejected',
        '--idempotency-key', "$runId-fin-old"
    )
    $steps.Add($s8) | Out-Null
    if (-not $s8.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'OLD_TOKEN_NOT_REJECTED' -Step 'mbg-finish-old-token' -Detail $s8.stdout_excerpt
    }

    # also reject old token on fail path
    $s8b = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'mbg-finish-old-token-fail-path' -ExpectFail -CliArgs @(
        'mbg-finish',
        '--actor', 'admin',
        '--task-id', $taskId,
        '--lease-token', $goodLease,
        '--result-summary', 'G9 old lease fail-path reuse must be rejected',
        '--fail',
        '--idempotency-key', "$runId-fin-old-fail"
    )
    $steps.Add($s8b) | Out-Null
    if (-not $s8b.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'OLD_TOKEN_FAIL_PATH_NOT_REJECTED' -Step 'mbg-finish-old-token-fail-path' -Detail $s8b.stdout_excerpt
    }

    $s8c = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'task-get-after-old' -CliArgs @(
        'task-get',
        '--task-id', $taskId
    )
    $steps.Add($s8c) | Out-Null
    if ($s8c.ok) {
        if ($s8c.raw.task) {
            $taskStateAfterOld = [string]$s8c.raw.task.state
            if ($s8c.raw.task.PSObject.Properties['lease_token'] -and $null -ne $s8c.raw.task.lease_token) {
                $leaseAfterOld = [string]$s8c.raw.task.lease_token
            } else {
                $leaseAfterOld = $null
            }
        }
        if ($taskStateAfterOld -ne 'completed') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'OLD_TOKEN_STATE_DRIFT' -Step 'task-get-after-old' -Detail "state=$taskStateAfterOld expected=completed"
        }
        if ($null -ne $leaseAfterOld -and $leaseAfterOld -ne '') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'OLD_TOKEN_LEASE_STILL_SET' -Step 'task-get-after-old' -Detail "lease_token=$leaseAfterOld expected=null"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'TASK_GET_AFTER_OLD_FAIL' -Step 'task-get-after-old' -Detail $s8c.stdout_excerpt
    }
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'OLD_TOKEN_SKIPPED' -Step 'mbg-finish-old-token' -Detail 'missing task/lease'
}

# 9) final status
$s9 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'status' -CliArgs @('status')
$steps.Add($s9) | Out-Null

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

$wrongRejected = $false
$oldRejected = $false
$oldFailRejected = $false
foreach ($st in $steps) {
    if ($st.step -eq 'mbg-finish-wrong-token' -and $st.ok -and $st.expect_fail) { $wrongRejected = $true }
    if ($st.step -eq 'mbg-finish-old-token' -and $st.ok -and $st.expect_fail) { $oldRejected = $true }
    if ($st.step -eq 'mbg-finish-old-token-fail-path' -and $st.ok -and $st.expect_fail) { $oldFailRejected = $true }
}

$evidence = [ordered]@{
    schema_version           = 'xinao.saturation.G9_lease_neg.v1'
    package                  = 'G9 CLI lease negative canary'
    station                  = 'G9'
    slice                    = 'lease-fencing'
    path_cn                  = 'promote → mbg-dispatch → mbg-finish(wrong token FAIL) → mbg-finish(good) → mbg-finish(old token FAIL)'
    run_id                   = $runId
    generated_at_utc         = (Get-Date).ToUniversalTime().ToString('o')
    ok                       = $overallOk
    completion_claim_allowed = $false
    meaning_cn               = '隔离 CLI 负测：wrong/old lease_token 必须被拒绝；≠ Temporal 量产；≠ 主库；≠ transport'
    hard_bans                = [ordered]@{
        live_temporal            = 'forbidden_this_script'
        m_keep                   = 'forbidden_this_script'
        desktop                  = 'forbidden_this_script'
        start_transport_default  = 'forbidden_this_script'
        service_cli_mcp_src      = 'forbidden_this_script'
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
        evidence_dir  = $EvidenceDir
        evidence_out  = $EvidenceOut
        evidence_run  = $EvidenceRun
        decision_hash = $decisionHash
        scratch_root  = $scratchRoot
    }
    ids                      = [ordered]@{
        thread_id              = $threadId
        task_id                = $taskId
        operation_id           = $operationId
        good_lease_token       = $goodLease
        wrong_lease_token      = $wrongLease
        task_state_after_wrong = $taskStateAfterWrong
        lease_after_wrong      = $leaseAfterWrong
        finish_outcome         = $finishOutcome
        task_state_after_finish = $taskStateAfterFinish
        task_state_after_old   = $taskStateAfterOld
        lease_after_old        = $leaseAfterOld
    }
    assertions               = [ordered]@{
        wrong_lease_token_rejected     = $wrongRejected
        task_still_running_after_wrong = ($taskStateAfterWrong -eq 'running')
        good_finish_completed          = ($finishOutcome -eq 'completed')
        old_lease_token_rejected       = $oldRejected
        old_token_fail_path_rejected   = $oldFailRejected
        task_completed_after_old_probe = ($taskStateAfterOld -eq 'completed')
        lease_cleared_after_finish     = ($null -eq $leaseAfterOld -or $leaseAfterOld -eq '')
        isolated_db_only               = $prodUntouched
    }
    steps                    = @($steps | ForEach-Object {
            [ordered]@{
                step           = $_.step
                ok             = $_.ok
                expect_fail    = $_.expect_fail
                exit_code      = $_.exit_code
                started_at_utc = $_.started_at_utc
                ended_at_utc   = $_.ended_at_utc
                cli_args       = @(
                    # redact full lease tokens in args for safety; keep prefix
                    foreach ($a in $_.cli_args) {
                        if ($goodLease -and $a -eq $goodLease) { '<GOOD_LEASE_REDACTED>' }
                        elseif ($wrongLease -and $a -eq $wrongLease) { '<WRONG_LEASE_REDACTED>' }
                        else { $a }
                    }
                )
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
[System.IO.File]::WriteAllText($EvidenceRun, $json, [System.Text.UTF8Encoding]::new($false))
$runCopy = Join-Path $runDir 'G9_lease_neg.json'
[System.IO.File]::WriteAllText($runCopy, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host ("RESULT ok={0} gaps={1}" -f $overallOk, $gaps.Count) -ForegroundColor $(if ($overallOk) { 'Green' } else { 'Yellow' })
Write-Host ("evidence: {0}" -f $EvidenceOut)
Write-Host ("run_copy:  {0}" -f $EvidenceRun)
Write-Host ("run_dir:   {0}" -f $runDir)
Write-Host ("wrong_rejected={0} old_rejected={1} finish={2}" -f $wrongRejected, $oldRejected, $finishOutcome)

if (-not $overallOk) {
    exit 1
}
exit 0
