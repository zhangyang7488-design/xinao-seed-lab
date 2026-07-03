# CodexActivator

Local-only direct Codex execution service for
`XINAO_HARDMODE_FULL_MACHINE_V1`.

```text
GET  http://127.0.0.1:19120/health
POST http://127.0.0.1:19120/codex/exec
GET  http://127.0.0.1:19120/codex/result/<task_id>
```

It invokes `codex exec` directly. It does not write to or consume
`action_queue`.

The hard guard is a narrow self-destruction denylist. It is not a writable-root
allowlist, and ordinary C/D/E execution remains allowed.
