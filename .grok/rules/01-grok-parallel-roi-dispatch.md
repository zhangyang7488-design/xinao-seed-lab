# 并行收益调度（元认知 · 自动注入）

SENTINEL:GROK_PARALLEL_ROI_DISPATCH_RULE_V1

用户问 **要不要并行 / 多线程 / 开几路**，或 **实时报额度**（如「C 和 DP 有」）→ 读 `grok-admin-bridge/grok_parallel_roi_dispatch.v1.json`，出 **≤6 行** 决策；不堆架构课。

- **Grok = 调度**；**A = 执行** `WORKER_ASSIGNMENT`
- 额度：用户没说的 lane **不开**（fail-closed）
- 卡续跑 → 不开子代理/审计；有 C 额度 → 优先 **C 并行实现**；有 DP 额度且动控制流 → **后台 DP 审计**
- 详包字段：`parallel_dispatch_decision`

SENTINEL:GROK_PARALLEL_ROI_DISPATCH_RULE_READY