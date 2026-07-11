# Grok 长久工作流 · 离线自主（自动注入）

SENTINEL:GROK_LONG_WORKFLOW_AUTONOMOUS_RULE_V1

**合同：** `grok_long_workflow_runtime.v1.json` · **主路：** `grok_333_one_mature_system_mainline_grok_sideline.v1.json`（333=一套Temporal成熟栈；本规则=**Grok岛旁路**）

## 三档门闩（权威 · 与 22/26 同表）

| 档 | 何时 | Bootstrap / Keepalive / 永续 |
|----|------|------------------------------|
| **dialogue** | 默认聊天 | **不**强制 `LongWorkflowBootstrap` 当会话门禁；可不启 poll/永续 |
| **bounded_task** | 一件有界活 | 可按需 Bootstrap/RunNext；**不**默认永续补位 |
| **autonomous_continuous** | 用户明示 **不要停 / 一直跑 / 睡觉 / 离线 / 永续** | Bootstrap · Keepalive · 永续栈 **才默认开启** |

- **三档细节**见 rule `26`；授权字面见 rule `22`。
- **rule `32`–`35` 默认 demote**；启用门 = **本规则三档抬到 `autonomous_continuous`** + 用户当轮显性语（见各 rule 启用门）。未抬档 → 禁止当对话 OS 硬推。

## 旁路纪律

- 岛 `task_queue`/`RunNext` **不是** 333 发动机；**不能**用队列空当 333/P0 闭合
- Grok 可借 Temporal 成熟栈 **建设** 333；交付物进展看 Temporal 证据

## 意图 vs 底座（用户 2026-07-09 纠偏）

- **意图 / 目标：** 服务 **P0/333 后台** 建设·运维·交付·证据续跑
- **保活 / poll：** **底座** — 让你能持续干活、不卡死；**不是**意图本身；**仅** `autonomous_continuous` 或用户明示睡觉时默认跑
- **地图全绿：** 施工包差距表无红格；**≠** P0 闭合；**≠** 只剩巡检；应种 **333 服务波**
- **禁止漂移：** 把 9 条重复探活模板当主菜单

## 站立授权（合同≠固定任务表 · 仅抬档后）

- **合同 = 行为授权：** 思考·搜索·自修复·进化·为333服务·额外动作
- **queue_empty ≠ 停（仅 autonomous）：** 先 `KeepalivePoll` 一次（底座）→ `Invoke-AutoSeedAfterQueueEmpty` 按差距选种
- **种子策略：** 全绿→333服务波；有红→定向修；非 W18–W24 固定表

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

## 入口（非 dialogue 门禁）

- `Invoke-GrokLongWorkflowBootstrap.ps1` — **仅** `autonomous_continuous` / 离线循环 / 用户明示睡觉·永续 时默认开头
- `dialogue`：**禁止**把 Bootstrap 当「新会话硬门」；有需要再跑，不拦聊天

SENTINEL:GROK_LONG_WORKFLOW_AUTONOMOUS_RULE_READY
