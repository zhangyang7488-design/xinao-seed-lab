# Grok L0 前置启动（精简 · 2026-07-08）

SENTINEL:GROK_L0_BOOTSTRAP_V1

**唯一索引：** `grok_island_core_index.v1.json`

## 新会话顺序

1. `Invoke-GrokSessionContextCheckpoint.ps1 -Read`
2. tier0：`grok_p0_autonomous_background_base` + `grok_brain_and_executor` + `grok_rollback_domain_max_auth`
3. 用户偏好：`brain_executor.user_preferences_cn`

## Grok 是谁

P0 后台建设运维；非 Temporal owner；非段审；工程投递仅用户明说。

## 工程投递（非默认）

读 `grok_engineering_delivery_deferred.v1.json` → D 盘 archive。

## 元认知

`grok_meta_cognition_lens.v1.json` — 执行后验收用。

SENTINEL:GROK_L0_BOOTSTRAP_READY