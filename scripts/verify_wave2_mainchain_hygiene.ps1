param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

$latestPath = Join-Path $RuntimeRoot "state\wave2_mainchain_hygiene\latest.json"
$mainLoopPath = Join-Path $RuntimeRoot "state\default_main_loop_hygiene\latest.json"
$blackWindowPath = Join-Path $RuntimeRoot "state\wave2_mainchain_hygiene\black_window_probe\latest.json"
$memoGapPath = Join-Path $RuntimeRoot "state\wave2_mainchain_hygiene\memo_gap_refresh\latest.json"
$nextFrontierPath = Join-Path $RuntimeRoot "state\wave2_mainchain_hygiene\next_frontier\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\wave_block2_mainchain_hygiene_20260704.md"
$schemaPath = Join-Path $RepoRoot "contracts\schemas\codex_s_wave2_mainchain_hygiene.v1.json"

$latest = Read-JsonFile $latestPath
$mainLoop = Read-JsonFile $mainLoopPath
$blackWindow = Read-JsonFile $blackWindowPath
$memoGap = Read-JsonFile $memoGapPath
$nextFrontier = Read-JsonFile $nextFrontierPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8

Assert-True (Test-Path -LiteralPath $schemaPath -PathType Leaf) "Schema missing."
Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.wave2_mainchain_hygiene.v1") "latest schema mismatch."
Assert-True ([string]$latest.task_id -eq "wave2_mainchain_hygiene_20260704") "task_id mismatch."
Assert-True ($latest.validation.passed -eq $true) "validation did not pass."
Assert-True ([string]$latest.named_blocker -eq "") "named_blocker is not empty."

Assert-True ($latest.source_package.all_required_sources_read_full -eq $true) "Source package was not fully read."
Assert-True ($latest.block_sequence.block3_source_frontier.validation_passed -eq $true) "Block3 not validated."
Assert-True ($latest.block_sequence.block3_source_frontier.source_gap_open -eq $false) "Block3 source gap still open."
Assert-True ($latest.block_sequence.block4_source_family.validation_passed -eq $true) "Block4 not validated."
Assert-True ([int]$latest.block_sequence.block4_source_family.accepted_artifact_count -ge 1) "Block4 accepted artifacts missing."
Assert-True ($latest.block_sequence.block5_phase0_kernel.validation_passed -eq $true) "Block5 not validated."
Assert-True ([int]$latest.block_sequence.block5_phase0_kernel.landed_count -ge 4) "Block5 kernel objects missing."

Assert-True ([string]$mainLoop.default_main_loop -eq "temporal_activity_event_queue_loop") "Default loop mismatch."
Assert-True ($mainLoop.single_default_while -eq $true) "single_default_while missing."
Assert-True ($mainLoop.event_backlog_frontier_driven -eq $true) "event/backlog/frontier trigger missing."
Assert-True ($mainLoop.thirty_minute_runner.disabled_or_reference_only -eq $true) "30min runner not disabled/reference-only."
Assert-True ($mainLoop.thirty_minute_runner.same_default_loop_reference_only -eq $true) "same_default loop not reference-only."
Assert-True ($mainLoop.thirty_minute_runner.overnight_runner_reference_only -eq $true) "overnight runner not reference-only."
Assert-True ($mainLoop.thirty_minute_runner.sleep_1800_default_main_loop_allowed -eq $false) "sleep 1800 still allowed."

Assert-True ($blackWindow.black_window_issue_handled -eq $true) "black window probe not handled."
Assert-True ([int]$blackWindow.visible_disallowed_cmd_powershell_python_count -eq 0) "visible cmd/powershell/python window detected."
Assert-True ($blackWindow.start_worker_contract.powershell_windowstyle_hidden -eq $true) "worker start script is not Hidden."
Assert-True ($blackWindow.no_window_code_contract.phase3_create_no_window -eq $true) "phase3 missing CREATE_NO_WINDOW."

Assert-True ([int]$memoGap.counts.total_targets -eq 13) "memo target total mismatch."
Assert-True ([int]$memoGap.counts.landed_or_migrated -eq 13) "memo targets not fully landed."
Assert-True ([int]$memoGap.counts.partial -eq 0) "memo partial gaps remain."
Assert-True ([int]$memoGap.counts.gap -eq 0) "memo gaps remain."

Assert-True ($nextFrontier.stop_allowed -eq $false) "next frontier stop_allowed must be false."
Assert-True (@($nextFrontier.next_frontier).Count -ge 1) "next frontier is empty."
$firstNextFrontier = @($nextFrontier.next_frontier)[0]
Assert-True ([string]$firstNextFrontier.action -eq "continue_source_frontier_claimcard_absorption") "next action mismatch."

foreach ($needle in @("main_loop", "runner_30min", "black_window", "memo_gap", "stop_allowed", "next_machine_action")) {
    Assert-True ($readback.Contains($needle)) "readback missing $needle."
}

Write-Output "wave2_mainchain_hygiene_latest=$latestPath"
Write-Output "default_main_loop_hygiene=$mainLoopPath"
Write-Output "black_window_probe=$blackWindowPath"
Write-Output "memo_gap_refresh=$memoGapPath"
Write-Output "next_frontier=$nextFrontierPath"
Write-Output "readback_zh=$readbackPath"
Write-Output "wave2_mainchain_hygiene=PASS"
