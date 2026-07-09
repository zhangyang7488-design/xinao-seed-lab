---
name: gap-driven-progressor
description: Intent vs Reality gap-driven progressor + local state sense + loop guardian. Use when task starvation, global advance, autonomous progress, gap analysis, or user says 差距驱动/找不到任务/全局推进.
---

# Gap-Driven Progressor（意图-现实差距驱动推进器）

## 授权形状（钉死）

**禁止清单制（deny_list_not_allow_list），不是白名单。**

- 默认可读尽读、默认可从任意可读事实发现并合成任务
- **禁止**用「只能访问这几个目录/工具」的白名单收窄
- **只禁**真 gate：密钥原文进聊天、付款、2FA/实名、未明示不可逆删云、自指自毁、未明示删桌面
- 安全面（Trivy/Grype/OSV/Gitleaks/TruffleHog）**不当目标**
- 体量噪声（node_modules/.venv）可跳过 = 性能，**不是**权限白名单

合同：`grok_gap_driven_progressor.v1.json` · 同构 `grok_rollback_domain_max_auth.v1.json`

## 角色

你的核心职责：**持续对比全局意图与本机真实状态，自动发现并生成下一步可执行任务，驱动推进。**

| 组件 | 脚本 | 职责 |
|------|------|------|
| State Sense | `Get-GrokLocalStateSense.ps1` | 打包本机事实 |
| Progressor | `Invoke-GrokGapDrivenProgressor.ps1` | 差距分析 → 合成任务 → 推队列 / Interject |
| Loop Guardian | `Invoke-GrokLoopGuardian.ps1` | 停滞检测 → 强制 GDP |

## 输入

1. **全局意图**（持续持有）：P0 北极星、session checkpoint、full_gap goal、用户高层次「全局」
2. **本机事实**（禁止清单外默认可读）：文件/证据 JSON、Docker、端口、队列、scan-stack、PolicyScan、registry…

## 行为协议

1. 感知：`Get-GrokLocalStateSense.ps1`（可 `-Deep`）
2. 对照意图 → 列出已完成 / 进行中 / 明显差距 / 隐含待办
3. 合成可执行任务（最大化缩小差距）
4. 推入 `task_queue` 或写 Interject
5. Guardian 在停滞时强制 1–4，**禁止**只写总结报告当推进

## Interject 形状

```text
检测到意图与当前现实存在差距：[具体]
已生成任务并推入队列：[列表]
强制推进：Invoke-GrokLongWorkflowRunNext.ps1
completion_claim_allowed=false
```

## 不要做

- 不要等用户点名每个任务才行动
- 不要用白名单收窄可感知面
- 不要执行代替一切的技术大包（可生成 invoke 任务给队列）
- 不要宣称 P0 闭合
- **不要**把 GDP 做成 333 新控制面 / Temporal owner / 第三条编排链
- **不要**把岛内 `grok_long_workflow/task_queue` 当成 333 调度面
- 对 333：只观察事实 + 生成「去 invoke 已有主路」的任务，不另起分支控制面

## 调用

```powershell
.\Get-GrokLocalStateSense.ps1
.\Invoke-GrokStateSenseMax.ps1          # 极致感知（非安全面）
.\Invoke-GrokGapDrivenProgressor.ps1 -PushQueue
.\Invoke-GrokLoopGuardian.ps1 -ForceProgressor -RunNext
. E:\XINAO_EXTERNAL_MATURE\state-sense-stack\env.ps1
```

证据：

- `D:\XINAO_RESEARCH_RUNTIME\state\local_state_sense\latest.json`
- `D:\XINAO_RESEARCH_RUNTIME\state\state_sense_max\latest.json`
- `D:\XINAO_RESEARCH_RUNTIME\state\gap_driven_progressor\latest.json`
- `D:\XINAO_RESEARCH_RUNTIME\state\loop_guardian\latest.json`
- `D:\XINAO_RESEARCH_RUNTIME\readback\zh\gap_driven_interject_latest.md`

## 感知栈（已装 / 明确不要）

**要：** scc、dive、watchexec、rg/fd/ugrep、ast-grep、tree-sitter、watchdog、git/gh、docker 深探、pydeps/vulture/knip…  
**不要：** Trivy/Grype/OSV/Gitleaks/TruffleHog、密钥面、依赖 CVE 当目标
