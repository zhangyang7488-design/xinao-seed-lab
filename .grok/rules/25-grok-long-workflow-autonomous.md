# Grok 长久工作流 · 离线自主（自动注入）

SENTINEL:GROK_LONG_WORKFLOW_AUTONOMOUS_RULE_V1

**合同：** `grok_long_workflow_runtime.v1.json` · **主路：** `grok_333_one_mature_system_mainline_grok_sideline.v1.json`（333=一套Temporal成熟栈；本规则=**Grok岛旁路**）

## 旁路纪律

- 岛 `task_queue`/`RunNext` **不是** 333 发动机；**不能**用队列空当 333/P0 闭合
- Grok 可借 Temporal 成熟栈 **建设** 333；交付物进展看 Temporal 证据

## 档位

仅当用户明示 **不要停 / 一直跑 / 睡觉 / 离线** → `autonomous_continuous`（见 rule `22`/`26`）。  
平时聊天 = `dialogue`；一件活 = `bounded_task`。

## 站立授权（合同≠固定任务表）

- **合同 = 行为授权：** 轮询·观察·保活·思考·外部搜索·自修复·进化·额外动作（有 token 时尽用）
- **queue_empty ≠ 停：** 触发 `Invoke-GrokLongWorkflowKeepalivePoll.ps1` + `Invoke-AutoSeedKeepaliveWave` 动态差距 Seed
- **Wave 种子：** 差距/registry/compose 驱动；非 W18–W24 固定表

## 用户睡觉 / 离线（autonomous_continuous）

- **硬停仅：** deny_list · 自指自毁 · 用户喊停
- **软阻塞不停队列：** 记录 bypass + named_blocker → 尽力闭环当前 task → 下一 task
- 每实质进展：`Invoke-GrokSessionContextCheckpoint.ps1 -Save`
- 报告写 `D:\XINAO_RESEARCH_RUNTIME\readback\zh\grok_overnight_report_latest.md`
- **P0 诚实：** 底座未完整自洽/自修复/自进化；不得声称闭合
- **默认不删桌面**

## 记忆分工

| 层 | 载体 |
|----|------|
| 当轮续接 | checkpoint `latest.json` |
| 跨项目偏好 | `MEMORY.md` |
| 工作流状态 | `grok_long_workflow/latest.json` + `task_queue.json` |
| 工程事实 | 机器 JSON 合同 |

## 必跑

`Invoke-GrokLongWorkflowBootstrap.ps1` — 新会话/离线循环开头

SENTINEL:GROK_LONG_WORKFLOW_AUTONOMOUS_RULE_READY