# Grok 4.5 岛 — 索引壳（always · 极短）

**唯一索引：** `grok-admin-bridge/grok_island_core_index.v1.json`
**证据根：** `D:\XINAO_RESEARCH_RUNTIME`
**规则目录：** `.grok/rules-on-demand/INDEX.md`（温/冷按需 Read）

## tier0 三件套

| 合同 | 用途 |
|------|------|
| `grok_p0_autonomous_background_base.v1.json` | 北极星 |
| `grok_brain_and_executor.v1.json` | 主体 + 偏好 |
| `grok_rollback_domain_max_auth.v1.json` | 授权 + 三档 |

## 新会话

1. `Invoke-GrokSessionContextCheckpoint.ps1 -Read` → 有 latest 直接续上
2. 细节只跟 `core_index` / 热 rules，禁止重聊架构

## 规则分层（真 demote = 文件不在 `.grok/rules/`）

| 层 | 路径 | 内容 |
|----|------|------|
| **热** | `.grok/rules/` | `00` `22` `23` `24` `26` `30` `36` `91` |
| **温** | `rules-on-demand/warm/` | `25` `27` `28` `29-depth` `31` `36-depth` `90` |
| **冷** | `rules-on-demand/cold/` | `32`–`35` + `29-admin` `30-dp` |

冷层 `32`–`35` 已退役，只作事故历史；连续工作始终用有限 episode + 三件套 + 检查点，不按关键词启动守护或第二编排器。

## 本窗脸

秘书 + 全息图 + 可回滚代办 · 4.5→Admin 默认可写 · Admin↛4.5
硬边界 / 验收 / 意图解码 → 热 rule `22` `30` `36` `91`（此处不展开）。

## 边界一句

做：P0 底座、队列、证据、可回滚全自动。
不做：默认 333 闭合、宣布用户完成、无授权改 S 仓。
稳定偏好 → 最小工程落点（`grok_preference_to_engineering_delta.v1.json`）；双窗同构，4.5 默认可焊 Admin。

## Install

```powershell
.\grok-admin-bridge\Install-GrokAdminBridge.ps1
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
```
