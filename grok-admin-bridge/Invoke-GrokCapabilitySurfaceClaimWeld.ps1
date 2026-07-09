#Requires -Version 5.1
<#
.SYNOPSIS
  Grok 自身能力面：E 盘高 ROI 候选 claim + 薄焊 + 默认可 invoke 证据。
  Grok 4.5 窗专用：-Apply 只改 4.5 skills。Admin Isolated 窗禁止 -Apply；禁止碰 task_queue / RunNext。
  原则：不 re-mirror；junction 不整包 copy；不全装 300 skills。
#>
param(
    [switch]$Plan,
    [switch]$Apply,
    [switch]$Status,
    [switch]$SkipSkillJunction,
    [string]$LaneSkillsRoot = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$bridge = $PSScriptRoot
$adminWorkspace = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace"
if ($Apply -and ((Split-Path $bridge -Parent) -eq $adminWorkspace)) {
    throw "GROK_ADMIN_ISOLATED_BOUNDARY: CapabilitySurfaceClaimWeld -Apply 归 Grok 4.5 窗；本窗仅 -Status/-Plan"
}
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$stateRoot = Join-Path $runtime "state\grok_capability_surface_claim"
$latestPath = Join-Path $stateRoot "latest.json"
New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null

$mirrorRoot = "E:\XINAO_EXTERNAL_MATURE\codex_20260627"

if ([string]::IsNullOrWhiteSpace($LaneSkillsRoot)) {
    $local = Join-Path (Split-Path $bridge -Parent) ".grok\skills"
    if (Test-Path -LiteralPath $local) { $LaneSkillsRoot = $local }
    if (-not $LaneSkillsRoot) {
        $LaneSkillsRoot = $local
        New-Item -ItemType Directory -Force -Path $LaneSkillsRoot | Out-Null
    }
}

# High-ROI skill junctions only (subset). prefix -> relative source under mirrorRoot
$skillWelds = @(
    # agent-workflow-system (package / phase / evidence discipline)
    @{ id = "aws-agent-project-master";  prefix = "aws"; src = "awesome_extracted\1139030773-cmd__agent-workflow-system\plugins\agent-workflow-system\skills\agent-project-master" }
    @{ id = "aws-agent-phase-closeout";  prefix = "aws"; src = "awesome_extracted\1139030773-cmd__agent-workflow-system\plugins\agent-workflow-system\skills\agent-phase-closeout" }
    @{ id = "aws-agent-drift-auditor";  prefix = "aws"; src = "awesome_extracted\1139030773-cmd__agent-workflow-system\plugins\agent-workflow-system\skills\agent-drift-auditor" }
    @{ id = "aws-agent-debug-fixer";    prefix = "aws"; src = "awesome_extracted\1139030773-cmd__agent-workflow-system\plugins\agent-workflow-system\skills\agent-debug-fixer" }
    # task scheduler shape
    @{ id = "ts-task-planner";           prefix = "ts";  src = "awesome_extracted\6Delta9__task-scheduler-codex-plugin\skills\task-planner" }
    # autopilot subset (long-run / discovery / qa — not full stack builders)
    @{ id = "ap-project-discovery";      prefix = "ap";  src = "awesome_extracted\AlexMi64__codex-project-autopilot\skills\project-discovery" }
    @{ id = "ap-autonomous-project-loop"; prefix = "ap"; src = "awesome_extracted\AlexMi64__codex-project-autopilot\skills\autonomous-project-loop" }
    @{ id = "ap-qa-reviewer";            prefix = "ap";  src = "awesome_extracted\AlexMi64__codex-project-autopilot\skills\qa-reviewer" }
    # message queue skills
    @{ id = "amq-cli";                   prefix = "amq"; src = "awesome_extracted\avivsinai__agent-message-queue\skills\amq-cli" }
    @{ id = "amq-spec";                  prefix = "amq"; src = "awesome_extracted\avivsinai__agent-message-queue\skills\amq-spec" }
    # codex-mem memory skills (thin)
    @{ id = "mem-search";                prefix = "mem"; src = "awesome_extracted\2kDarki__codex-mem\plugin\skills\mem-search" }
    @{ id = "mem-make-plan";             prefix = "mem"; src = "awesome_extracted\2kDarki__codex-mem\plugin\skills\make-plan" }
)

# Non-skill carriers: claim path + invoke hint (no third chain install)
$carrierClaims = @(
    @{ id = "superpowers_discipline"; tier = 1; role = "discipline_skills"; mirror = "awesome_extracted\obra__superpowers"; claim_state = "welded_skills_junction"; invoke = "sp-* skills under .grok/skills; Invoke-GrokIsomorphicCapabilityWeld -Status" }
    @{ id = "agent_workflow_system"; tier = 1; role = "workflow_phase_skills"; mirror = "awesome_extracted\1139030773-cmd__agent-workflow-system"; claim_state = "claim_weld_skills_subset"; invoke = "aws-* skills" }
    @{ id = "task_scheduler_plugin"; tier = 1; role = "schedule_shape"; mirror = "awesome_extracted\6Delta9__task-scheduler-codex-plugin"; claim_state = "claim_weld_skills_subset"; invoke = "ts-task-planner skill" }
    @{ id = "codex_project_autopilot"; tier = 1; role = "longrun_subset"; mirror = "awesome_extracted\AlexMi64__codex-project-autopilot"; claim_state = "claim_weld_skills_subset"; invoke = "ap-* skills" }
    @{ id = "agent_message_queue"; tier = 1; role = "agent_mq"; mirror = "awesome_extracted\avivsinai__agent-message-queue"; claim_state = "claim_weld_skills_subset"; invoke = "amq-* skills" }
    @{ id = "codex_mem"; tier = 1; role = "memory_skills"; mirror = "awesome_extracted\2kDarki__codex-mem"; claim_state = "claim_weld_skills_subset"; invoke = "mem-* skills" }
    @{ id = "everything_claude_code"; tier = 1; role = "toolbox_reference"; mirror = "awesome_extracted\affaan-m__everything-claude-code"; claim_state = "mirror_claimed_no_full_install"; invoke = "pattern borrow only; do not wholesale copy" }
    @{ id = "claude_skills_300"; tier = 1; role = "skills_supermarket"; mirror = "awesome_extracted\alirezarezvani__claude-skills"; claim_state = "mirror_claimed_no_full_install"; invoke = "forbid full 300 install; pick on demand" }
    @{ id = "temporal_official"; tier = 1; role = "durable_333_carrier"; mirror = "official\temporalio__temporal"; claim_state = "surface_333_not_grok_default_engine"; invoke = "S compose / task_entry claim; not Grok chat owner" }
    @{ id = "langgraph_official"; tier = 1; role = "wave_graph_333"; mirror = "official\langchain-ai__langgraph"; claim_state = "surface_333_not_grok_default_engine"; invoke = "integrated bus wave" }
    @{ id = "langfuse_official"; tier = 1; role = "observe_eval"; mirror = "official\langfuse__langfuse"; claim_state = "mirror_claimed_not_hooked"; invoke = "future M4 observe; not default yet" }
    @{ id = "humanlayer_official"; tier = 1; role = "hitl"; mirror = "official\humanlayer__humanlayer"; claim_state = "mirror_claimed_not_hooked"; invoke = "HITL pattern; not default shell" }
    @{ id = "openhands_official"; tier = 1; role = "coding_sandbox_worker"; mirror = "official\OpenHands__OpenHands"; claim_state = "registered_dormant_claim"; invoke = "Invoke-GrokOpenHandsSmokeWhenDocker.ps1" }
    @{ id = "mem0_official"; tier = 1; role = "long_memory"; mirror = "official\mem0ai__mem0"; claim_state = "mirror_claimed_not_mainline"; invoke = "checkpoint/MEMORY primary; mem0 optional later" }
    @{ id = "letta_official"; tier = 1; role = "agent_memory"; mirror = "official\letta-ai__letta"; claim_state = "mirror_claimed_not_mainline"; invoke = "optional later" }
    @{ id = "openclaw_stack"; tier = 2; role = "deferred_forbidden_default"; mirror = $null; claim_state = "explicitly_not_welded"; invoke = "do not install as second brain" }
)

function Write-JsonFile([string]$Path, [object]$Obj) {
    [System.IO.File]::WriteAllText($Path, ($Obj | ConvertTo-Json -Depth 16), $utf8)
}

function Get-ClaimRows {
    $rows = @()
    foreach ($c in $carrierClaims) {
        $full = if ($c.mirror) { Join-Path $mirrorRoot $c.mirror } else { $null }
        $onDisk = if ($full) { Test-Path -LiteralPath $full } else { $false }
        $rows += [ordered]@{
            id          = $c.id
            tier        = $c.tier
            role        = $c.role
            mirror_rel  = $c.mirror
            on_disk     = $onDisk
            claim_state = $c.claim_state
            now_can_invoke_hint = $c.invoke
            re_mirror   = $false
        }
    }
    return $rows
}

function Get-SkillPlan {
    $items = @()
    foreach ($s in $skillWelds) {
        $src = Join-Path $mirrorRoot $s.src
        $dst = Join-Path $LaneSkillsRoot $s.id
        $items += [ordered]@{
            id           = $s.id
            source       = $src
            target       = $dst
            source_ok    = (Test-Path -LiteralPath $src)
            already_weld = (Test-Path -LiteralPath $dst)
        }
    }
    return $items
}

function Invoke-Junction([string]$Dst, [string]$Src) {
    if (Test-Path -LiteralPath $Dst) { return "skipped_exists" }
    if (-not (Test-Path -LiteralPath $Src)) { return "source_missing" }
    $null = cmd /c "mklink /J `"$Dst`" `"$Src`""
    if (Test-Path -LiteralPath $Dst) { return "junction_ok" }
    return "junction_failed"
}

$scope = [ordered]@{
    window_cn        = "Grok 4.5 能力面 only"
    not_touch        = @("task_queue.json", "Invoke-GrokLongWorkflowRunNext", "Wave drain for other Grok")
    principle_cn     = "E盘已有 → claim + 薄焊 + 默认可 invoke；禁止 re-mirror / 整包第三条链"
}

if ($Status -or (-not $Plan -and -not $Apply)) {
    if (Test-Path -LiteralPath $latestPath) {
        if (-not $Quiet) { Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 }
        exit 0
    }
    $planOnly = [ordered]@{
        schema_version = "xinao.grok_capability_surface_claim.plan.v1"
        scope          = $scope
        carriers       = @(Get-ClaimRows)
        skills         = @(Get-SkillPlan)
        lane_skills    = $LaneSkillsRoot
        generated_at   = (Get-Date).ToString("o")
    }
    if (-not $Quiet) { $planOnly | ConvertTo-Json -Depth 12 }
    exit 0
}

if ($Plan) {
    $planOnly = [ordered]@{
        schema_version = "xinao.grok_capability_surface_claim.plan.v1"
        scope          = $scope
        carriers       = @(Get-ClaimRows)
        skills         = @(Get-SkillPlan)
        lane_skills    = $LaneSkillsRoot
        generated_at   = (Get-Date).ToString("o")
    }
    Write-JsonFile (Join-Path $stateRoot "plan_latest.json") $planOnly
    if (-not $Quiet) { $planOnly | ConvertTo-Json -Depth 12 }
    exit 0
}

if ($Apply) {
    $welded = @(); $skipped = @(); $failed = @()
    if (-not $SkipSkillJunction) {
        New-Item -ItemType Directory -Force -Path $LaneSkillsRoot | Out-Null
        foreach ($s in $skillWelds) {
            $src = Join-Path $mirrorRoot $s.src
            $dst = Join-Path $LaneSkillsRoot $s.id
            $r = Invoke-Junction -Dst $dst -Src $src
            $row = [ordered]@{ id = $s.id; source = $src; target = $dst; result = $r }
            switch ($r) {
                "junction_ok" { $welded += $row }
                "skipped_exists" { $skipped += $row }
                default { $failed += $row }
            }
        }
    }

    # Optional: OpenHands smoke claim refresh (does not start long tasks for other window)
    $ohSmoke = $null
    $ohScript = Join-Path $bridge "Invoke-GrokOpenHandsSmokeWhenDocker.ps1"
    if (Test-Path $ohScript) {
        try {
            # Only probe docker info path if already recorded; full pull may be heavy — call script
            & $ohScript 2>&1 | Out-Null
            $ohPath = Join-Path $runtime "state\openhands_smoke\latest.json"
            if (Test-Path $ohPath) { $ohSmoke = Get-Content $ohPath -Raw -Encoding UTF8 | ConvertFrom-Json }
        } catch {
            $ohSmoke = [ordered]@{ error = "$_" }
        }
    }

    $laneList = @(Get-ChildItem -LiteralPath $LaneSkillsRoot -Directory -EA SilentlyContinue | ForEach-Object { $_.Name })
    $spCount = @($laneList | Where-Object { $_ -like "sp-*" }).Count
    $awsCount = @($laneList | Where-Object { $_ -like "aws-*" }).Count
    $apCount = @($laneList | Where-Object { $_ -like "ap-*" }).Count
    $amqCount = @($laneList | Where-Object { $_ -like "amq-*" }).Count
    $memCount = @($laneList | Where-Object { $_ -like "mem-*" }).Count

    $result = [ordered]@{
        schema_version   = "xinao.grok_capability_surface_claim.result.v1"
        sentinel         = "SENTINEL:GROK_CAPABILITY_SURFACE_CLAIM"
        generated_at     = (Get-Date).ToString("o")
        scope            = $scope
        lane_skills_root = $LaneSkillsRoot
        carriers         = @(Get-ClaimRows)
        skill_weld       = [ordered]@{
            welded  = $welded
            skipped = $skipped
            failed  = $failed
        }
        skill_inventory  = [ordered]@{
            total_dirs = $laneList.Count
            sp         = $spCount
            aws        = $awsCount
            ap         = $apCount
            amq        = $amqCount
            mem        = $memCount
            ts         = @($laneList | Where-Object { $_ -like "ts-*" }).Count
            names      = $laneList
        }
        openhands_smoke  = $ohSmoke
        now_can_invoke   = @(
            "Get-ChildItem $LaneSkillsRoot",
            "skills: sp-* aws-* ap-* amq-* mem-* ts-task-planner",
            "Invoke-GrokIsomorphicCapabilityWeld.ps1 -Status",
            "Invoke-GrokCapabilitySurfaceClaimWeld.ps1 -Status",
            "Invoke-GrokOpenHandsSmokeWhenDocker.ps1"
        )
        not_done_cn = @(
            "Langfuse/Humanlayer/Mem0 未 hook 默认主路",
            "everything-claude-code / 300 skills 故意不全装",
            "OpenHands 可能仍 dormant/需 docker pull",
            "装进 skills ≠ 大包跑穿；completion_claim_allowed 仍 false"
        )
        completion_claim_allowed = $false
        honesty_cn = "claim+薄焊扩大 Grok 能力界面；不宣布 P0/333 闭合；不抢他窗任务队列"
    }
    Write-JsonFile $latestPath $result
    Write-JsonFile (Join-Path $stateRoot ("claim_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))) $result
    # human readback
    $rb = Join-Path $runtime "readback\zh"
    New-Item -ItemType Directory -Force -Path $rb | Out-Null
    $md = @(
        "# Grok 能力面 claim+薄焊 ($(Get-Date -Format o))",
        "",
        "- lane: $LaneSkillsRoot",
        "- skills total: $($laneList.Count) (sp=$spCount aws=$awsCount ap=$apCount amq=$amqCount mem=$memCount)",
        "- welded this run: $($welded.Count) skipped: $($skipped.Count) failed: $($failed.Count)",
        "- 未碰 shared task_queue",
        "- completion_claim_allowed=false",
        "",
        "## now_can_invoke",
        ($result.now_can_invoke | ForEach-Object { "- $_" }) -join "`n"
    ) -join "`n"
    [System.IO.File]::WriteAllText((Join-Path $rb "grok_capability_surface_claim_latest.md"), $md, $utf8)

    if (-not $Quiet) { $result | ConvertTo-Json -Depth 14 }
    if ($failed.Count -gt 0) { exit 2 }
    exit 0
}
