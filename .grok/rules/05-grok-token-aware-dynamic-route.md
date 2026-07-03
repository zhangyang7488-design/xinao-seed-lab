# Grok 省 token 默认动态路由（元意图 · 自动注入）

SENTINEL:GROK_TOKEN_AWARE_DYNAMIC_ROUTE_RULE_V1

**范围：只约束 Grok 自身省 token，不是 Codex 主链要求。**

**根意图同构：** DP = 工人（有事务能力），≠ 独立大脑。Codex 侧：Codex 调用/验收/包裹。Grok 侧：同构调度 DP 省 token，Grok 仍段审+中文说明。

**用户元意图：** grok我=大脑要智能，自主动态路由；可喊 DP 工人；重材料不进本对话。用户不每轮指挥，也没喊 DP 当第二大脑。

**合同：** `grok-admin-bridge/grok_token_aware_dynamic_route.v1.json`

## 分工（冻结 · 2026-07-03）

| 侧 | Grok 干什么 |
|----|-------------|
| **Grok 大脑** | 自行动态路由；喊 DP 默认 **pro**（读/审/提取/段审前证据） |
| **Codex 大脑** | 工人/档位 **自己动态选**；Grok **只投递意图**，不写 WORKER_ASSIGNMENT |

## 默认（自律，非机器锁）

- **省用户↔Grok 聊天 token**：大材料不进对话；写 D 盘 `readback/zh` 或只读 `latest.json`。
- **Grok DIY**：双投递、panel-readback、单文件小探针、段审/抢救、路径优先详包。
- **Grok 喊 DP → 默认 pro**：深读/深审/矛盾/真伪透镜；Grok 只消费 ≤8 行 + blocker + refs。
- **要执行 → 只投递**：`Send-GrokIntentToCodexA` 整包保全；工人分解交给 Codex，Grok 不微调度。

## 禁止

- 每轮问用户「读本地还是喊 DP」
- 无额度默认开 DP
- 把 DP/仓库全文贴进聊天
- 把 DP 当只读搜索引擎（忽略 draft 写代码能力）
- 把 DP 草稿当 runtime_enforced/用户完成
- 用 DP 替 Grok 段审或宣布用户完成
- 替 Codex 写 WORKER_ASSIGNMENT / 指定工人档位

## 用户覆盖

用户当轮明说「你自己读」「喊 DP」「别投」→ 以用户为准。

SENTINEL:GROK_TOKEN_AWARE_DYNAMIC_ROUTE_RULE_READY