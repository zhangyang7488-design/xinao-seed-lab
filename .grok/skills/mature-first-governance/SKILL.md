---
name: mature-first-governance
description: >
  Dynamic mature-implementation contrast for choices where current external facts can change
  the carrier, topology, route, or acceptance criteria, or when the user explicitly requests research or planning.
  Local inventory and reversible state work stay local-live first. Slash: /governance.
---

# 成熟实现动态对照

合同：`grok_mature_first_governance_loop.v1.json`；策略：`grok_mature_first_policy.v1.json`。

## 何时使用

- 当前官方或成熟实现可能改变技术选择、载体、拓扑、路线或验收。
- 用户明确要求先规划、搜索外部、成熟优先或做架构对照。
- 修复共享依赖、存储层或控制面时，至少做一次能实际影响恢复方案的当前对照。

本地事实盘点、状态读取、已确定路线内的普通可回滚动作，不强制外搜、ADR 或治理落盘；直接实施并验证。外搜没有改变选择时只记录证据，不制造第二套流程。

## 最薄闭环

| 步 | 动作 | 产出 |
|---|---|---|
| 0 | 归类 | 说明外部事实是否可能改变选择 |
| 1 | 必要时对照 | 当前官方文档、上游参考代码或可信成熟集成 |
| 2 | 恢复现场 | 本地真实对象、消费者和既有决定 |
| 3 | 选择 | 采用成熟原生面，或说明为何沿用现有载体 |
| 4 | 仅在需要时留档 | 新路线、拓扑或重要偏离才写短决策记录 |
| 5 | 实施与证据 | 真实调用、fresh process 或独立证据验收 |

用户明确说 `plan only` 时停在计划，禁止实施；其他清楚的 bounded 或 continuous 请求按最薄对照直接推进。

## Invoke

从仓库根执行：

```powershell
Set-Location (Join-Path $PWD "grok-admin-bridge")

# 当前任务确实需要外部对照时
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -RecordStep -StepId 0_classify -TaskClass research_external -SummaryCn "外部事实可能改变载体"
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -RecordStep -StepId 1_external_first -ExternalRefs @("https://docs.temporal.io/") -SummaryCn "当前官方语义已改变选择"
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -RecordStep -StepId 3_choose_carrier -CarrierChoice "official_native_surface" -SummaryCn "采用官方原生面"
.\Invoke-GrokMatureFirstGovernanceGate.ps1 -Evaluate -TaskClass research_external -ProposedAction "apply thin local binding"
```

## 硬禁

- 用隐藏 `Start-Process` 建第二个常驻 control plane。
- 用 ps1 串联冒充 durable orchestrator。
- 用本地搜索冒充外部成熟研究。
- 用户明确 `plan only` 时越界实施。

只有真实偏离成熟实现并需要持续追踪时才 `-RecordDeviation`；不要为普通可回滚工作制造治理对象。
