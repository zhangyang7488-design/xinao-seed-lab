# 333 legacy freeze manifest

SENTINEL:XINAO_CODEX_S_333_LEGACY_FREEZE_MANIFEST_READY

`legacy_freeze_manifest.v1` is the S-scoped read model for old A/B/C/CLEAN
surfaces. It freezes those surfaces as reference-only and names the S
replacement entrypoints:

- `RootIntentLoop / S Default Dynamic Loop` for the default mainline.
- `current_333_run_index` for current workflow readback.
- S ToolRegistry and CapabilityGateway for capability discovery.
- ArtifactAcceptanceQueue plus the current S completion boundary for
  acceptance.

Callable entrypoint:

```powershell
python -m xinao_seedlab.cli.__main__ 333-legacy-freeze-manifest
```

Runtime evidence:

```text
D:\XINAO_RESEARCH_RUNTIME\state\codex_333_legacy_freeze_manifest\latest.json
D:\XINAO_RESEARCH_RUNTIME\readback\zh\codex_333_legacy_freeze_manifest.md
```

Default-mainline binding:

- The S ToolRegistry provider id is `codex_s.333_legacy_freeze_manifest`.
- The default trigger no-stop ToolRegistry consumption requires that provider.
- The stateful continuity router accepts `P0.legacy_freeze_manifest` and then
  advances to `control_vs_evidence_boundary_contract.v1`.

Boundary:

This is not a completion gate, not an execution controller, and not a new
authority source. It only prevents old CLEAN/A/B/C/current_task_owner/completion
gate surfaces from silently becoming S hot-path authority.
