# 会话上下文检查点（always · 重启续上）

SENTINEL:GROK_SESSION_CONTEXT_CHECKPOINT_RULE_V1

**合同：** `grok-admin-bridge/grok_session_context_checkpoint.v1.json`
**脚本：** `Invoke-GrokSessionContextCheckpoint.ps1`
**证据：** `D:\XINAO_RESEARCH_RUNTIME\state\grok_session_context\latest.json`

## 分工

| 层 | 存什么 |
|----|--------|
| **检查点** | 当轮意图、刚做了什么、卡在哪、下一步（≤25 行） |
| **Memory** | 跨项目 Preferences（`C:\Users\xx363\.grok\memory\MEMORY.md`） |
| **聊天** | 不持久 — 重启靠检查点，不靠重聊 |

## 新会话第一步

1. `-Read` 读 `latest.json`；有则**直接续上**，禁止从零慢慢解释架构
2. 无检查点再读 Memory + L0 合同

## 有实质进展后

`-Save` 只写检查点；禁止顺带补池、调度、保活或启动终端。

SENTINEL:GROK_SESSION_CONTEXT_CHECKPOINT_RULE_READY
