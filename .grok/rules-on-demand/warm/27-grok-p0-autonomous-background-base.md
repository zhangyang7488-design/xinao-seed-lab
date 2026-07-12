# P0 后台底座 · 全局北极星（按需 Read · 非 always）

SENTINEL:GROK_P0_AUTONOMOUS_BACKGROUND_BASE_RULE_V1

**主合同：** `grok_p0_autonomous_background_base.v1.json`
**不锁你：** 规则锁语义与边界，不锁智力算力、不固定死；应完全理解用户要什么。

## 全局是什么

**P0 后台底座**：Temporal 耐久编排 + Docker `houtai-gongren` + worker 内 LangGraph；Grok 是唯一默认模型工人，宽度按 ready frontier、配额、延迟与证据动态计算。

**同构于你：** 上述五项目标对 **Grok 自身** 同构，不是只要求后台抽象系统而 Grok 自降格。

**不是：** ingress 绿、S verifier 绿、333 必先闭合、队列空=完成。

## 角色（纠偏后）

| 谁 | 干什么 |
|----|--------|
| **Grok heavy / 4.5** | 唯一默认模型工人；研究、测试、审计、证据 lane 均走规范三件套 |
| **Codex** | 思考与编排脑；紧耦合修改的单写者 |
| **非 Grok 模型** | 默认冻结；只有用户显式点名才可调用 |
| **WorkerPool** | 仅显式 bootstrap/fallback；不是默认执行面或耐久账本 |

## P0 语义环（工程不定死）

**相位（语义锁）：** 意图对齐 → 外部成熟对照 → 本机实施 → 真实测试/证据 → Grok/Codex 互审 → 下一最高收益对象。

这是适应性透镜，不是固定步骤、固定 lane 数、守护循环或第二编排器。

**用户偏好：** 由当前用户请求、核心索引和 D 盘检查点按最小相关切片读取；不引用已删除字段。

**工程类：** 后台自治实现 — D 盘 specs / 工具胶水宪法；不写 Grok JSON。

## P0 诚实

每个对象须以 verified / partial / blocked / unverified 诚实收口；不得以配置、队列空或模型自评冒充完成。

## 与 rule 22/26

成熟优先同构 + 三档执行 + 伪权限；本规则定**全局靶心**。

SENTINEL:GROK_P0_AUTONOMOUS_BACKGROUND_BASE_RULE_READY
