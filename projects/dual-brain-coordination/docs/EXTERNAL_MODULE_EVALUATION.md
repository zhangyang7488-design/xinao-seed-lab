# 外部成熟模块评估

检索日期：2026-07-11。只以官方文档、官方仓库和发布页作为采用依据。

## 结论

没有一个成熟开源项目能无代价覆盖“讨论 → 任务 → Admin 领取 → Artifact → 门铃”。默认主路因此组合成熟原语，而不安装第二套 Agent 平台：

| 层 | 采用 | 为什么 |
|---|---|---|
| 互操作语义 | `a2a-sdk==1.1.0` | 官方 `Message / Task / TaskStatus / Artifact` 类型，Apache-2.0 |
| 本机事务载体 | `apsw==3.53.3.0` + SQLite 3.53.3 | 无服务、原生 Windows、ACID、WAL、在线备份；避开本机 Python 自带 SQLite 3.50.4 的 WAL-reset 缺陷窗口 |
| 本地工具面 | `mcp==1.28.1` + stdio | Codex 原生工具入口；MCP 不承担耐久队列语义 |
| 命令行 | 标准库 `argparse` | Grok/Admin 可直接调用，不为少量命令增加控制台平台 |
| 类型校验 | A2A 已带的 Pydantic | 动态收益信号和公开输入有边界校验 |
| 观测 | `opentelemetry-api==1.42.1` | 默认 no-op，不监听、不上传、不记录 prompt/CoT；需要时由应用装 SDK |
| 状态机测试 | dev-only Hypothesis | 自动生成并缩减领取、暂停、恢复、重试序列 |

依赖全部由 `uv.lock` 钉住；不安装数据库服务、消息代理、Web UI、云 tracing 或后台 worker。

## 已复用与没有误用的 A2A 能力

A2A 1.0 规范把 Message、Task 和 Artifact 明确分开，并说明关键消息不能依赖瞬时流可靠投递：[A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)。官方 Python SDK 1.1.0 提供稳定类型、client/server、handler、route 和数据库 TaskStore：[release](https://github.com/a2aproject/a2a-python/releases/tag/v1.1.0)、[API](https://a2a-protocol.org/latest/sdk/python/api/)。

本工程直接使用 `a2a.types.Message/Task/Artifact/Part/TaskStatus/TaskState` 导出互操作对象，但没有把官方 `DatabaseTaskStore` 伪装成 worker queue。其公开接口只有 `save/get/list/delete`，底层是 Task 快照 `merge`，没有 claim、lease、ack、retry、DLQ、优先级或幂等请求键：[DatabaseTaskStore source](https://raw.githubusercontent.com/a2aproject/a2a-python/v1.1.0/src/a2a/server/tasks/database_task_store.py)、[TaskStore source](https://raw.githubusercontent.com/a2aproject/a2a-python/v1.1.0/src/a2a/server/tasks/task_store.py)。

因此本工程只补一组专用、受事务约束的任务字段，并保持 A2A adapter 为只读映射，避免双真源。

## SQLite 与 APSW

SQLite 提供串行化写事务；`BEGIN IMMEDIATE` 在事务开始就取得写权，避免读后升级产生历史分叉：[SQLite isolation](https://www.sqlite.org/isolation.html)。WAL 允许读写并发，但必须与 `-wal/-shm` 一起管理，并保持读事务短：[SQLite WAL](https://sqlite.org/wal.html)。在线备份必须使用 SQLite Backup API，不粗拷活库文件：[SQLite backup](https://www.sqlite.org/backup.html)。

2026 年 SQLite 官方披露并修复罕见 WAL-reset 数据竞争：主线修复版本为 3.51.3，部分旧线有回移。本机 Python 3.12 的 `sqlite3` 实际链接 3.50.4，因此本工程改用维护活跃、Windows 有 wheel、直接携带 SQLite 3.53.3 的 APSW 3.53.3.0：[APSW release](https://pypi.org/project/apsw/)、[APSW docs](https://rogerbinns.github.io/apsw/)。程序启动会拒绝低于 3.51.3 的运行时，而不是静默退化。

## 默认不采用的完整载体

| 候选 | 有效机制 | 当前不进默认主路的原因 | 何时升级 |
|---|---|---|---|
| [NATS JetStream](https://docs.nats.io/nats-concepts/jetstream) | durable stream、work queue、ACK、重放、去重 | 需要独立 server；当前本机规模没有覆盖运维成本 | 跨机、高吞吐、多个独立 worker、HA 或长周期重放 |
| [DBOS Python](https://github.com/dbos-inc/dbos-transact-py) | workflow ID、step checkpoint、durable queue、send/recv | 更适合单 owner Python 函数工作流；会把通用跨进程协调收窄为第二执行运行时 | 某类任务本身明确需要 Python step 续跑时做 executor adapter |
| [Temporal](https://github.com/temporalio/temporal) | 跨机接管、history replay、Task Queue、Signals/Updates、版本治理 | 生产需要 Temporal Service 和数据库；当前太重 | 任务跨天、必须跨机自动接管、活跃任务跨代码版本、多语言 worker |
| [LangGraph](https://github.com/langchain-ai/langgraph) | agent 内部 checkpoint、interrupt | 没有共享 worker claim/lease/ownership | 某个任务本身确实是可视化 agent 状态图 |
| [Restate](https://github.com/restatedev/restate) | keyed state、fencing、durable RPC | Server 为 BSL 1.1 且无原生 Windows server binary | 接受许可证与 Docker/WSL，且需要 keyed single-writer |
| [Dapr Workflow](https://docs.dapr.io/developing-applications/building-blocks/workflow/) | durable orchestration、external events | sidecar 与本地基础组件故障面高 | 已经全面采用 Dapr 的微服务系统 |
| [Prefect](https://github.com/PrefectHQ/prefect) | 数据流、调度、HITL UI | 目标偏数据/批处理且需 server/worker | 需求本质变为数据管道操作台 |
| [Hatchet](https://github.com/hatchet-dev/hatchet) | 高吞吐后台任务、事件等待 | 明确 at-least-once，通常需 server/Postgres | 高吞吐 background queue 成为主问题 |

外部副作用在这些框架中仍不能凭框架自动成为物理 exactly-once。Temporal 官方明确 Activity 可能执行多次：[Temporal Activity](https://docs.temporal.io/activity-definition)。本工程因此保留 operation/idempotency key、同库事务和显式证据语义。

## 消息与窗口候选

- [AMQ](https://github.com/avivsinai/agent-message-queue) 的 Maildir、thread、receipt、handoff、DLQ 可参考，但 Windows wake 仍依赖 WSL，且它不负责任务调度。
- [agmsg](https://github.com/fujibee/agmsg) 适合轻讨论，但项目明确不是任务队列，Windows 依赖 Git Bash。
- [MCP Agent Mail](https://github.com/Dicklesworthstone/mcp_agent_mail) 有 thread/ACK/附件/文件租约机制，但需要另一任务系统并形成第二平台。
- [AGNTCY SLIM](https://docs.agntcy.org/slim/overview/) 面向跨组织加密消息与 routing node，当前 2.x alpha 对本机双脑过重。
- IBM BeeAI ACP 已并入 A2A；AGNTCY `acp-spec` 已归档，均不作为新主路。
- tmux/amux/amq-squad 是 Unix 会话或团队 UI，不是 Windows 耐久总线。

门铃只做 best-effort wake/focus。outbox ACK 明确返回 `model_read=false`；只有目标角色主动调用 receipt 工具，才记录 `observed`。

## 智力保护判据

外部模块只在同时满足下列条件时进入主路：

1. 补的是可观察的真实能力缺口，不只是换术语。
2. 净收益覆盖新 daemon、身份、密钥、延迟和故障面。
3. 能钉版本、离线测试、显式关闭或替换。
4. 不规定模型如何思考，不要求固定轮数、固定 agent 数或必经流水线。

当前动态收益评估仅输出 `direct / discuss / task / discuss_then_task` 建议和理由，用户当前请求可直接覆盖；建议不参与数据库授权或状态门闩。
