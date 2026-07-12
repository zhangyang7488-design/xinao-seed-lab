# ADR-0001：嵌入式协调内核

状态：accepted，2026-07-11。

## 决策

默认组合是 `A2A types + APSW/SQLite + CLI/MCP adapters`：

1. A2A 负责对外的 Message、Task、Artifact 词汇与转换。
2. SQLite 是本机唯一耐久真源；事件证据、当前投影和必要 outbox 在同一事务提交。
3. 专用任务表仅补 A2A `DatabaseTaskStore` 缺失的 claim、lease、fencing、retry 和 idempotency。
4. CLI/MCP 都调用同一个服务层，不各自实现状态机。
5. route assessment 是可解释建议；只有授权、角色、状态转换、版本和租约令牌是硬边界。

## 为什么不是旧文件总线

多文件 read-modify-write 不能让消息、投影、队列和产物原子提交，也无法可靠处理崩溃、并发领取和重试。

## 为什么默认不装 DBOS、Temporal 或 NATS

- DBOS 适合单 owner Python 工作流恢复，但会把通用跨进程任务收件箱收窄成 Python 函数工作流；达到长步骤续跑需求时作为 executor adapter 接入。
- Temporal 在跨天/跨机自动接管、版本化运行和多语言 worker 时收益最高，但当前会引入独立服务运维。
- NATS JetStream 在跨机、高吞吐和广播/重放成为瓶颈时有价值；本机低规模下 SQLite 已提供更小的故障面。

## 升级触发器

- 需要多机或高吞吐 fan-out：评估 NATS JetStream/PostgreSQL。
- 任务跨天、worker 崩溃后必须由别机自动接管、活跃任务跨代码版本：直接评估 Temporal。
- 任务本身是单进程 Python durable workflow：可评估 DBOS adapter，但不替换协调真源。
- 只有在外部副作用需要异步通知时才 drain outbox；同库消费者直接查询任务和事件。

