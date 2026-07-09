#Requires -Version 5.1
<#
.SYNOPSIS
  双方同构 · 模块化分离 — 能力焊装薄壳（M5）。
  默认：把 E 盘已镜像的纪律 skills 以 junction 装进 Grok 4.5 岛 skills，并写 D 盘 claim 证据。
  不碰 long_workflow task_queue / HolographicGapScan / RunNext（避免与并行 Grok 波次冲突）。
#>
param(
    [switch]$Plan,
    [switch]$ApplyDisciplineSkills,
    [switch]$Status,
    [string]$LaneSkillsRoot = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
$contract = Join-Path $bridge "grok_dual_isomorphism_modular_separation.v1.json"
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateRoot = Join-Path $runtime "state\isomorphic_capability_weld"
$latestPath = Join-Path $stateRoot "latest.json"
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null

$mirrorRoot = "E:\XINAO_EXTERNAL_MATURE\codex_20260627"
$superpowersSkills = Join-Path $mirrorRoot "awesome_extracted\obra__superpowers\skills"

# Prefer skills under the bridge's own workspace; never default into another Grok home
if ([string]::IsNullOrWhiteSpace($LaneSkillsRoot)) {
    $localSkills = Join-Path (Split-Path $bridge -Parent) ".grok\skills"
    $candidates = @(
        $localSkills,
        "C:\Users\xx363\.grok-4.5-lane\skills",
        "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace-grok-4.5\.grok\skills"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { $LaneSkillsRoot = $c; break }
    }
    if ([string]::IsNullOrWhiteSpace($LaneSkillsRoot)) {
        $LaneSkillsRoot = $localSkills
        New-Item -ItemType Directory -Force -Path $LaneSkillsRoot | Out-Null
    }
}

# High-signal discipline subset (not full 300-skill dump)
$disciplineSkillIds = @(
    "using-superpowers",
    "writing-plans",
    "executing-plans",
    "test-driven-development",
    "systematic-debugging",
    "verification-before-completion",
    "subagent-driven-development"
)

function Write-JsonFile([string]$Path, [object]$Obj) {
    $json = $Obj | ConvertTo-Json -Depth 14
    [System.IO.File]::WriteAllText($Path, $json, $utf8)
}

function Get-PlanObject {
    $items = @()
    foreach ($id in $disciplineSkillIds) {
        $src = Join-Path $superpowersSkills $id
        $dst = Join-Path $LaneSkillsRoot "sp-$id"
        $items += [ordered]@{
            id           = $id
            source       = $src
            target       = $dst
            source_ok    = (Test-Path -LiteralPath $src)
            already_weld = (Test-Path -LiteralPath $dst)
        }
    }
    return [ordered]@{
        schema_version = "xinao.grok_isomorphic_capability_weld.plan.v1"
        sentinel       = "SENTINEL:ISOMORPHIC_CAPABILITY_WELD"
        contract_ref   = $contract
        lane_skills    = $LaneSkillsRoot
        superpowers    = $superpowersSkills
        dual_iso_cn    = "333 与 Grok 能力形状同构；本脚本只焊 Grok 岛纪律 skills（M5），不改 333 Temporal owner"
        modular_cn     = "M1入口/M2编排/M3工人/M4证据 不在此脚本合并；禁止第三条主链"
        avoid_conflict = @("Invoke-GrokLongWorkflowRunNext.ps1", "Invoke-GrokHolographicGapScan.ps1", "task_queue.json hot rewrite")
        discipline     = $items
        generated_at   = (Get-Date).ToString("o")
    }
}

if ($Status -or (-not $Plan -and -not $ApplyDisciplineSkills)) {
    if (Test-Path -LiteralPath $latestPath) {
        if (-not $Quiet) { Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 }
        exit 0
    }
    $p = Get-PlanObject
    if (-not $Quiet) { $p | ConvertTo-Json -Depth 10 }
    exit 0
}

if ($Plan) {
    $p = Get-PlanObject
    Write-JsonFile (Join-Path $stateRoot "plan_latest.json") $p
    if (-not $Quiet) { $p | ConvertTo-Json -Depth 10 }
    exit 0
}

if ($ApplyDisciplineSkills) {
    if (-not (Test-Path -LiteralPath $superpowersSkills)) {
        throw "superpowers mirror missing: $superpowersSkills"
    }
    New-Item -ItemType Directory -Force -Path $LaneSkillsRoot | Out-Null

    $welded = @()
    $skipped = @()
    $failed = @()

    foreach ($id in $disciplineSkillIds) {
        $src = Join-Path $superpowersSkills $id
        $dst = Join-Path $LaneSkillsRoot "sp-$id"
        if (-not (Test-Path -LiteralPath $src)) {
            $failed += [ordered]@{ id = $id; error = "source_missing"; source = $src }
            continue
        }
        if (Test-Path -LiteralPath $dst) {
            $skipped += [ordered]@{ id = $id; target = $dst; reason = "already_exists" }
            continue
        }
        try {
            # Junction: install into self without copying tree (claim, not reclone)
            $null = cmd /c "mklink /J `"$dst`" `"$src`""
            if (-not (Test-Path -LiteralPath $dst)) { throw "junction_failed" }
            $welded += [ordered]@{ id = $id; target = $dst; source = $src; mode = "junction" }
        }
        catch {
            $failed += [ordered]@{ id = $id; error = "$_"; source = $src; target = $dst }
        }
    }

    $result = [ordered]@{
        schema_version   = "xinao.grok_isomorphic_capability_weld.result.v1"
        sentinel         = "SENTINEL:ISOMORPHIC_CAPABILITY_WELD"
        generated_at     = (Get-Date).ToString("o")
        contract_ref     = $contract
        surface          = "grok_island_skills"
        isomorphic_note  = "discipline skills on Grok; 333 uses Temporal/wave carriers for same discipline shape"
        modular_note     = "M5 only; ingress/claim/worker modules unchanged"
        lane_skills_root = $LaneSkillsRoot
        welded           = $welded
        skipped          = $skipped
        failed           = $failed
        now_can_invoke   = @(
            "ls $LaneSkillsRoot\sp-*",
            "Grok skill discovery: sp-verification-before-completion / sp-writing-plans / ..."
        )
        completion_claim_allowed = $false
        honesty_cn       = "纪律 skills 已装进 Grok 岛 ≠ P0/333 闭合；真测与大包跑穿仍建设期"
    }
    Write-JsonFile $latestPath $result
    Write-JsonFile (Join-Path $stateRoot ("weld_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))) $result
    if (-not $Quiet) { $result | ConvertTo-Json -Depth 12 }
    if ($failed.Count -gt 0) { exit 2 }
    exit 0
}
