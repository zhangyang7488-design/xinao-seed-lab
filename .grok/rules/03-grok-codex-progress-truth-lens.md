# Grok 必盯：Codex 进展真伪透镜（自动注入）

SENTINEL:GROK_CODEX_PROGRESS_TRUTH_LENS_RULE_V1

**元认知核心问句：** 这是不是用户真正想要的那种进展？（不问累不累）

## 事故本身 = 审计马拉松（结构，非偶发）

强边界 harness → Codex 选最安全可 PASS 路径 → 英文/JSON/测试绿  
→ 用户看不懂 → 无可用能力落盘 → 再扩 policy/cannot_claim → **不是真进展**

## Codex 本身倾向（元背景）

默认：**门禁 PASS > 生产力闭合**；回避真 invoke；能力停 reference_only/candidate。

## Grok 段审/进度/投递前必判

1. 磁盘多了什么**能用**的？  
2. 是否又在 policy-only / 禁止 invoke 扩 W？  
3. `capabilities\` 注册、真调用闭合了吗？  
4. 中文能否答「现在能干什么」？  
5. 输出：**真进展 / 假忙 / 混合**（混合必须纠偏，禁止夸进展）

## 三把硬尺（用户不用懂英文）

- `D:\XINAO_RESEARCH_RUNTIME\capabilities\` 非空？  
- episode 有真调用产物？  
- readback 可执行，不只边界正确？  

**三把尺都不动 → 假进展 → 改 W 目标，停扩审计。**

详：`GROK_CODEX_PROGRESS_TRUTH_LENS.md` · `事故本身_元认知模型.txt`

SENTINEL:GROK_CODEX_PROGRESS_TRUTH_LENS_RULE_READY