[CmdletBinding()]
param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [switch]$RequireRunningProcess,
    [switch]$RequireExternalFamilies,
    [switch]$RequireEightWaves,
    [switch]$RequireA4DefaultShape,
    [string]$RequireDeadlineAtOrAfter = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$stateDir = Join-Path $RuntimeRoot "state\overnight_supervisor_loop"
$latestPath = Join-Path $stateDir "latest.json"
$heartbeatPath = Join-Path $stateDir "heartbeat_latest.json"
$launcherPath = Join-Path $stateDir "launcher_latest.json"
$pidPath = Join-Path $stateDir "loop.pid"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\overnight_supervisor_loop_20260704.md"
$assignmentPath = Join-Path $RuntimeRoot "state\worker_assignment\overnight_supervisor_loop_phase0_batch_20260704.json"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.overnight_supervisor_loop_watchdog\manifest.json"
$invokePath = Join-Path $RuntimeRoot "capabilities\codex_s.overnight_supervisor_loop_watchdog\invoke_evidence\latest.json"
$a4Path = Join-Path $stateDir "a4_default_shape\latest.json"

$latest = Read-JsonFile $latestPath
$heartbeat = Read-JsonFile $heartbeatPath
$assignment = Read-JsonFile $assignmentPath
$manifest = Read-JsonFile $manifestPath
$invoke = Read-JsonFile $invokePath

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.overnight_supervisor_loop.v1") "latest schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_CODEX_S_OVERNIGHT_SUPERVISOR_LOOP_ACTIVE") "sentinel mismatch."
Assert-True ($latest.foreground_poll_required -eq $true) "foreground_poll_required must stay true."
Assert-True ([string]$latest.poll_owner -eq "codex_s") "poll_owner must be codex_s."
Assert-True ($latest.user_prompts_required -eq $false) "user prompts must not be required."
Assert-True ($latest.completion_claim_allowed -eq $false) "completion claim must be blocked."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "readback missing."
Assert-True ([string]$assignment.source_intent_package_ref -like "*grok_overnight_supervisor_loop_phase0_batch_20260704.json") "worker assignment not rebound to overnight package."
Assert-True ([string]$manifest.provider_id -eq "codex_s.overnight_supervisor_loop_watchdog") "capability manifest provider mismatch."
Assert-True ($invoke.invoke_performed -eq $true) "capability invoke evidence missing."
Assert-True ([string]$heartbeat.schema_version -eq [string]$latest.schema_version) "heartbeat schema mismatch."

if ($RequireDeadlineAtOrAfter) {
    $requiredDeadline = [DateTimeOffset]::Parse($RequireDeadlineAtOrAfter)
    $actualDeadline = [DateTimeOffset]::Parse([string]$latest.deadline_at)
    Assert-True ($actualDeadline -ge $requiredDeadline) "deadline_at is before required extension."
}

if ($RequireRunningProcess) {
    Assert-True (Test-Path -LiteralPath $pidPath -PathType Leaf) "pid file missing."
    $pidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    Assert-True ($pidText -match '^\d+$') "pid file invalid."
    $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
    Assert-True ($null -ne $proc) "overnight supervisor process is not running."
}

if ($RequireExternalFamilies) {
    Assert-True ([int]$latest.external_search.non_local_source_family_count -ge 2) "external source-family count below 2."
}

if ($RequireEightWaves) {
    Assert-True ([int]$latest.wave_count -ge 8) "wave_count below 8."
    Assert-True ([int]$latest.ledger.succeeded_count -ge 8) "ledger succeeded below 8."
}

if ($RequireA4DefaultShape) {
    $a4 = Read-JsonFile $a4Path
    $readbackText = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
    Assert-True ([string]$a4.schema_version -eq "xinao.codex_s.overnight_a4_default_wave_shape.v1") "A.4 shape schema mismatch."
    Assert-True ($a4.validation.passed -eq $true) "A.4 default shape validation failed."
    Assert-True (($a4.stage_order -join "->") -eq "parallel_draft->merge->writer") "A.4 stage order mismatch."
    Assert-True ($a4.ledger_true_succeeded -eq $true) "A.4 ledger true succeeded missing."
    Assert-True ([string]$a4.meta_rsi_role -eq "evidence_only_not_main_worker") "meta_rsi must not be main worker."
    Assert-True ($readbackText.Contains("watchdog_status") -and $readbackText.Contains("root_intent_loop_driver")) "readback does not answer invoke."
    Assert-True ($readbackText.Contains("parallel_draft -> merge -> writer")) "readback missing A.4 wave shape."
}

Write-Output "overnight_supervisor_loop_latest=$latestPath"
Write-Output "overnight_supervisor_loop_heartbeat=$heartbeatPath"
Write-Output "overnight_supervisor_loop_readback=$readbackPath"
Write-Output "overnight_supervisor_loop_assignment=$assignmentPath"
Write-Output "overnight_supervisor_loop_capability_manifest=$manifestPath"
Write-Output "overnight_supervisor_loop_capability_invoke=$invokePath"
Write-Output "overnight_supervisor_loop_a4_default_shape=$a4Path"
Write-Output "validation_result=PASS"
