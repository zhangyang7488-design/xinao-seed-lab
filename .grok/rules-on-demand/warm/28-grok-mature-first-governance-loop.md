# 成熟优先治理环（按需 Read · 非 always · 行为宪法 · 极短）

SENTINEL:GROK_MATURE_FIRST_GOVERNANCE_LOOP_RULE_V1

**合同：** `grok_mature_first_governance_loop.v1.json` · **策略：** `grok_mature_first_policy.v1.json`
**Skill：** `mature-first-governance` · **思维 OS：** distill 十二条 · **钉合同环：** super_loop S1–S9

## 先于实施（站立）

```text
0 归类 → 1 外搜成熟 → 2 本地清单 → 3 选载体
→ 4 迷你ADR → 5 偏离门 → 6 实施 → 7 透镜
```

- **平台/运维/焊路/钉合同：** 0–4 **落盘**后才改仓/起进程/写 compose/改 rules
- **plan only：** 硬停步骤 4
- **全权/焊/跑完：** 仍须 0–4；禁跳过外搜
- **钉规则/合同事务：** 走 super_loop（S1 外搜→…→S6 lock→S7 逐条改→S8 证据）

## 分工

- rule `26` = 同构执行形状
- 本规则 = 治理 OS
- super_loop = 合同/rules 钉定专用环（⊂ 治理，不替代 26/28）

## 黄金路径（偏离须登记）

Temporal 官方 compose · LangGraph 官方插件 · 容器 worker · thin-glue 网关 · 薄壳入口
禁：start-dev 隐藏进程、第二套 orchestrator、while+sleep 当 owner

## 门

`Invoke-GrokMatureFirstGovernanceGate.ps1` · **fail-open**（记偏离；禁默认 deny 自锁）

## 禁

本地 rg 冒充外搜 · 未规划就改 ps1/compose · 报告绿=闭合

SENTINEL:GROK_MATURE_FIRST_GOVERNANCE_LOOP_RULE_READY
