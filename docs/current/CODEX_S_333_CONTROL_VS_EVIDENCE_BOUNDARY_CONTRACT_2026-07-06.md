# 333 control vs evidence boundary contract

SENTINEL:XINAO_CODEX_S_333_CONTROL_VS_EVIDENCE_BOUNDARY_READY

`control_vs_evidence_boundary_contract.v1` is the S-scoped contract that keeps
control authority separate from evidence/read models.

Callable entrypoint:

```powershell
python -m xinao_seedlab.cli.__main__ 333-control-vs-evidence-boundary-contract
```

Runtime evidence:

```text
D:\XINAO_RESEARCH_RUNTIME\state\codex_333_control_vs_evidence_boundary_contract\latest.json
D:\XINAO_RESEARCH_RUNTIME\readback\zh\codex_333_control_vs_evidence_boundary_contract.md
```

Boundary:

- Control authority is Temporal/workflow event history, workflow state, and
  accepted commands.
- `latest.json`, readback, verifier PASS, ToolRegistry, capability manifests,
  ClaimCards, and docs are evidence/read models only.
- Evidence/read models cannot trigger completion, dispatch, or
  `runtime_enforced` promotion by themselves.
- Promotion requires terminal provider/tool evidence, staging, fan-in, and
  ArtifactAcceptanceQueue decision before any read-model projection is trusted.

Default-mainline binding:

- The S ToolRegistry provider id is
  `codex_s.333_control_vs_evidence_boundary_contract`.
- The stateful continuity router accepts
  `P0.control_vs_evidence_boundary_contract` and then advances to
  `lane_lifecycle_metric_contract.v1`.
- This is not a completion gate and not an execution controller.
