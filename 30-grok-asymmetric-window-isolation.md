# 双窗不对称隔离（自动注入 · 2026-07-10）

SENTINEL:GROK_ASYMMETRIC_WINDOW_ISOLATION_RULE_V1

**合同：** `grok_4_5_self_isolation.v1.json` + `grok_admin_isolated_window_boundary.v1.json`  
**站立关系：** `grok_user_standing_relationship.v1.json`

## 极短核心

| 谁 | 默认 |
|----|------|
| **Grok 4.5（本窗）** | 可动 Admin（读/修/焊，在授权内） |
| **Grok Admin Isolated** | **只能动自己**；**禁止**写 4.5 岛 / `.grok-4.5-lane` / `state\grok_4_5` |
| **Admin 彻底工人** | **仅**用户当轮显性说「把 Admin 变成彻底工人」等才放开 |

## 本窗（4.5）必须

- 检查点写 `state\grok_4_5\session_context`
- 身份与 lane 独立
- 可观察并（需要时）操作 Admin 工作区

## Admin 窗必须（写给 Admin 的行为合同）

- 默认不写 peer 4.5 路径
- 默认不把 4.5 拖进 RunNext 当自己的执行器
- 共享 skills 工具池 ≠ 可改 4.5 身份

## 禁止

- 假装「隔离」却双向随便写  
- 无显性授权把 Admin 升成可动 4.5 的彻底工人  

SENTINEL:GROK_ASYMMETRIC_WINDOW_ISOLATION_RULE_READY
