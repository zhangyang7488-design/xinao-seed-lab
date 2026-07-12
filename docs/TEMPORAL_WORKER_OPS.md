# Temporal promoted worker · 运维手册（T9 / S5 / C08）

状态：ops guide（非 ADR）。与 `ADR-0001-EMBEDDED-KERNEL.md` **不冲突**：
内核仍是 SQLite 真源；Temporal 仅作 **promoted-task 执行附接**，
永不成为 dual-brain 治理 owner，也不替换 claim/lease/fencing。

当前实况（2026-07-12）：Temporal Server `1.31.0`、UI `2.49.1`、Python SDK
`1.30.0`；promoted queue 已进入官方 Worker Deployment，短任务使用
`PINNED`。日常 worker 运维不碰 compose；服务/schema 升级只能走独立预登记
canary、数据库备份/恢复演练和服务级回滚，不能借日常脚本顺手重建。

---

## 1. 范围与固定约定

| 项 | 值 |
|---|---|
| Workflow type | `XinaoPromotedTaskWorkflowV1` |
| Task queue（隔离） | `xinao-dualbrain-promoted-v1` |
| Namespace（默认） | `default` |
| gRPC address（本机默认） | `127.0.0.1:7233` |
| Workflow id 形态 | `xinao-task-{task_id}-g{control_epoch}` |
| 入口 | 仅显式 `temporal-start-promoted` |
| `auto_start_on_promote` | **必须 false** |
| chat / discuss → Temporal | **禁止** |
| Temporal 是否 dual-brain 治理 owner | **否** |
| Worker Deployment | `xinao-dualbrain-promoted` |
| Current build | `33da5bf45ff385e7b0407004a203508e` |
| Workflow versioning behavior | `PINNED` |

当前本机 Temporal 栈：

- `naijiu-shiwu` · `temporalio/server:1.31.0` · host `0.0.0.0:7233`
- `shiwu-mianban` · `temporalio/ui:2.49.1` · host `:8080`
- `shiwu-ku` · Temporal Postgres（compose 内部）
- `houtai-gongren` 轮询的是 **integrated-bus 队列族**，
  **不是** `xinao-dualbrain-promoted-v1`（不得用它冒充 dual-brain poller）

镜像与上游源码身份以
`E:\XINAO_RESEARCH_WORKSPACES\S\infra\temporal\official_source.v1.json` 为准；
上游形状钉在 `temporalio/samples-server@ca1106b647c34323876bd6f221f4310271096dd8`。

---

## 2. 环境变量（权威：`src/xinao_coordination/temporal/policy.py`）

| 变量 | 默认 | 语义 |
|---|---|---|
| `XINAO_TEMPORAL_ENABLED` | `0` | `1/true/yes/on` 才打开适配器 |
| `XINAO_TEMPORAL_MOCK` | `1` | 默认 mock 注册表；`0/false/no/off` 关 mock |
| `XINAO_TEMPORAL_LIVE` | `0` | `1` 才走 live 连接/start；**无 CLI `--live` 旗标** |
| `XINAO_TEMPORAL_ADDRESS` | `127.0.0.1:7233` | Temporal gRPC |
| `XINAO_TEMPORAL_NAMESPACE` | `default` | Namespace |
| `XINAO_TEMPORAL_TASK_QUEUE` | `xinao-dualbrain-promoted-v1` | 隔离 queue；勿与 bus 队列混用 |
| `XINAO_TEMPORAL_WORKFLOW_TYPE` | `XinaoPromotedTaskWorkflowV1` | worker_runtime 可选覆盖 |
| `XINAO_TEMPORAL_WORKER_LOG` | （可选） | G1 启动日志路径 |
| `XINAO_TEMPORAL_WORKER_VERSIONING` | `0` | canonical live worker 必须为 `1`；测试/历史 replay 可显式关 |
| `XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME` | 空 | versioning 开启时必须为 `xinao-dualbrain-promoted` |
| `XINAO_TEMPORAL_WORKER_BUILD_ID` | 空 | versioning 开启时必填；来自 `worker_deployment.v1.json` |

模式判定（`service.temporal_status`）：

1. `ENABLED=0` → `mode=disabled`
2. `ENABLED=1` 且 `LIVE=1` → `mode=live`（需真实 client/worker；见 §5）
3. 否则 → `mode=mock`（canary/CI 默认）

Managed 注入（不改源码，仅启动参数）：

```powershell
$Managed = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\provisioning\Invoke-XinaoCoordManaged.ps1'

# Mock canary（默认安全）
& $Managed -TemporalEnabled 1 -TemporalMock 1 -TemporalLive 0 -Target temporal-status

# Live probe / start（仅在 worker 已挂 poller 后）
& $Managed -TemporalEnabled 1 -TemporalMock 0 -TemporalLive 1 `
  -TemporalAddress '127.0.0.1:7233' -Target temporal-status
```

也可在调用进程上直接设 `Env:XINAO_TEMPORAL_*` 再 `-Target cli`。

---

## 3. 日常硬禁与已注册迁移例外

下列命令与行为在普通 dual-brain canary、night-run、peer 验收中 **默认禁止**
（`configs/modules/temporal.toml` → `[temporal.forbidden]`；证据字段
`no_live_temporal_recreate` / `no_docker_compose_up`）：

```text
# 禁止 — 会重建 Temporal 栈 / 抹 history / 破坏 27h+ 既有服务
docker compose up
docker compose up -d --force-recreate
docker compose up -d --renew-anon-volumes
docker compose down
docker compose down -v
docker restart naijiu-shiwu
docker rm -f naijiu-shiwu shiwu-mianban shiwu-ku
```

额外硬禁：

| 禁 | 原因 |
|---|---|
| `auto_start_on_promote=true` | promote 不得隐式起 workflow |
| chat/discuss 载荷进 Temporal | 仅 `metadata.promoted=true` 任务 |
| CLI/MCP 传入 `--live` | live **仅** env `XINAO_TEMPORAL_LIVE=1` |
| mock `pollers=1` 当作 live 焊通 | mock 假绿；C08 必须 CLI `task-queue describe` |
| 用 `houtai-gongren` bus 队列冒充 dual-brain poller | queue 名不同；须单独注册 |
| 把 Temporal 写成 dual-brain 治理 owner | 内核 + M-BG 仍权威 |
| canary 写生产 DB 冒充 live C08 | 隔离 canary DB 或明确 live 证据路径 |

**允许**：对 **已运行** 栈做只读探活（`temporal task-queue describe`、
UI、TCP `:7233`）、在 host 上 **新增** dual-brain worker 进程
（不 recreate Temporal 服务容器）。

**唯一例外形状**：单独命名的 server/schema 或 Worker Deployment 迁移，且已先有
精确 candidate/baseline、数据库 dump、隔离 restore 演练、独立 rollback、服务级
mutation 预算和正负 canary。例外不进入 `Invoke-PromotedTemporalWorker.ps1`，不得
扩大为 `compose down -v`、全栈重建或日常自愈。

---

## 4. 如何启动 promoted worker（live 焊通前置）

### 4.1 前置检查（零副作用）

```powershell
# 1) Temporal 服务已在跑（只读）
docker ps --filter name=naijiu-shiwu --format "{{.Names}} {{.Status}} {{.Ports}}"
# 期望：Up … (healthy)  0.0.0.0:7233->7233/tcp

# 2) promoted queue 当前 poller（基线；常为空）
temporal task-queue describe `
  --task-queue xinao-dualbrain-promoted-v1 `
  --address 127.0.0.1:7233 `
  --namespace default
# Pollers 空 = 未焊通；有 Identity（如 xinao-promoted-worker-g1）= worker 在轮询
# 夜跑初段曾为空；G1 启动后应以当次 describe 为准，禁止用 mock pollers 字段代替
```

对比：既有 bus worker 在别的 queue 上 **有** poller，例如
`xinao-integrated-langgraph-plugin-queue`。那 **不能** 代替
`xinao-dualbrain-promoted-v1`。

### 4.2 Worker 注册要求

Worker 实现归属 **G1**（`adapters/temporal/workflow.py` + `activities.py`
及可执行入口）。运维要求固定为：

1. `Client.connect(XINAO_TEMPORAL_ADDRESS, namespace=…)` 连 **既有** 服务。
2. `Worker(..., task_queue="xinao-dualbrain-promoted-v1",
   deployment_config=WorkerDeploymentConfig(...))`，deployment/build 来自 manifest。
3. 注册 workflow type `XinaoPromotedTaskWorkflowV1` 与配套 activities
   （activities 以 `operation_id` + stop/epoch 门禁；内核写 intent/证据）。
4. workflow `VersioningBehavior.PINNED`；启动时 versioning identity 缺失或不一致必须 fail closed。
5. `await worker.run()` 常驻；崩溃后 **重启同一 build/脚本**，禁止 compose recreate。
6. Identity 应可识别（日志/Deployment describe 可见），便于审计。

### 4.3 推荐启动形态（host 进程 · G1 入口）

入口与细节见 `adapters/temporal/README.md`；权威实现：

| 项 | 路径 |
|---|---|
| 启动脚本 | `adapters/temporal/run_worker.py` |
| Runtime | `adapters/temporal/worker_runtime.py`（`Client.connect` + `Worker.run`） |
| SDK pin | `adapters/temporal/requirements-temporal.txt`（`temporalio==1.30.0`） |
| Deployment manifest | `adapters/temporal/worker_deployment.v1.json` |
| Identity（观测） | 当前 build/PID 以 Deployment describe + fenced process evidence 为准 |
| Replay gate | `adapters/temporal/replay_promoted_histories.py` |

SDK 已同时钉在 `pyproject.toml`、`uv.lock` 和 worker requirements；新 build 应创建
side-by-side generation，不能就地污染仍承担流量的旧环境：

```bat
E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\.venv\Scripts\python.exe -m pip install -r adapters\temporal\requirements-temporal.txt
```

前台启动（仅诊断；canonical live 用隐藏入口）：

```powershell
$Root = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination'
$env:XINAO_TEMPORAL_ADDRESS    = '127.0.0.1:7233'
$env:XINAO_TEMPORAL_NAMESPACE  = 'default'
$env:XINAO_TEMPORAL_TASK_QUEUE = 'xinao-dualbrain-promoted-v1'
$env:XINAO_TEMPORAL_WORKER_VERSIONING = '1'
$env:XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME = 'xinao-dualbrain-promoted'
$env:XINAO_TEMPORAL_WORKER_BUILD_ID = '33da5bf45ff385e7b0407004a203508e'
& "$Root\.venv\Scripts\python.exe" "$Root\adapters\temporal\run_worker.py"
```

隐藏窗口（canonical；manifest fail-closed，不 recreate compose）：

```powershell
$Root = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination'
& "$Root\adapters\temporal\start_worker_hidden.ps1" `
  -PythonExe 'D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\generations\worker-versioning-sdk-1.30.0-ca1106b\Scripts\python.exe' `
  -DeploymentManifest "$Root\adapters\temporal\worker_deployment.v1.json" `
  -EvidenceDir 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\promoted_worker' `
  -PassThru
```

**可选诚实映射**：若明确把既有 worker 扩容到 `xinao-dualbrain-promoted-v1`
并在 `task-queue describe` 上出现真实 Identity，可记为 *mapped poller*；
禁止在无 describe 证据时口头映射 `houtai-gongren`。

### 4.4 Worker 就绪尺（必过）

```powershell
temporal task-queue describe `
  --task-queue xinao-dualbrain-promoted-v1 `
  --address 127.0.0.1:7233
```

**PASS 条件**：

- `temporal worker deployment describe --name xinao-dualbrain-promoted` 的 Current
  build 与 manifest 一致，ramping 为空；
- Current version 的 workflow/activity task queue 均有 poller；
- `LastAccessTime` 近（通常 < 1 min）；
- Identity 非空、非 mock 字符串。

**FAIL 条件**：Deployment 无 Current、build 漂移、poller 缺失；或仅应用层 mock
`pollers: 1`。CLI 默认的 unversioned queue 表不替代 Deployment version 证据。

切换新 build 必须先旁挂 candidate、重放全部 retained history、做真实 E2E，再通过
`set-ramping-version` / `set-current-version` 路由；不能靠停止旧进程碰运气。

历史 replay（写 D 盘证据，不调用模型）：

```powershell
$Py = 'D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\generations\worker-versioning-sdk-1.30.0-ca1106b\Scripts\python.exe'
& $Py adapters\temporal\replay_promoted_histories.py `
  --output-dir 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\promoted_replay'
```

### 4.5 客户端显式 start（worker 就绪后）

```powershell
$Managed = 'E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\provisioning\Invoke-XinaoCoordManaged.ps1'

# Live 环境（Admin live client 焊通后）
$env:XINAO_TEMPORAL_ENABLED = '1'
$env:XINAO_TEMPORAL_MOCK    = '0'
$env:XINAO_TEMPORAL_LIVE    = '1'
$env:XINAO_TEMPORAL_ADDRESS = '127.0.0.1:7233'

& $Managed -Target temporal-status
# 期望：mode=live；connectivity.reachable=true；poller 证据来自 describe 而非 mock

& $Managed -Target temporal-start-promoted `
  -TargetArgs @('--actor','codex','--task-id','<promoted_task_id>','--idempotency-key','live-c08-1')
# 期望：mode=live（或等价）；run_id 非 mock-run-*；二次同键 replayed=true
```

MCP 等价：`temporal_status` / `temporal_start_promoted`（角色由
`XINAO_COORD_ROLE` 绑定；无 caller actor 参数）。Stop 激活时 start 必须被抢占拒绝。

---

## 5. Mock vs Live 验收尺（Scoped ≠ Welded）

### 5.1 Mock / canary → 最高 `PASS_SCOPED*`（**不是** C08 PASS）

| 尺 | 要求 |
|---|---|
| Env | `ENABLED=1` `MOCK=1` `LIVE=0` |
| 代码路径 | 进程内 mock 注册表；`mode=mock` |
| 测试 | `tests/test_t9_temporal_promoted_adapter.py` 全过 |
| 证据脚本 | `scripts/_t9_temporal_promoted_evidence.py` → `PASS_SCOPED_CANARY` |
| S5 | `scripts/_s5_temporal_adapter_landed_evidence.py` → implementation landed |
| 硬声明 | `live_workflow_start_attempted=false`；`live_temporal_recreate=false`；`no_docker_compose_up=true` |
| 禁止升级 | 不得把 mock 幂等 start 写成 C08 / product_closed / completion_claim |

Mock 可证明：**薄适配落地、promoted-only、幂等、Stop 抢占、角色边界**。
Mock **不能** 证明：真实 poller、history、跨进程接管、live start_workflow。

> 注：当前 mock `describe_promoted_queue` 可能报 `pollers=1`——**属假指标**，
> 验收与 inventory 必须分列 **code landed** vs **live welded**；不得引用该字段为 live 焊通。

### 5.2 Live / C08 → 才可讨论 `C08 PASS`

全部满足才算 live welded（缺一 → `PARTIAL` / `FAIL_LIVE`）：

| # | 尺 | 证据 |
|---|---|---|
| L1 | 既有 Temporal TCP/服务 healthy | `docker ps` / socket；**无 recreate** |
| L2 | promoted queue 真实 poller ≥1 | `temporal task-queue describe -t xinao-dualbrain-promoted-v1` 非空 Pollers |
| L3 | Admin live client 真 `start_workflow` | `XINAO_TEMPORAL_LIVE=1` 不再对 live 抛“未实现”类 ValidationError |
| L4 | 显式 start 成功 | `temporal-start-promoted` 返回非 mock run_id；workflow 可 describe |
| L5 | 幂等 | 同 task/idem 二次 start → already-started / `replayed=true` |
| L6 | Stop 抢占 | user stop 后 start 拒绝 |
| L7 | 无 chat ingress | 非 promoted / discuss-only 被拒 |
| L8 | 证据落盘 | `C08_temporal_promoted_live_*.json`（或等价）含 describe 摘录与 queue poller 摘录 |
| L9 | 副作用边界 | canary 未 `compose up/recreate`；`completion_claim_allowed` 仍按整包策略 |

当前基线（2026-07-12）：live start、promoted poller、真实 history、PINNED
Worker Deployment 和 Grok→LangGraph→OpenHands broker E2E 均已焊通。配置或旧 PASS
标签仍不能代替新 build 的 replay、真实 E2E 与禁止副作用检查。

### 5.3 分列登记（S5 inventory 规则）

```text
code_landed:     adapters/temporal + src/.../temporal + CLI/MCP surface
live_welded:     poller_on_promoted_queue && real_start_workflow && live_evidence_json
mock_canary:     PASS_SCOPED_CANARY  (≠ C08 PASS)
C08_verdict:     PASS only if live_welded
```

---

## 6. 日常运维检查清单

1. **探活**：`naijiu-shiwu` healthy；`:7233` 可达。
2. **Poller**：`task-queue describe` on `xinao-dualbrain-promoted-v1`。
3. **Policy**：`temporal-status` → `auto_start_on_promote=false`；`mbg_temporal_owner=false`。
4. **Mock 回归**（默认）：`ENABLED=1 MOCK=1 LIVE=0` + T9 pytest / evidence 脚本。
5. **Versioning**：Deployment Current 必须等于 manifest，ramping 默认为空；新 build
   走旁挂→replay→E2E→ramp/current，失败先路由回已知 build。
6. **Live 仅在 L2+L3 就绪后**：设 `LIVE=1`，跑 live canary；失败时只处理精确身份的
   candidate worker，不 touch compose Temporal 服务。
7. **Stop**：全局面板 stop 时不得继续 start；清理 stop 后再试。
8. **回滚**：路由回退与 worker 退役优先；若 schema 已迁移，必须使用预迁移 DB dump
   和旧 server overlay 的完整回滚，**禁止** `compose down -v`“当回滚”。

---

## 7. 参考路径

| 路径 | 用途 |
|---|---|
| `src/xinao_coordination/temporal/policy.py` | env 默认与 policy 字典 |
| `src/xinao_coordination/temporal/client.py` | mock/live client 边界 |
| `src/xinao_coordination/temporal/envelope.py` | promoted-only envelope |
| `adapters/temporal/*` | shim + `run_worker.py` / `worker_runtime.py` |
| `adapters/temporal/worker_deployment.v1.json` | deployment/build/source digest SSOT |
| `adapters/temporal/replay_promoted_histories.py` | 全 retained history 导出与确定性 replay |
| `configs/modules/temporal.toml` | 默认与 forbidden 清单 |
| `provisioning/Invoke-XinaoCoordManaged.ps1` | managed env 注入 + temporal targets |
| `scripts/_t9_temporal_promoted_evidence.py` | mock canary 证据 |
| `scripts/_s5_temporal_adapter_landed_evidence.py` | code landed 证据 |
| `docs/ADR-0001-EMBEDDED-KERNEL.md` | 内核默认不装 Temporal；升级触发器 |
| `docs/OPERATIONS.md` | 本机协调入口 / 备份 / 租约 |

证据（G14）：
`D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G14_ops_doc\`
