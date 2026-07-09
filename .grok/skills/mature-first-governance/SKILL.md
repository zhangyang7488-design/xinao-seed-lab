---
name: mature-first-governance
description: >
  Mature-first governance loop before any platform/business implementation.
  Use on EVERY platform_ops, architecture, ops, weld, or when user says 先规划/成熟优先/治理环.
  Steps: classify → external mature → local inventory → carrier → mini-ADR → deviation gate → execute → evidence.
  Slash: /governance. NOT a substitute for dialogue; plan-only hard-stops writes.
---

# 成熟优先治理环（行为宪法）

**合同：** `grok_mature_first_governance_loop.v1.json` · **策略：** `grok_mature_first_policy.v1.json`

## 何时必用

- 平台/运维/Compose/Worker/底座/焊主路
- 用户说：**先规划**、**成熟优先**、**别手搓**、**搜索外部成熟**
- `bounded_task` / `autonomous_continuous` 且触及 S 仓/bridge/compose

**可跳过落盘：** 纯 `dialogue_only` 聊天、无实施意图

## 治理环（必须按序）

| 步 | 做什么 | 产出 |
|----|--------|------|
| 0 | 归类 | platform_ops / business_wave / delivery_shell / dialogue_only |
| 1 | 外部成熟 | WebSearch/WebFetch 官方文档+repo；prior_art 一句 |
| 2 | 本地清单 | E:\镜像、S脚本、seam_map（目录，非真理） |
| 3 | 选载体 | Compose/Cloud/官方Plugin 一次集成 |
| 4 | 迷你ADR | 采纳谁、薄绑什么、证据、**不建什么** |
| 5 | 偏离门 | 无偏离 / 登记 deviation |
| 6 | 实施 | 仅 0–5 完成后 |
| 7 | 透镜 | meta_cognition 三句尺 |

## 用户口令

| 用户说 | Grok 行为 |
|--------|-----------|
| 先规划 / plan only | **硬停** 在步骤 4；禁止改文件、起进程 |
| 全权 / 焊 / 跑完 | 跑满环后实施 |

## Invoke（Grok 自己跑）

```powershell
Set-Location "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"

# 新事务开头
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -RecordStep -StepId 0_classify -TaskClass platform_ops -SummaryCn "运维底座正规化"

# 外部成熟后
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -RecordStep -StepId 1_external_first -ExternalRefs @("https://github.com/temporalio/docker-compose") -SummaryCn "prior_art: Temporal官方compose"

# 规划产物（先规划模式）
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -SavePlan -PlanMarkdown "..." 

# 实施前评估
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -Evaluate -TaskClass platform_ops -ProposedAction "docker compose up temporal"

# 读当前治理状态
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -Read
```

## 黄金路径（默认）

见合同 `golden_path_registry` — Temporal compose、LangGraph plugin、Worker 容器化、LiteLLM compose、入口薄壳+SDK。

## 硬禁（默认）

- 隐藏 `Start-Process` 当 7×24 control plane  
- ps1 串联当 orchestrator（ClaimDurable 作平台层）  
- 本地搜索冒充外部成熟  
- 未规划就实施（用户喊先规划时）  

偏离须 `-RecordDeviation` 并写 `deviations.ndjson`。