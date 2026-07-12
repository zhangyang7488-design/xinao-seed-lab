# Temporal adapter (T9 / M-TMPL)

Blueprint shims re-export `src/xinao_coordination/temporal/*`.

- **Promoted tasks only** — never chat/discuss → Temporal
- **Explicit start** — `temporal-start-promoted`; `auto_start_on_promote=false`
- **Mock default** — `XINAO_TEMPORAL_ENABLED=1` + `XINAO_TEMPORAL_MOCK=1` for canary/CI
- **Live** — requires `XINAO_TEMPORAL_LIVE=1`, real client start (Admin-owned), and this worker

## Real worker (G1)

| Item | Value |
|------|--------|
| Address | `XINAO_TEMPORAL_ADDRESS` default `127.0.0.1:7233` |
| Namespace | `XINAO_TEMPORAL_NAMESPACE` default `default` |
| Task queue | `XINAO_TEMPORAL_TASK_QUEUE` default `xinao-dualbrain-promoted-v1` |
| Workflow type | `XinaoPromotedTaskWorkflowV1` |
| Activity types | 四个 `xinao.promoted.*` + `xinao.grok.execute_acpx_lane` / `materialize_acpx_fanin` |
| Query names | `get_status` / `get_progress` (not bare `status`) |
| Name SSOT | `adapters/temporal/names.py` |
| One-click E2E | `adapters/temporal/selftest_e2e.py` (connect→start→wait COMPLETED→query) |
| Entry | `adapters/temporal/run_worker.py` (alias: `worker_main.py`) |
| SDK pin | `adapters/temporal/requirements-temporal.txt` (`temporalio==1.30.0`) |
| Deployment | `xinao-dualbrain-promoted` / manifest `worker_deployment.v1.json` |
| Versioning behavior | `PINNED` |
| Retained replay | `replay_promoted_histories.py` |

### One-click selftest (no live server; time-skipping)

```bat
E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\.venv\Scripts\python.exe adapters\temporal\selftest_e2e.py
```

Live (requires Temporal + worker poller):

```bat
set XINAO_TEMPORAL_SELFTEST_LIVE=1
E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\.venv\Scripts\python.exe adapters\temporal\selftest_e2e.py
```

### Install SDK into project venv (no pyproject change)

```bat
E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\.venv\Scripts\python.exe -m pip install -r adapters\temporal\requirements-temporal.txt
```

### Start worker (foreground)

```bat
set XINAO_TEMPORAL_ADDRESS=127.0.0.1:7233
set XINAO_TEMPORAL_NAMESPACE=default
set XINAO_TEMPORAL_TASK_QUEUE=xinao-dualbrain-promoted-v1
set XINAO_TEMPORAL_WORKER_LOG=D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712\saturation\G1_temporal_worker\worker_start.log
E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\.venv\Scripts\python.exe E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\adapters\temporal\run_worker.py
```

### Start worker (hidden / no window, canonical versioned route)

```powershell
$Root='E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination'
& "$Root\adapters\temporal\start_worker_hidden.ps1" `
  -PythonExe 'D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\generations\worker-versioning-sdk-1.30.0-ca1106b\Scripts\python.exe' `
  -DeploymentManifest "$Root\adapters\temporal\worker_deployment.v1.json" `
  -EvidenceDir 'D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\promoted_worker' `
  -PassThru
```

### Prove poller

```bat
temporal task-queue describe --task-queue xinao-dualbrain-promoted-v1 --address 127.0.0.1:7233 --namespace default
```

Expect non-empty **Pollers** rows (workflow + activity). Mock mode must not fake this.

Also require the official deployment route:

```bat
temporal worker deployment describe --name xinao-dualbrain-promoted --address 127.0.0.1:7233
```

Current build must equal `worker_deployment.v1.json`; ramping must normally be empty.

### Export and replay every retained promoted history

```bat
D:\XINAO_RESEARCH_RUNTIME\tools\xinao-coordination\generations\worker-versioning-sdk-1.30.0-ca1106b\Scripts\python.exe adapters\temporal\replay_promoted_histories.py --output-dir D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination\promoted_replay
```

The command writes canonical history JSON plus `replay_report.json` and exits non-zero on
any nondeterminism. Run it before routing a new build.

## G8 mature bind (official Worker / RetryPolicy map)

Code-landed patterns are inventoried with **path + line anchors** (not C08 live PASS):

| Artifact | Path |
|----------|------|
| Primary map | `D:\XINAO_RESEARCH_RUNTIME\evidence\...\saturation\G8_mature_bind\MATURE_BIND_MAP.json` |
| Selftest entry | `adapters/temporal/selftest_worker.py` (WorkflowEnvironment time-skipping; no live server) |
| Worker bind | `adapters/temporal/worker_runtime.py` → `Client.connect` + `Worker(...)` + `worker.run()` |
| RetryPolicy | `src/.../temporal/activities.py` `DEFAULT_ACTIVITY_RETRY` + `workflow.execute_activity(..., retry_policy=...)` |

### Selftest (G8 evidence)

```bat
E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\.venv\Scripts\python.exe E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\adapters\temporal\selftest_worker.py
```

Writes `G8_temporal_worker_selftest_latest.json` under `G8_mature_bind/`.

**Scope boundary:** G8/G26 does **not** edit `src/xinao_coordination/temporal/client.py` (Admin live start).
