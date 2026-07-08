"""SUNSET stub — handroll deleted wave3; default → thin_glue_l9_worker_pool."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1"
SENTINEL = "SENTINEL:XINAO_MODULAR_DYNAMIC_WORKER_POOL_PHASE1_SUNSET_STUB_V1"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
TASK_ID = "modular_dynamic_worker_pool_phase1_20260704"
ASSIGNMENT_DAG_NODE_ID = "parallel_draft_batch_bind"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))


def _thin_glue_worker_pool_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_WORKER_POOL", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def run_wave(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "modular-dynamic-worker-pool-phase1-wave-001",
    target_width: int = 0,
    dynamic_width_decision: dict[str, Any] | None = None,
    write: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    del dynamic_width_decision, kwargs
    if not _thin_glue_worker_pool_enabled():
        return {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "status": "modular_dynamic_worker_pool_phase1_sunset",
            "handroll_intact": False,
            "named_blocker": "HANDROLL_DELETED_WAVE3_USE_THIN_GLUE_WORKER_POOL",
            "validation": {"passed": False},
        }
    from services.agent_runtime.thin_glue_l9_worker_pool import run_thin_glue_worker_pool_wave

    width = int(target_width or 2)
    thin_payload = run_thin_glue_worker_pool_wave(
        runtime_root=runtime_root,
        repo_root=repo_root,
        wave_id=wave_id,
        target_width=width,
        use_temporal=False,
        write=write,
    )
    thin_payload["delegated_from"] = "modular_dynamic_worker_pool_phase1.run_wave"
    thin_payload["hand_rolled_run_wave_bypassed"] = True
    thin_payload["sunset_stub"] = True
    return thin_payload


def run_enforced_while(**kwargs: Any) -> dict[str, Any]:
    return run_wave(**kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="modular-dynamic-worker-pool-phase1-wave-001")
    parser.add_argument("--target-width", type=int, default=0)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--enforced", action="store_true")
    parser.add_argument("--while-waves", type=int, default=1)
    args = parser.parse_args(argv)
    payload = run_wave(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        target_width=args.target_width,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())