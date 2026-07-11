# Temporal Host Grok WorkerPool（目标⑤ · 薄入口）

**合同：** `grok_temporal_host_grok_pool.v1.json`  
**入口：** `Invoke-GrokHostWorkerPoolFromTemporal.ps1`（短名：`Invoke-GrokTemporalHostPoolTrigger.ps1`）

## Activity 语义（钉死）

| 项 | 值 |
|----|-----|
| Activity 名 | `trigger_host_grok_worker_pool` |
| 语义 | **触发** Windows Host 上的 Grok WorkerPool |
| Grok 进程位置 | **仅 Host**（`CREATE_NO_WINDOW`） |
| Docker `houtai-gongren` | **不**在容器内 spawn `grok` |
| 桌面 `.lnk` | **不读**（不是启动路径） |

```text
Temporal (或 Host 侧调用者)
  → Invoke-GrokHostWorkerPoolFromTemporal.ps1
  → Invoke-CodexDispatchGrokWorkerPool.ps1
  → Invoke-GrokWorkerPool.ps1 -N
  → N × Invoke-GrokComposer25Worker.ps1   # Host only
```

## 参数

| 参数 | 说明 |
|------|------|
| `-N` | 并行工人数（1–32） |
| `-Prompt` / `-PromptFile` | 任务正文 |
| `-Cwd` | 工人工作目录 |
| `-MaxTurns` | 每路 max turns（烟测用 1） |
| `-WorkflowId` / `-RunId` | 可选，写入 state 关联 Temporal |
| `-SkipPauseGate` | 绕过 PAUSED_ALL（重连/烟测） |

## 证据

| 文件 | 用途 |
|------|------|
| `D:\XINAO_RESEARCH_RUNTIME\state\temporal_host_grok_pool\latest.json` | 本触发 state（`triggered_on=windows_host`, `not_docker_worker=true`, `pool_latest`） |
| `D:\XINAO_RESEARCH_RUNTIME\state\grok_worker_pool\latest.json` | 池汇总 |
| `D:\XINAO_RESEARCH_RUNTIME\readback\zh\temporal_host_grok_pool_latest.md` | 中文 readback |

## S 仓 activity 注册（可选 · 未在本交付改图）

若后续在 S 注册 activity，建议：

```text
name: trigger_host_grok_worker_pool
body: 在 **Windows Host** 执行上述 ps1（subprocess CREATE_NO_WINDOW）
禁止: 在 houtai-gongren 容器内找 Desktop .lnk / 跑 grok CLI
```

不要为了接这条路径大改现有 Temporal workflow 图；薄绑即可。

## 烟测

```powershell
cd <bridge>
.\Invoke-GrokHostWorkerPoolFromTemporal.ps1 -N 1 `
  -Prompt "Reply only: TEMPORAL_HOST_POOL_OK" `
  -MaxTurns 1 -TimeoutSec 180 -SkipPauseGate
```

`completion_claim_allowed=false` — 有烟测绿 ≠ 333/P0 闭合。
