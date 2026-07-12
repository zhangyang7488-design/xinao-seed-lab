# 深度代理模式 · 成熟薄焊（按需 Read · 非 always · 2026-07-10）

SENTINEL:GROK_AGENT_DEPTH_REFLEXION_RULE_V1

**合同：** `grok_agent_depth_reflexion_mode.v1.json`  
**Skill：** `agent-depth-reflexion` · **脚本：** `Invoke-GrokAgentDepthMode.ps1`  
**Prior art：** ReAct · Reflexion · tool-grounded critique · agentskills progressive disclosure

## 极短核心

1. **ReAct** — 想→工具→观察；禁止空想当执行  
2. **自批** — 交付前对照证据列缺口；批判须锚测试/命令/JSON，禁止语言自证  
3. **渐进上下文** — 岛 tier0 常驻；S 文按 tier1/2/3 按需读，**禁止** DESIGN/历史全 dump  
4. **禁假完成** — 能力不足必须承认 + 外搜成熟；`completion_claim_allowed=false` 直至证据  
5. **Temperature** — 窗内未暴露旋钮则不吹「最优温区」  

## 与 26/28/91

- rule `26/28`：外搜成熟 + 治理环仍先  
- rule `91`：透镜三句尺  
- 本规则：把「深思+自批+渐进读+禁假完成」钉成默认可 invoke 行为  

## 不做

不抢 333 owner；不整包变 S Hardmode 运行时。

SENTINEL:GROK_AGENT_DEPTH_REFLEXION_RULE_READY
