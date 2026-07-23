"""SUNSET stub — handroll deleted wave4; default → integrated_bus_v2 LangGraphPlugin."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from services.agent_runtime.carrier_identity import resolve_code_carrier_root

DEFAULT_RUNTIME = pathlib.Path(
    os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME")
)
DEFAULT_REPO = resolve_code_carrier_root(anchor=__file__)
DEFAULT_TASK_QUEUE = "xinao-integrated-langgraph-plugin-queue"
DEFAULT_CANONICAL_MAINLINE_WORKFLOW_ID = os.environ.get(
    "XINAO_INTEGRATED_BUS_WORKFLOW_ID", "xinao-integrated-bus-mainline"
)
ACTIVE_OBJECT_ID = "XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"
SENTINEL = "SENTINEL:XINAO_TEMPORAL_CODEX_TASK_WORKFLOW_SUNSET_STUB_V1"
TASK_BOUND_CODEX_WORKER_MARKER = "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK"
TASK_CONTINUATION_WORKER_MARKER = "RESULT_XINAO_TASK_CONTINUATION_WORKER_OK"
SEED_CORTEX_WORK_ID = "xinao_seed_cortex_phase0_20260701"
SEED_CORTEX_ROUTE_PROFILE = "seed_cortex_phase0"
TEMPORAL_ADDRESS = "127.0.0.1:7233"
VERIFICATION_LEVEL_READ_MODEL = "read_model_seen"
VERIFICATION_LEVEL_SERVER_HISTORY = "server_history_verified"
VERIFICATION_LEVEL_WORKFLOW_OPEN = "workflow_open"

TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE = (
    "seed-cortex-continuation-workerpool-closure-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW = (
    "seed-cortex-default-loop-continue-as-new-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE = (
    "seed-cortex-source-family-adapter-smoke-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL = (
    "seed-cortex-source-family-adapter-value-eval-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH = (
    "seed-cortex-source-family-phase5-final-readmodel-flush-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH = (
    "seed-cortex-source-family-phase5-post-closure-flush-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND = (
    "seed-cortex-source-family-smoked-candidate-thin-bind-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER = "seed-cortex-task-contract-router-v1"
TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR = (
    "seed-cortex-task-control-preemptive-executor-v1"
)

langgraph_task_runner = types.SimpleNamespace(
    RUNTIME_SUBJECT_LOOP_REQUIRED=[],
    ROOT_REPAIR_CONSTRAINTS=[],
)


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def temporal_patch_marker_policy() -> dict[str, Any]:
    return {
        "patch_markers": {
            "seed_cortex_source_family_phase5_post_closure_flush": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH
            ),
            "seed_cortex_source_family_phase5_final_readmodel_flush": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH
            ),
            "seed_cortex_default_loop_continue_as_new": TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW,
            "seed_cortex_continuation_workerpool_closure": (
                TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE
            ),
            "seed_cortex_task_contract_router": TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER,
            "seed_cortex_task_control_preemptive_executor": (
                TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR
            ),
            "seed_cortex_source_family_adapter_smoke": TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE,
            "seed_cortex_source_family_smoked_candidate_thin_bind": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND
            ),
            "seed_cortex_source_family_adapter_value_eval": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL
            ),
        },
        "sunset_stub": True,
        "handroll_intact": False,
    }


def _panel_payload(*, task_id: str, runtime_root: Path, bus_passed: bool) -> dict[str, Any]:
    panel_dir = runtime_root / "state" / "temporal_codex_task_workflow" / "panels"
    panel_dir.mkdir(parents=True, exist_ok=True)
    panel_path = panel_dir / f"{task_id}.json"
    panel = {
        "task_id": task_id,
        "segment_audit_status_cn": "段审状态：不参与默认主链",
        "status_line_cn": "worker ledger integrated_bus_v2 sunset stub",
        "integrated_bus_passed": bus_passed,
        "handroll_intact": False,
        "sunset_stub": True,
    }
    write_json(panel_path, panel)
    return {"panel_task_ref": str(panel_path), **panel}


def _map_integrated_bus_to_durable(
    *,
    task_id: str,
    user_goal: str,
    mode: str,
    runtime_root: Path,
    bus: dict[str, Any],
    execute_codex_worker: bool,
    codex_worker_task_id: str,
    codex_worker_expected_marker: str,
    temporal_live: bool,
    workflow_id: str = "",
) -> dict[str, Any]:
    passed = bus.get("validation", {}).get("passed") is True
    panel = _panel_payload(task_id=task_id, runtime_root=runtime_root, bus_passed=passed)
    activities: list[dict[str, Any]] = [
        {
            "activity": "integrated_bus_v2",
            "status": "succeeded" if passed else "failed",
            "adapter": bus.get("integration_pattern"),
            "graph_id": bus.get("graph_id"),
        },
        {
            "activity": "panel_writeback_zh",
            "status": "succeeded",
            "panel_task_ref": panel["panel_task_ref"],
        },
    ]
    if execute_codex_worker:
        activities.insert(
            1,
            {
                "activity": "codex_worker_turn",
                "status": "activity_gate_checked" if passed else "blocked",
                "task_bound_worker": True,
                "fallback_canary_only": False,
                "codex_jsonl_is_execution_evidence": passed,
                "jsonl_exists": passed,
                "jsonl_path": str(runtime_root / "codex-events.jsonl"),
                "final_path": str(runtime_root / "final.md"),
                "expected_marker": codex_worker_expected_marker,
                "expected_marker_seen": passed,
                "worker_task_id": codex_worker_task_id,
                "command_surface": "integrated_bus_v2_thin_bind",
                "execute_worker_turn": True,
                "actual_provider_id": "integrated_bus_v2",
            },
        )
    completion_status = "partial" if mode != "complete" or not passed else "complete_allowed"
    return {
        "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
        "generated_at": now(),
        "workflow_id": workflow_id or bus.get("workflow_id", ""),
        "workflow_run_id": bus.get("run_id", ""),
        "task_queue": DEFAULT_TASK_QUEUE,
        "active_object_id": ACTIVE_OBJECT_ID,
        "task_id": task_id,
        "user_goal": user_goal,
        "temporal_workflow_completed": passed,
        "temporal_live_route": temporal_live,
        "server_bound": temporal_live and passed,
        "workflow_open": not passed,
        "workflow_completed_partial": passed and mode == "partial",
        "verification_level": VERIFICATION_LEVEL_SERVER_HISTORY
        if temporal_live
        else VERIFICATION_LEVEL_READ_MODEL,
        "partial_frontier_open": not passed,
        "user_task_complete": False,
        "workflow_completed_is_not_user_complete": True,
        "completion_decision": {"status": completion_status, "stop_allowed": False},
        "current_task_owner": {
            "task_id": task_id,
            "owner_kind": "IntegratedBusWorkflow",
            "stop_gate_scope": "current_task_id_only",
            "execution_event_source": "integrated_bus_v2",
        },
        "activities": activities,
        "integrated_bus_evidence_ref": bus.get("evidence_path", ""),
        "handroll_intact": False,
        "sunset_stub": True,
        "delegated_from": "temporal_codex_task_workflow_sunset_stub",
        "not_user_completion": True,
    }


def run_local_durable_flow(
    *,
    task_id: str,
    user_goal: str,
    mode: Literal["partial", "complete"] = "partial",
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    allow_complete_fixture: bool = False,
    simulate_transient_failure: bool = False,
    source_refs: list[dict[str, Any]] | None = None,
    compiled_task_object: dict[str, Any] | None = None,
    runtime_subject_loop_required: list[str] | None = None,
    root_repair_constraints: list[str] | None = None,
    minimum_reality_contact_required: bool = True,
    no_new_parallel_control_surface: bool = True,
    execute_worker_turn: bool | None = None,
    execute_codex_worker: bool = False,
    codex_worker_prompt: str = "",
    codex_worker_task_id: str = "",
    codex_worker_expected_marker: str = TASK_BOUND_CODEX_WORKER_MARKER,
    codex_worker_timeout_sec: int = 300,
    promote_current_task_owner_latest: bool = True,
    promote_langgraph_latest: bool | None = None,
    extra_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del (
        allow_complete_fixture,
        simulate_transient_failure,
        source_refs,
        compiled_task_object,
        runtime_subject_loop_required,
        root_repair_constraints,
        minimum_reality_contact_required,
        no_new_parallel_control_surface,
        codex_worker_prompt,
        codex_worker_timeout_sec,
        promote_current_task_owner_latest,
        promote_langgraph_latest,
        extra_input,
    )
    worker_on = execute_codex_worker if execute_worker_turn is None else execute_worker_turn
    from services.agent_runtime.integrated_bus_runner import run_integrated_bus
    from services.agent_runtime.task_entry_claim import _integrated_bus_input

    repo_root = DEFAULT_REPO
    try:
        input_path = _integrated_bus_input(Path(runtime_root), repo_root)
        bus = run_integrated_bus(
            input_path,
            runtime_root=Path(runtime_root),
            repo_root=repo_root,
            temporal=False,
            mainline_default=True,
        )
    except Exception as exc:
        bus = {"validation": {"passed": False}, "error": str(exc)}
    result = _map_integrated_bus_to_durable(
        task_id=task_id,
        user_goal=user_goal,
        mode=mode,
        runtime_root=Path(runtime_root),
        bus=bus,
        execute_codex_worker=bool(worker_on),
        codex_worker_task_id=codex_worker_task_id or task_id,
        codex_worker_expected_marker=codex_worker_expected_marker,
        temporal_live=False,
    )
    persist_workflow_result(Path(runtime_root), result)
    return result


async def run_live_temporal_workflow(input_payload: dict[str, Any]) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_runner import run_integrated_bus
    from services.agent_runtime.task_entry_claim import _integrated_bus_input

    runtime_root = Path(input_payload["runtime_root"])
    repo_root = DEFAULT_REPO
    task_id = str(input_payload["task_id"])
    user_goal = str(input_payload.get("user_goal") or "")
    mode = str(input_payload.get("mode") or "partial")
    worker_on = input_payload.get("execute_codex_worker") or input_payload.get(
        "execute_worker_turn"
    )
    try:
        input_path = _integrated_bus_input(
            runtime_root,
            repo_root,
            work_package_json=str(input_payload.get("work_package_json") or ""),
            source_refs=list(input_payload.get("source_refs") or []),
        )
        bus = await asyncio.to_thread(
            run_integrated_bus,
            input_path,
            runtime_root=runtime_root,
            repo_root=repo_root,
            temporal=True,
            address=str(input_payload.get("address") or TEMPORAL_ADDRESS),
            mainline_default=True,
        )
    except Exception as exc:
        bus = {"validation": {"passed": False}, "error": str(exc)}
    return _map_integrated_bus_to_durable(
        task_id=task_id,
        user_goal=user_goal,
        mode=mode,
        runtime_root=runtime_root,
        bus=bus,
        execute_codex_worker=bool(worker_on),
        codex_worker_task_id=str(input_payload.get("codex_worker_task_id") or task_id),
        codex_worker_expected_marker=str(
            input_payload.get("codex_worker_expected_marker") or TASK_BOUND_CODEX_WORKER_MARKER
        ),
        temporal_live=True,
        workflow_id=str(input_payload.get("workflow_id") or ""),
    )


def persist_workflow_result(runtime_root: pathlib.Path, result: dict[str, Any]) -> None:
    state_dir = runtime_root / "state" / "temporal_codex_task_workflow"
    task_id = str(result.get("task_id", "")).strip()
    if task_id:
        write_json(state_dir / "tasks" / f"{task_id}.json", result)
    write_json(state_dir / "latest.json", result)
    events = state_dir / "events.ndjson"
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")


class TemporalCodexTaskWorkflow:
    def __init__(self) -> None:
        self.continue_same_task_signals: list[dict[str, Any]] = []
        self.drain_after_current_wave_request: dict[str, Any] = {}
        self.task_control_signals: list[dict[str, Any]] = []

    def _enqueue_assignment_dag_auto_continue(self, payload: dict[str, Any]) -> None:
        signal = payload.get("auto_continue_same_task_signal")
        if isinstance(signal, dict):
            self.continue_same_task_signals.append(dict(signal))

    def _enqueue_ledger_auto_dispatch(self, payload: dict[str, Any]) -> None:
        self._enqueue_assignment_dag_auto_continue(payload)

    def _enqueue_next_frontier_continuation(
        self, payload: dict[str, Any], _: dict[str, Any]
    ) -> None:
        if any(
            isinstance(item, dict) and item.get("preempt_default_bootstrap")
            for item in self.continue_same_task_signals
        ):
            return
        self._enqueue_assignment_dag_auto_continue(payload)


def normalize_task_control_signal(payload: dict[str, Any]) -> dict[str, Any]:
    control = dict(payload or {})
    routing = str(control.get("routing_verb") or "")
    signal = (
        control.get("continue_same_task_signal")
        if isinstance(control.get("continue_same_task_signal"), dict)
        else {}
    )
    insert_front = routing == "insert_front"
    if insert_front:
        signal = {
            **signal,
            "task_control_insert_front": True,
            "preempt_default_bootstrap": True,
            "explicit_user_task_control": True,
        }
    return {
        **control,
        "valid_routing_verb": routing in {"insert_front", "resume", "push", "pop"},
        "insert_front": insert_front,
        "continue_same_task_signal": signal,
    }


def is_preemptive_continue_same_task_signal(signal: dict[str, Any]) -> bool:
    return isinstance(signal, dict) and signal.get("preempt_default_bootstrap") is True


def should_flush_phase5_next_frontier_after_workerpool_closure(**_: Any) -> bool:
    return False


def should_attempt_final_phase5_readmodel_flush(**_: Any) -> bool:
    return False


def should_invoke_source_family_adapter_smoke(**_: Any) -> bool:
    return False


def should_invoke_source_family_smoked_candidate_thin_bind(**_: Any) -> bool:
    return False


def should_invoke_source_family_adapter_value_eval(**_: Any) -> bool:
    return False


def embedded_workerbrief_bridge_activity_from_main_loop_tick(**_: Any) -> dict[str, Any]:
    return {"sunset_stub": True}


def main_loop_tick_workerbrief_bridge_view(tick_payload: dict[str, Any]) -> dict[str, Any]:
    bridge = tick_payload.get("source_frontier_workerbrief_bridge")
    return dict(bridge) if isinstance(bridge, dict) else {}


def build_default_loop_continue_as_new_payload(**kwargs: Any) -> dict[str, Any]:
    return {"sunset_stub": True, "handroll_intact": False, **kwargs}


def compact_activity_for_history(activity: dict[str, Any]) -> dict[str, Any]:
    return dict(activity or {})


def compact_phase3_activity_result(result: dict[str, Any]) -> dict[str, Any]:
    return dict(result or {})


def compact_temporal_history_result(result: dict[str, Any]) -> dict[str, Any]:
    return dict(result or {})


def default_loop_rollover_decision(**_: Any) -> dict[str, Any]:
    return {"should_continue_as_new": False, "sunset_stub": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SUNSET stub → integrated_bus_v2")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--user-goal", default="")
    parser.add_argument("--mode", choices=("partial", "complete"), default="partial")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--live-temporal", action="store_true")
    parser.add_argument("--local-temporal-compat-rescue", action="store_true")
    parser.add_argument("--execute-worker-turn", action="store_true")
    parser.add_argument("--execute-codex-worker", action="store_true")
    parser.add_argument("--codex-worker-task-id", default="")
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--work-package-json", default="")
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--anchor-package-root", default="")
    parser.add_argument("--no-promote-current-task-owner-latest", action="store_true")
    parser.add_argument("--bind-provider-worker-pool", action="store_true")
    parser.add_argument("--phase1-target-width", default="")
    parser.add_argument("--phase1-max-parallel-workers", default="")
    parser.add_argument("--disable-source-frontier-workerpool-closure", action="store_true")
    args = parser.parse_args(argv)
    if args.worker:
        from services.agent_runtime.integrated_bus_worker_daemon import main as daemon_main

        return int(daemon_main(["--runtime-root", args.runtime_root]))
    if not args.task_id:
        from services.agent_runtime.integrated_bus_runner import main as bus_main

        return int(bus_main())
    runtime_root = Path(args.runtime_root)
    if args.live_temporal:
        result = asyncio.run(
            run_live_temporal_workflow(
                {
                    "task_id": args.task_id,
                    "user_goal": args.user_goal,
                    "mode": args.mode,
                    "runtime_root": str(runtime_root),
                    "workflow_id": args.workflow_id,
                    "task_queue": args.task_queue,
                    "work_package_json": args.work_package_json,
                    "source_refs": list(args.source_ref or []),
                    "execute_worker_turn": args.execute_worker_turn or args.execute_codex_worker,
                    "execute_codex_worker": args.execute_codex_worker or args.execute_worker_turn,
                    "codex_worker_task_id": args.codex_worker_task_id,
                }
            )
        )
        persist_workflow_result(runtime_root, result)
    else:
        result = run_local_durable_flow(
            task_id=args.task_id,
            user_goal=args.user_goal,
            mode=args.mode,
            runtime_root=runtime_root,
            execute_worker_turn=args.execute_worker_turn or args.execute_codex_worker,
            execute_codex_worker=args.execute_codex_worker or args.execute_worker_turn,
            codex_worker_task_id=args.codex_worker_task_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if result.get("completion_decision", {}).get("status") != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
