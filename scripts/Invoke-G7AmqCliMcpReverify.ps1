#Requires -Version 7.2
<#
.SYNOPSIS
  G7 AMQ/CLI/MCP adversarial re-verify (fresh evidence only).

.DESCRIPTION
  Fresh checks (no service/cli/mcp_server edits):
    1. MCP role binding pytest
    2. T1T2T5 + T6T7T8 canary re-run (isolated DB)
    3. Stop / lease / fencing negative pytest
    4. generation pin: current.json generation_id
    5. prod DB hash before/after canary

  Writes all evidence under:
    D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G7_amq_cli_mcp\
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$ProjectRoot = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination',
    [string]$EvidenceRoot = 'D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G7_amq_cli_mcp',
    [string]$ProdDb = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3',
    [string]$CurrentJson = 'D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\current.json',
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
    if (Test-Path -LiteralPath $CurrentJson -PathType Leaf) {
        try {
            $cur = Get-Content -LiteralPath $CurrentJson -Raw -Encoding UTF8 | ConvertFrom-Json
            $genPy = Join-Path $cur.generation_path 'venv\Scripts\python.exe'
            if (Test-Path -LiteralPath $genPy -PathType Leaf) { return $genPy }
        } catch {
            # fall through
        }
    }
    throw 'PYTHON_NOT_FOUND: project .venv / generation venv missing'
}

function Get-FileSha256Info {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{
            path   = $Path
            exists = $false
            sha256 = $null
            bytes  = $null
        }
    }
    $item = Get-Item -LiteralPath $Path
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return [ordered]@{
        path   = $Path
        exists = $true
        sha256 = $hash
        bytes  = [int64]$item.Length
    }
}

function Invoke-ExternalCapture {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$StdoutPath,
        [string]$StderrPath,
        [int]$TimeoutSec = 600
    )
    $started = (Get-Date).ToUniversalTime().ToString('o')
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    # Quote args that contain spaces
    $quoted = foreach ($a in $ArgumentList) {
        if ($a -match '[\s"]') {
            '"' + ($a -replace '"', '\"') + '"'
        } else {
            $a
        }
    }
    $psi.Arguments = ($quoted -join ' ')
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $exited = $proc.WaitForExit($TimeoutSec * 1000)
    if (-not $exited) {
        try { $proc.Kill($true) } catch { }
        throw "TIMEOUT_AFTER_${TimeoutSec}s: $FilePath $($ArgumentList -join ' ')"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $exitCode = $proc.ExitCode
    $ended = (Get-Date).ToUniversalTime().ToString('o')
    if ($StdoutPath) {
        $dir = Split-Path -Parent $StdoutPath
        if ($dir -and -not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        Set-Content -LiteralPath $StdoutPath -Value $stdout -Encoding UTF8
    }
    if ($StderrPath) {
        $dir = Split-Path -Parent $StderrPath
        if ($dir -and -not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        Set-Content -LiteralPath $StderrPath -Value $stderr -Encoding UTF8
    }
    return [ordered]@{
        started_at_utc = $started
        ended_at_utc   = $ended
        exit_code      = $exitCode
        stdout_path    = $StdoutPath
        stderr_path    = $StderrPath
        stdout_len     = $stdout.Length
        stderr_len     = $stderr.Length
        stdout_tail    = if ($stdout.Length -gt 2000) { $stdout.Substring($stdout.Length - 2000) } else { $stdout }
        stderr_tail    = if ($stderr.Length -gt 1000) { $stderr.Substring($stderr.Length - 1000) } else { $stderr }
    }
}

function Parse-PytestSummary {
    param([string]$Text)
    $passed = $null
    $failed = $null
    $errors = $null
    $skipped = $null
    if ($Text -match '(\d+)\s+passed') { $passed = [int]$Matches[1] }
    if ($Text -match '(\d+)\s+failed') { $failed = [int]$Matches[1] }
    if ($Text -match '(\d+)\s+error') { $errors = [int]$Matches[1] }
    if ($Text -match '(\d+)\s+skipped') { $skipped = [int]$Matches[1] }
    return [ordered]@{
        passed  = $passed
        failed  = $failed
        errors  = $errors
        skipped = $skipped
    }
}

# ---- bootstrap ----
$runStamp = New-IsoStamp
$runId = "g7_reverify_$runStamp"
Write-Step "bootstrap $runId"
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$logsDir = Join-Path $EvidenceRoot 'logs'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

$python = Get-PythonExe -Root $ProjectRoot
Write-Host "python=$python"

$checks = [ordered]@{}
$overallOk = $true

# ---- 4. generation pin (early, independent) ----
Write-Step 'generation pin (current.json)'
$genPinPath = Join-Path $EvidenceRoot 'generation_pin.json'
$genPinOk = $false
$genPin = [ordered]@{
    check              = 'generation_pin'
    pointer_path       = $CurrentJson
    pointer_exists     = (Test-Path -LiteralPath $CurrentJson -PathType Leaf)
    generation_id      = $null
    source_fingerprint = $null
    generation_path    = $null
    updated_at_utc     = $null
    generation_dir_exists = $false
    ok                 = $false
}
if ($genPin.pointer_exists) {
    $cur = Get-Content -LiteralPath $CurrentJson -Raw -Encoding UTF8 | ConvertFrom-Json
    $genPin.generation_id = [string]$cur.generation_id
    $genPin.source_fingerprint = [string]$cur.source_fingerprint
    $genPin.generation_path = [string]$cur.generation_path
    $genPin.updated_at_utc = [string]$cur.updated_at_utc
    $genPin.generation_dir_exists = (
        $genPin.generation_path -and (Test-Path -LiteralPath $genPin.generation_path -PathType Container)
    )
    $genPinOk = (
        -not [string]::IsNullOrWhiteSpace($genPin.generation_id) -and
        $genPin.generation_id -match '^coord-' -and
        $genPin.generation_dir_exists
    )
    $genPin.ok = $genPinOk
}
($genPin | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $genPinPath -Encoding UTF8
$checks['generation_pin'] = [ordered]@{
    id      = 'GEN_PIN'
    name    = 'generation pin: current.json generation_id'
    ok      = $genPinOk
    verdict = if ($genPinOk) { 'PASS' } else { 'FAIL' }
    evidence = $genPinPath
    detail  = [ordered]@{
        generation_id         = $genPin.generation_id
        generation_dir_exists = $genPin.generation_dir_exists
    }
}
if (-not $genPinOk) { $overallOk = $false }

# ---- 5a. prod DB hash BEFORE canary ----
Write-Step 'prod DB hash BEFORE canary'
$prodBeforePath = Join-Path $EvidenceRoot 'prod_db_hash_before.json'
$prodBefore = Get-FileSha256Info -Path $ProdDb
($prodBefore | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $prodBeforePath -Encoding UTF8

# ---- 1. role binding (MCP) ----
Write-Step 'pytest MCP role binding'
$roleStdout = Join-Path $logsDir 'pytest_mcp_role_binding_stdout.txt'
$roleStderr = Join-Path $logsDir 'pytest_mcp_role_binding_stderr.txt'
$roleArgs = @(
    '-m', 'pytest',
    'tests/test_mcp_role_binding.py',
    '-q', '--tb=short'
)
$roleRun = Invoke-ExternalCapture `
    -FilePath $python `
    -ArgumentList $roleArgs `
    -WorkingDirectory $ProjectRoot `
    -StdoutPath $roleStdout `
    -StderrPath $roleStderr `
    -TimeoutSec 300
$roleText = (Get-Content -LiteralPath $roleStdout -Raw -ErrorAction SilentlyContinue) + "`n" +
            (Get-Content -LiteralPath $roleStderr -Raw -ErrorAction SilentlyContinue)
$roleSummary = Parse-PytestSummary -Text $roleText
$roleOk = ($roleRun.exit_code -eq 0)
$roleEvidence = Join-Path $EvidenceRoot 'role_binding_result.json'
$roleResult = [ordered]@{
    check       = 'mcp_role_binding'
    ok          = $roleOk
    exit_code   = $roleRun.exit_code
    pytest      = $roleSummary
    command     = "$python $($roleArgs -join ' ')"
    started_at_utc = $roleRun.started_at_utc
    ended_at_utc   = $roleRun.ended_at_utc
    stdout_path = $roleStdout
    stderr_path = $roleStderr
    stdout_tail = $roleRun.stdout_tail
}
($roleResult | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $roleEvidence -Encoding UTF8
$checks['role_binding'] = [ordered]@{
    id      = 'MCP_ROLE_BINDING'
    name    = 'role binding (MCP)'
    ok      = $roleOk
    verdict = if ($roleOk) { 'PASS' } else { 'FAIL' }
    evidence = $roleEvidence
    detail  = $roleSummary
}
if (-not $roleOk) { $overallOk = $false }

# ---- 3. Stop / lease / fencing negative pytest ----
Write-Step 'pytest Stop/lease/fencing negatives'
$slfStdout = Join-Path $logsDir 'pytest_stop_lease_fencing_stdout.txt'
$slfStderr = Join-Path $logsDir 'pytest_stop_lease_fencing_stderr.txt'
# Focused negative suites: fault injection (lease fence + stop) + task lease fencing + t6t7t8 stop
$slfNodeIds = @(
    'tests/test_t6t7t8_fault_injection.py',
    'tests/test_t6t7t8_vertical_slice.py::test_t8_mbg_dispatch_idempotent_and_stop',
    'tests/test_tasks.py::test_pause_fences_old_worker_and_resume_requeues',
    'tests/test_tasks.py::test_expired_lease_is_recovered_and_fenced',
    'tests/test_tasks.py::test_claim_idempotency_returns_same_lease'
)
$slfArgs = @('-m', 'pytest') + $slfNodeIds + @('-q', '--tb=short')
$slfRun = Invoke-ExternalCapture `
    -FilePath $python `
    -ArgumentList $slfArgs `
    -WorkingDirectory $ProjectRoot `
    -StdoutPath $slfStdout `
    -StderrPath $slfStderr `
    -TimeoutSec 300
$slfText = (Get-Content -LiteralPath $slfStdout -Raw -ErrorAction SilentlyContinue) + "`n" +
           (Get-Content -LiteralPath $slfStderr -Raw -ErrorAction SilentlyContinue)
$slfSummary = Parse-PytestSummary -Text $slfText
$slfOk = ($slfRun.exit_code -eq 0)
$slfEvidence = Join-Path $EvidenceRoot 'stop_lease_fencing_result.json'
$slfResult = [ordered]@{
    check          = 'stop_lease_fencing_negative'
    ok             = $slfOk
    exit_code      = $slfRun.exit_code
    pytest         = $slfSummary
    node_ids       = $slfNodeIds
    command        = "$python $($slfArgs -join ' ')"
    started_at_utc = $slfRun.started_at_utc
    ended_at_utc   = $slfRun.ended_at_utc
    stdout_path    = $slfStdout
    stderr_path    = $slfStderr
    stdout_tail    = $slfRun.stdout_tail
    coverage_cn    = @(
        'wrong lease_token → LeaseError',
        'old lease after mbg_finish → fenced',
        'stop preempts mbg_dispatch',
        'pause fences old worker',
        'expired lease recovered and fenced'
    )
}
($slfResult | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $slfEvidence -Encoding UTF8
$checks['stop_lease_fencing'] = [ordered]@{
    id      = 'STOP_LEASE_FENCING'
    name    = 'Stop/lease/fencing pytest 负测'
    ok      = $slfOk
    verdict = if ($slfOk) { 'PASS' } else { 'FAIL' }
    evidence = $slfEvidence
    detail  = $slfSummary
}
if (-not $slfOk) { $overallOk = $false }

# ---- 2. T1T2T5 canary (isolated DB) ----
Write-Step 'T1T2T5 e2e canary (isolated DB)'
$t125Out = Join-Path $EvidenceRoot 'T1T2T5_e2e_canary.json'
$t125Stdout = Join-Path $logsDir 'T1T2T5_canary_stdout.txt'
$t125Stderr = Join-Path $logsDir 'T1T2T5_canary_stderr.txt'
$t125Script = Join-Path $ProjectRoot 'scripts\Invoke-T1T2T5E2ECanary.ps1'
$t125Args = @(
    '-NoLogo', '-NoProfile', '-NonInteractive',
    '-File', $t125Script,
    '-ProjectRoot', $ProjectRoot,
    '-EvidenceOut', $t125Out,
    '-CanaryRoot', $CanaryRoot,
    '-KeepDb'
)
$t125Run = Invoke-ExternalCapture `
    -FilePath 'pwsh.exe' `
    -ArgumentList $t125Args `
    -WorkingDirectory $ProjectRoot `
    -StdoutPath $t125Stdout `
    -StderrPath $t125Stderr `
    -TimeoutSec 300
$t125Ok = $false
$t125Detail = [ordered]@{ exit_code = $t125Run.exit_code; evidence_exists = $false }
if (Test-Path -LiteralPath $t125Out -PathType Leaf) {
    try {
        $t125Json = Get-Content -LiteralPath $t125Out -Raw -Encoding UTF8 | ConvertFrom-Json
        $t125Ok = [bool]$t125Json.ok -and ($t125Run.exit_code -eq 0)
        $t125Detail.evidence_exists = $true
        $t125Detail.canary_ok = [bool]$t125Json.ok
        $t125Detail.production_path_not_used = $null
        if ($t125Json.PSObject.Properties['hard_bans']) {
            $hb = $t125Json.hard_bans
            if ($hb.PSObject.Properties['production_path_not_used']) {
                $t125Detail.production_path_not_used = [bool]$hb.production_path_not_used
            }
            if ($hb.PSObject.Properties['used_db']) {
                $t125Detail.used_db = [string]$hb.used_db
            }
        }
        if ($t125Json.PSObject.Properties['environment']) {
            $t125Detail.isolated_db = [string]$t125Json.environment.isolated_db
        }
        if ($t125Json.PSObject.Properties['ids']) {
            $t125Detail.ids = $t125Json.ids
        }
        # require isolated DB used
        if ($t125Detail.production_path_not_used -eq $false) { $t125Ok = $false }
        if ($t125Detail.isolated_db -and ($t125Detail.isolated_db -eq $ProdDb)) { $t125Ok = $false }
    } catch {
        $t125Ok = $false
        $t125Detail.parse_error = $_.Exception.Message
    }
}
$checks['T1T2T5_canary'] = [ordered]@{
    id      = 'T1T2T5_E2E'
    name    = 'T1T2T5 canary re-run (isolated DB)'
    ok      = $t125Ok
    verdict = if ($t125Ok) { 'PASS' } else { 'FAIL' }
    evidence = $t125Out
    stdout  = $t125Stdout
    detail  = $t125Detail
}
if (-not $t125Ok) { $overallOk = $false }

# ---- 2b. T6T7T8 canary (isolated DB) ----
Write-Step 'T6T7T8 e2e canary (isolated DB)'
$t678Out = Join-Path $EvidenceRoot 'T6T7T8_e2e_canary.json'
$t678Stdout = Join-Path $logsDir 'T6T7T8_canary_stdout.txt'
$t678Stderr = Join-Path $logsDir 'T6T7T8_canary_stderr.txt'
$t678Script = Join-Path $ProjectRoot 'scripts\Invoke-T6T7T8E2ECanary.ps1'
$t678Args = @(
    '-NoLogo', '-NoProfile', '-NonInteractive',
    '-File', $t678Script,
    '-ProjectRoot', $ProjectRoot,
    '-EvidenceOut', $t678Out,
    '-CanaryRoot', $CanaryRoot,
    '-KeepDb'
)
$t678Run = Invoke-ExternalCapture `
    -FilePath 'pwsh.exe' `
    -ArgumentList $t678Args `
    -WorkingDirectory $ProjectRoot `
    -StdoutPath $t678Stdout `
    -StderrPath $t678Stderr `
    -TimeoutSec 300
$t678Ok = $false
$t678Detail = [ordered]@{ exit_code = $t678Run.exit_code; evidence_exists = $false }
if (Test-Path -LiteralPath $t678Out -PathType Leaf) {
    try {
        $t678Json = Get-Content -LiteralPath $t678Out -Raw -Encoding UTF8 | ConvertFrom-Json
        $t678Ok = [bool]$t678Json.ok -and ($t678Run.exit_code -eq 0)
        $t678Detail.evidence_exists = $true
        $t678Detail.canary_ok = [bool]$t678Json.ok
        if ($t678Json.PSObject.Properties['hard_bans']) {
            $hb = $t678Json.hard_bans
            if ($hb.PSObject.Properties['production_path_not_used']) {
                $t678Detail.production_path_not_used = [bool]$hb.production_path_not_used
            }
            if ($hb.PSObject.Properties['used_db']) {
                $t678Detail.used_db = [string]$hb.used_db
            }
        }
        if ($t678Json.PSObject.Properties['environment']) {
            $t678Detail.isolated_db = [string]$t678Json.environment.isolated_db
        }
        if ($t678Json.PSObject.Properties['ids']) {
            $t678Detail.ids = $t678Json.ids
        }
        if ($t678Detail.production_path_not_used -eq $false) { $t678Ok = $false }
        if ($t678Detail.isolated_db -and ($t678Detail.isolated_db -eq $ProdDb)) { $t678Ok = $false }
    } catch {
        $t678Ok = $false
        $t678Detail.parse_error = $_.Exception.Message
    }
}
$checks['T6T7T8_canary'] = [ordered]@{
    id      = 'T6T7T8_E2E'
    name    = 'T6T7T8 canary re-run (isolated DB)'
    ok      = $t678Ok
    verdict = if ($t678Ok) { 'PASS' } else { 'FAIL' }
    evidence = $t678Out
    stdout  = $t678Stdout
    detail  = $t678Detail
}
if (-not $t678Ok) { $overallOk = $false }

# ---- 5b. prod DB hash AFTER canary ----
Write-Step 'prod DB hash AFTER canary'
$prodAfterPath = Join-Path $EvidenceRoot 'prod_db_hash_after.json'
$prodAfter = Get-FileSha256Info -Path $ProdDb
($prodAfter | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $prodAfterPath -Encoding UTF8

$prodUnchanged = $false
if ($prodBefore.exists -and $prodAfter.exists) {
    $prodUnchanged = ($prodBefore.sha256 -eq $prodAfter.sha256) -and ($prodBefore.bytes -eq $prodAfter.bytes)
} elseif (-not $prodBefore.exists -and -not $prodAfter.exists) {
    # no prod db present both sides → treat as unchanged non-touch (vacuous)
    $prodUnchanged = $true
}
$prodComparePath = Join-Path $EvidenceRoot 'prod_db_hash_compare.json'
$prodCompare = [ordered]@{
    check              = 'prod_db_hash_before_after'
    prod_db            = $ProdDb
    before             = $prodBefore
    after              = $prodAfter
    sha256_unchanged   = $prodUnchanged
    ok                 = $prodUnchanged
    meaning_cn         = 'canary 必须使用隔离 DB；生产库 hash 前后应一致'
}
($prodCompare | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $prodComparePath -Encoding UTF8
$checks['prod_db_hash'] = [ordered]@{
    id      = 'PROD_DB_HASH'
    name    = 'prod DB hash before/after canary'
    ok      = $prodUnchanged
    verdict = if ($prodUnchanged) { 'PASS' } else { 'FAIL' }
    evidence = $prodComparePath
    detail  = [ordered]@{
        before_sha256 = $prodBefore.sha256
        after_sha256  = $prodAfter.sha256
        unchanged     = $prodUnchanged
    }
}
if (-not $prodUnchanged) { $overallOk = $false }

# ---- report ----
Write-Step 'write reverify_report.json'
$reportPath = Join-Path $EvidenceRoot 'reverify_report.json'
$passFailTable = @(
    $checks['role_binding'],
    $checks['T1T2T5_canary'],
    $checks['T6T7T8_canary'],
    $checks['stop_lease_fencing'],
    $checks['generation_pin'],
    $checks['prod_db_hash']
) | ForEach-Object {
    [ordered]@{
        id      = $_.id
        name    = $_.name
        verdict = $_.verdict
        ok      = $_.ok
        evidence = $_.evidence
    }
}

$report = [ordered]@{
    schema_version     = 'xinao.g7_amq_cli_mcp.reverify.v1'
    station            = 'G7_AMQ_CLI_MCP'
    role               = 'adversarial_reverify'
    run_id             = $runId
    generated_at_utc   = (Get-Date).ToUniversalTime().ToString('o')
    project_root       = $ProjectRoot
    evidence_root      = $EvidenceRoot
    python             = $python
    overall_ok         = $overallOk
    overall_verdict    = if ($overallOk) { 'PASS' } else { 'FAIL' }
    hard_bans          = [ordered]@{
        service_cli_mcp_source_edit = 'forbidden'
        live_temporal               = 'forbidden_this_station'
        m_keep                      = 'forbidden_this_station'
        production_db_write         = $ProdDb
    }
    checks             = $checks
    pass_fail_table    = $passFailTable
    artifacts          = [ordered]@{
        reverify_report        = $reportPath
        role_binding           = $roleEvidence
        stop_lease_fencing     = $slfEvidence
        T1T2T5_e2e_canary      = $t125Out
        T6T7T8_e2e_canary      = $t678Out
        generation_pin         = $genPinPath
        prod_db_hash_before    = $prodBeforePath
        prod_db_hash_after     = $prodAfterPath
        prod_db_hash_compare   = $prodComparePath
        logs_dir               = $logsDir
    }
    reverify_script    = 'scripts/Invoke-G7AmqCliMcpReverify.ps1'
}

($report | ConvertTo-Json -Depth 16) | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ''
Write-Host '======== G7 PASS/FAIL TABLE ========' -ForegroundColor Yellow
foreach ($row in $passFailTable) {
    $color = if ($row.ok) { 'Green' } else { 'Red' }
    Write-Host ("[{0}] {1} — {2}" -f $row.verdict, $row.id, $row.name) -ForegroundColor $color
}
Write-Host ("OVERALL: {0}" -f $report.overall_verdict) -ForegroundColor $(if ($overallOk) { 'Green' } else { 'Red' })
Write-Host ("report: {0}" -f $reportPath)

if (-not $overallOk) { exit 1 }
exit 0
