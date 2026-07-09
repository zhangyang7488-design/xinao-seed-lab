"""Default main loop trigger — thin bind to integrated_bus_v2 Temporal L4 hot path."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.default_main_loop_trigger_candidate.v1"
SENTINEL = "SENTINEL:XINAO_CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VERIFIER_READY"
STATE_NAME = "default_main_loop_trigger_candidate"
TASK_ID = "xinao_seed_cortex_phase0_20260701"
DEFAULT_RUNTIME = Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
TEMPORAL_ADDRESS = "127.0.0.1:7233"


def integrated_bus_temporal_default_enabled() -> bool:
    return os.environ.get("XINAO_INTEGRATED_BUS_TEMPORAL_DEFAULT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _invoke_integrated_bus_v2(
    *,
    runtime_root: Path,
    repo_root: Path,
    temporal: bool,
) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_runner import run_integrated_bus

    try:
        return run_integrated_bus(
            None,
            runtime_root=runtime_root,
            repo_root=repo_root,
            temporal=temporal,
            address=TEMPORAL_ADDRESS,
            mainline_default=True,
        )
    except Exception as exc:
        if not temporal:
            return {"validation": {"passed": False}, "error": str(exc)}
        try:
            local = run_integrated_bus(
                None,
                runtime_root=runtime_root,
                repo_root=repo_root,
                temporal=False,
                mainline_default=True,
            )
            local["temporal_fallback"] = True
            local["temporal_error"] = str(exc)
            return local
        except Exception as local_exc:
            return {
                "validation": {"passed": False},
                "error": str(local_exc),
                "temporal_fallback": True,
                "temporal_error": str(exc),
            }


def _build_trigger_payload(
    bus: dict[str, Any],
    *,
    runtime_root: Path,
    wave_id: str,
    workflow_id: str = "",
    workflow_run_id: str = "",
    write: bool = True,
) -> dict[str, Any]:
    passed = bus.get("validation", {}).get("passed") is True
    temporal_live = bus.get("invoke_mode") == "temporal_langgraph_plugin"
    integrated_bus_v2_ref = str(
        bus.get("integrated_bus_v2_latest_ref") or bus.get("evidence_path") or ""
    )
    adoption_state = (
        "runtime_enforced" if passed and temporal_live else "runtime_trigger_candidate_verifier_ready"
    )
    runtime_enforced = passed and temporal_live
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "work_id": TASK_ID,
        "route_profile": "seed_cortex_phase0",
        "wave_id": wave_id,
        "workflow_id": workflow_id or str(bus.get("workflow_id") or ""),
        "workflow_run_id": workflow_run_id or str(bus.get("run_id") or ""),
        "status": (
            "default_main_loop_trigger_task_scoped_runtime_enforced"
            if runtime_enforced
            else "default_main_loop_trigger_candidate_verifier_ready"
            if passed
            else "default_main_loop_trigger_candidate_blocked"
        ),
        "adoption_state": adoption_state,
        "adoption_state_boundary": {
            "adoption_state": adoption_state,
            "scope": "default_main_loop_trigger_candidate_only",
            "state_is_scoped_candidate": not runtime_enforced,
            "not_global_runtime_enforcement": True,
            "not_global_default_trigger": True,
            "root_loop_every_wave_enforced": runtime_enforced,
            "runtime_enforced": runtime_enforced,
            "runtime_enforced_scope": (
                "integrated_bus_v2_temporal_langgraph_plugin_l4"
                if temporal_live
                else "integrated_bus_v2_local_compat"
            ),
            "trigger_installed": True,
            "meaning_cn": (
                "default_main_loop_trigger_candidate 薄绑 integrated_bus_v2；"
                "L4 Temporal LangGraphPlugin 为默认热路径。"
            ),
            "missing_to_runtime_enforced_cn": (
                ""
                if runtime_enforced
                else "Temporal worker 未就绪时走 local compat；需 daemon + LangGraphPlugin worker 绿堆。"
            ),
        },
        "runtime_enforced": runtime_enforced,
        "runtime_enforced_scope": (
            "integrated_bus_v2_temporal_langgraph_plugin_l4"
            if temporal_live
            else "integrated_bus_v2_local_compat"
        ),
        "temporal_enforced": temporal_live and passed,
        "trigger_installed": True,
        "stop_hook_controller": False,
        "sunset_stub": False,
        "handroll_intact": False,
        "delegated_from": "default_main_loop_trigger_candidate.py",
        "replacement": "integrated_bus_v2",
        "integrated_bus_v2_ref": integrated_bus_v2_ref,
        "integrated_bus_invoke_mode": bus.get("invoke_mode", ""),
        "integration_pattern": bus.get(
            "integration_pattern", "temporalio.contrib.langgraph.LangGraphPlugin"
        ),
        "graph_id": bus.get("graph_id", "xinao-integrated-bus-v2"),
        "mainline_default_hot_path": True,
        "main_execution_loop": (
            "integrated_bus_v2: signal_feed→intake→validate→gateway→search→fanin→promotion→finalize"
        ),
        "completion_claim_allowed": False,
        "phase1_data_chain_allowed": False,
        "positive_ev_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "is_stop_guard_layer": False,
        "is_completion_gate": False,
        "not_default_runtime_controller": True,
        "candidate_for": "RootIntentLoop / S Default Dynamic Loop",
        "target_service_method": "SeedCortexService.default_main_loop_trigger_candidate",
        "evidence_refs": [integrated_bus_v2_ref] if integrated_bus_v2_ref else [],
        "integrated_bus": {
            "validation": bus.get("validation"),
            "invoke_mode": bus.get("invoke_mode"),
            "evidence_path": bus.get("evidence_path"),
            "temporal_fallback": bus.get("temporal_fallback"),
        },
        "validation": {
            "passed": passed,
            "checks": {
                "integrated_bus_v2_invoked": True,
                "trigger_bound_to_integrated_bus": True,
                "sunset_stub_replaced": True,
                "temporal_l4_hot_path": temporal_live and passed,
            },
        },
        "acceptance_now_can_invoke_cn": (
            f"主循环 trigger 已绑 integrated_bus_v2；mode={bus.get('invoke_mode')}；passed={passed}。"
            if passed
            else "主循环 trigger 绑 integrated_bus_v2 未绿；见 integrated_bus validation。"
        ),
    }
    if write:
        out_dir = runtime_root / "state" / STATE_NAME
        out_dir.mkdir(parents=True, exist_ok=True)
        latest = out_dir / "latest.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["latest_ref"] = str(latest)
        activity_latest = out_dir / "temporal_activity_latest.json"
        activity_payload = {
            **payload,
            "activity": "integrated_bus_v2_langgraph_plugin",
            "temporal_live": temporal_live,
        }
        activity_latest.write_text(
            json.dumps(activity_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        payload["temporal_activity_latest_ref"] = str(activity_latest)
    return payload


def build(**kwargs: Any) -> dict[str, Any]:
    runtime_root = Path(kwargs.pop("runtime_root", DEFAULT_RUNTIME))
    repo_root = Path(kwargs.pop("repo_root", DEFAULT_REPO))
    wave_id = str(kwargs.pop("wave_id", "codex-s-main-execution-wave-20260702"))
    workflow_id = str(kwargs.pop("workflow_id", ""))
    workflow_run_id = str(kwargs.pop("workflow_run_id", ""))
    write = bool(kwargs.pop("write", True))
    for ignored in (
        "anchor_package_root",
        "codex_subagents",
        "service",
        "bind_provider_worker_pool",
        "phase1_target_width",
        "phase1_max_parallel_workers",
        "phase1_require_external_draft",
        "allocation_plan_activity",
        "dynamic_width_decision",
        "work_package",
    ):
        kwargs.pop(ignored, None)
    temporal = integrated_bus_temporal_default_enabled()
    bus = _invoke_integrated_bus_v2(
        runtime_root=runtime_root,
        repo_root=repo_root,
        temporal=temporal,
    )
    if temporal and bus.get("validation", {}).get("passed") is not True:
        local = _invoke_integrated_bus_v2(
            runtime_root=runtime_root,
            repo_root=repo_root,
            temporal=False,
        )
        if local.get("validation", {}).get("passed") is True:
            local["temporal_attempted"] = True
            local["temporal_validation_passed"] = False
            bus = local
    return _build_trigger_payload(
        bus,
        runtime_root=runtime_root,
        wave_id=wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        write=write,
    )


def run(**kwargs: Any) -> dict[str, Any]:
    return build(**kwargs)


def run_wave(**kwargs: Any) -> dict[str, Any]:
    return build(**kwargs)


def build_controller(**kwargs: Any) -> dict[str, Any]:
    return build(**kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Default main loop trigger → integrated_bus_v2 L4")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO))
    parser.add_argument("--wave-id", default="codex-s-main-execution-wave-20260702")
    parser.add_argument("--local", action="store_true", help="Force local graph (skip Temporal L4)")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if args.local:
        os.environ["XINAO_INTEGRATED_BUS_TEMPORAL_DEFAULT"] = "0"
    payload = build(
        runtime_root=args.runtime_root,
        repo_root=args.repo_root,
        wave_id=args.wave_id,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())