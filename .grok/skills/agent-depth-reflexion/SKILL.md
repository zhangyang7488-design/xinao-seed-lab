---
name: agent-depth-reflexion
description: >
  Deep agent mode welded from mature external patterns: ReAct, Reflexion,
  tool-grounded self-critique, Agent Skills progressive disclosure, verification
  before completion, anti language-fake-done. Use when user says 深度模式/强制深思/
  禁假完成/Reflexion/搜外部成熟思维并执行六维, or non-trivial platform/research/coding.
  Slash: /depth. NOT 333 owner; NOT full S dump into context.
---

# Agent Depth + Reflexion（成熟薄焊）

**合同：** `grok-admin-bridge/grok_agent_depth_reflexion_mode.v1.json`  
**脚本：** `Invoke-GrokAgentDepthMode.ps1`  
**同构：** rule `29` · mature-first `28` · meta-lens `91` · `sp-verification-before-completion`

## Prior art（外搜采纳，不手搓第二套脑）

| 成熟源 | 采纳什么 |
|--------|----------|
| **ReAct** | 想一步→工具→观察→再想；禁止空想当执行 |
| **Reflexion** | 失败/交付前：文字自批 + 进检查点/证据；下轮可改 |
| **Reflection 2026** | generate→critique→revise；**1–3 轮**+停止条件 |
| **Tool-grounded critique** | 自批必须挂测试/命令/JSON 证据；禁止语言自证 |
| **agentskills.io** | 渐进披露：名描→SKILL 全文→引用文件；禁止全仓灌 |
| **AGENTS.md** | 索引；深文按需 |
| **verification-before-completion** | 宣称完成前跑验证 |

## 默认环（非 dialogue 闲聊）

```text
0 档位  dialogue | bounded_task | autonomous_continuous
1 外搜  平台/未知 → WebSearch/成熟组件（rule 26/28）
2 渐进  Invoke-GrokAgentDepthMode.ps1 -LoadTier N 或按任务读
3 ReAct  计划 → 并行工具/子代理 → 观察
4 自批  缺口 / 风险 / 是否语言假完成
5 验证  命令·测试·latest.json
6 交付  now_can_do；未闭合则 completion_claim_allowed=false
```

## 禁假完成（硬）

- 无证据不说「已闭合 / 已焊上 / 用户完成」
- 能力不足：**承认** + 外搜 + 或派子代理 / worker lane
- 更多 CoT 文字 **不能** 替代 pytest / docker ps / 文件哈希
- P0/333 默认不宣称闭合

## S 上下文（渐进，非全量）

| Tier | 何时 | 读什么 |
|------|------|--------|
| 0 | 每会话 | checkpoint + 岛 tier0 + rules |
| 1 | 任务碰 S/333/hardmode | `S\SEED_CORTEX_MUST_READ_FIRST.md` + `CODEX_S_L0.md` |
| 2 | RSI/自进化 | `meta_rsi_wave` schema + `Write-MetaRsiWave.ps1`（薄绑，不抢 owner） |
| 3 | 点名 | DESIGN/docs/current — rg 后读，禁止 dump 全仓 |

## Temperature

平台未暴露旋钮 → **诚实说不可调**；精确靠验证，不靠假温度叙事。

## Invoke

```powershell
Set-Location "...\grok-admin-bridge"
.\Invoke-GrokAgentDepthMode.ps1 -Status
.\Invoke-GrokAgentDepthMode.ps1 -LoadTier 1
.\Invoke-GrokAgentDepthMode.ps1 -SelfCritique -SummaryCn "本轮做了什么"
```

## 不做

- 不整包成为 Codex S Hardmode 运行时  
- 不默认 RootIntentLoop / xinao-memory  
- 不手搓新控制面替代 Temporal  
