# P0 后台底座 · 动态收益北极星（按需 Read · 非 always）

SENTINEL:GROK_P0_AUTONOMOUS_BACKGROUND_BASE_RULE_V2

**主合同：** `grok_p0_autonomous_background_base.v1.json`
**双腿主路：** 当前交互 TUI 在线的有界工作通常走 A=`direct-grok-worker-pool`；只有显式交接后的关窗耐久、跨重启续作或无人后台多波才走 B=`Temporal→Docker houtai-gongren→worker-internal LangGraph`。已有 route receipt 优先连续，`continuous`/`resume` 本身不切腿。

## 全局语义

当前用户明确选择 continuous 时，唯一完成身份是恢复出的主线全局意图。每个有限 episode 保存局部证据后，必须回到主线全局按当前事实重算下一前沿；局部 `verified`、单个候选 `NO_ACTION` 或一条路径受阻都不能结束 continuous。

候选只在能缩小真实差距、增加有效证据或降低关键不确定性且净收益为正时执行；不空转、不为维持运行制造改动，也不因省 token、怕额度或未再次获授权跳过正收益调用。

## 动态分工

| lane | 作用 |
|---|---|
| **Grok** | 研究、审计、测试、证据和独立视角；收益接近时软偏好 |
| **Codex agents** | 上下文继承、紧耦合工程、并行验证 |
| **combined** | 两类优势能互补且额外成本有净收益时组合 |
| **WorkerPool** | 正常 A 腿；按 task fit/既有 route receipt 选择，不是 fallback、无条件默认或常驻补池 |

工人、工具、外搜、宽度和顺序均动态选择；没有唯一默认模型工人，也不要求用户逐次点名。额度是调度遥测，不是“不调用”的门禁。

## 停止与证据

只在用户 stop、用户改变 continuous 模式，或完整覆盖替代路径/继续发现/补证据/修前置后整条主线仍被不可抗拒条件阻断时停止。配置、进程存在、队列空、报告绿或局部里程碑都不能冒充完成。

SENTINEL:GROK_P0_AUTONOMOUS_BACKGROUND_BASE_RULE_READY
