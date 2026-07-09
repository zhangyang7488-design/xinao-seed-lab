[CmdletBinding()]
param(
    [string]$OutputRoot = "C:\Users\xx363\Desktop\GROK_GLOBAL_RULES_HARVEST_20260626",
    [string]$DivisionPath = (Join-Path $PSScriptRoot "global_rules_harvest_division.v1.json")
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$sources = @(
    @{ cat = "L0"; path = "D:\XINAO_CLEAN_RUNTIME\resources\startup\codex_l0_bootstrap.md" },
    @{ cat = "L0_B"; path = "C:\Users\xx363\CodexWorkspaces\B\nianhua\runtime\resources\startup\codex_l0_bootstrap.md" },
    @{ cat = "default_backlog"; path = "D:\XINAO_CLEAN_RUNTIME\resources\continuation\default_backlog.json" },
    @{ cat = "execution_frame"; path = "D:\XINAO_CLEAN_RUNTIME\resources\startup\codex_default_execution_frame.md" },
    @{ cat = "default_work_binding"; path = "D:\XINAO_CLEAN_RUNTIME\state\default_work_binding\latest.json" },
    @{ cat = "constitution"; path = "D:\XINAO_CLEAN_RUNTIME\resources\docs\AI_RUNTIME_OBJECT_REQUIREMENTS.md" },
    @{ cat = "behavior_kernel"; path = "D:\XINAO_CLEAN_RUNTIME\resources\docs\AI_BEHAVIOR_KERNEL.md" },
    @{ cat = "active_object"; path = "D:\XINAO_CLEAN_RUNTIME\ACTIVE_OBJECT.json" },
    @{ cat = "tx_boundary"; path = "D:\XINAO_CLEAN_RUNTIME\state\codex_default_transaction_boundary\latest.json" },
    @{ cat = "rule_authoring"; path = "D:\XINAO_CLEAN_RUNTIME\control_panel\rule_authoring_policy.md" },
    @{ cat = "safety_anti_regression"; path = "D:\XINAO_CLEAN_RUNTIME\control_panel\safety_template_anti_regression.md" },
    @{ cat = "sole_migration_grok"; path = (Join-Path $PSScriptRoot "sole_migration_architecture.v1.json") },
    @{ cat = "l0_convergence"; path = (Join-Path $PSScriptRoot "l0_global_convergence.v1.json") },
    @{ cat = "audit_division"; path = (Join-Path $PSScriptRoot "grok_parallel_audit_division.v1.json") },
    @{ cat = "harvest_division"; path = $DivisionPath },
    @{ cat = "grok_agents"; path = "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\AGENTS.md" },
    @{ cat = "grok_global_audit"; path = (Join-Path $PSScriptRoot "GROK_GLOBAL_HUMAN_AUDIT.md") },
    @{ cat = "grok_bridge_config"; path = (Join-Path $PSScriptRoot "bridge.config.json") },
    @{ cat = "b_agents"; path = "C:\Users\xx363\CodexWorkspaces\B\nianhua\AGENTS.md" },
    @{ cat = "hooks_a"; path = "C:\Users\xx363\.codex-a\hooks.json" },
    @{ cat = "hooks_b"; path = "C:\Users\xx363\.codex-b\hooks.json" },
    @{ cat = "hooks_c"; path = "C:\Users\xx363\.codex-c\hooks.json" }
)

$rawDir = Join-Path $OutputRoot "raw"
$curatedDir = $OutputRoot
New-Item -ItemType Directory -Force -Path $rawDir, $curatedDir | Out-Null

$manifest = [System.Collections.Generic.List[object]]::new()
foreach ($s in $sources) {
    $item = [ordered]@{ category = $s.cat; source_path = $s.path; copied = $false; dest = "" }
    if (Test-Path -LiteralPath $s.path) {
        $safeName = ($s.cat -replace '[^\w\-.]+', '_') + "_" + [IO.Path]::GetFileName($s.path)
        $dest = Join-Path $rawDir $safeName
        Copy-Item -LiteralPath $s.path -Destination $dest -Force
        $item.copied = $true
        $item.dest = $dest
    }
    $manifest.Add([pscustomobject]$item)
}

$grokBridgeTxt = @"
[Grok 桥接与分工规则 — 预采集 04 草稿]
生成时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
说明: 本文件为 Grok 薄绑定预写；B/C/DP worker 完成后会补充 curated 版本。

--- Grok 角色 ---
- 保全用户 semantic_object，投递 CodexA，旁路审计/喊 B/C/DP
- 非任务主、非完成裁判、非执行器
- Grok 岛与 A/B/C 隔离；A 不得写 Grok 工作区

--- 唯一事务 ---
- 中间旧承载全换外部成熟；胶水仅薄绑定
- 进度问: 用户跟 Grok 说一句话，中间还有手搓在 default 吗

--- Git/GitHub/本地仓 ---
- 非主线；deferred_cleanup 收尾层
- 事实源: D:\XINAO_CLEAN_RUNTIME\state

--- 旁路审计分工 ---
- B: 工程事实（后台 exec）
- DP: 语义缩水/假完成（LiteLLM）
- C: standby
- 喊审计时不 POST /codex-a/*

详见 Grok 工作区 grok-admin-bridge/*.json 与 AGENTS.md
"@
$grokBridgeTxt | Set-Content -LiteralPath (Join-Path $curatedDir "04_Grok桥接与分工规则.txt") -Encoding UTF8

$readme = @"
GROK 全局规则打包 — 规则地图（初稿）
=====================================
文件夹: $OutputRoot
生成: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

【你怎么读】
1. raw/     — 原文复制（未改字）
2. 01_B_*   — CodexB 工程提取（L0/仓库/运行时）
3. 02_C_*   — CodexC 备用仓提取
4. 03_DP_*  — DP 语义索引（去重、冲突、中文目录）
5. 04_Grok_*— Grok 桥接分工

【分工】
- Grok: 预采集 raw + 派工
- B/C/DP: 后台 worker 整理（不打扰 A 主线）

【注意】
- Git 脏 / GitHub 未推送 ≠ 跑偏
- PASS/canary ≠ 用户完成
- 讨论用本包，不当作已收敛完成

worker 跑完后请再看 00_README（DP 会更新）
"@
$readme | Set-Content -LiteralPath (Join-Path $curatedDir "00_README_规则地图.txt") -Encoding UTF8

$result = [ordered]@{
    schema_version = "xinao.grok_global_rules_harvest_gather.v1"
    generated_at = (Get-Date).ToString("o")
    output_root = $OutputRoot
    raw_dir = $rawDir
    files_written = @(
        "00_README_规则地图.txt",
        "04_Grok桥接与分工规则.txt"
    )
    sources = @($manifest)
    copied_count = @($manifest | Where-Object { $_.copied }).Count
    pending_worker_outputs = @(
        "01_B_工程规则_L0仓库运行时.txt",
        "02_C_工程规则_备用仓.txt",
        "03_DP_语义规则_人类可读索引.txt"
    )
}
$stateDir = "D:\XINAO_CLEAN_RUNTIME\state\grok_global_rules_harvest"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $stateDir "latest.json") -Encoding UTF8
$result | ConvertTo-Json -Depth 8