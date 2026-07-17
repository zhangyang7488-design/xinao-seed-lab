# 成熟实现动态对照（按需 Read · 非 always · 极短）

SENTINEL:GROK_MATURE_FIRST_GOVERNANCE_LOOP_RULE_V2

**合同：** `grok_mature_first_governance_loop.v1.json` · **策略：** `grok_mature_first_policy.v1.json`
**Skill：** `mature-first-governance`

## 按事实缺口激活

```text
状态 / 进度 / inventory / 已定路线内可回滚动作
  → 本地 live → 直接动作 → 真实验证
外部当前事实可能改变对象 / 载体 / 拓扑 / 路线 / 验收
  → 轻量成熟对照 → 本地清单 → 选择最薄载体 → 实施 → 真实验证
```

- 平台、依赖、协议、陌生成熟能力或共享控制面修复，只有对照能改变方案时才激活外搜。
- 纯本地状态与可回滚修补不为凑流程写 ADR、治理状态或外搜。
- 用户明确 `plan only` 时只规划，不实施。
- 稳定纠正只改最小现有载体并挂回归，不启动第二治理环。

## 成熟完整性

需要对照时优先当前官方 SDK、上游参考代码和可信成熟 integration；本地只留参数、路径、合同翻译和最薄 adapter。Temporal、LangGraph、容器 worker 等是已验证候选，不是每个问题的固定答案。

## 门

`Invoke-GrokMatureFirstGovernanceGate.ps1` 仅记录必要证据，`fail-open`；不默认 deny 工具，也不把未写 ADR 变成普通施工的阻塞。

## 禁

本地 rg 冒充外部研究 · 外部研究替代本机现状 · 报告绿冒充闭合 · 隐藏进程或脚本循环冒充耐久控制面

SENTINEL:GROK_MATURE_FIRST_GOVERNANCE_LOOP_RULE_READY
