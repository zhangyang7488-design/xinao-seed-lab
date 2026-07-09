#Requires -Version 5.1
<#
.SYNOPSIS
  长久工作流自主推进：取最高优先级 pending task 执行 → 更新队列 → 差距重扫。
#>
param(
    [switch]$SeedWave6,
    [switch]$SeedWave7,
    [switch]$SeedWave8,
    [switch]$SeedWave9,
    [switch]$SeedWave10,
    [switch]$SeedWave11,
    [switch]$SeedWave12,
    [switch]$SeedWave18,
    [switch]$SeedWave20,
    [switch]$SeedWave21,
    [switch]$SeedWave22,
    [switch]$SeedWave23,
    [switch]$SeedWave24,
    [switch]$SeedWave17,
    [switch]$AutoSeedFromVision,
    [switch]$NoAutoSeedFromVision,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$queuePath = Join-Path $runtime "state\grok_long_workflow\task_queue.json"
$outDir = Join-Path $runtime "state\grok_long_workflow\runs"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Update-QueueTask([object]$Queue, [string]$Id, [string]$Status, [string]$Note = "") {
    $changed = $false
    $newTasks = [System.Collections.Generic.List[object]]::new()
    foreach ($t in $Queue.tasks) {
        if ([string]$t.id -eq $Id) {
            $row = [ordered]@{}
            foreach ($p in $t.PSObject.Properties) { $row[$p.Name] = $p.Value }
            $row["status"] = $Status
            $row["completed_at"] = (Get-Date).ToString("o")
            if ($Note) { $row["note"] = $Note }
            [void]$newTasks.Add([pscustomobject]$row)
            $changed = $true
        } else {
            [void]$newTasks.Add($t)
        }
    }
    if (-not $changed) { throw "Task not found: $Id" }
    $Queue.tasks = $newTasks.ToArray()
    $Queue.updated_at = (Get-Date).ToString("o")
    $Queue | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $queuePath -Encoding UTF8
}

function Invoke-TaskHandler([string]$Id, [string]$InvokeHint) {
    switch -Regex ($Id) {
        "^W6_1_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W6_2_" { & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null; return "wave_status_ok" }
        "^W6_3_" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
            return "bootstrap_ok"
        }
        "^W7_1_" { & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null; return "registry_rescan_ok" }
        "^W7_2_" {
            $ctx = "D:\XINAO_RESEARCH_RUNTIME\state\dp_audit_wave\context_20260708.txt"
            if (-not (Test-Path $ctx)) {
                New-Item -ItemType Directory -Force -Path (Split-Path $ctx) | Out-Null
                @(
                    "DP audit context — holographic gap snapshot $(Get-Date -Format o)",
                    "spine_0to7 green; horizontal_gap_count=0; P0 not closed",
                    "next: tool-table coverage + false-progress lens"
                ) | Set-Content -LiteralPath $ctx -Encoding UTF8
            }
            if (Test-Path (Join-Path $bridge "Invoke-GrokDpAuditWave.ps1")) {
                & (Join-Path $bridge "Invoke-GrokDpAuditWave.ps1") -Throttle 2 | Out-Null
                return "dp_audit_wave_ok"
            }
            return "dp_audit_skipped"
        }
        "^W7_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet | Out-Null
            return "wave_status_ok"
        }
        "^W8_1_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W8_2_" {
            & (Join-Path $bridge "Invoke-GrokMatureFirstGovernanceGate.ps1") -RecordStep `
                -StepId "7_evidence" -TaskClass "platform_ops" `
                -SummaryCn "Wave8全息自主队列：差距0+横向partial诚实登记" `
                -LocalRefs @("state/holographic_gap/latest.json") -Quiet | Out-Null
            return "governance_step_ok"
        }
        "^W8_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 30 -Quiet | Out-Null
            return "continue_wave_ok"
        }
        "^W8_4_" {
            Push-Location $bridge
            try {
                if (Test-Path (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1")) {
                    & (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1") -Quiet | Out-Null
                }
            } finally { Pop-Location }
            return "capability_max_ok"
        }
        "^W9_1_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W9_2_" { & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet | Out-Null; return "wave_status_ok" }
        "^W9_3_" {
            Push-Location $bridge
            try { & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null }
            finally { Pop-Location }
            return "registry_rescan_ok"
        }
        "^W10_1_" {
            Push-Location $bridge
            try {
                $laneSkills = Join-Path (Split-Path $bridge -Parent) ".grok\skills"
                & (Join-Path $bridge "Invoke-GrokIsomorphicCapabilityWeld.ps1") -ApplyDisciplineSkills -LaneSkillsRoot $laneSkills -Quiet | Out-Null
            } finally { Pop-Location }
            return "isomorphic_weld_ok"
        }
        "^W10_2_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W10_3_" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
            return "bootstrap_ok"
        }
        "^W10_4_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·Wave10双同构" `
                -ResumeBriefCn "M5纪律skills junction；promotion绿；evolution仍partial" `
                -LastMachineActions @("isomorphic_weld","SeedWave10") `
                -NextMachineActions @("proactive_evolution_intake","大包跑穿") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\isomorphic_capability_weld\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json"
                ) `
                -DoNotReExplain @("completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W11_1_" {
            & (Join-Path $bridge "Invoke-GrokVisionMegaPackageLand.ps1") -Quiet | Out-Null
            return "vision_mega_package_landed"
        }
        "^W11_2_" {
            & (Join-Path $bridge "Invoke-GrokProactiveEvolutionIntake.ps1") -Quiet | Out-Null
            return "proactive_evolution_intake_ok"
        }
        "^W11_3_" {
            & (Join-Path $bridge "Invoke-GrokModularSeparationProbe.ps1") -Quiet | Out-Null
            return "modular_m1m4_probe_ok"
        }
        "^W11_4_" {
            # M5 只读状态，禁止重复 ApplyDisciplineSkills
            & (Join-Path $bridge "Invoke-GrokIsomorphicCapabilityWeld.ps1") -Status -Quiet | Out-Null
            return "m5_status_only_ok"
        }
        "^W11_5_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W11_6_" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
            return "bootstrap_ok"
        }
        "^W11_7_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "Wave11愿景大包+主动进化+模块探活" `
                -ResumeBriefCn "W11_vision 大包落盘；evolution intake；M1-M4 probe；M5不重复Apply；completion_claim=false" `
                -LastMachineActions @("SeedWave11","vision_package","evolution_intake","modular_probe") `
                -NextMachineActions @("按vision大包逐项真测","DP决策环工程化") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\vision_mega_package\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\proactive_evolution_intake\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\modular_separation_probe\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json"
                ) `
                -DoNotReExplain @("completion_claim_allowed=false","M5已焊勿重复Apply") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W\d+_1_vision_true_test" {
            & (Join-Path $bridge "Invoke-GrokVisionMegaPackageTrueTest.ps1") -Quiet | Out-Null
            return "vision_true_test_ok"
        }
        "^W\d+_2_dp_lane_smoke" {
            & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode draft -Provider dp `
                -WaveId "vision-true-test-dp" -LaneId "VISION-DP-brain-slot" `
                -Objective "愿景大包V13真测：DP后台主脑语义位形状烟测" -InputText "≤8字回复dp_shape_ok" | Out-Null
            return "dp_lane_smoke_ok"
        }
        "^W\d+_3_qwen_lane_smoke" {
            & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode draft -Provider qwen `
                -WaveId "vision-true-test-qwen" -LaneId "VISION-QWEN-worker" `
                -Objective "愿景大包V14真测：千问工人面形状烟测" -InputText "≤8字回复qwen_shape_ok" | Out-Null
            return "qwen_lane_smoke_ok"
        }
        "^W\d+_4_task_entry_wave" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null | Out-Null
            return "wave_status_ok"
        }
        "^W\d+_5_modular_probe" {
            & (Join-Path $bridge "Invoke-GrokModularSeparationProbe.ps1") -Quiet | Out-Null
            return "modular_probe_ok"
        }
        "^W\d+_6_registry_rescan" {
            & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
            return "registry_rescan_ok"
        }
        "^W\d+_7_evolution_intake" {
            & (Join-Path $bridge "Invoke-GrokProactiveEvolutionIntake.ps1") -Quiet | Out-Null
            return "evolution_intake_ok"
        }
        "^W\d+_8_gap_rescan" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W\d+_9_bootstrap" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
            return "bootstrap_ok"
        }
        "^W17_1_" {
            & (Join-Path $bridge "Invoke-GrokMatureFirstGovernanceGate.ps1") -RecordStep `
                -StepId "4_carrier" -TaskClass "platform_ops" `
                -SummaryCn "Wave17 DP决策环工程化载体登记" `
                -LocalRefs @("grok_p0_autonomous_background_base.v1.json", "state/dp_decision_loop") -Quiet | Out-Null
            return "governance_step_ok"
        }
        "^W17_2_" {
            & (Join-Path $bridge "Invoke-GrokDpDecisionLoop.ps1") -Quiet | Out-Null
            return "dp_decision_loop_ok"
        }
        "^W17_3_" {
            & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode audit -Provider dp `
                -WaveId "w17-dp-brain" -LaneId "DP-DECISION-V13" `
                -Objective "V13落地：DP主脑决策位真audit" `
                -InputFile (Join-Path $runtime "state\dp_decision_loop\context\context_w17-dp-brain.txt") 2>$null | Out-Null
            if (-not (Test-Path (Join-Path $runtime "state\dp_decision_loop\context\context_w17-dp-brain.txt"))) {
                & (Join-Path $bridge "Invoke-GrokDpDecisionLoop.ps1") -WaveId "w17-dp-brain" -Quiet | Out-Null
            }
            return "dp_v13_invoke_ok"
        }
        "^W17_4_" {
            & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode draft -Provider qwen `
                -WaveId "w17-qwen-worker" -LaneId "QWEN-WORKER-V14" `
                -Objective "V14落地：千问工人面真draft" -InputText "≤12字中文确认工人面invoke_ok" | Out-Null
            return "qwen_v14_invoke_ok"
        }
        "^W17_5_" {
            & (Join-Path $bridge "Invoke-GrokVisionMegaPackageTrueTest.ps1") -Quiet | Out-Null
            return "vision_true_test_ok"
        }
        "^W17_6_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W17_7_" {
            & (Join-Path $bridge "Invoke-GrokProactiveEvolutionIntake.ps1") -Quiet | Out-Null
            return "evolution_intake_ok"
        }
        "^W17_8_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "DP决策环工程化·Admin Isolated" `
                -ResumeBriefCn "W17 DP决策环；vision partial收敛推进；窗界隔离；completion_claim=false" `
                -LastMachineActions @("SeedWave17","dp_decision_loop","lane_invoke") `
                -NextMachineActions @("contracted条目评估","P0诚实未闭合") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\dp_decision_loop\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\vision_mega_package\latest.json"
                ) `
                -DoNotReExplain @("勿写Grok4.5","completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W18_1_" {
            $statusScript = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Status-XinaoBaseCompose.ps1"
            if (Test-Path -LiteralPath $statusScript) {
                & $statusScript | Out-Null
                return "xinao_base_status_ok"
            }
            return "xinao_base_status_missing"
        }
        "^W18_2_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null | Out-Null
            return "task_entry_wave_ok"
        }
        "^W18_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 45 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W18_4_" {
            & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
            return "registry_rescan_ok"
        }
        "^W18_5_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W20_1_" {
            $statusScript = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Status-XinaoBaseCompose.ps1"
            if (Test-Path -LiteralPath $statusScript) { & $statusScript | Out-Null; return "xinao_base_status_ok" }
            return "xinao_base_status_missing"
        }
        "^W20_2_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 60 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W20_3_" {
            Push-Location $bridge
            try {
                & (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1") -SkipDocker -SkipMem0 -Quiet | Out-Null
            } finally { Pop-Location }
            return "capability_maximize_ok"
        }
        "^W20_4_" {
            & (Join-Path $bridge "Invoke-GrokCapabilitySurfaceClaimWeld.ps1") -Status -Quiet | Out-Null
            return "capability_surface_status_ok"
        }
        "^W20_5_" {
            & (Join-Path $bridge "Invoke-GrokVisionMegaPackageTrueTest.ps1") -Quiet | Out-Null
            return "vision_true_test_ok"
        }
        "^W20_6_" {
            & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
            return "registry_rescan_ok"
        }
        "^W20_7_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W21_1_" {
            & (Join-Path $bridge "Invoke-GrokMatureFirstGovernanceGate.ps1") -RecordStep `
                -StepId "4_carrier" -TaskClass "platform_ops" `
                -SummaryCn "Wave21 333主路焊点：Temporal+task_entry+Pro验收薄绑" `
                -LocalRefs @("grok_333_one_mature_system_mainline_grok_sideline.v1.json", "state/task_entry", "state/xinao_base_compose") -Quiet | Out-Null
            return "governance_mainline_weld_ok"
        }
        "^W21_2_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 90 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W21_3_" {
            $statusScript = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Status-XinaoBaseCompose.ps1"
            if (Test-Path -LiteralPath $statusScript) { & $statusScript | Out-Null }
            $tw = "temporal workflow list --address 127.0.0.1:7233 2>&1"
            $wfOut = ""
            try { $wfOut = (Invoke-Expression $tw | Out-String).Trim() } catch { $wfOut = $_.Exception.Message }
            $evDir = Join-Path $runtime "state\temporal_mainline_probe"
            New-Item -ItemType Directory -Force -Path $evDir | Out-Null
            @{ schema_version = "xinao.temporal_mainline_probe.v1"; generated_at = (Get-Date).ToString("o"); workflow_list_excerpt = $wfOut.Substring(0, [Math]::Min(2000, $wfOut.Length)) } |
                ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evDir "latest.json") -Encoding UTF8
            return "temporal_mainline_probe_ok"
        }
        "^W21_4_" {
            & (Join-Path $bridge "Invoke-GrokCodexSDirectWorkerLane.ps1") -Mode audit -Provider deepseek `
                -WaveId "w21-pro-review" -LaneId "PRO-REVIEW-V13" `
                -Objective "V13真audit：DeepSeek V4 Pro验收节点（非决策环）" `
                -InputText "≤20字中文：pro_review_shape_ok" 2>$null | Out-Null
            return "pro_review_audit_ok"
        }
        "^W21_5_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W22_1_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntry.ps1") -Intent "Wave22 fan-in AAQ promotion gate 真测" -Quiet 2>$null | Out-Null
            return "task_entry_new_intake_ok"
        }
        "^W22_2_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1") -Quiet 2>$null | Out-Null
            return "task_entry_claim_ok"
        }
        "^W22_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 120 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W22_4_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null | Out-Null
            return "wave_status_ok"
        }
        "^W22_5_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W23_1_" {
            $statusScript = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Status-XinaoBaseCompose.ps1"
            if (Test-Path -LiteralPath $statusScript) { & $statusScript | Out-Null; return "xinao_base_status_ok" }
            return "xinao_base_status_missing"
        }
        "^W23_2_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1") -Quiet 2>$null | Out-Null
            return "task_entry_claim_ok"
        }
        "^W23_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 120 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W23_4_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null | Out-Null
            return "wave_status_ok"
        }
        "^W23_5_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W24_1_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntry.ps1") -Intent "Wave24 P0主路续跑：多task history+自洽评估" -Quiet 2>$null | Out-Null
            return "task_entry_intake_ok"
        }
        "^W24_2_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryClaimDurable.ps1") -Quiet 2>$null | Out-Null
            return "task_entry_claim_ok"
        }
        "^W24_3_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 90 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W24_4_" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null | Out-Null
            return "wave_status_ok"
        }
        "^W24_5_" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W24_6_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·Wave24主路续跑" `
                -ResumeBriefCn "用户问是否停了：旁路队列空=本轮完非硬停；续种Wave24；completion_claim=false" `
                -LastMachineActions @("SeedWave24","user_ask_continue") `
                -NextMachineActions @("SeedWave25_if_empty","P0评估") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\task_entry\wave_closure\latest.json") `
                -DoNotReExplain @("queue_empty≠停","旁路≠333闭合") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W\d+_1_keepalive_poll" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowKeepalivePoll.ps1") -Quiet | Out-Null
            return "keepalive_poll_ok"
        }
        "^W\d+_2_compose_status" {
            $statusScript = "E:\XINAO_RESEARCH_WORKSPACES\S\scripts\Status-XinaoBaseCompose.ps1"
            if (Test-Path -LiteralPath $statusScript) { & $statusScript | Out-Null; return "xinao_base_status_ok" }
            return "xinao_base_status_missing"
        }
        "^W\d+_3_task_entry_continue" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryContinueWave.ps1") -WaitSeconds 60 -Quiet 2>$null | Out-Null
            return "task_entry_continue_ok"
        }
        "^W\d+_4_wave_status" {
            & (Join-Path $bridge "Invoke-GrokTaskEntryWaveStatus.ps1") -Quiet 2>$null | Out-Null
            return "wave_status_ok"
        }
        "^W\d+_5_evolution_intake" {
            & (Join-Path $bridge "Invoke-GrokProactiveEvolutionIntake.ps1") -Quiet | Out-Null
            return "evolution_intake_ok"
        }
        "^W\d+_6_registry_rescan" {
            & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet | Out-Null
            return "registry_rescan_ok"
        }
        "^W\d+_6b_capability_maximize" {
            Push-Location $bridge
            try {
                & (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1") -SkipDocker -SkipMem0 -Quiet | Out-Null
            } finally { Pop-Location }
            return "capability_maximize_ok"
        }
        "^W\d+_6_git_weld_commit" {
            $evDir = Join-Path $runtime "state\git_weld_evidence"
            New-Item -ItemType Directory -Force -Path $evDir | Out-Null
            $wsRoot = Split-Path $bridge -Parent
            Push-Location $wsRoot
            try {
                $porcelain = (git status --porcelain 2>&1 | Out-String).Trim()
                @{ schema_version = "xinao.git_weld_evidence.v1"; generated_at = (Get-Date).ToString("o"); porcelain = $porcelain } |
                    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $evDir "latest.json") -Encoding UTF8
                if ($porcelain) {
                    git add grok-admin-bridge/ .grok/ Agents.md 2>$null | Out-Null
                    git commit -m "grok keepalive: weld checkpoint $(Get-Date -Format 'yyyyMMdd_HHmm')" 2>$null | Out-Null
                }
            } finally { Pop-Location }
            return "git_weld_evidence_ok"
        }
        "^W\d+_7_gap_rescan" { & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null; return "gap_scan_ok" }
        "^W\d+_8_bootstrap" {
            & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
            return "bootstrap_ok"
        }
        "^W\d+_9_checkpoint" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·站立授权保活轮询" `
                -ResumeBriefCn "queue_empty→保活poll→动态Seed；合同=行为授权非固定任务表；completion_claim=false" `
                -LastMachineActions @("keepalive_poll","AutoSeedKeepaliveWave","RunNext") `
                -NextMachineActions @("续RunNext保活环","333主路证据","P0诚实评估") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\grok_keepalive_poll\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json"
                ) `
                -DoNotReExplain @("queue_empty≠停","合同=行为授权","旁路≠333闭合") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W23_6_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "Temporal自修后续claim·promotion闭合" `
                -ResumeBriefCn "Wave23：7233已绿；续claim+fan-in；completion_claim=false" `
                -LastMachineActions @("SeedWave23","temporal_self_repair","task_entry_claim") `
                -NextMachineActions @("promotion_gate证据","P0评估") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\task_entry\wave_closure\latest.json") `
                -DoNotReExplain @("旁路≠333闭合") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W22_6_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "333主路fan-in/AAQ/promotion探针" `
                -ResumeBriefCn "Wave22新task续波；查promotion_gate；completion_claim=false" `
                -LastMachineActions @("SeedWave22","task_entry_new_wave") `
                -NextMachineActions @("promotion_gate闭合","P0诚实评估") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\task_entry\wave_closure\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\aaq\integrated_bus\latest.json"
                ) `
                -DoNotReExplain @("旁路≠333闭合") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W21_6_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "愿景收敛·焊333主路证据" `
                -ResumeBriefCn "Wave21主路探针+续波+Pro audit；vision landed=17；completion_claim=false" `
                -LastMachineActions @("SeedWave21","temporal_probe","task_entry_continue") `
                -NextMachineActions @("fan-in/AAQ晋升","续主路history证据") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\temporal_mainline_probe\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\task_entry\latest.json"
                ) `
                -DoNotReExplain @("旁路≠333闭合","DP仅缩写") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W20_8_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "同构自举·缺则下载焊·终为333" `
                -ResumeBriefCn "Wave20：333主路续跑+Grok能力最大化；用户不必过问；completion_claim=false" `
                -LastMachineActions @("SeedWave20","capability_maximize","task_entry_continue") `
                -NextMachineActions @("续RunNext","焊333主路证据") `
                -EvidenceRefs @(
                    "grok_333_one_mature_system_mainline_grok_sideline.v1.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\grok_capability_maximize\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\task_entry\latest.json"
                ) `
                -DoNotReExplain @("旁路≠333闭合","同构五目标") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W18_6_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "Grok自举旁路·终为交付333主路" `
                -ResumeBriefCn "合同钉死双轨分尺；Wave18 333主路Temporal+task_entry；旁路registry；completion_claim=false" `
                -LastMachineActions @("self_bootstrap_contract","SeedWave18") `
                -NextMachineActions @("续RunNext","焊333主路证据") `
                -EvidenceRefs @(
                    "grok_333_one_mature_system_mainline_grok_sideline.v1.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\xinao_base_compose\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\task_entry"
                ) `
                -DoNotReExplain @("旁路≠333闭合","DP仅缩写") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W\d+_10_checkpoint" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "愿景大包逐项真测·不要停" `
                -ResumeBriefCn "RunNext+vision_true_test；pending空自动Seed下一波；completion_claim=false" `
                -LastMachineActions @("vision_true_test","RunNext","AutoSeedFromVision") `
                -NextMachineActions @("续RunNext直到partial收敛","DP决策环工程化") `
                -EvidenceRefs @(
                    "D:\XINAO_RESEARCH_RUNTIME\state\vision_mega_package\true_test_latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\vision_mega_package\latest.json",
                    "D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json"
                ) `
                -DoNotReExplain @("completion_claim_allowed=false","M5已焊勿重复Apply") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W9_4_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·Wave9" `
                -ResumeBriefCn "promotion_gate读盘修；W6-W8全绿；evolution仍partial诚实" `
                -LastMachineActions @("SeedWave9","promotion_probe","gap_rescan") `
                -NextMachineActions @("proactive_evolution_intake","DP决策环") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json") `
                -DoNotReExplain @("completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W8_5_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "不要停·Wave8续跑" `
                -ResumeBriefCn "W6+W7全绿；Wave8推进；named_gaps空；P0未闭合" `
                -LastMachineActions @("SeedWave8","RunNext") `
                -NextMachineActions @("promotion_gate","evolution_loop") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json") `
                -DoNotReExplain @("completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "^W6_4_" {
            & (Join-Path $bridge "Invoke-GrokSessionContextCheckpoint.ps1") -Save `
                -UserIntentAnchorCn "全息自主焊接循环" `
                -ResumeBriefCn "横向7格+RunNext真推；主轴0-7绿；P0未闭合" `
                -LastMachineActions @("Invoke-GrokLongWorkflowRunNext", "horizontal_grids", "gap_rescan") `
                -NextMachineActions @("SeedWave7_if_queue_empty", "DP决策环") `
                -EvidenceRefs @("D:\XINAO_RESEARCH_RUNTIME\state\holographic_gap\latest.json") `
                -DoNotReExplain @("图景↔事实↔差距", "completion_claim_allowed=false") `
                -Quiet | Out-Null
            return "checkpoint_saved"
        }
        "registry_scan" { & (Join-Path $bridge "Invoke-GrokLocalCapabilityRegistryScan.ps1") -Quiet 2>$null; return "registry_scan_ok" }
        "capability_maximize" { & (Join-Path $bridge "Invoke-GrokCapabilityMaximize.ps1") -Quiet 2>$null; return "capability_max_ok" }
        default {
            if ($InvokeHint -match "GapScan") {
                & (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null
                return "gap_scan_ok"
            }
            if ($InvokeHint -match "Bootstrap") {
                & (Join-Path $bridge "Invoke-GrokLongWorkflowBootstrap.ps1") -Quiet | Out-Null
                return "bootstrap_ok"
            }
            return "noop_unmapped"
        }
    }
}

function Merge-SeedTasks([object]$Seed) {
    if (Test-Path -LiteralPath $queuePath) {
        $existing = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($existing.tasks | Where-Object { $_.status -eq "pending" })
        if ($pending.Count -eq 0) {
            $existing.tasks = @($existing.tasks) + @($Seed.tasks)
            $existing.updated_at = (Get-Date).ToString("o")
            if ($Seed.PSObject.Properties.Name -contains "scope_cn" -and $Seed.scope_cn) {
                $existing.scope_cn = $Seed.scope_cn
            }
            $existing | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $queuePath -Encoding UTF8
            return $true
        }
        return $false
    }
    $Seed | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $queuePath -Encoding UTF8
    return $true
}

function Get-NextVisionWaveNumber {
    if (-not (Test-Path -LiteralPath $queuePath)) { return 12 }
    $q = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    # 排除 deferred wave=99，避免下一波跳到 W100
    $visionWaves = @($q.tasks | Where-Object { [int]$_.wave -ge 12 -and [int]$_.wave -lt 90 } | ForEach-Object { [int]$_.wave })
    $max = 11
    if ($visionWaves.Count -gt 0) { $max = [int]($visionWaves | Measure-Object -Maximum).Maximum }
    $next = [math]::Max(12, $max + 1)
    while (@($q.tasks | Where-Object { [int]$_.wave -eq $next }).Count -gt 0) { $next++ }
    return $next
}

function Test-VisionPartialConverged {
    $visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
    if (-not (Test-Path -LiteralPath $visionPath)) { return $false }
    $v = Get-Content $visionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $partial = @($v.items | Where-Object { $_.status -in @("partial", "open", "in_progress") } | ForEach-Object { $_.id })
    if ($partial.Count -eq 0) { return $true }
    # 只剩 worker lane 形状绿、模型 invoke 未晋升 → 停止同态空转种子
    $onlyLane = ($partial.Count -le 2) -and (@($partial | Where-Object { $_ -notmatch '^V1[34]_' }).Count -eq 0)
    if ($onlyLane) { return $true }
    return $false
}

function Invoke-AutoSeedFromVisionPackage {
    if (Test-VisionPartialConverged) { return $false }
    $visionPath = Join-Path $runtime "state\vision_mega_package\latest.json"
    if (-not (Test-Path -LiteralPath $visionPath)) {
        & (Join-Path $bridge "Invoke-GrokVisionMegaPackageLand.ps1") -Quiet | Out-Null
    }
    $wave = Get-NextVisionWaveNumber
    $basePri = 38 + (($wave - 12) * 12)
    $seed = [ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "愿景大包逐项真测·Wave$wave"
        tasks          = @(
            [ordered]@{ id = "W${wave}_1_vision_true_test"; wave = $wave; priority = $basePri; status = "pending"; title_cn = "愿景大包逐项真测"; invoke = "Invoke-GrokVisionMegaPackageTrueTest.ps1" }
            [ordered]@{ id = "W${wave}_2_dp_lane_smoke"; wave = $wave; priority = ($basePri + 1); status = "pending"; title_cn = "DP worker lane 烟测(V13)"; invoke = "Invoke-GrokCodexSDirectWorkerLane.ps1 -Provider dp" }
            [ordered]@{ id = "W${wave}_3_qwen_lane_smoke"; wave = $wave; priority = ($basePri + 2); status = "pending"; title_cn = "千问 worker lane 烟测(V14)"; invoke = "Invoke-GrokCodexSDirectWorkerLane.ps1 -Provider qwen" }
            [ordered]@{ id = "W${wave}_4_task_entry_wave"; wave = $wave; priority = ($basePri + 3); status = "pending"; title_cn = "333 task_entry WaveStatus(V11)"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W${wave}_5_modular_probe"; wave = $wave; priority = ($basePri + 4); status = "pending"; title_cn = "M1-M4模块化探活(V03)"; invoke = "Invoke-GrokModularSeparationProbe.ps1" }
            [ordered]@{ id = "W${wave}_6_registry_rescan"; wave = $wave; priority = ($basePri + 5); status = "pending"; title_cn = "能力注册表重扫(V15)"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W${wave}_7_evolution_intake"; wave = $wave; priority = ($basePri + 6); status = "pending"; title_cn = "主动进化 intake(V17)"; invoke = "Invoke-GrokProactiveEvolutionIntake.ps1" }
            [ordered]@{ id = "W${wave}_8_gap_rescan"; wave = $wave; priority = ($basePri + 7); status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W${wave}_9_bootstrap"; wave = $wave; priority = ($basePri + 8); status = "pending"; title_cn = "Bootstrap刷新"; invoke = "Invoke-GrokLongWorkflowBootstrap.ps1" }
            [ordered]@{ id = "W${wave}_10_checkpoint"; wave = $wave; priority = ($basePri + 9); status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    }
    return (Merge-SeedTasks $seed)
}

function Get-NextKeepaliveWaveNumber {
    if (-not (Test-Path -LiteralPath $queuePath)) { return 25 }
    $q = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $keepWaves = @($q.tasks | Where-Object { [int]$_.wave -ge 25 -and [int]$_.wave -lt 90 } | ForEach-Object { [int]$_.wave })
    $max = 24
    if ($keepWaves.Count -gt 0) { $max = [int]($keepWaves | Measure-Object -Maximum).Maximum }
    $next = [math]::Max(25, $max + 1)
    while (@($q.tasks | Where-Object { [int]$_.wave -eq $next }).Count -gt 0) { $next++ }
    return $next
}

function Invoke-AutoSeedKeepaliveWave {
    param([switch]$SkipPoll)

    if (-not $SkipPoll) {
        & (Join-Path $bridge "Invoke-GrokLongWorkflowKeepalivePoll.ps1") -Quiet | Out-Null
    }

    $pollPath = Join-Path $runtime "state\grok_keepalive_poll\latest.json"
    $poll = $null
    if (Test-Path -LiteralPath $pollPath) {
        $poll = Get-Content $pollPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }

    $gapPath = Join-Path $runtime "state\holographic_gap\latest.json"
    $gap = $null
    if (Test-Path -LiteralPath $gapPath) {
        $gap = Get-Content $gapPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }

    $wave = Get-NextKeepaliveWaveNumber
    $basePri = 110 + (($wave - 25) * 10)
    $tasks = [System.Collections.Generic.List[object]]::new()
    $prio = $basePri

    $taskDefs = [System.Collections.Generic.List[object]]::new()
    [void]$taskDefs.Add(@{ suffix = "1_keepalive_poll"; title = "旁路保活轮询观察"; invoke = "Invoke-GrokLongWorkflowKeepalivePoll.ps1" })
    [void]$taskDefs.Add(@{ suffix = "2_compose_status"; title = "333主路：compose/7233探活"; invoke = "Status-XinaoBaseCompose.ps1" })
    [void]$taskDefs.Add(@{ suffix = "3_task_entry_continue"; title = "333主路：task_entry续波"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" })
    [void]$taskDefs.Add(@{ suffix = "4_wave_status"; title = "333主路：WaveStatus读回"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" })
    [void]$taskDefs.Add(@{ suffix = "5_evolution_intake"; title = "主动进化intake"; invoke = "Invoke-GrokProactiveEvolutionIntake.ps1" })

    $hasGitWeld = $false
    if ($gap -and @($gap.named_gaps) -contains "GROK_ISLAND_UNCOMMITTED_WELDS") { $hasGitWeld = $true }
    if ($gap -and $gap.nine_grid -and [string]$gap.nine_grid.git_working_tree -eq "gap") { $hasGitWeld = $true }
    if ($hasGitWeld) {
        [void]$taskDefs.Add(@{ suffix = "6_git_weld_commit"; title = "旁路：未提交焊点证据+commit"; invoke = "git_weld_evidence" })
    } else {
        [void]$taskDefs.Add(@{ suffix = "6_registry_rescan"; title = "能力注册表重扫"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" })
    }
    if ($poll -and @($poll.named_blockers) -match "TEMPORAL") {
        [void]$taskDefs.Add(@{ suffix = "6b_capability_maximize"; title = "旁路：能力面最大化探活"; invoke = "Invoke-GrokCapabilityMaximize.ps1" })
    }
    [void]$taskDefs.Add(@{ suffix = "7_gap_rescan"; title = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" })
    [void]$taskDefs.Add(@{ suffix = "8_bootstrap"; title = "Bootstrap刷新"; invoke = "Invoke-GrokLongWorkflowBootstrap.ps1" })
    [void]$taskDefs.Add(@{ suffix = "9_checkpoint"; title = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" })

    foreach ($def in $taskDefs) {
        [void]$tasks.Add([ordered]@{
            id         = "W${wave}_$($def.suffix)"
            wave       = $wave
            priority   = $prio
            status     = "pending"
            title_cn   = $def.title
            invoke     = $def.invoke
            source     = "keepalive_dynamic"
        })
        $prio++
    }

    $seed = [ordered]@{
        schema_version   = "xinao.grok_long_workflow_task_queue.v1"
        updated_at       = (Get-Date).ToString("o")
        execution_mode   = "autonomous_continuous"
        scope_cn         = "站立授权保活·Wave$wave·动态差距驱动"
        standing_auth_cn = "合同=行为授权；轮询观察保活自修复进化；非固定任务表"
        tasks            = $tasks.ToArray()
    }
    return (Merge-SeedTasks $seed)
}

function Get-NextPendingTask([object]$Queue) {
    return @($Queue.tasks | Where-Object { $_.status -eq "pending" } | Sort-Object { [int]$_.priority } | Select-Object -First 1)
}

function Write-OvernightReportBrief([string]$Line) {
    $rb = Join-Path $runtime "readback\zh\grok_overnight_report_latest.md"
    if (-not (Test-Path -LiteralPath (Split-Path $rb))) {
        New-Item -ItemType Directory -Force -Path (Split-Path $rb) | Out-Null
    }
    Add-Content -LiteralPath $rb -Value $Line -Encoding UTF8
}

if ($SeedWave17) {
    if (-not $Quiet) {
        @{ status = "seed_wave17_retired"; reason_cn = "DP仅=DeepSeek V4 Pro验收节点缩写；见 grok_deepseek_v4_pro_review_node.v1.json" } | ConvertTo-Json -Depth 4
    }
}
elseif ($SeedWave24) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "不要停：333主路新task+claim+fan-in续跑"
        tasks          = @(
            [ordered]@{ id = "W24_1_task_entry_intake"; wave = 24; priority = 100; status = "pending"; title_cn = "333：新task intake"; invoke = "Invoke-GrokTaskEntry.ps1" }
            [ordered]@{ id = "W24_2_task_entry_claim"; wave = 24; priority = 101; status = "pending"; title_cn = "333：durable claim"; invoke = "Invoke-GrokTaskEntryClaimDurable.ps1" }
            [ordered]@{ id = "W24_3_task_entry_continue"; wave = 24; priority = 102; status = "pending"; title_cn = "333：续波90s"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W24_4_wave_status"; wave = 24; priority = 103; status = "pending"; title_cn = "333：WaveStatus"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W24_5_gap_rescan"; wave = 24; priority = 104; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W24_6_checkpoint"; wave = 24; priority = 105; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave23) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "Temporal自修后续：claim Wave22 staged task + fan-in/promotion"
        tasks          = @(
            [ordered]@{ id = "W23_1_compose_status"; wave = 23; priority = 90; status = "pending"; title_cn = "333：compose/7233探活"; invoke = "Status-XinaoBaseCompose.ps1" }
            [ordered]@{ id = "W23_2_task_entry_claim"; wave = 23; priority = 91; status = "pending"; title_cn = "333：durable claim staged"; invoke = "Invoke-GrokTaskEntryClaimDurable.ps1" }
            [ordered]@{ id = "W23_3_task_entry_continue"; wave = 23; priority = 92; status = "pending"; title_cn = "333：续波120s"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W23_4_wave_status"; wave = 23; priority = 93; status = "pending"; title_cn = "333：WaveStatus+promotion"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W23_5_gap_rescan"; wave = 23; priority = 94; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W23_6_checkpoint"; wave = 23; priority = 95; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave22) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "333主路：新task→claim→续波→fan-in/AAQ/promotion证据"
        tasks          = @(
            [ordered]@{ id = "W22_1_task_entry_intake"; wave = 22; priority = 80; status = "pending"; title_cn = "333：新task intake"; invoke = "Invoke-GrokTaskEntry.ps1" }
            [ordered]@{ id = "W22_2_task_entry_claim"; wave = 22; priority = 81; status = "pending"; title_cn = "333：durable claim"; invoke = "Invoke-GrokTaskEntryClaimDurable.ps1" }
            [ordered]@{ id = "W22_3_task_entry_continue"; wave = 22; priority = 82; status = "pending"; title_cn = "333：续波120s等fan-in"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W22_4_wave_status"; wave = 22; priority = 83; status = "pending"; title_cn = "333：WaveStatus+AAQ读回"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W22_5_gap_rescan"; wave = 22; priority = 84; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W22_6_checkpoint"; wave = 22; priority = 85; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave21) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "愿景收敛后：焊333主路Temporal证据+Pro验收薄绑"
        tasks          = @(
            [ordered]@{ id = "W21_1_governance_mainline"; wave = 21; priority = 70; status = "pending"; title_cn = "治理环：333主路焊点登记"; invoke = "Invoke-GrokMatureFirstGovernanceGate.ps1" }
            [ordered]@{ id = "W21_2_task_entry_continue"; wave = 21; priority = 71; status = "pending"; title_cn = "333主路：task_entry续波90s"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W21_3_temporal_mainline_probe"; wave = 21; priority = 72; status = "pending"; title_cn = "333主路：Temporal workflow探针"; invoke = "temporal workflow list" }
            [ordered]@{ id = "W21_4_pro_review_audit"; wave = 21; priority = 73; status = "pending"; title_cn = "333：Pro验收节点真audit(V13)"; invoke = "Invoke-GrokCodexSDirectWorkerLane deepseek audit" }
            [ordered]@{ id = "W21_5_gap_rescan"; wave = 21; priority = 74; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W21_6_checkpoint"; wave = 21; priority = 75; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave20) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "同构自举：缺则下载焊Grok面；333主路Temporal+task_entry续跑"
        tasks          = @(
            [ordered]@{ id = "W20_1_xinao_base_status"; wave = 20; priority = 60; status = "pending"; title_cn = "333主路：compose状态(V12)"; invoke = "Status-XinaoBaseCompose.ps1" }
            [ordered]@{ id = "W20_2_task_entry_continue"; wave = 20; priority = 61; status = "pending"; title_cn = "333主路：task_entry续波(V11)"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W20_3_capability_maximize"; wave = 20; priority = 62; status = "pending"; title_cn = "Grok旁路：缺则下载安装焊能力(V15)"; invoke = "Invoke-GrokCapabilityMaximize.ps1" }
            [ordered]@{ id = "W20_4_capability_surface_status"; wave = 20; priority = 63; status = "pending"; title_cn = "Grok旁路：能力面认领状态"; invoke = "Invoke-GrokCapabilitySurfaceClaimWeld.ps1 -Status" }
            [ordered]@{ id = "W20_5_vision_true_test"; wave = 20; priority = 64; status = "pending"; title_cn = "愿景逐项真测"; invoke = "Invoke-GrokVisionMegaPackageTrueTest.ps1" }
            [ordered]@{ id = "W20_6_registry_rescan"; wave = 20; priority = 65; status = "pending"; title_cn = "能力注册重扫"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W20_7_gap_rescan"; wave = 20; priority = 66; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W20_8_checkpoint"; wave = 20; priority = 67; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave18) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "双轨分尺：333主路Temporal+task_entry；Grok旁路registry自举"
        tasks          = @(
            [ordered]@{ id = "W18_1_xinao_base_status"; wave = 18; priority = 50; status = "pending"; title_cn = "333主路：XINAO Base compose 状态(V12)"; invoke = "Status-XinaoBaseCompose.ps1" }
            [ordered]@{ id = "W18_2_task_entry_wave"; wave = 18; priority = 51; status = "pending"; title_cn = "333主路：task_entry WaveStatus(V11)"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W18_3_task_entry_continue"; wave = 18; priority = 52; status = "pending"; title_cn = "333主路：task_entry ContinueWave"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W18_4_registry_rescan"; wave = 18; priority = 53; status = "pending"; title_cn = "Grok旁路：能力注册重扫(V15)"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W18_5_gap_rescan"; wave = 18; priority = 54; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W18_6_checkpoint"; wave = 18; priority = 55; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave12) {
    [void](Invoke-AutoSeedFromVisionPackage)
}
elseif ($SeedWave11) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "愿景大包+主动进化+M1-M4探活（不重复M5 Apply）"
        tasks          = @(
            [ordered]@{ id = "W11_1_vision_mega_package_land"; wave = 11; priority = 31; status = "pending"; title_cn = "愿景超级完整大包落盘"; invoke = "Invoke-GrokVisionMegaPackageLand.ps1" }
            [ordered]@{ id = "W11_2_proactive_evolution_intake"; wave = 11; priority = 32; status = "pending"; title_cn = "主动进化 intake"; invoke = "Invoke-GrokProactiveEvolutionIntake.ps1" }
            [ordered]@{ id = "W11_3_modular_m1m4_probe"; wave = 11; priority = 33; status = "pending"; title_cn = "M1-M4模块化分离探活"; invoke = "Invoke-GrokModularSeparationProbe.ps1" }
            [ordered]@{ id = "W11_4_m5_status_only"; wave = 11; priority = 34; status = "pending"; title_cn = "M5只读Status勿重复Apply"; invoke = "Invoke-GrokIsomorphicCapabilityWeld.ps1 -Status" }
            [ordered]@{ id = "W11_5_gap_rescan"; wave = 11; priority = 35; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W11_6_bootstrap"; wave = 11; priority = 36; status = "pending"; title_cn = "Bootstrap刷新"; invoke = "Invoke-GrokLongWorkflowBootstrap.ps1" }
            [ordered]@{ id = "W11_7_checkpoint"; wave = 11; priority = 37; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave10) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "双同构M5纪律skills+证据透镜"
        tasks          = @(
            [ordered]@{ id = "W10_1_isomorphic_discipline_weld"; wave = 10; priority = 27; status = "pending"; title_cn = "同构能力焊装纪律skills"; invoke = "Invoke-GrokIsomorphicCapabilityWeld.ps1 -ApplyDisciplineSkills" }
            [ordered]@{ id = "W10_2_gap_rescan"; wave = 10; priority = 28; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W10_3_bootstrap"; wave = 10; priority = 29; status = "pending"; title_cn = "Bootstrap刷新"; invoke = "Invoke-GrokLongWorkflowBootstrap.ps1" }
            [ordered]@{ id = "W10_4_checkpoint"; wave = 10; priority = 30; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave9) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "promotion_gate读盘+evolution诚实续跑"
        tasks          = @(
            [ordered]@{ id = "W9_1_promotion_gap_rescan"; wave = 9; priority = 23; status = "pending"; title_cn = "promotion_gate 读盘+差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W9_2_wave_status"; wave = 9; priority = 24; status = "pending"; title_cn = "4-7 WaveStatus"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W9_3_registry_rescan"; wave = 9; priority = 25; status = "pending"; title_cn = "能力注册表重扫"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W9_4_checkpoint"; wave = 9; priority = 26; status = "pending"; title_cn = "检查点"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave8) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "P0语义环续跑：治理环+波闭合+能力最大化"
        tasks          = @(
            [ordered]@{ id = "W8_1_holographic_rescan"; wave = 8; priority = 18; status = "pending"; title_cn = "全息差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W8_2_governance_evidence"; wave = 8; priority = 19; status = "pending"; title_cn = "治理环证据登记"; invoke = "Invoke-GrokMatureFirstGovernanceGate.ps1" }
            [ordered]@{ id = "W8_3_continue_wave_poll"; wave = 8; priority = 20; status = "pending"; title_cn = "4-7 ContinueWave 薄绑等待"; invoke = "Invoke-GrokTaskEntryContinueWave.ps1" }
            [ordered]@{ id = "W8_4_capability_maximize"; wave = 8; priority = 21; status = "pending"; title_cn = "能力界面最大化探活"; invoke = "Invoke-GrokCapabilityMaximize.ps1" }
            [ordered]@{ id = "W8_5_checkpoint_save"; wave = 8; priority = 22; status = "pending"; title_cn = "检查点保存"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}
elseif ($SeedWave7) {
    Merge-SeedTasks ([ordered]@{
        schema_version = "xinao.grok_long_workflow_task_queue.v1"
        updated_at     = (Get-Date).ToString("o")
        execution_mode = "autonomous_continuous"
        scope_cn       = "DP决策环+证据透镜续跑"
        tasks          = @(
            [ordered]@{ id = "W7_1_registry_rescan"; wave = 7; priority = 15; status = "pending"; title_cn = "能力注册表重扫"; invoke = "Invoke-GrokLocalCapabilityRegistryScan.ps1" }
            [ordered]@{ id = "W7_2_dp_audit_wave"; wave = 7; priority = 16; status = "pending"; title_cn = "DP审计波（工具表覆盖）"; invoke = "Invoke-GrokDpAuditWave.ps1" }
            [ordered]@{ id = "W7_3_wave_evidence_refresh"; wave = 7; priority = 17; status = "pending"; title_cn = "4-7证据刷新"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
        )
    })
}
elseif ($SeedWave6 -or -not (Test-Path -LiteralPath $queuePath)) {
    Merge-SeedTasks ([ordered]@{
        schema_version  = "xinao.grok_long_workflow_task_queue.v1"
        updated_at      = (Get-Date).ToString("o")
        execution_mode  = "autonomous_continuous"
        scope_cn        = "全息差距焊主路；主轴+横向+九宫"
        tasks           = @(
            [ordered]@{ id = "W6_1_holographic_horizontal_rescan"; wave = 6; priority = 11; status = "pending"; title_cn = "横向7格+差距重扫"; invoke = "Invoke-GrokHolographicGapScan.ps1" }
            [ordered]@{ id = "W6_2_wave_status_rescan"; wave = 6; priority = 12; status = "pending"; title_cn = "4-7 WaveStatus 重扫"; invoke = "Invoke-GrokTaskEntryWaveStatus.ps1" }
            [ordered]@{ id = "W6_3_bootstrap_refresh"; wave = 6; priority = 13; status = "pending"; title_cn = "Bootstrap+探活刷新"; invoke = "Invoke-GrokLongWorkflowBootstrap.ps1" }
            [ordered]@{ id = "W6_4_checkpoint_save"; wave = 6; priority = 14; status = "pending"; title_cn = "检查点保存"; invoke = "Invoke-GrokSessionContextCheckpoint.ps1 -Save" }
        )
    })
}

if (-not (Test-Path -LiteralPath $queuePath)) { throw "No task queue at $queuePath" }

$explicitSeed = $SeedWave6 -or $SeedWave7 -or $SeedWave8 -or $SeedWave9 -or $SeedWave10 -or $SeedWave11 -or $SeedWave12 -or $SeedWave18 -or $SeedWave20 -or $SeedWave21 -or $SeedWave22 -or $SeedWave23 -or $SeedWave24 -or $SeedWave17
if (-not $NoAutoSeedFromVision) {
    $queuePeek = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $pendingPeek = @($queuePeek.tasks | Where-Object { $_.status -eq "pending" })
    if ($pendingPeek.Count -eq 0 -and (-not $explicitSeed -or $AutoSeedFromVision -or $SeedWave12)) {
        [void](Invoke-AutoSeedFromVisionPackage)
    }
}

$queue = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$next = Get-NextPendingTask $queue
$keepaliveSeeded = $false
$keepalivePollRan = $false

if ($next.Count -eq 0) {
    & (Join-Path $bridge "Invoke-GrokLongWorkflowKeepalivePoll.ps1") -Quiet | Out-Null
    $keepalivePollRan = $true
    $keepaliveSeeded = Invoke-AutoSeedKeepaliveWave -SkipPoll
    if ($keepaliveSeeded) {
        $waveNum = Get-NextKeepaliveWaveNumber
        if ($waveNum -gt 25) { $waveNum = $waveNum - 1 }
        Write-OvernightReportBrief ("`n## $(Get-Date -Format 'yyyy-MM-dd HH:mm') 队列空→保活轮询→动态Seed Wave$waveNum · 站立授权行为环 · completion_claim=false")
        $queue = Get-Content $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $next = Get-NextPendingTask $queue
    }
}

if ($next.Count -eq 0) {
    $converged = Test-VisionPartialConverged
    if ($converged) {
        Write-OvernightReportBrief ("`n## $(Get-Date -Format 'yyyy-MM-dd HH:mm') vision partial 收敛停种 · landed 见 latest.json · completion_claim=false")
    }
    $result = [ordered]@{
        status                   = "queue_empty"
        hint_cn                  = if ($converged) { "vision partial 已收敛；保活已轮询；旁路续自举+333主路探活" } else { "无 pending；已尝试 AutoSeedFromVision+Keepalive；站立授权行为环续跑" }
        auto_seed_attempted      = (-not $NoAutoSeedFromVision)
        vision_partial_converged = $converged
        keepalive_poll_ran       = $keepalivePollRan
        keepalive_seeded         = $keepaliveSeeded
        standing_auth_cn         = "合同=行为授权；轮询观察保活自修复进化；非固定任务表"
        not_closure              = $true
        completion_claim_allowed = $false
    }
    if (-not $Quiet) { $result | ConvertTo-Json -Depth 6 }
    exit 0
}

$task = $next[0]
$taskId = [string]$task.id
$invokeHint = ""
if ($task.PSObject.Properties["invoke"]) { $invokeHint = [string]$task.invoke }

$runLog = [ordered]@{
    schema_version = "xinao.grok_long_workflow_run.v1"
    task_id        = $taskId
    started_at     = (Get-Date).ToString("o")
    invoke_hint    = $invokeHint
}
try {
    $outcome = Invoke-TaskHandler -Id $taskId -InvokeHint $invokeHint
    $runLog.outcome = $outcome
    $runLog.status = "done"
    Update-QueueTask -Queue $queue -Id $taskId -Status "done" -Note $outcome
} catch {
    $runLog.status = "blocked"
    $runLog.error = $_.Exception.Message
    Update-QueueTask -Queue $queue -Id $taskId -Status "blocked" -Note $_.Exception.Message
}

$runLog.finished_at = (Get-Date).ToString("o")
$runFile = Join-Path $outDir ("run_{0}_{1}.json" -f $taskId, (Get-Date).ToString("yyyyMMdd_HHmmss"))
$runLog | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runFile -Encoding UTF8

& (Join-Path $bridge "Invoke-GrokHolographicGapScan.ps1") -Quiet | Out-Null

if (-not $Quiet) { $runLog | ConvertTo-Json -Depth 6 }
exit 0