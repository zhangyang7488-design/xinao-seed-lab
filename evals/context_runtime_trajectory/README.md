# Context runtime trajectory harness

This suite keeps deterministic context-runtime contracts separate from live
Codex behavior evidence.

## Contract mode

The canonical behavior runner invokes:

```powershell
uv run python evals/context_runtime_trajectory/run_context_runtime_trajectory.py `
  --mode contract `
  --operation-root D:\path\to\operation-scoped-root `
  --output D:\path\to\context-runtime-contract.receipt.json
```

The operation root must be new or empty. Each case owns a separate store. The
fresh ablation additionally owns different `enabled-store` and `empty-store`
roots. Contract mode never uses the production Context Fabric, production
Codex homes, a model, network access, or tools.

The four deterministic cases cover:

- S-to-B source-linked fresh materialization versus an empty-store ablation;
- secret-withholding and structural non-authority for discussion and Stop;
- A/C clean-room denial with byte-identical S/B store readback;
- corrupt-store fail-open behavior preserving the L0 current-words layer.

`runtime_claim_allowed` is always `false`. Contract success does **not** prove
that a model interpreted the history correctly, avoided tools, crossed an
actual app-server compact/resume boundary, or reduced longitudinal user burden.

## Live mode

The reserved interface is:

```powershell
uv run python evals/context_runtime_trajectory/run_context_runtime_trajectory.py `
  --mode live `
  --operation-root D:\path\to\operation-scoped-root `
  --output D:\path\to\context-runtime-live.receipt.json `
  --codex-path D:\path\to\codex.exe `
  --s-codex-home C:\path\to\s-home `
  --b-codex-home C:\path\to\b-home `
  --working-dir E:\XINAO_RESEARCH_WORKSPACES\S `
  --hook-sink D:\path\to\hook-sink-contract.json
```

Live mode currently returns a typed `ineligible` receipt and exit code `3`.
It will only become claim-eligible when one implementation jointly observes:

1. real `initialize`, `thread/start|resume`, `turn/start`, and
   `thread/compact/start` app-server events;
2. real installed-hook discovery/trust and the corresponding hook-sink order;
3. isolated S/B homes and stores; and
4. raw model/tool events used by the behavioral assertions.

Direct JSON-stdio calls to the hook adapter cannot satisfy that evidence bar.

Exit codes are `0` pass, `1` contract assertion failure, `2` usage or
infrastructure failure, and `3` live evidence ineligible.
