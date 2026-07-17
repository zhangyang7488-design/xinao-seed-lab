# T1+T2+T5 回滚与负测清单

范围：`dual-brain-coordination` 内核纵切（投递→讨论→收口→晋升）。  
**禁止**触碰 live 栈（生产 `dual_brain_coordination` 库、运行中 Temporal、M-KEEP、桌面快捷方式）。

自动化入口：`tests/test_t1t2t5_rollback_negative.py`  
纵切正测：`tests/test_t1t2t5_vertical_slice.py`

## 负测不变式

| ID | 场景 | 期望 | 自动化 |
|----|------|------|--------|
| N1 | **禁用 / 缺失 AMQ** | 内核 `open/post/close/promote` 仍可用；`AmqTransport` 仅自身失败 | `test_kernel_usable_when_amq_disabled_or_missing` |
| N2 | **Stop 后** | 无新 `promote` / `dispatch`；Stop 不自动解除 | `test_stop_blocks_new_promote_and_dispatch` |
| N3 | **进程重启** | 同一 sqlite 文件恢复 thread / task / stop meta；backup 亦可恢复 | `test_restart_recovers_state_from_same_sqlite_file` |

## 回滚步骤（ops · 可回滚域）

### R0 — 安全边界

1. 只操作 **canary / 临时** 库，或明确 `XINAO_COORD_DB` 指向隔离路径。  
2. 默认 live 库：`D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\coordination.sqlite3` — **本清单不写它**。  
3. 无 daemon；回滚 = 停调用 + 换库/清 stop + 必要时从 backup 恢复。

### R1 — 关掉 AMQ 薄适配（旁路降级）

AMQ 是可选投递面，**不是**内核真源。

1. 停止调用 `amq-send` / `amq-ingest` / `amq-outbox-flush`。  
2. 去掉或改错 `XINAO_AMQ_BIN` / `AMQ` / `--amq-bin`（模拟缺失）。  
3. 验证内核仍可：

```powershell
$Root = 'E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination'
$Managed = Join-Path $Root 'provisioning\Invoke-XinaoCoordManaged.ps1'
$env:XINAO_COORD_DB = 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\rollback_probe.sqlite3'
& $Managed -Target cli -TargetArgs @('doctor')
& $Managed -Target cli -TargetArgs @('thread-open','--actor','codex','--title','amq-off','--body','kernel','--idempotency-key','rb-amq-off')
```

期望：CLI/内核绿；AMQ 子进程命令可失败且不污染 kernel 状态。

### R2 — Stop：冻结新晋升

```powershell
& $Managed -Target cli -TargetArgs @('stop','--actor','user','--reason','rollback freeze','--idempotency-key','rb-stop')
& $Managed -Target cli -TargetArgs @('stop-status')
# promote 必须失败（InvalidTransitionError / stop is active）
& $Managed -Target cli -TargetArgs @('promote','--actor','codex','--source-thread-id','<id>','--decision-hash','<hash>','--title','x','--goal','y','--idempotency-key','must-fail')
```

解除（显式，永不自动）：

```powershell
& $Managed -Target cli -TargetArgs @('stop-clear','--actor','user','--reason','resume authorized','--idempotency-key','rb-clear')
```

### R3 — 从 sqlite 恢复（重启 / 损坏替换）

耐久单元 = `coordination.sqlite3`（+ 运行中的 `-wal`/`-shm` 一体，勿用普通复制活库）。

1. 停止所有显式 CLI/MCP 对该库的写调用。  
2. 保留损坏库与 wal/shm 作证据。  
3. 用 Online Backup 产出冷备份，或指向已验收备份：

```powershell
& $Managed -Target cli -TargetArgs @('backup','--output','D:\XINAO_RESEARCH_RUNTIME\backups\dual-brain-canary-rb.sqlite3')
$env:XINAO_COORD_DB = 'D:\XINAO_RESEARCH_RUNTIME\backups\dual-brain-canary-rb.sqlite3'
& $Managed -Target cli -TargetArgs @('doctor')
```

4. `doctor` PASS 后才继续 claim/promote。  
5. 若需清 stop：仅 user `stop-clear`（见 R2）。

### R4 — 验证命令（pytest · 隔离）

```powershell
cd E:\XINAO_RESEARCH_WORKSPACES\S\projects\dual-brain-coordination
uv run pytest tests/test_t1t2t5_rollback_negative.py -q
```

## 诚实边界

- 本清单 = 内核/旁路可回滚验证；**≠** T1+T2+T5 产品纵切宣称完成。  
- S1 AMQ 冒烟成功 ≠ 纵切完成。  
- 不抢 Temporal 事务核；不启 M-KEEP。
