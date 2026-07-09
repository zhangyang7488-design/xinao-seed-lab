[CmdletBinding()]
param(
    [string]$UserFocusCn = "",
    [ValidateSet("B", "C", "DP", "BC", "BDP", "BCDP", "All")]
    [string]$Summon = "BDP",
    [switch]$SkipEvidenceCollection,
    [switch]$WaitForReports,
    [switch]$WaitForSemantic,
    [switch]$Async,
    [int]$WaitSec = 300,
    [string]$ConfigPath = "",
    [string]$AuditorsPath = "",
    [string]$DivisionPath = ""
)

$ErrorActionPreference = "Stop"
$GrokBridgeRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
if (-not $ConfigPath) { $ConfigPath = Join-Path $GrokBridgeRoot "bridge.config.json" }
if (-not $AuditorsPath) { $AuditorsPath = Join-Path $GrokBridgeRoot "parallel_global_audit_auditors.json" }
if (-not $DivisionPath) { $DivisionPath = Join-Path $GrokBridgeRoot "grok_parallel_audit_division.v1.json" }
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

function Read-JsonFile {
    param([string]$Path)
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $raw = [System.IO.File]::ReadAllText($Path, $utf8)
    $raw | ConvertFrom-Json
}

function Expand-SummonList {
    param([string]$Token)
    switch ($Token) {
        "B" { return @("B") }
        "C" { return @("C") }
        "DP" { return @("DP") }
        "BC" { return @("B", "C") }
        "BDP" { return @("B", "DP") }
        "BCDP" { return @("B", "C", "DP") }
        "All" { return @("B", "C", "DP") }
        default { throw "UNKNOWN_SUMMON_TOKEN:$Token" }
    }
}

function Invoke-GrokAuditWorker {
    param(
        [string]$Python,
        [string[]]$WorkerArgs,
        [bool]$Wait,
        [string]$StdoutLog,
        [string]$StderrLog
    )
    if ($Wait) {
        & $Python @WorkerArgs
        return @{
            mode = "sync_observe"
            exit_code = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
            process_id = $null
        }
    }
    $proc = Start-Process `
        -FilePath $Python `
        -ArgumentList $WorkerArgs `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog
    return @{
        mode = "detached_process"
        exit_code = $null
        process_id = $proc.Id
    }
}

$config = Read-JsonFile -Path $ConfigPath
$auditorsConfig = Read-JsonFile -Path $AuditorsPath
$division = $null
if (Test-Path -LiteralPath $DivisionPath) {
    $division = Read-JsonFile -Path $DivisionPath
}
$runtimeRoot = [string]$config.runtime_root
if (-not $runtimeRoot) { $runtimeRoot = "D:\XINAO_CLEAN_RUNTIME" }

# Default: sync invoke + local observe. Use -Async only when caller explicitly wants fire-and-forget.
$waitAll = (-not $Async) -or $WaitForReports -or $WaitForSemantic

$codexAPanel = $null
$codexATurnRunning = $false
try {
    if ($config.ingress_base_url) {
        $rb = Invoke-WebRequest -Uri ($config.ingress_base_url.TrimEnd('/') + "/codex-a/panel-readback") -UseBasicParsing -TimeoutSec 10
        $codexAPanel = ($rb.Content | ConvertFrom-Json).state
        $codexATurnRunning = ($codexAPanel.turn_status -eq "RUNNING")
    }
} catch {}

if ($codexATurnRunning -and $waitAll -and -not $PSBoundParameters.ContainsKey('Async')) {
    Write-Warning "CODEX_A_TURN_RUNNING: switching to detached_process; use Get-GrokLocalObserve.ps1 to watch"
    $waitAll = $false
}

$now = Get-Date
$ticketId = "grok_parallel_global_audit_{0}" -f $now.ToString("yyyyMMdd_HHmmss")
$artifactRoot = Join-Path $runtimeRoot "artifacts\generated\grok_parallel_global_audit\$ticketId"
$stateDir = Join-Path $runtimeRoot "state\grok_parallel_global_audit"
$observeRoot = Join-Path $runtimeRoot "state\grok_local_observe\$ticketId"
New-Item -ItemType Directory -Force -Path $artifactRoot, $stateDir, $observeRoot | Out-Null
@{
    schema_version = "xinao.grok_local_observe.ticket.v1"
    ticket_id = $ticketId
    generated_at = (Get-Date).ToString("o")
    observe_root = $observeRoot
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path (Split-Path $observeRoot -Parent) "latest_ticket.json") -Encoding UTF8

$evidencePath = Join-Path $runtimeRoot "state\grok_global_human_audit\latest.json"
if (-not $SkipEvidenceCollection) {
    $auditScript = Join-Path $GrokBridgeRoot "Invoke-GrokGlobalHumanAudit.ps1"
    $evidenceJson = & $auditScript -RuntimeRoot $runtimeRoot | Out-String
    $evidencePath = Join-Path $runtimeRoot "state\grok_global_human_audit\latest.json"
    if (-not (Test-Path -LiteralPath $evidencePath)) {
        $evidencePath = Join-Path $artifactRoot "grok_evidence.snapshot.json"
        $evidenceJson | Set-Content -LiteralPath $evidencePath -Encoding UTF8
    }
}

$currentIntentId = "unknown"
try {
    if (Test-Path -LiteralPath $config.intent_state_ref) {
        $admitted = Get-Content -LiteralPath $config.intent_state_ref -Raw | ConvertFrom-Json
        if ($admitted.current_intent_id) { $currentIntentId = [string]$admitted.current_intent_id }
    }
} catch {}

$summonList = Expand-SummonList -Token $Summon
$dispatches = [System.Collections.Generic.List[object]]::new()
$namedBlockers = [System.Collections.Generic.List[string]]::new()
$python = [string]$config.ucp_python
$timeout = [Math]::Max(60, $WaitSec)

foreach ($code in $summonList) {
    $auditor = $auditorsConfig.auditors.$code
    if (-not $auditor) {
        $namedBlockers.Add("UNKNOWN_AUDITOR_$code")
        continue
    }

    $role = [string]$auditor.role
    $reportPath = Join-Path $artifactRoot ("{0}.report.json" -f $role)
    $workerRel = [string]$auditor.worker_script
    $workerScript = if ($workerRel -match '^[A-Za-z]:\\') {
        $workerRel
    } else {
        Join-Path $GrokBridgeRoot (Split-Path $workerRel -Leaf)
    }

    $dispatchRecord = [ordered]@{
        auditor_code = $code
        role = $role
        label_cn = [string]$auditor.label_cn
        carrier = [string]$auditor.carrier
        visible_window = $false
        status = "pending"
        started_at = $now.ToString("o")
        report_path_expected = $reportPath
    }

    if (-not (Test-Path -LiteralPath $python)) {
        $dispatchRecord.status = "route_missing"
        $dispatchRecord.named_blocker = "PYTHON_RUNTIME_MISSING"
        $namedBlockers.Add("PYTHON_RUNTIME_MISSING")
        $dispatches.Add([pscustomobject]$dispatchRecord)
        continue
    }
    if (-not (Test-Path -LiteralPath $workerScript)) {
        $dispatchRecord.status = "route_missing"
        $dispatchRecord.named_blocker = "WORKER_SCRIPT_MISSING"
        $namedBlockers.Add("WORKER_SCRIPT_MISSING:$code")
        $dispatches.Add([pscustomobject]$dispatchRecord)
        continue
    }

    $observePath = Join-Path $observeRoot ("{0}.observe.json" -f $role)
    $dispatchRecord.observe_state_path = $observePath
    $stdoutLog = Join-Path $artifactRoot ("{0}.worker.stdout.log" -f $role)
    $stderrLog = Join-Path $artifactRoot ("{0}.worker.stderr.log" -f $role)

    if ($code -in @("B", "C")) {
        $workerArgs = @(
            $workerScript,
            "--auditor", $code,
            "--evidence-path", $evidencePath,
            "--output-path", $reportPath,
            "--user-focus-cn", $UserFocusCn,
            "--timeout-seconds", ([string]$timeout),
            "--ticket-id", $ticketId,
            "--observe-state-path", $observePath
        )
    }
    else {
        $workerArgs = @(
            $workerScript,
            "--evidence-path", $evidencePath,
            "--output-path", $reportPath,
            "--role", "dp_semantic_audit",
            "--user-focus-cn", $UserFocusCn,
            "--timeout-seconds", ([string]$timeout),
            "--ticket-id", $ticketId,
            "--observe-state-path", $observePath
        )
    }

    try {
        $run = Invoke-GrokAuditWorker -Python $python -WorkerArgs $workerArgs -Wait:$waitAll -StdoutLog $stdoutLog -StderrLog $stderrLog
        $dispatchRecord.worker_script = $workerScript
        $dispatchRecord.dispatch_mode = $run.mode
        $dispatchRecord.process_id = $run.process_id
        if ($run.mode -eq "detached_process") {
            $dispatchRecord.status = "detached_running"
        }
        else {
            $dispatchRecord.exit_code = $run.exit_code
            $dispatchRecord.report_path = $reportPath
            if ($run.exit_code -eq 0) {
                $dispatchRecord.status = "completed_pass"
            }
            elseif (Test-Path -LiteralPath $reportPath) {
                $dispatchRecord.status = "completed_non_pass"
            }
            else {
                $dispatchRecord.status = "failed"
                $namedBlockers.Add("AUDIT_WORKER_FAILED:$code")
            }
        }
    }
    catch {
        $dispatchRecord.status = "failed"
        $dispatchRecord.error = $_.Exception.Message
        $namedBlockers.Add("AUDIT_WORKER_EXCEPTION:$code")
    }

    $dispatches.Add([pscustomobject]$dispatchRecord)
}

$antiCollision = [ordered]@{
    does_not_post_to_codex_a = $true
    forbidden_during_summon = @(
        "/codex-a/intent",
        "/codex-a/visible-typeahead",
        "/codex-a/visible-inject",
        "/codex-a/dialog"
    )
    codex_a_turn_running = $codexATurnRunning
    dispatch_mode_when_a_running = "async_background_only"
    visible_window = $false
    correction_requires_user_agreement = $true
}
if ($division -and $division.anti_collision) {
    $antiCollision.division_ref = $DivisionPath
    $antiCollision.note_cn = $division.anti_collision.note_cn
}

$grokNextStepCn = "A 继续主线；旁路只读审计；Git/GitHub 仅收尾提及；Grok 读回后用人话四段式汇报"
$dispatchStatus = "failed"
if ($namedBlockers.Count -eq 0) {
    $dispatchStatus = "summoned"
}
elseif (@($dispatches | Where-Object { $_.status -match 'summoned|completed' }).Count -gt 0) {
    $dispatchStatus = "partial"
}

$manifest = [ordered]@{
    schema_version = "xinao.grok_parallel_global_audit.dispatch.v2"
    generated_at = $now.ToString("o")
    ticket_id = $ticketId
    audit_lane = "grok_parallel_global_side_audit"
    protocol_id = "PHASE_PARALLEL_AUDIT_V1"
    sole_migration_ref = [string]$config.sole_migration_architecture_ref
    division_ref = $DivisionPath
    not_task_owner = $true
    not_user_completion = $true
    not_completion_decision = $true
    does_not_block_codex_a = $true
    visible_window = $false
    preferred_carriers = @("codex_exec_json_background", "litellm_deepseek_gateway_background")
    anti_collision = $antiCollision
    repo_surface_policy = if ($division) { $division.repo_surface_policy } else { @{ git_repo_not_mainline = $true } }
    codex_a_panel_snapshot = @{
        turn_status = if ($codexAPanel) { $codexAPanel.turn_status } else { "unknown" }
        named_blocker = if ($codexAPanel) { $codexAPanel.named_blocker } else { "" }
    }
    current_intent_id = $currentIntentId
    user_focus_cn = $UserFocusCn
    summon = $summonList
    grok_evidence_path = $evidencePath
    artifact_dir = $artifactRoot
    observe_root = $observeRoot
    local_observe_plane = "state/grok_local_observe/{ticket_id}/*.observe.json"
    default_dispatch_mode = if ($waitAll) { "sync_observe" } else { "detached_process" }
    dispatches = @($dispatches)
    named_blockers = @($namedBlockers)
    grok_next_step_cn = $grokNextStepCn
    status = $dispatchStatus
}

$latestPath = Join-Path $stateDir "latest.json"
$ticketPath = Join-Path $stateDir "$ticketId.json"
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $latestPath -Encoding UTF8
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $ticketPath -Encoding UTF8
$manifest | ConvertTo-Json -Depth 12