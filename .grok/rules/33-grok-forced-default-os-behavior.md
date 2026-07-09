# 强制默认 OS 行为 · 轮回循环并行补位（自动注入）

SENTINEL:GROK_FORCED_DEFAULT_OS_BEHAVIOR_RULE_V1

**合同：** `grok-admin-bridge/grok_forced_default_os_behavior.v1.json`  
**Meta 编排：** `Invoke-GrokSubagentPoolOrchestrator.ps1`  
**Ledger：** `D:\XINAO_RESEARCH_RUNTIME\state\subagent_pool\latest.json`

## 站立授权（直至用户明说撤销）

- **执行范式：** 动态波次并行 + 自动补位 worker pool
- **默认模式：** 持续多波并行推进，**不是**思考一轮就结束
- **并行：** 每波 **最大子代理数** 启动；不足 **立即补**
- **补位：** 任一子代理结束（成功/失败/终止）→ **同回合立刻** 新建补位，维持最大并发
- **循环：** **轮回循环**；波末 → 下一波规划与执行（continue-as-new）
- **优先级：** token 消耗速度 + 任务推进速度 > 保守串行等待
- **撤销：** 仅当用户明说「切换单轮模式」「停止自动补位」「进入保守模式」「终止强制默认OS合同」

## 不靠 LLM 记 — 读盘触发

**新会话第零步（与 checkpoint 并列）：**
1. `Invoke-GrokSubagentPoolOrchestrator.ps1 -Action Read` 或读 `subagent_pool/latest.json`
2. 若 `refill_required=true` 或 `in_flight_count < max_parallel` → **本回合立即** `Task` 补满 `spawn_directives`

**子代理返回后（同回合）：**
- `Invoke-GrokSubagentPoolOrchestrator.ps1 -Action Complete -SubagentId <id> -Status success|failed`
- 读 `refill_count` → **立刻再 spawn**，禁止只汇报

**波末：**
- `Invoke-GrokOrchestratorPulse.ps1` + `Invoke-GrokWaveCycleRun.ps1`（续波）+ checkpoint `-Save`

## 实施 vs 登记

桌面三 txt = **实施源**；合同/ledger = **政策与状态机**。禁止只写 JSON 不干活。

SENTINEL:GROK_FORCED_DEFAULT_OS_BEHAVIOR_RULE_READY