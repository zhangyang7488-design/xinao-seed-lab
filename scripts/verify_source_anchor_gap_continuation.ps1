$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"
$anchorRoot = Join-Path (Join-Path $env:USERPROFILE "Desktop") (
    [string]([char]0x65B0) + [string]([char]0x7CFB) + [string]([char]0x7EDF)
)

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\source_anchor_gap_continuation.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_source_anchor_gap_continuation.py"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "Source anchor gap continuation py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "Source anchor gap continuation pytest failed."

if ((Test-Path -LiteralPath $runtimeRoot -PathType Container) -and (Test-Path -LiteralPath $anchorRoot -PathType Container)) {
    $output = python $modulePath `
        --repo-root $repoRoot `
        --runtime-root $runtimeRoot `
        --anchor-package-root $anchorRoot `
        --continuation-mode-active
    $generationExitCode = $LASTEXITCODE
    if ($generationExitCode -ne 0) {
        $output | ForEach-Object { Write-Output $_ }
    }
    Assert-True ($generationExitCode -eq 0) "Source anchor gap continuation generation failed."

    $latestPath = Join-Path $runtimeRoot "state\source_anchor_gap_continuation\latest.json"
    $coveragePath = Join-Path $runtimeRoot "state\source_anchor_coverage\latest.json"
    $slicesPath = Join-Path $runtimeRoot "state\source_anchor_task_slices\latest.json"
    $taskCardPath = Join-Path $runtimeRoot "state\task_card\source_anchor_coverage_next_ready.json"
    foreach ($path in @($latestPath, $coveragePath, $slicesPath, $taskCardPath)) {
        Assert-True (Test-Path -LiteralPath $path -PathType Leaf) "Missing source anchor evidence: $path"
    }

    $payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($payload.schema_version -eq "xinao.codex_s.source_anchor_gap_continuation.v1") "Schema mismatch."
    Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_GAP_CONTINUATION_READY") "Payload sentinel mismatch."
    Assert-True ($payload.source_anchor_complete -eq $true) "Source anchor entry root missing."
    Assert-True ($payload.source_anchors.discovery_policy -eq "entry_root_only_no_text_file_binding") "Source anchor should only check entry root."
    Assert-True ($payload.source_anchors.text_file_scan_enabled -eq $false) "Source anchor scanned text files."
    Assert-True ($payload.auto_task_slicing_enabled -eq $false) "Auto source task slicing was enabled."
    Assert-True ($payload.source_anchor_task_slicing_frozen -eq $true) "Auto source task slicing was not frozen."
    Assert-True ($payload.source_text_debt_open -eq $false) "Source text debt should not drive continuation while frozen."
    Assert-True ($payload.coverage_gate_decision.report_allowed -eq $true) "Report allowance missing."
    Assert-True ($payload.stop_hook_may_use_as_decision_input -eq $true) "Stop hook decision input boundary missing."
    Assert-True ($payload.validation.checks.source_text_debt_accounted_for -eq $true) "Source text debt was not accounted for."
    $taskCard = Get-Content -LiteralPath $taskCardPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($taskCard.status -eq "frozen_tombstone_not_taskcard") "Stale source-anchor TaskCard was not frozen."

    Write-Output "source_anchor_gap_continuation_latest=$latestPath"
    Write-Output "source_anchor_coverage_latest=$coveragePath"
    Write-Output "source_anchor_task_slices_latest=$slicesPath"
    Write-Output "source_anchor_next_task_card=$taskCardPath"
}
else {
    Write-Output "runtime_generation_skipped=missing_runtime_or_anchor_root"
}

Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_CODEX_S_SOURCE_ANCHOR_GAP_CONTINUATION_READY"
