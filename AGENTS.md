# Grok Admin Isolated — Grok heavy · P0 后台底座

**唯一索引：** `grok-admin-bridge/grok_island_core_index.v1.json`

## tier0 默认三件套

| 文件 | 用途 |
|------|------|
| `grok_p0_autonomous_background_base.v1.json` | 北极星 |
| `grok_brain_and_executor.v1.json` | 主体 + `user_preferences_cn` |
| `grok_rollback_domain_max_auth.v1.json` | 授权 + 三档执行 |

## 新会话

1. `Invoke-GrokSessionContextCheckpoint.ps1 -Read`
2. 读 tier0；有检查点禁止重聊架构
3. 进度：`D:\XINAO_RESEARCH_RUNTIME`

## 分工

- **你对 Grok 说的** = 个人偏好 → `user_preferences_cn` / D 盘 `specs/`
- **后台自治实现** = 工程 → D 盘 `specs/`、工具胶水宪法追加区
- **工程投递 333/S** = 非默认 → `grok_engineering_delivery_deferred` + archive

## 元认知（验收）

`grok_meta_cognition_lens.v1.json` — 这是不是真进展？能 invoke 什么？

## 行为宪法（治理环）

`grok_mature_first_governance_loop.v1.json` · rule `28` · skill `mature-first-governance`  
平台/运维/焊路：**先治理环再实施**；`Invoke-GrokMatureFirstGovernanceGate.ps1`

## 自动 rules（活跃 10 条）

`00` `22`–`28` `90` `91` — 见 core_index。旧 rules 01–21 已归档。

## 边界

| 做 | 不做 |
|----|------|
| P0 建设、队列、证据、透镜 | 默认 333/ingress 闭合 |
| 可回滚域全自动 | 宣布用户完成、段审 |
| 用户喊搜→原生 WebSearch | 后台工程写进 Grok JSON |

## 人读

- `桌面\Grok过夜可见规划_读我_20260708.txt`
- `桌面\Grok合同盘点_20260708.txt`
- `GROK_L0_BOOTSTRAP.md`

## Install

```powershell
.\grok-admin-bridge\Install-GrokAdminBridge.ps1
.\grok-admin-bridge\Get-GrokLocalCapabilityStatus.ps1
```