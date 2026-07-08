"""SUNSET stub — handroll deleted wave3; default → integrated_bus_v2; optional thin_glue L2."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.root_intent_loop_driver.v1"
SENTINEL = "SENTINEL:XINAO_ROOT_INTENT_LOOP_DRIVER_SUNSET_STUB_V1"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_ANCHOR_PACKAGE = Path(r"C:\Users\xx363\Desktop\新系统")


def _thin_glue_root_intent_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_ROOT_INTENT", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def build(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    anchor_package_root: str | Path = DEFAULT_ANCHOR_PACKAGE,
    wave_id: str = "codex-s-root-intent-loop-driver-wave-20260703",
    codex_subagents: list[str] | None = None,
    bind_provider_worker_pool: bool = False,
    phase1_target_width: int = 0,
    phase1_max_parallel_workers: int | None = 12,
    phase1_require_external_draft: bool = True,
    workflow_id: str = "",
    workflow_run_id: str = "",
    explicit_user_stop: bool = False,
    ordinary_discussion: bool = False,
    service: Any | None = None,
    p1_module: Any | None = None,
    p1_default_main_chain_enabled: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    del (
        anchor_package_root,
        codex_subagents,
        phase1_target_width,
        phase1_max_parallel_workers,
        phase1_require_external_draft,
        explicit_user_stop,
        ordinary_discussion,
        service,
        p1_module,
        p1_default_main_chain_enabled,
    )
    try:
        from services.agent_runtime.integrated_bus_facade_redirect import facade_hard_redirect_enabled
        from services.agent_runtime.integrated_bus_runner import run_integrated_bus

        if facade_hard_redirect_enabled() and not bind_provider_worker_pool:
            payload = run_integrated_bus(
                None,
                runtime_root=Path(runtime_root),
                repo_root=Path(repo_root),
                temporal=False,
                mainline_default=True,
            )
            payload["delegated_from"] = "root_intent_loop_driver.build"
            payload["hand_rolled_build_bypassed"] = True
            payload["handroll_intact"] = False
            payload["sunset_stub"] = True
            return payload
    except Exception:
        pass
    if _thin_glue_root_intent_enabled() and not bind_provider_worker_pool:
        from services.agent_runtime.thin_glue_l2_root_intent import run_thin_glue_root_intent_tick

        thin_payload = run_thin_glue_root_intent_tick(
            runtime_root=runtime_root,
            repo_root=repo_root,
            wave_id=wave_id,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            write=write,
        )
        thin_payload["delegated_from"] = "root_intent_loop_driver.build"
        thin_payload["hand_rolled_build_bypassed"] = True
        thin_payload["sunset_stub"] = True
        return thin_payload
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "root_intent_loop_driver_sunset",
        "handroll_intact": False,
        "named_blocker": "HANDROLL_DELETED_WAVE3_USE_INTEGRATED_BUS",
        "replacement": "integrated_bus_v2",
        "validation": {"passed": False},
    }


def build_cli_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version", SCHEMA_VERSION),
        "validation": payload.get("validation"),
        "run_id": payload.get("run_id"),
        "delegated_from": payload.get("delegated_from"),
        "handroll_intact": payload.get("handroll_intact", False),
        "sunset_stub": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--anchor-package-root", default=str(DEFAULT_ANCHOR_PACKAGE))
    parser.add_argument("--wave-id", default="codex-s-root-intent-loop-driver-wave-20260703")
    parser.add_argument("--codex-subagent", action="append", default=[])
    parser.add_argument("--bind-provider-worker-pool", action="store_true")
    parser.add_argument("--phase1-target-width", type=int, default=0)
    parser.add_argument("--phase1-max-parallel-workers", type=int, default=12)
    parser.add_argument("--allow-local-stub-acceptance", action="store_true")
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--explicit-user-stop", action="store_true")
    parser.add_argument("--ordinary-discussion", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--full-output", action="store_true")
    args = parser.parse_args(argv)
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        anchor_package_root=args.anchor_package_root,
        wave_id=args.wave_id,
        codex_subagents=args.codex_subagent,
        bind_provider_worker_pool=args.bind_provider_worker_pool,
        phase1_target_width=args.phase1_target_width,
        phase1_max_parallel_workers=args.phase1_max_parallel_workers,
        phase1_require_external_draft=not args.allow_local_stub_acceptance,
        workflow_id=args.workflow_id,
        workflow_run_id=args.workflow_run_id,
        explicit_user_stop=args.explicit_user_stop,
        ordinary_discussion=args.ordinary_discussion,
        write=not args.no_write,
    )
    output_payload = payload if args.full_output else build_cli_summary(payload)
    print(json.dumps(output_payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())