# AMQ adapter (thin bind · T1)

Implementation lives in the importable package:

`src/xinao_coordination/amq/`

Thin re-exports in this directory match the construction-package blueprint paths.

| Blueprint file | Package module |
|----------------|----------------|
| `transport.py` | `xinao_coordination.amq.transport` |
| `mapping.py` | `xinao_coordination.amq.mapping` |
| `ingest.py` | `xinao_coordination.amq.ingest` |
| `outbox.py` | `xinao_coordination.amq.outbox` |

Kernel `CoordinationService` remains the sole authority for discussion/closure/task state.
AMQ is raw spool only. No daemon, no second control plane.

## Canary roots

- State DB: `D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\coordination.sqlite3`
- AMQ spool: `D:\XINAO_RESEARCH_RUNTIME\state\dual_brain_coordination_canary\amq`
- Config: `configs/modules/amq.toml` + canary `amq/meta/mailbox_canary.json`
- Binary (pinned): `D:\XINAO_RESEARCH_RUNTIME\tools\amq\bin\amq.exe` (0.42.0, MIT)

## Isolation behaviors

- Declared `payload_sha256` mismatch → quarantine (`amq/quarantine/new`), no kernel write
- Duplicate delivery same idempotency key + same payload → replayed, no second object
- Same key + different payload → reject + quarantine
- Path-like `message_id` rejected
- Outbox ACK stage is `ADAPTER_DELIVERED` only (`model_read=false`)

## Tests

```text
.venv\Scripts\python.exe -m pytest tests/test_amq_t1.py tests/test_t1t2t5_vertical_slice.py -v
```
