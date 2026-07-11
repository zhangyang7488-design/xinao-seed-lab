# 前台永续驱动 · 主窗口决策+脚本（自动注入 · 用户显性才启用）

SENTINEL:GROK_FRONTEND_PERPETUAL_DRIVE_RULE_V1

**合同：** `grok-admin-bridge/grok_frontend_perpetual_drive.v1.json`  
**入口：** `Invoke-GrokFrontendPerpetualDrive.ps1`  
**证据：** `D:\XINAO_RESEARCH_RUNTIME\state\frontend_perpetual_drive\latest.json`

## 启用门（硬句 · 2026-07-11 demote）

**默认不启用。** 非技术用户对话 / 默认 `dialogue` **不得**自动 `SingleCycle` 循环 / 每回合后置驱动。  
**仅当用户当轮显性**说「不要停 / 睡觉 / 永续 / 一直跑 / 前台永续驱动」时，下列分工与后置动作才生效。  
未明示 → 禁止读 `post_action_required` 后自驱下一轮。  
**交叉：** 三档门闩权威 = rule `25`（须抬到 `autonomous_continuous`）+ 本启用门显性语。

## 分工（仅启用门通过后；直至用户撤销）

| 谁 | 干什么 |
|----|--------|
| **前台主窗口 Grok** | 决策 + **自己调用脚本**驱动 GapScan → Pulse → WaveCycle → RunNext → Task 补位 |
| **后台 daemon** | **辅助**：长时间 GapScan + 守护 pending（**不替代**前台 WaveCycle） |

## 后置动作（仅启用门通过后）

**每完成一次 GapScan + WaveCycle 之后，必须自动重复执行本永续驱动令，直到用户明确说停止。**

主 Grok **启用后每回合结尾**：读 `frontend_perpetual_drive/latest.json`；若 `post_action_required=true` → **立刻**再 `Invoke-GrokFrontendPerpetualDrive.ps1 -SingleCycle`（禁止只汇报停）。

## 禁止（启用后）

- 停下来等用户 · 只思考不跑脚本 · 全扔 daemon 自己不动 · 假绿

## 撤销

用户明说：停止 / 睡觉模式结束 / 切换单轮模式 / 终止前台永续驱动

SENTINEL:GROK_FRONTEND_PERPETUAL_DRIVE_RULE_READY