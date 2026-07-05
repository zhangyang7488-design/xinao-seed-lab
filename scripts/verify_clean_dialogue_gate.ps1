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

function Read-TextFile {
    param([string]$Path)
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing file: $Path"
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Assert-Contains {
    param(
        [string]$Text,
        [string]$Needle,
        [string]$Label
    )
    Assert-True ($Text.Contains($Needle)) "$Label missing required text: $Needle"
}

function Assert-Before {
    param(
        [string]$Text,
        [string]$First,
        [string]$Second,
        [string]$Label
    )
    $firstIndex = $Text.IndexOf($First)
    $secondIndex = $Text.IndexOf($Second)
    Assert-True ($firstIndex -ge 0) "$Label missing first marker: $First"
    Assert-True ($secondIndex -ge 0) "$Label missing second marker: $Second"
    Assert-True ($firstIndex -lt $secondIndex) "$Label marker order invalid: '$First' must appear before '$Second'"
}

$agentsPath = Join-Path $RepoRoot "AGENTS.md"
$l0Path = Join-Path $RepoRoot "CODEX_S_L0.md"
$mustReadPath = Join-Path $RepoRoot "SEED_CORTEX_MUST_READ_FIRST.md"
$docsBoundaryPath = Join-Path $RepoRoot "docs\current\CODEX_S_CURRENT_DOCS_BOUNDARY_2026-07-02.md"

$agents = Read-TextFile $agentsPath
$l0 = Read-TextFile $l0Path
$mustRead = Read-TextFile $mustReadPath
$docsBoundary = Read-TextFile $docsBoundaryPath

Assert-Contains $agents "## CleanDialogueGate v1" "AGENTS.md"
Assert-Contains $agents "This is the outermost gate." "AGENTS.md"
Assert-Contains $agents "default_mode = human_dialogue" "AGENTS.md"
Assert-Contains $agents "execution_requires_explicit_user_action = true" "AGENTS.md"
Assert-Contains $agents "meta_conversation_never_triggers_runtime_by_itself = true" "AGENTS.md"
Assert-Contains $agents 'Project rules apply after `execution` is selected.' "AGENTS.md"
Assert-Contains $agents 'Global Codex self-prelude is downstream of `CleanDialogueGate`.' "AGENTS.md"
Assert-Before $agents "## CleanDialogueGate v1" "When the current object mentions Seed Cortex" "AGENTS.md"

Assert-Contains $l0 "## CleanDialogueGate v1" "CODEX_S_L0.md"
Assert-Contains $l0 "This gate is outermost." "CODEX_S_L0.md"
Assert-Contains $l0 'After `CleanDialogueGate` classifies the current message as `execution`' "CODEX_S_L0.md"
Assert-Contains $l0 'The artifact question is valid only after `execution` is selected.' "CODEX_S_L0.md"
Assert-Contains $l0 "Global Codex self-prelude is always on for this S identity after" "CODEX_S_L0.md"
Assert-Contains $l0 'For `human_dialogue`, do not enter execution-graph mode.' "CODEX_S_L0.md"
Assert-Before $l0 "## CleanDialogueGate v1" "## 0. Boot Authority" "CODEX_S_L0.md"

Assert-Contains $mustRead "## Clean Dialogue Boundary" "SEED_CORTEX_MUST_READ_FIRST.md"
Assert-Contains $mustRead "ordinary/meta dialogue" "SEED_CORTEX_MUST_READ_FIRST.md"
Assert-Contains $mustRead "This file applies after" "SEED_CORTEX_MUST_READ_FIRST.md"

Assert-Contains $docsBoundary '`CleanDialogueGate v1` is the outermost conversation boundary.' "docs/current boundary"
Assert-Contains $docsBoundary "must not trigger" "docs/current boundary"

$stateDir = Join-Path $RuntimeRoot "state\clean_dialogue_gate"
$readbackDir = Join-Path $RuntimeRoot "readback\zh"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
New-Item -ItemType Directory -Force -Path $readbackDir | Out-Null

$latestPath = Join-Path $stateDir "latest.json"
$readbackPath = Join-Path $readbackDir "clean_dialogue_gate_20260705.md"

$evidence = [ordered]@{
    schema_version = "xinao.codex_s.clean_dialogue_gate.v1"
    task_id = "clean_dialogue_gate_20260705"
    generated_at = (Get-Date).ToString("o")
    adoption_state = "default_hot_path_ready"
    runtime_enforced = $false
    completion_claim_allowed = $false
    boundary = "conversation_intent_gate_before_s_startup"
    validation = [ordered]@{
        passed = $true
        clean_dialogue_gate_before_hot_path = $true
        self_prelude_downstream_of_gate = $true
        human_dialogue_blocks_hot_path_tools_runtime = $true
        execution_requires_explicit_user_action = $true
    }
    files = @(
        $agentsPath,
        $l0Path,
        $mustReadPath,
        $docsBoundaryPath
    )
    classifier_samples = @(
        [ordered]@{
            sample_id = "contamination_question"
            expected_mode = "human_dialogue"
            action = "direct_answer_no_tools"
        },
        [ordered]@{
            sample_id = "outside_handling_question"
            expected_mode = "human_dialogue"
            action = "direct_answer_or_diagnosis_no_mutation"
        },
        [ordered]@{
            sample_id = "inspect_repo_for_pollution_source"
            expected_mode = "execution"
            action = "load_hot_path_then_inspect"
        },
        [ordered]@{
            sample_id = "land_gate_in_code"
            expected_mode = "execution"
            action = "bounded_repo_diff_and_verifier"
        }
    )
    missing_to_next_state = @(
        "Codex host/runtime invokes this classifier before every tool turn",
        "Regression evidence proves human_dialogue cannot trigger hot-path reads or tool use"
    )
}

$evidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $latestPath -Encoding UTF8

$readbackBase64 = "IyBDbGVhbkRpYWxvZ3VlR2F0ZSDkuK3mloflm57or7sKCuebtOaOpee7k+iuuu+8muW3suaKiuKAnOWFiOWIpOaWreaYr+S4jeaYr+aZrumAmuWvueivneKAneaUvuWIsCBTIOeDrei3r+W+hOacgOWJjemdouOAggoK546w5Zyo55qE6L6555WM77yaCi0gaHVtYW5fZGlhbG9ndWXvvJrnm7TmjqXlm57nrZTkurror53vvIzkuI3or7vlt6XnqIvng63ot6/lvoTvvIzkuI3ot5Hlt6XlhbfvvIzkuI3lhpkgcnVudGltZSDor4Hmja7jgIIKLSBjbGFyaWZpY2F0aW9u77ya5YWI6Zeu5riF5qWa5oiW5Y+q5YGa56qE6K+K5pat77yM5LiN6Ieq5Yqo5omn6KGM44CCCi0gZGlhZ25vc2lz77ya5Y+v5Lul5YiG5p6Q5aSx6LSl5qih5byP77yM5L2G5LiN5pS5IHJlcG8vcnVudGltZeOAggotIGV4ZWN1dGlvbu+8mueUqOaIt+aYjuehruimgeaxguajgOafpeOAgei/kOihjOOAgemqjOivgeOAgee8lui+keOAgeWunueOsOOAgeiQveWcsOOAgeS/ruWkjeOAgeiwg+eUqOW3peWFt+aXtu+8jOaJjei/m+WFpSBTIOWQr+WKqOi3r+e6v+WSjOaJp+ihjOWbvuOAggoK6IO95Yqb6YeH57qz54q25oCB77yaZGVmYXVsdF9ob3RfcGF0aF9yZWFkeeOAggrov5nku6PooajvvJrlkK/liqjng63ot6/lvoTpu5jorqTlj6/lj5HnjrDvvIzlubbkuJQgZm9jdXNlZCB2ZXJpZmllciDlt7LlhpnlhaXor4Hmja7vvJvov5nkuI3mmK/lrr/kuLvnuqcgcnVudGltZSDlvLrliLbliIbnsbvlmajjgIIK6L+Y57y65LuA5LmI5omN6IO96L+b5YWl5LiL5LiA54q25oCB77ya6ZyA6KaBIENvZGV4IGhvc3QvcnVudGltZSDlnKjmr4/mrKHlt6XlhbfliY3lvLrliLbosIPnlKjov5nkuKrliIbnsbvlmajvvIzlubbnlKjlm57lvZLor4Hmja7or4HmmI4gaHVtYW5fZGlhbG9ndWUg5LiN5Lya6Kem5Y+RIGhvdC1wYXRoL3Rvb2zjgII="
$readback = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($readbackBase64))

Set-Content -LiteralPath $readbackPath -Value $readback -Encoding UTF8

Write-Output "clean_dialogue_gate_latest=$latestPath"
Write-Output "clean_dialogue_gate_readback_zh=$readbackPath"
Write-Output "clean_dialogue_gate=PASS"
