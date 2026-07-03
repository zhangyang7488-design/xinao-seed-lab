$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = "D:\XINAO_RESEARCH_RUNTIME"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$modulePath = Join-Path $repoRoot "services\agent_runtime\codex_s_live_backend_watch.py"
$testPath = Join-Path $repoRoot "tests\seedcortex\test_codex_s_live_backend_watch.py"
$schemaPath = Join-Path $repoRoot "contracts\schemas\codex_s_live_backend_watch.v1.json"

python -m py_compile $modulePath
Assert-True ($LASTEXITCODE -eq 0) "Live backend watch py_compile failed."

python -m pytest -q $testPath
Assert-True ($LASTEXITCODE -eq 0) "Live backend watch pytest failed."

$output = python $modulePath --repo-root $repoRoot --runtime-root $runtimeRoot
Assert-True ($LASTEXITCODE -eq 0) "Live backend watch generation failed."
$text = $output -join "`n"
Assert-True ($text.Contains("SENTINEL:XINAO_CODEX_S_LIVE_BACKEND_WATCH_READY")) "Live backend watch sentinel missing."

$latestPath = Join-Path $runtimeRoot "state\codex_s_live_backend_watch\latest.json"
$readbackPath = Join-Path $runtimeRoot "readback\zh\codex_s_live_backend_watch_20260702.md"

Assert-True (Test-Path -LiteralPath $latestPath -PathType Leaf) "Missing live backend watch latest."
Assert-True (Test-Path -LiteralPath $readbackPath -PathType Leaf) "Missing live backend watch readback."
Assert-True (Test-Path -LiteralPath $schemaPath -PathType Leaf) "Missing live backend watch schema."

$payload = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($payload.schema_version -eq "xinao.codex_s.live_backend_watch.v1") "Schema mismatch."
Assert-True ($payload.sentinel -eq "SENTINEL:XINAO_CODEX_S_LIVE_BACKEND_WATCH_READY") "Payload sentinel mismatch."
Assert-True ($payload.validation.passed -eq $true) "Payload validation failed."
Assert-True ($payload.old_backend_mirror_semantics_reused -eq $true) "Old backend semantics flag missing."
Assert-True ($payload.old_backend_endpoint_used -eq $false) "Old backend endpoint was used."
Assert-True ($payload.compat_endpoint_used -eq $false) "Compat endpoint was used."
Assert-True ($payload.static_context_triggers_poll -eq $false) "Static context triggered poll."
Assert-True ($payload.not_source_of_truth -eq $true) "Boundary not_source_of_truth missing."
Assert-True ($payload.not_user_completion -eq $true) "Boundary not_user_completion missing."
Assert-True ($payload.not_completion_decision -eq $true) "Boundary not_completion_decision missing."
Assert-True ($payload.not_execution_controller -eq $true) "Boundary not_execution_controller missing."

$requiredCategories = @(
    "worker_running",
    "temporal_pending_activity",
    "worker_jsonl_non_terminal",
    "assignment_next_ready",
    "assignment_auto_continue_expected",
    "queue_or_lane_non_terminal",
    "output_growth_detected"
)
$oldCategories = @($payload.old_semantic_categories.continue_required_categories)
foreach ($category in $requiredCategories) {
    Assert-True ($oldCategories -contains $category) "Missing old semantic category: $category"
}

$readbackText = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
$notTruth = [string]([char]0x4E0D) + [string]([char]0x662F) + [string]([char]0x4E8B) + [string]([char]0x5B9E) + [string]([char]0x6E90)
$poll = [string]([char]0x8F6E) + [string]([char]0x8BE2)
Assert-True ($readbackText.Contains($notTruth)) "Readback missing boundary text."
Assert-True ($readbackText.Contains($poll)) "Readback missing poll text."

Write-Output "codex_s_live_backend_watch_latest=$latestPath"
Write-Output "codex_s_live_backend_watch_readback=$readbackPath"
Write-Output "validation_result=PASS"
Write-Output "SENTINEL:XINAO_CODEX_S_LIVE_BACKEND_WATCH_READY"
