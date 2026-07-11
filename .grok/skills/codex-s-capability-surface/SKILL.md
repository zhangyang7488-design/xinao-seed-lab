---
name: codex-s-capability-surface
description: >
  Codex S Hardmode capability surface claimed onto Grok 4.5: which MCPs/scripts
  are thin-bound, which are deliberately skipped (xinao-memory Qdrant lock,
  333 ownership, Codex-native plugins). Use when user opens S Hardmode, asks
  挂S能力/S能力面/Hardmode能力, or capability inventory vs S.
  Slash: /codex-s-surface. NOT RootIntentLoop owner; NOT xinao-memory mount.
---

# Codex S → Grok 能力面（薄挂）

**证据：** `D:\XINAO_RESEARCH_RUNTIME\state\grok_codex_s_capability_surface\latest.json`  
**源：** Desktop `OPEN CODEX S HARDMODE.lnk` → `Open-Codex-S-Hardmode.ps1` → `~/.codex-seed-cortex`  
**S 快照：** `D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\state\capability_snapshot.json`

## 已挂（对 Grok 有用）

| 能力 | 形态 | 用途 |
|------|------|------|
| **xinao** | stdio（S 同款 python MCP） | XINAO 工具面；替代挂死的 HTTP :19460 |
| **windows** | 已有 | 桌面/UI |
| **codebase-memory** | exe + `CBM_CACHE_DIR=...\grok45` | 仓语义记忆（独立缓存，不碰 mem0） |
| **chrome-devtools** | 全局 npm | 浏览器调试 |
| **openaiDeveloperDocs** | HTTP MCP | OpenAI 产品事实 |
| **filesystem / fetch / mcp_memory** | 标准 MCP | 盘访问 / HTTP / 图记忆 |
| **direct worker lane** | `Invoke-GrokCodexSDirectWorkerLane.ps1` | 千问/DP 单 lane |
| **light research** | `Invoke-GrokCodexSLightResearchLoop.ps1` | 前台轻研究，非 333 |

## 故意不挂

| 能力 | 原因 |
|------|------|
| **xinao-memory** | 多窗口 stdio 各嵌一套 Qdrant → 抢 `D:\...\mem0\qdrant\.lock` |
| **RootIntentLoop / Temporal 主链** | 333 所有权，不是 Grok 默认主战场 |
| **Codex 40 plugins / browser_use / computer_use** | Codex 运行时原生，不可整包搬到 Grok |

## Invoke

```powershell
Set-Location "C:\Users\xx363\Grok_Admin_Isolated\workspace-grok-4.5-island\grok-admin-bridge"

# 能力面状态 / claim 刷新
.\Invoke-GrokCodexSCapabilitySurfaceClaim.ps1 -Status

# 直调 worker（已有 skill: codex-s-direct-worker-lane）
.\Invoke-GrokCodexSDirectWorkerLane.ps1 -Mode draft -Provider auto -Objective "..." -InputText "..."

# 轻研究环（非 333）
.\Invoke-GrokCodexSLightResearchLoop.ps1 -Mode local_only -Objective "..." -LocalQuery "..."
```

## 配置落点

- Lane（本窗生效）：`C:\Users\xx363\.grok-4.5-lane\config.toml`
- Island 工作区：`workspace-grok-4.5-island\.grok\config.toml`
- **新 MCP 需重开 Grok 4.5 会话** 才会握手

## 硬边界

- `completion_claim_allowed=false`
- 不宣布用户完成 / 不把挂 MCP 说成 P0 闭合
- 记忆主路径仍是 checkpoint + `MEMORY.md`；mem0 等 S 修好跨进程锁再议
