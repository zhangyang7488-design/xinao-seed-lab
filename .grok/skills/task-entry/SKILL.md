---
name: task-entry
description: >
  XINAO task entry module: diverse delivery, single 333 claim, in-system decomposition.
  Use when user delivers a task (一句话/文件/路径/目录/块B模板), says 投递任务/任务入口/多样投递,
  or references 任务入口_可复制口径. Slash: /task-entry.
  NOT frontend step decomposition; NOT claiming Temporal owner.
---

# 任务入口（多样投递 · 单一认领 · 系统内分解）

**冻结：** 桌面 `任务入口_可复制口径_20260709.txt` 块A · D盘 `specs/xinao_task_entry_frozen_copy_paste_20260709.md`

## 你必须做的

1. **只投递，不拆计划** — 禁止在聊天里列 15 步当主链交付
2. **自己 invoke** `Invoke-GrokTaskEntry.ps1`，写 D 盘证据
3. **回复块C三句**：①读到没 ②durable 证据路径 ③blocker

## Invoke（always run yourself）

```powershell
Set-Location "C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge"

# 一句话
.\Invoke-GrokTaskEntry.ps1 -Intent "【一句话要干什么】"

# 文本文件 / 路径
.\Invoke-GrokTaskEntry.ps1 -InputFile "C:\path\to\material.txt"
.\Invoke-GrokTaskEntry.ps1 -InputDir "C:\path\to\folder"

# 块B 任务模板文件
.\Invoke-GrokTaskEntry.ps1 -TaskFile "C:\path\to\task.txt"

# 代投 Codex（ingress 绿时；仍非 Temporal owner）
.\Invoke-GrokTaskEntry.ps1 -Intent "..." -DeliveryShell codex -TryCodexProxy

# 查状态
.\Get-GrokTaskEntryStatus.ps1
```

## 证据

- `D:\XINAO_RESEARCH_RUNTIME\state\task_entry\latest.json`
- `readback\zh\task_entry_latest.md`

## 诚实（本机常见）

- Temporal:7233 关 → `intake_staged_pending_durable_owner`（正常，不是失败撒谎）
- 桌面目录监听 **未启**（合同 `desktop_watch_future.enabled=false`）

## 硬边界

- Grok/Codex = 投递壳；耐久 owner = Temporal（333 内）
- `completion_claim_allowed=false`
- ingress 绿 ≠ 333 闭合

Contract: `grok-admin-bridge/grok_task_entry_module.v1.json`