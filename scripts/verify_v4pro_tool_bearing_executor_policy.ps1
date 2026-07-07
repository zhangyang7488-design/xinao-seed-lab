param(
    [string]$RuntimeRoot = "D:\XINAO_RESEARCH_RUNTIME",
    [string]$RepoRoot = "E:\XINAO_RESEARCH_WORKSPACES\S"
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Read-JsonFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing JSON file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-AcceptedDecisionsForCandidate {
    param([string]$RuntimeRoot, [string]$CandidateId)
    $paths = @()
    $latest = Join-Path $RuntimeRoot "state\artifact_acceptance_queue\latest.json"
    if (Test-Path -LiteralPath $latest -PathType Leaf) { $paths += $latest }
    $episodesRoot = Join-Path $RuntimeRoot "runs\episodes"
    if (Test-Path -LiteralPath $episodesRoot -PathType Container) {
        $paths += @(Get-ChildItem -LiteralPath $episodesRoot -Recurse -Filter artifact_acceptance.json -File | ForEach-Object { $_.FullName })
    }
    $matches = @()
    foreach ($path in $paths) {
        $payload = Read-JsonFile $path
        foreach ($decision in @($payload.decisions)) {
            if ([string]$decision.candidate_id -eq $CandidateId -and [string]$decision.status -eq "accepted") {
                $matches += $decision
            }
        }
    }
    return @($matches)
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
Assert-True (Test-Path -LiteralPath $python -PathType Leaf) "Missing repo venv python."

& $python -m services.agent_runtime.v4pro_tool_bearing_executor_policy --runtime-root $RuntimeRoot --repo-root $RepoRoot
Assert-True ($LASTEXITCODE -eq 0) "v4pro_tool_bearing_executor_policy CLI failed."

$taskId = "p0_011_v4pro_tool_bearing_executor_policy"
$latestPath = Join-Path $RuntimeRoot "state\v4pro_tool_bearing_executor_policy\latest.json"
$readbackPath = Join-Path $RuntimeRoot "readback\zh\v4pro_tool_bearing_executor_policy_20260707.md"
$manifestPath = Join-Path $RuntimeRoot "capabilities\codex_s.v4pro_tool_bearing_executor_policy\manifest.json"
$latest = Read-JsonFile $latestPath
$manifest = Read-JsonFile $manifestPath
$readback = Get-Content -LiteralPath $readbackPath -Raw -Encoding UTF8
$accepted = @(Get-AcceptedDecisionsForCandidate -RuntimeRoot $RuntimeRoot -CandidateId $taskId | Where-Object { [string]$_.artifact_acceptance_decision -eq "accepted_for_binding" })

Assert-True ([string]$latest.schema_version -eq "xinao.codex_s.v4pro_tool_bearing_executor_policy.v1") "Schema mismatch."
Assert-True ([string]$latest.sentinel -eq "SENTINEL:XINAO_V4PRO_TOOL_BEARING_EXECUTOR_POLICY_READY") "Sentinel mismatch."
Assert-True ([string]$latest.task_id -eq $taskId) "task_id mismatch."
Assert-True ([string]$latest.status -eq "v4pro_tool_bearing_executor_policy_ready") "Status is not ready."
Assert-True ($latest.tool_bearing_executor_eligible -eq $true) "V4Pro is not eligible."
Assert-True ($latest.repo_mutation_allowed -eq $true) "Repo mutation not allowed."
Assert-True ($latest.commit_push_allowed -eq $true) "Commit/push not allowed."
Assert-True ($latest.v4pro_self_acceptance_allowed -eq $false) "V4Pro self-acceptance allowed."
Assert-True ([string]$latest.final_acceptance_owner -eq "codex_or_deterministic_verifier") "Final acceptance owner mismatch."
foreach ($field in @("default_mainline_binding", "runtime_worker_load", "focused_verification", "D_runtime_evidence_readback", "git_clean_status", "commit_hash", "push_target", "current_333_mainline_state", "remaining_or_named_blocker_state")) {
    Assert-True (@($latest.closure_evidence_bundle_required) -contains $field) "Missing closure bundle field: $field"
}
Assert-True ([string]$latest.shortcut.WorkingDirectory -eq $RepoRoot) "Shortcut does not point at S repo."
Assert-True ([string]$latest.shortcut.Arguments -match "XINAO DeepSeek V4 Pro S Hardmode") "Shortcut is not V4Pro hardmode."
Assert-True ($latest.validation.passed -eq $true) "Validation failed."
Assert-True ([string]$manifest.provider_id -eq "codex_s.v4pro_tool_bearing_executor_policy") "Manifest provider mismatch."
Assert-True ($readback -match "SENTINEL:XINAO_V4PRO_TOOL_BEARING_EXECUTOR_POLICY_READY") "Readback sentinel missing."
Assert-True ($accepted.Count -ge 1) "AAQ did not accept P0-011."

Write-Output "v4pro_tool_bearing_executor_policy_latest=$latestPath"
Write-Output "readback=$readbackPath"
Write-Output "SENTINEL:XINAO_V4PRO_TOOL_BEARING_EXECUTOR_POLICY_VERIFY_PASS"
