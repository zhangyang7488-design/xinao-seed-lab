[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S",
    [string]$Python = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Payload
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $Payload | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$stateDir = Join-Path $RuntimeRoot "state\root_intent_loop_driver_hook"
$latestPath = Join-Path $stateDir "latest.json"
$stopAuditPath = Join-Path $RuntimeRoot "state\codex_s_stop_continuation_audit\latest.json"
$stopAudit = Read-JsonFile -Path $stopAuditPath
$packet = $null
if ($null -ne $stopAudit -and $null -ne $stopAudit.next_loop_packet) {
    $packet = $stopAudit.next_loop_packet
}

$packetContinue = $false
foreach ($key in @("should_continue_loop", "restore", "dispatch", "poll", "fan_in", "verify_evidence_readback", "recompute_capacity", "next_wave")) {
    if ($null -ne $packet -and $packet.PSObject.Properties.Name -contains $key -and $packet.$key -eq $true) {
        $packetContinue = $true
    }
}
$auditContinue = (
    ($null -ne $stopAudit -and $stopAudit.should_continue_loop -eq $true) -or
    ($null -ne $stopAudit -and $stopAudit.stop_handoff_available -eq $true) -or
    $packetContinue
)
$explicitUserStopRequested = (
    ($null -ne $stopAudit -and $null -ne $stopAudit.report_stop_surface -and $stopAudit.report_stop_surface.explicit_user_stop_requested -eq $true) -or
    ($null -ne $packet -and $null -ne $packet.front_gate -and [string]$packet.front_gate -eq "explicit_user_stop_override")
)
if ($explicitUserStopRequested) {
    $auditContinue = $false
}

$waveId = "codex-s-root-intent-loop-hook-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
$record = [ordered]@{
    schema_version = "xinao.codex_s.root_intent_loop_driver_hook.v1"
    status = "transfer_not_invoked"
    generated_at = (Get-Date).ToString("o")
    runtime_root = $RuntimeRoot
    repo_root = $RepoRoot
    stop_audit_ref = $stopAuditPath
    audit_should_continue_loop = [bool]$auditContinue
    explicit_user_stop_requested = [bool]$explicitUserStopRequested
    stop_hook_transfer_only = $true
    stop_hook_controller = $false
    stop_hook_is_controller = $false
    stop_hook_is_completion_gate = $false
    stop_hook_dispatches_main_execution_loop_directly = $false
    stop_hook_writes_worker_dispatch_ledger = $false
    root_intent_loop_driver_is_controller = $false
    root_intent_loop_driver_invoked_by_stop_hook_transfer = $false
    root_intent_loop_driver_runtime_enforced_by_hook = $false
    root_intent_loop_driver_owns_runtime_scope_if_invoked = $true
    wave_id = $waveId
    completion_claim_allowed = $false
    not_user_completion = $true
    not_completion_decision = $true
    not_execution_controller = $true
    not_completion_gate = $true
    fail_open = $true
    runtime_enforced_scope = "Stop hook wrapper is transfer-only: it may invoke the RootIntentLoop driver when stop audit says continue, but it does not become the controller, completion gate, worker ledger writer, or main-loop decision authority."
    sentinel = "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_TRANSFER_ONLY_HOOK"
}

try {
    if (-not $auditContinue) {
        $record.status = "skipped_stop_handoff_not_active"
        Write-JsonFile -Path $latestPath -Payload $record
        if (-not $Quiet) {
            $record | ConvertTo-Json -Depth 20
        }
        return
    }

    if (-not $Python) {
        $Python = "python"
    }

    Push-Location $RepoRoot
    try {
        $oldPythonPath = $env:PYTHONPATH
        $env:PYTHONPATH = "$RepoRoot\src;$RepoRoot"
        $anchorPackageRoot = Join-Path "C:\Users\xx363\Desktop" (
            [string]([char]0x65B0) + [string]([char]0x7CFB) + [string]([char]0x7EDF)
        )
        $pythonArgs = @(
            "-m",
            "xinao_seedlab.cli.__main__",
            "root-intent-loop-driver",
            "--runtime-root",
            $RuntimeRoot,
            "--anchor-package-root",
            $anchorPackageRoot,
            "--wave-id",
            $waveId
        )
        $output = @(& $Python @pythonArgs 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
        Pop-Location
    }

    $driverLatestPath = Join-Path $RuntimeRoot "state\root_intent_loop_driver\latest.json"
    $driverLatest = Read-JsonFile -Path $driverLatestPath
    $driverValidationPassed = (
        $null -ne $driverLatest -and
        $null -ne $driverLatest.validation -and
        $driverLatest.validation.passed -eq $true
    )
    $driverSentinelVerified = (
        $null -ne $driverLatest -and
        [string]$driverLatest.sentinel -eq "SENTINEL:XINAO_CODEX_S_ROOT_INTENT_LOOP_DRIVER_RUNTIME_ENFORCED"
    )
    $driverLatestVerified = (
        $exitCode -eq 0 -and
        (Test-Path -LiteralPath $driverLatestPath -PathType Leaf) -and
        $driverValidationPassed -and
        $driverSentinelVerified
    )

    $record.status = if ($driverLatestVerified) { "transfer_invoked_driver_verified" } else { "transfer_invoked_driver_failed_open" }
    $record.exit_code = $exitCode
    $record.output_tail = @($output | Select-Object -Last 20)
    $record.driver_latest_ref = $driverLatestPath
    $record.driver_latest_exists = Test-Path -LiteralPath $driverLatestPath -PathType Leaf
    $record.driver_latest_status = if ($null -ne $driverLatest -and $driverLatest.status) { [string]$driverLatest.status } else { "" }
    $record.driver_latest_validation_passed = [bool]$driverValidationPassed
    $record.driver_latest_sentinel_verified = [bool]$driverSentinelVerified
    $record.root_intent_loop_driver_invoked_by_stop_hook_transfer = $true
    $record.root_intent_loop_driver_runtime_enforced_by_hook = $false
    $record.driver_runtime_enforced_scope = "owned_by_root_intent_loop_driver_payload_only_if_driver_latest_verifies; not owned by Stop hook wrapper"
    if (-not $driverLatestVerified) {
        $record.named_blocker = if ($exitCode -ne 0) { "ROOT_INTENT_LOOP_DRIVER_HOOK_INVOCATION_FAILED" } else { "ROOT_INTENT_LOOP_DRIVER_HOOK_INVOCATION_UNVERIFIED" }
    }
    Write-JsonFile -Path $latestPath -Payload $record
}
catch {
    $record.status = "transfer_failed_open"
    $record.named_blocker = "ROOT_INTENT_LOOP_DRIVER_HOOK_FAILED_OPEN"
    $record.error_type = $_.Exception.GetType().FullName
    $record.error = $_.Exception.Message
    Write-JsonFile -Path $latestPath -Payload $record
}

if (-not $Quiet) {
    $record | ConvertTo-Json -Depth 20
}
