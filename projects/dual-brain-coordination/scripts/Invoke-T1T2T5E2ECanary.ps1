#Requires -Version 7.2
<#
.SYNOPSIS
  T1+T2+T5 端到端 canary（隔离目录）：post/discuss → receipt → close → promote

.DESCRIPTION
  使用独立 SQLite（不写生产 dual_brain_coordination 活库），经 CLI 走通：
    thread-open → thread-post → receipt-record → dual close → promote
  结果写入：
    D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T1T2T5_e2e_canary.json

  硬禁：live Temporal / M-KEEP / 桌面路径改动。
  本脚本不启动 docker、不改 compose、不碰 M-KEEP、不写 Desktop。

.PARAMETER ProjectRoot
  dual-brain-coordination 工程根

.PARAMETER EvidenceOut
  结果 JSON 路径

.PARAMETER KeepDb
  保留隔离 DB（默认保留，便于审计）
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination',
    [string]$EvidenceOut = 'D:\XINAO_RESEARCH_RUNTIME\state\kaigong_wave\T1T2T5_e2e_canary.json',
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
        [string]$StepName
    )
    $argLine = @('-m', 'xinao_coordination.cli', '--db', $Db) + $CliArgs
    $stdout = ''
    $stderr = ''
    $exitCode = -1
    $started = (Get-Date).ToUniversalTime().ToString('o')
    try {
        $psi = @{
            FilePath               = $Python
            ArgumentList           = $argLine
            WorkingDirectory       = $ProjectRoot
            RedirectStandardOutput = $true
            RedirectStandardError  = $true
            PassThru               = $true
            NoNewWindow            = $true
            Wait                   = $true
        }
        # Prefer native call for simpler JSON capture
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
        if ($stdout.Trim().StartsWith('{') -or $stdout.Trim().StartsWith('[')) {
            $parsed = $stdout | ConvertFrom-Json -ErrorAction Stop
            $parseOk = $true
        }
    } catch {
        $parseOk = $false
    }

    $summary = $null
    if ($parseOk -and $null -ne $parsed) {
        # Compact command-output summary (not full dump in top-level narrative)
        $summary = [ordered]@{
            ok             = [bool]($parsed.ok)
            action         = if ($parsed.PSObject.Properties['action']) { [string]$parsed.action } else { $null }
            error          = if ($parsed.PSObject.Properties['error']) { [string]$parsed.error } else { $null }
            message        = if ($parsed.PSObject.Properties['message']) { [string]$parsed.message } else { $null }
            thread_id      = $null
            thread_state   = $null
            message_id     = $null
            task_id        = $null
            task_state     = $null
            decision_hash  = $null
            receipt_type   = $null
            created        = $null
            replayed       = if ($parsed.PSObject.Properties['replayed']) { [bool]$parsed.replayed } else { $null }
        }
        if ($parsed.PSObject.Properties['thread'] -and $parsed.thread) {
            $summary.thread_id = [string]$parsed.thread.thread_id
            $summary.thread_state = [string]$parsed.thread.state
        }
        if ($parsed.PSObject.Properties['message_id']) {
            $summary.message_id = [string]$parsed.message_id
        }
        if ($parsed.PSObject.Properties['task'] -and $parsed.task) {
            $summary.task_id = [string]$parsed.task.task_id
            $summary.task_state = [string]$parsed.task.state
        }
        if ($parsed.PSObject.Properties['decision_hash']) {
            $summary.decision_hash = [string]$parsed.decision_hash
        }
        if ($parsed.PSObject.Properties['item_id']) {
            $summary.message_id = [string]$parsed.item_id
        }
        if ($parsed.PSObject.Properties['receipt_type']) {
            $summary.receipt_type = [string]$parsed.receipt_type
        }
        if ($parsed.PSObject.Properties['created']) {
            $summary.created = [bool]$parsed.created
        }
    }

    $stepOk = ($exitCode -eq 0) -and $parseOk -and ($null -ne $parsed) -and ([bool]$parsed.ok -eq $true)
    return [ordered]@{
        step           = $StepName
        ok             = $stepOk
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
            code       = $Code
            step       = $Step
            detail     = $Detail
            at_utc     = (Get-Date).ToUniversalTime().ToString('o')
        }) | Out-Null
}

# --- hard bans (path / product surface) ---
$hardBans = [ordered]@{
    live_temporal    = $true
    m_keep           = $true
    desktop_mutate   = $true
    production_db    = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3'
}
# Assert we never point --db at production
$productionDb = $hardBans.production_db

$stamp = New-IsoStamp
$runId = "t1t2t5_e2e_{0}_{1}" -f $stamp, ([guid]::NewGuid().ToString('N').Substring(0, 8))
$runDir = Join-Path $CanaryRoot ("e2e_runs\{0}" -f $runId)
$dbPath = Join-Path $runDir 'coordination.sqlite3'
$decisionHash = "t1t2t5-canary-{0}" -f $stamp

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EvidenceOut) | Out-Null

if ([string]::Equals((Resolve-Path -LiteralPath (Split-Path -Parent $dbPath) -ErrorAction SilentlyContinue), (Split-Path -Parent $productionDb))) {
    throw "REFUSING_PRODUCTION_DB_DIR"
}

$python = Get-PythonExe -Root $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
# never inherit experimental agent ops
Remove-Item Env:XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS -ErrorAction SilentlyContinue

$steps = [System.Collections.Generic.List[object]]::new()
$gaps = [System.Collections.Generic.List[object]]::new()
$overallOk = $true
$threadId = $null
$messageId = $null
$taskId = $null
$promotedState = $null

Write-Step "run_id=$runId isolated_db=$dbPath"

# 0) doctor on empty isolated db
$s0 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'doctor' -CliArgs @('doctor')
$steps.Add($s0) | Out-Null
if (-not $s0.ok) {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'DOCTOR_FAIL' -Step 'doctor' -Detail "exit=$($s0.exit_code)"
}

# 1) open discuss thread
$s1 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-open' -CliArgs @(
    'thread-open',
    '--actor', 'grok_4_5',
    '--title', 'T1T2T5 e2e canary discuss',
    '--body', 'proposal: vertical slice post/receipt/close/promote in isolated canary DB only; no Temporal/M-KEEP.',
    '--idempotency-key', "$runId-open"
)
$steps.Add($s1) | Out-Null
if ($s1.ok) {
    $threadId = [string]$s1.raw.thread.thread_id
} else {
    $overallOk = $false
    Add-Gap -Gaps $gaps -Code 'OPEN_FAIL' -Step 'thread-open' -Detail $s1.stdout_excerpt
}

# 2) post (discuss)
if ($threadId) {
    $s2 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-post' -CliArgs @(
        'thread-post',
        '--actor', 'codex',
        '--thread-id', $threadId,
        '--body', 'counter: accept vertical slice plan; promote only after dual close + decision_hash match.',
        '--kind', 'counter',
        '--idempotency-key', "$runId-post"
    )
    $steps.Add($s2) | Out-Null
    if ($s2.ok) {
        $messageId = [string]$s2.raw.message_id
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'POST_FAIL' -Step 'thread-post' -Detail $s2.stdout_excerpt
    }
} else {
    Add-Gap -Gaps $gaps -Code 'POST_SKIPPED' -Step 'thread-post' -Detail 'no thread_id from open'
    $overallOk = $false
}

# 3) receipt (peer observes message; sender cannot self-receipt on broadcast)
if ($messageId) {
    $s3 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'receipt-record' -CliArgs @(
        'receipt-record',
        '--actor', 'grok_4_5',
        '--item-type', 'message',
        '--item-id', $messageId,
        '--receipt-type', 'observed'
    )
    $steps.Add($s3) | Out-Null
    if (-not $s3.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'RECEIPT_FAIL' -Step 'receipt-record' -Detail $s3.stdout_excerpt
    }
} else {
    Add-Gap -Gaps $gaps -Code 'RECEIPT_SKIPPED' -Step 'receipt-record' -Detail 'no message_id from post'
    $overallOk = $false
}

# 4a) close vote grok
if ($threadId) {
    $s4a = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-close-grok' -CliArgs @(
        'thread-close',
        '--actor', 'grok_4_5',
        '--thread-id', $threadId,
        '--decision', 'accept',
        '--resolution-key', $decisionHash,
        '--summary', 'grok accepts T1T2T5 canary close',
        '--idempotency-key', "$runId-close-g"
    )
    $steps.Add($s4a) | Out-Null
    if (-not $s4a.ok) {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'CLOSE_GROK_FAIL' -Step 'thread-close-grok' -Detail $s4a.stdout_excerpt
    }
}

# 4b) close vote codex → ACCEPTED
if ($threadId) {
    $s4b = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'thread-close-codex' -CliArgs @(
        'thread-close',
        '--actor', 'codex',
        '--thread-id', $threadId,
        '--decision', 'accept',
        '--resolution-key', $decisionHash,
        '--summary', 'codex accepts T1T2T5 canary close',
        '--idempotency-key', "$runId-close-c"
    )
    $steps.Add($s4b) | Out-Null
    if ($s4b.ok) {
        $closeState = [string]$s4b.raw.thread.state
        if ($closeState -ne 'ACCEPTED') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'CLOSE_NOT_ACCEPTED' -Step 'thread-close-codex' -Detail "state=$closeState expected=ACCEPTED"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'CLOSE_CODEX_FAIL' -Step 'thread-close-codex' -Detail $s4b.stdout_excerpt
    }
}

# 5) explicit promote (T5 gate; never auto from chat)
if ($threadId) {
    $s5 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'promote' -CliArgs @(
        'promote',
        '--actor', 'codex',
        '--source-thread-id', $threadId,
        '--decision-hash', $decisionHash,
        '--title', 'T1T2T5 e2e canary promoted task',
        '--goal', 'Prove explicit promote after dual accept; isolated canary only.',
        '--owner', 'admin',
        '--writer-scope', 'canary_e2e',
        '--acceptance', 'cli e2e canary evidence JSON written',
        '--budget', 'isolated-db-only',
        '--stop-scope', 'global',
        '--idempotency-key', "$runId-promote"
    )
    $steps.Add($s5) | Out-Null
    if ($s5.ok) {
        $taskId = [string]$s5.raw.task.task_id
        $promotedState = [string]$s5.raw.task.state
        if ($promotedState -ne 'queued') {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'PROMOTE_STATE' -Step 'promote' -Detail "state=$promotedState expected=queued"
        }
        $src = [string]$s5.raw.task.source_thread_id
        if ($src -ne $threadId) {
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'PROMOTE_SOURCE_MISMATCH' -Step 'promote' -Detail "source=$src thread=$threadId"
        }
    } else {
        $overallOk = $false
        Add-Gap -Gaps $gaps -Code 'PROMOTE_FAIL' -Step 'promote' -Detail $s5.stdout_excerpt
    }
} else {
    Add-Gap -Gaps $gaps -Code 'PROMOTE_SKIPPED' -Step 'promote' -Detail 'no thread_id'
    $overallOk = $false
}

# 6) final status snapshot
$s6 = Invoke-CoordCli -Python $python -Db $dbPath -StepName 'status' -CliArgs @('status')
$steps.Add($s6) | Out-Null

# Negative control note: chat must not auto-task (assert promote required) already covered by path.
# Guard: production db file not modified by this run (mtime check best-effort)
$prodUntouched = $true
$prodNote = 'production db absent or not compared'
if (Test-Path -LiteralPath $productionDb -PathType Leaf) {
    try {
        $prodInfo = Get-Item -LiteralPath $productionDb
        # We only assert we never used it as --db; mtime can change from others.
        $prodNote = "present; canary used isolated db only: $dbPath"
        if ($dbPath -eq $productionDb) {
            $prodUntouched = $false
            $overallOk = $false
            Add-Gap -Gaps $gaps -Code 'PRODUCTION_DB_USED' -Step 'guard' -Detail $dbPath
        }
    } catch {
        $prodNote = $_.Exception.Message
    }
}

$evidence = [ordered]@{
    schema_version             = 'xinao.kaigong_wave.T1T2T5_e2e_canary.v1'
    package                    = '4/5 construction writer'
    slice                      = 'T1+T2+T5'
    path_cn                    = 'post/discuss → receipt → close → promote'
    run_id                     = $runId
    generated_at_utc           = (Get-Date).ToUniversalTime().ToString('o')
    ok                         = $overallOk
    completion_claim_allowed   = $false
    meaning_cn                 = '隔离 canary 纵切真跑；≠ 主路全量闭合；≠ Temporal 量产；≠ M-KEEP'
    hard_bans                  = [ordered]@{
        live_temporal  = 'forbidden_this_script'
        m_keep         = 'forbidden_this_script'
        desktop        = 'forbidden_this_script'
        production_db  = $productionDb
        used_db        = $dbPath
        production_note = $prodNote
        production_path_not_used = $prodUntouched
    }
    environment                = [ordered]@{
        project_root   = $ProjectRoot
        python         = $python
        canary_root    = $CanaryRoot
        run_dir        = $runDir
        isolated_db    = $dbPath
        evidence_out   = $EvidenceOut
        decision_hash  = $decisionHash
    }
    ids                        = [ordered]@{
        thread_id      = $threadId
        message_id     = $messageId
        task_id        = $taskId
        promoted_state = $promotedState
    }
    steps                      = @($steps | ForEach-Object {
            # strip full raw from disk narrative to keep file smaller but keep summary + excerpt
            [ordered]@{
                step           = $_.step
                ok             = $_.ok
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
    gaps                       = @($gaps)
    step_count                 = $steps.Count
    gap_count                  = $gaps.Count
    pass_steps                 = @($steps | Where-Object { $_.ok } | ForEach-Object { $_.step })
    fail_steps                 = @($steps | Where-Object { -not $_.ok } | ForEach-Object { $_.step })
}

$json = $evidence | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($EvidenceOut, $json, [System.Text.UTF8Encoding]::new($false))

# also copy under run dir for audit trail
$runCopy = Join-Path $runDir 'T1T2T5_e2e_canary.json'
[System.IO.File]::WriteAllText($runCopy, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host ("RESULT ok={0} gaps={1}" -f $overallOk, $gaps.Count) -ForegroundColor $(if ($overallOk) { 'Green' } else { 'Yellow' })
Write-Host ("evidence: {0}" -f $EvidenceOut)
Write-Host ("run_dir:  {0}" -f $runDir)
Write-Host ("thread={0} message={1} task={2}" -f $threadId, $messageId, $taskId)

if (-not $overallOk) {
    exit 1
}
exit 0
