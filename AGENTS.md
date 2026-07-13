# Grok Admin Isolated — 索引壳（always · 极短）

**唯一索引：** `grok-admin-bridge/grok_island_core_index.v1.json`
**证据根：** `D:\XINAO_RESEARCH_RUNTIME`
**规则目录：** `.grok/rules-on-demand/INDEX.md`

## tier0 列表

| 合同 | 用途 |
|------|------|
| `grok_p0_autonomous_background_base.v1.json` | 北极星 |
| `grok_brain_and_executor.v1.json` | 主体 + 偏好 |
| `grok_rollback_domain_max_auth.v1.json` | 授权 + 三档 |

## 新会话

1. `Invoke-GrokSessionContextCheckpoint.ps1 -Read` → 有 latest 直接续上
2. 细节跟 `core_index` / 热 rules；禁止重聊架构

## 规则分层（真 demote = 不在 `.grok/rules/`）

| 层 | 路径 | 内容 |
|----|------|------|
| **热** | `.grok/rules/` | `00` `22` `23` `24` `26` `29` `30` `91` |
| **温** | `.grok/rules-on-demand/warm/` | `27` `28` `31` `90` |

旧冷层及 `25`、`30-dp` 已从工作树物理移除；历史仅留在 Git 与 D 盘事故证据。连续工作始终用有限 episode + 三件套 + 检查点，不按关键词启动守护或第二编排器。

## 本窗脸（Admin）

**默认：自域工人** — 只动本岛；**禁写 4.5**（`.grok-4.5-lane` / `state\grok_4_5` / 4.5 岛仓）。
升彻底工人：**仅**用户当轮显性口令。硬边界见 rule `29`/`30`。

## 边界一句

做：P0 底座、队列、证据、可回滚全自动（自域）。
不做：默认 333 闭合、宣布用户完成、无授权写 4.5 / 改 S 仓。
稳定偏好 → 最小工程落点（`grok_preference_to_engineering_delta.v1.json`）；Admin 自域同构，默认不写 4.5。

## 本地核验

```powershell
.\grok-admin-bridge\Test-GrokRepositoryContracts.ps1
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
```
