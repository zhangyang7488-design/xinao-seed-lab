# 轮回循环 · 每波默认行为（自动注入 · 用户显性才启用）

SENTINEL:GROK_WAVE_CYCLE_DEFAULT_BEHAVIOR_RULE_V1

**合同：** `grok_wave_cycle_default_behavior.v1.json` · **入口：** `Invoke-GrokWaveCycleRun.ps1`

## 启用门（硬句 · 2026-07-11 demote）

**默认不启用。** 非技术用户对话 / 默认 `dialogue` **不得**自动拉 WaveCycle / 最大并行 / 完成即补开。  
**仅当用户当轮显性**说「不要停 / 睡觉 / 永续 / 一直跑 / 轮回 / 波次并行」时，本规则正文才生效。  
未明示 → 保持一问一答；可说明能力存在，**禁止**当默认 OS 硬推。  
**交叉：** 三档门闩权威 = rule `25`（须抬到 `autonomous_continuous`）+ 本启用门显性语。

## 实施源（实现不登记）

形状实施以桌面三份 txt 为准；合同+脚本=**可执行政策入口**，**≠** 已焊完证明：

| 文件 | 钉什么 |
|------|--------|
| `合同_默认加动态升级_指针_20260710.txt` | T0 默认 + T1 动态升级；搜索双轨；旧文=语义锚 |
| `后台免费本地搜索_成熟选型与集成_20260710.txt` | SearXNG+rg+DDGS 给后台；Grok 用原生搜 |
| `外部成熟_动态轮回与智能派模_完整形状_20260710.txt` | C 耐久环 + B 编排 + A 网关；滚动并行 |

## 每波强制（仅启用门通过后）

1. **最大子代理并行**（默认 5，策略定宽；禁止绑聊天窗口数）
2. **完成即补开** — 工作守恒：谁结束立刻从 frontier 派下一项
3. **滚动验收** — accept/reject/escalate 记 evidence；禁止 PASS 当停
4. **frontier 来源** — `named_gaps` + `WEAK_STRATEGY_*` + dynamic_roi + 愿景 partial

## 循环语义

- **continue-as-new**：读 checkpoint → 并行跑 → 存 checkpoint → **下一圈**（非单轮）
- **硬停仅：** deny · 自毁 · 用户喊停 · `user_stop.flag`
- **软阻塞：** 记 blocker，尽力闭环，续下一项

## 与旁路关系

- 本入口服务 **Grok 岛旁路** 推进；**不是** 333 Temporal 发动机
- 千问=**云** API draft；Pro=验收；禁止本地 ollama 冒充千问默认

## 必知反模式

× while+sleep 当 owner · × 报告绿=闭合 · × 只登记合同=轮回已成

SENTINEL:GROK_WAVE_CYCLE_DEFAULT_BEHAVIOR_RULE_READY