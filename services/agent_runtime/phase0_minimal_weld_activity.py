"""SUNSET facade — delegates to integrated_bus_runner (LangGraphPlugin default path)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_runner import run_integrated_bus

SCHEMA_VERSION = "xinao.codex_s.phase0_minimal_weld.v1"
SENTINEL = "SENTINEL:XINAO_PHASE0_MINIMAL_WELD_READY"
REPLACES_HANDROLL = True


def run_phase0_minimal_weld(
    input_path: Path | None = None,
    *,
    runtime_root: Path | None = None,
    repo_root: Path | None = None,
    prefer_e2b: bool = False,
    prefer_docker: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    del prefer_e2b, prefer_docker, write
    payload = run_integrated_bus(
        input_path,
        runtime_root=runtime_root or Path(r"D:\XINAO_RESEARCH_RUNTIME"),
        repo_root=repo_root or Path(r"E:\XINAO_RESEARCH_WORKSPACES\S"),
        temporal=False,
        mainline_default=True,
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["sentinel"] = SENTINEL
    payload["phase"] = "0"
    payload["thin_glue_phase0"] = True
    payload["replaces_handroll"] = REPLACES_HANDROLL
    payload["delegates_to"] = "services.agent_runtime.integrated_bus_runner"
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if result.get("commit_hash"):
        payload["commit_hash"] = result["commit_hash"]
    if result.get("proof_path"):
        payload["proof_path"] = result["proof_path"]
    rt = runtime_root or Path(r"D:\XINAO_RESEARCH_RUNTIME")
    evidence = payload.get("evidence_path") or str(rt / "readback" / f"integrated_bus_{payload.get('run_id', 'latest')}.json")
    if Path(evidence).is_file():
        phase0_alias = Path(rt) / "readback" / f"phase0_{payload.get('run_id', 'latest')}.json"
        phase0_alias.parent.mkdir(parents=True, exist_ok=True)
        phase0_alias.write_text(Path(evidence).read_text(encoding="utf-8"), encoding="utf-8")
        payload["phase0_readback_alias"] = str(phase0_alias)
    return payload


try:
    from temporalio import activity as _temporal_activity
except Exception:

    class _MissingActivity:
        @staticmethod
        def defn(fn=None, *, name: str | None = None):
            def wrap(f):
                return f

            return wrap if fn is None else wrap(fn)

    _temporal_activity = _MissingActivity()  # type: ignore[misc, assignment]


@_temporal_activity.defn(name="phase0_minimal_intake_and_execute")
async def phase0_minimal_intake_and_execute(test_input_path: str) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_runner import run_integrated_bus_temporal

    return await run_integrated_bus_temporal(
        Path(test_input_path),
        mainline_default=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase0 minimal weld → integrated bus")
    parser.add_argument("--input", default="")
    parser.add_argument("--temporal", action="store_true")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    try:
        if args.temporal:
            import asyncio
            from services.agent_runtime.integrated_bus_runner import resolve_input, run_integrated_bus_temporal

            trigger = resolve_input(input_path)
            payload = asyncio.run(run_integrated_bus_temporal(trigger, mainline_default=True))
        else:
            payload = run_phase0_minimal_weld(input_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())