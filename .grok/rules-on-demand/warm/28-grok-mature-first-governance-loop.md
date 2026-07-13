# 成熟优先治理环 · 行为宪法（按需 Read · 非 always）

SENTINEL:GROK_MATURE_FIRST_GOVERNANCE_LOOP_RULE_V1

**合同：** `grok_mature_first_governance_loop.v1.json` · **策略：** `grok_mature_first_policy.v1.json`
**Skill：** `.grok/skills/mature-first-governance/SKILL.md`

## 站立授权（先于实施）

任何事务默认走治理环，不是「想起来再搜一下」：

```text
0 归类 → 1 外部成熟先行 → 2 本地资产清单 → 3 选载体
→ 4 迷你ADR → 5 偏离门 → 6 实施 → 7 证据透镜
```

- **平台/运维/焊路**：0–4 **落盘**后方可改仓库、起进程、写 compose
- **用户喊先规划/plan only**：硬停于步骤 4，**禁止实施**
- **用户喊全权/焊/跑完**：仍须 0–4；禁止跳过外部成熟

## 与 rule 26 关系

rule `26` = 同构执行形状；本规则 = **治理操作系统**（含运维思维）。二者同时生效。

## 黄金路径（默认禁止偏离，偏离须登记）

| 域 | 默认 |
|----|------|
| Temporal | 官方 compose / Cloud · 非 start-dev+隐藏进程 |
| LangGraph | `temporalio[langgraph]` 官方插件 |
| Worker | 容器/服务部署 · 非隐藏 python 守护 |
| 网关 | `docker-compose.thin-glue.yml` |
| 入口 | 薄壳 + SDK · 非 ClaimDurable 当 orchestrator |

## 策略门（OPA精神）

实质变更前：`Invoke-GrokMatureFirstGovernanceGate.ps1 -Evaluate` 或 `-RecordStep`
**fail-open**：记录偏离，不默认 deny Grok 工具（禁自锁）。

## 禁止默认心态

- 本地 rg/盘点 **冒充** 外部成熟调研
- 未规划就改 ps1/compose/隐藏起进程
- 报告/json 绿 = 闭合

SENTINEL:GROK_MATURE_FIRST_GOVERNANCE_LOOP_RULE_READY