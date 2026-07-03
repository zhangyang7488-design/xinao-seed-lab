# 默认：任何事务 = 最大 RootIntentLoop（自动注入）

SENTINEL:GROK_DEFAULT_MAX_ROOT_INTENT_LOOP_ALL_TX_RULE_V1

**用户强调累了 — 已冻结，不必每轮重复。** 合同：`grok_default_max_root_intent_loop_all_transactions.v1.json`

- **整个事务当前** = 默认 **动态最大循环**；**任何事务**均适用。
- 默认链：思考满负荷 → 执行满负荷 → poll/fan-in → acceptance → 中文锚定 → 弹栈/回主线 → 续跑。
- **唯一例外**：任务包或 WORKER_ASSIGNMENT **明示当前 serial_boundary**（或 router/额度 **named_blocker** 落盘）。
- 无例外证据 **禁止**降级：evidence-only、verifier 波、probe 顶替、逐步问用户、缩事务。
- 每次 `Send-GrokIntentToCodexA` **自动注入**详包；Grok 段审按此判真伪进展。

SENTINEL:GROK_DEFAULT_MAX_ROOT_INTENT_LOOP_ALL_TX_RULE_READY