# 永续运行 + 睡觉模式（自动注入）

SENTINEL:GROK_PERPETUAL_SLEEP_DAEMON_RULE_V1

**合同：** `grok_perpetual_sleep_daemon.v1.json`  
**守护：** `Invoke-GrokPerpetualSeedLabDaemon.ps1`  
**停：** `D:\XINAO_RESEARCH_RUNTIME\state\grok_perpetual_daemon\user_stop.flag` 或用户明说「停止」「睡觉模式结束」

## 硬默认（直至撤销）

1. **永不停止** — 禁止交报告停、禁止等确认停
2. **GapScan 发动机** — `Invoke-GrokFullGapScan.ps1`；对照意图规格书+工具表+反假绿
3. **最大并行+补位** — `Invoke-GrokSubagentPoolOrchestrator.ps1` + 本回合 Task 补满
4. **波次执行** — `Invoke-GrokWaveCycleRun.ps1` / `RunNext`
5. **治理环** — 平台/焊路先 0–4 再实施
6. **证据** — D 盘 + 中文 readback；`completion_claim_allowed=false`

## 主会话每回合

读 `subagent_pool/latest.json` → 补位 Task → 不空转汇报。

SENTINEL:GROK_PERPETUAL_SLEEP_DAEMON_RULE_READY