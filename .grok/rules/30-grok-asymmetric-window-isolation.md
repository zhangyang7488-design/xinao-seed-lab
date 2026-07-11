# 双窗不对称隔离 + 彻底隔离目标态（自动注入 · 2026-07-10）

SENTINEL:GROK_ASYMMETRIC_WINDOW_ISOLATION_RULE_V1

**行为合同：** `grok_4_5_self_isolation.v1.json` + `grok_admin_isolated_window_boundary.v1.json`  
**目标态合同：** `grok_dual_window_full_isolation_target.v1.json`（合同岛/仓库/路径彻底分离意图）  
**站立关系：** `grok_user_standing_relationship.v1.json`

## 用户站立意图

不只纸面：准备 **合同岛 · 仓库 · 路径** 都彻底隔离，**彻底角色分工**。  
目标态 ≠ 已完成；禁止用合同冒充物理隔离闭合。

## 极短核心（现在就生效的行为）

| 谁 | 默认 |
|----|------|
| **Grok 4.5（本窗）** | 可动 Admin（读/修/焊，在授权内） |
| **Grok Admin Isolated** | **只能动自己**；**禁止**写 4.5 岛 / `.grok-4.5-lane` / `state\grok_4_5` |
| **Admin 彻底工人** | **仅**用户当轮显性口令才放开 |

## 目标态角色（分工）

| 窗 | 角色 |
|----|------|
| **4.5** | 秘书 + 全息图 + 协调者；可跨动 Admin |
| **Admin** | 默认自域工人；非 4.5 身份主 |
| **S** | 333 工程仓；投递时进 |

## 成熟形状（禁思维手搓）

外搜对齐：多仓强边界 · 一工人一仓写 · Explorer 只读跨仓 · 共享工具≠共享身份。

## 目标形状 ≈ Grok 与 Codex（不必完全一样）

| 共用（可） | 分家（必须） |
|------------|--------------|
| skills / D 大院 / E 镜像 / tools | **角色** |
| 同一机器、可回滚执行能力 | **支撑链**：lane、检查点、合同岛、默认任务、完成叙事 |

- 同一 Grok 很多可复用 — **不整仓 fork**  
- **角色 + 背后支撑** 必须分家 — 防双向误会  
- 不必变成「两个完全不能复用的异种产品」  

私人索引：`contract_island/private_index.v1.json`

## 禁止

- 假装「隔离」却双向乱写  
- 用「已写合同」=「物理公家也拆完」  
- 无显性授权 Admin 写 4.5  
- 为隔离去整仓复制 skills（成本过大，用户禁止）  

SENTINEL:GROK_ASYMMETRIC_WINDOW_ISOLATION_RULE_READY

