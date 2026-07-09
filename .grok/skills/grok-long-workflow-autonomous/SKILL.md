---
name: grok-long-workflow-autonomous
description: >
  Grok long-running autonomous workflow: memory layers, task queue, overnight report,
  capability bootstrap. Use when user sleeps/offline, says 长久工作流/自身能力最大化/睡醒报告,
  or at session start after checkpoint Read. Slash: /long-workflow.
  NOT Codex Temporal owner — Grok island executor with full rollback-domain auth.
---

# Grok Long Workflow (Autonomous)

用户离线/睡觉时：**除真实硬阻塞外全自动**推进 Grok 岛任务。

**意图 vs 底座：** 保活/poll = 让你能干活的底座；目标 = 服务 P0/333 后台。地图全绿后 queue_empty 种 **333 服务波**，非重复 9 条巡检模板。

## Memory stack (read in order)

1. `Invoke-GrokSessionContextCheckpoint.ps1 -Read`
2. `C:\Users\xx363\.grok\memory\MEMORY.md`
3. `D:\XINAO_RESEARCH_RUNTIME\state\grok_long_workflow\latest.json`
4. `D:\XINAO_RESEARCH_RUNTIME\state\grok_long_workflow\task_queue.json`

## Bootstrap (always run)

```powershell
Set-Location "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"
.\Invoke-GrokLongWorkflowBootstrap.ps1 -SeedDefaultQueue
```

## Work loop

1. Pick highest `priority` `pending` task from `task_queue.json`
2. Execute with MCP/scripts/GitHub search/local mirrors — **不删桌面**
3. Write evidence under `D:\XINAO_RESEARCH_RUNTIME\`
4. Update task `status` → `done` or `blocked` + `named_blocker`
5. `-Save` checkpoint; append `readback\zh\grok_overnight_report_latest.md` (中文 ≤40 行)
6. Repeat until queue empty or only hard blockers remain
7. queue_empty: `KeepalivePoll` 一次（底座）→ 全绿种 333 服务波 / 有红种定向修

## Hard stop only

`DOCKER_DAEMON_NOT_RUNNING` · `INGRESS_19102_DOWN` · deny_list · 自指自毁 · 用户喊停

## Capability matrix

| Need | Use |
|------|-----|
| GitHub 搜仓 | `grok_com_github` MCP or `gh` CLI |
| 本地镜像 | `E:\XINAO_EXTERNAL_MATURE` + registry scan |
| 投递 Codex | `Send-GrokIntentToCodexA.ps1` when ingress up |
| 桌面 UI | `windows` MCP |
| 规则/授权 | `grok_long_workflow_runtime.v1.json` + rule `25` + `22` |

Contract: `grok-admin-bridge/grok_long_workflow_runtime.v1.json`