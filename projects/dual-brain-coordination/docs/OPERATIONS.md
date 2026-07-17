# 本机操作与恢复

## 状态与入口

- 工程：`E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination`
- 默认数据库：`D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3`
- 托管入口：`E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination\provisioning\Invoke-XinaoCoordManaged.ps1`
- 当前代际指针：`D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\current.json`
- CLI：`Invoke-XinaoCoordManaged.ps1 -Target cli -TargetArgs ...`
- MCP：`Invoke-XinaoCoordManaged.ps1 -Target mcp`

也可以用 `XINAO_COORD_DB` 指向隔离测试库。数据库、`-wal` 和 `-shm` 是一个整体；活库不得用普通文件复制备份。

## 最小工作流

```powershell
$Root = 'E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination'
$Managed = Join-Path $Root 'provisioning\Invoke-XinaoCoordManaged.ps1'
& $Managed -Target cli -TargetArgs @('route-assess', '--uncertainty', '0.8', '--complementarity', '0.9')
& $Managed -Target cli -TargetArgs @('thread-open', '--actor', 'codex', '--title', '方案讨论', '--body', '提案', '--idempotency-key', 'demo-open')
& $Managed -Target cli -TargetArgs @('task-list', '--state', 'queued')
& $Managed -Target cli -TargetArgs @('task-claim', '--worker-id', 'admin', '--idempotency-key', 'claim-001')
```

所有写命令都接受或生成幂等键。外部调用方重试时必须复用同一键；同一键换 payload 会被拒绝。

## 租约与接管

- `task-claim` 返回不可猜测 lease token。
- `task-start/heartbeat/complete/fail` 必须携带当前 token。
- 暂停、取消、失败重试或租约过期会递增 `control_epoch` 并清空 token；旧 worker 的迟到提交被拒绝。
- 无后台 sweep。进程启动、领取前或人工调用 `sweep` 时回收过期租约。

Agent operation 使用独立的短时对账任务，不与交互 TUI watchdog 耦合：

```powershell
& "$Root\provisioning\Invoke-XinaoCoordReconcile.ps1" -Mode Check
& "$Root\provisioning\Invoke-XinaoCoordReconcile.ps1" -Mode Status
```

提交会 best-effort 立即启动临时 worker；若 launcher 创建失败，同一调用者立即做一次 90 秒上限的
前台 reconcile。SessionStart/精确会话恢复可以先检查 nonterminal operation，只在存在
`queued/retry_wait` 时显式执行一次 `Check`。工程不注册计划任务；如果所有交互进程都消失，durable
operation 会保留到下次 SessionStart 或人工 `Check`，不会伪装成无人值守连续运行。

## 完成与证据

`task-complete` 必须同时提供非空摘要和证据列表。内核只声明 `evidence_attached_not_independently_verified`，不会把自报证据升级成 verified。产物可先用 `artifact-add` 注册；本地文件会计算 SHA-256 和大小。

## 门铃与回执

- `notification-pull/ack` 处理外部适配器门铃；ACK 只代表适配器成功投递。
- `receipt-record` 只接受对象的收件人/所有者角色，并记录一次显式本地工具声明。CLI 的
  `--actor` 仍是 trusted-local caller-declared role；MCP 由进程环境 `XINAO_COORD_ROLE` 绑定，
  变更工具 schema 不暴露 `actor`。这不是密码学身份认证，因此回执不会被表述成“已证明目标模型本人阅读”。
- 门铃失败不会丢 Task/Message；调用方可从数据库重新列出。

## 健康、备份与恢复

T1+T2+T5 回滚/负测清单（禁用 AMQ、Stop 后无 promote、sqlite 重启恢复）：见 `docs/ROLLBACK_NEGATIVE.md`，自动化 `tests/test_t1t2t5_rollback_negative.py`。

```powershell
& $Managed -Target cli -TargetArgs @('doctor')
& $Managed -Target cli -TargetArgs @('sweep')
& $Managed -Target cli -TargetArgs @('backup', '--output', 'D:\XINAO_RESEARCH_RUNTIME\backups\dual-brain-20260711.sqlite3')
```

冷启动只有在代际/前置缺失时才联网；固定 uv 缺失时会下载官方安装器并同时验证安装器与最终 `uv.exe` SHA-256。运行依赖严格读取 `uv.lock`，工程 wheel 使用 Hatchling 1.31.0 及完整哈希约束构建。正常 MCP/CLI 启动不调用 uv，也不触网。

`backup` 使用 SQLite Online Backup API，拒绝覆盖已有目标，并在完成后重新执行 quick check、foreign key check 和 schema check。

恢复时：

1. 停止所有显式 CLI/MCP 调用，不需要停止 daemon，因为工程没有 daemon。
2. 保留损坏库及其 `-wal/-shm` 作为证据，不粗删。
3. 将 `XINAO_COORD_DB` 指向已验收备份，先运行 `doctor`。
4. 只有 doctor PASS 后才继续显式调用入口或领取。

## 真实边界

- SQLite 是单 writer、多 reader；本机低/中并发合适，不是跨机 HA。
- 无后台 reconciler；若所有调用进程消失，数据仍会保留，但崩溃 worker 要到下次 SessionStart、提交失败回退或人工 `Check` 才继续。
- A2A adapter 当前提供标准对象导出；没有默认打开网络 A2A server。
- MCP 是工具面，不是消息总线。
- CLI 的 `actor` 是可信本机协作声明；每个 MCP 进程必须绑定且只绑定一个
  `XINAO_COORD_ROLE`。角色校验阻止工具参数内的跨角色冒充，但不是面向本机管理员的安全边界或密码学认证。
  Admin 被硬性禁止 open/post/close 讨论；`thread-get` 与 `events-list` 仍是本机共享只读查询，不构成读隔离。
- 不保证任意 HTTP/Git/邮件副作用 exactly-once；目标系统仍需幂等键或事后查询核验。
