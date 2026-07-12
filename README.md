# XINAO dual-brain coordination

这是一个本机嵌入式协调内核，不是第二套 Agent 平台。它把成熟模块组合为：

- A2A 1.1 的 `Message / Task / Artifact` 互操作语义；
- APSW 携带的 SQLite 3.53.3，负责跨进程事务、约束和崩溃恢复；
- Codex/Grok/Admin 共用的 CLI 与 MCP 薄入口；
- 可选、显式调用的通知 outbox；通知成功不等于模型已读。

Grok ACP 载体是可替换的薄适配，并保留一个源码级回滚开关。本机 canonical Codex/Grok/Admin
新进程默认暴露 40 个讨论、任务、证据和通知工具；只有显式设置
`XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS=1` 的调用者才会看到另外 5 个 `operation-*` 工具。
operation 提交会 best-effort 即时拉起短生命周期 worker；首次 launcher 失败时，同一调用者只做一次
90 秒上限的前台 reconcile。能力可用不等于每轮强制调用；入队 ACK 也绝不表述为模型完成。
独立 ACP 薄入口默认把工作目录放在 D 盘受管 scratch；`submit`/`run` 等待真实 terminal，并使用
quiet 输出只返回最终文本，不外泄 thought 事件。运行时缺失时按固定版本和哈希自动补足，正常快路不访问网络。
quiet 入口只丢弃 acpx 明确定义的 `[acpx] tokens:` / `[acpx] cost:` 两类 stderr 计量元数据；
其他 stderr 与非零退出仍原样可见。Node 主程序与 `npm.cmd` 都有固定哈希；若仅 `npm.cmd` 丢失，
入口会优先从已验证的本地 Node archive 原子补回，离线时也无需重新下载。

默认状态目录是 `D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination`。工程不创建服务、计划任务、开机项或隐藏守护进程；跨进程恢复只在提交失败、SessionStart 审计或人工显式 `Check` 时有界执行。

默认运行入口不是工程内 `.venv`，而是 `provisioning\Invoke-XinaoCoordManaged.ps1`。它在 D 盘创建不可变代际：正常路径只验证并启动当前代际；代际或 uv/Python 缺失时，才使用固定哈希的 uv 0.11.16、uv 管理 Python 3.12.13、`uv.lock` 与带哈希的构建约束自动补足。并发冷启动由跨进程文件锁收敛到一个写者。

ACPX 代际另把完整 payload 文件索引和摘要写入代际目录之外的
`D:\XINAO_RESEARCH_RUNTIME\tools\acpx\trust\payload-anchors`。代际内 `generation.json` 与外置锚必须同时吻合；
因此同时改 payload 和自报 manifest 也不会进入快路。锚缺失时只能由 frozen `package-lock.json`、固定
tarball integrity、禁用 install scripts 的一次干净安装建立；已有锚冲突时保守失败，不用当前 payload 覆盖锚。

## 核心原则

讨论、任务和产物是不同对象。只有权限、状态、幂等、租约和证据属于硬约束；“是否先讨论、是否调用第二个脑”由可解释的预期净收益建议决定，建议永远不是执行门闩。

CLI 的 `--actor` 仍是可信本机运维声明；MCP 则由启动配置中的
`XINAO_COORD_ROLE=codex|grok_4_5|admin` 绑定为单一角色，所有变更工具都不接受调用方传入
`actor`/`worker_id`。这能阻止模型在工具参数中冒充另一角色，但不是密码学进程认证；门铃 ACK 和
receipt 仍不会伪称目标模型本人已读。

## 开发

```powershell
uv sync --dev
uv run xinao-coord --help
uv run pytest
```

生产/跨进程入口：

```powershell
.\provisioning\Invoke-XinaoCoordManaged.ps1 -Target ensure
.\provisioning\Invoke-XinaoCoordManaged.ps1 -Target cli -TargetArgs @('doctor')
.\provisioning\Invoke-XinaoCoordManaged.ps1 -Target mcp
```

详细设计、外部方案比较和升级阈值见 `docs/`。
