#Requires -Version 5.1
<#
.SYNOPSIS
  将用户意图/愿景落成「超级完整大包」可验收条目（抗缩包）。
  输出 D:\...\state\vision_mega_package\latest.json + readback md。
  不宣布闭合；条目供 W11 与后续波次逐项落地/真测。
#>
param([switch]$Quiet)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding $false
$bridge = $PSScriptRoot
$runtime = & (Join-Path $bridge "Resolve-GrokEvidenceRuntimeRoot.ps1")
$outDir = Join-Path $runtime "state\vision_mega_package"
$rbDir = Join-Path $runtime "readback\zh"
New-Item -ItemType Directory -Force -Path $outDir, $rbDir | Out-Null

$items = @(
    [ordered]@{ id = "V01_p0_five_goals"; surface = @("333","grok"); title_cn = "五目标：自治·自修复·自进化·全局自洽·最大能力界面"; accept_cn = "合同钉死且双方同构引用；now_can_invoke 能答谁决策"; status = "contracted"; evidence = @("grok_p0_autonomous_background_base.v1.json","grok_dual_isomorphism_modular_separation.v1.json") }
    [ordered]@{ id = "V02_dual_isomorphism"; surface = @("333","grok"); title_cn = "双方同构：能力形状相同、载体可分"; accept_cn = "dual_iso 合同 + brain/p0 挂接"; status = "landed"; evidence = @("grok_dual_isomorphism_modular_separation.v1.json") }
    [ordered]@{ id = "V03_modular_separation"; surface = @("333","grok"); title_cn = "模块化分离 M1-M5；意图可扔 Grok 或文本路径"; accept_cn = "task_entry=M1；long_workflow/claim=M2；probe 证据"; status = "in_progress"; evidence = @("grok_task_entry_module.v1.json","state/modular_separation_probe") }
    [ordered]@{ id = "V04_intent_throw_run"; surface = @("333","grok"); title_cn = "扔意图后后台自跑（不依赖讨论窗）"; accept_cn = "pending 任务可 RunNext 无人值守推进"; status = "partial"; evidence = @("state/grok_long_workflow") }
    [ordered]@{ id = "V05_mega_package_discipline"; surface = @("grok"); title_cn = "拆超级完整大包·抗缩包·抗换靶"; accept_cn = "本大包条目完整；修前置须回跳原 id"; status = "landed"; evidence = @("state/vision_mega_package/latest.json") }
    [ordered]@{ id = "V06_true_test_gate"; surface = @("333","grok"); title_cn = "真测门：invoke/失败态；禁止 latest 单独闭合"; accept_cn = "verification skill + gap completion_claim_allowed=false"; status = "partial"; evidence = @("sp-verification-before-completion","holographic_gap") }
    [ordered]@{ id = "V07_m5_discipline_skills"; surface = @("grok"); title_cn = "M5 外部成熟纪律 skills 装进自身"; accept_cn = "junction 可 ls；-Status 有证据；勿重复 Apply"; status = "landed"; evidence = @("state/isomorphic_capability_weld/latest.json") }
    [ordered]@{ id = "V08_mature_first_loop"; surface = @("grok","333"); title_cn = "成熟优先治理环 0-7 平台先落盘"; accept_cn = "governance latest 有步骤；fail-open"; status = "landed"; evidence = @("state/grok_governance") }
    [ordered]@{ id = "V09_holographic_construction"; surface = @("333","grok"); title_cn = "施工包全息：主轴+横向+九宫 图景↔事实↔差距"; accept_cn = "preamble+GapScan 实时；差距缩小尺"; status = "partial"; evidence = @("grok_construction_package_preamble.v1.json","state/holographic_gap") }
    [ordered]@{ id = "V10_long_workflow_carrier"; surface = @("grok"); title_cn = "长久工作流队列载体（非聊天自觉）"; accept_cn = "task_queue+RunNext+overnight 报告"; status = "partial"; evidence = @("grok_long_workflow_runtime.v1.json") }
    [ordered]@{ id = "V11_task_entry_333"; surface = @("333"); title_cn = "333 多样投递·单一认领·系统内分解"; accept_cn = "durable_claimed + wave 证据；壳≠owner"; status = "partial"; evidence = @("state/task_entry") }
    [ordered]@{ id = "V12_temporal_lg_carrier"; surface = @("333"); title_cn = "Temporal 耐久 + LangGraph 波内（黄金路径）"; accept_cn = "compose/worker 健康；非 start-dev 默认"; status = "partial"; evidence = @("S/docker-compose.yml","state/integrated_bus_*") }
    [ordered]@{ id = "V13_dp_brain_slot"; surface = @("333","grok"); title_cn = "DP 后台主脑语义位（非仅分配）"; accept_cn = "worker lane dp 可 invoke；modes 工程期"; status = "open"; evidence = @("Invoke-GrokCodexSDirectWorkerLane.ps1") }
    [ordered]@{ id = "V14_worker_surface"; surface = @("333","grok"); title_cn = "工人面（千问等）草稿/轻量"; accept_cn = "lane qwen 可 invoke 或诚实 blocker"; status = "open"; evidence = @("Invoke-GrokCodexSDirectWorkerLane.ps1") }
    [ordered]@{ id = "V15_registry_claim_no_zombie"; surface = @("grok"); title_cn = "能力注册：盘上有→claim→hook→可 invoke"; accept_cn = "dormant/unclaimed 减少；禁 mirror 冒充"; status = "partial"; evidence = @("state/local_capability_registry") }
    [ordered]@{ id = "V16_checkpoint_resume"; surface = @("grok"); title_cn = "检查点续接禁止重聊架构"; accept_cn = "latest.json 可读；新窗 -Read"; status = "landed"; evidence = @("state/grok_session_context") }
    [ordered]@{ id = "V17_proactive_evolution"; surface = @("grok"); title_cn = "主动进化 intake 落盘（evolution 诚实绿）"; accept_cn = "proactive_evolution_intake/latest.json 存在"; status = "in_progress"; evidence = @("state/proactive_evolution_intake") }
    [ordered]@{ id = "V18_anti_fake_green"; surface = @("333","grok"); title_cn = "反假绿：completion_claim_allowed 纪律"; accept_cn = "未完整自洽前必须 false"; status = "landed"; evidence = @("holographic_gap.completion_claim_allowed") }
    [ordered]@{ id = "V19_no_third_chain"; surface = @("333","grok"); title_cn = "禁止第三条主链/OpenClaw 整栈第二大脑"; accept_cn = "dual_iso forbidden_default 遵守"; status = "contracted"; evidence = @("grok_dual_isomorphism_modular_separation.v1.json") }
    [ordered]@{ id = "V20_desktop_no_delete"; surface = @("grok"); title_cn = "桌面默认不删；可回滚域全权"; accept_cn = "rule22 生效"; status = "contracted"; evidence = @("grok_rollback_domain_max_auth.v1.json") }
)

$counts = [ordered]@{
    total      = $items.Count
    landed     = @($items | Where-Object { $_.status -eq "landed" }).Count
    contracted = @($items | Where-Object { $_.status -eq "contracted" }).Count
    partial    = @($items | Where-Object { $_.status -eq "partial" }).Count
    in_progress= @($items | Where-Object { $_.status -eq "in_progress" }).Count
    open       = @($items | Where-Object { $_.status -eq "open" }).Count
}

$pkg = [ordered]@{
    schema_version           = "xinao.vision_mega_package.v1"
    sentinel                 = "SENTINEL:VISION_MEGA_PACKAGE"
    generated_at             = (Get-Date).ToString("o")
    title_cn                 = "用户意图愿景 · 超级完整大包（抗缩包）"
    dual_iso_ref             = "grok_dual_isomorphism_modular_separation.v1.json"
    preamble_ref             = "grok_construction_package_preamble.v1.json"
    completion_claim_allowed = $false
    honesty_cn               = "大包落盘 ≠ 跑穿；逐项真测后改 status；禁止假绿"
    counts                   = $counts
    items                    = $items
    next_land_order          = @(
        "V17_proactive_evolution",
        "V03_modular_separation",
        "V04_intent_throw_run",
        "V06_true_test_gate",
        "V13_dp_brain_slot",
        "V11_task_entry_333",
        "V12_temporal_lg_carrier"
    )
}

$latest = Join-Path $outDir "latest.json"
[System.IO.File]::WriteAllText($latest, ($pkg | ConvertTo-Json -Depth 14), $utf8)
[System.IO.File]::WriteAllText((Join-Path $outDir ("package_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))), ($pkg | ConvertTo-Json -Depth 14), $utf8)

$md = @()
$md += "# 愿景超级完整大包（$(Get-Date -Format o)）"
$md += ""
$md += "completion_claim_allowed=**false** · 条目 $($counts.total) · landed=$($counts.landed) partial=$($counts.partial) open=$($counts.open)"
$md += ""
$md += "| id | surface | status | 标题 |"
$md += "|----|---------|--------|------|"
foreach ($it in $items) {
    $surf = ($it.surface -join "+")
    $md += "| $($it.id) | $surf | $($it.status) | $($it.title_cn) |"
}
$md += ""
$md += "## 验收纪律"
$md += "- 抗缩包：未知也要挂 open，不得默删"
$md += "- 抗换靶：修前置回跳原 id"
$md += "- 真测：改 status 必须附 evidence/invoke"
$mdPath = Join-Path $rbDir "vision_mega_package_latest.md"
[System.IO.File]::WriteAllText($mdPath, ($md -join "`n"), $utf8)

if (-not $Quiet) { $pkg | ConvertTo-Json -Depth 8 }
exit 0
