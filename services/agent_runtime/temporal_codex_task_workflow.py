import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

_REPO_ROOT = pathlib.Path(
    os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S")
)
if __package__ in (None, ""):
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_ROOT = _REPO_ROOT / "src"
if _SRC_ROOT.exists() and str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from services.agent_runtime import codex_default_task_runner
from services.agent_runtime import allocation_plan
from services.agent_runtime import codex_native_provider_scheduler_phase4
from services.agent_runtime import codex_s_main_execution_loop_tick
from services.agent_runtime import completion_claim_payload_builder as builder
from services.agent_runtime import default_main_loop_trigger_candidate
from services.agent_runtime import dp_sidecar_execution_port
from services.agent_runtime import durable_parallel_wave_packet
from services.agent_runtime import langgraph_task_runner
from services.agent_runtime import l1_l2_segment_gate
from services.agent_runtime import phase0_reusable_kernel
from services.agent_runtime import pre_pass_audit_loop
from services.agent_runtime import scheduler_invocation_packet
from services.agent_runtime import source_frontier_fanin_acceptance
from services.agent_runtime import source_frontier_workerbrief_bridge
from services.agent_runtime import source_frontier_workerpool_closure
from services.agent_runtime import source_family_mature_thin_bind_sunset
from services.agent_runtime import source_family_wave_scheduler
from services.agent_runtime import temporal_activity_no_window_dp_worker_pool_phase3
from services.agent_runtime import wave2_mainchain_hygiene
from services.agent_runtime import worker_dispatch_ledger


try:
    from temporalio import activity, workflow
    from temporalio.common import RetryPolicy
except Exception:
    class _MissingTemporalActivity:
        @staticmethod
        def defn(fn):
            return fn

    class _MissingTemporalWorkflow:
        @staticmethod
        def defn(cls):
            return cls

        @staticmethod
        def run(fn):
            return fn

        @staticmethod
        def signal(fn):
            return fn

        @staticmethod
        async def execute_activity(fn, *args, **kwargs):
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args)
            return fn(*args)

        @staticmethod
        async def wait_condition(fn, *args, **kwargs):
            return bool(fn())

        @staticmethod
        def continue_as_new(*args, **kwargs):
            return None

    class RetryPolicy:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    activity = _MissingTemporalActivity()
    workflow = _MissingTemporalWorkflow()


DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
ACTIVE_OBJECT_ID = "XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"
SENTINEL = "SENTINEL:XINAO_TEMPORAL_CODEX_TASK_WORKFLOW_PASS"
NON_RETRYABLE_ERROR_TYPES = (
    "XINAO_OBJECT_REPLACEMENT_DENIED",
    "XINAO_OPERATION_DEGRADATION_DENIED",
    "XINAO_POLICY_DENY",
    "XINAO_COMPLETION_CLAIM_REJECTED_BY_POLICY",
)
TRANSIENT_ERROR_TYPES = (
    "XINAO_TRANSIENT_TOOL_ERROR",
    "XINAO_TRANSIENT_NETWORK_ERROR",
    "XINAO_TEMPORAL_ACTIVITY_TIMEOUT",
)
CODEX_ACTIVATOR_URL = os.environ.get("CODEX_ACTIVATOR_URL", "http://127.0.0.1:19121")
TASK_BOUND_CODEX_WORKER_MARKER = "RESULT_XINAO_TASK_BOUND_CODEX_WORKER_OK"
TASK_CONTINUATION_WORKER_MARKER = "RESULT_XINAO_TASK_CONTINUATION_WORKER_OK"
TEMPORAL_ADDRESS = "127.0.0.1:7233"
PARTIAL_KEEPALIVE_SLEEP_SECONDS = 30 * 24 * 60 * 60
VERIFICATION_LEVEL_READ_MODEL = "read_model_seen"
VERIFICATION_LEVEL_SERVER_HISTORY = "server_history_verified"
VERIFICATION_LEVEL_WORKFLOW_OPEN = "workflow_open"
MATURE_EXECUTION_CARRIER = "codex_exec_json_app_server_sdk_worker"
MATURE_EXECUTION_CARRIER_REFS = [
    "openai/codex exec --json",
    "codex app-server worker turn",
    "CodexSDK/codex-wrapper JSONL stream shape",
    "codex-orchestrator jobs--json observe shape",
]
CODEX_A_BRAIN_DISPATCHER_ROLE = "brain_turn_and_worker_dispatch_coordinator_only"
CONTINUATION_AUTHORIZATION_LANE = "codex_a_brain_dispatch"
CONTINUATION_GATE_OWNER = "codex_a_brain_plus_temporal_assignment_dag"
SEGMENT_AUDIT_REVIEWER_LANE = "grok_segment_audit"
SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE = "grok_segment_audit_dual_visible_and_backend_verdict"
SEGMENT_AUDIT_AUTHORIZATION_LANE = SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE
SEGMENT_PASS_NEXT_BOUNDED_WORKER_HOP = "same_workflow_segment_pass_next_bounded_worker"
TEMPORAL_PATCH_ASSIGNMENT_DRIVEN_PHASE_EXIT_SEGMENT_PASS = "assignment-driven-phase-exit-segment-pass-v1"
TEMPORAL_PATCH_GROK_WAIT_L1_CONTINUATION_WORKER = "grok-wait-l1-continuation-worker-v1"
TEMPORAL_PATCH_PHASE_EXIT_NO_GROK_WAIT_BEFORE_PARTIAL_CONTINUATION = "phase-exit-no-grok-wait-before-partial-continuation-v1"
TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER = "seed-cortex-worker-dispatch-ledger-v1"
TEMPORAL_PATCH_SEED_CORTEX_DURABLE_PARALLEL_WAVE_PACKET = "seed-cortex-durable-parallel-wave-packet-v1"
TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE = (
    "seed-cortex-default-main-loop-trigger-candidate-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SCHEDULER_INVOCATION_PACKET = (
    "seed-cortex-scheduler-invocation-packet-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_DURABLE_CONSUMER = (
    "seed-cortex-source-frontier-durable-consumer-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_WAVE_SCHEDULER = (
    "seed-cortex-source-family-wave-scheduler-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET = (
    "seed-cortex-source-family-mature-thin-bind-sunset-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_DP_WORKER_POOL_WAVE = (
    "seed-cortex-default-dp-worker-pool-wave-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_PHASE0_REUSABLE_KERNEL = (
    "seed-cortex-phase0-reusable-kernel-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_WAVE2_MAINCHAIN_HYGIENE = (
    "seed-cortex-wave2-mainchain-hygiene-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_PRE_PASS_AUDIT_LOOP = (
    "seed-cortex-pre-pass-audit-loop-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN = (
    "seed-cortex-allocation-plan-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE = (
    "seed-cortex-source-frontier-workerbrief-bridge-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERPOOL_CLOSURE = (
    "seed-cortex-source-frontier-workerpool-closure-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE = (
    "seed-cortex-continuation-workerpool-closure-v1"
)
SEED_CORTEX_RUNTIME_ROOT = pathlib.Path(r"D:\XINAO_RESEARCH_RUNTIME")
SEED_CORTEX_ROUTE_PROFILE = "seed_cortex_phase0"
SEED_CORTEX_WORK_ID = "xinao_seed_cortex_phase0_20260701"
ASSIGNMENT_DAG_WORKERPOOL_MIN_TIMEOUT_SECONDS = 1800


def temporal_patch_marker_policy() -> dict[str, Any]:
    return {
        "new_history_continuation_lane": CONTINUATION_AUTHORIZATION_LANE,
        "old_replay_mainchain_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "segment_audit_authorization_lane": SEGMENT_AUDIT_AUTHORIZATION_LANE,
        "segment_audit_reviewer_lane": SEGMENT_AUDIT_REVIEWER_LANE,
        "phase_exit_segment_audit_unchanged": True,
        "old_replay_does_not_restore_grok_mainchain_authorization": True,
        "patch_markers": {
            "assignment_driven_phase_exit_segment_pass": TEMPORAL_PATCH_ASSIGNMENT_DRIVEN_PHASE_EXIT_SEGMENT_PASS,
            "grok_wait_l1_continuation_worker": TEMPORAL_PATCH_GROK_WAIT_L1_CONTINUATION_WORKER,
            "phase_exit_no_grok_wait_before_partial_continuation": TEMPORAL_PATCH_PHASE_EXIT_NO_GROK_WAIT_BEFORE_PARTIAL_CONTINUATION,
            "seed_cortex_worker_dispatch_ledger": TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER,
            "seed_cortex_durable_parallel_wave_packet": TEMPORAL_PATCH_SEED_CORTEX_DURABLE_PARALLEL_WAVE_PACKET,
            "seed_cortex_default_main_loop_trigger_candidate": (
                TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE
            ),
            "seed_cortex_scheduler_invocation_packet": (
                TEMPORAL_PATCH_SEED_CORTEX_SCHEDULER_INVOCATION_PACKET
            ),
            "seed_cortex_source_frontier_durable_consumer": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_DURABLE_CONSUMER
            ),
            "seed_cortex_source_family_wave_scheduler": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_WAVE_SCHEDULER
            ),
            "seed_cortex_source_family_mature_thin_bind_sunset": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET
            ),
            "seed_cortex_default_dp_worker_pool_wave": (
                TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_DP_WORKER_POOL_WAVE
            ),
            "seed_cortex_phase0_reusable_kernel": (
                TEMPORAL_PATCH_SEED_CORTEX_PHASE0_REUSABLE_KERNEL
            ),
            "seed_cortex_wave2_mainchain_hygiene": (
                TEMPORAL_PATCH_SEED_CORTEX_WAVE2_MAINCHAIN_HYGIENE
            ),
            "seed_cortex_pre_pass_audit_loop": (
                TEMPORAL_PATCH_SEED_CORTEX_PRE_PASS_AUDIT_LOOP
            ),
            "seed_cortex_allocation_plan": (
                TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN
            ),
            "seed_cortex_source_frontier_workerbrief_bridge": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE
            ),
            "seed_cortex_source_frontier_workerpool_closure": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERPOOL_CLOSURE
            ),
            "seed_cortex_continuation_workerpool_closure": (
                TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE
            ),
        },
    }


def temporal_patch_enabled(marker: str, *, default_when_unavailable: bool = True) -> bool:
    patched = getattr(workflow, "patched", None)
    if not callable(patched):
        return default_when_unavailable
    try:
        return bool(patched(marker))
    except Exception:
        return default_when_unavailable


def embedded_workerbrief_bridge_activity_from_main_loop_tick(
    main_loop_tick: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(main_loop_tick, dict):
        return {}
    bridge = main_loop_tick.get("source_frontier_workerbrief_bridge")
    if not isinstance(bridge, dict):
        return {}
    output = bridge.get("output_paths") if isinstance(bridge.get("output_paths"), dict) else {}
    validation = bridge.get("validation") if isinstance(bridge.get("validation"), dict) else {}
    passed = validation.get("passed") is True
    wave_id = str(bridge.get("wave_id") or "")
    if not wave_id:
        return {}
    return {
        "activity": "source_frontier_workerbrief_bridge",
        "status": "embedded_main_loop_tick_bridge" if passed else "embedded_main_loop_tick_bridge_blocked",
        "named_blocker": "" if passed else "CODEX_S_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_VALIDATION_FAILED",
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_main_loop_tick_embedded_workerbrief_bridge",
        "bridge_validation_passed": passed,
        "bridge_wave_id": wave_id,
        "bridge_latest_ref": str(output.get("latest") or ""),
        "bridge_temporal_activity_latest_ref": str(output.get("temporal_activity_latest") or ""),
        "bridge_wave_ref": str(output.get("wave") or ""),
        "source_bound_worker_brief_queue_ref": str(output.get("worker_brief_queue_latest") or ""),
        "mapping_ref": str(output.get("mapping_latest") or ""),
        "worker_dispatch_ledger_wave_ref": str(output.get("worker_dispatch_ledger_wave") or ""),
        "worker_dispatch_ledger_activity_ref": str(output.get("worker_dispatch_ledger_activity") or ""),
        "readback_zh_ref": str(output.get("readback_zh") or ""),
        "source_item_count": bridge.get("source_item_count"),
        "worker_brief_binding_count": bridge.get("worker_brief_binding_count"),
        "generated_bounded_item": bridge.get("source_frontier_delta", {}).get("generated_bounded_item")
        if isinstance(bridge.get("source_frontier_delta"), dict)
        else None,
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("main_loop_tick_embedded_workerbrief_bridge_read_model"),
    }


def main_loop_tick_workerbrief_bridge_view(tick_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(tick_payload, dict):
        return {}
    bridge = tick_payload.get("source_frontier_workerbrief_bridge")
    if not isinstance(bridge, dict):
        return {}
    return {
        "wave_id": bridge.get("wave_id"),
        "status": bridge.get("status"),
        "validation": bridge.get("validation") if isinstance(bridge.get("validation"), dict) else {},
        "output_paths": bridge.get("output_paths") if isinstance(bridge.get("output_paths"), dict) else {},
        "source_item_count": bridge.get("source_item_count"),
        "worker_brief_binding_count": bridge.get("worker_brief_binding_count"),
        "source_frontier_delta": bridge.get("source_frontier_delta")
        if isinstance(bridge.get("source_frontier_delta"), dict)
        else {},
        "latest_alias_is_not_proof": bridge.get("latest_alias_is_not_proof"),
        "completion_claim_allowed": bridge.get("completion_claim_allowed"),
        "not_execution_controller": bridge.get("not_execution_controller"),
    }


def is_seed_cortex_s_payload(input_payload: dict[str, Any]) -> bool:
    route_profile = str(input_payload.get("route_profile") or "").strip()
    task_id = str(input_payload.get("task_id") or "").strip()
    return route_profile == SEED_CORTEX_ROUTE_PROFILE or task_id == SEED_CORTEX_WORK_ID


def seed_cortex_runtime_root_allowed(runtime_root: pathlib.Path) -> bool:
    runtime_text = str(runtime_root).replace("/", "\\").rstrip("\\").lower()
    required_text = str(SEED_CORTEX_RUNTIME_ROOT).replace("/", "\\").rstrip("\\").lower()
    return runtime_text == required_text


def should_call_seed_cortex_worker_dispatch_ledger(input_payload: dict[str, Any]) -> bool:
    if not is_seed_cortex_s_payload(input_payload):
        return False
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    return seed_cortex_runtime_root_allowed(runtime_root)


def temporal_hot_path_wave_id(
    input_payload: dict[str, Any],
    wave_index: int,
    signal_payload: dict[str, Any] | None = None,
) -> str:
    signal = signal_payload if isinstance(signal_payload, dict) else {}
    base = _safe_task_file_id(
        str(input_payload.get("workflow_id") or input_payload.get("task_id") or "workflow")
    )
    node = _safe_task_file_id(
        str(
            signal.get("assignment_dag_node_id")
            or signal.get("source_kind")
            or "ingress"
        )
    )
    return f"{base}-wave-{max(1, int(wave_index)):02d}-{node[:48]}"


def continuation_authorization_fields() -> dict[str, Any]:
    return {
        "mainchain_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "continuation_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "continuation_gate_owner": CONTINUATION_GATE_OWNER,
        "continuation_gate": {
            "owner": CONTINUATION_GATE_OWNER,
            "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
            "dispatch_model": "reconcile_read_models_plus_temporal_dispatch",
            "worker_carrier": "temporal_task_queue_worker_long_poll",
            "not_bidirectional_http_poll": True,
            "waiting_grok_blocks_continuation": False,
        },
        "segment_audit_authorization_lane": SEGMENT_AUDIT_AUTHORIZATION_LANE,
        "segment_audit_verdict_authorization_lane": SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE,
        "segment_audit_scope": "phase_exit_only",
        "waiting_grok_blocks_continuation": False,
        "waiting_grok_blocks_completion_stop_l2": True,
        "grok_mainchain_authorization_allowed": False,
        "phase_exit_segment_audit_unchanged": True,
        "temporal_patch_marker_policy": temporal_patch_marker_policy(),
    }


def normalize_verification_level(level: Any) -> str:
    if level in (VERIFICATION_LEVEL_READ_MODEL, VERIFICATION_LEVEL_SERVER_HISTORY, VERIFICATION_LEVEL_WORKFLOW_OPEN):
        return str(level)
    legacy_level = str(level or "")
    if legacy_level in ("L1_READ_MODEL_ONLY", "L2_SERVER_BOUND_PENDING_HISTORY", "L2_SERVER_HISTORY_VERIFIED", "L3_WORKFLOW_OPEN"):
        mapping = {
            "L1_READ_MODEL_ONLY": VERIFICATION_LEVEL_READ_MODEL,
            "L2_SERVER_BOUND_PENDING_HISTORY": VERIFICATION_LEVEL_SERVER_HISTORY,
            "L2_SERVER_HISTORY_VERIFIED": VERIFICATION_LEVEL_SERVER_HISTORY,
            "L3_WORKFLOW_OPEN": VERIFICATION_LEVEL_WORKFLOW_OPEN,
        }
        return mapping[legacy_level]
    return VERIFICATION_LEVEL_READ_MODEL


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: pathlib.Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return dict(default or {})
    return payload if isinstance(payload, dict) else dict(default or {})


def temporal_task_queue_has_poller(task_queue: str) -> tuple[bool, dict[str, Any]]:
    command = [
        "temporal",
        "task-queue",
        "describe",
        "--address",
        TEMPORAL_ADDRESS,
        "--task-queue",
        task_queue,
        "--output",
        "json",
        "--command-timeout",
        "10s",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return False, {
            "status": "blocked",
            "named_blocker": "TEMPORAL_TASK_QUEUE_DESCRIBE_FAILED",
            "error": str(exc),
        }
    if completed.returncode != 0:
        return False, {
            "status": "blocked",
            "named_blocker": "TEMPORAL_TASK_QUEUE_DESCRIBE_FAILED",
            "stderr": (completed.stderr or completed.stdout)[-1200:],
        }
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        return False, {
            "status": "blocked",
            "named_blocker": "TEMPORAL_TASK_QUEUE_DESCRIBE_JSON_INVALID",
            "error": str(exc),
        }
    pollers = payload.get("pollers")
    poller_count = len(pollers) if isinstance(pollers, list) else 0
    return poller_count > 0, {
        "status": "poller_seen" if poller_count > 0 else "blocked",
        "named_blocker": "" if poller_count > 0 else "TEMPORAL_WORKER_SERVICE_NOT_POLLING",
        "pollers_seen": poller_count,
        "stats_seen": len(payload.get("stats") or []) if isinstance(payload.get("stats"), list) else 0,
        "not_source_of_truth": True,
        "not_user_completion": True,
    }


def build_worker_assignment(result: dict[str, Any], assignment_ref: pathlib.Path) -> dict[str, Any]:
    task_id = str(result.get("task_id", "")).strip()
    user_goal = str(result.get("user_goal", "")).strip()
    current_intent_id = str(result.get("current_intent_id") or "intent-xinao-intent-admission-layer-mvp")
    return {
        "schema_version": "xinao.worker_assignment.v1",
        "task_id": task_id,
        "current_intent_id": current_intent_id,
        "created_at": now(),
        "assignment_scope": "TaskObject/current_task_owner lifecycle binding for Temporal-compatible durable flow",
        "semantic_object": user_goal
        or "Temporal-compatible task owner binding with task-scoped worker evidence requirements.",
        "codex_a_role": CODEX_A_BRAIN_DISPATCHER_ROLE,
        "codex_a_execution_owner": False,
        "codex_not_all_roles_at_once": True,
        "planner": "CodexA current brain turn + LangGraph planning frontier",
        "executor": [
            "Temporal-compatible workflow owner",
            "LangGraph checkpoint/frontier",
            "Codex exec --json or app-server worker when execute_codex_worker is enabled",
            "visible-inject reference delivery only when this task came from Action ingress",
        ],
        "verifier": [
            "state/temporal_codex_task_workflow/tasks/<task_id>.json",
            "state/current_task_owner/<task_id>.json",
            "state/worker_assignment/<task_id>.json",
            "LangGraph checkpoint readback",
            "completion claim payload for the same task_id before any completion statement",
        ],
        "side_auditor": [
            "independent side audit before completion claim",
            "human-visible audit lane when completion/final/Stop semantics are involved",
        ],
        "stop_authority": "current_task_owner + worker_assignment + task-bound worker evidence + side audit + /completion/claim; this assignment is not user completion",
        "fallback_owner": "CodexA brain turn continues lifecycle repair or records a named blocker; user is not log transport",
        "mature_carriers": [
            "TaskObject/current_task_owner",
            "Temporal-compatible durable flow",
            "LangGraph checkpoint/frontier",
            "Codex exec --json/app-server worker evidence",
            "OPA/Conftest/completion claim gate",
        ],
        "required_evidence": [
            str(assignment_ref),
            str(assignment_ref.parents[1] / "current_task_owner" / f"{task_id}.json"),
            str(assignment_ref.parents[1] / "temporal_codex_task_workflow" / "tasks" / f"{task_id}.json"),
            "task-scoped Codex worker JSONL or explicit skipped-worker blocker",
            "task-scoped completion claim payload only for completion decisions",
        ],
        "allowed_structural_actions": [
            "lifecycle repair for owner/assignment/readback consistency",
            "run focused tests and verifiers",
            "deploy verified thin adapter to D runtime",
            "record task-bound evidence",
        ],
        "forbidden_claims": [
            "user completion",
            "global runtime complete",
            "visible-inject delivery is execution completion",
            "workflow completed is user task complete",
            "HTTP accepted/readback is final completion",
        ],
        "worker_assignment_ref": str(assignment_ref),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }


def persist_current_task_binding(runtime_root: pathlib.Path, owner: dict[str, Any], result: dict[str, Any]) -> str:
    task_id = str(owner.get("task_id") or result.get("task_id") or "").strip()
    if not task_id:
        return ""
    assignment_ref = runtime_root / "state" / "worker_assignment" / f"{task_id}.json"
    owner["worker_assignment_ref"] = str(assignment_ref)
    result["worker_assignment_ref"] = str(assignment_ref)
    result["task_id"] = task_id
    if not assignment_ref.exists():
        write_json(assignment_ref, build_worker_assignment(result, assignment_ref))
    write_json(runtime_root / "state" / "current_task_owner" / f"{task_id}.json", owner)
    if result.get("promote_current_task_owner_latest", True) is not False:
        write_json(runtime_root / "state" / "current_task_owner" / "latest.json", owner)
    return str(assignment_ref)


def persist_workflow_result(runtime_root: pathlib.Path, result: dict[str, Any]) -> None:
    state_dir = runtime_root / "state" / "temporal_codex_task_workflow"
    task_id = str(result.get("task_id", "")).strip()
    workflow_id = str(result.get("workflow_id", "")).strip()
    workflow_run_id = str(result.get("workflow_run_id", "")).strip()
    if task_id:
        owner = result.get("current_task_owner")
        if isinstance(owner, dict):
            persist_current_task_binding(runtime_root, owner, result)
        write_json(state_dir / "tasks" / f"{task_id}.json", result)
        if workflow_id:
            workflow_safe = _safe_task_file_id(workflow_id)
            run_safe = _safe_task_file_id(workflow_run_id) if workflow_run_id else "no-run-id"
            workflow_ref = state_dir / "workflows" / f"{workflow_safe}.{run_safe}.json"
            task_workflow_ref = state_dir / "tasks" / _safe_task_file_id(task_id) / f"{workflow_safe}.{run_safe}.json"
            result = {
                **result,
                "task_latest_ref": str(state_dir / "tasks" / f"{task_id}.json"),
                "workflow_result_ref": str(workflow_ref),
                "task_workflow_result_ref": str(task_workflow_ref),
            }
            write_json(workflow_ref, result)
            write_json(task_workflow_ref, result)
    write_json(state_dir / "latest.json", result)
    events = state_dir / "events.ndjson"
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")


def task_object_binding_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    task_object = payload.get("compiled_task_object") if isinstance(payload.get("compiled_task_object"), dict) else {}
    if not task_object:
        task_object = payload.get("task_object") if isinstance(payload.get("task_object"), dict) else {}
    graph_result = payload.get("graph_result") if isinstance(payload.get("graph_result"), dict) else {}
    if not task_object and isinstance(graph_result.get("task_object"), dict):
        task_object = graph_result["task_object"]
    return {
        "compiled_task_object": dict(task_object or {}),
        "compiled_task_object_sha256": payload.get("compiled_task_object_sha256") or task_object.get("task_object_sha256", ""),
        "source_refs_sha256": payload.get("source_refs_sha256") or task_object.get("source_refs_sha256", ""),
        "acceptance_contract": payload.get("acceptance_contract") or task_object.get("acceptance_contract", {}),
    }


def source_goal_ref(user_goal: str, objective_code: str = "TEMPORAL_CODEX_TASK_WORKFLOW") -> dict[str, Any]:
    return {
        "source_text_embedded": False,
        "source_text_authority": False,
        "semantic_input_role": "non_authoritative_reference",
        "source_sha256": hashlib.sha256(user_goal.encode("utf-8")).hexdigest() if user_goal else "",
        "source_char_count": len(user_goal),
        "compiled_objective_code": objective_code,
    }


def file_source_ref(path: pathlib.Path) -> dict[str, Any]:
    data = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "role": "non_authoritative_semantic_input",
        "source_text_authority": False,
        "semantic_input_role": "non_authoritative_reference",
    }


def read_compiled_task_object(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("compiled TaskObject JSON must be an object")
    return payload


def authority_boundary(role: str) -> dict[str, Any]:
    return {
        "role": role,
        "source_of_truth": "external_mature_runtime",
        "truth_carriers": [
            "Temporal workflow state",
            "LangGraph checkpoint/store",
            "OPA/Conftest policy decision",
            "machine verifier evidence",
            "human-visible audit evidence",
        ],
        "not_source_of_truth": True,
        "not_user_completion": True,
        "workflow_completed_is_not_user_complete": True,
    }


def compact_history_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 1000 else value[:1000] + "...[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def compact_observe_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "schema_version": payload.get("schema_version"),
        "event_count": payload.get("event_count"),
        "event_type_counts": payload.get("event_type_counts", {}),
        "agent_message_count": payload.get("agent_message_count"),
        "command_execution_count": payload.get("command_execution_count"),
        "turn_completed_count": payload.get("turn_completed_count"),
        "token_usage": payload.get("token_usage", {}),
        "files_modified_count": payload.get("files_modified_count"),
        "files_modified": payload.get("files_modified", []),
        "last_agent_message_preview": compact_history_scalar(
            payload.get("last_agent_message_preview") or ""
        ),
        "mature_pattern_refs": payload.get("mature_pattern_refs", []),
        "not_source_of_truth": payload.get("not_source_of_truth") is True,
        "not_user_completion": payload.get("not_user_completion") is True,
        "not_completion_decision": payload.get("not_completion_decision") is True,
    }


def compact_human_egress_filter(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    compact = {
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "human_egress_policy": payload.get("human_egress_policy"),
        "headless_worker": payload.get("headless_worker") is True,
        "jsonl_path": payload.get("jsonl_path", ""),
        "raw_final_path": payload.get("raw_final_path", ""),
        "user_visible_final_path": payload.get("user_visible_final_path", ""),
        "raw_final_backend_evidence_only": payload.get("raw_final_backend_evidence_only")
        is True,
        "worker_final_user_visible_allowed": payload.get("worker_final_user_visible_allowed")
        is True,
        "codex_final_to_user_allowed": payload.get("codex_final_to_user_allowed") is True,
        "segment_boundary_user_egress_blocked": payload.get(
            "segment_boundary_user_egress_blocked"
        )
        is True,
        "agent_message_count": payload.get("agent_message_count"),
        "not_source_of_truth": payload.get("not_source_of_truth") is True,
        "not_user_completion": payload.get("not_user_completion") is True,
        "not_completion_decision": payload.get("not_completion_decision") is True,
    }
    observe = payload.get("jobs_json_observe")
    if isinstance(observe, dict):
        compact["jobs_json_observe"] = compact_observe_summary(observe)
    return compact


def compact_history_ref_item(item: Any) -> Any:
    if isinstance(item, (str, int, float, bool)) or item is None:
        return compact_history_scalar(item)
    if not isinstance(item, dict):
        return None
    preferred_keys = (
        "ref",
        "path",
        "id",
        "entry_id",
        "lane_ref",
        "lane_kind",
        "source",
        "provider",
        "mode",
        "source_entry_id",
        "dispatch_status",
        "poll_status",
        "status",
        "workflow_id",
        "wave_id",
        "worker_brief_id",
        "digest",
        "sha256",
        "exists",
        "validation_passed",
        "not_execution_controller",
    )
    compact: dict[str, Any] = {}
    for item_key in preferred_keys:
        if item_key not in item:
            continue
        value = compact_history_scalar(item.get(item_key))
        if value not in (None, ""):
            compact[item_key] = value
    return compact


def compact_history_value(key: str, value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return compact_history_scalar(value)
    if isinstance(value, dict):
        if key in {"validation", "runtime_entrypoint_invocation", "authority_boundary"}:
            return {
                str(k): compact_history_value(str(k), v)
                for k, v in value.items()
                if not isinstance(v, (list, dict)) or str(k).endswith(("_ref", "_refs"))
            }
        if key == "human_egress_filter":
            return compact_human_egress_filter(value)
        if key in {"jobs_json_observe_backend_readback", "jobs_json_observe"}:
            return compact_observe_summary(value)
        if key in {
            "backend_evidence_refs",
            "evidence_refs",
            "output_paths",
            "temporal",
            "next_wave_decision",
            "runtime_entrypoint",
        }:
            return {
                str(k): compact_history_value(str(k), v)
                for k, v in value.items()
                if not str(k).endswith(("payload", "activities"))
            }
        return {}
    if isinstance(value, list):
        if key in {"activities", "task_bound_worker_command_executions", "command_executions"}:
            return []
        if len(value) <= 50 and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            return [compact_history_scalar(item) for item in value]
        if key.endswith(("_refs", "_ids", "_paths")):
            return [
                compacted
                for compacted in (
                    compact_history_ref_item(item) for item in value[:50]
                )
                if compacted not in (None, {}, "")
            ]
        return []
    return None


def compact_activity_for_history(activity_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(activity_payload, dict):
        return {}
    compact: dict[str, Any] = {}
    always_keep = {
        "activity",
        "status",
        "named_blocker",
        "task_id",
        "worker_task_id",
        "workflow_id",
        "workflow_run_id",
        "wave_id",
        "run_id",
        "task_queue",
        "worker_kind",
        "phase_scope",
        "worker_assignment_ref",
        "runtime_enforced",
        "runtime_enforced_scope",
        "completion_claim_allowed",
        "not_source_of_truth",
        "not_user_completion",
        "not_completion_decision",
        "not_completion_gate",
        "not_execution_controller",
        "implementation_worker_required",
        "continue_same_task_signal_worker_required",
        "segment_pass_next_worker_required",
        "jsonl_exists",
        "codex_jsonl_is_execution_evidence",
        "raw_final_backend_evidence_only",
        "worker_final_user_visible_allowed",
        "codex_final_to_user_allowed",
        "no_pytest_wall_to_user",
        "headless_worker",
        "task_bound_worker",
        "fallback_canary_only",
        "expected_marker",
        "expected_marker_seen",
        "activator_ok",
        "reused_existing_task_result",
        "existing_task_result_ref",
        "external_condition",
        "retryable",
        "retry_after_text",
        "jobs_json_observe_joined",
        "task_bound_worker_token_usage",
        "task_bound_worker_files_modified",
        "task_bound_worker_files_modified_count",
        "failure_classification",
        "segment_pass_checker_default",
    }
    for key, value in activity_payload.items():
        keep = (
            key in always_keep
            or key.endswith(
                (
                    "_id",
                    "_ids",
                    "_ref",
                    "_refs",
                    "_path",
                    "_paths",
                    "_count",
                    "_counts",
                    "_sha256",
                    "_scope",
                    "_status",
                    "_policy",
                    "_decision",
                )
            )
            or key.startswith(("not_", "is_", "has_"))
            or key in {"validation", "authority_boundary", "human_egress_filter"}
        )
        if keep:
            compact_value = compact_history_value(key, value)
            if compact_value not in (None, {}, []):
                compact[key] = compact_value
    observe = activity_payload.get("jobs_json_observe_backend_readback")
    if isinstance(observe, dict):
        compact["jobs_json_observe_backend_readback"] = compact_observe_summary(observe)
    observe = activity_payload.get("jobs_json_observe")
    if isinstance(observe, dict):
        compact["jobs_json_observe"] = compact_observe_summary(observe)
    commands = activity_payload.get("task_bound_worker_command_executions")
    if isinstance(commands, list):
        compact["task_bound_worker_command_execution_count"] = len(commands)
    verification = activity_payload.get("verification")
    if isinstance(verification, list):
        compact["verification"] = compact_history_value("verification", verification)
    failure_classification = activity_payload.get("failure_classification")
    if isinstance(failure_classification, dict):
        compact["failure_classification"] = {
            "named_blocker": compact_history_scalar(
                failure_classification.get("named_blocker", "")
            ),
            "external_condition": failure_classification.get("external_condition") is True,
            "retryable": failure_classification.get("retryable") is True,
            "retry_after_text": compact_history_scalar(
                failure_classification.get("retry_after_text", "")
            ),
        }
    work_package = activity_payload.get("work_package")
    if isinstance(work_package, dict):
        work_package_summary = {
            "files": compact_history_value("files", work_package.get("files", [])),
            "objective": compact_history_scalar(work_package.get("objective", "")),
            "next_ready_node_id": compact_history_scalar(work_package.get("next_ready_node_id", "")),
        }
        work_package_summary = {
            key: value
            for key, value in work_package_summary.items()
            if value not in (None, "", [], {})
        }
        if work_package_summary:
            compact["work_package"] = work_package_summary
    return compact


def compact_temporal_history_result(result: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(result)
    for key, value in list(compacted.items()):
        if key.endswith("_activity") and isinstance(value, dict):
            compacted[key] = compact_activity_for_history(value)
    activities = compacted.get("activities")
    if isinstance(activities, list):
        compacted["activities"] = [
            compact_activity_for_history(item) for item in activities if isinstance(item, dict)
        ]
    if isinstance(compacted.get("segment_pass_next_worker"), dict):
        compacted["segment_pass_next_worker"] = compact_activity_for_history(
            compacted["segment_pass_next_worker"]
        )
    if isinstance(compacted.get("jobs_json_observe_backend_readback"), dict):
        compacted["jobs_json_observe_backend_readback"] = compact_observe_summary(
            compacted["jobs_json_observe_backend_readback"]
        )
    commands = compacted.get("task_bound_worker_command_executions")
    if isinstance(commands, list):
        compacted["task_bound_worker_command_execution_count"] = len(commands)
        compacted["task_bound_worker_command_executions"] = []
    if isinstance(compacted.get("phase5_observability_discovery_readback"), dict):
        phase5 = compacted["phase5_observability_discovery_readback"]
        compacted["phase5_observability_discovery_readback"] = {
            "task_workflow_correlated": phase5.get("task_workflow_correlated"),
            "evidence_refs": phase5.get("evidence_refs", {}),
            "progress_truth_sources": phase5.get("progress_truth_sources", []),
            "truth_promotion_denied_reason": phase5.get(
                "truth_promotion_denied_reason", ""
            ),
        }
    return compacted


def compact_phase3_activity_result(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    keep_keys = {
        "schema_version",
        "sentinel",
        "activity",
        "status",
        "task_id",
        "wave_id",
        "named_blocker",
        "phase1_latest_ref",
        "worker_dispatch_ledger_ref",
        "tool_trace_evidence_ref",
        "draft_staging_queue_ref",
        "merge_consumer_ref",
        "merge_artifact",
        "draft_count",
        "staged_count",
        "merged_count",
        "actual_dispatched_width",
        "actual_completed_width",
        "true_dp_draft_count",
        "local_stub_draft_count",
        "completion_claim_allowed",
        "not_completion_boundary",
        "validation",
        "generated_at",
    }
    compact: dict[str, Any] = {}
    for key in keep_keys:
        if key in payload:
            compact[key] = compact_history_value(key, payload[key])
    phase_summary = payload.get("phase1_payload_summary")
    if isinstance(phase_summary, dict):
        compact["phase1_payload_summary"] = {
            str(key): compact_history_value(str(key), value)
            for key, value in phase_summary.items()
            if str(key).endswith(("_count", "_ref", "_id"))
            or str(key)
            in {
                "status",
                "wave_id",
                "named_blocker",
                "actual_dispatched_width",
                "actual_completed_width",
            }
        }
    activity_context = payload.get("activity_context")
    if isinstance(activity_context, dict):
        compact["activity_context"] = {
            key: compact_history_value(key, value)
            for key, value in activity_context.items()
            if key
            in {
                "workflow_id",
                "workflow_run_id",
                "task_queue",
                "activity_name",
                "event_history_ref",
            }
            or key.endswith("_ref")
        }
    dynamic_width = payload.get("dynamic_width_decision")
    if isinstance(dynamic_width, dict):
        compact["dynamic_width_decision"] = {
            "target_width": dynamic_width.get("target_width"),
            "target_width_source": dynamic_width.get("target_width_source"),
            "operator_cap_applied": dynamic_width.get("operator_cap_applied"),
            "fixed_20_or_50_used": dynamic_width.get("fixed_20_or_50_used"),
            "runtime_enforced": dynamic_width.get("runtime_enforced"),
            "not_execution_controller": dynamic_width.get("not_execution_controller"),
        }
    capacity_observation = payload.get("capacity_observation")
    if isinstance(capacity_observation, dict):
        compact["capacity_observation"] = {
            "not_default_width": capacity_observation.get("not_default_width"),
            "not_permanent_cap": capacity_observation.get("not_permanent_cap"),
            "provider_headroom_bound": capacity_observation.get("provider_headroom_bound"),
            "backlog_bound": capacity_observation.get("backlog_bound"),
        }
    return compact


def retry_policy_dict() -> dict[str, Any]:
    return {
        "initial_interval_seconds": 1,
        "maximum_interval_seconds": 10,
        "maximum_attempts": 3,
        "non_retryable_error_types": list(NON_RETRYABLE_ERROR_TYPES),
        "retryable_error_types": list(TRANSIENT_ERROR_TYPES),
    }


def temporal_retry_policy():
    return RetryPolicy(
        initial_interval=dt.timedelta(seconds=1),
        maximum_interval=dt.timedelta(seconds=10),
        maximum_attempts=3,
        non_retryable_error_types=list(NON_RETRYABLE_ERROR_TYPES),
    )


def _read_text_if_exists(path: pathlib.Path, limit: int = 4000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def _path_exists_and_nonempty(path_raw: Any) -> bool:
    if not path_raw:
        return False
    path = pathlib.Path(str(path_raw))
    return path.is_file() and path.stat().st_size > 0


def _safe_task_file_id(task_id: str) -> str:
    safe = "".join(ch for ch in str(task_id) if ch.isalnum() or ch in "-_.")
    return safe or hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:24]


def _grok_admin_bridge_root(runtime_root: pathlib.Path) -> pathlib.Path:
    desktop_bridge = pathlib.Path(r"C:\Users\xx363\Desktop\Grok_Admin_Isolated\workspace\grok-admin-bridge")
    if runtime_root == DEFAULT_RUNTIME and desktop_bridge.exists():
        return desktop_bridge
    return runtime_root / "grok-admin-bridge"


def _human_egress_required(segment_gate: dict[str, Any], panel_payload: dict[str, Any]) -> bool:
    status = str(segment_gate.get("status") or panel_payload.get("segment_audit_status") or "")
    return bool(
        segment_gate.get("segment_audit_ready")
        or segment_gate.get("workflow_waiting_grok_segment_audit")
        or status
        or panel_payload.get("codex_to_grok_segment_audit_summon_ref")
        or panel_payload.get("grok_segment_verdict_leg2_valid")
    )


def _write_grok_human_egress_report(
    runtime_root: pathlib.Path,
    task_id: str,
    panel_payload: dict[str, Any],
    segment_gate: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    if not _human_egress_required(segment_gate, panel_payload):
        return {}
    safe_task_id = _safe_task_file_id(task_id)
    generated_at = now()
    state_report_dir = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "reports"
    state_report_dir.mkdir(parents=True, exist_ok=True)
    state_report_ref = state_report_dir / f"{safe_task_id}.grok_report.zh.md"
    state_latest_report_ref = state_report_dir / "latest.grok_report.zh.md"
    report_ref = state_report_ref
    latest_report_ref = state_latest_report_ref
    inbox_ref = state_report_ref
    router_dir = runtime_root / "state" / "human_egress_router"
    router_task_ref = router_dir / "tasks" / f"{safe_task_id}.json"
    router_latest_ref = router_dir / "latest.json"
    worker_jsonl = str(
        panel_payload.get("same_workflow_next_worker_jsonl_path")
        or panel_payload.get("worker_jsonl_path")
        or ""
    )
    worker_final = str(panel_payload.get("worker_final_path") or "")
    segment_status = str(segment_gate.get("status") or panel_payload.get("segment_audit_status_cn") or "")
    frontend_ref = runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "frontend_tui_send" / "tasks" / f"{safe_task_id}.json"
    frontend = read_json(frontend_ref, {})
    frontend_tui_sent = frontend.get("frontend_tui_sent") is True
    session_modified = frontend.get("session_modified_after_send") is True
    shortcut_launched = frontend.get("shortcut_launched") is True
    pre_existing_grok_found = (
        frontend.get("pre_existing_grok_tui_found") is True
        or int(frontend.get("pre_shortcut_candidate_count") or 0) > 0
    )
    existing_grok_reused = frontend.get("used_existing_grok_tui") is True and not shortcut_launched
    desktop_context_gate_pass = bool(existing_grok_reused and frontend_tui_sent and session_modified)
    shortcut_started_new_session = bool(shortcut_launched and frontend_tui_sent and session_modified and not pre_existing_grok_found)
    shortcut_bypassed_existing_grok = bool(shortcut_launched and pre_existing_grok_found)
    context_loss_risk = shortcut_bypassed_existing_grok
    if desktop_context_gate_pass:
        context_gate_status = "desktop_grok_context_reused"
    elif shortcut_bypassed_existing_grok:
        context_gate_status = "V2_EXISTING_GROK_CONTEXT_BYPASSED_BY_SHORTCUT"
    elif shortcut_started_new_session:
        context_gate_status = "new_grok_session_started"
    else:
        context_gate_status = "backend_only_state_no_visible_delivery"
    consumer_egress_blocked = shortcut_bypassed_existing_grok
    consumer_egress_blocker = "V2_EXISTING_GROK_CONTEXT_BYPASSED_BY_SHORTCUT" if shortcut_bypassed_existing_grok else ""
    markdown = "\n".join([
        "【Codex→Grok 人类出口路由回执 · 非完成】",
        f"task_id: {task_id}",
        f"generated_at: {generated_at}",
        f"source: {source}",
        "human_egress_route: grok_report_only",
        "grok_visible_delivery_auto_open_allowed: false",
        "grok_reads_state_only_when_user_requests_review: false",
        "auto_review_requested: true",
        "user_manual_copy_required: false",
        "desktop_grok_existing_context_preferred: true",
        "shortcut_allowed_when_no_existing_context: true",
        f"desktop_grok_context_gate: {context_gate_status}",
        f"used_existing_grok_tui: {str(existing_grok_reused).lower()}",
        f"shortcut_launched: {str(shortcut_launched).lower()}",
        f"pre_existing_grok_tui_found: {str(pre_existing_grok_found).lower()}",
        f"context_loss_risk: {str(context_loss_risk).lower()}",
        f"consumer_egress_blocked: {str(consumer_egress_blocked).lower()}",
        "codex_final_to_user_allowed: false",
        "worker_final_user_visible_allowed: false",
        "worker_final_backend_evidence_only: true",
        "no_pytest_wall_to_user: true",
        f"segment_audit_status: {segment_status}",
        f"summon_ref: {panel_payload.get('codex_to_grok_segment_audit_summon_ref') or segment_gate.get('codex_to_grok_segment_audit_summon_ref') or ''}",
        f"grok_verdict: {panel_payload.get('grok_verdict') or segment_gate.get('grok_verdict') or ''}",
        f"next_worker_task_id: {panel_payload.get('same_workflow_next_worker_task_id') or ''}",
        f"worker_jsonl_backend_evidence: {worker_jsonl}",
        f"worker_final_backend_only: {worker_final}",
        "",
        "给 Grok 的处理要求：",
        "- 用中文向用户汇报当前段状态；不要复述 pytest/JSONL 墙。",
        "- Codex worker final 只能当后台证据，不是用户状态源。",
        "- 这是系统自动拉取的审核/授权请求；用户无需复制 TUI。",
        "- 若需要 verdict，仍按 Grok→A dual_visible_and_backend leg2 回写。",
        "- 这不是用户完成、不是 Stop、不是 completion claim。",
        "",
    ])
    report_ref.write_text(markdown, encoding="utf-8")
    latest_report_ref.write_text(markdown, encoding="utf-8")
    state_report_ref.write_text(markdown, encoding="utf-8")
    state_latest_report_ref.write_text(markdown, encoding="utf-8")
    inbox_ref.write_text(markdown, encoding="utf-8")
    observe = panel_payload.get("jobs_json_observe_backend_readback")
    if not isinstance(observe, dict):
        observe = panel_payload.get("jobs_json_observe") if isinstance(panel_payload.get("jobs_json_observe"), dict) else {}
    router_payload = {
        "schema_version": "xinao.human_egress_router.v1",
        "generated_at": generated_at,
        "task_id": task_id,
        "safe_task_id": safe_task_id,
        "status": context_gate_status,
        "human_egress_route": "grok_report_only",
        "grok_visible_delivery_auto_open_allowed": False,
        "grok_reads_state_only_when_user_requests_review": False,
        "auto_review_requested": True,
        "grok_auto_review_requested": True,
        "user_requested_grok_review_required": False,
        "user_manual_copy_required": False,
        "task_aligned": True,
        "panel_task_id": str(panel_payload.get("task_id") or ""),
        "segment_gate_task_id": str(segment_gate.get("task_id") or task_id),
        "desktop_grok_existing_context_preferred": True,
        "shortcut_allowed_when_no_existing_context": True,
        "shortcut_launch_only_if_no_valid_existing_window": True,
        "frontend_tui_send_ref": str(frontend_ref),
        "frontend_tui_sent": frontend_tui_sent,
        "session_modified_after_send": session_modified,
        "used_existing_grok_tui": existing_grok_reused,
        "shortcut_launched": shortcut_launched,
        "pre_existing_grok_tui_found": pre_existing_grok_found,
        "shortcut_started_new_session": shortcut_started_new_session,
        "shortcut_bypassed_existing_grok": shortcut_bypassed_existing_grok,
        "desktop_grok_context_gate": context_gate_status,
        "desktop_grok_context_reused": desktop_context_gate_pass,
        "desktop_context_continuity_verified": desktop_context_gate_pass,
        "context_loss_risk": context_loss_risk,
        "consumer_egress_blocked": consumer_egress_blocked,
        "consumer_egress_blocker": consumer_egress_blocker,
        "target_window_title": str(frontend.get("target_window_title") or ""),
        "target_tab_name": str(frontend.get("target_tab_name") or ""),
        "codex_final_to_user_allowed": False,
        "worker_final_user_visible_allowed": False,
        "worker_final_backend_evidence_only": True,
        "no_pytest_wall_to_user": True,
        "panel_user_face_policy": "grok_report_reference_only",
        "grok_report_written": True,
        "grok_report_verify_pass": True,
        "grok_report_ref": str(state_report_ref),
        "grok_report_latest_ref": str(state_latest_report_ref),
        "grok_report_bridge_ref": str(report_ref),
        "grok_report_bridge_latest_ref": str(latest_report_ref),
        "grok_report_inbox_ref": str(inbox_ref),
        "grok_report_inbox_visible_delivery": False,
        "router_task_ref": str(router_task_ref),
        "router_latest_ref": str(router_latest_ref),
        "worker_jsonl_backend_evidence": worker_jsonl,
        "worker_final_backend_only": worker_final,
        "human_egress_filter_ref": str(panel_payload.get("human_egress_filter_ref") or ""),
        "jobs_json_observe_backend_readback": observe,
        "jobs_json_observe_joined": bool(observe),
        "codex_to_grok_segment_audit_summon_ref": str(
            panel_payload.get("codex_to_grok_segment_audit_summon_ref")
            or segment_gate.get("codex_to_grok_segment_audit_summon_ref")
            or ""
        ),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    write_json(router_task_ref, router_payload)
    write_json(router_latest_ref, router_payload)
    return router_payload


def _apply_human_egress_policy_to_panel_payload(payload: dict[str, Any], human_egress: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not human_egress:
        return payload
    observe = payload.get("jobs_json_observe_backend_readback")
    if not isinstance(observe, dict):
        observe = payload.get("jobs_json_observe") if isinstance(payload.get("jobs_json_observe"), dict) else {}
    backend_refs = dict(payload.get("backend_evidence_refs") if isinstance(payload.get("backend_evidence_refs"), dict) else {})
    backend_refs.update({
        "worker_jsonl_backend_evidence": str(human_egress.get("worker_jsonl_backend_evidence") or ""),
        "worker_final_backend_only": str(human_egress.get("worker_final_backend_only") or ""),
        "grok_report_ref": str(human_egress.get("grok_report_ref") or ""),
        "human_egress_router_ref": str(human_egress.get("router_task_ref") or ""),
        "human_egress_filter_ref": str(payload.get("human_egress_filter_ref") or ""),
        "jobs_json_observe_backend_readback": bool(observe),
    })
    for key in (
        "worker_jsonl_path",
        "worker_final_path",
        "same_workflow_next_worker_task_id",
        "same_workflow_next_worker_jsonl_path",
        "partial_continuation_ref",
    ):
        payload[key] = ""
    for key in (
        "partial_continuation_dispatch",
        "segment_pass_next_worker",
        "segment_audit_gate",
        "completion_decision",
    ):
        payload.pop(key, None)
    payload.update({
        "user_egress_sanitized": True,
        "user_egress_policy": "segment_boundary_user_face_grok_report_only",
        "frontend_user_payload_policy": "panel_short_status_no_worker_final_no_pytest_wall",
        "backend_evidence_redacted_from_user_face": True,
        "grok_visible_delivery_auto_open_allowed": False,
        "grok_reads_state_only_when_user_requests_review": False,
        "auto_review_requested": True,
        "grok_auto_review_requested": True,
        "user_requested_grok_review_required": False,
        "user_manual_copy_required": False,
        "backend_evidence_refs": backend_refs,
        "jobs_json_observe_backend_readback": observe,
        "jobs_json_observe_joined": bool(observe),
        "can_user_use_scope_cn": "用户面只显示短状态；Codex worker final/pytest/JSONL 留在后台证据和 Grok report，不直出给用户。",
        "status_cn": "段边界已封到 Grok 审查/汇报通道；Codex 不直出验收报告。",
        "user_visible_summary_cn": "段边界已封到 Grok 审查/汇报通道；后台证据已写入 Grok report。",
        "segment_audit_status_cn": "等 Grok 审查",
        "next_human_action_cn": "",
    })
    payload["panel_lines_cn"] = {
        "status_line_cn": "一句话状态：段边界已封到 Grok 审查/汇报通道；Codex 不直出验收报告。",
        "blocked_line_cn": "卡在哪：系统已自动拉 Grok 审核/授权；worker final、验收明细、JSONL 只作为后台证据。",
        "next_line_cn": "下一跳：下一机器动作：Grok 可自动采证据后回 Codex；Codex 继续同 task 后台续跑，不把验收墙发给用户。",
        "segment_audit_status_cn": "等 Grok 审查",
        "next_human_action_cn": "",
    }
    payload["status_line_cn"] = payload["panel_lines_cn"]["status_line_cn"]
    payload["blocked_line_cn"] = payload["panel_lines_cn"]["blocked_line_cn"]
    payload["next_line_cn"] = payload["panel_lines_cn"]["next_line_cn"]
    return payload


def jobs_json_observe_from_worker_result(worker_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(worker_result, dict):
        return {}
    candidates: list[dict[str, Any]] = []
    for container in (
        worker_result,
        worker_result.get("activator_result"),
        worker_result.get("activator_response"),
    ):
        if not isinstance(container, dict):
            continue
        if isinstance(container.get("jobs_json_observe"), dict):
            candidates.append(container["jobs_json_observe"])
        filter_payload = container.get("human_egress_filter")
        if isinstance(filter_payload, dict) and isinstance(filter_payload.get("jobs_json_observe"), dict):
            candidates.append(filter_payload["jobs_json_observe"])
    if not candidates:
        return {}
    observe = dict(candidates[0])
    token_usage = observe.get("token_usage") if isinstance(observe.get("token_usage"), dict) else {}
    command_executions = observe.get("command_executions") if isinstance(observe.get("command_executions"), list) else []
    files_modified = observe.get("files_modified") if isinstance(observe.get("files_modified"), list) else []
    event_type_counts = observe.get("event_type_counts") if isinstance(observe.get("event_type_counts"), dict) else {}
    return {
        "schema_version": "xinao.jobs_json_observe_backend_readback.v1",
        "event_count": int(observe.get("event_count") or 0),
        "event_type_counts": event_type_counts,
        "agent_message_count": int(observe.get("agent_message_count") or 0),
        "command_execution_count": int(observe.get("command_execution_count") or 0),
        "turn_completed_count": int(observe.get("turn_completed_count") or 0),
        "token_usage": {
            "input_tokens": int(token_usage.get("input_tokens") or 0),
            "output_tokens": int(token_usage.get("output_tokens") or 0),
            "total_tokens": int(token_usage.get("total_tokens") or 0),
        },
        "files_modified": [str(item) for item in files_modified],
        "files_modified_count": int(observe.get("files_modified_count") or len(files_modified)),
        "command_executions": [
            {
                "command": str(item.get("command") or ""),
                "exit_code": item.get("exit_code", item.get("exitCode", "")),
                "output_chars": int(item.get("output_chars") or 0),
            }
            for item in command_executions
            if isinstance(item, dict)
        ][-20:],
        "last_agent_message_preview_backend_only": str(observe.get("last_agent_message_preview") or "")[:240],
        "mature_pattern_refs": [str(item) for item in observe.get("mature_pattern_refs", [])] if isinstance(observe.get("mature_pattern_refs"), list) else [],
        "mature_pattern_summary": str(observe.get("mature_pattern_summary") or ""),
        "source_human_egress_filter_ref": str(worker_result.get("human_egress_filter_ref") or ""),
        "source_jsonl_backend_evidence": str(worker_result.get("jsonl_path") or ""),
        "source_raw_final_backend_only": str(worker_result.get("raw_final_path") or ""),
        "raw_final_redacted_from_user": True,
        "pytest_pass_wall_redacted_from_user": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
    }


def _activator_detail_payload(result_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result_payload, dict):
        return {}
    for key in ("activator_response", "activator_result"):
        nested = result_payload.get(key)
        if isinstance(nested, dict):
            return nested
    return result_payload


def _append_action_delivery_trace_event(runtime_root: pathlib.Path, task_id: str, event: dict[str, Any]) -> pathlib.Path:
    safe_task_id = _safe_task_file_id(task_id)
    trace_ref = runtime_root / "state" / "action_delivery_trace" / f"{safe_task_id}.jsonl"
    trace_ref.parent.mkdir(parents=True, exist_ok=True)
    with trace_ref.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    return trace_ref


def _write_audit_authorization_pull_request(
    runtime_root: pathlib.Path,
    task_id: str,
    segment_gate: dict[str, Any],
    *,
    source: str,
    blocker: str = "",
) -> dict[str, Any]:
    safe_task_id = _safe_task_file_id(task_id)
    generated_at = now()
    request_root = runtime_root / "state" / "audit_authorization_pull_request"
    task_ref = request_root / "tasks" / f"{safe_task_id}.json"
    latest_ref = request_root / "latest.json"
    blocker = str(blocker or segment_gate.get("named_blocker") or "GROK_SEGMENT_AUDIT_VERDICT_REQUIRED")
    event = {
        "schema_version": "xinao.action-delivery-trace-event.v1",
        "trace_id": f"audit-authorization-pull-{safe_task_id}",
        "task_id": task_id,
        "safe_task_id": safe_task_id,
        "window_id": f"audit-authorization-pull-{safe_task_id}",
        "event_name": "audit_authorization_pull_request.auto_requested",
        "status": "AUTO_REQUESTED",
        "service": "temporal_codex_task_workflow",
        "timestamp": generated_at,
        "payload": {
            "reviewer_lane": "grok_segment_audit",
            "named_blocker": blocker,
            "temporal_resume_signal": "grok_segment_verdict",
        },
    }
    trace_ref = _append_action_delivery_trace_event(runtime_root, task_id, event)
    payload = {
        "schema_version": "xinao.audit_authorization_pull_request.v1",
        "generated_at": generated_at,
        "task_id": task_id,
        "safe_task_id": safe_task_id,
        "segment_id": str(segment_gate.get("segment_id") or "phase0_phase1"),
        "status": "auto_review_authorization_requested",
        "request_state": "auto_pull_requested_waiting_external_verdict",
        "source": source,
        "named_blocker": blocker,
        "reviewer_lane": "grok_segment_audit",
        "authorization_lane": SEGMENT_AUDIT_AUTHORIZATION_LANE,
        "segment_audit_only": True,
        "authorization_scope": "phase_exit_segment_audit_only",
        "segment_audit_authorization_lane": SEGMENT_AUDIT_AUTHORIZATION_LANE,
        "segment_audit_verdict_authorization_lane": SEGMENT_AUDIT_VERDICT_AUTHORIZATION_LANE,
        "mainchain_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "continuation_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "continuation_gate_owner": CONTINUATION_GATE_OWNER,
        "waiting_grok_blocks_continuation": False,
        "waiting_grok_blocks_completion_stop_l2": True,
        "grok_mainchain_authorization_allowed": False,
        "auto_review_requested": True,
        "grok_auto_review_requested": True,
        "grok_can_auto_review_when_bridge_available": True,
        "grok_bridge_unavailable_means_request_queued_not_user_handoff": True,
        "audit_request_status": "pending_recoverable",
        "grok_bridge_availability": "degraded",
        "grok_bridge_probe": {
            "grok_tui_reachable": False,
            "inbox_writable": True,
            "receive_script_ok": False,
            "leg2_dual_delivery_ok": False,
            "probe_at": generated_at,
        },
        "grok_auto_audit_eligible": False,
        "grok_auto_audit_trigger": "leg1_post_activity",
        "user_requested_grok_review_required": False,
        "user_manual_copy_required": False,
        "user_must_copy_tui": False,
        "a_does_not_self_approve": True,
        "codex_does_not_write_grok_verdict": True,
        "automatic_verdict_allowed": False,
        "completion_stop_l2_still_gated_by_grok": True,
        "l1_continuation_not_blocked_by_grok_wait": True,
        "temporal_waits_for_signal": True,
        "temporal_resume_signal": "grok_segment_verdict",
        "next_recovery_action_cn": "等 Grok 桥接恢复后自动续审；无需用户搬 JSONL。",
        "task_ref": str(task_ref),
        "latest_ref": str(latest_ref),
        "action_delivery_trace_ref": str(trace_ref),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("audit_authorization_pull_request_read_model"),
    }
    write_json(task_ref, payload)
    write_json(latest_ref, payload)
    return payload


def _send_codex_segment_audit_summon_to_grok(
    runtime_root: pathlib.Path,
    task_id: str,
    segment_gate: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    if not (
        segment_gate.get("segment_audit_ready") is True
        and segment_gate.get("workflow_waiting_grok_segment_audit") is True
        and str(segment_gate.get("status") or "") == "WAITING_GROK_SEGMENT_AUDIT"
    ):
        return {}
    repo_root = _REPO_ROOT
    script = repo_root / "scripts" / "Send-CodexSegmentAuditSummonToGrokV2.ps1"
    if runtime_root == DEFAULT_RUNTIME and script.is_file():
        try:
            powershell_bin = shutil.which("pwsh.exe") or shutil.which("pwsh") or shutil.which("powershell.exe") or "powershell.exe"
            completed = subprocess.run(
                [
                    powershell_bin,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-RuntimeRoot",
                    str(runtime_root),
                    "-BridgeRoot",
                    str(_grok_admin_bridge_root(runtime_root)),
                    "-TaskId",
                    task_id,
                    "-SegmentId",
                    str(segment_gate.get("segment_id") or "phase0_phase1"),
                    "-Source",
                    source,
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=True,
            )
            payload = json.loads(completed.stdout)
            auth_pull = _write_audit_authorization_pull_request(
                runtime_root,
                task_id,
                segment_gate,
                source=f"{source}.script",
            )
            payload["script_ref"] = str(script)
            payload["script_called"] = True
            payload["auto_review_requested"] = True
            payload["grok_auto_review_requested"] = True
            payload["grok_reads_state_only_when_user_requests_review"] = False
            payload["user_requested_grok_review_required"] = False
            payload["audit_authorization_pull_ref"] = str(auth_pull.get("task_ref") or "")
            payload["audit_authorization_pull_latest_ref"] = str(auth_pull.get("latest_ref") or "")
            frontend_sent = payload.get("frontend_tui_sent") is True and payload.get("session_modified_after_send") is True
            payload["audit_request_status"] = "auto_audit_triggered" if frontend_sent else "pending_recoverable"
            payload["grok_bridge_availability"] = "available" if frontend_sent else "degraded"
            payload["grok_bridge_probe"] = {
                "grok_tui_reachable": bool(payload.get("pre_existing_grok_tui_found") or payload.get("used_existing_grok_tui")),
                "inbox_writable": True,
                "receive_script_ok": frontend_sent,
                "leg2_dual_delivery_ok": False,
                "probe_at": now(),
            }
            payload["grok_auto_audit_eligible"] = frontend_sent
            payload["grok_auto_audit_trigger"] = "leg1_post_activity"
            payload["user_must_carry_logs"] = False
            payload["next_recovery_action_cn"] = (
                "已触发 Grok 自动审；等待 Grok leg2 dual verdict signal。"
                if frontend_sent
                else "等 Grok 桥接恢复后自动续审；无需用户搬 JSONL。"
            )
            return payload
        except Exception as exc:
            failure = {
                "schema_version": "xinao.codex_to_grok_segment_audit_summon.error.v1",
                "generated_at": now(),
                "task_id": task_id,
                "status": "codex_segment_audit_summon_script_failed_fallback_used",
                "named_blocker": "CODEX_TO_GROK_SEGMENT_AUDIT_SUMMON_SCRIPT_FAILED",
                "script_ref": str(script),
                "error": str(exc)[:1200],
                "not_source_of_truth": True,
                "not_user_completion": True,
                "not_completion_decision": True,
                "not_execution_controller": True,
            }
            write_json(runtime_root / "state" / "codex_to_grok_segment_audit_summon" / "errors" / f"{_safe_task_file_id(task_id)}.json", failure)
    safe_task_id = _safe_task_file_id(task_id)
    generated_at = now()
    segment_id = str(segment_gate.get("segment_id") or "phase0_phase1")
    window_id = f"codex-to-grok-segment-audit-{safe_task_id}"
    summon_root = runtime_root / "state" / "codex_to_grok_segment_audit_summon"
    task_ref = summon_root / "tasks" / f"{safe_task_id}.json"
    latest_ref = summon_root / "latest.json"
    action_trace_ref = runtime_root / "state" / "action_delivery_trace" / f"{safe_task_id}.jsonl"
    event = {
        "schema_version": "xinao.action-delivery-trace-event.v1",
        "trace_id": f"codex-to-grok-segment-audit-summon-{safe_task_id}",
        "task_id": task_id,
        "safe_task_id": safe_task_id,
        "window_id": window_id,
        "event_name": "codex_to_grok_segment_audit_summon.backend_state_written",
        "status": "BACKEND_ONLY",
        "service": "temporal_codex_task_workflow",
        "timestamp": generated_at,
        "payload": {
            "delivery_mode": "backend_only_state",
            "backend_task_ref": str(task_ref),
            "grok_visible_delivery_auto_open_allowed": False,
            "grok_auto_review_requested": True,
        },
    }
    trace_ref = _append_action_delivery_trace_event(runtime_root, task_id, event)
    auth_pull = _write_audit_authorization_pull_request(
        runtime_root,
        task_id,
        segment_gate,
        source=f"{source}.summon",
    )
    payload = {
        "schema_version": "xinao.codex_to_grok_segment_audit_summon.v1",
        "sentinel": "SENTINEL:CODEX_TO_GROK_SEGMENT_AUDIT_SUMMON_BACKEND_ONLY_V1",
        "generated_at": generated_at,
        "task_id": task_id,
        "safe_task_id": safe_task_id,
        "source_task_id": task_id,
        "predecessor_task_id": task_id,
        "segment_id": segment_id,
        "status": "codex_segment_audit_backend_state_written",
        "summon_state": "segment_audit_ready_backend_state_auto_review_requested",
        "segment_audit_ready": True,
        "workflow_waiting_grok_segment_audit": True,
        "delivery_mode": "backend_only_state",
        "script_version": "legacy_backend_compat_only",
        "full_visible_delivery_mode": "disabled_by_stop_order_backend_only_state",
        "frontend_tui_sent": False,
        "session_modified_after_send": False,
        "frontend_tui_skipped": True,
        "frontend_tui_skip_reason": "stop_order_backend_only_default",
        "frontend_tui_required": False,
        "old_inbox_only_is_not_full_visible_delivery": True,
        "forbid_codex_visible_inject_for_codex_to_grok": True,
        "rescue_cockpit_channel_preserved": True,
        "prefer_existing_grok_tui": False,
        "shortcut_launch_only_if_no_valid_existing_window": False,
        "foreground_delivery_kind": "disabled_by_stop_order",
        "grok_visible_delivery_auto_open_allowed": False,
        "grok_chat_window_push_allowed": False,
        "grok_desktop_typeahead_allowed": False,
        "shortcut_launch_allowed": False,
        "grok_reads_state_only_when_user_requests_review": False,
        "user_requested_grok_review_required": False,
        "auto_review_requested": True,
        "grok_auto_review_requested": True,
        "grok_can_auto_review_when_bridge_available": True,
        "grok_bridge_unavailable_means_request_queued_not_user_handoff": True,
        "audit_request_status": "pending_recoverable",
        "grok_bridge_availability": "degraded",
        "grok_bridge_probe": {
            "grok_tui_reachable": False,
            "inbox_writable": True,
            "receive_script_ok": False,
            "leg2_dual_delivery_ok": False,
            "probe_at": generated_at,
        },
        "grok_auto_audit_eligible": False,
        "grok_auto_audit_trigger": "leg1_post_activity",
        "audit_authorization_pull_ref": str(auth_pull.get("task_ref") or ""),
        "audit_authorization_pull_latest_ref": str(auth_pull.get("latest_ref") or ""),
        "recoverable_audit_refs": {
            "summon_ref": str(task_ref),
            "grok_report_ref": "",
            "inbox_ref": str(_grok_admin_bridge_root(runtime_root) / "inbox" / "segment_audit_summon_visible.md"),
        },
        "user_must_carry_logs": False,
        "next_recovery_action_cn": "等 Grok 桥接恢复后自动续审；无需用户搬 JSONL。",
        "report_payload_policy": "backend_state_auto_grok_review_pull_no_codex_verdict",
        "default_transaction_gate": "segment_audit_backend_state_auto_grok_review_pull_then_dual_verdict",
        "bypass_allowed": False,
        "backend_task_ref": str(task_ref),
        "backend_latest_ref": str(latest_ref),
        "visible_ref": "",
        "visible_trace_ref": "",
        "action_delivery_trace_ref": str(trace_ref),
        "window_id": window_id,
        "message_kind": "segment_audit_summon_not_user_intent",
        "source": source,
        "codex_does_not_write_grok_verdict": True,
        "grok_is_not_a_execution_lock": True,
        "forbidden": ["verdict", "pass", "fail", "completion_claim", "stop"],
        "cross_check": {
            "backend_task_id": task_id,
            "action_delivery_trace_task_id": task_id,
            "action_delivery_trace_window_id": window_id,
            "same_task_id_and_window": True,
            "visible_frontend_disabled_by_stop_order": True,
        },
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    write_json(task_ref, payload)
    write_json(latest_ref, payload)
    return {
        **payload,
        "task_ref": str(task_ref),
        "latest_ref": str(latest_ref),
    }


def _grok_segment_waiting_decision_override(
    completion_decision: dict[str, Any],
    segment_gate: dict[str, Any],
) -> dict[str, Any]:
    status = str(segment_gate.get("status") or "")
    next_lane = str(segment_gate.get("next_lane") or "L1")
    hard_wait_blockers = {
        "GROK_SEGMENT_AUDIT_REQUIRED",
        "WAITING_GROK_SEGMENT_AUDIT",
        "GROK_SEGMENT_VERDICT_DUAL_DELIVERY_REQUIRED",
        "GROK_SEGMENT_AUDIT_FAILED_CONTINUE_L1",
        "GROK_SEGMENT_AUDIT_HOLD_CONTINUE_L1",
        "GROK_SEGMENT_AUDIT_VERDICT_REQUIRED",
        "GROK_180S_NO_REPLY_CODEXA_BRAIN_FALLBACK_L1",
        "CODEX_TO_GROK_SEGMENT_AUDIT_SUMMON_REQUIRED",
        "GROK_SEGMENT_AUDIT_LEG2_EVIDENCE_REQUIRED",
    }
    if status == "GROK_SEGMENT_AUDIT_PASS":
        return {
            **dict(completion_decision),
            "status": "partial",
            "stop_allowed": False,
            "named_blocker": "",
            "required_gate": "SEGMENT_AUDIT_GATE_PASS_ALLOWED",
            "next_action": f"next_lane={next_lane}",
            "not_source_of_truth": True,
            "not_user_completion": True,
            "segment_audit_status": "GROK_SEGMENT_AUDIT_PASS",
            "segment_audit_next_lane": next_lane or "L2",
        }
    if status in {
        "segment_audit_not_ready",
        "WAITING_GROK_SEGMENT_AUDIT",
        "GROK_SEGMENT_AUDIT_FAIL",
        "GROK_SEGMENT_AUDIT_HOLD",
        "GROK_SEGMENT_AUDIT_TIMEOUT_CODEXA_BRAIN_FALLBACK",
    }:
        named_blocker = str(segment_gate.get("named_blocker") or "GROK_SEGMENT_AUDIT_REQUIRED")
        if named_blocker not in hard_wait_blockers:
            named_blocker = "GROK_SEGMENT_AUDIT_REQUIRED"
        return {
            "status": "partial",
            "stop_allowed": False,
            "named_blocker": named_blocker,
            "required_gate": "SEGMENT_AUDIT_GROK_DECISION_REQUIRED",
            "next_action": f"next_lane={next_lane}",
            "segment_audit_status": status,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "segment_audit_next_lane": "L1",
        }
    return dict(completion_decision)


def _segment_completion_candidate_seen(input_payload: dict[str, Any]) -> bool:
    decision = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
    worker = input_payload.get("worker_dispatch_evidence") if isinstance(input_payload.get("worker_dispatch_evidence"), dict) else {}
    status = str(decision.get("status") or "")
    if input_payload.get("segment_complete") is True or input_payload.get("segment_audit_ready") is True:
        return True
    if status == "complete_allowed":
        return True
    worker_ok = bool(l1_l2_segment_gate._worker_evidence_success(worker))
    return bool(worker_ok and status == "partial")


def _augment_conflict_worker_evidence_from_task_result(
    runtime_root: pathlib.Path,
    worker: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(worker, dict):
        return {}
    worker_task_id = str(worker.get("worker_task_id") or worker.get("task_id") or worker.get("codex_worker_task_id") or "")
    named_blocker = str(worker.get("named_blocker") or "").strip()
    if named_blocker != "CODEX_ACTIVATOR_TASK_ID_CONFLICT" or not worker_task_id:
        return worker
    result_path = runtime_root / "state" / "codex_results" / worker_task_id / "result.json"
    existing = read_json(result_path, {})
    if not isinstance(existing, dict) or existing.get("ok") is not True:
        return worker
    merged = {**worker, **existing}
    merged["worker_task_id"] = worker_task_id
    merged["task_id"] = worker_task_id
    merged["result_path"] = str(result_path)
    if not merged.get("jsonl_path"):
        jsonl_path = runtime_root / "state" / "codex_results" / worker_task_id / "codex-events.jsonl"
        if jsonl_path.is_file():
            merged["jsonl_path"] = str(jsonl_path)
    merged["named_blocker"] = str(existing.get("named_blocker") or "")
    merged["replayed_existing_worker_result_after_task_id_conflict"] = True
    return merged


def _materialize_segment_audit_ready_if_needed(runtime_root: pathlib.Path, task_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    if not _segment_completion_candidate_seen(input_payload):
        worker_candidate = input_payload.get("worker_dispatch_evidence") if isinstance(input_payload.get("worker_dispatch_evidence"), dict) else {}
        worker_candidate = _augment_conflict_worker_evidence_from_task_result(runtime_root, worker_candidate)
        decision_candidate = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
        if str(decision_candidate.get("status") or "") not in {"partial", "complete_allowed"} or not l1_l2_segment_gate._worker_evidence_success(worker_candidate):
            return {}
        input_payload = {**input_payload, "worker_dispatch_evidence": worker_candidate}
    gate_task = runtime_root / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json"
    existing_task = read_json(gate_task, {})
    worker = input_payload.get("worker_dispatch_evidence") if isinstance(input_payload.get("worker_dispatch_evidence"), dict) else {}
    worker = _augment_conflict_worker_evidence_from_task_result(runtime_root, worker)
    decision = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
    incoming_worker_task = str(worker.get("worker_task_id") or worker.get("task_id") or worker.get("codex_worker_task_id") or "")
    incoming_segment_id = str(
        input_payload.get("segment_id")
        or input_payload.get("phase_scope")
        or worker.get("phase_scope")
        or "phase0_phase1"
    )
    existing_worker_task = str(existing_task.get("worker_task_id") or "")
    existing_segment_id = str(existing_task.get("segment_id") or "")
    existing_pass_reused_for_old_segment = (
        existing_task.get("segment_audit_ready") is True
        and str(existing_task.get("status") or "") == "GROK_SEGMENT_AUDIT_PASS"
        and bool(incoming_worker_task)
        and (
            incoming_worker_task != existing_worker_task
            or (bool(existing_segment_id) and incoming_segment_id != existing_segment_id)
        )
    )
    if existing_task.get("segment_audit_ready") is True and not existing_pass_reused_for_old_segment:
        return existing_task
    return l1_l2_segment_gate.write_segment_complete_ready_gate(
        runtime_root=runtime_root,
        task_id=task_id,
        segment_id=incoming_segment_id,
        worker_evidence=worker,
        completion_decision=decision,
        source_activity="segment_audit_gate_activity",
    )


def _write_grok_segment_audit_request_if_ready(
    runtime_root: pathlib.Path,
    task_id: str,
    segment_gate: dict[str, Any],
) -> dict[str, Any]:
    if not (
        segment_gate.get("segment_audit_ready") is True
        and segment_gate.get("workflow_waiting_grok_segment_audit") is True
    ):
        return {}
    generated_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
    auth_pull = _write_audit_authorization_pull_request(
        runtime_root,
        task_id,
        segment_gate,
        source="grok_segment_audit_request",
    )
    payload = {
        "schema_version": "xinao.grok_segment_audit_request.v1",
        "generated_at": generated_at,
        "task_id": task_id,
        "segment_id": str(segment_gate.get("segment_id") or "phase0_phase1"),
        "segment_audit_ready": True,
        "workflow_waiting_grok": True,
        "workflow_waiting_grok_segment_audit": True,
        "segment_audit_status": str(segment_gate.get("status") or "WAITING_GROK_SEGMENT_AUDIT"),
        "request_state": "auto_pull_requested_waiting_full_dual_delivery",
        "audit_authorization_pull_requested": True,
        "audit_authorization_pull_ref": str(auth_pull.get("task_ref") or ""),
        "audit_authorization_pull_latest_ref": str(auth_pull.get("latest_ref") or ""),
        "auto_review_requested": True,
        "grok_auto_review_requested": True,
        "grok_can_auto_review_when_bridge_available": True,
        "grok_bridge_unavailable_means_request_queued_not_user_handoff": True,
        "audit_request_status": "pending_recoverable",
        "grok_bridge_availability": "degraded",
        "grok_bridge_probe": {
            "grok_tui_reachable": False,
            "inbox_writable": True,
            "receive_script_ok": False,
            "leg2_dual_delivery_ok": False,
            "probe_at": generated_at,
        },
        "grok_auto_audit_eligible": False,
        "grok_auto_audit_trigger": "leg1_post_activity",
        "notify_v1_default_retired": True,
        "notify_v1_rescue_only": True,
        "notify_v1_default_mainline": False,
        "used_as_success_signal": False,
        "notify_pending_as_mainline": False,
        "not_leg1": True,
        "not_full_visible": True,
        "release_requires_bidirectional_dual_delivery_full_ring": True,
        "grok_notified": True,
        "notification_mode": "auto_review_pull_request_no_codex_verdict",
        "next_human_action_cn": "",
        "next_machine_action_cn": "系统已自动拉取 Grok 审核/授权；Grok 可在桥接可用时自动审 evidence 并回写 dual verdict；notify v1 只作 rescue。",
        "next_recovery_action_cn": "等 Grok 桥接恢复后自动续审；无需用户搬 JSONL。",
        "user_must_copy_tui": False,
        "user_must_carry_logs": False,
        "user_requested_grok_review_required": False,
        "grok_chat_window_push_allowed": False,
        "codex_cannot_push_grok_chat": True,
        "automatic_verdict_allowed": False,
        "verdict": "",
        "grok_verdict": "",
        "verdict_delivery_mode": "",
        "not_grok_verdict": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("grok_segment_audit_request_read_model"),
    }
    request_dir = runtime_root / "state" / "grok_segment_audit_request"
    task_ref = request_dir / "tasks" / f"{task_id}.json"
    latest_ref = request_dir / "latest.json"
    write_json(task_ref, payload)
    write_json(latest_ref, payload)
    return {
        **payload,
        "request_ref": str(task_ref),
        "latest_ref": str(latest_ref),
        "request_task_ref": str(task_ref),
        "request_latest_ref": str(latest_ref),
    }


def _sync_current_owner_segment_audit_state(runtime_root: pathlib.Path, task_id: str, segment_gate: dict[str, Any]) -> None:
    owner_latest = runtime_root / "state" / "current_task_owner" / "latest.json"
    owner_task = runtime_root / "state" / "current_task_owner" / f"{task_id}.json"
    owner = read_json(owner_task, {})
    if not isinstance(owner, dict) or str(owner.get("task_id") or "") != str(task_id):
        latest_owner = read_json(owner_latest, {})
        owner = latest_owner if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == str(task_id) else {"task_id": task_id}
    temporal_latest = read_json(runtime_root / "state" / "temporal_codex_task_workflow" / "latest.json", {})
    if isinstance(temporal_latest, dict) and str(temporal_latest.get("task_id") or "") == str(task_id):
        temporal_owner = temporal_latest.get("current_task_owner") if isinstance(temporal_latest.get("current_task_owner"), dict) else {}
        if temporal_latest.get("worker_service_polling") is True or temporal_owner.get("worker_service_polling") is True:
            owner["worker_service_polling"] = True
            owner["worker_service_evidence"] = (
                temporal_latest.get("worker_service_evidence")
                if isinstance(temporal_latest.get("worker_service_evidence"), dict)
                else temporal_owner.get("worker_service_evidence", {})
            )
    owner.update({
        "segment_audit_ready": bool(segment_gate.get("segment_audit_ready")),
        "workflow_waiting_grok_segment_audit": bool(segment_gate.get("workflow_waiting_grok_segment_audit")),
        "grok_verdict": str(segment_gate.get("grok_verdict") or ""),
        "verdict_delivery_mode": str(segment_gate.get("verdict_delivery_mode") or ""),
        "segment_audit_status": str(segment_gate.get("status") or ""),
        "segment_audit_next_lane": str(segment_gate.get("next_lane") or "L1"),
        "segment_audit_gate_ref": str(segment_gate.get("gate_task_ref") or segment_gate.get("gate_latest_ref") or ""),
        "grok_gate_ref": str(segment_gate.get("grok_gate_ref") or ""),
        "audit_authorization_pull_requested": segment_gate.get("audit_authorization_pull_requested") is True,
        "audit_authorization_pull_ref": str(segment_gate.get("audit_authorization_pull_ref") or ""),
        "audit_authorization_pull_latest_ref": str(segment_gate.get("audit_authorization_pull_latest_ref") or ""),
        "auto_review_requested": segment_gate.get("auto_review_requested") is True,
        "grok_auto_review_requested": segment_gate.get("grok_auto_review_requested") is True,
        "grok_can_auto_review_when_bridge_available": segment_gate.get("grok_can_auto_review_when_bridge_available") is True,
        "grok_bridge_unavailable_means_request_queued_not_user_handoff": segment_gate.get("grok_bridge_unavailable_means_request_queued_not_user_handoff") is True,
        "backend_only_verdict_allowed": False,
        "completion_claim_allowed": False,
        "stop_allowed_without_grok_pass": False,
        "not_user_completion": True,
        "not_completion_decision": True,
    })
    if str(segment_gate.get("status") or "") == "GROK_SEGMENT_AUDIT_PASS":
        worker_task_id = f"{task_id}.segment-pass.L2.worker"
        worker_jsonl = runtime_root / "state" / "codex_results" / worker_task_id / "codex-events.jsonl"
        worker_result = read_json(runtime_root / "state" / "codex_results" / worker_task_id / "result.json", {})
        if worker_jsonl.is_file() and isinstance(worker_result, dict) and worker_result.get("ok") is True:
            owner.update({
                "segment_pass_must_dispatch_next_bounded_worker": False,
                "segment_pass_phase_exit_checker_dispatched": True,
                "same_workflow_next_worker_dispatched": True,
                "same_workflow_next_worker_task_id": worker_task_id,
                "same_workflow_next_worker_jsonl_path": str(worker_jsonl),
                "mainline_next_hop": SEGMENT_PASS_NEXT_BOUNDED_WORKER_HOP,
            })
    write_json(owner_task, owner)
    latest_owner = read_json(owner_latest, {})
    if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == str(task_id):
        write_json(owner_latest, owner)


def _sync_l1_l2_segment_gate_evaluation(runtime_root: pathlib.Path, task_id: str, segment_gate: dict[str, Any]) -> None:
    gate_dir = runtime_root / "state" / "l1_l2_segment_gate"
    gate_task = gate_dir / "tasks" / f"{task_id}.json"
    gate_latest = gate_dir / "latest.json"
    existing = read_json(gate_task, {})
    if not isinstance(existing, dict) or str(existing.get("task_id") or "") != str(task_id):
        existing = {"schema_version": "xinao.l1_l2_segment_gate.v1", "task_id": task_id}
    evaluated_status = str(segment_gate.get("status") or existing.get("status") or "")
    persisted_status = evaluated_status
    if (
        evaluated_status == "WAITING_GROK_SEGMENT_AUDIT"
        and str(existing.get("status") or "") == "SEGMENT_COMPLETE_WAITING_GROK_HOTPATH_READY"
    ):
        persisted_status = str(existing.get("status") or "")
    merged = {
        **existing,
        "generated_at": now(),
        "task_id": task_id,
        "segment_id": str(segment_gate.get("segment_id") or existing.get("segment_id") or "phase0_phase1"),
        "worker_task_id": str(segment_gate.get("worker_task_id") or existing.get("worker_task_id") or ""),
        "worker_jsonl_path": str(segment_gate.get("worker_jsonl_path") or existing.get("worker_jsonl_path") or ""),
        "status": persisted_status,
        "segment_audit_ready": bool(segment_gate.get("segment_audit_ready")),
        "workflow_waiting_grok_segment_audit": bool(segment_gate.get("workflow_waiting_grok_segment_audit")),
        "grok_verdict": str(segment_gate.get("grok_verdict") or ""),
        "verdict_delivery_mode": str(segment_gate.get("verdict_delivery_mode") or ""),
        "dual_visible_and_backend_verdict": segment_gate.get("dual_visible_and_backend_verdict") is True,
        "codex_to_grok_segment_audit_summon_valid": segment_gate.get("codex_to_grok_segment_audit_summon_valid") is True,
        "codex_to_grok_segment_audit_summon_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_ref") or ""),
        "grok_segment_verdict_leg2_valid": segment_gate.get("grok_segment_verdict_leg2_valid") is True,
        "grok_segment_verdict_leg2_evidence": segment_gate.get("grok_segment_verdict_leg2_evidence") if isinstance(segment_gate.get("grok_segment_verdict_leg2_evidence"), dict) else {},
        "grok_waiting_does_not_block_continuation": segment_gate.get("grok_waiting_does_not_block_continuation") is True,
        "grok_segment_verdict_gates_completion_stop_l2_only": segment_gate.get("grok_segment_verdict_gates_completion_stop_l2_only") is True,
        "grok_segment_verdict_wait_blocking": segment_gate.get("grok_segment_verdict_wait_blocking") is True,
        "audit_authorization_pull_requested": segment_gate.get("audit_authorization_pull_requested") is True,
        "audit_authorization_pull_ref": str(segment_gate.get("audit_authorization_pull_ref") or ""),
        "audit_authorization_pull_latest_ref": str(segment_gate.get("audit_authorization_pull_latest_ref") or ""),
        "auto_review_requested": segment_gate.get("auto_review_requested") is True,
        "grok_auto_review_requested": segment_gate.get("grok_auto_review_requested") is True,
        "grok_can_auto_review_when_bridge_available": segment_gate.get("grok_can_auto_review_when_bridge_available") is True,
        "grok_bridge_unavailable_means_request_queued_not_user_handoff": segment_gate.get("grok_bridge_unavailable_means_request_queued_not_user_handoff") is True,
        "bidirectional_dual_delivery_full_ring_valid": segment_gate.get("bidirectional_dual_delivery_full_ring_valid") is True,
        "next_lane": str(segment_gate.get("next_lane") or "L1"),
        "l2_release_allowed": segment_gate.get("l2_release_allowed") is True,
        "named_blocker": str(segment_gate.get("named_blocker") or ""),
        "completion_claim_allowed": False,
        "stop_allowed": False,
        "backend_only_verdict_allowed": False,
        "worker_pass_as_l2": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
    }
    write_json(gate_task, merged)
    write_json(gate_latest, merged)


def _read_grok_segment_audit_request(runtime_root: pathlib.Path, task_id: str) -> dict[str, Any]:
    request_path = runtime_root / "state" / "grok_segment_audit_request" / "tasks" / f"{task_id}.json"
    payload = read_json(request_path, {})
    if payload:
        payload.setdefault("request_ref", str(request_path))
    return payload


def _safe_temporal_json(command: list[str]) -> tuple[bool, dict[str, Any], str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    except Exception as exc:
        return False, {"error": str(exc)}, "temporal_cli_invocation_failed"
    if completed.returncode != 0:
        return False, {
            "stderr": (completed.stderr or completed.stdout)[-2000:],
            "returncode": completed.returncode,
        }, "temporal_cli_non_zero_exit"
    try:
        return True, json.loads(completed.stdout or "{}"), "temporal_cli_json_ok"
    except json.JSONDecodeError as exc:
        return False, {"stderr": completed.stdout[:2000], "error": str(exc)}, "temporal_cli_json_invalid"


def temporal_workflow_describe(*, workflow_id: str, run_id: str, address: str = TEMPORAL_ADDRESS) -> dict[str, Any]:
    command = [
        "temporal",
        "workflow",
        "describe",
        "--address",
        address,
        "--workflow-id",
        workflow_id,
        "--run-id",
        run_id,
        "--output",
        "json",
    ]
    ok, payload, status = _safe_temporal_json(command)
    payload["cli_status"] = status
    payload["cli_ok"] = ok
    return payload


def temporal_workflow_show(*, workflow_id: str, run_id: str, address: str = TEMPORAL_ADDRESS) -> dict[str, Any]:
    command = [
        "temporal",
        "workflow",
        "show",
        "--address",
        address,
        "--workflow-id",
        workflow_id,
        "--run-id",
        run_id,
        "--output",
        "json",
    ]
    ok, payload, status = _safe_temporal_json(command)
    payload["cli_status"] = status
    payload["cli_ok"] = ok
    return payload


def _extract_temporal_events(show_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = show_payload.get("events")
    if isinstance(events, list):
        return events
    history = show_payload.get("history")
    if isinstance(history, dict):
        nested_events = history.get("events")
        if isinstance(nested_events, list):
            return nested_events
    return []


def _extract_workflow_status(show_payload: dict[str, Any]) -> str:
    info = show_payload.get("workflowExecutionInfo")
    if isinstance(info, dict):
        status = info.get("status")
        if status:
            return str(status)
        status = info.get("status_code")
        if status:
            return str(status)
    return ""


def _derive_workflow_open_from_events(events: list[dict[str, Any]], status: str) -> bool:
    return status in {
        "RUNNING",
        "running",
        "WorkflowExecutionStatus_RUNNING",
        "WORKFLOW_EXECUTION_STATUS_RUNNING",
        "workflowexecutionstatusrunning",
    } or any(
        str(event.get("eventType") or event.get("event_type", "")).endswith("Started") and str(event.get("eventType") or event.get("event_type", "")).startswith("WorkflowExecution")
        for event in events
    ) and not any(
        str(event.get("eventType") or event.get("event_type", "")).endswith(term)
        for event in events
        for term in ("WorkflowExecutionCompleted", "WorkflowExecutionFailed", "WorkflowExecutionTerminated", "WorkflowExecutionTimedOut", "WorkflowExecutionCanceled", "WorkflowExecutionContinuedAsNew")
    )


def _verify_temporal_workflow_history(
    runtime_root: pathlib.Path,
    task_id: str,
    workflow_id: str,
    workflow_run_id: str,
) -> tuple[dict[str, Any], str]:
    evidence_dir = runtime_root / "state" / "task_bound_evidence" / task_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    describe_ref = evidence_dir / "temporal_describe.json"
    show_ref = evidence_dir / "temporal_show.json"
    summary_ref = evidence_dir / "g2_temporal_server_verification.json"
    describe_payload = temporal_workflow_describe(workflow_id=workflow_id, run_id=workflow_run_id)
    show_payload = temporal_workflow_show(workflow_id=workflow_id, run_id=workflow_run_id)
    write_json(describe_ref, describe_payload)
    write_json(show_ref, show_payload)
    events = _extract_temporal_events(show_payload)
    event_count = len(events)
    status = _extract_workflow_status(show_payload).strip()
    workflow_open = _derive_workflow_open_from_events(events, status)
    workflow_completed = any(
        str(event.get("eventType") or event.get("event_type", "")).endswith(term)
        for event in events
        for term in ("WorkflowExecutionCompleted", "WorkflowExecutionFailed", "WorkflowExecutionTerminated", "WorkflowExecutionTimedOut")
    )
    started_seen = any(
        str(event.get("eventType") or event.get("event_type", "")).endswith("WorkflowExecutionStarted")
        for event in events
    )
    activity_scheduled_count = sum(
        1 for event in events
        if str(event.get("eventType") or event.get("event_type", "")).endswith("ActivityTaskScheduled")
    )
    activity_started_count = sum(
        1 for event in events
        if str(event.get("eventType") or event.get("event_type", "")).endswith("ActivityTaskStarted")
    )
    activity_completed_count = sum(
        1 for event in events
        if str(event.get("eventType") or event.get("event_type", "")).endswith("ActivityTaskCompleted")
    )
    timer_started_seen = any(
        str(event.get("eventType") or event.get("event_type", "")).endswith("TimerStarted")
        for event in events
    )
    terminal_event_seen = any(
        str(event.get("eventType") or event.get("event_type", "")).endswith(term)
        for event in events
        for term in ("Completed", "Failed", "TimedOut", "Terminated", "Cancelled", "ContinuedAsNew")
    )
    server_history_ok = bool(describe_payload.get("cli_ok")) and bool(show_payload.get("cli_ok"))
    verification_level = (
        VERIFICATION_LEVEL_WORKFLOW_OPEN
        if workflow_open and not workflow_completed
        else VERIFICATION_LEVEL_SERVER_HISTORY
        if server_history_ok
        else VERIFICATION_LEVEL_READ_MODEL
    )
    summary = {
        "schema_version": "xinao.g2_temporal_server_verification.v1",
        "task_id": task_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "generated_at": now(),
        "execution_mode": "temporal_server",
        "local_run_observed": False,
        "worker_service_polling": False,
        "describe_ref": str(describe_ref),
        "show_ref": str(show_ref),
        "describe_cli_ok": bool(describe_payload.get("cli_ok")),
        "show_cli_ok": bool(show_payload.get("cli_ok")),
        "server_bound": bool(describe_payload.get("cli_ok")) and bool(show_payload.get("cli_ok")),
        "workflow_open": bool(workflow_open),
        "workflow_completed_partial": bool(workflow_open and not workflow_completed),
        "workflow_completed": bool(workflow_completed),
        "verification_level": verification_level,
        "verification_requirements": {
            "server_bound": bool(describe_payload.get("cli_ok")) and bool(show_payload.get("cli_ok")),
            "workflow_started_seen": bool(started_seen),
            "activity_events_seen": bool(activity_scheduled_count or activity_started_count or activity_completed_count),
            "workflow_open": bool(workflow_open),
            "history_complete_no_errors": bool(describe_payload.get("cli_ok")) and bool(show_payload.get("cli_ok")),
        },
        "event_count": int(event_count),
        "workflow_started_seen": bool(started_seen),
        "activity_scheduled_count": int(activity_scheduled_count),
        "activity_started_count": int(activity_started_count),
        "activity_completed_count": int(activity_completed_count),
        "timer_started_seen": bool(timer_started_seen),
        "terminal_event_seen": bool(terminal_event_seen),
        "status": status or "UNKNOWN",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
    }
    write_json(summary_ref, summary)
    summary["summary_ref"] = str(summary_ref)
    return summary, verification_level


def call_codex_activator(payload: dict[str, Any], *, timeout_sec: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        CODEX_ACTIVATOR_URL + "/codex/exec",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_sec + 30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[-2000:]}
        return {
            "ok": False,
            "status": "FAIL",
            "http_status": exc.code,
            "named_blocker": payload.get("named_blocker", "CODEX_ACTIVATOR_HTTP_ERROR"),
            "activator_response": payload,
        }
    except OSError as exc:
        return {
            "ok": False,
            "status": "FAIL",
            "named_blocker": "CODEX_ACTIVATOR_UNREACHABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:1200],
        }


def claim_activity_checkpoint(task_id: str, activity_name: str, runtime_root: pathlib.Path) -> dict[str, Any]:
    payload = builder.build_claim_payload(
        task_id=task_id,
        mode="partial",
        user_goal=f"Temporal activity checkpoint: {activity_name}",
        next_action=f"Continue Temporal workflow after {activity_name}; workflow completed is not user completion.",
        runtime_root=runtime_root,
    )
    decision = codex_default_task_runner.local_completion_claim(payload)
    claim_path = builder.write_claim_payload(
        payload=payload,
        runtime_root=runtime_root,
        output_path=runtime_root / "state" / "completion_claim_payloads" / f"{task_id}_{activity_name}.json",
    )
    return {
        "activity": activity_name,
        "claim_path": str(claim_path),
        "completion_decision": decision,
        "stop_allowed": decision.get("stop_allowed") is True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("derived_activity_checkpoint"),
    }


@activity.defn
async def bind_task_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    checkpoint = claim_activity_checkpoint(input_payload["task_id"], "bind_task", runtime_root)
    return {
        "activity": "bind_task",
        "status": "activity_gate_checked",
        "task_id": input_payload["task_id"],
        "source_goal_ref": source_goal_ref(input_payload.get("user_goal", "")),
        **checkpoint,
    }


@activity.defn
async def run_langgraph_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    if input_payload.get("simulate_non_retryable") == "object_replacement":
        raise RuntimeError("XINAO_OBJECT_REPLACEMENT_DENIED")
    graph_result = await asyncio.to_thread(
        langgraph_task_runner.run_task_graph,
        task_id=input_payload["task_id"],
        user_goal=input_payload.get("user_goal", ""),
        mode=input_payload.get("mode", "partial"),
        runtime_root=runtime_root,
        allow_complete_fixture=bool(input_payload.get("allow_complete_fixture")),
        source_refs=list(input_payload.get("source_refs") or []),
        runtime_subject_loop_required=list(input_payload.get("runtime_subject_loop_required") or []),
        root_repair_constraints=list(input_payload.get("root_repair_constraints") or []),
        minimum_reality_contact_required=bool(input_payload.get("minimum_reality_contact_required", True)),
        no_new_parallel_control_surface=bool(input_payload.get("no_new_parallel_control_surface", True)),
        compiled_task_object=dict(input_payload.get("compiled_task_object") or {}),
        promote_latest=input_payload.get(
            "promote_langgraph_latest",
            input_payload.get("promote_current_task_owner_latest", True),
        ) is not False,
    )
    claim_payload = graph_result.get("completion_claim_payload")
    if isinstance(claim_payload, dict):
        claim_payload["current_task_owner"] = current_task_owner_from_input(
            input_payload,
            live_temporal=bool(input_payload.get("workflow_run_id")),
        )
    checkpoint = claim_activity_checkpoint(input_payload["task_id"], "run_langgraph", runtime_root)
    return {
        "activity": "run_langgraph",
        "status": "activity_gate_checked",
        "graph_result": graph_result,
        **checkpoint,
    }


@activity.defn
async def completion_claim_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    graph_result = input_payload["graph_result"]
    claim_payload = dict(graph_result.get("completion_claim_payload") or {})
    owner = input_payload.get("current_task_owner") or {}
    claim_path = ""
    if claim_payload and owner:
        graph_binding = task_object_binding_from_payload({"graph_result": graph_result})
        if not owner.get("compiled_task_object_sha256"):
            owner["compiled_task_object_sha256"] = graph_binding["compiled_task_object_sha256"]
        if not owner.get("source_refs_sha256"):
            owner["source_refs_sha256"] = graph_binding["source_refs_sha256"]
        if not owner.get("acceptance_contract"):
            owner["acceptance_contract"] = graph_binding["acceptance_contract"]
        claim_payload["current_task_owner"] = owner
        runtime_root_raw = input_payload.get("runtime_root")
        runtime_root = pathlib.Path(str(runtime_root_raw)) if runtime_root_raw else DEFAULT_RUNTIME
        if runtime_root_raw:
            persist_current_task_binding(
                runtime_root,
                owner,
                {
                    "task_id": str(owner.get("task_id") or claim_payload.get("task_object_id") or ""),
                    "user_goal": str(claim_payload.get("task_object_id") or ""),
                    "promote_current_task_owner_latest": input_payload.get("promote_current_task_owner_latest", True) is not False,
                },
            )
            claim_path = str(builder.write_claim_payload(
                payload=claim_payload,
                runtime_root=runtime_root,
            ))
        decision = codex_default_task_runner.local_completion_claim(claim_payload, runtime_root)
        segment_gate = l1_l2_segment_gate.evaluate_task_l1_l2_segment_gate(runtime_root, str(owner.get("task_id") or claim_payload.get("task_object_id") or input_payload["task_id"]))
        decision = _grok_segment_waiting_decision_override(decision, segment_gate)
    else:
        decision = graph_result["completion_decision"]
    return {
        "activity": "completion_claim",
        "status": "activity_gate_checked",
        "required_endpoint": "/completion/claim",
        "completion_decision": decision,
        "claim_payload": claim_payload or graph_result.get("completion_claim_payload"),
        "claim_path": claim_path,
        "current_task_owner_bound": bool(owner),
        "stop_allowed": decision.get("stop_allowed") is True,
    }


@activity.defn
async def codex_worker_turn_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    if not input_payload.get("execute_codex_worker", False):
        named_blocker = str(input_payload.get("named_blocker") or "")
        if named_blocker:
            return {
                "activity": "codex_worker_turn",
                "status": "activity_blocked",
                "named_blocker": named_blocker,
                "assignment_missing_fields": list(input_payload.get("assignment_missing_fields") or []),
                "not_source_of_truth": True,
                "not_user_completion": True,
                "authority_boundary": authority_boundary("codex_worker_turn_blocked_readback"),
                "required_for_production_completion": True,
            }
        return {
            "activity": "codex_worker_turn",
            "status": "skipped_until_route_requires_codex_execution",
            "not_source_of_truth": True,
            "not_user_completion": True,
            "authority_boundary": authority_boundary("codex_worker_turn_skipped_readback"),
            "required_for_production_completion": True,
        }
    expected_marker = str(input_payload.get("codex_worker_expected_marker") or TASK_BOUND_CODEX_WORKER_MARKER)
    worker_prompt = str(input_payload.get("codex_worker_prompt") or "").strip()
    worker_task_id = str(input_payload.get("codex_worker_task_id") or f"{input_payload['task_id']}.codex-worker.{run_id()}")
    if worker_prompt:
        timeout_sec = int(input_payload.get("codex_worker_timeout_sec") or 300)
        workspace_hint = str(input_payload.get("workspace_hint") or input_payload.get("repo_root") or "").strip()
        route_profile = str(input_payload.get("route_profile") or os.environ.get("XINAO_ROUTE_PROFILE") or "").strip()
        task_id_text = str(input_payload.get("task_id") or "")
        default_codex_target = "codex-s" if route_profile == "seed_cortex_phase0" or "seed_cortex" in task_id_text else "codex-a"
        codex_worker_target = str(input_payload.get("codex_worker_target") or default_codex_target)
        if route_profile == "seed_cortex_phase0" and codex_worker_target != "codex-s" and input_payload.get("legacy_reference_only") is not True:
            return {
                "activity": "codex_worker_turn",
                "status": "activity_blocked",
                "named_blocker": "CODEX_S_TEMPORAL_REJECTS_NON_S_TARGET_WITHOUT_LEGACY_REFERENCE_ONLY",
                "target": codex_worker_target,
                "route_profile": route_profile,
                "not_source_of_truth": True,
                "not_user_completion": True,
                "not_completion_decision": True,
                "authority_boundary": authority_boundary("codex_s_temporal_target_guard"),
                "required_next_action": "dispatch codex-s or mark the request legacy_reference_only",
            }
        segment_boundary_headless = bool(
            input_payload.get("worker_final_user_visible_allowed") is not True
            or input_payload.get("segment_boundary_headless")
            or input_payload.get("segment_pass_next_worker_required")
            or input_payload.get("human_egress_route") == "grok_report_only"
        )
        activator_payload = {
            "task_id": worker_task_id,
            "target": codex_worker_target,
            "route_profile": route_profile or ("seed_cortex_phase0" if codex_worker_target == "codex-s" else "legacy_reference_only"),
            "result_role": "task_bound_worker_evidence_only_requires_fan_in_acceptance",
            "not_user_completion": True,
            "not_completion_decision": True,
            "prompt": worker_prompt,
            "timeout_sec": timeout_sec,
            "wait": True,
            "trace_id": f"xinao-temporal-worker-{worker_task_id}",
            "action_decision": "task_bound_codex_worker_turn_required_by_route_gate",
            "dispatch_strategy": "temporal_codex_task_workflow_to_codex_activator",
            "headless_worker": segment_boundary_headless,
            "segment_boundary_headless": segment_boundary_headless,
            "human_egress_policy": "grok_report_only" if segment_boundary_headless else "",
            "worker_final_user_visible_allowed": False if segment_boundary_headless else True,
            "mature_execution_carrier": str(input_payload.get("mature_execution_carrier") or MATURE_EXECUTION_CARRIER),
            "mature_execution_carrier_refs": list(input_payload.get("mature_execution_carrier_refs") or MATURE_EXECUTION_CARRIER_REFS),
            "worker_evidence_contract": str(input_payload.get("worker_evidence_contract") or "task_bound_codex_exec_jsonl"),
            "segment_pass_checker_default": input_payload.get("segment_pass_checker_default") is True,
            "worker_kind": str(input_payload.get("worker_kind") or ""),
            "phase_scope": str(input_payload.get("phase_scope") or ""),
            "worker_assignment_ref": str(input_payload.get("worker_assignment_ref") or ""),
            "phase_execution": input_payload.get("phase_execution") if isinstance(input_payload.get("phase_execution"), dict) else {},
            "work_package": input_payload.get("work_package") if isinstance(input_payload.get("work_package"), dict) else {},
            "verification": input_payload.get("verification") if isinstance(input_payload.get("verification"), (list, dict)) else [],
            "assignment_driven_dispatch": input_payload.get("assignment_driven_dispatch") is True,
            "implementation_worker_required": input_payload.get("implementation_worker_required") is True,
            "continue_same_task_signal_worker_required": input_payload.get("continue_same_task_signal_worker_required") is True,
            "segment_boundary_policy": str(input_payload.get("segment_boundary_policy") or ""),
            "grok_audit_policy": str(input_payload.get("grok_audit_policy") or ""),
            "grok_waiting_does_not_block_continuation": input_payload.get("grok_waiting_does_not_block_continuation") is True,
        }
        if workspace_hint:
            activator_payload["workspace_hint"] = workspace_hint
            activator_payload["repo_root"] = workspace_hint
        existing_result_ref = runtime_root / "state" / "codex_results" / worker_task_id / "result.json"
        existing_result = read_json(existing_result_ref, {})
        reused_existing_task_result = bool(
            existing_result.get("ok") is True
            and str(existing_result.get("task_id") or "") == worker_task_id
        )
        result_payload = (
            {**existing_result, "reused_existing_task_result": True}
            if reused_existing_task_result
            else await asyncio.to_thread(call_codex_activator, activator_payload, timeout_sec=timeout_sec)
        )
        result_detail = _activator_detail_payload(result_payload)
        final_path = pathlib.Path(str(result_detail.get("final_path", ""))) if result_detail.get("final_path") else pathlib.Path()
        raw_final_path = pathlib.Path(str(result_detail.get("raw_final_path", ""))) if result_detail.get("raw_final_path") else final_path
        jsonl_path = pathlib.Path(str(result_detail.get("jsonl_path", ""))) if result_detail.get("jsonl_path") else pathlib.Path()
        final_tail = _read_text_if_exists(raw_final_path, limit=4000)
        marker_seen = expected_marker in final_tail
        jsonl_nonempty = _path_exists_and_nonempty(jsonl_path)
        task_bound = result_detail.get("task_id") == worker_task_id
        activator_ok = result_payload.get("ok") is True or result_detail.get("ok") is True
        status = "activity_gate_checked" if activator_ok and marker_seen and jsonl_nonempty and task_bound else "activity_blocked"
        observe = jobs_json_observe_from_worker_result(result_detail)
        failure_classification = (
            result_detail.get("failure_classification")
            if isinstance(result_detail.get("failure_classification"), dict)
            else (
                result_payload.get("failure_classification")
                if isinstance(result_payload.get("failure_classification"), dict)
                else {}
            )
        )
        blocker = ""
        if status != "activity_gate_checked":
            blocker = str(result_payload.get("named_blocker") or result_detail.get("named_blocker") or "")
            if not task_bound:
                blocker = blocker or "TASK_BOUND_CODEX_WORKER_RESULT_TASK_ID_MISMATCH"
            elif not jsonl_nonempty:
                blocker = blocker or "TASK_BOUND_CODEX_WORKER_JSONL_MISSING"
            elif not marker_seen:
                blocker = blocker or "TASK_BOUND_CODEX_WORKER_MARKER_MISSING"
            else:
                blocker = blocker or "TASK_BOUND_CODEX_WORKER_FAILED"
        activity_result = {
            "activity": "codex_worker_turn",
            "status": status,
            "command_surface": "Temporal activity -> codex_activator -> codex exec --json",
            "mature_execution_carrier": str(input_payload.get("mature_execution_carrier") or MATURE_EXECUTION_CARRIER),
            "mature_execution_carrier_refs": list(input_payload.get("mature_execution_carrier_refs") or MATURE_EXECUTION_CARRIER_REFS),
            "worker_evidence_contract": str(input_payload.get("worker_evidence_contract") or "task_bound_codex_exec_jsonl"),
            "segment_pass_checker_default": input_payload.get("segment_pass_checker_default") is True,
            "task_id": input_payload["task_id"],
            "worker_task_id": worker_task_id,
            "task_bound_worker": task_bound,
            "segment_pass_next_worker_required": bool(input_payload.get("segment_pass_next_worker_required")),
            "implementation_worker_required": bool(input_payload.get("implementation_worker_required")),
            "continue_same_task_signal_worker_required": bool(input_payload.get("continue_same_task_signal_worker_required")),
            "worker_kind": str(input_payload.get("worker_kind") or ""),
            "phase_scope": str(input_payload.get("phase_scope") or ""),
            "dispatch_strategy": str(input_payload.get("dispatch_strategy") or "temporal_codex_task_workflow_to_codex_activator"),
            "worker_assignment_ref": str(input_payload.get("worker_assignment_ref") or ""),
            "phase_execution": input_payload.get("phase_execution") if isinstance(input_payload.get("phase_execution"), dict) else {},
            "work_package": input_payload.get("work_package") if isinstance(input_payload.get("work_package"), dict) else {},
            "verification": input_payload.get("verification") if isinstance(input_payload.get("verification"), (list, dict)) else [],
            "workspace_hint": workspace_hint,
            "repo_root": str(input_payload.get("repo_root") or workspace_hint),
            "segment_boundary_policy": str(input_payload.get("segment_boundary_policy") or ""),
            "grok_audit_policy": str(input_payload.get("grok_audit_policy") or ""),
            "segment_pass_same_workflow": bool(input_payload.get("segment_pass_same_workflow")),
            "segment_pass_next_lane": str(input_payload.get("segment_pass_next_lane") or ""),
            "fallback_canary_only": False,
            "codex_jsonl_is_execution_evidence": jsonl_nonempty,
            "jsonl_path": str(jsonl_path) if result_detail.get("jsonl_path") else "",
            "jsonl_exists": jsonl_nonempty,
            "final_path": str(final_path) if result_detail.get("final_path") else "",
            "raw_final_path": str(raw_final_path) if result_detail.get("raw_final_path") else "",
            "human_egress_filter_ref": str(result_detail.get("human_egress_filter_ref") or ""),
            "human_egress_filter": result_detail.get("human_egress_filter") if isinstance(result_detail.get("human_egress_filter"), dict) else {},
            "jobs_json_observe": observe,
            "jobs_json_observe_joined": bool(observe),
            "task_bound_worker_token_usage": observe.get("token_usage", {}) if observe else {},
            "task_bound_worker_files_modified": observe.get("files_modified", []) if observe else [],
            "task_bound_worker_command_executions": observe.get("command_executions", []) if observe else [],
            "backend_evidence_refs": {
                "worker_jsonl_backend_evidence": str(jsonl_path) if result_detail.get("jsonl_path") else "",
                "worker_final_backend_only": str(final_path) if result_detail.get("final_path") else "",
                "worker_raw_final_backend_only": str(raw_final_path) if result_detail.get("raw_final_path") else "",
                "human_egress_filter_ref": str(result_detail.get("human_egress_filter_ref") or ""),
                "jobs_json_observe_backend_readback": bool(observe),
            },
            "headless_worker": result_detail.get("headless_worker") is True,
            "raw_final_backend_evidence_only": result_detail.get("raw_final_backend_evidence_only") is True,
            "codex_final_to_user_allowed": result_detail.get("codex_final_to_user_allowed") is True,
            "worker_final_user_visible_allowed": result_detail.get("worker_final_user_visible_allowed") is True,
            "no_pytest_wall_to_user": result_detail.get("no_pytest_wall_to_user") is True,
            "expected_marker": expected_marker,
            "expected_marker_seen": marker_seen,
            "activator_ok": activator_ok,
            "reused_existing_task_result": reused_existing_task_result,
            "existing_task_result_ref": str(existing_result_ref) if reused_existing_task_result else "",
            "failure_classification": failure_classification,
            "external_condition": result_payload.get("external_condition") is True
            or result_detail.get("external_condition") is True
            or failure_classification.get("external_condition") is True,
            "retryable": result_payload.get("retryable") is True
            or result_detail.get("retryable") is True
            or failure_classification.get("retryable") is True,
            "retry_after_text": str(
                result_payload.get("retry_after_text")
                or result_detail.get("retry_after_text")
                or failure_classification.get("retry_after_text")
                or ""
            ),
            "activator_response": result_detail if result_detail is not result_payload else {},
            "activator_result": result_payload,
            "named_blocker": blocker,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "authority_boundary": authority_boundary("task_bound_codex_exec_jsonl_activity_readback"),
        }
        return compact_activity_for_history(activity_result)
    tool_root = runtime_root if (runtime_root / "tools" / "codex-sdk-python").exists() else DEFAULT_RUNTIME
    python = tool_root / "tools" / "codex-sdk-python" / ".venv" / "Scripts" / "python.exe"
    ucp = tool_root / "tools" / "universal_control_plane_v0" / "universal_control_plane_v0.py"
    if not python.is_file() or not ucp.is_file():
        return {
            "activity": "codex_worker_turn",
            "status": "activity_blocked",
            "command_surface": "UCP -> codex_exec_direct -> codex exec --json",
            "named_blocker": "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING",
            "tool_root": str(tool_root),
            "python_exists": python.is_file(),
            "ucp_exists": ucp.is_file(),
            "not_source_of_truth": True,
            "not_user_completion": True,
            "authority_boundary": authority_boundary("codex_exec_jsonl_activity_readback"),
        }
    command = [
            str(python),
            str(ucp),
            "dispatch",
            "--source",
            "temporal_codex_task_workflow",
            "--target",
            "codex_exec_direct",
            "--verb",
            "bounded_canary",
    ]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "activity": "codex_worker_turn",
            "status": "activity_blocked",
            "command_surface": "UCP -> codex_exec_direct -> codex exec --json",
            "named_blocker": "CODEX_WORKER_UCP_TOOL_PROCESS_CREATE_FAILED",
            "tool_root": str(tool_root),
            "error_type": type(exc).__name__,
            "error": str(exc)[:1200],
            "not_source_of_truth": True,
            "not_user_completion": True,
            "authority_boundary": authority_boundary("codex_exec_jsonl_activity_readback"),
        }
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    result_payload: dict[str, Any] = {}
    try:
        result_payload = json.loads(stdout)
    except json.JSONDecodeError:
        result_payload = {"parse_error": "UCP_DISPATCH_STDOUT_NOT_JSON"}
    status = "activity_gate_checked" if completed.returncode == 0 and result_payload.get("result", {}).get("status") == "PASS" else "activity_blocked"
    ucp_result = result_payload.get("result", {}).get("result", {})
    event_types = list(ucp_result.get("event_types") or [])
    return {
        "activity": "codex_worker_turn",
        "status": status,
        "command_surface": "UCP -> codex_exec_direct -> codex exec --json",
        "returncode": completed.returncode,
        "ucp_result": result_payload,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-2000:],
        "codex_jsonl_is_execution_evidence": ucp_result.get("saw_jsonl_event") is True
        or ucp_result.get("saw_thread_started") is True
        or "thread.started" in event_types
        or "turn.completed" in event_types,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("codex_exec_jsonl_activity_readback"),
    }


@activity.defn
async def worker_dispatch_ledger_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "worker_dispatch_ledger",
            "status": "skipped_non_seed_cortex_route",
            "adoption_state": worker_dispatch_ledger.ADOPTION_STATE,
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("worker_dispatch_ledger_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "worker_dispatch_ledger",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_WORKER_DISPATCH_LEDGER_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "adoption_state": worker_dispatch_ledger.ADOPTION_STATE,
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("worker_dispatch_ledger_runtime_root_guard"),
        }
    evidence = input_payload.get("worker_dispatch_evidence")
    if isinstance(evidence, dict):
        worker_results = [evidence]
    elif isinstance(evidence, list):
        worker_results = [item for item in evidence if isinstance(item, dict)]
    else:
        worker_results = []
    worker_results = [
        item for item in worker_results if item.get("activity") == "codex_worker_turn"
    ]
    if not worker_results:
        return {
            "activity": "worker_dispatch_ledger",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_WORKER_DISPATCH_LEDGER_MISSING_WORKER_RESULT",
            "adoption_state": worker_dispatch_ledger.ADOPTION_STATE,
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("worker_dispatch_ledger_missing_worker_result"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-codex-task-{task_id}"
    )
    dispatch_time = worker_dispatch_ledger.now_iso()
    entries = [
        worker_dispatch_ledger.temporal_worker_activity_entry(
            wave_id=wave_id,
            task_id=task_id,
            worker_result=item,
            dispatch_time=dispatch_time,
        )
        for item in worker_results
    ]
    ledger_payload = worker_dispatch_ledger.build_worker_dispatch_ledger(
        repo_root=_REPO_ROOT,
        runtime_root=runtime_root,
        wave_id=wave_id,
        task_id=task_id,
        extra_entries=entries,
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        runtime_entrypoint_invocation={
            "invoked_by": "temporal_codex_task_workflow.worker_dispatch_ledger_activity",
            "runtime_enforced_scope": (
                "seed_cortex_temporal_worker_dispatch_ledger_write_activity"
            ),
            "runtime_enforced": True,
        },
        write=True,
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "worker_dispatch_ledger"
        / "temporal_activity_latest.json"
    )
    worker_dispatch_ledger.write_json(temporal_activity_latest, ledger_payload)
    passed = ledger_payload.get("validation", {}).get("passed") is True
    return {
        "activity": "worker_dispatch_ledger",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "CODEX_S_WORKER_DISPATCH_LEDGER_VALIDATION_FAILED",
        "adoption_state": ledger_payload.get("adoption_state"),
        "runtime_entrypoint_invocation": ledger_payload.get("runtime_entrypoint_invocation", {}),
        "runtime_enforced": ledger_payload.get("runtime_entrypoint_invocation", {}).get("runtime_enforced") is True,
        "runtime_enforced_scope": ledger_payload.get("runtime_entrypoint_invocation", {}).get("runtime_enforced_scope", ""),
        "ledger_validation_passed": passed,
        "ledger_summary": ledger_payload.get("summary", {}),
        "ledger_succeeded_count": int(ledger_payload.get("succeeded_count") or 0),
        "ledger_succeeded_entry_ids": ledger_payload.get("succeeded_entry_ids") or [],
        "ledger_poll_entries": ledger_payload.get("poll_entries") or [],
        "ledger_latest_ref": ledger_payload.get("output_paths", {}).get("runtime_latest", ""),
        "ledger_poll_latest_ref": ledger_payload.get("output_paths", {}).get("poll_latest", ""),
        "ledger_temporal_activity_latest_ref": str(temporal_activity_latest),
        "ledger_readback_zh_ref": ledger_payload.get("output_paths", {}).get("runtime_readback_zh", ""),
        "actual_worker_result_count": len(worker_results),
        "actual_dispatch_entries": entries,
        "actual_dispatch_entry_ids": [entry.get("entry_id", "") for entry in entries],
        "fan_in_decision": "accepted_for_ledger_evidence_only",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("worker_dispatch_ledger_activity_read_model"),
    }


@activity.defn
async def main_execution_loop_tick_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "main_execution_loop_tick",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("main_execution_loop_tick_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "main_execution_loop_tick",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_MAIN_EXECUTION_LOOP_TICK_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("main_execution_loop_tick_runtime_root_guard"),
        }
    worker_ledger_activity_ref = (
        input_payload.get("worker_dispatch_ledger_activity")
        if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
        else {}
    )
    tick_payload = codex_s_main_execution_loop_tick.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        continuation_mode_active=True,
        explicit_user_stop=False,
        codex_subagents=list(input_payload.get("codex_subagents") or []),
        worker_dispatch_ledger_activity_ref=worker_ledger_activity_ref,
        wave_id=str(
            input_payload.get("wave_id")
            or input_payload.get("workflow_id")
            or f"temporal-main-execution-loop-{task_id}"
        ),
        write=True,
    )
    tick_payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.main_execution_loop_tick_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    tick_payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_main_execution_loop_tick_activity_only"
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "codex_s_main_execution_loop_tick"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "codex_s_main_execution_loop_tick" / "latest.json"
    readback = runtime_root / "readback" / "zh" / "codex_s_main_execution_loop_tick_20260702.md"
    codex_s_main_execution_loop_tick.write_json(latest, tick_payload)
    codex_s_main_execution_loop_tick.write_json(temporal_activity_latest, tick_payload)
    codex_s_main_execution_loop_tick.write_text(
        readback,
        codex_s_main_execution_loop_tick.render_readback(tick_payload),
    )
    passed = tick_payload.get("validation", {}).get("passed") is True
    bridge_view = main_loop_tick_workerbrief_bridge_view(tick_payload)
    return {
        "activity": "main_execution_loop_tick",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "CODEX_S_MAIN_EXECUTION_LOOP_TICK_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": tick_payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": tick_payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
        "tick_validation_passed": passed,
        "tick_latest_ref": str(latest),
        "tick_temporal_activity_latest_ref": str(temporal_activity_latest),
        "worker_dispatch_ledger_activity_ref": worker_ledger_activity_ref,
        "source_frontier_workerbrief_bridge": bridge_view,
        "source_frontier_workerbrief_bridge_validation_passed": (
            bridge_view.get("validation", {}).get("passed") is True
            if isinstance(bridge_view.get("validation"), dict)
            else False
        ),
        "next_wave_decision": tick_payload.get("next_wave_decision", {}),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("main_execution_loop_tick_activity_read_model"),
    }


@activity.defn
async def allocation_plan_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "allocation_plan",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("allocation_plan_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "allocation_plan",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_ALLOCATION_PLAN_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("allocation_plan_runtime_root_guard"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-allocation-plan-{task_id}"
    )
    extra_refs = {
        "workflow_run_id": str(input_payload.get("run_id") or input_payload.get("workflow_id") or ""),
        "workflow_refs": [
            str(input_payload.get("main_execution_loop_tick_activity", {}).get("tick_latest_ref", ""))
            if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
            else "",
            str(input_payload.get("durable_parallel_wave_packet_activity", {}).get("durable_packet_latest_ref", ""))
            if isinstance(input_payload.get("durable_parallel_wave_packet_activity"), dict)
            else "",
        ],
        "worker_ledger_refs": [
            str(input_payload.get("worker_dispatch_ledger_activity", {}).get("ledger_temporal_activity_latest_ref", ""))
            if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
            else "",
        ],
        "source_frontier_refs": [
            str(input_payload.get("source_frontier_durable_consumer_activity", {}).get("latest_ref", ""))
            if isinstance(input_payload.get("source_frontier_durable_consumer_activity"), dict)
            else "",
            str(input_payload.get("source_family_wave_scheduler_activity", {}).get("latest_ref", ""))
            if isinstance(input_payload.get("source_family_wave_scheduler_activity"), dict)
            else "",
        ],
        "fan_in_refs": [
            str(input_payload.get("default_dp_draft_staging_fan_in_activity", {}).get("draft_staging_ref", ""))
            if isinstance(input_payload.get("default_dp_draft_staging_fan_in_activity"), dict)
            else "",
        ],
        "event_history_refs": [
            str(input_payload.get("workflow_id") or ""),
            str(input_payload.get("wave_id") or ""),
        ],
    }
    payload = allocation_plan.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        task_id=task_id,
        wave_id=f"{wave_id}-allocation-plan",
        extra_refs=extra_refs,
        invoked_by_temporal_activity=True,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.allocation_plan_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_allocation_plan_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_allocation_plan_activity_only"
    )
    temporal_activity_latest = (
        runtime_root / "state" / "allocation_plan" / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "allocation_plan" / "latest.json"
    allocation_plan.write_json(latest, payload)
    allocation_plan.write_json(temporal_activity_latest, payload)
    allocation_plan.write_text(
        pathlib.Path(payload["output_paths"]["readback_zh"]),
        allocation_plan.render_readback(payload),
    )
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "allocation_plan",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "CODEX_S_ALLOCATION_PLAN_VALIDATION_FAILED",
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_allocation_plan_activity",
        "allocation_plan_validation_passed": passed,
        "allocation_plan_latest_ref": str(latest),
        "allocation_plan_temporal_activity_latest_ref": str(temporal_activity_latest),
        "worker_brief_queue_ref": payload.get("output_paths", {}).get("worker_brief_queue_latest", ""),
        "lane_allocations_ref": payload.get("output_paths", {}).get("lane_allocations_latest", ""),
        "dispatch_attempts_ref": payload.get("output_paths", {}).get("dispatch_attempts_latest", ""),
        "repair_plan_ref": payload.get("output_paths", {}).get("repair_plan_latest", ""),
        "readback_zh_ref": payload.get("output_paths", {}).get("readback_zh", ""),
        "lane_allocations": payload.get("lane_allocations", []),
        "lane_class_count": payload.get("lane_class_count"),
        "total_requested_width": payload.get("total_requested_width"),
        "target_width_source": payload.get("target_width_source", ""),
        "fixed_20_or_50_used": payload.get("fixed_20_or_50_used"),
        "repair_required": payload.get("repair_required") is True,
        "next_allocation_advice": payload.get("next_allocation_advice", {}),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("allocation_plan_activity_read_model"),
    }


@activity.defn
async def source_frontier_workerbrief_bridge_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_frontier_workerbrief_bridge",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_completion_gate": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_frontier_workerbrief_bridge_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_frontier_workerbrief_bridge",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_completion_gate": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_frontier_workerbrief_bridge_runtime_root_guard"),
        }
    workflow_id = str(
        input_payload.get("workflow_id")
        or input_payload.get("run_id")
        or "source-frontier-workerpool-global-closure-20260704"
    )
    wave_id = str(
        input_payload.get("wave_id")
        or workflow_id
        or "source-frontier-workerpool-global-closure-20260704"
    )
    activity_context = {
        "source_frontier_durable_consumer_activity": input_payload.get(
            "source_frontier_durable_consumer_activity", {}
        ),
        "default_dp_worker_pool_wave_activity": input_payload.get(
            "default_dp_worker_pool_wave_activity", {}
        ),
        "default_dp_draft_staging_fan_in_activity": input_payload.get(
            "default_dp_draft_staging_fan_in_activity", {}
        ),
        "default_loop_runtime_state_update_activity": input_payload.get(
            "default_loop_runtime_state_update_activity", {}
        ),
        "source_family_wave_scheduler_activity": input_payload.get(
            "source_family_wave_scheduler_activity", {}
        ),
        "allocation_plan_activity": input_payload.get("allocation_plan_activity", {}),
    }
    payload = source_frontier_workerbrief_bridge.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        wave_id=f"{wave_id}-source-frontier-workerbrief-bridge",
        workflow_id=workflow_id,
        invoked_by_temporal_activity=True,
        activity_context=activity_context,
        write=True,
    )
    passed = payload.get("validation", {}).get("passed") is True
    output = payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
    return {
        "activity": "source_frontier_workerbrief_bridge",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "CODEX_S_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE_VALIDATION_FAILED",
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_frontier_workerbrief_bridge_activity",
        "bridge_validation_passed": passed,
        "bridge_latest_ref": str(output.get("latest") or ""),
        "bridge_temporal_activity_latest_ref": str(output.get("temporal_activity_latest") or ""),
        "bridge_wave_ref": str(output.get("wave") or ""),
        "source_bound_worker_brief_queue_ref": str(output.get("worker_brief_queue_latest") or ""),
        "mapping_ref": str(output.get("mapping_latest") or ""),
        "worker_dispatch_ledger_wave_ref": str(output.get("worker_dispatch_ledger_wave") or ""),
        "worker_dispatch_ledger_activity_ref": str(output.get("worker_dispatch_ledger_activity") or ""),
        "readback_zh_ref": str(output.get("readback_zh") or ""),
        "source_item_count": payload.get("source_item_count"),
        "worker_brief_binding_count": payload.get("worker_brief_binding_count"),
        "generated_bounded_item": payload.get("source_frontier_delta", {}).get("generated_bounded_item")
        if isinstance(payload.get("source_frontier_delta"), dict)
        else None,
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_frontier_workerbrief_bridge_activity_read_model"),
    }


@activity.defn
async def source_frontier_workerpool_closure_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_frontier_workerpool_closure",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_completion_gate": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_frontier_workerpool_closure_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_frontier_workerpool_closure",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_completion_gate": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_frontier_workerpool_closure_runtime_root_guard"),
        }
    workflow_id = str(
        input_payload.get("workflow_id")
        or input_payload.get("run_id")
        or "source-frontier-workerpool-global-closure-20260704"
    )
    workflow_run_id = str(input_payload.get("workflow_run_id") or "")
    wave_id = str(
        input_payload.get("wave_id")
        or workflow_id
        or "source-frontier-workerpool-global-closure-20260704"
    )
    parent_wave_id = str(
        input_payload.get("parent_wave_id")
        or f"{wave_id}-source-frontier-workerbrief-bridge"
    )
    payload = source_frontier_workerpool_closure.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        wave_id=f"{wave_id}-source-frontier-workerpool-closure",
        parent_wave_id=parent_wave_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        invoked_by_temporal_activity=True,
        write=True,
    )
    passed = payload.get("validation", {}).get("passed") is True
    repair = payload.get("repair_plan") if isinstance(payload.get("repair_plan"), dict) else {}
    output = payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}
    return {
        "activity": "source_frontier_workerpool_closure",
        "status": "activity_gate_checked"
        if passed
        else "activity_repair_required"
        if repair.get("repair_required") is True
        else "activity_blocked",
        "named_blocker": repair.get("named_blocker", "")
        if repair.get("repair_required") is True
        else ""
        if passed
        else "CODEX_S_SOURCE_FRONTIER_WORKERPOOL_CLOSURE_VALIDATION_FAILED",
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_frontier_workerpool_closure_activity",
        "closure_validation_passed": passed,
        "repair_required": repair.get("repair_required") is True,
        "repair_plan_ref": str(output.get("repair_plan") or ""),
        "closure_latest_ref": str(output.get("latest") or ""),
        "closure_wave_ref": str(output.get("wave") or ""),
        "worker_dispatch_ledger_wave_ref": str(output.get("worker_dispatch_ledger_wave") or ""),
        "worker_dispatch_ledger_activity_ref": str(output.get("worker_dispatch_ledger_activity") or ""),
        "staging_ref": str(output.get("staging") or ""),
        "merge_ref": str(output.get("merge") or ""),
        "fan_in_ref": str(output.get("fan_in") or ""),
        "aaq_ref": str(output.get("aaq") or ""),
        "next_frontier_ref": str(output.get("next_frontier") or ""),
        "readback_zh_ref": str(output.get("readback_zh") or ""),
        "source_bound_worker_brief_count": payload.get("source_bound_worker_brief_count"),
        "lane_result_count": len(payload.get("lane_results", []))
        if isinstance(payload.get("lane_results"), list)
        else 0,
        "acceptance_chains": payload.get("acceptance_chains", []),
        "latest_alias_is_not_proof": True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_frontier_workerpool_closure_activity_read_model"),
    }


@activity.defn
async def pre_pass_audit_loop_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "pre_pass_audit_loop",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("pre_pass_audit_loop_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "pre_pass_audit_loop",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_PRE_PASS_AUDIT_LOOP_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("pre_pass_audit_loop_runtime_root_guard"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-pre-pass-audit-loop-{task_id}"
    )
    extra_refs = {
        "workflow_refs": [
            str(input_payload.get("main_execution_loop_tick_activity", {}).get("tick_latest_ref", ""))
            if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
            else "",
            str(input_payload.get("durable_parallel_wave_packet_activity", {}).get("durable_packet_latest_ref", ""))
            if isinstance(input_payload.get("durable_parallel_wave_packet_activity"), dict)
            else "",
        ],
        "worker_ledger_refs": [
            str(input_payload.get("worker_dispatch_ledger_activity", {}).get("ledger_temporal_activity_latest_ref", ""))
            if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
            else "",
        ],
        "source_frontier_refs": [
            str(input_payload.get("source_frontier_durable_consumer_activity", {}).get("latest_ref", ""))
            if isinstance(input_payload.get("source_frontier_durable_consumer_activity"), dict)
            else "",
            str(input_payload.get("source_family_wave_scheduler_activity", {}).get("latest_ref", ""))
            if isinstance(input_payload.get("source_family_wave_scheduler_activity"), dict)
            else "",
        ],
        "provider_invocation_refs": [
            str(input_payload.get("scheduler_invocation_packet_activity", {}).get("latest_ref", ""))
            if isinstance(input_payload.get("scheduler_invocation_packet_activity"), dict)
            else "",
        ],
        "fan_in_refs": [
            str(input_payload.get("default_dp_draft_staging_fan_in_activity", {}).get("draft_staging_ref", ""))
            if isinstance(input_payload.get("default_dp_draft_staging_fan_in_activity"), dict)
            else "",
        ],
    }
    payload = pre_pass_audit_loop.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        task_id=task_id,
        wave_id=f"{wave_id}-pre-pass",
        candidate_json=str(input_payload.get("pre_pass_candidate_json") or ""),
        extra_refs=extra_refs,
        invoked_by_temporal_activity=True,
        write=True,
    )
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "pre_pass_audit_loop",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": payload.get("named_blocker", "") if passed else "CODEX_S_PRE_PASS_AUDIT_LOOP_VALIDATION_FAILED",
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_pre_pass_audit_loop_activity",
        "pre_pass_validation_passed": passed,
        "pre_pass_latest_ref": payload.get("output_paths", {}).get("latest", ""),
        "candidate_snapshot_ref": payload.get("output_paths", {}).get("candidate_snapshot_latest", ""),
        "audit_lane_registry_ref": payload.get("output_paths", {}).get("audit_lane_registry_latest", ""),
        "audit_fan_in_ref": payload.get("output_paths", {}).get("audit_fan_in_latest", ""),
        "repair_plan_ref": payload.get("repair_plan_ref", ""),
        "readback_zh_ref": payload.get("output_paths", {}).get("readback_zh", ""),
        "fan_in_decision": payload.get("audit_fan_in", {}).get("decision", ""),
        "repair_required": payload.get("pre_pass_payload", {}).get("repair_required") is True,
        "continue_main_loop": payload.get("pre_pass_payload", {}).get("continue_main_loop") is True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("pre_pass_audit_loop_activity_read_model"),
    }


@activity.defn
async def dp_worker_pool_wave_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    payload = temporal_activity_no_window_dp_worker_pool_phase3.run_dp_worker_pool_wave_activity(
        dict(input_payload or {})
    )
    return compact_phase3_activity_result(payload)


@activity.defn
async def draft_staging_fan_in_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    payload = temporal_activity_no_window_dp_worker_pool_phase3.run_draft_staging_fan_in_activity(
        dict(input_payload or {})
    )
    return compact_phase3_activity_result(payload)


@activity.defn
async def loop_runtime_state_update_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    payload = temporal_activity_no_window_dp_worker_pool_phase3.run_loop_runtime_state_update_activity(
        dict(input_payload or {})
    )
    return compact_phase3_activity_result(payload)


@activity.defn
async def codex_native_provider_scheduler_phase4_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or "codex-native-provider-scheduler-phase4-wave-001"
    )
    invoke_codex_exec = input_payload.get("phase4_invoke_codex_exec", True) is not False
    timeout_seconds = int(
        input_payload.get("phase4_codex_exec_timeout_seconds")
        or input_payload.get("codex_exec_timeout_seconds")
        or 180
    )
    invoke_qwen = input_payload.get("phase4_invoke_qwen", True) is not False
    qwen_timeout_seconds = int(
        input_payload.get("phase4_qwen_timeout_seconds")
        or input_payload.get("qwen_timeout_seconds")
        or 60
    )
    payload = codex_native_provider_scheduler_phase4.run_provider_scheduler(
        runtime_root=runtime_root,
        repo_root=repo_root,
        wave_id=wave_id,
        invoke_codex_exec=invoke_codex_exec,
        codex_exec_timeout_seconds=timeout_seconds,
        invoke_qwen=invoke_qwen,
        qwen_timeout_seconds=qwen_timeout_seconds,
        write=True,
    )
    passed = payload.get("validation", {}).get("passed") is True
    evidence_refs = payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), dict) else {}
    result = {
        "activity": "codex_native_provider_scheduler_phase4",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": ";".join(payload.get("named_blockers") or []),
        "provider_scheduler_status": payload.get("status"),
        "validation_passed": passed,
        "validation": payload.get("validation", {}),
        "latest_ref": evidence_refs.get("latest", ""),
        "provider_registry_ref": evidence_refs.get("provider_registry", ""),
        "executor_adapter_ref": evidence_refs.get("executor_adapter", ""),
        "model_gateway_ref": evidence_refs.get("model_gateway", ""),
        "qwen_prepaid_policy_ref": evidence_refs.get("qwen_prepaid_policy", ""),
        "provider_invocation_ref": evidence_refs.get("provider_invocation", ""),
        "qwen_invocation_ref": evidence_refs.get("qwen_invocation", ""),
        "draft_staging_ref": evidence_refs.get("draft_staging", ""),
        "merge_consumer_ref": evidence_refs.get("merge_consumer", ""),
        "merge_artifact": payload.get("merge_artifact", ""),
        "readback_ref": evidence_refs.get("readback", ""),
        "capability_manifest_ref": evidence_refs.get("capability_manifest", ""),
        "codex_native_default_primary": payload.get("codex_native_default_primary") is True,
        "dp_deepseek_aux_parallel_draft": payload.get("dp_deepseek_aux_parallel_draft") is True,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_boundary": True,
        "authority_boundary": authority_boundary("codex_native_provider_scheduler_phase4_activity"),
        "temporal": {
            "workflow_id": str(input_payload.get("workflow_id") or ""),
            "workflow_run_id": str(input_payload.get("workflow_run_id") or ""),
            "task_queue": str(input_payload.get("task_queue") or DEFAULT_TASK_QUEUE),
            "activity_name": "codex_native_provider_scheduler_phase4_activity",
            "worker_identity": f"{os.getpid()}@{os.environ.get('COMPUTERNAME') or ''}",
            "event_history_ref": "",
        },
    }
    temporal_latest = codex_native_provider_scheduler_phase4.output_paths(runtime_root)[
        "temporal_activity_latest"
    ]
    codex_native_provider_scheduler_phase4.write_json(temporal_latest, result)
    result["temporal_activity_latest_ref"] = str(temporal_latest)
    return result


def durable_packet_codex_subagent_refs(
    input_payload: dict[str, Any],
    worker_ledger_activity_ref: dict[str, Any],
    main_loop_tick_activity_ref: dict[str, Any],
) -> list[str]:
    explicit = input_payload.get("codex_subagents")
    if isinstance(explicit, list):
        refs = [str(item) for item in explicit if str(item).strip()]
        if refs:
            return refs

    candidate_sources: list[dict[str, Any]] = [worker_ledger_activity_ref]
    nested_worker = main_loop_tick_activity_ref.get("worker_dispatch_ledger_activity_ref")
    if isinstance(nested_worker, dict):
        candidate_sources.append(nested_worker)

    refs: list[str] = []
    seen: set[str] = set()
    for source in candidate_sources:
        entry_ids = source.get("actual_dispatch_entry_ids")
        if not isinstance(entry_ids, list):
            continue
        for index, entry_id in enumerate(entry_ids, start=1):
            raw = str(entry_id).strip()
            if not raw:
                continue
            # Keep the exact entry id in actual_dispatch_refs; use a colon-safe
            # token here because durable_parallel_wave_packet.parse_subagent uses
            # "agent_id:role" syntax for compact readback.
            token = raw.replace(":", "__").replace(" ", "_")
            ref = f"{token}:temporal_worker_activity"
            if ref not in seen:
                refs.append(ref)
                seen.add(ref)
    if refs:
        return refs

    actual_worker_count = int(worker_ledger_activity_ref.get("actual_worker_result_count") or 0)
    if actual_worker_count > 0:
        task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID).replace(":", "__")
        return [f"{task_id}:temporal_worker_activity"]
    return []


def ensure_dp_sidecar_execution_port_refs(
    *,
    runtime_root: pathlib.Path,
    task_id: str,
    wave_id: str,
) -> dict[str, Any]:
    runner_latest = runtime_root / "state" / "dp_sidecar_execution_port" / "latest.json"
    provider_latest = runtime_root / "state" / "dp_sidecar_execution_provider" / "latest.json"
    manifest = (
        runtime_root
        / "capabilities"
        / "legacy.deepseek_dp_sidecar.dp_sidecar_execution_port"
        / "manifest.json"
    )
    existing_refs = {
        "runner_latest": str(runner_latest),
        "provider_latest": str(provider_latest),
        "provider_manifest": str(manifest),
    }
    if runner_latest.is_file() and provider_latest.is_file() and manifest.is_file():
        return {
            "status": "already_bound",
            "invoked": False,
            "mode": "provider_probe",
            "refs": existing_refs,
            "not_execution_controller": True,
        }
    invocation_id = f"{wave_id.replace(':', '_')}-dp-sidecar-execution-bootstrap"
    try:
        payload = dp_sidecar_execution_port.invoke_dp_sidecar_execution_port(
            runtime_root=runtime_root,
            task_id=f"{task_id}-dp-sidecar-execution-bootstrap",
            request_id=f"{task_id}-dp-sidecar-execution-route",
            invocation_id=invocation_id,
            episode_id="seedcortex-temporal-main-loop",
            mode="provider_probe",
            objective=(
                "Temporal durable packet must bind dp_sidecar_execution_port runner, "
                "provider, and manifest refs before fan-in."
            ),
            input_text=(
                "provider_probe only; bind DP sidecar execution refs; "
                "do not mutate repo; do not claim completion"
            ),
            write=True,
        )
    except Exception as exc:
        return {
            "status": "blocked",
            "invoked": True,
            "mode": "provider_probe",
            "named_blocker": "DP_SIDECAR_EXECUTION_PORT_BOOTSTRAP_FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "refs": existing_refs,
            "not_execution_controller": True,
        }
    provider_payload = (
        payload.get("provider_payload") if isinstance(payload.get("provider_payload"), dict) else {}
    )
    return {
        "status": "bootstrapped",
        "invoked": True,
        "mode": payload.get("mode") or "provider_probe",
        "runner_status": payload.get("status"),
        "provider_mode_invocation_status": provider_payload.get("mode_invocation_status"),
        "provider_registration_status": provider_payload.get("provider_registration_status"),
        "provider_named_blocker": provider_payload.get("named_blocker"),
        "refs": existing_refs,
        "not_execution_controller": True,
    }


@activity.defn
async def durable_parallel_wave_packet_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "durable_parallel_wave_packet",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("durable_parallel_wave_packet_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "durable_parallel_wave_packet",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_DURABLE_PARALLEL_WAVE_PACKET_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("durable_parallel_wave_packet_runtime_root_guard"),
        }
    worker_ledger_activity_ref = (
        input_payload.get("worker_dispatch_ledger_activity")
        if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
        else {}
    )
    main_loop_tick_activity_ref = (
        input_payload.get("main_execution_loop_tick_activity")
        if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
        else {}
    )
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-durable-parallel-wave-packet-{task_id}"
    )
    dp_sidecar_bootstrap = ensure_dp_sidecar_execution_port_refs(
        runtime_root=runtime_root,
        task_id=task_id,
        wave_id=wave_id,
    )
    codex_subagents = durable_packet_codex_subagent_refs(
        input_payload,
        worker_ledger_activity_ref,
        main_loop_tick_activity_ref,
    )
    packet_payload = durable_parallel_wave_packet.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        codex_subagents=codex_subagents,
        wave_id=wave_id,
        write=True,
    )
    packet_payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.durable_parallel_wave_packet_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_durable_parallel_wave_packet_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
        "dp_sidecar_execution_bootstrap": dp_sidecar_bootstrap,
    }
    packet_payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_durable_parallel_wave_packet_activity_only"
    )
    packet_payload["actual_activity_refs"] = {
        "worker_dispatch_ledger_activity_ref": worker_ledger_activity_ref,
        "main_execution_loop_tick_activity_ref": main_loop_tick_activity_ref,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
    }
    packet_payload.setdefault("actual_dispatch_refs", {})[
        "worker_dispatch_ledger_actual_entry_ids"
    ] = list(worker_ledger_activity_ref.get("actual_dispatch_entry_ids") or [])
    packet_payload["actual_dispatch_refs"][
        "derived_codex_subagent_refs_from_worker_activity"
    ] = bool(codex_subagents)
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "durable_parallel_wave_packet"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "durable_parallel_wave_packet" / "latest.json"
    readback = runtime_root / "readback" / "zh" / "durable_parallel_wave_packet_20260702.md"
    durable_parallel_wave_packet.write_json(latest, packet_payload)
    durable_parallel_wave_packet.write_json(temporal_activity_latest, packet_payload)
    durable_parallel_wave_packet.write_text(
        readback,
        durable_parallel_wave_packet.render_readback(packet_payload),
    )
    passed = packet_payload.get("validation", {}).get("passed") is True
    return {
        "activity": "durable_parallel_wave_packet",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "CODEX_S_DURABLE_PARALLEL_WAVE_PACKET_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": packet_payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": packet_payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_durable_parallel_wave_packet_activity",
        "durable_packet_validation_passed": passed,
        "durable_packet_latest_ref": str(latest),
        "durable_packet_temporal_activity_latest_ref": str(temporal_activity_latest),
        "durable_packet_readback_zh_ref": str(readback),
        "worker_dispatch_ledger_activity_ref": worker_ledger_activity_ref,
        "main_execution_loop_tick_activity_ref": main_loop_tick_activity_ref,
        "actual_dispatch_refs": packet_payload.get("actual_dispatch_refs", {}),
        "continue_dispatch_expected": packet_payload.get("continue_dispatch_expected"),
        "fan_in_policy": packet_payload.get("fan_in_policy", {}),
        "temporal_activity_refs": packet_payload.get("temporal_activity_refs", {}),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("durable_parallel_wave_packet_activity_read_model"),
    }


@activity.defn
async def source_frontier_durable_consumer_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_frontier_durable_consumer",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_frontier_durable_consumer_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_frontier_durable_consumer",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FRONTIER_CONSUMER_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_frontier_durable_consumer_runtime_root_guard"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-source-frontier-consumer-{task_id}"
    )
    consumer_payload = source_frontier_fanin_acceptance.consume_source_frontier_backlog(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        wave_id=wave_id,
        max_waves=int(input_payload.get("source_frontier_consumer_max_waves") or 3),
        durable_activity_invoked=True,
        write=True,
    )
    consumer_payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_frontier_durable_consumer_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_frontier_durable_consumer_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    consumer_payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_source_frontier_durable_consumer_activity_only"
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "source_frontier_durable_consumer"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "source_frontier_durable_consumer" / "latest.json"
    source_frontier_fanin_acceptance.write_json(latest, consumer_payload)
    source_frontier_fanin_acceptance.write_json(temporal_activity_latest, consumer_payload)
    passed = consumer_payload.get("validation", {}).get("passed") is True
    return {
        "activity": "source_frontier_durable_consumer",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": consumer_payload.get("named_blocker") or (
            "" if passed else "SOURCE_FRONTIER_DURABLE_CONSUMER_VALIDATION_FAILED"
        ),
        "runtime_entrypoint_invocation": consumer_payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": consumer_payload[
            "runtime_entrypoint_adoption_state"
        ],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_frontier_durable_consumer_activity",
        "consumer_validation_passed": passed,
        "consumer_latest_ref": str(latest),
        "consumer_temporal_activity_latest_ref": str(temporal_activity_latest),
        "consumer_readback_zh_ref": str(consumer_payload.get("readback_zh") or ""),
        "source_gap_open": consumer_payload.get("source_gap_open"),
        "consumed_batch_ids": consumer_payload.get("consumed_batch_ids", []),
        "remaining_batch_ids": consumer_payload.get("remaining_batch_ids", []),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_frontier_durable_consumer_activity_read_model"),
    }


@activity.defn
async def source_family_wave_scheduler_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_family_wave_scheduler",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_wave_scheduler_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_family_wave_scheduler",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FAMILY_WAVE_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_wave_scheduler_runtime_root_guard"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-source-family-wave-{task_id}"
    )
    payload = source_family_wave_scheduler.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        wave_id=wave_id,
        invoked_by_main_execution_loop_tick=False,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_family_wave_scheduler_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_wave_scheduler_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_source_family_wave_scheduler_activity_only"
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "source_family_wave_scheduler"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "source_family_wave_scheduler" / "latest.json"
    source_family_wave_scheduler.write_json(latest, payload)
    source_family_wave_scheduler.write_json(temporal_activity_latest, payload)
    passed = payload.get("validation", {}).get("passed") is True
    next_frontier = payload.get("next_frontier_machine_actions", {})
    next_frontier_items = (
        next_frontier.get("next_frontier", [])
        if isinstance(next_frontier, dict)
        else []
    )
    next_frontier_first = (
        next_frontier_items[0]
        if isinstance(next_frontier_items, list)
        and next_frontier_items
        and isinstance(next_frontier_items[0], dict)
        else {}
    )
    source_frontier_gap = (
        next_frontier.get("source_frontier_gap", {})
        if isinstance(next_frontier, dict)
        else {}
    )
    return {
        "activity": "source_family_wave_scheduler",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "SOURCE_FAMILY_WAVE_SCHEDULER_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload[
            "runtime_entrypoint_adoption_state"
        ],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_wave_scheduler_activity",
        "scheduler_validation_passed": passed,
        "source_family_wave_scheduler_latest_ref": str(latest),
        "source_family_wave_scheduler_temporal_activity_latest_ref": str(temporal_activity_latest),
        "source_family_wave_id": str(payload.get("wave_id") or ""),
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "source_family_count": len(
            payload.get("claim_card_staging_queue", {}).get("source_families", [])
        )
        if isinstance(payload.get("claim_card_staging_queue"), dict)
        else 0,
        "accepted_artifact_count": payload.get("artifact_acceptance_queue", {}).get(
            "accepted_artifact_count"
        )
        if isinstance(payload.get("artifact_acceptance_queue"), dict)
        else 0,
        "next_frontier_scope": payload.get("next_frontier_machine_actions", {})
        .get("source_frontier_gap", {})
        .get("gap_scope")
        if isinstance(payload.get("next_frontier_machine_actions"), dict)
        else "",
        "next_frontier_action": str(next_frontier_first.get("action") or ""),
        "remaining_topic_family_count": source_frontier_gap.get(
            "remaining_topic_family_count"
        ),
        "source_gap_open": source_frontier_gap.get("source_package_gap_open"),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_family_wave_scheduler_activity_read_model"),
    }


@activity.defn
async def source_family_mature_thin_bind_sunset_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_family_mature_thin_bind_sunset",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_phase5_sunset_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_family_mature_thin_bind_sunset",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FAMILY_PHASE5_SUNSET_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_phase5_sunset_runtime_root_guard"),
        }
    source_family_wave = (
        input_payload.get("source_family_wave_scheduler_activity")
        if isinstance(input_payload.get("source_family_wave_scheduler_activity"), dict)
        else {}
    )
    base_wave_id = str(
        source_family_wave.get("source_family_wave_id")
        or input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-source-family-phase5-sunset-{task_id}"
    )
    wave_id = str(input_payload.get("phase5_sunset_wave_id") or f"{base_wave_id}-phase5-mature-thin-bind-sunset")
    payload = source_family_mature_thin_bind_sunset.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        wave_id=wave_id,
        invoked_by_temporal_activity=True,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_family_mature_thin_bind_sunset_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_phase5_sunset_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_source_family_phase5_sunset_activity_only"
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "source_family_mature_thin_bind_sunset"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "source_family_mature_thin_bind_sunset" / "latest.json"
    source_family_mature_thin_bind_sunset.write_json(latest, payload)
    source_family_mature_thin_bind_sunset.write_json(temporal_activity_latest, payload)
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "source_family_mature_thin_bind_sunset",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "SOURCE_FAMILY_PHASE5_SUNSET_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_phase5_sunset_activity",
        "sunset_validation_passed": passed,
        "source_family_mature_thin_bind_sunset_latest_ref": str(latest),
        "source_family_mature_thin_bind_sunset_temporal_activity_latest_ref": str(
            temporal_activity_latest
        ),
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "wave_id": str(payload.get("wave_id") or ""),
        "parent_wave_id": str(payload.get("parent_wave_id") or ""),
        "consumed_next_frontier_action": str(payload.get("consumed_next_frontier_action") or ""),
        "source_frontier_remaining_topic_family_count": payload.get(
            "source_frontier_remaining_topic_family_count"
        ),
        "sunset_edge_count": payload.get("sunset_edges", {}).get("edge_count")
        if isinstance(payload.get("sunset_edges"), dict)
        else 0,
        "candidate_adapter_smoke_count": payload.get(
            "candidate_adapter_smoke_queue", {}
        ).get("candidate_count")
        if isinstance(payload.get("candidate_adapter_smoke_queue"), dict)
        else 0,
        "next_frontier_ref": str(
            payload.get("output_paths", {}).get("next_frontier_machine_actions_latest")
            or ""
        ),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_family_phase5_sunset_activity_read_model"),
    }


@activity.defn
async def phase0_reusable_kernel_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "phase0_reusable_kernel",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("phase0_reusable_kernel_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "phase0_reusable_kernel",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_PHASE0_REUSABLE_KERNEL_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("phase0_reusable_kernel_runtime_root_guard"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-phase0-reusable-kernel-{task_id}"
    )
    payload = phase0_reusable_kernel.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        spec_path=pathlib.Path(
            str(
                input_payload.get("spec_path")
                or r"D:\XINAO_RESEARCH_RUNTIME\specs\max_benefit_dynamic_loop_authority_20260702.v1.md"
            )
        ),
        wave_id=wave_id,
        invoked_by_temporal_activity=True,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.phase0_reusable_kernel_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_phase0_reusable_kernel_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_phase0_reusable_kernel_activity_only"
    )
    temporal_activity_latest = (
        runtime_root / "state" / "phase0_reusable_kernel" / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "phase0_reusable_kernel" / "latest.json"
    phase0_reusable_kernel.write_json(latest, payload)
    phase0_reusable_kernel.write_json(temporal_activity_latest, payload)
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "phase0_reusable_kernel",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "PHASE0_REUSABLE_KERNEL_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_phase0_reusable_kernel_activity",
        "kernel_validation_passed": passed,
        "phase0_reusable_kernel_latest_ref": str(latest),
        "phase0_reusable_kernel_temporal_activity_latest_ref": str(temporal_activity_latest),
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "landed_count": payload.get("kernel_objects", {}).get("landed_count")
        if isinstance(payload.get("kernel_objects"), dict)
        else 0,
        "object_count": payload.get("kernel_objects", {}).get("object_count")
        if isinstance(payload.get("kernel_objects"), dict)
        else 0,
        "new_work_id_thin_bind_ready": payload.get("new_work_id_thin_bind", {}).get(
            "bind_without_hand_solder"
        )
        is True
        if isinstance(payload.get("new_work_id_thin_bind"), dict)
        else False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("phase0_reusable_kernel_activity_read_model"),
    }


@activity.defn
async def wave2_mainchain_hygiene_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "wave2_mainchain_hygiene",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("wave2_mainchain_hygiene_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "wave2_mainchain_hygiene",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_WAVE2_MAINCHAIN_HYGIENE_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("wave2_mainchain_hygiene_runtime_root_guard"),
        }
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-wave2-mainchain-hygiene-{task_id}"
    )
    payload = wave2_mainchain_hygiene.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        planning_text=pathlib.Path(
            str(
                input_payload.get("planning_text")
                or r"C:\Users\xx363\Desktop\新系统_源文本对照_整块进度规划_20260704.txt"
            )
        ),
        wave_id=wave_id,
        invoked_by_temporal_activity=True,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.wave2_mainchain_hygiene_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_wave2_mainchain_hygiene_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_wave2_mainchain_hygiene_activity_only"
    )
    temporal_activity_latest = (
        runtime_root / "state" / "wave2_mainchain_hygiene" / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "wave2_mainchain_hygiene" / "latest.json"
    wave2_mainchain_hygiene.write_json(latest, payload)
    wave2_mainchain_hygiene.write_json(temporal_activity_latest, payload)
    passed = payload.get("validation", {}).get("passed") is True
    memo_counts = payload.get("memo_gap_refresh", {}).get("counts", {})
    return {
        "activity": "wave2_mainchain_hygiene",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else payload.get("named_blocker") or "WAVE2_MAINCHAIN_HYGIENE_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_wave2_mainchain_hygiene_activity",
        "hygiene_validation_passed": passed,
        "wave2_mainchain_hygiene_latest_ref": str(latest),
        "wave2_mainchain_hygiene_temporal_activity_latest_ref": str(temporal_activity_latest),
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "black_window_issue_handled": payload.get("black_window_probe", {}).get("black_window_issue_handled") is True,
        "visible_disallowed_cmd_powershell_python_count": int(
            payload.get("black_window_probe", {}).get("visible_disallowed_cmd_powershell_python_count")
            or 0
        ),
        "memo_gap_landed_or_migrated": int(memo_counts.get("landed_or_migrated") or 0)
        if isinstance(memo_counts, dict)
        else 0,
        "memo_gap_total_targets": int(memo_counts.get("total_targets") or 0)
        if isinstance(memo_counts, dict)
        else 0,
        "default_main_loop": str(
            payload.get("default_main_loop_hygiene", {}).get("default_main_loop") or ""
        ),
        "next_frontier_action": str(
            (payload.get("next_frontier_machine_actions", {}).get("next_frontier") or [{}])[0].get("action")
            if isinstance(payload.get("next_frontier_machine_actions"), dict)
            else ""
        ),
        "stop_allowed": payload.get("next_frontier_machine_actions", {}).get("stop_allowed")
        if isinstance(payload.get("next_frontier_machine_actions"), dict)
        else None,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("wave2_mainchain_hygiene_activity_read_model"),
    }


def default_trigger_candidate_codex_subagent_refs(
    input_payload: dict[str, Any],
    durable_wave_packet_activity_ref: dict[str, Any],
) -> list[str]:
    explicit = input_payload.get("codex_subagents")
    if isinstance(explicit, list):
        refs = [str(item) for item in explicit if str(item).strip()]
        if refs:
            return refs
    actual_dispatch = durable_wave_packet_activity_ref.get("actual_dispatch_refs")
    if not isinstance(actual_dispatch, dict):
        return []
    refs = actual_dispatch.get("codex_subagents")
    if isinstance(refs, list):
        normalized: list[str] = []
        for item in refs:
            if isinstance(item, dict):
                agent_id = str(item.get("agent_id") or "").strip()
                role = str(item.get("role") or "temporal_worker_activity").strip()
                if agent_id:
                    normalized.append(f"{agent_id}:{role}")
                continue
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized
    return []


def scheduler_invocation_spawned_lanes(
    input_payload: dict[str, Any],
    durable_wave_packet_activity_ref: dict[str, Any],
    main_loop_tick_activity_ref: dict[str, Any],
    worker_ledger_activity_ref: dict[str, Any] | None = None,
    allocation_plan_activity_ref: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    worker_ledger_activity_ref = (
        worker_ledger_activity_ref if isinstance(worker_ledger_activity_ref, dict) else {}
    )
    allocation_plan_activity_ref = (
        allocation_plan_activity_ref if isinstance(allocation_plan_activity_ref, dict) else {}
    )
    actual_dispatch = durable_wave_packet_activity_ref.get("actual_dispatch_refs")
    if not isinstance(actual_dispatch, dict):
        actual_dispatch = {}
    codex_subagents = actual_dispatch.get("codex_subagents")
    if not isinstance(codex_subagents, list):
        codex_subagents = []

    evidence_ref = str(
        durable_wave_packet_activity_ref.get("durable_packet_temporal_activity_latest_ref")
        or durable_wave_packet_activity_ref.get("durable_packet_latest_ref")
        or ""
    )
    readback_ref = str(durable_wave_packet_activity_ref.get("durable_packet_readback_zh_ref") or "")
    poll_ref = str(
        main_loop_tick_activity_ref.get("tick_temporal_activity_latest_ref")
        or main_loop_tick_activity_ref.get("tick_latest_ref")
        or ""
    )
    workflow_id = str(
        input_payload.get("workflow_id")
        or input_payload.get("wave_id")
        or input_payload.get("task_id")
        or SEED_CORTEX_WORK_ID
    )
    scheduler_ref = (
        f"{workflow_id}:temporal_codex_task_workflow.scheduler_invocation_packet_activity"
    )

    lanes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_lane(
        lane_ref: str,
        *,
        source: str,
        spawned_by: str,
        lane_kind: str = "current_parent_codex_subagent",
        poll_status: str = "activity_gate_checked",
        dispatch_status: str = "dispatched",
        extra: dict[str, Any] | None = None,
    ) -> None:
        lane_ref = lane_ref.strip()
        if not lane_ref or lane_ref in seen:
            return
        seen.add(lane_ref)
        lane: dict[str, Any] = {
            "lane_kind": lane_kind
            if lane_kind in scheduler_invocation_packet.LANE_KINDS
            else "other_actual_lane",
            "lane_ref": lane_ref,
            "actual_ref": True,
            "source": source,
            "spawned_by": spawned_by,
            "poll_status": poll_status,
            "dispatch_status": dispatch_status,
            "scheduler_invocation_ref": scheduler_ref,
            "not_execution_controller": True,
        }
        for key, value in (extra or {}).items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            lane[key] = value
        if poll_ref:
            lane["poll_ref"] = poll_ref
        if evidence_ref:
            lane["evidence_ref"] = evidence_ref
        if readback_ref:
            lane["readback_ref"] = readback_ref
        lanes.append(lane)

    for item in codex_subagents:
        if isinstance(item, dict):
            agent_id = str(item.get("agent_id") or item.get("lane_ref") or "").strip()
            role = str(item.get("role") or "temporal_worker_activity").strip()
            upstream_source = str(
                item.get("source") or "durable_parallel_wave_packet_activity"
            )
            provider = str(item.get("provider") or "").strip()
            mode = str(item.get("mode") or "").strip()
            source_entry_id = str(item.get("source_entry_id") or "").strip()
            item_poll_status = str(item.get("poll_status") or "activity_gate_checked")
        else:
            agent_id = str(item).strip()
            role = "temporal_worker_activity"
            upstream_source = "durable_parallel_wave_packet_activity"
            provider = ""
            mode = ""
            source_entry_id = ""
            item_poll_status = "activity_gate_checked"
        if not agent_id:
            continue
        lane_ref = f"{agent_id}:{role}" if role and ":" not in agent_id else agent_id
        append_lane(
            lane_ref,
            source="durable_parallel_wave_packet_activity_result.actual_dispatch_refs.codex_subagents",
            spawned_by="temporal_codex_task_workflow.durable_parallel_wave_packet_activity",
            poll_status=item_poll_status,
            dispatch_status="completed"
            if item_poll_status in {"succeeded", "activity_gate_checked", "completed"}
            else "dispatched",
            extra={
                "agent_id": agent_id,
                "provider": provider,
                "mode": mode,
                "source_entry_id": source_entry_id,
                "upstream_source": upstream_source,
            },
        )

    allocation_lanes = allocation_plan_activity_ref.get("lane_allocations")
    if isinstance(allocation_lanes, list):
        allocation_evidence_ref = str(
            allocation_plan_activity_ref.get("allocation_plan_temporal_activity_latest_ref")
            or allocation_plan_activity_ref.get("allocation_plan_latest_ref")
            or ""
        )
        allocation_readback_ref = str(allocation_plan_activity_ref.get("readback_zh_ref") or "")
        for item in allocation_lanes:
            if not isinstance(item, dict):
                continue
            lane_class = str(item.get("lane_class") or "").strip()
            lane_id = str(item.get("lane_id") or "").strip()
            if not lane_id or not lane_class:
                continue
            provider_candidates = item.get("provider_candidates")
            provider = (
                str(provider_candidates[0])
                if isinstance(provider_candidates, list) and provider_candidates
                else ""
            )
            if lane_class in {"cheap_draft", "extraction", "eval", "contradiction", "audit"}:
                lane_kind = "dp_sidecar_execution"
            elif lane_class == "durable_temporal":
                lane_kind = "temporal_activity_lane"
            elif lane_class == "foreground_brain":
                lane_kind = "current_parent_codex_subagent"
            else:
                lane_kind = "local_tool_lane"
            append_lane(
                lane_id,
                source="allocation_plan_activity_result.lane_allocations",
                spawned_by="temporal_codex_task_workflow.allocation_plan_activity",
                lane_kind=lane_kind,
                poll_status="activity_gate_checked",
                dispatch_status="planned_or_dispatched_by_allocation_plan",
                extra={
                    "lane_class": lane_class,
                    "provider": provider,
                    "mode": lane_class,
                    "requested_width": item.get("requested_width"),
                    "upstream_source": "allocation_plan_activity",
                    "evidence_ref": allocation_evidence_ref,
                    "readback_ref": allocation_readback_ref,
                },
            )

    if lanes:
        return lanes

    entry_ids = actual_dispatch.get("worker_dispatch_ledger_actual_entry_ids")
    if isinstance(entry_ids, list):
        for entry_id in entry_ids:
            append_lane(
                str(entry_id),
                source="worker_dispatch_ledger_actual_entry_id",
                spawned_by="temporal_codex_task_workflow.worker_dispatch_ledger_activity",
                extra={"source_entry_id": str(entry_id).strip()},
            )
    if lanes:
        return lanes

    worker_sources: list[dict[str, Any]] = []
    for source in (
        worker_ledger_activity_ref,
        durable_wave_packet_activity_ref.get("worker_dispatch_ledger_activity_ref"),
        main_loop_tick_activity_ref.get("worker_dispatch_ledger_activity_ref"),
    ):
        if isinstance(source, dict):
            worker_sources.append(source)

    for source in worker_sources:
        dispatch_entries = source.get("actual_dispatch_entries")
        if isinstance(dispatch_entries, list):
            for entry in dispatch_entries:
                if not isinstance(entry, dict):
                    continue
                provider = str(entry.get("provider") or "").strip()
                mode = str(entry.get("mode") or "").strip()
                poll_status = str(entry.get("poll_status") or "activity_gate_checked").strip()
                if provider not in {"temporal.codex_worker_turn_activity", "codex.subagent"}:
                    continue
                if mode not in {"worker", "subagent"}:
                    continue
                if poll_status in {"planned_not_spawned", "not_applicable_not_spawned"}:
                    continue
                entry_id = str(entry.get("entry_id") or "").strip()
                agent_id = str(entry.get("agent_id") or "").strip()
                append_lane(
                    entry_id or agent_id,
                    source="worker_dispatch_ledger_activity_result.actual_dispatch_entries",
                    spawned_by="temporal_codex_task_workflow.worker_dispatch_ledger_activity",
                    poll_status=poll_status,
                    dispatch_status="completed"
                    if poll_status in {"succeeded", "activity_gate_checked", "completed"}
                    else "dispatched",
                    extra={
                        "agent_id": agent_id,
                        "provider": provider,
                        "mode": mode,
                        "source_entry_id": entry_id,
                    },
                )
        if lanes:
            return lanes
        entry_ids = source.get("actual_dispatch_entry_ids")
        if isinstance(entry_ids, list):
            for entry_id in entry_ids:
                append_lane(
                    str(entry_id),
                    source="worker_dispatch_ledger_activity_result.actual_dispatch_entry_ids",
                    spawned_by="temporal_codex_task_workflow.worker_dispatch_ledger_activity",
                    extra={"source_entry_id": str(entry_id).strip()},
                )
        if lanes:
            return lanes
    return lanes


@activity.defn
async def default_main_loop_trigger_candidate_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "default_main_loop_trigger_candidate",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary(
                "default_main_loop_trigger_candidate_non_seed_cortex_skip"
            ),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "default_main_loop_trigger_candidate",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary(
                "default_main_loop_trigger_candidate_runtime_root_guard"
            ),
        }
    main_loop_tick_activity_ref = (
        input_payload.get("main_execution_loop_tick_activity")
        if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
        else {}
    )
    worker_ledger_activity_ref = (
        input_payload.get("worker_dispatch_ledger_activity")
        if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
        else {}
    )
    durable_wave_packet_activity_ref = (
        input_payload.get("durable_parallel_wave_packet_activity")
        if isinstance(input_payload.get("durable_parallel_wave_packet_activity"), dict)
        else {}
    )
    wave_id = str(
        input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-default-main-loop-trigger-candidate-{task_id}"
    )
    codex_subagents = default_trigger_candidate_codex_subagent_refs(
        input_payload,
        durable_wave_packet_activity_ref,
    )
    from xinao_seedlab.application.seed_cortex import build_default_service

    service = build_default_service(runtime_root)
    trigger_payload = service.default_main_loop_trigger_candidate(
        anchor_package_root=str(
            input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统"
        ),
        wave_id=wave_id,
        codex_subagents=codex_subagents,
        write_runtime=True,
    )
    trigger_payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.default_main_loop_trigger_candidate_activity",
        "invoked": True,
        "runtime_enforced_scope": (
            "seed_cortex_temporal_default_main_loop_trigger_candidate_activity"
        ),
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
        "stop_hook_controller": False,
    }
    trigger_payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_default_main_loop_trigger_candidate_activity_only"
    )
    trigger_payload["actual_activity_refs"] = {
        "main_execution_loop_tick_activity_ref": main_loop_tick_activity_ref,
        "durable_parallel_wave_packet_activity_ref": durable_wave_packet_activity_ref,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
        "refs_are_not_stop_guard_layers": True,
    }
    trigger_payload["activity_scope_boundary"] = {
        "runtime_enforced_only_for_this_temporal_activity": True,
        "global_default_trigger_installed": False,
        "stop_hook_controller": False,
        "is_completion_gate": False,
        "is_broad_execution_controller": False,
        "promotion_beyond_activity_scope_requires": [
            "Temporal_or_LangGraph_invokes_each_real_wave",
            "task_scoped_fan_in_evidence",
            "ArtifactAcceptanceQueue_decision",
            "Chinese_readback",
        ],
    }
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "default_main_loop_trigger_candidate"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "default_main_loop_trigger_candidate" / "latest.json"
    readback = (
        runtime_root
        / "readback"
        / "zh"
        / "default_main_loop_trigger_candidate_20260702.md"
    )
    default_main_loop_trigger_candidate.write_json(latest, trigger_payload)
    default_main_loop_trigger_candidate.write_json(temporal_activity_latest, trigger_payload)
    default_main_loop_trigger_candidate.write_text(
        readback,
        default_main_loop_trigger_candidate.render_readback(trigger_payload),
    )
    passed = trigger_payload.get("validation", {}).get("passed") is True
    return {
        "activity": "default_main_loop_trigger_candidate",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": ""
        if passed
        else "CODEX_S_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": trigger_payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": trigger_payload[
            "runtime_entrypoint_adoption_state"
        ],
        "runtime_enforced": True,
        "runtime_enforced_scope": (
            "seed_cortex_temporal_default_main_loop_trigger_candidate_activity"
        ),
        "trigger_candidate_validation_passed": passed,
        "trigger_candidate_latest_ref": str(latest),
        "trigger_candidate_temporal_activity_latest_ref": str(temporal_activity_latest),
        "trigger_candidate_readback_zh_ref": str(readback),
        "main_execution_loop_tick_activity_ref": main_loop_tick_activity_ref,
        "durable_parallel_wave_packet_activity_ref": durable_wave_packet_activity_ref,
        "actual_dispatch_refs": trigger_payload.get("actual_dispatch_refs", {}),
        "poll_refs": trigger_payload.get("poll_refs", {}),
        "fan_in_refs": trigger_payload.get("fan_in_refs", {}),
        "evidence_refs": trigger_payload.get("evidence_refs", {}),
        "readback_refs": trigger_payload.get("readback_refs", {}),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary(
            "default_main_loop_trigger_candidate_activity_read_model"
        ),
    }


@activity.defn
async def scheduler_invocation_packet_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "scheduler_invocation_packet",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary(
                "scheduler_invocation_packet_non_seed_cortex_skip"
            ),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "scheduler_invocation_packet",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SCHEDULER_INVOCATION_PACKET_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary(
                "scheduler_invocation_packet_runtime_root_guard"
            ),
        }
    main_loop_tick_activity_ref = (
        input_payload.get("main_execution_loop_tick_activity")
        if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
        else {}
    )
    worker_ledger_activity_ref = (
        input_payload.get("worker_dispatch_ledger_activity")
        if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
        else {}
    )
    durable_wave_packet_activity_ref = (
        input_payload.get("durable_parallel_wave_packet_activity")
        if isinstance(input_payload.get("durable_parallel_wave_packet_activity"), dict)
        else {}
    )
    default_trigger_candidate_activity_ref = (
        input_payload.get("default_main_loop_trigger_candidate_activity")
        if isinstance(input_payload.get("default_main_loop_trigger_candidate_activity"), dict)
        else {}
    )
    allocation_plan_activity_ref = (
        input_payload.get("allocation_plan_activity")
        if isinstance(input_payload.get("allocation_plan_activity"), dict)
        else {}
    )
    spawned_lanes = scheduler_invocation_spawned_lanes(
        input_payload,
        durable_wave_packet_activity_ref,
        main_loop_tick_activity_ref,
        worker_ledger_activity_ref,
        allocation_plan_activity_ref,
    )
    spawned_lane_sources = {
        str(lane.get("source") or "")
        for lane in spawned_lanes
        if isinstance(lane, dict)
    }
    spawned_lane_upstream_sources = {
        str(lane.get("upstream_source") or "")
        for lane in spawned_lanes
        if isinstance(lane, dict)
    }
    packet_payload = scheduler_invocation_packet.build_scheduler_invocation_packet(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        spawned_lanes=spawned_lanes,
        current_parent_codex_invocation_ref="",
        callable_scheduler_invocation_ref="temporal_codex_task_workflow.scheduler_invocation_packet_activity",
        dp_launcher_ref="",
        write=True,
    )
    packet_payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.scheduler_invocation_packet_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_scheduler_invocation_packet_activity",
        "runtime_enforced": True,
        "packet_runtime_enforced": packet_payload.get("runtime_enforced") is True,
        "packet_default_runtime_scheduler_invoked": packet_payload.get(
            "default_runtime_scheduler_invoked"
        )
        is True,
        "not_execution_controller": True,
        "not_completion_gate": True,
        "default_runtime_scheduler_hook_installed": False,
    }
    packet_payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_scheduler_invocation_packet_activity_only"
    )
    packet_payload["actual_activity_refs"] = {
        "main_execution_loop_tick_activity_ref": main_loop_tick_activity_ref,
        "worker_dispatch_ledger_activity_ref": worker_ledger_activity_ref,
        "durable_parallel_wave_packet_activity_ref": durable_wave_packet_activity_ref,
        "default_main_loop_trigger_candidate_activity_ref": (
            default_trigger_candidate_activity_ref
        ),
        "allocation_plan_activity_ref": allocation_plan_activity_ref,
        "refs_are_evidence_only": True,
        "refs_are_not_completion_gates": True,
        "refs_are_not_execution_controllers": True,
        "refs_are_not_default_runtime_scheduler_invocation": True,
        "spawned_lanes_derived_from_activity_refs": bool(spawned_lanes),
        "spawned_lanes_derived_from_durable_activity": any(
            "durable_parallel_wave_packet_activity" in source
            for source in spawned_lane_sources
        )
        or (
            bool(spawned_lanes)
            and isinstance(
                durable_wave_packet_activity_ref.get("actual_dispatch_refs"),
                dict,
            )
        ),
        "spawned_lanes_derived_from_worker_dispatch_ledger_activity": any(
            "worker_dispatch_ledger" in source
            for source in (spawned_lane_sources | spawned_lane_upstream_sources)
        )
        or bool(worker_ledger_activity_ref.get("actual_dispatch_entry_ids")),
        "spawned_lanes_derived_from_allocation_plan_activity": any(
            "allocation_plan_activity" in source
            for source in (spawned_lane_sources | spawned_lane_upstream_sources)
        )
        or bool(allocation_plan_activity_ref.get("lane_allocations")),
    }
    packet_payload["activity_scope_boundary"] = {
        "runtime_enforced_only_for_this_temporal_activity": True,
        "packet_runtime_enforced": packet_payload.get("runtime_enforced") is True,
        "packet_default_runtime_scheduler_invoked": packet_payload.get(
            "default_runtime_scheduler_invoked"
        )
        is True,
        "default_runtime_scheduler_installed": False,
        "global_scheduler_spawned_lanes": False,
        "stop_hook_controller": False,
        "is_completion_gate": False,
        "is_broad_execution_controller": False,
        "activity_scoped_spawned_lane_count": len(spawned_lanes),
        "promotion_beyond_activity_scope_requires": [
            "Temporal_or_LangGraph_invokes_each_real_wave",
            "event_history_or_checkpoint_binding",
            "task_scoped_fan_in_evidence",
            "ArtifactAcceptanceQueue_decision",
            "Chinese_readback",
        ],
    }
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "scheduler_invocation_packet"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "scheduler_invocation_packet" / "latest.json"
    readback = runtime_root / "readback" / "zh" / scheduler_invocation_packet.READBACK_NAME
    scheduler_invocation_packet.write_json(latest, packet_payload)
    scheduler_invocation_packet.write_json(temporal_activity_latest, packet_payload)
    scheduler_invocation_packet.write_text(
        readback,
        scheduler_invocation_packet.render_readback(packet_payload),
    )
    passed = packet_payload.get("validation", {}).get("passed") is True
    packet_lane_refs = packet_payload.get("scheduler_spawned_lane_refs", [])
    if not isinstance(packet_lane_refs, list):
        packet_lane_refs = []
    compact_packet_lane_refs = [
        {
            "lane_kind": str(lane.get("lane_kind") or ""),
            "lane_ref": str(lane.get("lane_ref") or ""),
            "source": str(lane.get("source") or ""),
            "dispatch_status": str(lane.get("dispatch_status") or ""),
            "poll_status": str(lane.get("poll_status") or ""),
            "not_execution_controller": lane.get("not_execution_controller", True)
            is True,
        }
        for lane in packet_lane_refs[:16]
        if isinstance(lane, dict)
    ]
    actual_activity_refs = packet_payload.get("actual_activity_refs", {})
    if not isinstance(actual_activity_refs, dict):
        actual_activity_refs = {}
    compact_actual_activity_refs = {
        "refs_are_evidence_only": actual_activity_refs.get("refs_are_evidence_only")
        is True,
        "refs_are_not_completion_gates": actual_activity_refs.get(
            "refs_are_not_completion_gates"
        )
        is True,
        "refs_are_not_execution_controllers": actual_activity_refs.get(
            "refs_are_not_execution_controllers"
        )
        is True,
        "refs_are_not_default_runtime_scheduler_invocation": actual_activity_refs.get(
            "refs_are_not_default_runtime_scheduler_invocation"
        )
        is True,
        "spawned_lanes_derived_from_activity_refs": actual_activity_refs.get(
            "spawned_lanes_derived_from_activity_refs"
        )
        is True,
        "spawned_lanes_derived_from_durable_activity": actual_activity_refs.get(
            "spawned_lanes_derived_from_durable_activity"
        )
        is True,
        "spawned_lanes_derived_from_worker_dispatch_ledger_activity": (
            actual_activity_refs.get(
                "spawned_lanes_derived_from_worker_dispatch_ledger_activity"
            )
            is True
        ),
        "spawned_lanes_derived_from_allocation_plan_activity": actual_activity_refs.get(
            "spawned_lanes_derived_from_allocation_plan_activity"
        )
        is True,
    }
    activity_scope_boundary = packet_payload.get("activity_scope_boundary", {})
    compact_activity_scope_boundary = (
        {
            "runtime_enforced_only_for_this_temporal_activity": (
                activity_scope_boundary.get(
                    "runtime_enforced_only_for_this_temporal_activity"
                )
                is True
            ),
            "packet_runtime_enforced": activity_scope_boundary.get(
                "packet_runtime_enforced"
            )
            is True,
            "packet_default_runtime_scheduler_invoked": activity_scope_boundary.get(
                "packet_default_runtime_scheduler_invoked"
            )
            is True,
            "default_runtime_scheduler_installed": activity_scope_boundary.get(
                "default_runtime_scheduler_installed"
            )
            is True,
            "global_scheduler_spawned_lanes": activity_scope_boundary.get(
                "global_scheduler_spawned_lanes"
            )
            is True,
            "stop_hook_controller": activity_scope_boundary.get("stop_hook_controller")
            is True,
            "is_completion_gate": activity_scope_boundary.get("is_completion_gate")
            is True,
            "is_broad_execution_controller": activity_scope_boundary.get(
                "is_broad_execution_controller"
            )
            is True,
            "activity_scoped_spawned_lane_count": int(
                activity_scope_boundary.get("activity_scoped_spawned_lane_count") or 0
            ),
        }
        if isinstance(activity_scope_boundary, dict)
        else {}
    )
    return {
        "activity": "scheduler_invocation_packet",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": ""
        if passed
        else "CODEX_S_SCHEDULER_INVOCATION_PACKET_VALIDATION_FAILED",
        "packet_named_blocker": packet_payload.get("named_blocker", ""),
        "runtime_entrypoint_invocation": packet_payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": packet_payload[
            "runtime_entrypoint_adoption_state"
        ],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_scheduler_invocation_packet_activity",
        "packet_runtime_enforced": packet_payload.get("runtime_enforced") is True,
        "packet_default_runtime_scheduler_invoked": packet_payload.get(
            "default_runtime_scheduler_invoked"
        )
        is True,
        "scheduler_invocation_packet_validation_passed": passed,
        "scheduler_invocation_packet_latest_ref": str(latest),
        "scheduler_invocation_packet_temporal_activity_latest_ref": str(
            temporal_activity_latest
        ),
        "scheduler_invocation_packet_readback_zh_ref": str(readback),
        "latest_ref": str(latest),
        "temporal_activity_latest_ref": str(temporal_activity_latest),
        "readback_zh_ref": str(readback),
        "actual_activity_refs": compact_actual_activity_refs,
        "activity_scope_boundary": compact_activity_scope_boundary,
        "packet_status": packet_payload.get("status"),
        "packet_adoption_state": packet_payload.get("adoption_state"),
        "packet_scheduler_invoked": packet_payload.get("scheduler_invoked") is True,
        "packet_spawned_lane_count": int(packet_payload.get("spawned_lane_count") or 0),
        "packet_scheduler_spawned_lane_refs": compact_packet_lane_refs,
        "packet_scheduler_spawned_lane_ref_count": len(packet_lane_refs),
        "packet_scheduler_spawned_lane_refs_truncated": len(packet_lane_refs)
        > len(compact_packet_lane_refs),
        "packet_default_runtime_scheduler_invoked_root": packet_payload.get(
            "default_runtime_scheduler_invoked"
        ),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary(
            "scheduler_invocation_packet_activity_read_model"
        ),
    }


def default_continuation_worker_prompt(task_id: str, decision: dict[str, Any]) -> str:
    reason = str(decision.get("reason") or decision.get("required_gate") or "partial_completion_claim")
    return (
        "LEGACY RESCUE ONLY: continuation.N is not a main-chain next hop. "
        "Do not read files, run commands, edit files, or reason broadly. "
        "Return exactly three short lines for this bounded Temporal continuation:\n"
        f"1 task_id={task_id}\n"
        f"2 not_user_completion=true partial_reason={reason}\n"
        f"3 continuation_dispatched=true {TASK_CONTINUATION_WORKER_MARKER}\n"
    )


def segment_pass_next_worker_payload(
    input_payload: dict[str, Any],
    decision: dict[str, Any],
    segment_gate: dict[str, Any],
) -> dict[str, Any]:
    task_id = str(input_payload["task_id"])
    next_lane = str(decision.get("segment_audit_next_lane") or segment_gate.get("next_lane") or "L2")
    workflow_ref = str(input_payload.get("workflow_id") or input_payload.get("workflow_run_id") or "workflow")
    worker_suffix = _safe_task_file_id(workflow_ref)[-48:] or "workflow"
    worker_task_id = str(
        input_payload.get("segment_pass_next_worker_task_id")
        or f"{task_id}.segment-pass.{next_lane}.worker.{worker_suffix}"
    )
    prompt = str(input_payload.get("segment_pass_next_worker_prompt") or "").strip()
    if not prompt:
        prompt = (
            "BOUNDED SEGMENT-PASS L2 WORKER. Do not restart XINAO bootstrap, do not "
            "read broad startup files, do not call /codex-a/intent, do not dispatch "
            "another Codex worker, and do not wait on this worker's own result.\n"
            f"task_id={task_id}\n"
            f"next_lane={next_lane}\n"
            f"l1_l2_gate=D:\\XINAO_CLEAN_RUNTIME\\state\\l1_l2_segment_gate\\tasks\\{task_id}.json\n"
            f"grok_gate=D:\\XINAO_CLEAN_RUNTIME\\state\\grok_l1_l2_segment_gate\\tasks\\{task_id}.json\n"
            f"worker_assignment=D:\\XINAO_CLEAN_RUNTIME\\state\\worker_assignment\\{task_id}.json\n"
            "Scope: verify these task-scoped evidence paths are coherent enough to "
            "continue the frontier; if a required path is missing, report the named "
            "blocker only. Do not claim user completion or terminal approval.\n"
            "Return exactly four short lines:\n"
            f"1 task_id={task_id}\n"
            f"2 next_lane={next_lane}\n"
            "3 status=segment_pass_l2_worker_checked not_user_completion=true\n"
            f"4 {TASK_BOUND_CODEX_WORKER_MARKER}\n"
        )
    return {
        **input_payload,
        "execute_codex_worker": True,
        "codex_worker_task_id": worker_task_id,
        "codex_worker_prompt": prompt,
        "codex_worker_expected_marker": str(
            input_payload.get("segment_pass_next_worker_expected_marker") or TASK_BOUND_CODEX_WORKER_MARKER
        ),
        "segment_pass_next_lane": next_lane,
        "segment_pass_next_worker_required": True,
        "segment_pass_same_workflow": True,
    }


def grok_wait_l1_continuation_worker_payload(
    input_payload: dict[str, Any],
    decision: dict[str, Any],
    segment_gate: dict[str, Any],
    sequence: int,
) -> dict[str, Any]:
    phase_execution = input_payload.get("phase_execution") if isinstance(input_payload.get("phase_execution"), dict) else {}
    phase_scope = str(
        input_payload.get("phase_scope")
        or phase_execution.get("phase_scope")
        or "L1_grok_wait_nonblocking_durable_continuation"
    )
    signal_payload = {
        **input_payload,
        "user_goal": (
            str(input_payload.get("user_goal") or "")
            + "\n\nPolicy: Grok segment verdict gates completion/Stop/L2 only; it must not park "
            "same-workflow L1 implementation continuation while the workflow is partial."
        ),
        "routing_verb": "continue_same_task",
        "grok_waiting_does_not_block_continuation": True,
        "segment_audit_status": str(segment_gate.get("status") or decision.get("segment_audit_status") or ""),
        "segment_audit_named_blocker": str(segment_gate.get("named_blocker") or decision.get("named_blocker") or ""),
        "worker_kind": str(input_payload.get("worker_kind") or phase_execution.get("worker_kind") or ""),
        "phase_scope": phase_scope,
        "work_package": input_payload.get("work_package") if isinstance(input_payload.get("work_package"), dict) else {},
        "verification": input_payload.get("verification") if isinstance(input_payload.get("verification"), (list, dict)) else [],
        "codex_worker_timeout_sec": input_payload.get("codex_worker_timeout_sec")
        or input_payload.get("implementation_worker_timeout_sec")
        or input_payload.get("timeout_sec"),
        "worker_assignment_ref": str(input_payload.get("worker_assignment_ref") or ""),
        "human_egress_route": str(input_payload.get("human_egress_route") or "grok_report_only"),
    }
    payload = continue_same_task_worker_payload(input_payload, signal_payload, sequence)
    payload.update({
        "grok_wait_l1_continuation_worker_required": bool(payload.get("execute_codex_worker")),
        "grok_waiting_does_not_block_continuation": True,
        "segment_pass_next_worker_required": False,
        "segment_pass_same_workflow": True,
    })
    return payload


def codex_worker_activity_timeout(input_payload: dict[str, Any]) -> dt.timedelta:
    try:
        timeout_sec = int(
            input_payload.get("codex_worker_activity_timeout_sec")
            or input_payload.get("codex_worker_timeout_sec")
            or 300
        )
    except (TypeError, ValueError):
        timeout_sec = 300
    timeout_sec = max(60, timeout_sec + 120)
    return dt.timedelta(seconds=timeout_sec)


def phase_exit_segment_pass_allowed(input_payload: dict[str, Any], segment_gate: dict[str, Any]) -> bool:
    return bool(
        input_payload.get("phase_exit_ready")
        or input_payload.get("segment_phase_exit_ready")
        or input_payload.get("segment_pass_checker_allowed")
        or segment_gate.get("phase_exit_ready")
        or segment_gate.get("segment_phase_exit_ready")
        or segment_gate.get("segment_pass_checker_allowed")
    )


def segment_gate_allows_l1_continuation(segment_gate: dict[str, Any]) -> bool:
    status = str(segment_gate.get("status") or "")
    return bool(
        segment_gate.get("workflow_waiting_grok_segment_audit") is True
        or status == "GROK_SEGMENT_AUDIT_TIMEOUT_CODEXA_BRAIN_FALLBACK"
        or segment_gate.get("codexa_brain_fallback_allowed") is True
        or segment_gate.get("codexa_brain_fallback_active") is True
    )


def is_assignment_implementation_worker(worker: dict[str, Any]) -> bool:
    return bool(
        isinstance(worker, dict)
        and (
            worker.get("implementation_worker_required") is True
            or str(worker.get("worker_kind") or "") == "implementation_worker"
        )
    )


def same_workflow_next_hop(worker: dict[str, Any], *, timer_wait: bool = False) -> str:
    if worker:
        if is_assignment_implementation_worker(worker):
            return "same_workflow_assignment_driven_implementation_worker"
        return SEGMENT_PASS_NEXT_BOUNDED_WORKER_HOP
    if timer_wait:
        return "temporal_workflow_internal_timer_or_signal_wait"
    return ""


def phase5_read_model_join_groups_from_refs(
    evidence_refs: dict[str, str],
    task_id: str,
    workflow_id: str,
    workflow_run_id: str,
    worker_jsonl_path: str = "",
) -> dict[str, dict[str, Any]]:
    refs = evidence_refs if isinstance(evidence_refs, dict) else {}

    def has_ref(name: str) -> bool:
        return bool(str(refs.get(name) or ""))

    groups: dict[str, dict[str, Any]] = {
        "A_files_machine": {
            "label": "A",
            "joined": has_ref("openapi_contract"),
            "carrier": "OpenAPI contract + current-authority filesystem readback",
            "progress_truth_allowed": False,
        },
        "B_discovery_catalog": {
            "label": "B",
            "joined": any(has_ref(name) for name in (
                "backstage_catalog",
                "dify_workflow_read_model",
                "xinao_mcp_http_discovery",
                "ucp_mcp_binding",
                "openapi_contract",
            )),
            "carrier": "Backstage/OpenAPI/MCP/UCP/Dify discovery read models",
            "progress_truth_allowed": False,
        },
        "C_temporal_owner": {
            "label": "C",
            "joined": bool(task_id and workflow_id and workflow_run_id),
            "carrier": "Temporal workflow task_id/workflow_id/workflow_run_id correlation",
            "progress_truth_allowed": True,
        },
        "D_task_bound_worker_jsonl": {
            "label": "D",
            "joined": bool(worker_jsonl_path),
            "carrier": "task-bound Codex exec --json JSONL",
            "progress_truth_allowed": True,
        },
        "E_observation_snapshot": {
            "label": "E",
            "joined": bool(task_id and workflow_id),
            "carrier": "/codex-a/observation-snapshot and panel readback projection",
            "progress_truth_allowed": False,
        },
        "F_trace_correlation": {
            "label": "F",
            "joined": any(has_ref(name) for name in (
                "opentelemetry_collector",
                "opentelemetry_trace_canary",
                "langfuse_trace_readback",
                "litellm_model_gateway",
                "action_delivery_trace",
            )),
            "carrier": "OTel/Langfuse/LiteLLM/action trace correlation read models",
            "progress_truth_allowed": False,
            "truth_role": "correlation_only_not_completion_or_owner_truth",
        },
    }
    for group in groups.values():
        group.update({
            "completion_source_allowed": False,
            "owner_replacement_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
        })
    return groups


def phase5_observability_discovery_panel_readback(
    runtime_root: pathlib.Path,
    task_id: str,
    workflow_id: str,
    workflow_run_id: str,
    worker_jsonl_path: str = "",
) -> dict[str, Any]:
    evidence_refs = {
        "opentelemetry_collector": str(runtime_root / "state" / "otel_collector" / "latest.json"),
        "opentelemetry_trace_canary": str(runtime_root / "state" / "otel_unified_trace_canary" / "latest.json"),
        "langfuse_trace_readback": str(runtime_root / "state" / "langfuse" / "latest.json"),
        "litellm_model_gateway": str(runtime_root / "state" / "lite_llm_proxy" / "latest.json"),
        "backstage_catalog": str(runtime_root / "state" / "backstage_catalog" / "latest.json"),
        "dify_workflow_read_model": str(runtime_root / "state" / "dify_saved_workflow_binding" / "latest.json"),
        "xinao_mcp_http_discovery": str(runtime_root / "state" / "xinao_mcp_http" / "latest.json"),
        "ucp_mcp_binding": str(runtime_root / "state" / "universal_control_plane_v0" / "mcp_binding.json"),
        "openapi_contract": str(runtime_root / "action_contract" / "new_action_minimal_ingress_v1.openapi.json"),
        "action_delivery_trace": str(runtime_root / "state" / "action_delivery_trace" / f"{task_id}.jsonl"),
        "task_bound_worker_jsonl": str(worker_jsonl_path or ""),
    }
    read_model_join_groups = phase5_read_model_join_groups_from_refs(
        evidence_refs,
        task_id,
        workflow_id,
        workflow_run_id,
        worker_jsonl_path,
    )
    read_model_joined_labels = [
        group["label"]
        for group in read_model_join_groups.values()
        if group.get("joined") is True
    ]
    return {
        "schema_version": "xinao.phase5_observability_discovery_trace_binding.readback.v1",
        "phase_scope": "Phase5_observability_discovery_trace_binding",
        "task_id": task_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "bound_task_id": task_id,
        "bound_workflow_id": workflow_id,
        "bound_workflow_run_id": workflow_run_id,
        "same_workflow_required": True,
        "task_workflow_correlated": bool(task_id and workflow_id and workflow_run_id),
        "default_progress_truth": "Temporal Event History + task-bound worker JSONL evidence",
        "observability_progress_truth_allowed": False,
        "catalog_progress_truth_allowed": False,
        "model_gateway_progress_truth_allowed": False,
        "current_task_owner_replacement_allowed": False,
        "completion_claim_allowed": False,
        "trace_catalog_model_refs_are_evidence_only": True,
        "read_model_join_groups": read_model_join_groups,
        "read_model_joined_labels": read_model_joined_labels,
        "a_b_c_d_e_f_read_model_joined": all(
            group.get("joined") is True for group in read_model_join_groups.values()
        ),
        "trace_correlation_only": True,
        "app_server_stale_cannot_override_temporal_jsonl": True,
        "progress_truth_sources": {
            "temporal_event_history": {
                "required": True,
                "progress_truth_allowed": True,
                "task_id": task_id,
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
            },
            "task_bound_worker_jsonl": {
                "required": True,
                "progress_truth_allowed": True,
                "ref": str(worker_jsonl_path or ""),
            },
            "observability_discovery_read_models": {
                "required": False,
                "progress_truth_allowed": False,
                "completion_source_allowed": False,
                "owner_replacement_allowed": False,
                "truth_promotion_denied_reason": "observability_discovery_read_models_are_backend_evidence_only_not_progress_truth",
            },
        },
        "truth_promotion_denied_reason": "observability_discovery_read_models_are_backend_evidence_only_not_progress_truth",
        "evidence_refs": evidence_refs,
        "authority_boundary": {
            "role": "phase5_observability_discovery_trace_binding_readback",
            "source_of_truth": "external_mature_runtime",
            "truth_carriers": [
                "Temporal workflow state and event history",
                "task-bound Codex worker JSONL evidence",
                "LangGraph checkpoint/store",
                "OPA/Conftest policy decision",
            ],
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "observability_read_model_only": True,
        },
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "not_current_task_owner": True,
    }


def continue_same_task_worker_payload(
    input_payload: dict[str, Any],
    signal_payload: dict[str, Any],
    sequence: int,
) -> dict[str, Any]:
    task_id = str(input_payload["task_id"])
    workflow_ref = str(input_payload.get("workflow_id") or input_payload.get("workflow_run_id") or "workflow")
    workflow_run_ref = str(signal_payload.get("workflow_run_id") or input_payload.get("workflow_run_id") or "")
    signal_instance_ref = str(signal_payload.get("generated_at") or signal_payload.get("signal_id") or "")
    worker_suffix_source = "-".join(part for part in (workflow_ref, workflow_run_ref, signal_instance_ref) if part)
    worker_suffix = hashlib.sha256(worker_suffix_source.encode("utf-8")).hexdigest()[:16] if worker_suffix_source else "workflow"
    worker_task_id = str(
        signal_payload.get("codex_worker_task_id")
        or f"{task_id}.continue-same-task.worker.{sequence}.{worker_suffix}"
    )
    user_goal = str(signal_payload.get("user_goal") or input_payload.get("user_goal") or "")
    phase_execution = signal_payload.get("phase_execution") if isinstance(signal_payload.get("phase_execution"), dict) else {}
    worker_kind = str(
        phase_execution.get("worker_kind")
        or signal_payload.get("worker_kind")
        or signal_payload.get("phase_worker_kind")
        or ""
    ).strip()
    phase_scope = str(phase_execution.get("phase_scope") or signal_payload.get("phase_scope") or "").strip()
    work_package = (
        phase_execution.get("work_package")
        if isinstance(phase_execution.get("work_package"), dict)
        else signal_payload.get("work_package")
        if isinstance(signal_payload.get("work_package"), dict)
        else {}
    )
    verification = (
        phase_execution.get("verification")
        if isinstance(phase_execution.get("verification"), (list, dict))
        else signal_payload.get("verification")
        if isinstance(signal_payload.get("verification"), (list, dict))
        else []
    )
    assignment_ref = str(signal_payload.get("worker_assignment_ref") or "")
    repo_root = str(
        phase_execution.get("repo_root")
        or signal_payload.get("repo_root")
        or signal_payload.get("workspace_hint")
        or str(_REPO_ROOT)
    )
    assignment_driven_prompt = worker_kind == "implementation_worker"
    prompt = "" if assignment_driven_prompt else str(signal_payload.get("codex_worker_prompt") or "").strip()
    assignment_missing_fields = list(signal_payload.get("assignment_missing_fields") or [])
    assignment_invalid_fields = list(signal_payload.get("assignment_invalid_fields") or [])
    if not worker_kind and "worker_kind" not in assignment_missing_fields:
        assignment_missing_fields.append("worker_kind")
    elif worker_kind and worker_kind != "implementation_worker" and "worker_kind_not_implementation_worker" not in assignment_invalid_fields:
        assignment_invalid_fields.append("worker_kind_not_implementation_worker")
    if not phase_scope and "phase_scope" not in assignment_missing_fields:
        assignment_missing_fields.append("phase_scope")
    if not work_package and "work_package" not in assignment_missing_fields:
        assignment_missing_fields.append("work_package")
    if not verification and "verification" not in assignment_missing_fields:
        assignment_missing_fields.append("verification")
    segment_pass_requested = bool(
        signal_payload.get("segment_pass_checker_default") is True
        or signal_payload.get("segment_pass_checker_allowed") is True
        or phase_execution.get("segment_pass_checker_default") is True
        or phase_execution.get("segment_pass_checker_allowed") is True
    )
    if segment_pass_requested and "segment_pass_checker_not_implementation_worker" not in assignment_invalid_fields:
        assignment_invalid_fields.append("segment_pass_checker_not_implementation_worker")
    timeout_source = (
        phase_execution.get("timeout_sec")
        or signal_payload.get("codex_worker_timeout_sec")
        or signal_payload.get("implementation_worker_timeout_sec")
    )
    if timeout_source in (None, "") and "timeout_sec" not in assignment_missing_fields:
        assignment_missing_fields.append("timeout_sec")
    assignment_scope_blocked = bool(assignment_missing_fields or assignment_invalid_fields)
    assignment_blocker = (
        "BLOCKED_INVALID_WORKER_ASSIGNMENT_SCOPE"
        if assignment_invalid_fields
        else "BLOCKED_NO_WORKER_ASSIGNMENT_SCOPE"
        if assignment_missing_fields
        else ""
    )
    if assignment_scope_blocked:
        prompt = ""
    if assignment_scope_blocked and (not worker_kind or not phase_scope):
        worker_kind = worker_kind or "BLOCKED_EXPLICIT_PHASE_WORKER_ASSIGNMENT_REQUIRED"
        phase_scope = phase_scope or "BLOCKED_EXPLICIT_PHASE_SCOPE_REQUIRED"
    if not prompt:
        if assignment_scope_blocked:
            prompt = (
                "DO NOT IMPLEMENT. Explicit phase worker assignment is missing for this "
                "continue_same_task signal or is invalid for the Phase default. Report "
                "the named blocker only; do not call "
                "/codex-a/intent, do not start a new workflow, and do not claim completion.\n"
                f"task_id={task_id}\n"
                f"named_blocker={assignment_blocker}\n"
                f"Final line must contain exactly {TASK_BOUND_CODEX_WORKER_MARKER}.\n"
            )
        else:
            prompt = (
                "IMPLEMENTATION WORKER FOR THE EXISTING XINAO TEMPORAL WORKFLOW. Do not call "
                "/codex-a/intent, do not start a new workflow, do not create a new owner, "
                "do not emit a user-facing pytest/PASS wall, and do not claim completion.\n"
                f"task_id={task_id}\n"
                f"workflow_id={workflow_ref}\n"
                f"continuation_authorization_lane={CONTINUATION_AUTHORIZATION_LANE}\n"
                f"segment_audit_authorization_lane={SEGMENT_AUDIT_AUTHORIZATION_LANE}\n"
                f"worker_kind={worker_kind}\n"
                f"phase_scope={phase_scope}\n"
                f"worker_assignment_ref={assignment_ref}\n"
                f"repo_root={repo_root}\n"
                f"user_goal_summary={user_goal[:900]}\n"
                "work_package_json="
                + json.dumps(work_package, ensure_ascii=False, sort_keys=True)[:3000]
                + "\n"
                "verification_json="
                + json.dumps(verification, ensure_ascii=False, sort_keys=True)[:1600]
                + "\n"
                "Scope: implement the next explicit work package from the task-scoped "
                "WORKER_ASSIGNMENT and C:\\Users\\xx363\\Desktop\\最大成熟组件能力最大化.txt. "
                "Prefer mature carriers already mirrored under E:\\XINAO_EXTERNAL_MATURE and "
                "the existing Temporal/codex exec --json/LangGraph/OPA surfaces. Keep edits "
                "thin and task-scoped. Run the narrow verification for the files you change. "
                "If the phase boundary is not ready, leave a named blocker and next machine "
                "action, but do not trigger Grok segment audit yourself.\n"
                "Return a concise backend-only implementation report with these labels: "
                "local_current_state, external_mature_replacement, actual_change, verification, "
                "named_blocker, next_machine_action.\n"
                "Final line must contain exactly "
                f"{TASK_BOUND_CODEX_WORKER_MARKER}.\n"
                "Do not use the old segment-pass four-line checker format as the Phase default.\n"
            )
    try:
        timeout_sec = int(timeout_source or 1800)
    except (TypeError, ValueError):
        timeout_sec = 1800
    timeout_sec = max(300, timeout_sec)
    try:
        activity_timeout_sec = int(
            phase_execution.get("max_activity_timeout_sec")
            or signal_payload.get("codex_worker_activity_timeout_sec")
            or timeout_sec
        )
    except (TypeError, ValueError):
        activity_timeout_sec = timeout_sec
    activity_timeout_sec = max(timeout_sec, activity_timeout_sec)
    return {
        **input_payload,
        **continuation_authorization_fields(),
        "user_goal": user_goal or str(input_payload.get("user_goal") or ""),
        "execute_codex_worker": not assignment_scope_blocked,
        "codex_worker_task_id": worker_task_id,
        "codex_worker_prompt": prompt,
        "codex_worker_expected_marker": str(signal_payload.get("codex_worker_expected_marker") or TASK_BOUND_CODEX_WORKER_MARKER),
        "codex_worker_timeout_sec": timeout_sec,
        "codex_worker_activity_timeout_sec": activity_timeout_sec,
        "worker_kind": worker_kind,
        "phase_scope": phase_scope,
        "work_package": work_package,
        "verification": verification,
        "phase_execution": phase_execution,
        "assignment_missing_fields": assignment_missing_fields,
        "assignment_invalid_fields": assignment_invalid_fields,
        "assignment_scope_blocked": assignment_scope_blocked,
        "named_blocker": assignment_blocker,
        "worker_assignment_ref": assignment_ref,
        "repo_root": repo_root,
        "workspace_hint": repo_root,
        "caller_prompt_ignored_by_assignment": bool(
            (assignment_driven_prompt or assignment_scope_blocked)
            and (
                signal_payload.get("codex_worker_prompt")
                or signal_payload.get("caller_codex_worker_prompt")
            )
        ),
        "dispatch_strategy": "codex_exec_json_implementation_worker",
        "mature_execution_carrier": MATURE_EXECUTION_CARRIER,
        "mature_execution_carrier_refs": list(MATURE_EXECUTION_CARRIER_REFS),
        "worker_evidence_contract": "task_bound_codex_exec_jsonl_or_app_server_sdk",
        "assignment_driven_dispatch": bool(not assignment_scope_blocked and worker_kind == "implementation_worker"),
        "codex_a_role": CODEX_A_BRAIN_DISPATCHER_ROLE,
        "codex_a_execution_owner": False,
        "segment_pass_checker_default": False,
        "segment_pass_checker_allowed": False,
        "human_egress_route": str(signal_payload.get("human_egress_route") or input_payload.get("human_egress_route") or "grok_report_only"),
        "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "segment_boundary_headless": True,
        "continue_same_task_signal_worker_required": True,
        "implementation_worker_required": bool(not assignment_scope_blocked and worker_kind == "implementation_worker"),
        "segment_boundary_policy": "phase_exit_only",
        "grok_audit_policy": "only_after_phase_ready",
        "segment_pass_next_worker_required": False,
        "segment_pass_same_workflow": True,
        "continue_same_task_signal": signal_payload,
    }


def next_continuation_worker_task_id(runtime_root: pathlib.Path, task_id: str) -> str:
    """Legacy rescue helper; mainline partial continuation stays inside Temporal."""
    results_root = runtime_root / "state" / "codex_results"
    prefix = f"{task_id}.continuation."
    max_index = 0
    if results_root.exists():
        for path in results_root.iterdir():
            if not path.is_dir() or not path.name.startswith(prefix):
                continue
            suffix = path.name[len(prefix):]
            if suffix.isdigit():
                max_index = max(max_index, int(suffix))
    return f"{task_id}.continuation.{max_index + 1}"


def assignment_dag_auto_continue_signal(runtime_root: pathlib.Path, task_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    assignment_ref = runtime_root / "state" / "worker_assignment" / f"{task_id}.json"
    assignment = read_json(assignment_ref, {})
    dag = assignment.get("assignment_dag") if isinstance(assignment.get("assignment_dag"), dict) else {}
    nodes = dag.get("nodes") if isinstance(dag.get("nodes"), list) else []
    next_node_id = str(dag.get("next_ready_node_id") or "")
    if not next_node_id or next_node_id == str(dag.get("blocked_terminal_node_id") or ""):
        return {}
    next_node = next((node for node in nodes if isinstance(node, dict) and str(node.get("id") or "") == next_node_id), {})
    if not next_node:
        return {}
    node_status = str(next_node.get("status") or "").lower()
    if "blocked" in node_status or "terminal" in node_status:
        return {}
    previous_signal = input_payload.get("continue_same_task_signal") if isinstance(input_payload.get("continue_same_task_signal"), dict) else {}
    previous_phase = previous_signal.get("phase_execution") if isinstance(previous_signal.get("phase_execution"), dict) else {}
    previous_work = previous_phase.get("work_package") if isinstance(previous_phase.get("work_package"), dict) else {}
    previously_dispatched_node = str(
        previous_signal.get("assignment_dag_node_id")
        or previous_signal.get("dag_next_ready_node_id")
        or previous_work.get("next_ready_node_id")
        or ""
    )
    if previously_dispatched_node and previously_dispatched_node == next_node_id:
        return {}
    phase_execution = dict(assignment.get("phase_execution") if isinstance(assignment.get("phase_execution"), dict) else {})
    node_files = next_node.get("files") if isinstance(next_node.get("files"), list) else []
    node_acceptance = next_node.get("acceptance") if isinstance(next_node.get("acceptance"), list) else []
    work_package = dict(phase_execution.get("work_package") if isinstance(phase_execution.get("work_package"), dict) else {})
    work_package.update({
        "objective": (
            "Execute assignment_dag next_ready_node_id="
            + next_node_id
            + " under the existing Temporal workflow; write task-bound JSONL evidence; "
            "do not spawn owner, do not use pump default, and do not claim completion."
        ),
        "next_ready_node_id": next_node_id,
        "work_items": [next_node],
        "files": node_files,
    })
    timeout_sec = int(
        phase_execution.get("timeout_sec")
        or assignment.get("implementation_worker_timeout_sec")
        or assignment.get("codex_worker_timeout_sec")
        or input_payload.get("implementation_worker_timeout_sec")
        or input_payload.get("codex_worker_timeout_sec")
        or 1800
    )
    if next_node_id == "parallel_draft_batch_bind" or isinstance(next_node.get("lanes"), list):
        timeout_sec = max(timeout_sec, ASSIGNMENT_DAG_WORKERPOOL_MIN_TIMEOUT_SECONDS)
    max_activity_timeout_sec = int(phase_execution.get("max_activity_timeout_sec") or timeout_sec)
    max_activity_timeout_sec = max(max_activity_timeout_sec, timeout_sec)
    phase_execution.update({
        "worker_kind": "implementation_worker",
        "phase_scope": str(phase_execution.get("phase_scope") or assignment.get("dag_scope") or "assignment_dag_auto_continue"),
        "timeout_sec": timeout_sec,
        "max_activity_timeout_sec": max_activity_timeout_sec,
        "work_package": work_package,
        "verification": node_acceptance or phase_execution.get("verification") or ["assignment_dag node evidence written"],
        "segment_pass_checker_default": False,
        "segment_pass_checker_allowed": False,
    })
    return {
        "task_id": task_id,
        "source_task_id": task_id,
        "routing_verb": "continue_same_task",
        **continuation_authorization_fields(),
        "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "source_kind": "assignment_dag_auto_continue",
        "execute_policy": "auto",
        "execute_codex_worker": True,
        "workflow_id": str(assignment.get("workflow_id") or input_payload.get("workflow_id") or ""),
        "workflow_run_id": str(assignment.get("workflow_run_id") or input_payload.get("workflow_run_id") or ""),
        "worker_assignment_ref": str(assignment_ref),
        "assignment_id": str(assignment.get("assignment_id") or ""),
        "dag_scope": str(assignment.get("dag_scope") or ""),
        "assignment_dag_node_id": next_node_id,
        "dag_next_ready_node_id": next_node_id,
        "phase_scope": str(phase_execution.get("phase_scope") or ""),
        "phase_execution": phase_execution,
        "codex_worker_timeout_sec": timeout_sec,
        "implementation_worker_timeout_sec": timeout_sec,
        "user_goal": str(assignment.get("objective_cn") or input_payload.get("user_goal") or ""),
        "message": "assignment_dag auto-continue next_ready_node_id=" + next_node_id,
        "assignment_dag_auto_continue": True,
        "spawn_new_owner_allowed": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
    }


@activity.defn
async def partial_continuation_dispatch_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    decision = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
    segment_gate = input_payload.get("segment_audit_gate") if isinstance(input_payload.get("segment_audit_gate"), dict) else {}
    next_worker = input_payload.get("segment_pass_next_worker") if isinstance(input_payload.get("segment_pass_next_worker"), dict) else {}
    next_worker_ok = next_worker.get("status") == "activity_gate_checked" and (
        next_worker.get("jsonl_exists") is True
        or next_worker.get("codex_jsonl_is_execution_evidence") is True
        or bool(next_worker.get("jsonl_path"))
    )
    implementation_worker_ok = bool(next_worker_ok and is_assignment_implementation_worker(next_worker))
    task_id = str(input_payload["task_id"])
    auto_signal = assignment_dag_auto_continue_signal(runtime_root, task_id, input_payload)
    auto_signal_fields = {
        "assignment_dag_auto_continue": bool(auto_signal),
        "auto_continue_same_workflow": bool(auto_signal),
        "auto_continue_same_task_signal": auto_signal,
        "auto_continue_next_ready_node_id": str(auto_signal.get("assignment_dag_node_id") or "") if auto_signal else "",
    }
    base = {
        "activity": "partial_continuation_dispatch",
        "completion_decision": decision,
        **continuation_authorization_fields(),
        "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("partial_continuation_dispatch_activity_readback"),
    }
    if decision.get("status") != "partial" or decision.get("stop_allowed") is True:
        output = {
            **base,
            "status": "skipped_completion_claim_not_partial",
            "continuation_dispatched": False,
        }
        write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "continuation_dispatch" / f"{task_id}.json", output)
        if next_worker_ok:
            owner_task = runtime_root / "state" / "current_task_owner" / f"{task_id}.json"
            owner_latest = runtime_root / "state" / "current_task_owner" / "latest.json"
            owner = read_json(owner_task, {})
            if not isinstance(owner, dict) or str(owner.get("task_id") or "") != task_id:
                latest_owner = read_json(owner_latest, {})
                owner = latest_owner if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == task_id else {"task_id": task_id}
            owner.update({
                "segment_pass_must_dispatch_next_bounded_worker": False if implementation_worker_ok else True,
                "assignment_driven_implementation_worker_dispatched": implementation_worker_ok,
                "segment_pass_phase_exit_checker_dispatched": bool(next_worker_ok and not implementation_worker_ok),
                "same_workflow_next_worker_dispatched": True,
                "same_workflow_next_worker_task_id": str(next_worker.get("worker_task_id") or ""),
                "same_workflow_next_worker_jsonl_path": str(next_worker.get("jsonl_path") or ""),
                "mainline_next_hop": same_workflow_next_hop(next_worker),
                "workflow_internal_timer_scheduled": False,
                "workflow_kept_open_by_durable_timer": False,
                "not_user_completion": True,
                "not_completion_decision": True,
            })
            write_json(owner_task, owner)
            latest_owner = read_json(owner_latest, {})
            if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == task_id:
                write_json(owner_latest, owner)
        return output
    if str(decision.get("segment_audit_status") or segment_gate.get("status") or "") == "GROK_SEGMENT_AUDIT_PASS":
        output = {
            **base,
            "status": (
                "assignment_driven_implementation_worker_dispatched"
                if implementation_worker_ok
                else "phase_exit_segment_pass_checker_dispatched"
                if next_worker_ok
                else "segment_pass_next_worker_blocked"
            ),
            "continuation_dispatched": bool(next_worker_ok),
            "external_continuation_worker_dispatched": False,
            "legacy_continuation_worker_allowed": False,
            "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
            "workflow_internal_timer_scheduled": False,
            "workflow_kept_open_by_durable_timer": False,
            "partial_frontier_open": True,
            "segment_pass_must_dispatch_next_bounded_worker": bool(not implementation_worker_ok),
            "assignment_driven_implementation_worker_dispatched": implementation_worker_ok,
            "segment_pass_phase_exit_checker_dispatched": bool(next_worker_ok and not implementation_worker_ok),
            "same_workflow_next_worker_dispatched": bool(next_worker_ok),
            "command_surface": "Temporal workflow activity -> same task Codex worker; implementation is assignment-driven, segment-pass is phase-exit checker only; no .continuation.N worker",
            "task_id": task_id,
            "worker_task_id": str(next_worker.get("worker_task_id") or ""),
            "worker_jsonl_path": str(next_worker.get("jsonl_path") or ""),
            "worker_final_path": str(next_worker.get("final_path") or ""),
            "mainline_next_hop": same_workflow_next_hop(next_worker),
            "next_required_activity": "GROK_SEGMENT_AUDIT_PASS + partial must stay in the same workflow; implementation comes only from WORKER_ASSIGNMENT, while segment-pass is phase-exit checker only.",
            "named_blocker": "" if next_worker_ok else str(next_worker.get("named_blocker") or "SEGMENT_PASS_WITHOUT_NEXT_BOUNDED_WORKER"),
            "segment_pass_next_worker": next_worker,
            **auto_signal_fields,
        }
        write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "continuation_dispatch" / f"{task_id}.json", output)
        return output
    if next_worker_ok and segment_gate_allows_l1_continuation(segment_gate):
        output = {
            **base,
            "status": "grok_wait_l1_continuation_worker_dispatched",
            "continuation_dispatched": True,
            "external_continuation_worker_dispatched": False,
            "legacy_continuation_worker_allowed": False,
            "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
            "workflow_internal_timer_scheduled": False,
            "workflow_kept_open_by_durable_timer": False,
            "partial_frontier_open": True,
            "workflow_waiting_signal": False,
            "workflow_waiting_grok_segment_audit": True,
            "grok_waiting_does_not_block_continuation": True,
            "completion_stop_l2_still_gated_by_grok": True,
            "segment_pass_must_dispatch_next_bounded_worker": False,
            "assignment_driven_implementation_worker_dispatched": implementation_worker_ok,
            "segment_pass_phase_exit_checker_dispatched": False,
            "same_workflow_next_worker_dispatched": True,
            "command_surface": "Temporal workflow activity -> same task Codex implementation worker; Grok verdict gates completion/Stop/L2 only.",
            "task_id": task_id,
            "worker_task_id": str(next_worker.get("worker_task_id") or ""),
            "worker_jsonl_path": str(next_worker.get("jsonl_path") or ""),
            "worker_final_path": str(next_worker.get("final_path") or ""),
            "mainline_next_hop": same_workflow_next_hop(next_worker),
            "next_required_activity": "Keep the same workflow running via assignment-driven implementation worker; Grok leg2 remains required only for completion, Stop, or L2 release.",
            "named_blocker": "",
            "segment_pass_next_worker": next_worker,
            **auto_signal_fields,
        }
        write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "continuation_dispatch" / f"{task_id}.json", output)
        return output
    if auto_signal:
        output = {
            **base,
            "status": "assignment_dag_auto_continue_signal_prepared",
            "continuation_dispatched": False,
            "external_continuation_worker_dispatched": False,
            "legacy_continuation_worker_allowed": False,
            "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
            "workflow_internal_timer_scheduled": False,
            "workflow_kept_open_by_durable_timer": False,
            "partial_frontier_open": True,
            "workflow_waiting_signal": False,
            "workflow_signal_name": "continue_same_task",
            "grok_waiting_does_not_block_continuation": True,
            "grok_segment_verdict_gates_completion_stop_l2_only": True,
            "one_segment_does_not_wait_for_user": True,
            "command_surface": "Temporal workflow internal assignment_dag auto-continue signal; no user scheduling, no new owner, no pump default.",
            "task_id": task_id,
            "worker_task_id": "",
            "next_required_activity": "Workflow must enqueue the prepared auto_continue_same_task_signal and dispatch the next assignment_dag node in the same workflow.",
            "named_blocker": "",
            **auto_signal_fields,
        }
        write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "continuation_dispatch" / f"{task_id}.json", output)
        return output
    output = {
        **base,
        "status": "l1_continuation_worker_not_dispatched_yet",
        "continuation_dispatched": False,
        "external_continuation_worker_dispatched": False,
        "legacy_continuation_worker_allowed": False,
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "workflow_internal_timer_scheduled": True,
        "workflow_kept_open_by_durable_timer": True,
        "partial_frontier_open": True,
        "workflow_waiting_signal": False,
        "workflow_signal_name": "continue_same_task",
        "grok_waiting_does_not_block_continuation": True,
        "grok_segment_verdict_gates_completion_stop_l2_only": True,
        "command_surface": "Temporal workflow stays open for same-task continue_same_task signal; Grok verdict gates completion/Stop/L2 only; no .continuation.N worker",
        "task_id": task_id,
        "worker_task_id": "",
        "partial_keepalive_sleep_seconds": int(input_payload.get("partial_keepalive_sleep_seconds") or PARTIAL_KEEPALIVE_SLEEP_SECONDS),
        "next_required_activity": "Dispatch or wait for a same-task continue_same_task implementation worker; do not wait for Grok verdict before L1 continuation.",
        "named_blocker": "L1_CONTINUATION_WORKER_NOT_DISPATCHED",
        **auto_signal_fields,
    }
    write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "continuation_dispatch" / f"{task_id}.json", output)
    return output


def _ledger_succeeded_count_from_activity(worker_ledger: dict[str, Any]) -> int:
    if not isinstance(worker_ledger, dict):
        return 0
    ledger_summary = (
        worker_ledger.get("ledger_summary")
        if isinstance(worker_ledger.get("ledger_summary"), dict)
        else {}
    )
    poll_summary = (
        worker_ledger.get("poll_result_summary")
        if isinstance(worker_ledger.get("poll_result_summary"), dict)
        else {}
    )
    return int(
        worker_ledger.get("ledger_succeeded_count")
        or ledger_summary.get("succeeded_count")
        or worker_ledger.get("succeeded_count")
        or poll_summary.get("succeeded_count")
        or 0
    )


def _ledger_runtime_enforced_from_activity(worker_ledger: dict[str, Any]) -> bool:
    if not isinstance(worker_ledger, dict):
        return False
    runtime_entrypoint = (
        worker_ledger.get("runtime_entrypoint_invocation")
        if isinstance(worker_ledger.get("runtime_entrypoint_invocation"), dict)
        else {}
    )
    hot_path = (
        worker_ledger.get("hot_path_binding")
        if isinstance(worker_ledger.get("hot_path_binding"), dict)
        else {}
    )
    return (
        worker_ledger.get("runtime_enforced") is True
        or runtime_entrypoint.get("runtime_enforced") is True
        or hot_path.get("runtime_enforced") is True
    )


def _worker_evidence_upstream_blocker(worker_evidence: Any) -> dict[str, Any]:
    if not isinstance(worker_evidence, list):
        return {}
    for item in worker_evidence:
        if not isinstance(item, dict):
            continue
        blocker = str(item.get("named_blocker") or "").strip()
        if not blocker:
            continue
        classification = (
            item.get("failure_classification")
            if isinstance(item.get("failure_classification"), dict)
            else {}
        )
        if not classification and isinstance(item.get("activator_result"), dict):
            activator_result = _activator_detail_payload(item["activator_result"])
            classification = (
                activator_result.get("failure_classification")
                if isinstance(activator_result.get("failure_classification"), dict)
                else {}
            )
        return {
            "named_blocker": blocker,
            "status": str(item.get("status") or ""),
            "worker_task_id": str(item.get("worker_task_id") or ""),
            "external_condition": item.get("external_condition") is True
            or classification.get("external_condition") is True,
            "retryable": item.get("retryable") is True
            or classification.get("retryable") is True,
            "retry_after_text": str(
                item.get("retry_after_text")
                or classification.get("retry_after_text")
                or ""
            ),
        }
    return {}


def select_primary_worker_dispatch_ledger_activity(activities: list[dict[str, Any]]) -> dict[str, Any]:
    ledgers = [item for item in activities if item.get("activity") == "worker_dispatch_ledger"]
    if not ledgers:
        return {}
    return next(
        (
            item
            for item in reversed(ledgers)
            if _ledger_runtime_enforced_from_activity(item)
            and _ledger_succeeded_count_from_activity(item) > 0
        ),
        ledgers[-1],
    )


def select_primary_ledger_auto_dispatch_ingress_activity(activities: list[dict[str, Any]]) -> dict[str, Any]:
    auto_dispatches = [
        item
        for item in activities
        if item.get("activity") == "ledger_auto_dispatch_ingress"
    ]
    if not auto_dispatches:
        return {}
    return next(
        (
            item
            for item in reversed(auto_dispatches)
            if item.get("status") == "auto_dispatch_ingress_enqueued"
            or (
                isinstance(item.get("validation"), dict)
                and item.get("validation", {}).get("passed") is True
            )
            or item.get("runtime_enforced") is True
        ),
        auto_dispatches[-1],
    )


@activity.defn
async def ledger_auto_dispatch_ingress_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "ledger_auto_dispatch_ingress",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_AUTO_DISPATCH_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
        }
    worker_ledger = (
        input_payload.get("worker_dispatch_ledger_activity")
        if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
        else {}
    )
    upstream_blocker = _worker_evidence_upstream_blocker(
        input_payload.get("worker_dispatch_evidence")
    )
    continuation = (
        input_payload.get("partial_continuation_dispatch")
        if isinstance(input_payload.get("partial_continuation_dispatch"), dict)
        else {}
    )
    prepared_signal = (
        continuation.get("auto_continue_same_task_signal")
        if isinstance(continuation.get("auto_continue_same_task_signal"), dict)
        else {}
    )
    current_wave_index = int(input_payload.get("wave_index") or 1)
    next_wave_index = current_wave_index + 1
    next_wave_id = temporal_hot_path_wave_id(
        input_payload,
        next_wave_index,
        prepared_signal,
    )
    ledger_succeeded_count = _ledger_succeeded_count_from_activity(worker_ledger)
    ledger_runtime_enforced = _ledger_runtime_enforced_from_activity(worker_ledger)
    should_dispatch = (
        ledger_runtime_enforced
        and ledger_succeeded_count > 0
        and bool(prepared_signal)
    )
    auto_signal = dict(prepared_signal) if should_dispatch else {}
    if auto_signal:
        canonical_repo = str(input_payload.get("repo_root") or _REPO_ROOT)
        auto_signal.update(
            {
                "source_kind": "worker_dispatch_ledger_auto_dispatch",
                "assignment_dag_source_kind": prepared_signal.get("source_kind")
                or "assignment_dag_auto_continue",
                "wave_id": next_wave_id,
                "temporal_hot_path_wave_index": next_wave_index,
                "runtime_root": str(runtime_root),
                "repo_root": canonical_repo,
                "workspace_hint": canonical_repo,
                "auto_dispatch_reason": "worker_ledger_succeeded",
                "worker_dispatch_ledger_succeeded_count": ledger_succeeded_count,
                "manual_cli_required": False,
                "watch_window_required": False,
                "completion_claim_allowed": False,
                "not_user_completion": True,
            }
        )
    status = (
        "auto_dispatch_ingress_enqueued"
        if should_dispatch
        else "auto_dispatch_waiting_assignment_signal"
        if ledger_runtime_enforced and ledger_succeeded_count > 0
        else "auto_dispatch_blocked_waiting_worker_ledger_succeeded"
    )
    named_blocker = ""
    if not ledger_runtime_enforced:
        named_blocker = "WORKER_DISPATCH_LEDGER_ACTIVITY_NOT_RUNTIME_ENFORCED"
    elif ledger_succeeded_count <= 0:
        named_blocker = str(
            upstream_blocker.get("named_blocker")
            or "WORKER_DISPATCH_LEDGER_NO_SUCCEEDED_POLL"
        )
    elif not prepared_signal:
        named_blocker = "ASSIGNMENT_DAG_NEXT_READY_SIGNAL_NOT_AVAILABLE"
    latest = runtime_root / "state" / "temporal_codex_task_workflow" / "auto_dispatch_latest.json"
    task_latest = (
        runtime_root
        / "state"
        / "temporal_codex_task_workflow"
        / "auto_dispatch"
        / f"{_safe_task_file_id(task_id)}.{_safe_task_file_id(str(input_payload.get('wave_id') or 'wave'))}.json"
    )
    default_latest = runtime_root / "state" / "default_auto_dispatch" / "latest.json"
    payload = {
        "activity": "ledger_auto_dispatch_ingress",
        "schema_version": "xinao.temporal_codex_task_workflow.ledger_auto_dispatch_ingress.v1",
        "status": status,
        "named_blocker": named_blocker,
        "task_id": task_id,
        "workflow_id": str(input_payload.get("workflow_id") or ""),
        "workflow_run_id": str(input_payload.get("workflow_run_id") or ""),
        "wave_id": str(input_payload.get("wave_id") or ""),
        "next_wave_id": next_wave_id,
        "current_wave_index": current_wave_index,
        "next_wave_index": next_wave_index,
        "source_kind": "worker_dispatch_ledger_poll",
        "dispatch_reason": "worker_ledger_succeeded" if should_dispatch else named_blocker,
        "upstream_named_blocker": upstream_blocker.get("named_blocker") or "",
        "upstream_worker_blocker_ref": upstream_blocker,
        "external_condition": upstream_blocker.get("external_condition") is True,
        "retryable": upstream_blocker.get("retryable") is True,
        "retry_after_text": upstream_blocker.get("retry_after_text") or "",
        "worker_dispatch_ledger_runtime_enforced": ledger_runtime_enforced,
        "worker_dispatch_ledger_succeeded_count": ledger_succeeded_count,
        "worker_dispatch_ledger_activity_ref": worker_ledger,
        "main_execution_loop_tick_activity_ref": input_payload.get("main_execution_loop_tick_activity")
        if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
        else {},
        "partial_continuation_dispatch_ref": continuation,
        "auto_continue_same_workflow": should_dispatch,
        "auto_continue_same_task_signal": auto_signal,
        "ingress": {
            "ingress_kind": "Temporal worker poll",
            "target_workflow_signal": "continue_same_task",
            "target_activity": "main_execution_loop_tick_activity",
            "manual_cli_required": False,
            "watch_window_required": False,
        },
        "runtime_enforced": should_dispatch,
        "runtime_enforced_scope": "seed_cortex_temporal_ledger_auto_dispatch_ingress",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "validation": {
            "passed": should_dispatch,
            "checks": {
                "worker_dispatch_ledger_runtime_enforced": ledger_runtime_enforced,
                "worker_dispatch_ledger_succeeded_present": ledger_succeeded_count > 0,
                "prepared_continue_signal_present": bool(prepared_signal),
                "upstream_external_condition_named": (
                    upstream_blocker.get("external_condition") is True
                    and bool(upstream_blocker.get("named_blocker"))
                ),
                "manual_cli_required_false": True,
                "watch_window_required_false": True,
            },
        },
        "output_paths": {
            "latest": str(latest),
            "task_latest": str(task_latest),
            "default_auto_dispatch_latest": str(default_latest),
        },
        "written_at": now(),
    }
    write_json(latest, payload)
    write_json(task_latest, payload)
    write_json(default_latest, payload)
    write_json(
        runtime_root / "state" / "worker_assignment_dynamic_fanout" / "latest.json",
        {
            "schema_version": "xinao.worker_assignment_dynamic_fanout.v1",
            "status": "auto_dispatch_ingress_enqueued"
            if should_dispatch
            else "auto_dispatch_waiting",
            "task_id": task_id,
            "workflow_id": payload["workflow_id"],
            "wave_id": payload["wave_id"],
            "next_wave_id": next_wave_id,
            "worker_running": should_dispatch,
            "temporal_pending_activity": should_dispatch,
            "next_ready": should_dispatch,
            "auto_continue_expected": should_dispatch,
            "source_kind": "worker_dispatch_ledger_auto_dispatch",
            "worker_dispatch_ledger_activity_ref": str(
                worker_ledger.get("ledger_temporal_activity_latest_ref")
                or worker_ledger.get("ledger_latest_ref")
                or (
                    worker_ledger.get("output_paths", {}).get("runtime_latest")
                    if isinstance(worker_ledger.get("output_paths"), dict)
                    else ""
                )
                or ""
            ),
            "main_execution_loop_tick_activity_ref": str(
                input_payload.get("main_execution_loop_tick_activity", {}).get(
                    "tick_temporal_activity_latest_ref", ""
                )
                if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
                else ""
            ),
            "auto_dispatch_latest": str(latest),
            "repo_root": str(input_payload.get("repo_root") or _REPO_ROOT),
            "runtime_root": str(runtime_root),
            "manual_cli_required": False,
            "watch_window_required": False,
            "completion_claim_allowed": False,
            "not_user_completion": True,
        },
    )
    return payload


@activity.defn
async def write_status_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    output = {
        "activity": "write_status",
        "status": "status_written_after_completion_decision",
        "completion_decision": input_payload["completion_decision"],
        "canonical_completion_source": "/completion/claim",
        "temporal_workflow_completed_is_not_user_complete": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("derived_temporal_status_write"),
    }
    write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "activity_status_latest.json", output)
    return output


@activity.defn
async def segment_audit_gate_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    task_id = str(input_payload["task_id"])
    ready_projection = _materialize_segment_audit_ready_if_needed(runtime_root, task_id, input_payload)
    segment_gate = l1_l2_segment_gate.evaluate_task_l1_l2_segment_gate(
        runtime_root=runtime_root,
        task_id=task_id,
    )
    audit_request = _write_grok_segment_audit_request_if_ready(runtime_root, task_id, segment_gate)
    if not audit_request:
        audit_request = _read_grok_segment_audit_request(runtime_root, task_id)
    pre_summon_human_egress = _write_grok_human_egress_report(
        runtime_root,
        task_id,
        {
            "task_id": task_id,
            "segment_audit_status_cn": "等 Grok 审查",
            "workflow_waiting_grok_segment_audit": segment_gate.get("workflow_waiting_grok_segment_audit"),
            "codex_to_grok_segment_audit_summon_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_ref") or ""),
        },
        segment_gate,
        source="segment_audit_gate_activity.pre_summon",
    )
    summon = _send_codex_segment_audit_summon_to_grok(
        runtime_root,
        task_id,
        segment_gate,
        source="segment_audit_gate_activity",
    )
    output = {
        "activity": "segment_audit_gate",
        "status": segment_gate["status"],
        "task_id": task_id,
        "segment_id": segment_gate["segment_id"],
        "segment_complete_seen": bool(ready_projection.get("segment_complete_seen") or input_payload.get("segment_complete")),
        "segment_audit_ready": segment_gate["segment_audit_ready"],
        "segment_audit_ready_projection_written": bool(ready_projection),
        "segment_audit_ready_projection_ref": str(runtime_root / "state" / "l1_l2_segment_gate" / "tasks" / f"{task_id}.json") if ready_projection else "",
        "segment_audit_hotpath": "segment_complete_to_segment_audit_ready_wait_grok",
        "segment_audit_boundary_cn": "TUI/worker 不能自停；Grok dual verdict 前禁止 Stop/L2/completion。",
        "grok_segment_audit_request_ref": str(audit_request.get("request_ref") or ""),
        "grok_segment_audit_request_written": bool(audit_request),
        "audit_authorization_pull_requested": audit_request.get("audit_authorization_pull_requested") is True,
        "audit_authorization_pull_ref": str(audit_request.get("audit_authorization_pull_ref") or ""),
        "audit_authorization_pull_latest_ref": str(audit_request.get("audit_authorization_pull_latest_ref") or ""),
        "auto_review_requested": audit_request.get("auto_review_requested") is True,
        "grok_auto_review_requested": audit_request.get("grok_auto_review_requested") is True,
        "codex_to_grok_segment_audit_summon_ref": str(summon.get("task_ref") or summon.get("backend_task_ref") or ""),
        "codex_to_grok_segment_audit_summon_latest_ref": str(summon.get("latest_ref") or summon.get("backend_latest_ref") or ""),
        "codex_to_grok_segment_audit_summon_written": bool(summon),
        "codex_to_grok_segment_audit_summon_delivery_mode": str(summon.get("delivery_mode") or ""),
        "codex_to_grok_segment_audit_summon_visible_ref": str(summon.get("visible_ref") or ""),
        "codex_to_grok_segment_audit_summon_visible_trace_ref": str(summon.get("visible_trace_ref") or ""),
        "codex_to_grok_segment_audit_summon_cross_check": summon.get("cross_check") if isinstance(summon.get("cross_check"), dict) else {},
        "human_egress_report_written_before_summon": bool(pre_summon_human_egress),
        "human_egress_router_ref": str(pre_summon_human_egress.get("router_task_ref") or ""),
        "grok_report_ref": str(pre_summon_human_egress.get("grok_report_ref") or ""),
        "egress_before_summon_order": "human_egress_report_then_leg1_summon" if pre_summon_human_egress else "",
        "codex_to_grok_segment_audit_summon_required": segment_gate.get("codex_to_grok_segment_audit_summon_required") is True,
        "codex_to_grok_segment_audit_summon_valid": segment_gate.get("codex_to_grok_segment_audit_summon_valid") is True,
        "codex_to_grok_segment_audit_summon_existing_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_ref") or ""),
        "grok_segment_verdict_leg2_required": segment_gate.get("grok_segment_verdict_leg2_required") is True,
        "grok_segment_verdict_leg2_valid": segment_gate.get("grok_segment_verdict_leg2_valid") is True,
        "grok_waiting_does_not_block_continuation": segment_gate.get("grok_waiting_does_not_block_continuation") is True,
        "grok_segment_verdict_gates_completion_stop_l2_only": segment_gate.get("grok_segment_verdict_gates_completion_stop_l2_only") is True,
        "grok_segment_verdict_wait_blocking": segment_gate.get("grok_segment_verdict_wait_blocking") is True,
        "bidirectional_dual_delivery_full_ring_valid": segment_gate.get("bidirectional_dual_delivery_full_ring_valid") is True,
        "l2_release_allowed": segment_gate.get("l2_release_allowed") is True,
        "notify_v1_rescue_only": True,
        "notify_v1_default_mainline": False,
        "grok_notified": audit_request.get("grok_notified") is True,
        "grok_chat_window_push_allowed": False,
        "automatic_verdict_allowed": False,
        "workflow_waiting_grok_segment_audit": segment_gate["workflow_waiting_grok_segment_audit"],
        "workflow_open_required": bool(segment_gate["segment_audit_ready"]),
        "grok_verdict": segment_gate["grok_verdict"],
        "verdict_delivery_mode": segment_gate["verdict_delivery_mode"],
        "dual_visible_and_backend_required": True,
        "codex_to_grok_visible_frontend_required": False,
        "codex_to_grok_visible_frontend_disabled_by_stop_order": segment_gate.get("codex_to_grok_visible_frontend_disabled_by_stop_order") is True,
        "grok_visible_delivery_auto_open_allowed": False,
        "grok_reads_state_only_when_user_requests_review": False,
        "dual_visible_and_backend_verdict": segment_gate["dual_visible_and_backend_verdict"],
        "backend_only_verdict_allowed": False,
        "backend_only_verdict_seen": segment_gate["backend_only_verdict_seen"],
        "tui_self_stop_allowed": False,
        "completion_claim_allowed": False,
        "stop_allowed_without_grok_pass": False,
        "continuation_n_segment_audit_pass_allowed": segment_gate["continuation_n_segment_audit_pass_allowed"],
        "next_lane": segment_gate["next_lane"],
        "named_blocker": segment_gate["named_blocker"],
        "grok_reply_timeout_seconds": segment_gate.get("grok_reply_timeout_seconds"),
        "grok_request_age_seconds": segment_gate.get("grok_request_age_seconds"),
        "codexa_brain_fallback_allowed": segment_gate.get("codexa_brain_fallback_allowed") is True,
        "codexa_brain_fallback_active": segment_gate.get("codexa_brain_fallback_active") is True,
        "codexa_brain_fallback_is_l2": segment_gate.get("codexa_brain_fallback_is_l2") is True,
        "gate_latest_ref": segment_gate["gate_latest_ref"],
        "gate_task_ref": segment_gate.get("gate_task_ref", ""),
        "grok_gate_ref": segment_gate["grok_gate_ref"],
        "grok_latest_stale_for_task": segment_gate.get("grok_latest_stale_for_task") is True,
        "segment_gate_source": segment_gate.get("segment_gate_source", ""),
        "grok_gate_source": segment_gate.get("grok_gate_source", ""),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("segment_audit_gate_read_model"),
    }
    grok_request = _write_grok_segment_audit_request_if_ready(runtime_root, task_id, output)
    if grok_request:
        output["grok_segment_audit_request_ref"] = grok_request.get("request_latest_ref", "")
        output["grok_segment_audit_request_task_ref"] = grok_request.get("request_task_ref", "")
        output["audit_authorization_pull_requested"] = grok_request.get("audit_authorization_pull_requested") is True
        output["audit_authorization_pull_ref"] = str(grok_request.get("audit_authorization_pull_ref") or "")
        output["audit_authorization_pull_latest_ref"] = str(grok_request.get("audit_authorization_pull_latest_ref") or "")
        output["auto_review_requested"] = grok_request.get("auto_review_requested") is True
        output["grok_auto_review_requested"] = grok_request.get("grok_auto_review_requested") is True
        output["next_human_action_cn"] = grok_request.get("next_human_action_cn", "")
        output["user_must_copy_tui"] = False
    if not output["codex_to_grok_segment_audit_summon_written"]:
        summon = _send_codex_segment_audit_summon_to_grok(
            runtime_root,
            task_id,
            output,
            source="segment_audit_gate_activity.output",
        )
        if summon:
            output["codex_to_grok_segment_audit_summon_ref"] = str(summon.get("task_ref") or summon.get("backend_task_ref") or "")
            output["codex_to_grok_segment_audit_summon_latest_ref"] = str(summon.get("latest_ref") or summon.get("backend_latest_ref") or "")
            output["codex_to_grok_segment_audit_summon_written"] = True
            output["codex_to_grok_segment_audit_summon_delivery_mode"] = str(summon.get("delivery_mode") or "")
            output["codex_to_grok_segment_audit_summon_visible_ref"] = str(summon.get("visible_ref") or "")
            output["codex_to_grok_segment_audit_summon_visible_trace_ref"] = str(summon.get("visible_trace_ref") or "")
            output["codex_to_grok_segment_audit_summon_cross_check"] = summon.get("cross_check") if isinstance(summon.get("cross_check"), dict) else {}
            output["auto_review_requested"] = output.get("auto_review_requested") is True or summon.get("auto_review_requested") is True
            output["grok_auto_review_requested"] = output.get("grok_auto_review_requested") is True or summon.get("grok_auto_review_requested") is True
            output["audit_authorization_pull_ref"] = str(output.get("audit_authorization_pull_ref") or summon.get("audit_authorization_pull_ref") or "")
            output["audit_authorization_pull_latest_ref"] = str(output.get("audit_authorization_pull_latest_ref") or summon.get("audit_authorization_pull_latest_ref") or "")
            output["audit_authorization_pull_requested"] = bool(output.get("audit_authorization_pull_ref"))
    if not output["codex_to_grok_segment_audit_summon_ref"]:
        output["codex_to_grok_segment_audit_summon_ref"] = output["codex_to_grok_segment_audit_summon_existing_ref"]
    _sync_l1_l2_segment_gate_evaluation(runtime_root, task_id, output)
    _sync_current_owner_segment_audit_state(runtime_root, task_id, output)
    write_json(runtime_root / "state" / "temporal_codex_task_workflow" / "segment_audit" / f"{task_id}.json", output)
    return output


@activity.defn
async def panel_writeback_zh_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    task_id = str(input_payload["task_id"])
    decision = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
    continuation = input_payload.get("partial_continuation_dispatch") if isinstance(input_payload.get("partial_continuation_dispatch"), dict) else {}
    segment_gate = input_payload.get("segment_audit_gate") if isinstance(input_payload.get("segment_audit_gate"), dict) else {}
    worker = input_payload.get("worker_dispatch_evidence") if isinstance(input_payload.get("worker_dispatch_evidence"), dict) else {}
    next_worker = input_payload.get("segment_pass_next_worker") if isinstance(input_payload.get("segment_pass_next_worker"), dict) else {}
    observe_source_worker = next_worker if next_worker.get("status") == "activity_gate_checked" else worker
    observe = jobs_json_observe_from_worker_result(observe_source_worker)
    phase5_readback = phase5_observability_discovery_panel_readback(
        runtime_root,
        task_id,
        str(input_payload.get("workflow_id") or ""),
        str(input_payload.get("workflow_run_id") or ""),
        str(observe_source_worker.get("jsonl_path") or ""),
    )
    worker_ok = worker.get("status") == "activity_gate_checked" or worker.get("expected_marker_seen") is True
    next_worker_ok = next_worker.get("status") == "activity_gate_checked" and next_worker.get("jsonl_exists") is True
    next_worker_is_implementation = is_assignment_implementation_worker(next_worker)
    continuation_ok = continuation.get("continuation_dispatched") is True
    internal_timer_ok = continuation.get("workflow_internal_timer_scheduled") is True
    owner_only = input_payload.get("execute_codex_worker") is not True
    summary = (
        "已进入 Temporal/current_task_owner；已派 assignment-driven implementation worker；这不是用户完成。"
        if next_worker_ok and next_worker_is_implementation
        else "已进入 Temporal/current_task_owner；阶段末 segment-pass checker 已派出；这不是用户完成。"
        if next_worker_ok
        else "已进入 Temporal/current_task_owner；A 的 task-bound worker 有证据；这不是用户完成。"
        if worker_ok
        else (
            "已进入 Temporal/current_task_owner；本轮 owner_only 未派 worker，不能当作完成。"
            if owner_only
            else "已进入 Temporal/current_task_owner；A 的 task-bound worker 证据还不完整，不能当作完成。"
        )
    )
    if worker.get("named_blocker"):
        blocked = f"卡在哪：{worker.get('named_blocker')}"
    elif owner_only:
        blocked = "卡在哪：owner_only 路径按要求未派 worker；仍需后续真实验收面。"
    else:
        blocked = "没有命名 blocker；机器仍按当前 task_id 继续收敛。"
    segment_lane = str(
        decision.get("segment_audit_next_lane")
        or ("L2" if segment_gate.get("status") == "GROK_SEGMENT_AUDIT_PASS" else "L1")
    )
    segment_passed = segment_gate.get("status") == "GROK_SEGMENT_AUDIT_PASS"
    waiting_grok_segment_audit = bool(segment_gate.get("workflow_waiting_grok_segment_audit")) and not segment_passed
    audit_request = _read_grok_segment_audit_request(runtime_root, task_id)
    waiting_label = "是" if waiting_grok_segment_audit else "否"
    if not segment_gate.get("segment_audit_ready"):
        segment_lane = "L1"
    if continuation_ok and next_worker_ok and waiting_grok_segment_audit:
        if next_worker_is_implementation:
            next_line = f"同 workflow 已派 WORKER_ASSIGNMENT 驱动的 L1 implementation worker：{next_worker.get('worker_task_id')}；JSONL 已写入；系统已自动拉 Grok 审核/授权，Grok 只继续卡完成/Stop/L2。"
        else:
            next_line = f"同 workflow 已派 bounded worker：{next_worker.get('worker_task_id')}；JSONL 已写入；系统已自动拉 Grok 审核/授权，Grok 只继续卡完成/Stop/L2。"
        blocked = f"卡在哪：系统已自动拉 Grok 审核/授权；Grok leg2 verdict 尚未闭合，所以不能 Stop/L2/completion claim；但不再阻断同 workflow L1 续跑。blocker={segment_gate.get('named_blocker') or ''}"
    elif segment_gate.get("status") in {
        "WAITING_GROK_SEGMENT_AUDIT",
        "GROK_SEGMENT_AUDIT_FAIL",
        "GROK_SEGMENT_AUDIT_HOLD",
        "segment_audit_not_ready",
        "GROK_SEGMENT_AUDIT_TIMEOUT_CODEXA_BRAIN_FALLBACK",
    }:
        if segment_gate.get("codexa_brain_fallback_active") is True:
            next_line = "Grok 3 分钟无回复或连不上，CodexA 暂接 brain 继续 L1 修复；这不是 L2/Stop/完成。"
        else:
            next_line = f"系统已自动拉 Grok 审核/授权；Grok 可在桥接可用时自动审 evidence 并双投递 verdict 回 Codex；双投递 PASS 前禁止 Stop/L2/completion claim；当前 L1/L2 = {segment_lane}。"
        blocked = f"卡在哪：leg1/notify 已登记；自动拉审已发出；等待 Grok leg2 verdict，用户无需复制 TUI；旧 WAITING/notify v1 挂牌不算成功；blocker={segment_gate.get('named_blocker') or ''}"
    elif continuation_ok and next_worker_ok:
        if next_worker_is_implementation:
            next_line = f"同 workflow 已派 WORKER_ASSIGNMENT 驱动的 implementation worker：{next_worker.get('worker_task_id')}；JSONL 已写入，仍保持 partial。"
        else:
            next_line = f"阶段末 segment-pass checker 已在同 workflow 派出：{next_worker.get('worker_task_id')}；JSONL 已写入，仍保持 partial。"
        blocked = "卡在哪：无停机 blocker；段审 pass 后已自动续跑，仍需后续 completion claim 和用户可见验收。"
    elif continuation_ok:
        next_line = "partial 后同 workflow continuation 已登记；不得把 worker PASS 当用户完成。"
    elif segment_gate.get("status") == "GROK_SEGMENT_AUDIT_PASS":
        next_line = f"segment 审计已通过（同 task leg1+leg2 整环）；下一段意图为 {segment_lane}，仍保持 partial，不能直接完成。"
    elif internal_timer_ok:
        next_line = "partial 后 workflow 已保持 OPEN，并由 Temporal durable timer/signal wait 承接下一跳；continuation.N 只能 legacy rescue。"
    elif owner_only:
        next_line = "owner_only 已写 current_task_owner；下一步按用户授权再派 worker 或继续 Lobe 眼门验收。"
    elif decision.get("status") == "partial":
        next_line = "partial 但 continuation 未派发；继续读取 completion claim、worker evidence 和 side audit。"
    else:
        next_line = "继续读取 completion claim、worker evidence 和 side audit，再决定下一机器动作。"
    blocked_detail = blocked[len("卡在哪："):] if blocked.startswith("卡在哪：") else blocked
    if segment_passed:
        blocked_line = f"卡在哪：旧 inbox-only/notify v1 只是 rescue/compat；段审已通过，Grok leg2 verdict 已闭合；{blocked_detail or '无 blocker。'}"
    else:
        blocked_line = f"卡在哪：旧 inbox-only/notify v1 只是 rescue/compat；等待 Grok leg2 verdict/段审：{waiting_label}；{blocked_detail or '无 blocker。'}"
    segment_audit_status_cn = (
        "段审状态：等待 Grok 审查"
        if waiting_grok_segment_audit
        else "通过" if segment_passed
        else "段审状态：失败" if segment_gate.get("status") == "GROK_SEGMENT_AUDIT_FAIL"
        else "段审状态：未就绪"
    )
    next_human_action_cn = ""
    grok_request_ref = str(segment_gate.get("grok_segment_audit_request_ref") or "")
    payload = {
        "schema_version": "xinao.codexa_intent_user_visible_status.v1",
        "task_id": task_id,
        "status_cn": summary,
        "user_visible_summary_cn": summary,
        "panel_lines_cn": {
            "status_line_cn": f"一句话状态：双投递已启用；旧 inbox-only 只是 rescue/compat，新链路是 dual_visible_and_backend；当前 L1/L2 = {segment_lane}。",
            "blocked_line_cn": blocked_line,
            "next_line_cn": "下一跳：下一机器动作：" + next_line,
            "segment_audit_status_cn": segment_audit_status_cn,
            "next_human_action_cn": next_human_action_cn,
        },
        "segment_audit_status_cn": segment_audit_status_cn,
        "next_human_action_cn": next_human_action_cn,
        "grok_segment_audit_request_ref": grok_request_ref,
        "user_must_copy_tui": False if waiting_grok_segment_audit else bool(segment_gate.get("user_must_copy_tui") or False),
        "status_line_cn": f"一句话状态：双投递已启用；旧 inbox-only 只是 rescue/compat，新链路是 dual_visible_and_backend；当前 L1/L2 = {segment_lane}。",
        "blocked_line_cn": blocked_line,
        "next_line_cn": "下一跳：下一机器动作：" + next_line,
        "route": "codex-a-intent",
        "route_id": "codex-a-intent",
        "route_endpoint": "/codex-a/intent",
        "default_write_endpoint": "/codex-a/intent",
        "workflow_id": str(input_payload.get("workflow_id") or ""),
        "workflow_run_id": str(input_payload.get("workflow_run_id") or ""),
        "backend_codex_worker_dispatch": worker_ok,
        "worker_jsonl_path": str(worker.get("jsonl_path") or ""),
        "worker_final_path": str(worker.get("final_path") or ""),
        "human_egress_filter_ref": str(worker.get("human_egress_filter_ref") or ""),
        "jobs_json_observe_backend_readback": observe,
        "jobs_json_observe_joined": bool(observe),
        "task_bound_worker_token_usage": observe.get("token_usage", {}) if observe else {},
        "task_bound_worker_files_modified": observe.get("files_modified", []) if observe else [],
        "task_bound_worker_command_executions": observe.get("command_executions", []) if observe else [],
        "backend_evidence_refs": {
            "worker_jsonl_backend_evidence": str(observe_source_worker.get("jsonl_path") or ""),
            "worker_final_backend_only": str(observe_source_worker.get("final_path") or ""),
            "worker_raw_final_backend_only": str(observe_source_worker.get("raw_final_path") or ""),
            "human_egress_filter_ref": str(observe_source_worker.get("human_egress_filter_ref") or ""),
            "jobs_json_observe_backend_readback": bool(observe),
            "phase5_observability_discovery_readback": True,
            "observability_discovery_evidence_refs": phase5_readback["evidence_refs"],
        },
        "phase5_observability_discovery_readback": phase5_readback,
        "observability_discovery_refs_joined": bool(phase5_readback["task_workflow_correlated"]),
        "trace_catalog_model_refs_are_evidence_only": True,
        "progress_truth_sources": phase5_readback["progress_truth_sources"],
        "observability_discovery_truth_promotion_denied_reason": phase5_readback["truth_promotion_denied_reason"],
        "current_task_owner_replacement_allowed": False,
        "partial_continuation_dispatched": continuation_ok,
        "partial_continuation_ref": str(continuation.get("worker_task_id") or ""),
        "partial_continuation_dispatch": continuation,
        "workflow_internal_timer_scheduled": internal_timer_ok,
        "workflow_kept_open_by_durable_timer": internal_timer_ok,
        "mainline_next_hop": same_workflow_next_hop(next_worker, timer_wait=internal_timer_ok),
        "segment_pass_must_dispatch_next_bounded_worker": bool(
            segment_gate.get("status") == "GROK_SEGMENT_AUDIT_PASS"
            and next_worker_ok
            and not is_assignment_implementation_worker(next_worker)
        ),
        "assignment_driven_implementation_worker_dispatched": bool(next_worker_ok and is_assignment_implementation_worker(next_worker)),
        "segment_pass_phase_exit_checker_dispatched": bool(next_worker_ok and not is_assignment_implementation_worker(next_worker)),
        "same_workflow_next_worker_dispatched": bool(next_worker_ok),
        "same_workflow_next_worker_task_id": str(next_worker.get("worker_task_id") or ""),
        "same_workflow_next_worker_jsonl_path": str(next_worker.get("jsonl_path") or ""),
        "segment_pass_next_worker": next_worker,
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "segment_audit_gate": segment_gate,
        "grok_segment_audit_request_ref": str(audit_request.get("request_ref") or ""),
        "grok_segment_audit_request_written": bool(audit_request),
        "audit_authorization_pull_requested": segment_gate.get("audit_authorization_pull_requested") is True or audit_request.get("audit_authorization_pull_requested") is True,
        "audit_authorization_pull_ref": str(segment_gate.get("audit_authorization_pull_ref") or audit_request.get("audit_authorization_pull_ref") or ""),
        "audit_authorization_pull_latest_ref": str(segment_gate.get("audit_authorization_pull_latest_ref") or audit_request.get("audit_authorization_pull_latest_ref") or ""),
        "auto_review_requested": segment_gate.get("auto_review_requested") is True or audit_request.get("auto_review_requested") is True,
        "grok_auto_review_requested": segment_gate.get("grok_auto_review_requested") is True or audit_request.get("grok_auto_review_requested") is True,
        "grok_can_auto_review_when_bridge_available": segment_gate.get("grok_can_auto_review_when_bridge_available") is True or audit_request.get("grok_can_auto_review_when_bridge_available") is True,
        "grok_bridge_unavailable_means_request_queued_not_user_handoff": segment_gate.get("grok_bridge_unavailable_means_request_queued_not_user_handoff") is True or audit_request.get("grok_bridge_unavailable_means_request_queued_not_user_handoff") is True,
        "notify_v1_default_retired": True,
        "notify_v1_rescue_only": True,
        "notify_v1_default_mainline": False,
        "notify_pending_as_mainline": False,
        "codex_to_grok_segment_audit_summon_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_ref") or ""),
        "codex_to_grok_segment_audit_summon_latest_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_latest_ref") or ""),
        "codex_to_grok_segment_audit_summon_written": bool(segment_gate.get("codex_to_grok_segment_audit_summon_written")),
        "codex_to_grok_segment_audit_summon_delivery_mode": str(segment_gate.get("codex_to_grok_segment_audit_summon_delivery_mode") or ""),
        "codex_to_grok_segment_audit_summon_visible_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_visible_ref") or ""),
        "codex_to_grok_segment_audit_summon_visible_trace_ref": str(segment_gate.get("codex_to_grok_segment_audit_summon_visible_trace_ref") or ""),
        "codex_to_grok_segment_audit_summon_cross_check": segment_gate.get("codex_to_grok_segment_audit_summon_cross_check")
        if isinstance(segment_gate.get("codex_to_grok_segment_audit_summon_cross_check"), dict)
        else {},
        "bidirectional_dual_delivery_full_ring_valid": bool(segment_gate.get("bidirectional_dual_delivery_full_ring_valid")),
        "l2_release_allowed": bool(segment_gate.get("l2_release_allowed")),
        "grok_notified": audit_request.get("grok_notified") is True,
        "grok_chat_window_push_allowed": False,
        "grok_reads_state_only_when_user_requests_review": False,
        "user_requested_grok_review_required": False,
        "automatic_verdict_allowed": False,
        "segment_audit_ready": bool(segment_gate.get("segment_audit_ready")),
        "workflow_waiting_grok_segment_audit": bool(segment_gate.get("workflow_waiting_grok_segment_audit")),
        "bidirectional_dual_delivery_full_ring_valid": bool(segment_gate.get("bidirectional_dual_delivery_full_ring_valid")),
        "grok_segment_verdict_leg2_valid": bool(segment_gate.get("grok_segment_verdict_leg2_valid")),
        "grok_verdict": str(segment_gate.get("grok_verdict") or ""),
        "verdict_delivery_mode": str(segment_gate.get("verdict_delivery_mode") or ""),
        "backend_only_verdict_allowed": False,
        "tui_self_stop_allowed": False,
        "completion_claim_allowed": False,
        "stop_allowed_without_grok_pass": False,
        "completion_decision": decision,
        "can_user_use_now": True,
        "can_user_use_scope_cn": "只能从 panel 中文状态看见当前在跑/卡哪和下一机器动作；不代表系统完成或用户完成。",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "authority_boundary": authority_boundary("temporal_panel_writeback_zh_read_model"),
        "updated_at": now(),
    }
    human_egress = _write_grok_human_egress_report(
        runtime_root,
        task_id,
        payload,
        segment_gate,
        source="temporal_panel_writeback_zh_activity",
    )
    if human_egress:
        payload.update({
            "human_egress_route": "grok_report_only",
            "human_egress_router_ref": str(human_egress.get("router_task_ref") or ""),
            "grok_report_ref": str(human_egress.get("grok_report_ref") or ""),
            "grok_report_latest_ref": str(human_egress.get("grok_report_latest_ref") or ""),
            "grok_report_inbox_ref": str(human_egress.get("grok_report_inbox_ref") or ""),
            "grok_report_written": True,
            "grok_report_verify_pass": human_egress.get("grok_report_verify_pass") is True,
            "desktop_grok_existing_context_preferred": True,
            "shortcut_allowed_when_no_existing_context": True,
            "desktop_grok_context_gate": str(human_egress.get("desktop_grok_context_gate") or ""),
            "desktop_grok_context_reused": human_egress.get("desktop_grok_context_reused") is True,
            "desktop_context_continuity_verified": human_egress.get("desktop_context_continuity_verified") is True,
            "pre_existing_grok_tui_found": human_egress.get("pre_existing_grok_tui_found") is True,
            "used_existing_grok_tui": human_egress.get("used_existing_grok_tui") is True,
            "shortcut_launched": human_egress.get("shortcut_launched") is True,
            "shortcut_started_new_session": human_egress.get("shortcut_started_new_session") is True,
            "shortcut_bypassed_existing_grok": human_egress.get("shortcut_bypassed_existing_grok") is True,
            "context_loss_risk": human_egress.get("context_loss_risk") is True,
            "consumer_egress_blocked": human_egress.get("consumer_egress_blocked") is True,
            "consumer_egress_blocker": str(human_egress.get("consumer_egress_blocker") or ""),
            "codex_final_to_user_allowed": False,
            "worker_final_user_visible_allowed": False,
            "worker_final_backend_evidence_only": True,
            "no_pytest_wall_to_user": True,
            "panel_user_face_policy": "grok_report_reference_only",
            "human_egress_router": human_egress,
        })
        payload["can_user_use_scope_cn"] = "用户中文状态源为 Grok report；Codex worker final/pytest/JSONL 只保留后台证据，不直出给用户。"
        payload = _apply_human_egress_policy_to_panel_payload(payload, human_egress)
    panel_dir = runtime_root / "state" / "codex_a_panel_readback"
    write_json(panel_dir / "tasks" / f"{task_id}.json", payload)
    if input_payload.get("promote_current_task_owner_latest", True) is not False:
        write_json(panel_dir / "latest_intent_status.json", payload)
    if next_worker_ok or human_egress:
        owner_task = runtime_root / "state" / "current_task_owner" / f"{task_id}.json"
        owner_latest = runtime_root / "state" / "current_task_owner" / "latest.json"
        owner = read_json(owner_task, {})
        if not isinstance(owner, dict) or str(owner.get("task_id") or "") != task_id:
            latest_owner = read_json(owner_latest, {})
            owner = latest_owner if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == task_id else {"task_id": task_id}
        owner_update = {
            "human_egress_route": str(payload.get("human_egress_route") or owner.get("human_egress_route") or ""),
            "human_egress_router_ref": str(payload.get("human_egress_router_ref") or owner.get("human_egress_router_ref") or ""),
            "grok_report_ref": str(payload.get("grok_report_ref") or owner.get("grok_report_ref") or ""),
            "grok_report_verify_pass": payload.get("grok_report_verify_pass") is True or owner.get("grok_report_verify_pass") is True,
            "codex_final_to_user_allowed": False,
            "worker_final_user_visible_allowed": False,
            "worker_final_backend_evidence_only": True,
            "no_pytest_wall_to_user": payload.get("no_pytest_wall_to_user") is True or owner.get("no_pytest_wall_to_user") is True,
            "jobs_json_observe_backend_readback": payload.get("jobs_json_observe_backend_readback") if isinstance(payload.get("jobs_json_observe_backend_readback"), dict) else owner.get("jobs_json_observe_backend_readback", {}),
            "jobs_json_observe_joined": payload.get("jobs_json_observe_joined") is True or owner.get("jobs_json_observe_joined") is True,
            "task_bound_worker_token_usage": payload.get("task_bound_worker_token_usage") if isinstance(payload.get("task_bound_worker_token_usage"), dict) else owner.get("task_bound_worker_token_usage", {}),
            "task_bound_worker_files_modified": payload.get("task_bound_worker_files_modified") if isinstance(payload.get("task_bound_worker_files_modified"), list) else owner.get("task_bound_worker_files_modified", []),
            "task_bound_worker_command_executions": payload.get("task_bound_worker_command_executions") if isinstance(payload.get("task_bound_worker_command_executions"), list) else owner.get("task_bound_worker_command_executions", []),
            "backend_evidence_refs": payload.get("backend_evidence_refs") if isinstance(payload.get("backend_evidence_refs"), dict) else owner.get("backend_evidence_refs", {}),
            "backend_only_verdict_allowed": False,
            "mainline_next_hop": same_workflow_next_hop(next_worker) if next_worker_ok else str(owner.get("mainline_next_hop") or ""),
            "workflow_internal_timer_scheduled": False,
            "workflow_kept_open_by_durable_timer": False,
            "not_user_completion": True,
            "not_completion_decision": True,
        }
        if next_worker_ok:
            implementation_worker_ok = is_assignment_implementation_worker(next_worker)
            owner_update.update({
                "segment_pass_must_dispatch_next_bounded_worker": False if implementation_worker_ok else True,
                "assignment_driven_implementation_worker_dispatched": implementation_worker_ok,
                "segment_pass_phase_exit_checker_dispatched": not implementation_worker_ok,
                "same_workflow_next_worker_dispatched": True,
                "same_workflow_next_worker_task_id": str(next_worker.get("worker_task_id") or ""),
                "same_workflow_next_worker_jsonl_path": str(next_worker.get("jsonl_path") or ""),
            })
        owner.update(owner_update)
        write_json(owner_task, owner)
        latest_owner = read_json(owner_latest, {})
        if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == task_id:
            write_json(owner_latest, owner)
    return {
        "activity": "panel_writeback_zh",
        "status": "panel_writeback_zh_written",
        "task_id": task_id,
        "completion_decision": decision,
        "panel_task_ref": str(panel_dir / "tasks" / f"{task_id}.json"),
        "panel_latest_ref": str(panel_dir / "latest_intent_status.json") if input_payload.get("promote_current_task_owner_latest", True) is not False else "",
        "panel_lines_cn": payload["panel_lines_cn"],
        "human_egress_route": payload.get("human_egress_route", ""),
        "human_egress_router_ref": payload.get("human_egress_router_ref", ""),
        "grok_report_ref": payload.get("grok_report_ref", ""),
        "grok_report_latest_ref": payload.get("grok_report_latest_ref", ""),
        "grok_report_verify_pass": payload.get("grok_report_verify_pass") is True,
        "desktop_grok_context_gate": payload.get("desktop_grok_context_gate", ""),
        "desktop_grok_context_reused": payload.get("desktop_grok_context_reused") is True,
        "desktop_context_continuity_verified": payload.get("desktop_context_continuity_verified") is True,
        "used_existing_grok_tui": payload.get("used_existing_grok_tui") is True,
        "shortcut_launched": payload.get("shortcut_launched") is True,
        "context_loss_risk": payload.get("context_loss_risk") is True,
        "codex_final_to_user_allowed": payload.get("codex_final_to_user_allowed") is True,
        "worker_final_user_visible_allowed": payload.get("worker_final_user_visible_allowed") is True,
        "no_pytest_wall_to_user": payload.get("no_pytest_wall_to_user") is True,
        "jobs_json_observe_backend_readback": payload.get("jobs_json_observe_backend_readback") if isinstance(payload.get("jobs_json_observe_backend_readback"), dict) else {},
        "jobs_json_observe_joined": payload.get("jobs_json_observe_joined") is True,
        "task_bound_worker_token_usage": payload.get("task_bound_worker_token_usage") if isinstance(payload.get("task_bound_worker_token_usage"), dict) else {},
        "task_bound_worker_files_modified": payload.get("task_bound_worker_files_modified") if isinstance(payload.get("task_bound_worker_files_modified"), list) else [],
        "task_bound_worker_command_executions": payload.get("task_bound_worker_command_executions") if isinstance(payload.get("task_bound_worker_command_executions"), list) else [],
        "backend_evidence_refs": payload.get("backend_evidence_refs") if isinstance(payload.get("backend_evidence_refs"), dict) else {},
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("temporal_panel_writeback_zh_activity"),
    }


@workflow.defn
class TemporalCodexTaskWorkflow:
    def __init__(self) -> None:
        self.grok_segment_verdict_signal: dict[str, Any] = {}
        self.continue_same_task_signals: list[dict[str, Any]] = []

    @workflow.signal
    async def grok_segment_verdict(self, verdict: dict[str, Any]) -> None:
        self.grok_segment_verdict_signal = dict(verdict or {})

    @workflow.signal
    async def continue_same_task(self, payload: dict[str, Any]) -> None:
        self.continue_same_task_signals.append(dict(payload or {}))

    def _has_grok_segment_verdict_signal(self) -> bool:
        return bool(self.grok_segment_verdict_signal)

    def _enqueue_assignment_dag_auto_continue(self, continuation: dict[str, Any]) -> None:
        if not isinstance(continuation, dict):
            return
        signal_payload = continuation.get("auto_continue_same_task_signal")
        if continuation.get("auto_continue_same_workflow") is True and isinstance(signal_payload, dict) and signal_payload:
            self.continue_same_task_signals.append(dict(signal_payload))

    def _enqueue_ledger_auto_dispatch(self, auto_dispatch: dict[str, Any]) -> None:
        if not isinstance(auto_dispatch, dict):
            return
        signal_payload = auto_dispatch.get("auto_continue_same_task_signal")
        if (
            auto_dispatch.get("auto_continue_same_workflow") is True
            and isinstance(signal_payload, dict)
            and signal_payload
        ):
            self.continue_same_task_signals.append(dict(signal_payload))

    @workflow.run
    async def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        input_payload = {
            **input_payload,
            "workflow_id": workflow.info().workflow_id,
            "workflow_run_id": workflow.info().run_id,
            "task_queue": workflow.info().task_queue,
            "repo_root": str(input_payload.get("repo_root") or _REPO_ROOT),
        }
        retry = temporal_retry_policy()
        if (
            str(input_payload.get("task_id") or "")
            == codex_native_provider_scheduler_phase4.TASK_ID
            or input_payload.get("codex_native_provider_scheduler_phase4") is True
        ):
            phase4_activity = await workflow.execute_activity(
                codex_native_provider_scheduler_phase4_activity,
                input_payload,
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=retry,
            )
            passed = phase4_activity.get("validation_passed") is True
            return {
                "schema_version": (
                    codex_native_provider_scheduler_phase4.SCHEMA_VERSION
                    + ".workflow_result"
                ),
                "sentinel": codex_native_provider_scheduler_phase4.SENTINEL,
                "workflow_id": input_payload.get("workflow_id"),
                "workflow_run_id": input_payload.get("workflow_run_id"),
                "task_queue": input_payload.get("task_queue"),
                "active_object_id": ACTIVE_OBJECT_ID,
                "task_id": codex_native_provider_scheduler_phase4.TASK_ID,
                "status": "phase4_codex_native_provider_scheduler_workflow_ready"
                if passed
                else "phase4_codex_native_provider_scheduler_workflow_blocked",
                "activities": {"codex_native_provider_scheduler_phase4_activity": phase4_activity},
                "temporal_workflow_completed": False,
                "temporal_live_route": True,
                "server_bound": True,
                "workflow_open": True,
                "workflow_completed_partial": True,
                "workflow_completed_is_not_user_complete": True,
                "not_source_of_truth": True,
                "not_user_completion": True,
                "not_completion_boundary": True,
                "user_task_complete": False,
                "completion_decision": {
                    "status": "partial",
                    "stop_allowed": False,
                    "reason": "ProviderScheduler activity registered and invoked; this is not a user completion boundary.",
                    "named_blocker": phase4_activity.get("named_blocker", ""),
                    "not_source_of_truth": True,
                    "not_user_completion": True,
                },
                "mainline_next_hop": "codex_native_provider_scheduler_registered_for_default_route",
                "verification_level": VERIFICATION_LEVEL_WORKFLOW_OPEN,
                "validation": phase4_activity.get("validation", {}),
            }
        if (
            str(input_payload.get("task_id") or "")
            == temporal_activity_no_window_dp_worker_pool_phase3.TASK_ID
            or input_payload.get("phase3_temporal_activity_no_window_dp_pool") is True
        ):
            max_event_waves = max(
                1,
                min(
                    5,
                    int(
                        input_payload.get("max_event_waves_per_run")
                        or input_payload.get("max_event_waves_per_workflow")
                        or 2
                    ),
                ),
            )
            continue_as_new_enabled = input_payload.get("phase3_continue_as_new", True) is not False
            generation = int(input_payload.get("phase3_continue_generation") or 0)
            current_payload = {
                **input_payload,
                "phase3_event_queue_self_chain_enabled": continue_as_new_enabled,
                "phase3_max_event_waves_per_run": max_event_waves,
                "phase3_continue_generation": generation,
            }
            activity_waves: list[dict[str, Any]] = []
            loop_state: dict[str, Any] = {}
            stopped_due_to = "max_event_waves_per_run"
            for wave_index in range(max_event_waves):
                current_payload = {
                    **current_payload,
                    "phase3_event_wave_index_in_run": wave_index + 1,
                }
                dp_wave = await workflow.execute_activity(
                    dp_worker_pool_wave_activity,
                    current_payload,
                    start_to_close_timeout=dt.timedelta(minutes=90),
                    retry_policy=retry,
                )
                fan_in = await workflow.execute_activity(
                    draft_staging_fan_in_activity,
                    {
                        **current_payload,
                        "dp_worker_pool_wave_activity": dp_wave,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=retry,
                )
                loop_state = await workflow.execute_activity(
                    loop_runtime_state_update_activity,
                    {
                        **current_payload,
                        "dp_worker_pool_wave_activity": dp_wave,
                        "draft_staging_fan_in_activity": fan_in,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=retry,
                )
                activity_waves.append(
                    {
                        "dp_worker_pool_wave_activity": dp_wave,
                        "draft_staging_fan_in_activity": fan_in,
                        "loop_runtime_state_update_activity": loop_state,
                    }
                )
                phase_summary = (
                    loop_state.get("phase1_payload_summary")
                    if isinstance(loop_state.get("phase1_payload_summary"), dict)
                    else {}
                )
                next_frontier = (
                    loop_state.get("next_frontier")
                    if isinstance(loop_state.get("next_frontier"), list)
                    else []
                )
                if phase_summary.get("named_blocker"):
                    stopped_due_to = "named_blocker"
                    break
                if loop_state.get("stop", {}).get("stop_allowed") is True:
                    stopped_due_to = "stop_allowed_true"
                    break
                if not next_frontier:
                    stopped_due_to = "no_next_frontier"
                    break
                current_payload = {
                    **current_payload,
                    "wave_id": str(next_frontier[0].get("wave_id") or current_payload.get("wave_id") or ""),
                }
            should_continue = (
                continue_as_new_enabled
                and stopped_due_to == "max_event_waves_per_run"
                and loop_state.get("stop", {}).get("stop_allowed") is False
                and bool(loop_state.get("next_frontier"))
            )
            if should_continue:
                next_frontier = (
                    loop_state.get("next_frontier")
                    if isinstance(loop_state.get("next_frontier"), list)
                    else []
                )
                next_payload = {
                    **input_payload,
                    "wave_id": str(next_frontier[0].get("wave_id") or input_payload.get("wave_id") or ""),
                    "phase3_continue_generation": generation + 1,
                    "phase3_previous_run_id": workflow.info().run_id,
                    "phase3_continue_as_new": True,
                    "phase3_event_queue_self_chain_enabled": True,
                    "phase3_max_event_waves_per_run": max_event_waves,
                }
                workflow.continue_as_new(next_payload)
            latest_wave = activity_waves[-1] if activity_waves else {}
            return {
                "schema_version": (
                    temporal_activity_no_window_dp_worker_pool_phase3.SCHEMA_VERSION
                    + ".workflow_result"
                ),
                "sentinel": temporal_activity_no_window_dp_worker_pool_phase3.SENTINEL,
                "task_id": temporal_activity_no_window_dp_worker_pool_phase3.TASK_ID,
                "workflow_id": input_payload.get("workflow_id"),
                "workflow_run_id": input_payload.get("workflow_run_id"),
                "task_queue": input_payload.get("task_queue"),
                "status": (
                    "phase3_temporal_activity_workflow_ready"
                    if loop_state.get("validation", {}).get("passed") is True
                    else "phase3_temporal_activity_workflow_blocked"
                ),
                "activities": latest_wave,
                "activity_waves": activity_waves,
                "event_queue_self_chain": {
                    "enabled": continue_as_new_enabled,
                    "continue_as_new_enabled": continue_as_new_enabled,
                    "generation": generation,
                    "waves_consumed_in_run": len(activity_waves),
                    "max_event_waves_per_run": max_event_waves,
                    "stopped_due_to": stopped_due_to,
                    "would_continue_as_new": should_continue,
                },
                "runtime_enforced_scope": (
                    temporal_activity_no_window_dp_worker_pool_phase3.RUNTIME_SCOPE
                ),
                "completion_claim_allowed": False,
                "not_user_completion": True,
                "not_completion_boundary": True,
                "not_source_of_truth": True,
                "validation": {
                    "passed": loop_state.get("validation", {}).get("passed") is True,
                    "checks": {
                        "dp_wave_activity_invoked": bool(dp_wave),
                        "fan_in_activity_invoked": bool(fan_in),
                        "loop_runtime_state_activity_invoked": bool(loop_state),
                        "no_old_segment_or_pass_gate": True,
                        "event_queue_self_chain_bound": continue_as_new_enabled,
                        "event_queue_consumed_at_least_one_wave": len(activity_waves) >= 1,
                    },
                },
            }
        bound = await workflow.execute_activity(
            bind_task_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        graph = await workflow.execute_activity(
            run_langgraph_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=retry,
        )
        codex_worker = await workflow.execute_activity(
            codex_worker_turn_activity,
            input_payload,
            start_to_close_timeout=codex_worker_activity_timeout(input_payload),
            retry_policy=retry,
        )
        claim = await workflow.execute_activity(
            completion_claim_activity,
            {
                "graph_result": graph["graph_result"],
                "current_task_owner": current_task_owner_from_input(input_payload, live_temporal=True),
                "runtime_root": input_payload["runtime_root"],
                "promote_current_task_owner_latest": input_payload.get("promote_current_task_owner_latest", True) is not False,
            },
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        segment_gate = await workflow.execute_activity(
            segment_audit_gate_activity,
            {
                **input_payload,
                "completion_decision": claim["completion_decision"],
                "worker_dispatch_evidence": codex_worker,
            },
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        decision = _grok_segment_waiting_decision_override(
            claim["completion_decision"],
            segment_gate if isinstance(segment_gate, dict) else {},
        )
        if self.grok_segment_verdict_signal:
            segment_gate = await workflow.execute_activity(
                segment_audit_gate_activity,
                {
                    **input_payload,
                    "completion_decision": claim["completion_decision"],
                    "worker_dispatch_evidence": codex_worker,
                    "grok_segment_verdict_signal": self.grok_segment_verdict_signal,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            self.grok_segment_verdict_signal = {}
            decision = _grok_segment_waiting_decision_override(
                claim["completion_decision"],
                segment_gate if isinstance(segment_gate, dict) else {},
            )
        status = await workflow.execute_activity(
            write_status_activity,
            {"runtime_root": input_payload["runtime_root"], "completion_decision": decision},
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        activities = [bound, graph, codex_worker, claim, status, segment_gate]
        segment_pass_next_worker: dict[str, Any] = {}
        segment_pass_phase_exit_patch = temporal_patch_enabled(TEMPORAL_PATCH_ASSIGNMENT_DRIVEN_PHASE_EXIT_SEGMENT_PASS)
        grok_wait_continuation_patch = temporal_patch_enabled(TEMPORAL_PATCH_GROK_WAIT_L1_CONTINUATION_WORKER)
        if (
            segment_gate.get("status") == "GROK_SEGMENT_AUDIT_PASS"
            and decision.get("status") == "partial"
            and (
                not segment_pass_phase_exit_patch
                or phase_exit_segment_pass_allowed(input_payload, segment_gate if isinstance(segment_gate, dict) else {})
            )
        ):
            next_worker_input = segment_pass_next_worker_payload(input_payload, decision, segment_gate if isinstance(segment_gate, dict) else {})
            segment_pass_next_worker = await workflow.execute_activity(
                codex_worker_turn_activity,
                next_worker_input,
                start_to_close_timeout=codex_worker_activity_timeout(next_worker_input),
                retry_policy=retry,
            )
            segment_pass_next_worker.update({
                "segment_pass_next_worker_required": True,
                "segment_pass_same_workflow": True,
                "worker_task_id": str(next_worker_input.get("codex_worker_task_id") or ""),
            })
        elif (
            grok_wait_continuation_patch
            and decision.get("status") == "partial"
            and segment_gate_allows_l1_continuation(segment_gate if isinstance(segment_gate, dict) else {})
            and segment_gate.get("status") != "GROK_SEGMENT_AUDIT_PASS"
        ):
            next_worker_input = grok_wait_l1_continuation_worker_payload(input_payload, decision, segment_gate if isinstance(segment_gate, dict) else {}, len(activities) + 1)
            if next_worker_input.get("execute_codex_worker") is True:
                segment_pass_next_worker = await workflow.execute_activity(
                    codex_worker_turn_activity,
                    next_worker_input,
                    start_to_close_timeout=codex_worker_activity_timeout(next_worker_input),
                    retry_policy=retry,
                )
                segment_pass_next_worker.update({
                    "grok_wait_l1_continuation_worker_required": True,
                    "grok_waiting_does_not_block_continuation": True,
                    "segment_pass_next_worker_required": False,
                    "segment_pass_same_workflow": True,
                    "worker_task_id": str(next_worker_input.get("codex_worker_task_id") or ""),
                })
        continuation = await workflow.execute_activity(
            partial_continuation_dispatch_activity,
            {
                **input_payload,
                "completion_decision": decision,
                "segment_audit_gate": segment_gate,
                "segment_pass_next_worker": segment_pass_next_worker,
            },
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=retry,
        )
        panel = await workflow.execute_activity(
            panel_writeback_zh_activity,
            {
                **input_payload,
                "completion_decision": decision,
                "worker_dispatch_evidence": codex_worker,
                "partial_continuation_dispatch": continuation,
                "segment_audit_gate": segment_gate,
                "segment_pass_next_worker": segment_pass_next_worker,
            },
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        current_wave_index = 1
        current_wave_id = temporal_hot_path_wave_id(input_payload, current_wave_index)
        worker_ledger: dict[str, Any] = {}
        if (
            temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER)
            and should_call_seed_cortex_worker_dispatch_ledger(input_payload)
        ):
            worker_evidence = [codex_worker]
            if segment_pass_next_worker:
                worker_evidence.append(segment_pass_next_worker)
            worker_ledger = await workflow.execute_activity(
                worker_dispatch_ledger_activity,
                {
                    **input_payload,
                    "worker_dispatch_evidence": worker_evidence,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        main_loop_tick: dict[str, Any] = {}
        if worker_ledger:
            main_loop_tick = await workflow.execute_activity(
                main_execution_loop_tick_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        durable_wave_packet: dict[str, Any] = {}
        if (
            main_loop_tick
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_DURABLE_PARALLEL_WAVE_PACKET)
        ):
            durable_wave_packet = await workflow.execute_activity(
                durable_parallel_wave_packet_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        allocation_plan_result: dict[str, Any] = {}
        if (
            main_loop_tick
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN)
        ):
            allocation_plan_result = await workflow.execute_activity(
                allocation_plan_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        source_frontier_consumer: dict[str, Any] = {}
        if (
            durable_wave_packet
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_DURABLE_CONSUMER
            )
        ):
            source_frontier_consumer = await workflow.execute_activity(
                source_frontier_durable_consumer_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                    "source_frontier_consumer_max_waves": 3,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        default_dp_worker_pool_wave: dict[str, Any] = {}
        default_dp_fan_in: dict[str, Any] = {}
        default_loop_runtime_state: dict[str, Any] = {}
        if (
            source_frontier_consumer
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_DP_WORKER_POOL_WAVE
            )
            and input_payload.get("disable_default_dp_worker_pool_wave") is not True
        ):
            default_dp_payload = {
                **input_payload,
                "worker_dispatch_ledger_activity": worker_ledger,
                "main_execution_loop_tick_activity": main_loop_tick,
                "durable_parallel_wave_packet_activity": durable_wave_packet,
                "source_frontier_durable_consumer_activity": source_frontier_consumer,
                "wave_id": f"{current_wave_id}-default-dp-worker-pool",
                "wave_index": current_wave_index,
                "target_width": int(input_payload.get("autonomous_dp_target_width") or 0),
                "max_parallel_workers": int(
                    input_payload.get("autonomous_dp_max_parallel_workers")
                    or input_payload.get("max_parallel_workers")
                    or 0
                ),
                "phase3_event_queue_self_chain_enabled": input_payload.get(
                    "phase3_event_queue_self_chain_enabled", True
                )
                is not False,
                "phase3_max_event_waves_per_run": int(
                    input_payload.get("phase3_max_event_waves_per_run")
                    or input_payload.get("max_event_waves_per_run")
                    or 1
                ),
                "phase3_event_wave_index_in_run": current_wave_index,
                "phase3_continue_generation": int(input_payload.get("phase3_continue_generation") or 0),
            }
            default_dp_worker_pool_wave = await workflow.execute_activity(
                dp_worker_pool_wave_activity,
                default_dp_payload,
                start_to_close_timeout=dt.timedelta(minutes=90),
                retry_policy=retry,
            )
            default_dp_fan_in = await workflow.execute_activity(
                draft_staging_fan_in_activity,
                {
                    **default_dp_payload,
                    "dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                },
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=retry,
            )
            default_loop_runtime_state = await workflow.execute_activity(
                loop_runtime_state_update_activity,
                {
                    **default_dp_payload,
                    "dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "draft_staging_fan_in_activity": default_dp_fan_in,
                },
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=retry,
            )
        source_family_wave: dict[str, Any] = {}
        if (
            source_frontier_consumer
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_WAVE_SCHEDULER
            )
        ):
            source_family_wave = await workflow.execute_activity(
                source_family_wave_scheduler_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        source_family_phase5_sunset: dict[str, Any] = {}
        if (
            source_family_wave
            and source_family_wave.get("next_frontier_action")
            == source_family_mature_thin_bind_sunset.PHASE5_ACTION
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET
            )
        ):
            source_family_phase5_sunset = await workflow.execute_activity(
                source_family_mature_thin_bind_sunset_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        phase0_kernel: dict[str, Any] = {}
        if (
            source_family_wave
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_PHASE0_REUSABLE_KERNEL)
        ):
            phase0_kernel = await workflow.execute_activity(
                phase0_reusable_kernel_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        wave2_hygiene: dict[str, Any] = {}
        if (
            phase0_kernel
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_WAVE2_MAINCHAIN_HYGIENE)
        ):
            wave2_hygiene = await workflow.execute_activity(
                wave2_mainchain_hygiene_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        if (
            not allocation_plan_result
            and
            main_loop_tick
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN)
        ):
            allocation_plan_result = await workflow.execute_activity(
                allocation_plan_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        source_frontier_workerbrief_bridge_result: dict[str, Any] = {}
        if (
            source_frontier_consumer
            and allocation_plan_result
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERBRIEF_BRIDGE
            )
        ):
            source_frontier_workerbrief_bridge_result = await workflow.execute_activity(
                source_frontier_workerbrief_bridge_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "allocation_plan_activity": allocation_plan_result,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        source_frontier_workerpool_closure_result: dict[str, Any] = {}
        if (
            source_frontier_workerbrief_bridge_result
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERPOOL_CLOSURE
            )
            and input_payload.get("disable_source_frontier_workerpool_closure") is not True
        ):
            source_frontier_workerpool_closure_result = await workflow.execute_activity(
                source_frontier_workerpool_closure_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "allocation_plan_activity": allocation_plan_result,
                    "parent_wave_id": f"{current_wave_id}-source-frontier-workerbrief-bridge",
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=90),
                retry_policy=retry,
            )
        default_trigger_candidate: dict[str, Any] = {}
        if (
            durable_wave_packet
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE
            )
        ):
            default_trigger_candidate = await workflow.execute_activity(
                default_main_loop_trigger_candidate_activity,
                {
                    **input_payload,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "allocation_plan_activity": allocation_plan_result,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        scheduler_packet: dict[str, Any] = {}
        if (
            default_trigger_candidate
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_SCHEDULER_INVOCATION_PACKET)
        ):
            scheduler_packet = await workflow.execute_activity(
                scheduler_invocation_packet_activity,
                {
                    **input_payload,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "allocation_plan_activity": allocation_plan_result,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        pre_pass_audit: dict[str, Any] = {}
        if (
            main_loop_tick
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_PRE_PASS_AUDIT_LOOP)
        ):
            pre_pass_audit = await workflow.execute_activity(
                pre_pass_audit_loop_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "allocation_plan_activity": allocation_plan_result,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=retry,
            )
        auto_dispatch_ingress: dict[str, Any] = {}
        if worker_ledger:
            auto_dispatch_ingress = await workflow.execute_activity(
                ledger_auto_dispatch_ingress_activity,
                {
                    **input_payload,
                    "partial_continuation_dispatch": continuation,
                    "worker_dispatch_evidence": worker_evidence,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "allocation_plan_activity": allocation_plan_result,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "pre_pass_audit_loop_activity": pre_pass_audit,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            self._enqueue_ledger_auto_dispatch(auto_dispatch_ingress)
        else:
            self._enqueue_assignment_dag_auto_continue(continuation)
        activities.append(continuation)
        if segment_pass_next_worker:
            activities.append(segment_pass_next_worker)
        activities.append(panel)
        if worker_ledger:
            activities.append(worker_ledger)
        if main_loop_tick:
            activities.append(main_loop_tick)
        if durable_wave_packet:
            activities.append(durable_wave_packet)
        if source_frontier_consumer:
            activities.append(source_frontier_consumer)
        if default_dp_worker_pool_wave:
            activities.append(default_dp_worker_pool_wave)
        if default_dp_fan_in:
            activities.append(default_dp_fan_in)
        if default_loop_runtime_state:
            activities.append(default_loop_runtime_state)
        if source_family_wave:
            activities.append(source_family_wave)
        if source_family_phase5_sunset:
            activities.append(source_family_phase5_sunset)
        if phase0_kernel:
            activities.append(phase0_kernel)
        if wave2_hygiene:
            activities.append(wave2_hygiene)
        if allocation_plan_result:
            activities.append(allocation_plan_result)
        if source_frontier_workerbrief_bridge_result:
            activities.append(source_frontier_workerbrief_bridge_result)
        if source_frontier_workerpool_closure_result:
            activities.append(source_frontier_workerpool_closure_result)
        if default_trigger_candidate:
            activities.append(default_trigger_candidate)
        if scheduler_packet:
            activities.append(scheduler_packet)
        if pre_pass_audit:
            activities.append(pre_pass_audit)
        if auto_dispatch_ingress:
            activities.append(auto_dispatch_ingress)
        result = build_workflow_result(input_payload, activities, live_temporal=True)
        persist_workflow_result(pathlib.Path(input_payload["runtime_root"]), result)
        if decision.get("status") == "complete_allowed" and decision.get("stop_allowed") is True:
            return result
        while True:
            try:
                await workflow.wait_condition(
                    lambda: bool(self.continue_same_task_signals),
                    timeout=dt.timedelta(seconds=int(input_payload.get("partial_keepalive_sleep_seconds") or PARTIAL_KEEPALIVE_SLEEP_SECONDS)),
                )
            except (asyncio.TimeoutError, TimeoutError):
                continue
            if not self.continue_same_task_signals:
                continue
            signal_payload = self.continue_same_task_signals.pop(0)
            current_wave_index = int(signal_payload.get("temporal_hot_path_wave_index") or 2)
            current_wave_id = str(
                signal_payload.get("wave_id")
                or temporal_hot_path_wave_id(input_payload, current_wave_index, signal_payload)
            )
            continue_worker_input = continue_same_task_worker_payload(
                input_payload,
                signal_payload,
                len(activities) + 1,
            )
            continue_worker = await workflow.execute_activity(
                codex_worker_turn_activity,
                continue_worker_input,
                start_to_close_timeout=codex_worker_activity_timeout(continue_worker_input),
                retry_policy=retry,
            )
            continue_worker.update({
                **continuation_authorization_fields(),
                "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
                "segment_pass_next_worker_required": False,
                "continue_same_task_signal_worker_required": True,
                "segment_pass_same_workflow": True,
                "worker_task_id": str(continue_worker_input.get("codex_worker_task_id") or ""),
                "continue_same_task_signal": signal_payload,
            })
            if (
                str(signal_payload.get("segment_boundary_policy") or "") == "phase_exit_now_requires_grok_segment_audit"
                or str(signal_payload.get("phase_scope") or "").startswith("PhaseExit_")
                or signal_payload.get("force_segment_audit_after_worker") is True
            ):
                continue_segment_id = str(
                    signal_payload.get("segment_id")
                    or signal_payload.get("phase_scope")
                    or continue_worker.get("phase_scope")
                    or continue_worker_input.get("phase_scope")
                    or f"continue_same_task_worker_{len(activities) + 1}"
                )
                segment_gate = await workflow.execute_activity(
                    segment_audit_gate_activity,
                    {
                        **input_payload,
                        "segment_id": continue_segment_id,
                        "segment_complete": True,
                        "completion_decision": decision,
                        "worker_dispatch_evidence": continue_worker,
                        "continue_same_task_signal": signal_payload,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
                decision = _grok_segment_waiting_decision_override(
                    decision,
                    segment_gate if isinstance(segment_gate, dict) else {},
                )
                if self.grok_segment_verdict_signal:
                    segment_gate = await workflow.execute_activity(
                        segment_audit_gate_activity,
                        {
                            **input_payload,
                            "segment_id": continue_segment_id,
                            "segment_complete": True,
                            "completion_decision": decision,
                            "worker_dispatch_evidence": continue_worker,
                            "continue_same_task_signal": signal_payload,
                            "grok_segment_verdict_signal": self.grok_segment_verdict_signal,
                        },
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=retry,
                    )
                    self.grok_segment_verdict_signal = {}
                    decision = _grok_segment_waiting_decision_override(
                        decision,
                        segment_gate if isinstance(segment_gate, dict) else {},
                    )
                elif not temporal_patch_enabled(TEMPORAL_PATCH_PHASE_EXIT_NO_GROK_WAIT_BEFORE_PARTIAL_CONTINUATION):
                    try:
                        await workflow.wait_condition(
                            self._has_grok_segment_verdict_signal,
                            timeout=dt.timedelta(seconds=180),
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        pass
                    if self.grok_segment_verdict_signal:
                        segment_gate = await workflow.execute_activity(
                            segment_audit_gate_activity,
                            {
                                **input_payload,
                                "segment_id": continue_segment_id,
                                "segment_complete": True,
                                "completion_decision": decision,
                                "worker_dispatch_evidence": continue_worker,
                                "continue_same_task_signal": signal_payload,
                                "grok_segment_verdict_signal": self.grok_segment_verdict_signal,
                            },
                            start_to_close_timeout=dt.timedelta(minutes=2),
                            retry_policy=retry,
                        )
                        self.grok_segment_verdict_signal = {}
                        decision = _grok_segment_waiting_decision_override(
                            decision,
                            segment_gate if isinstance(segment_gate, dict) else {},
                        )
            continuation = await workflow.execute_activity(
                partial_continuation_dispatch_activity,
                {
                    **input_payload,
                    "completion_decision": decision,
                    "segment_audit_gate": segment_gate,
                    "segment_pass_next_worker": continue_worker,
                    "continue_same_task_signal": signal_payload,
                },
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=retry,
            )
            panel = await workflow.execute_activity(
                panel_writeback_zh_activity,
                {
                    **input_payload,
                    "completion_decision": decision,
                    "worker_dispatch_evidence": continue_worker,
                    "partial_continuation_dispatch": continuation,
                    "segment_audit_gate": segment_gate,
                    "segment_pass_next_worker": continue_worker,
                    "continue_same_task_signal": signal_payload,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            worker_ledger = {}
            if (
                temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER)
                and should_call_seed_cortex_worker_dispatch_ledger(input_payload)
            ):
                worker_ledger = await workflow.execute_activity(
                    worker_dispatch_ledger_activity,
                    {
                        **input_payload,
                        "worker_dispatch_evidence": [continue_worker],
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            main_loop_tick = {}
            if worker_ledger:
                main_loop_tick = await workflow.execute_activity(
                    main_execution_loop_tick_activity,
                    {
                        **input_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            durable_wave_packet = {}
            if (
                main_loop_tick
                and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_DURABLE_PARALLEL_WAVE_PACKET)
            ):
                durable_wave_packet = await workflow.execute_activity(
                    durable_parallel_wave_packet_activity,
                    {
                        **input_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            allocation_plan_result = {}
            if (
                main_loop_tick
                and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_ALLOCATION_PLAN)
            ):
                allocation_plan_result = await workflow.execute_activity(
                    allocation_plan_activity,
                    {
                        **input_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            source_frontier_workerbrief_bridge_result = (
                embedded_workerbrief_bridge_activity_from_main_loop_tick(main_loop_tick)
            )
            source_frontier_workerpool_closure_result = {}
            if (
                source_frontier_workerbrief_bridge_result
                and source_frontier_workerbrief_bridge_result.get("bridge_validation_passed") is True
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_CONTINUATION_WORKERPOOL_CLOSURE
                )
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FRONTIER_WORKERPOOL_CLOSURE
                )
                and input_payload.get("disable_source_frontier_workerpool_closure") is not True
            ):
                parent_bridge_wave_id = str(
                    source_frontier_workerbrief_bridge_result.get("bridge_wave_id")
                    or f"{current_wave_id}-source-frontier-workerbrief-bridge"
                )
                source_frontier_workerpool_closure_result = await workflow.execute_activity(
                    source_frontier_workerpool_closure_activity,
                    {
                        **input_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "parent_wave_id": parent_bridge_wave_id,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=90),
                    retry_policy=retry,
                )
            default_trigger_candidate = {}
            if (
                durable_wave_packet
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_MAIN_LOOP_TRIGGER_CANDIDATE
                )
            ):
                default_trigger_candidate = await workflow.execute_activity(
                    default_main_loop_trigger_candidate_activity,
                    {
                        **input_payload,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            scheduler_packet = {}
            if (
                default_trigger_candidate
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SCHEDULER_INVOCATION_PACKET
                )
            ):
                scheduler_packet = await workflow.execute_activity(
                    scheduler_invocation_packet_activity,
                    {
                        **input_payload,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            pre_pass_audit = {}
            if (
                main_loop_tick
                and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_PRE_PASS_AUDIT_LOOP)
            ):
                pre_pass_audit = await workflow.execute_activity(
                    pre_pass_audit_loop_activity,
                    {
                        **input_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=retry,
                )
            auto_dispatch_ingress = {}
            if worker_ledger:
                auto_dispatch_ingress = await workflow.execute_activity(
                    ledger_auto_dispatch_ingress_activity,
                    {
                        **input_payload,
                        "partial_continuation_dispatch": continuation,
                        "worker_dispatch_evidence": [continue_worker],
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "pre_pass_audit_loop_activity": pre_pass_audit,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
                self._enqueue_ledger_auto_dispatch(auto_dispatch_ingress)
            else:
                self._enqueue_assignment_dag_auto_continue(continuation)
            activities.extend([continue_worker, continuation, panel])
            if worker_ledger:
                activities.append(worker_ledger)
            if main_loop_tick:
                activities.append(main_loop_tick)
            if durable_wave_packet:
                activities.append(durable_wave_packet)
            if allocation_plan_result:
                activities.append(allocation_plan_result)
            if source_frontier_workerbrief_bridge_result:
                activities.append(source_frontier_workerbrief_bridge_result)
            if source_frontier_workerpool_closure_result:
                activities.append(source_frontier_workerpool_closure_result)
            if default_trigger_candidate:
                activities.append(default_trigger_candidate)
            if scheduler_packet:
                activities.append(scheduler_packet)
            if pre_pass_audit:
                activities.append(pre_pass_audit)
            if auto_dispatch_ingress:
                activities.append(auto_dispatch_ingress)
            result = build_workflow_result(input_payload, activities, live_temporal=True)
            persist_workflow_result(pathlib.Path(input_payload["runtime_root"]), result)


def build_workflow_result(input_payload: dict[str, Any], activities: list[dict[str, Any]], *, live_temporal: bool) -> dict[str, Any]:
    completion_activity = next(item for item in activities if item["activity"] == "completion_claim")
    graph_activity = next((item for item in activities if item.get("activity") == "run_langgraph" and isinstance(item.get("graph_result"), dict)), {})
    graph_result = graph_activity.get("graph_result") if isinstance(graph_activity.get("graph_result"), dict) else {}
    object_binding = task_object_binding_from_payload({
        **input_payload,
        "graph_result": graph_result,
    })
    decision = completion_activity["completion_decision"]
    segment_audit_activity = next((item for item in activities if item.get("activity") == "segment_audit_gate"), {})
    decision = _grok_segment_waiting_decision_override(
        decision,
        segment_audit_activity if isinstance(segment_audit_activity, dict) else {},
    )
    continuation_activity = next((item for item in activities if item.get("activity") == "partial_continuation_dispatch"), {})
    segment_pass_next_worker = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "codex_worker_turn"
            and item.get("implementation_worker_required") is True
        ),
        {},
    )
    if not segment_pass_next_worker:
        segment_pass_next_worker = next(
        (
            item
            for item in activities
            if item.get("activity") == "codex_worker_turn"
            and item.get("segment_pass_next_worker_required") is True
        ),
        {},
        )
    same_workflow_next_worker_dispatched = (
        segment_pass_next_worker.get("status") == "activity_gate_checked"
        and (
            segment_pass_next_worker.get("jsonl_exists") is True
            or segment_pass_next_worker.get("codex_jsonl_is_execution_evidence") is True
            or bool(segment_pass_next_worker.get("jsonl_path"))
        )
    )
    panel_activity = next((item for item in activities if item.get("activity") == "panel_writeback_zh"), {})
    primary_worker_activity = next((item for item in activities if item.get("activity") == "codex_worker_turn"), {})
    worker_dispatch_ledger_activity_result = select_primary_worker_dispatch_ledger_activity(activities)
    main_execution_loop_tick_activity_result = next(
        (item for item in reversed(activities) if item.get("activity") == "main_execution_loop_tick"),
        {},
    )
    durable_parallel_wave_packet_activity_result = next(
        (item for item in reversed(activities) if item.get("activity") == "durable_parallel_wave_packet"),
        {},
    )
    source_frontier_durable_consumer_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_frontier_durable_consumer"
        ),
        {},
    )
    default_dp_worker_pool_wave_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "dp_worker_pool_wave_activity"
        ),
        {},
    )
    default_dp_draft_staging_fan_in_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "draft_staging_fan_in_activity"
        ),
        {},
    )
    default_loop_runtime_state_update_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "loop_runtime_state_update_activity"
        ),
        {},
    )
    source_family_wave_scheduler_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_family_wave_scheduler"
        ),
        {},
    )
    source_family_mature_thin_bind_sunset_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_family_mature_thin_bind_sunset"
        ),
        {},
    )
    phase0_reusable_kernel_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "phase0_reusable_kernel"
        ),
        {},
    )
    wave2_mainchain_hygiene_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "wave2_mainchain_hygiene"
        ),
        {},
    )
    default_main_loop_trigger_candidate_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "default_main_loop_trigger_candidate"
        ),
        {},
    )
    scheduler_invocation_packet_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "scheduler_invocation_packet"
        ),
        {},
    )
    allocation_plan_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "allocation_plan"
        ),
        {},
    )
    source_frontier_workerbrief_bridge_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_frontier_workerbrief_bridge"
        ),
        {},
    )
    source_frontier_workerpool_closure_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_frontier_workerpool_closure"
        ),
        {},
    )
    pre_pass_audit_loop_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "pre_pass_audit_loop"
        ),
        {},
    )
    ledger_auto_dispatch_ingress_activity_result = select_primary_ledger_auto_dispatch_ingress_activity(activities)
    observe_source_worker = segment_pass_next_worker if same_workflow_next_worker_dispatched else primary_worker_activity
    worker_observe = jobs_json_observe_from_worker_result(observe_source_worker if isinstance(observe_source_worker, dict) else {})
    phase5_readback = phase5_observability_discovery_panel_readback(
        pathlib.Path(input_payload.get("runtime_root") or DEFAULT_RUNTIME),
        str(input_payload["task_id"]),
        str(input_payload.get("workflow_id", f"xinao-codex-task-{input_payload['task_id']}")),
        str(input_payload.get("workflow_run_id", "")),
        str(observe_source_worker.get("jsonl_path") or "") if isinstance(observe_source_worker, dict) else "",
    )
    result = {
        "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
        "generated_at": now(),
        "workflow_id": input_payload.get("workflow_id", f"xinao-codex-task-{input_payload['task_id']}"),
        "workflow_run_id": input_payload.get("workflow_run_id", ""),
        "task_queue": input_payload.get("task_queue", DEFAULT_TASK_QUEUE),
        "active_object_id": ACTIVE_OBJECT_ID,
        "task_id": input_payload["task_id"],
        "source_goal_ref": source_goal_ref(input_payload.get("user_goal", "")),
        "source_refs": list(input_payload.get("source_refs") or []),
        "compiled_task_object": object_binding["compiled_task_object"],
        "compiled_task_object_sha256": object_binding["compiled_task_object_sha256"],
        "source_refs_sha256": object_binding["source_refs_sha256"],
        "acceptance_contract": object_binding["acceptance_contract"],
        "runtime_subject_loop_required": list(input_payload.get("runtime_subject_loop_required") or langgraph_task_runner.RUNTIME_SUBJECT_LOOP_REQUIRED),
        "root_repair_constraints": list(input_payload.get("root_repair_constraints") or langgraph_task_runner.ROOT_REPAIR_CONSTRAINTS),
        "minimum_reality_contact_required": bool(input_payload.get("minimum_reality_contact_required", True)),
        "no_new_parallel_control_surface": bool(input_payload.get("no_new_parallel_control_surface", True)),
        "temporal_workflow_completed": decision.get("status") == "complete_allowed" and decision.get("stop_allowed") is True,
        "temporal_live_route": live_temporal,
        "server_bound": live_temporal,
        "workflow_open": bool(live_temporal and not (decision.get("status") == "complete_allowed" and decision.get("stop_allowed") is True)),
        "workflow_completed_partial": live_temporal and decision.get("status") == "partial",
        "verification_level": normalize_verification_level(
            VERIFICATION_LEVEL_WORKFLOW_OPEN
            if live_temporal and decision.get("status") == "partial"
            else VERIFICATION_LEVEL_SERVER_HISTORY
            if live_temporal
            else VERIFICATION_LEVEL_READ_MODEL
        ),
        "workflow_completed_is_not_user_complete": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "promote_current_task_owner_latest": input_payload.get("promote_current_task_owner_latest", True) is not False,
        "authority_boundary": authority_boundary("temporal_workflow_state_carrier"),
        "canonical_completion_source": "/completion/claim",
        "execution_mode": "temporal_server" if live_temporal else "local_temporal_compat",
        "local_run_observed": not bool(live_temporal),
        "worker_service_polling": bool(input_payload.get("worker_service_polling", False)),
        "g2_temporal_server_verification_ref": input_payload.get("g2_temporal_server_verification_ref", ""),
        "completion_decision": decision,
        "user_task_complete": decision.get("status") == "complete_allowed" and decision.get("stop_allowed") is True,
        "partial_continuation_dispatched": bool(continuation_activity.get("continuation_dispatched")),
        "partial_continuation_ref": continuation_activity.get("worker_task_id", "") if isinstance(continuation_activity, dict) else "",
        "workflow_internal_timer_scheduled": bool(continuation_activity.get("workflow_internal_timer_scheduled")),
        "workflow_kept_open_by_durable_timer": bool(continuation_activity.get("workflow_kept_open_by_durable_timer")),
        "partial_frontier_open": decision.get("status") == "partial" and decision.get("stop_allowed") is not True,
        "mainline_next_hop": same_workflow_next_hop(
            segment_pass_next_worker if same_workflow_next_worker_dispatched else {},
            timer_wait=bool(continuation_activity.get("workflow_internal_timer_scheduled")),
        ),
        "segment_pass_must_dispatch_next_bounded_worker": bool(
            str(segment_audit_activity.get("status")) == "GROK_SEGMENT_AUDIT_PASS"
            and phase_exit_segment_pass_allowed(input_payload, segment_audit_activity if isinstance(segment_audit_activity, dict) else {})
        ),
        "assignment_driven_implementation_worker_dispatched": bool(
            same_workflow_next_worker_dispatched
            and segment_pass_next_worker.get("implementation_worker_required") is True
        ),
        "worker_kind": str(segment_pass_next_worker.get("worker_kind") or input_payload.get("worker_kind") or ""),
        "phase_scope": str(segment_pass_next_worker.get("phase_scope") or input_payload.get("phase_scope") or ""),
        "worker_assignment_ref": str(segment_pass_next_worker.get("worker_assignment_ref") or input_payload.get("worker_assignment_ref") or ""),
        "worker_dispatch_ledger_activity": (
            worker_dispatch_ledger_activity_result
            if isinstance(worker_dispatch_ledger_activity_result, dict)
            else {}
        ),
        "worker_dispatch_ledger_latest_ref": str(
            worker_dispatch_ledger_activity_result.get("ledger_latest_ref") or ""
        )
        if isinstance(worker_dispatch_ledger_activity_result, dict)
        else "",
        "worker_dispatch_ledger_temporal_activity_latest_ref": str(
            worker_dispatch_ledger_activity_result.get("ledger_temporal_activity_latest_ref") or ""
        )
        if isinstance(worker_dispatch_ledger_activity_result, dict)
        else "",
        "worker_dispatch_ledger_readback_zh_ref": str(
            worker_dispatch_ledger_activity_result.get("ledger_readback_zh_ref") or ""
        )
        if isinstance(worker_dispatch_ledger_activity_result, dict)
        else "",
        "worker_dispatch_ledger_adoption_state": str(
            worker_dispatch_ledger_activity_result.get("adoption_state") or ""
        )
        if isinstance(worker_dispatch_ledger_activity_result, dict)
        else "",
        "worker_dispatch_ledger_runtime_enforced": bool(
            isinstance(worker_dispatch_ledger_activity_result, dict)
            and worker_dispatch_ledger_activity_result.get("runtime_enforced") is True
        ),
        "worker_dispatch_ledger_not_execution_controller": True,
        "worker_dispatch_ledger_not_completion_gate": True,
        "main_execution_loop_tick_activity": (
            main_execution_loop_tick_activity_result
            if isinstance(main_execution_loop_tick_activity_result, dict)
            else {}
        ),
        "main_execution_loop_tick_latest_ref": str(
            main_execution_loop_tick_activity_result.get("tick_latest_ref") or ""
        )
        if isinstance(main_execution_loop_tick_activity_result, dict)
        else "",
        "main_execution_loop_tick_temporal_activity_latest_ref": str(
            main_execution_loop_tick_activity_result.get("tick_temporal_activity_latest_ref")
            or ""
        )
        if isinstance(main_execution_loop_tick_activity_result, dict)
        else "",
        "main_execution_loop_tick_runtime_enforced": bool(
            isinstance(main_execution_loop_tick_activity_result, dict)
            and main_execution_loop_tick_activity_result.get("runtime_enforced") is True
        ),
        "main_execution_loop_tick_not_execution_controller": True,
        "main_execution_loop_tick_not_completion_gate": True,
        "durable_parallel_wave_packet_activity": (
            durable_parallel_wave_packet_activity_result
            if isinstance(durable_parallel_wave_packet_activity_result, dict)
            else {}
        ),
        "durable_parallel_wave_packet_latest_ref": str(
            durable_parallel_wave_packet_activity_result.get("durable_packet_latest_ref") or ""
        )
        if isinstance(durable_parallel_wave_packet_activity_result, dict)
        else "",
        "durable_parallel_wave_packet_temporal_activity_latest_ref": str(
            durable_parallel_wave_packet_activity_result.get(
                "durable_packet_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(durable_parallel_wave_packet_activity_result, dict)
        else "",
        "durable_parallel_wave_packet_readback_zh_ref": str(
            durable_parallel_wave_packet_activity_result.get("durable_packet_readback_zh_ref")
            or ""
        )
        if isinstance(durable_parallel_wave_packet_activity_result, dict)
        else "",
        "durable_parallel_wave_packet_runtime_enforced": bool(
            isinstance(durable_parallel_wave_packet_activity_result, dict)
            and durable_parallel_wave_packet_activity_result.get("runtime_enforced") is True
        ),
        "durable_parallel_wave_packet_runtime_enforced_scope": str(
            durable_parallel_wave_packet_activity_result.get("runtime_enforced_scope") or ""
        )
        if isinstance(durable_parallel_wave_packet_activity_result, dict)
        else "",
        "durable_parallel_wave_packet_validation_passed": bool(
            isinstance(durable_parallel_wave_packet_activity_result, dict)
            and durable_parallel_wave_packet_activity_result.get("durable_packet_validation_passed") is True
        ),
        "durable_parallel_wave_packet_not_execution_controller": True,
        "durable_parallel_wave_packet_not_completion_gate": True,
        "source_frontier_durable_consumer_activity": (
            source_frontier_durable_consumer_activity_result
            if isinstance(source_frontier_durable_consumer_activity_result, dict)
            else {}
        ),
        "source_frontier_durable_consumer_latest_ref": str(
            source_frontier_durable_consumer_activity_result.get("consumer_latest_ref")
            or ""
        )
        if isinstance(source_frontier_durable_consumer_activity_result, dict)
        else "",
        "source_frontier_durable_consumer_temporal_activity_latest_ref": str(
            source_frontier_durable_consumer_activity_result.get("consumer_temporal_activity_latest_ref")
            or ""
        )
        if isinstance(source_frontier_durable_consumer_activity_result, dict)
        else "",
        "source_frontier_durable_consumer_readback_zh_ref": str(
            source_frontier_durable_consumer_activity_result.get("consumer_readback_zh_ref")
            or ""
        )
        if isinstance(source_frontier_durable_consumer_activity_result, dict)
        else "",
        "source_frontier_durable_consumer_source_gap_open": bool(
            isinstance(source_frontier_durable_consumer_activity_result, dict)
            and source_frontier_durable_consumer_activity_result.get("source_gap_open") is True
        ),
        "source_frontier_durable_consumer_consumed_batch_ids": list(
            source_frontier_durable_consumer_activity_result.get("consumed_batch_ids") or []
        )
        if isinstance(source_frontier_durable_consumer_activity_result, dict)
        else [],
        "source_frontier_durable_consumer_remaining_batch_ids": list(
            source_frontier_durable_consumer_activity_result.get("remaining_batch_ids") or []
        )
        if isinstance(source_frontier_durable_consumer_activity_result, dict)
        else [],
        "source_frontier_durable_consumer_not_execution_controller": True,
        "source_frontier_durable_consumer_not_completion_gate": True,
        "default_dp_worker_pool_wave_activity": (
            default_dp_worker_pool_wave_activity_result
            if isinstance(default_dp_worker_pool_wave_activity_result, dict)
            else {}
        ),
        "default_dp_worker_pool_wave_status": str(
            default_dp_worker_pool_wave_activity_result.get("status") or ""
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else "",
        "default_dp_worker_pool_dynamic_width_source": str(
            (
                default_dp_worker_pool_wave_activity_result.get("dynamic_width_decision")
                if isinstance(default_dp_worker_pool_wave_activity_result.get("dynamic_width_decision"), dict)
                else {}
            ).get("target_width_source")
            or ""
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else "",
        "default_dp_worker_pool_dynamic_width_reason": str(
            (
                default_dp_worker_pool_wave_activity_result.get("dynamic_width_decision")
                if isinstance(default_dp_worker_pool_wave_activity_result.get("dynamic_width_decision"), dict)
                else {}
            ).get("width_decision_reason")
            or ""
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else "",
        "default_dp_worker_pool_actual_dispatched_width": int(
            default_dp_worker_pool_wave_activity_result.get("actual_dispatched_width") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_actual_completed_width": int(
            default_dp_worker_pool_wave_activity_result.get("actual_completed_width") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_draft_count": int(
            default_dp_worker_pool_wave_activity_result.get("draft_count") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_true_dp_draft_count": int(
            default_dp_worker_pool_wave_activity_result.get("true_dp_draft_count") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_local_stub_draft_count": int(
            default_dp_worker_pool_wave_activity_result.get("local_stub_draft_count") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_staged_count": int(
            default_dp_worker_pool_wave_activity_result.get("staged_count") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_merged_count": int(
            default_dp_worker_pool_wave_activity_result.get("merged_count") or 0
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else 0,
        "default_dp_worker_pool_named_blocker": str(
            default_dp_worker_pool_wave_activity_result.get("named_blocker") or ""
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else "",
        "default_dp_worker_pool_phase1_latest_ref": str(
            default_dp_worker_pool_wave_activity_result.get("phase1_latest_ref") or ""
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else "",
        "default_dp_worker_pool_worker_dispatch_ledger_ref": str(
            default_dp_worker_pool_wave_activity_result.get("worker_dispatch_ledger_ref") or ""
        )
        if isinstance(default_dp_worker_pool_wave_activity_result, dict)
        else "",
        "default_dp_worker_pool_validation_passed": bool(
            isinstance(default_dp_worker_pool_wave_activity_result, dict)
            and default_dp_worker_pool_wave_activity_result.get("validation", {}).get("passed") is True
        ),
        "default_dp_draft_staging_fan_in_activity": (
            default_dp_draft_staging_fan_in_activity_result
            if isinstance(default_dp_draft_staging_fan_in_activity_result, dict)
            else {}
        ),
        "default_loop_runtime_state_update_activity": (
            default_loop_runtime_state_update_activity_result
            if isinstance(default_loop_runtime_state_update_activity_result, dict)
            else {}
        ),
        "default_dp_worker_pool_not_execution_controller": True,
        "default_dp_worker_pool_not_completion_gate": True,
        "source_family_wave_scheduler_activity": (
            source_family_wave_scheduler_activity_result
            if isinstance(source_family_wave_scheduler_activity_result, dict)
            else {}
        ),
        "source_family_wave_scheduler_latest_ref": str(
            source_family_wave_scheduler_activity_result.get(
                "source_family_wave_scheduler_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else "",
        "source_family_wave_scheduler_temporal_activity_latest_ref": str(
            source_family_wave_scheduler_activity_result.get(
                "source_family_wave_scheduler_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else "",
        "source_family_wave_scheduler_readback_zh_ref": str(
            source_family_wave_scheduler_activity_result.get("readback_zh_ref") or ""
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else "",
        "source_family_wave_scheduler_source_family_count": int(
            source_family_wave_scheduler_activity_result.get("source_family_count") or 0
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else 0,
        "source_family_wave_scheduler_accepted_artifact_count": int(
            source_family_wave_scheduler_activity_result.get("accepted_artifact_count") or 0
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else 0,
        "source_family_wave_scheduler_next_frontier_scope": str(
            source_family_wave_scheduler_activity_result.get("next_frontier_scope") or ""
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else "",
        "source_family_wave_scheduler_next_frontier_action": str(
            source_family_wave_scheduler_activity_result.get("next_frontier_action") or ""
        )
        if isinstance(source_family_wave_scheduler_activity_result, dict)
        else "",
        "source_family_wave_scheduler_remaining_topic_family_count": (
            source_family_wave_scheduler_activity_result.get("remaining_topic_family_count")
            if isinstance(source_family_wave_scheduler_activity_result, dict)
            else None
        ),
        "source_family_wave_scheduler_not_execution_controller": True,
        "source_family_wave_scheduler_not_completion_gate": True,
        "source_family_mature_thin_bind_sunset_activity": (
            source_family_mature_thin_bind_sunset_activity_result
            if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
            else {}
        ),
        "source_family_mature_thin_bind_sunset_latest_ref": str(
            source_family_mature_thin_bind_sunset_activity_result.get(
                "source_family_mature_thin_bind_sunset_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
        else "",
        "source_family_mature_thin_bind_sunset_temporal_activity_latest_ref": str(
            source_family_mature_thin_bind_sunset_activity_result.get(
                "source_family_mature_thin_bind_sunset_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
        else "",
        "source_family_mature_thin_bind_sunset_readback_zh_ref": str(
            source_family_mature_thin_bind_sunset_activity_result.get("readback_zh_ref")
            or ""
        )
        if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
        else "",
        "source_family_mature_thin_bind_sunset_consumed_action": str(
            source_family_mature_thin_bind_sunset_activity_result.get(
                "consumed_next_frontier_action"
            )
            or ""
        )
        if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
        else "",
        "source_family_mature_thin_bind_sunset_edge_count": int(
            source_family_mature_thin_bind_sunset_activity_result.get("sunset_edge_count")
            or 0
        )
        if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
        else 0,
        "source_family_mature_thin_bind_sunset_candidate_adapter_smoke_count": int(
            source_family_mature_thin_bind_sunset_activity_result.get(
                "candidate_adapter_smoke_count"
            )
            or 0
        )
        if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
        else 0,
        "source_family_mature_thin_bind_sunset_validation_passed": bool(
            isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
            and source_family_mature_thin_bind_sunset_activity_result.get(
                "sunset_validation_passed"
            )
            is True
        ),
        "source_family_mature_thin_bind_sunset_not_execution_controller": True,
        "source_family_mature_thin_bind_sunset_not_completion_gate": True,
        "phase0_reusable_kernel_activity": (
            phase0_reusable_kernel_activity_result
            if isinstance(phase0_reusable_kernel_activity_result, dict)
            else {}
        ),
        "phase0_reusable_kernel_latest_ref": str(
            phase0_reusable_kernel_activity_result.get("phase0_reusable_kernel_latest_ref")
            or ""
        )
        if isinstance(phase0_reusable_kernel_activity_result, dict)
        else "",
        "phase0_reusable_kernel_temporal_activity_latest_ref": str(
            phase0_reusable_kernel_activity_result.get(
                "phase0_reusable_kernel_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(phase0_reusable_kernel_activity_result, dict)
        else "",
        "phase0_reusable_kernel_readback_zh_ref": str(
            phase0_reusable_kernel_activity_result.get("readback_zh_ref") or ""
        )
        if isinstance(phase0_reusable_kernel_activity_result, dict)
        else "",
        "phase0_reusable_kernel_landed_count": int(
            phase0_reusable_kernel_activity_result.get("landed_count") or 0
        )
        if isinstance(phase0_reusable_kernel_activity_result, dict)
        else 0,
        "phase0_reusable_kernel_object_count": int(
            phase0_reusable_kernel_activity_result.get("object_count") or 0
        )
        if isinstance(phase0_reusable_kernel_activity_result, dict)
        else 0,
        "phase0_reusable_kernel_new_work_id_thin_bind_ready": bool(
            isinstance(phase0_reusable_kernel_activity_result, dict)
            and phase0_reusable_kernel_activity_result.get("new_work_id_thin_bind_ready")
            is True
        ),
        "phase0_reusable_kernel_not_execution_controller": True,
        "phase0_reusable_kernel_not_completion_gate": True,
        "wave2_mainchain_hygiene_activity": (
            wave2_mainchain_hygiene_activity_result
            if isinstance(wave2_mainchain_hygiene_activity_result, dict)
            else {}
        ),
        "wave2_mainchain_hygiene_latest_ref": str(
            wave2_mainchain_hygiene_activity_result.get("wave2_mainchain_hygiene_latest_ref")
            or ""
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else "",
        "wave2_mainchain_hygiene_temporal_activity_latest_ref": str(
            wave2_mainchain_hygiene_activity_result.get(
                "wave2_mainchain_hygiene_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else "",
        "wave2_mainchain_hygiene_readback_zh_ref": str(
            wave2_mainchain_hygiene_activity_result.get("readback_zh_ref") or ""
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else "",
        "wave2_mainchain_hygiene_black_window_issue_handled": bool(
            isinstance(wave2_mainchain_hygiene_activity_result, dict)
            and wave2_mainchain_hygiene_activity_result.get("black_window_issue_handled")
            is True
        ),
        "wave2_mainchain_hygiene_visible_disallowed_cmd_powershell_python_count": int(
            wave2_mainchain_hygiene_activity_result.get(
                "visible_disallowed_cmd_powershell_python_count"
            )
            or 0
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else 0,
        "wave2_mainchain_hygiene_memo_gap_landed_or_migrated": int(
            wave2_mainchain_hygiene_activity_result.get("memo_gap_landed_or_migrated")
            or 0
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else 0,
        "wave2_mainchain_hygiene_memo_gap_total_targets": int(
            wave2_mainchain_hygiene_activity_result.get("memo_gap_total_targets") or 0
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else 0,
        "wave2_mainchain_hygiene_default_main_loop": str(
            wave2_mainchain_hygiene_activity_result.get("default_main_loop") or ""
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else "",
        "wave2_mainchain_hygiene_next_frontier_action": str(
            wave2_mainchain_hygiene_activity_result.get("next_frontier_action") or ""
        )
        if isinstance(wave2_mainchain_hygiene_activity_result, dict)
        else "",
        "wave2_mainchain_hygiene_stop_allowed": (
            wave2_mainchain_hygiene_activity_result.get("stop_allowed")
            if isinstance(wave2_mainchain_hygiene_activity_result, dict)
            else None
        ),
        "wave2_mainchain_hygiene_not_execution_controller": True,
        "wave2_mainchain_hygiene_not_completion_gate": True,
        "default_main_loop_trigger_candidate_activity": (
            default_main_loop_trigger_candidate_activity_result
            if isinstance(default_main_loop_trigger_candidate_activity_result, dict)
            else {}
        ),
        "default_main_loop_trigger_candidate_latest_ref": str(
            default_main_loop_trigger_candidate_activity_result.get(
                "trigger_candidate_latest_ref"
            )
            or ""
        )
        if isinstance(default_main_loop_trigger_candidate_activity_result, dict)
        else "",
        "default_main_loop_trigger_candidate_temporal_activity_latest_ref": str(
            default_main_loop_trigger_candidate_activity_result.get(
                "trigger_candidate_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(default_main_loop_trigger_candidate_activity_result, dict)
        else "",
        "default_main_loop_trigger_candidate_readback_zh_ref": str(
            default_main_loop_trigger_candidate_activity_result.get(
                "trigger_candidate_readback_zh_ref"
            )
            or ""
        )
        if isinstance(default_main_loop_trigger_candidate_activity_result, dict)
        else "",
        "default_main_loop_trigger_candidate_runtime_enforced": bool(
            isinstance(default_main_loop_trigger_candidate_activity_result, dict)
            and default_main_loop_trigger_candidate_activity_result.get("runtime_enforced")
            is True
        ),
        "default_main_loop_trigger_candidate_runtime_enforced_scope": str(
            default_main_loop_trigger_candidate_activity_result.get("runtime_enforced_scope")
            or ""
        )
        if isinstance(default_main_loop_trigger_candidate_activity_result, dict)
        else "",
        "default_main_loop_trigger_candidate_validation_passed": bool(
            isinstance(default_main_loop_trigger_candidate_activity_result, dict)
            and default_main_loop_trigger_candidate_activity_result.get(
                "trigger_candidate_validation_passed"
            )
            is True
        ),
        "default_main_loop_trigger_candidate_not_execution_controller": True,
        "default_main_loop_trigger_candidate_not_completion_gate": True,
        "scheduler_invocation_packet_activity": (
            scheduler_invocation_packet_activity_result
            if isinstance(scheduler_invocation_packet_activity_result, dict)
            else {}
        ),
        "scheduler_invocation_packet_latest_ref": str(
            scheduler_invocation_packet_activity_result.get(
                "scheduler_invocation_packet_latest_ref"
            )
            or ""
        )
        if isinstance(scheduler_invocation_packet_activity_result, dict)
        else "",
        "scheduler_invocation_packet_temporal_activity_latest_ref": str(
            scheduler_invocation_packet_activity_result.get(
                "scheduler_invocation_packet_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(scheduler_invocation_packet_activity_result, dict)
        else "",
        "scheduler_invocation_packet_readback_zh_ref": str(
            scheduler_invocation_packet_activity_result.get(
                "scheduler_invocation_packet_readback_zh_ref"
            )
            or ""
        )
        if isinstance(scheduler_invocation_packet_activity_result, dict)
        else "",
        "scheduler_invocation_packet_runtime_enforced": bool(
            isinstance(scheduler_invocation_packet_activity_result, dict)
            and scheduler_invocation_packet_activity_result.get("runtime_enforced")
            is True
        ),
        "scheduler_invocation_packet_runtime_enforced_scope": str(
            scheduler_invocation_packet_activity_result.get("runtime_enforced_scope")
            or ""
        )
        if isinstance(scheduler_invocation_packet_activity_result, dict)
        else "",
        "scheduler_invocation_packet_validation_passed": bool(
            isinstance(scheduler_invocation_packet_activity_result, dict)
            and scheduler_invocation_packet_activity_result.get(
                "scheduler_invocation_packet_validation_passed"
            )
            is True
        ),
        "scheduler_invocation_packet_packet_runtime_enforced": bool(
            isinstance(scheduler_invocation_packet_activity_result, dict)
            and scheduler_invocation_packet_activity_result.get("packet_runtime_enforced")
            is True
        ),
        "scheduler_invocation_packet_packet_default_runtime_scheduler_invoked": bool(
            isinstance(scheduler_invocation_packet_activity_result, dict)
            and scheduler_invocation_packet_activity_result.get(
                "packet_default_runtime_scheduler_invoked"
            )
            is True
        ),
        "scheduler_invocation_packet_not_execution_controller": True,
        "scheduler_invocation_packet_not_completion_gate": True,
        "allocation_plan_activity": (
            allocation_plan_activity_result
            if isinstance(allocation_plan_activity_result, dict)
            else {}
        ),
        "allocation_plan_latest_ref": str(
            allocation_plan_activity_result.get("allocation_plan_latest_ref") or ""
        )
        if isinstance(allocation_plan_activity_result, dict)
        else "",
        "allocation_plan_temporal_activity_latest_ref": str(
            allocation_plan_activity_result.get("allocation_plan_temporal_activity_latest_ref")
            or ""
        )
        if isinstance(allocation_plan_activity_result, dict)
        else "",
        "allocation_plan_worker_brief_queue_ref": str(
            allocation_plan_activity_result.get("worker_brief_queue_ref") or ""
        )
        if isinstance(allocation_plan_activity_result, dict)
        else "",
        "allocation_plan_lane_class_count": int(
            allocation_plan_activity_result.get("lane_class_count") or 0
        )
        if isinstance(allocation_plan_activity_result, dict)
        else 0,
        "allocation_plan_total_requested_width": int(
            allocation_plan_activity_result.get("total_requested_width") or 0
        )
        if isinstance(allocation_plan_activity_result, dict)
        else 0,
        "allocation_plan_target_width_source": str(
            allocation_plan_activity_result.get("target_width_source") or ""
        )
        if isinstance(allocation_plan_activity_result, dict)
        else "",
        "allocation_plan_fixed_20_or_50_used": (
            allocation_plan_activity_result.get("fixed_20_or_50_used")
            if isinstance(allocation_plan_activity_result, dict)
            else None
        ),
        "allocation_plan_repair_required": bool(
            isinstance(allocation_plan_activity_result, dict)
            and allocation_plan_activity_result.get("repair_required") is True
        ),
        "allocation_plan_validation_passed": bool(
            isinstance(allocation_plan_activity_result, dict)
            and allocation_plan_activity_result.get("allocation_plan_validation_passed") is True
        ),
        "allocation_plan_not_execution_controller": True,
        "allocation_plan_not_completion_gate": True,
        "source_frontier_workerbrief_bridge_activity": (
            source_frontier_workerbrief_bridge_activity_result
            if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
            else {}
        ),
        "source_frontier_workerbrief_bridge_latest_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get("bridge_latest_ref") or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_wave_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get("bridge_wave_ref") or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_source_bound_worker_brief_queue_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get(
                "source_bound_worker_brief_queue_ref"
            )
            or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_mapping_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get("mapping_ref") or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_worker_dispatch_ledger_wave_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get(
                "worker_dispatch_ledger_wave_ref"
            )
            or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_worker_dispatch_ledger_activity_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get(
                "worker_dispatch_ledger_activity_ref"
            )
            or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_readback_zh_ref": str(
            source_frontier_workerbrief_bridge_activity_result.get("readback_zh_ref") or ""
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else "",
        "source_frontier_workerbrief_bridge_source_item_count": int(
            source_frontier_workerbrief_bridge_activity_result.get("source_item_count") or 0
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else 0,
        "source_frontier_workerbrief_bridge_worker_brief_binding_count": int(
            source_frontier_workerbrief_bridge_activity_result.get(
                "worker_brief_binding_count"
            )
            or 0
        )
        if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
        else 0,
        "source_frontier_workerbrief_bridge_generated_bounded_item": (
            source_frontier_workerbrief_bridge_activity_result.get(
                "generated_bounded_item"
            )
            if isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
            else None
        ),
        "source_frontier_workerbrief_bridge_validation_passed": bool(
            isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
            and source_frontier_workerbrief_bridge_activity_result.get(
                "bridge_validation_passed"
            )
            is True
        ),
        "source_frontier_workerbrief_bridge_latest_alias_is_not_proof": bool(
            isinstance(source_frontier_workerbrief_bridge_activity_result, dict)
            and source_frontier_workerbrief_bridge_activity_result.get(
                "latest_alias_is_not_proof"
            )
            is True
        ),
        "source_frontier_workerbrief_bridge_not_execution_controller": True,
        "source_frontier_workerbrief_bridge_not_completion_gate": True,
        "source_frontier_workerpool_closure_activity": (
            source_frontier_workerpool_closure_activity_result
            if isinstance(source_frontier_workerpool_closure_activity_result, dict)
            else {}
        ),
        "source_frontier_workerpool_closure_wave_ref": str(
            source_frontier_workerpool_closure_activity_result.get("closure_wave_ref") or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_worker_dispatch_ledger_wave_ref": str(
            source_frontier_workerpool_closure_activity_result.get(
                "worker_dispatch_ledger_wave_ref"
            )
            or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_staging_ref": str(
            source_frontier_workerpool_closure_activity_result.get("staging_ref") or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_merge_ref": str(
            source_frontier_workerpool_closure_activity_result.get("merge_ref") or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_fan_in_ref": str(
            source_frontier_workerpool_closure_activity_result.get("fan_in_ref") or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_aaq_ref": str(
            source_frontier_workerpool_closure_activity_result.get("aaq_ref") or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_next_frontier_ref": str(
            source_frontier_workerpool_closure_activity_result.get("next_frontier_ref")
            or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_readback_zh_ref": str(
            source_frontier_workerpool_closure_activity_result.get("readback_zh_ref")
            or ""
        )
        if isinstance(source_frontier_workerpool_closure_activity_result, dict)
        else "",
        "source_frontier_workerpool_closure_repair_required": bool(
            isinstance(source_frontier_workerpool_closure_activity_result, dict)
            and source_frontier_workerpool_closure_activity_result.get(
                "repair_required"
            )
            is True
        ),
        "source_frontier_workerpool_closure_validation_passed": bool(
            isinstance(source_frontier_workerpool_closure_activity_result, dict)
            and source_frontier_workerpool_closure_activity_result.get(
                "closure_validation_passed"
            )
            is True
        ),
        "source_frontier_workerpool_closure_latest_alias_is_not_proof": bool(
            isinstance(source_frontier_workerpool_closure_activity_result, dict)
            and source_frontier_workerpool_closure_activity_result.get(
                "latest_alias_is_not_proof"
            )
            is True
        ),
        "source_frontier_workerpool_closure_not_execution_controller": True,
        "source_frontier_workerpool_closure_not_completion_gate": True,
        "pre_pass_audit_loop_activity": (
            pre_pass_audit_loop_activity_result
            if isinstance(pre_pass_audit_loop_activity_result, dict)
            else {}
        ),
        "pre_pass_audit_loop_latest_ref": str(
            pre_pass_audit_loop_activity_result.get("pre_pass_latest_ref") or ""
        )
        if isinstance(pre_pass_audit_loop_activity_result, dict)
        else "",
        "pre_pass_audit_loop_repair_plan_ref": str(
            pre_pass_audit_loop_activity_result.get("repair_plan_ref") or ""
        )
        if isinstance(pre_pass_audit_loop_activity_result, dict)
        else "",
        "pre_pass_audit_loop_repair_required": bool(
            isinstance(pre_pass_audit_loop_activity_result, dict)
            and pre_pass_audit_loop_activity_result.get("repair_required") is True
        ),
        "pre_pass_audit_loop_validation_passed": bool(
            isinstance(pre_pass_audit_loop_activity_result, dict)
            and pre_pass_audit_loop_activity_result.get("pre_pass_validation_passed") is True
        ),
        "pre_pass_audit_loop_not_execution_controller": True,
        "pre_pass_audit_loop_not_completion_gate": True,
        "ledger_auto_dispatch_ingress_activity": (
            ledger_auto_dispatch_ingress_activity_result
            if isinstance(ledger_auto_dispatch_ingress_activity_result, dict)
            else {}
        ),
        "ledger_auto_dispatch_ingress_runtime_enforced": bool(
            isinstance(ledger_auto_dispatch_ingress_activity_result, dict)
            and ledger_auto_dispatch_ingress_activity_result.get("runtime_enforced")
            is True
        ),
        "ledger_auto_dispatch_ingress_latest_ref": str(
            ledger_auto_dispatch_ingress_activity_result.get("output_paths", {}).get(
                "latest"
            )
            or ""
        )
        if isinstance(ledger_auto_dispatch_ingress_activity_result, dict)
        and isinstance(ledger_auto_dispatch_ingress_activity_result.get("output_paths"), dict)
        else "",
        "ledger_auto_dispatch_next_wave_id": str(
            ledger_auto_dispatch_ingress_activity_result.get("next_wave_id") or ""
        )
        if isinstance(ledger_auto_dispatch_ingress_activity_result, dict)
        else "",
        "mature_execution_carrier": str(segment_pass_next_worker.get("mature_execution_carrier") or input_payload.get("mature_execution_carrier") or MATURE_EXECUTION_CARRIER),
        "mature_execution_carrier_refs": list(segment_pass_next_worker.get("mature_execution_carrier_refs") or input_payload.get("mature_execution_carrier_refs") or MATURE_EXECUTION_CARRIER_REFS),
        "worker_evidence_contract": str(segment_pass_next_worker.get("worker_evidence_contract") or input_payload.get("worker_evidence_contract") or "task_bound_codex_exec_jsonl_or_app_server_sdk"),
        "codex_a_role": CODEX_A_BRAIN_DISPATCHER_ROLE,
        "codex_a_execution_owner": False,
        "worker_evidence_role": "task_bound_backend_evidence_not_panel_latest_truth",
        "segment_pass_checker_default": False,
        "same_workflow_next_worker_dispatched": bool(same_workflow_next_worker_dispatched),
        "same_workflow_next_worker_task_id": str(segment_pass_next_worker.get("worker_task_id") or ""),
        "same_workflow_next_worker_jsonl_path": str(segment_pass_next_worker.get("jsonl_path") or ""),
        "segment_pass_next_worker": segment_pass_next_worker if isinstance(segment_pass_next_worker, dict) else {},
        "jobs_json_observe_backend_readback": worker_observe,
        "jobs_json_observe_joined": bool(worker_observe),
        "task_bound_worker_token_usage": worker_observe.get("token_usage", {}) if worker_observe else {},
        "task_bound_worker_files_modified": worker_observe.get("files_modified", []) if worker_observe else [],
        "task_bound_worker_command_executions": worker_observe.get("command_executions", []) if worker_observe else [],
        "backend_evidence_refs": {
            "worker_jsonl_backend_evidence": str(observe_source_worker.get("jsonl_path") or "") if isinstance(observe_source_worker, dict) else "",
            "worker_final_backend_only": str(observe_source_worker.get("final_path") or "") if isinstance(observe_source_worker, dict) else "",
            "worker_raw_final_backend_only": str(observe_source_worker.get("raw_final_path") or "") if isinstance(observe_source_worker, dict) else "",
            "human_egress_filter_ref": str(observe_source_worker.get("human_egress_filter_ref") or "") if isinstance(observe_source_worker, dict) else "",
            "source_family_mature_thin_bind_sunset": str(
                source_family_mature_thin_bind_sunset_activity_result.get(
                    "source_family_mature_thin_bind_sunset_latest_ref"
                )
                or ""
            )
            if isinstance(source_family_mature_thin_bind_sunset_activity_result, dict)
            else "",
            "jobs_json_observe_backend_readback": bool(worker_observe),
            "phase5_observability_discovery_readback": True,
            "observability_discovery_evidence_refs": phase5_readback["evidence_refs"],
        },
        "phase5_observability_discovery_readback": phase5_readback,
        "observability_discovery_refs_joined": bool(phase5_readback["task_workflow_correlated"]),
        "trace_catalog_model_refs_are_evidence_only": True,
        "progress_truth_sources": phase5_readback["progress_truth_sources"],
        "observability_discovery_truth_promotion_denied_reason": phase5_readback["truth_promotion_denied_reason"],
        "current_task_owner_replacement_allowed": False,
        "human_egress_route": str(panel_activity.get("human_egress_route") or ""),
        "human_egress_router_ref": str(panel_activity.get("human_egress_router_ref") or ""),
        "grok_report_ref": str(panel_activity.get("grok_report_ref") or ""),
        "grok_report_latest_ref": str(panel_activity.get("grok_report_latest_ref") or ""),
        "grok_report_verify_pass": panel_activity.get("grok_report_verify_pass") is True,
        "codex_final_to_user_allowed": panel_activity.get("codex_final_to_user_allowed") is True,
        "worker_final_user_visible_allowed": panel_activity.get("worker_final_user_visible_allowed") is True,
        "no_pytest_wall_to_user": panel_activity.get("no_pytest_wall_to_user") is True,
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "segment_audit_gate": segment_audit_activity if isinstance(segment_audit_activity, dict) else {},
        "segment_audit_ready": bool(segment_audit_activity.get("segment_audit_ready")),
        "workflow_waiting_grok_segment_audit": bool(segment_audit_activity.get("workflow_waiting_grok_segment_audit")),
        "grok_verdict": str(segment_audit_activity.get("grok_verdict") or ""),
        "verdict_delivery_mode": str(segment_audit_activity.get("verdict_delivery_mode") or ""),
        "segment_audit_status": str(segment_audit_activity.get("status") or decision.get("segment_audit_status") or ""),
        "segment_audit_next_lane": str(
            decision.get("segment_audit_next_lane")
            or segment_audit_activity.get("next_lane")
            or ("L2" if str(segment_audit_activity.get("status")) == "GROK_SEGMENT_AUDIT_PASS" else "L1")
        ),
        "segment_audit_pass_dual_visible_and_backend": bool(
            str(segment_audit_activity.get("status")) == "GROK_SEGMENT_AUDIT_PASS"
            and bool(segment_audit_activity.get("dual_visible_and_backend_verdict"))
            and bool(segment_audit_activity.get("bidirectional_dual_delivery_full_ring_valid"))
        ),
        "backend_only_verdict_allowed": False,
        "activities": activities,
        "retry_policy": retry_policy_dict(),
        "non_retryable_policy_denials": list(NON_RETRYABLE_ERROR_TYPES),
        "transient_retryable_errors": list(TRANSIENT_ERROR_TYPES),
    }
    if live_temporal:
        result = compact_temporal_history_result(result)
    result["current_task_owner"] = build_current_task_owner(result)
    return result


def build_current_task_owner(result: dict[str, Any]) -> dict[str, Any]:
    return current_task_owner_from_input(result, live_temporal=bool(result.get("temporal_live_route")))


def current_task_owner_from_input(input_payload: dict[str, Any], *, live_temporal: bool) -> dict[str, Any]:
    object_binding = task_object_binding_from_payload(input_payload)
    completion_decision = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
    return {
        "schema_version": "xinao.current_task_owner.v1",
        "generated_at": input_payload.get("generated_at", now()),
        "task_id": input_payload["task_id"],
        "active_object_id": input_payload.get("active_object_id", ACTIVE_OBJECT_ID),
        "owner_kind": "TemporalWorkflow",
        "workflow_id": input_payload.get("workflow_id", ""),
        "workflow_run_id": input_payload.get("workflow_run_id", ""),
        "task_queue": input_payload.get("task_queue", DEFAULT_TASK_QUEUE),
        "server_bound": bool(input_payload.get("server_bound", live_temporal and bool(input_payload.get("workflow_id")) and bool(input_payload.get("workflow_run_id")))),
        "workflow_open": bool(input_payload.get("workflow_open", live_temporal and not bool(input_payload.get("temporal_workflow_completed")))),
        "workflow_completed_partial": bool(input_payload.get("workflow_completed_partial", live_temporal and completion_decision.get("status") == "partial")),
        "workflow_internal_timer_scheduled": bool(input_payload.get("workflow_internal_timer_scheduled")),
        "workflow_kept_open_by_durable_timer": bool(input_payload.get("workflow_kept_open_by_durable_timer")),
        "execution_mode": "temporal_server" if live_temporal else str(input_payload.get("execution_mode") or "local_temporal_compat"),
        "local_run_observed": bool(input_payload.get("local_run_observed") or (not live_temporal)),
        "mature_execution_carrier": str(input_payload.get("mature_execution_carrier") or MATURE_EXECUTION_CARRIER),
        "mature_execution_carrier_refs": list(input_payload.get("mature_execution_carrier_refs") or MATURE_EXECUTION_CARRIER_REFS),
        "worker_evidence_contract": str(input_payload.get("worker_evidence_contract") or "task_bound_codex_exec_jsonl_or_app_server_sdk"),
        "segment_pass_checker_default": input_payload.get("segment_pass_checker_default") is True,
        "mainline_next_hop": input_payload.get("mainline_next_hop") or (
            "same_workflow_assignment_driven_implementation_worker"
            if bool(input_payload.get("same_workflow_next_worker_dispatched"))
            and str(input_payload.get("worker_kind") or "") == "implementation_worker"
            else
            SEGMENT_PASS_NEXT_BOUNDED_WORKER_HOP
            if bool(input_payload.get("same_workflow_next_worker_dispatched"))
            else
            "temporal_workflow_internal_timer_or_signal_wait"
            if bool(input_payload.get("workflow_internal_timer_scheduled"))
            else ""
        ),
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "segment_audit_ready": bool(input_payload.get("segment_audit_ready")),
        "workflow_waiting_grok_segment_audit": bool(input_payload.get("workflow_waiting_grok_segment_audit")),
        "grok_verdict": str(input_payload.get("grok_verdict") or ""),
        "verdict_delivery_mode": str(input_payload.get("verdict_delivery_mode") or ""),
        "segment_audit_status": str(input_payload.get("segment_audit_status") or ""),
        "segment_audit_next_lane": str(
            input_payload.get("segment_audit_next_lane")
            or ("L2" if str(input_payload.get("segment_audit_status")) == "GROK_SEGMENT_AUDIT_PASS" else "L1")
        ),
        "g2_temporal_server_verification_ref": str(input_payload.get("g2_temporal_server_verification_ref") or ""),
        "worker_service_polling": bool(input_payload.get("worker_service_polling", False)),
        "worker_service_evidence": input_payload.get("worker_service_evidence", {}),
        "segment_pass_must_dispatch_next_bounded_worker": bool(input_payload.get("segment_pass_must_dispatch_next_bounded_worker")),
        "same_workflow_next_worker_dispatched": bool(input_payload.get("same_workflow_next_worker_dispatched")),
        "same_workflow_next_worker_task_id": str(input_payload.get("same_workflow_next_worker_task_id") or ""),
        "same_workflow_next_worker_jsonl_path": str(input_payload.get("same_workflow_next_worker_jsonl_path") or ""),
        "human_egress_route": str(input_payload.get("human_egress_route") or ""),
        "human_egress_router_ref": str(input_payload.get("human_egress_router_ref") or ""),
        "grok_report_ref": str(input_payload.get("grok_report_ref") or ""),
        "grok_report_verify_pass": input_payload.get("grok_report_verify_pass") is True,
        "codex_final_to_user_allowed": input_payload.get("codex_final_to_user_allowed") is True,
        "worker_final_user_visible_allowed": input_payload.get("worker_final_user_visible_allowed") is True,
        "no_pytest_wall_to_user": input_payload.get("no_pytest_wall_to_user") is True,
        "jobs_json_observe_backend_readback": input_payload.get("jobs_json_observe_backend_readback") if isinstance(input_payload.get("jobs_json_observe_backend_readback"), dict) else {},
        "jobs_json_observe_joined": input_payload.get("jobs_json_observe_joined") is True,
        "task_bound_worker_token_usage": input_payload.get("task_bound_worker_token_usage") if isinstance(input_payload.get("task_bound_worker_token_usage"), dict) else {},
        "task_bound_worker_files_modified": input_payload.get("task_bound_worker_files_modified") if isinstance(input_payload.get("task_bound_worker_files_modified"), list) else [],
        "task_bound_worker_command_executions": input_payload.get("task_bound_worker_command_executions") if isinstance(input_payload.get("task_bound_worker_command_executions"), list) else [],
        "backend_evidence_refs": input_payload.get("backend_evidence_refs") if isinstance(input_payload.get("backend_evidence_refs"), dict) else {},
        "codex_a_role": str(input_payload.get("codex_a_role") or CODEX_A_BRAIN_DISPATCHER_ROLE),
        "codex_a_execution_owner": False,
        "worker_evidence_role": "task_bound_backend_evidence_not_panel_latest_truth",
        "backend_only_verdict_allowed": False,
        "verification_level": input_payload.get("verification_level") or (
            VERIFICATION_LEVEL_WORKFLOW_OPEN
            if live_temporal and not bool(input_payload.get("temporal_workflow_completed"))
            else VERIFICATION_LEVEL_SERVER_HISTORY
            if live_temporal
            else VERIFICATION_LEVEL_READ_MODEL
        ),
        "compiled_task_object_sha256": object_binding["compiled_task_object_sha256"],
        "source_refs_sha256": object_binding["source_refs_sha256"],
        "acceptance_contract": object_binding["acceptance_contract"],
        "execution_event_source": "Temporal Event History" if live_temporal else "local durable compatibility flow",
        "execution_surface": "Temporal workflow -> LangGraph checkpoint/frontier -> Codex exec/app-server worker evidence -> /completion/claim",
        "stop_gate_scope": "current_task_id_only",
        "stop_gate_must_read": [
            "current task workflow_id/run_id",
            "current task LangGraph checkpoint/frontier",
            "current task Codex exec JSONL or app-server event evidence",
            "current task /completion/claim decision",
            "current task verifier and side-audit evidence",
        ],
        "forbidden_completion_sources": [
            "global latest.json without matching task_id",
            "report text",
            "projection summary",
            "blackboard message",
            "Codex final response without post-final gate",
        ],
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "authority_boundary": authority_boundary("current_task_owner_read_model_from_temporal"),
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
    execute_codex_worker: bool = False,
    codex_worker_prompt: str = "",
    codex_worker_task_id: str = "",
    codex_worker_expected_marker: str = TASK_BOUND_CODEX_WORKER_MARKER,
    codex_worker_timeout_sec: int = 300,
    promote_current_task_owner_latest: bool = True,
    promote_langgraph_latest: bool | None = None,
    extra_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_payload = {
        "task_id": task_id,
        "user_goal": user_goal,
        "mode": mode,
        "runtime_root": str(runtime_root),
        "route_profile": "seed_cortex_phase0" if task_id == SEED_CORTEX_WORK_ID or "seed_cortex" in task_id else "",
        "allow_complete_fixture": allow_complete_fixture,
        "source_refs": list(source_refs or []),
        "compiled_task_object": dict(compiled_task_object or {}),
        "runtime_subject_loop_required": list(runtime_subject_loop_required or langgraph_task_runner.RUNTIME_SUBJECT_LOOP_REQUIRED),
        "root_repair_constraints": list(root_repair_constraints or langgraph_task_runner.ROOT_REPAIR_CONSTRAINTS),
        "minimum_reality_contact_required": minimum_reality_contact_required,
        "no_new_parallel_control_surface": no_new_parallel_control_surface,
        "execute_codex_worker": execute_codex_worker,
        "codex_worker_prompt": codex_worker_prompt,
        "codex_worker_task_id": codex_worker_task_id,
        "codex_worker_expected_marker": codex_worker_expected_marker,
        "codex_worker_timeout_sec": codex_worker_timeout_sec,
        "promote_current_task_owner_latest": promote_current_task_owner_latest,
        "promote_langgraph_latest": promote_current_task_owner_latest if promote_langgraph_latest is None else promote_langgraph_latest,
        "workflow_id": f"xinao-codex-task-{task_id}-{run_id()}",
        "workflow_run_id": f"local-run-{run_id()}",
        "task_queue": DEFAULT_TASK_QUEUE,
    }
    if extra_input:
        input_payload.update(extra_input)
    activities: list[dict[str, Any]] = []
    activities.append(asyncio.run(bind_task_activity(input_payload)))
    if simulate_transient_failure:
        activities.append({
            "activity": "run_langgraph",
            "status": "transient_failed_then_retried",
            "error_type": "XINAO_TRANSIENT_TOOL_ERROR",
            "retry_allowed": True,
        })
    graph = asyncio.run(run_langgraph_activity(input_payload))
    activities.append(graph)
    codex_worker = asyncio.run(codex_worker_turn_activity(input_payload))
    activities.append(codex_worker)
    claim = asyncio.run(completion_claim_activity({
        "graph_result": graph["graph_result"],
        "current_task_owner": current_task_owner_from_input(input_payload, live_temporal=False),
        "runtime_root": str(runtime_root),
        "promote_current_task_owner_latest": promote_current_task_owner_latest,
    }))
    segment_gate = asyncio.run(segment_audit_gate_activity({
        **input_payload,
        "completion_decision": claim["completion_decision"],
        "worker_dispatch_evidence": codex_worker,
    }))
    activities.append(segment_gate)
    activities.append(claim)
    overridden_decision = _grok_segment_waiting_decision_override(
        claim["completion_decision"],
        segment_gate if isinstance(segment_gate, dict) else {},
    )
    activities.append(asyncio.run(write_status_activity({
        "runtime_root": str(runtime_root),
        "completion_decision": overridden_decision,
    })))
    segment_pass_next_worker: dict[str, Any] = {}
    if (
        segment_gate.get("status") == "GROK_SEGMENT_AUDIT_PASS"
        and overridden_decision.get("status") == "partial"
        and phase_exit_segment_pass_allowed(input_payload, segment_gate if isinstance(segment_gate, dict) else {})
    ):
        next_worker_input = segment_pass_next_worker_payload(input_payload, overridden_decision, segment_gate if isinstance(segment_gate, dict) else {})
        segment_pass_next_worker = asyncio.run(codex_worker_turn_activity(
            next_worker_input
        ))
        segment_pass_next_worker.update({
            "segment_pass_next_worker_required": True,
            "segment_pass_same_workflow": True,
            "worker_task_id": str(next_worker_input.get("codex_worker_task_id") or ""),
        })
        activities.append(segment_pass_next_worker)
    elif (
        overridden_decision.get("status") == "partial"
        and segment_gate.get("workflow_waiting_grok_segment_audit") is True
        and segment_gate.get("status") != "GROK_SEGMENT_AUDIT_PASS"
    ):
        next_worker_input = grok_wait_l1_continuation_worker_payload(input_payload, overridden_decision, segment_gate if isinstance(segment_gate, dict) else {}, len(activities) + 1)
        if next_worker_input.get("execute_codex_worker") is True:
            segment_pass_next_worker = asyncio.run(codex_worker_turn_activity(next_worker_input))
            segment_pass_next_worker.update({
                "grok_wait_l1_continuation_worker_required": True,
                "grok_waiting_does_not_block_continuation": True,
                "segment_pass_next_worker_required": False,
                "segment_pass_same_workflow": True,
                "worker_task_id": str(next_worker_input.get("codex_worker_task_id") or ""),
            })
            activities.append(segment_pass_next_worker)
    continuation = asyncio.run(partial_continuation_dispatch_activity({
        **input_payload,
        "completion_decision": overridden_decision,
        "segment_audit_gate": segment_gate,
        "segment_pass_next_worker": segment_pass_next_worker,
    }))
    activities.append(continuation)
    activities.append(asyncio.run(panel_writeback_zh_activity({
        **input_payload,
        "completion_decision": overridden_decision,
        "worker_dispatch_evidence": codex_worker,
        "partial_continuation_dispatch": continuation,
        "segment_audit_gate": segment_gate,
        "segment_pass_next_worker": segment_pass_next_worker,
    })))
    if should_call_seed_cortex_worker_dispatch_ledger(input_payload):
        current_wave_index = 1
        current_wave_id = temporal_hot_path_wave_id(input_payload, current_wave_index)
        worker_evidence = [codex_worker]
        if segment_pass_next_worker:
            worker_evidence.append(segment_pass_next_worker)
        worker_ledger = asyncio.run(worker_dispatch_ledger_activity({
            **input_payload,
            "worker_dispatch_evidence": worker_evidence,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(worker_ledger)
        main_loop_tick = asyncio.run(main_execution_loop_tick_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(main_loop_tick)
        durable_wave_packet = asyncio.run(durable_parallel_wave_packet_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(durable_wave_packet)
        source_frontier_consumer = asyncio.run(source_frontier_durable_consumer_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
            "source_frontier_consumer_max_waves": 3,
        }))
        activities.append(source_frontier_consumer)
        default_dp_payload = {
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "wave_id": f"{current_wave_id}-default-dp-worker-pool",
            "wave_index": current_wave_index,
            "target_width": int(input_payload.get("autonomous_dp_target_width") or 0),
            "max_parallel_workers": int(
                input_payload.get("autonomous_dp_max_parallel_workers")
                or input_payload.get("max_parallel_workers")
                or 0
            ),
            "phase3_event_queue_self_chain_enabled": input_payload.get(
                "phase3_event_queue_self_chain_enabled", True
            )
            is not False,
            "phase3_max_event_waves_per_run": int(
                input_payload.get("phase3_max_event_waves_per_run")
                or input_payload.get("max_event_waves_per_run")
                or 1
            ),
            "phase3_event_wave_index_in_run": current_wave_index,
            "phase3_continue_generation": int(input_payload.get("phase3_continue_generation") or 0),
        }
        default_dp_worker_pool_wave = asyncio.run(dp_worker_pool_wave_activity(default_dp_payload))
        activities.append(default_dp_worker_pool_wave)
        default_dp_fan_in = asyncio.run(draft_staging_fan_in_activity({
            **default_dp_payload,
            "dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
        }))
        activities.append(default_dp_fan_in)
        default_loop_runtime_state = asyncio.run(loop_runtime_state_update_activity({
            **default_dp_payload,
            "dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "draft_staging_fan_in_activity": default_dp_fan_in,
        }))
        activities.append(default_loop_runtime_state)
        source_family_wave = asyncio.run(source_family_wave_scheduler_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(source_family_wave)
        source_family_phase5_sunset = {}
        if (
            source_family_wave
            and source_family_wave.get("next_frontier_action")
            == source_family_mature_thin_bind_sunset.PHASE5_ACTION
        ):
            source_family_phase5_sunset = asyncio.run(source_family_mature_thin_bind_sunset_activity({
                **input_payload,
                "worker_dispatch_ledger_activity": worker_ledger,
                "main_execution_loop_tick_activity": main_loop_tick,
                "durable_parallel_wave_packet_activity": durable_wave_packet,
                "source_frontier_durable_consumer_activity": source_frontier_consumer,
                "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                "source_family_wave_scheduler_activity": source_family_wave,
                "wave_id": current_wave_id,
                "wave_index": current_wave_index,
            }))
            activities.append(source_family_phase5_sunset)
        phase0_kernel = asyncio.run(phase0_reusable_kernel_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(phase0_kernel)
        wave2_hygiene = asyncio.run(wave2_mainchain_hygiene_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(wave2_hygiene)
        allocation_plan_result = asyncio.run(allocation_plan_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(allocation_plan_result)
        source_frontier_workerbrief_bridge_result = asyncio.run(source_frontier_workerbrief_bridge_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "allocation_plan_activity": allocation_plan_result,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(source_frontier_workerbrief_bridge_result)
        source_frontier_workerpool_closure_result = asyncio.run(source_frontier_workerpool_closure_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "allocation_plan_activity": allocation_plan_result,
            "parent_wave_id": f"{current_wave_id}-source-frontier-workerbrief-bridge",
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(source_frontier_workerpool_closure_result)
        default_trigger_candidate = asyncio.run(default_main_loop_trigger_candidate_activity({
            **input_payload,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "allocation_plan_activity": allocation_plan_result,
            "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
            "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(default_trigger_candidate)
        scheduler_packet = asyncio.run(scheduler_invocation_packet_activity({
            **input_payload,
            "main_execution_loop_tick_activity": main_loop_tick,
            "worker_dispatch_ledger_activity": worker_ledger,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
            "allocation_plan_activity": allocation_plan_result,
            "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
            "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(scheduler_packet)
        pre_pass_audit = asyncio.run(pre_pass_audit_loop_activity({
            **input_payload,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "allocation_plan_activity": allocation_plan_result,
            "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
            "scheduler_invocation_packet_activity": scheduler_packet,
            "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
            "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(pre_pass_audit)
        auto_dispatch_ingress = asyncio.run(ledger_auto_dispatch_ingress_activity({
            **input_payload,
            "partial_continuation_dispatch": continuation,
            "worker_dispatch_evidence": worker_evidence,
            "worker_dispatch_ledger_activity": worker_ledger,
            "main_execution_loop_tick_activity": main_loop_tick,
            "durable_parallel_wave_packet_activity": durable_wave_packet,
            "source_frontier_durable_consumer_activity": source_frontier_consumer,
            "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
            "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
            "default_loop_runtime_state_update_activity": default_loop_runtime_state,
            "source_family_wave_scheduler_activity": source_family_wave,
            "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
            "phase0_reusable_kernel_activity": phase0_kernel,
            "wave2_mainchain_hygiene_activity": wave2_hygiene,
            "allocation_plan_activity": allocation_plan_result,
            "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
            "scheduler_invocation_packet_activity": scheduler_packet,
            "pre_pass_audit_loop_activity": pre_pass_audit,
            "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
            "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(auto_dispatch_ingress)
    result = build_workflow_result(input_payload, activities, live_temporal=False)
    persist_workflow_result(runtime_root, result)
    return result


async def run_live_temporal_workflow(input_payload: dict[str, Any]) -> dict[str, Any]:
    from temporalio.client import Client

    task_queue = input_payload.get("task_queue", DEFAULT_TASK_QUEUE)
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    poller_ok, poller_evidence = temporal_task_queue_has_poller(str(task_queue))
    if not poller_ok:
        return {
            "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
            "generated_at": now(),
            "workflow_id": input_payload.get("workflow_id") or "",
            "workflow_run_id": "",
            "task_queue": task_queue,
            "active_object_id": ACTIVE_OBJECT_ID,
            "task_id": input_payload["task_id"],
            "temporal_workflow_completed": False,
            "temporal_live_route": True,
            "server_bound": False,
            "workflow_open": False,
            "workflow_completed_partial": False,
            "verification_level": VERIFICATION_LEVEL_READ_MODEL,
            "partial_frontier_open": False,
            "workflow_internal_timer_scheduled": False,
            "workflow_kept_open_by_durable_timer": False,
            "mainline_next_hop": "",
            "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
            "workflow_completed_is_not_user_complete": True,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "canonical_completion_source": "/completion/claim",
            "execution_mode": "temporal_server",
            "local_run_observed": False,
            "completion_decision": {
                "status": "blocked",
                "stop_allowed": False,
                "named_blocker": poller_evidence.get("named_blocker") or "TEMPORAL_WORKER_SERVICE_NOT_POLLING",
                "not_source_of_truth": True,
                "not_user_completion": True,
            },
            "user_task_complete": False,
            "activities": [],
            "current_task_owner": current_task_owner_from_input({
                **input_payload,
                "workflow_id": input_payload.get("workflow_id") or "",
                "workflow_run_id": "",
                "task_queue": task_queue,
            }, live_temporal=True),
            "worker_service_polling": False,
            "worker_service_evidence": poller_evidence,
            "retry_policy": retry_policy_dict(),
            "non_retryable_policy_denials": list(NON_RETRYABLE_ERROR_TYPES),
            "transient_retryable_errors": list(TRANSIENT_ERROR_TYPES),
        }
    client = await Client.connect(TEMPORAL_ADDRESS)
    task_queue = input_payload.get("task_queue", DEFAULT_TASK_QUEUE)
    workflow_id = input_payload.get("workflow_id") or f"xinao-codex-task-{input_payload['task_id']}-{run_id()}"
    handle = await client.start_workflow(
        TemporalCodexTaskWorkflow.run,
        input_payload,
        id=workflow_id,
        task_queue=task_queue,
    )
    verification_summary: dict[str, Any] = {}
    verification_level = VERIFICATION_LEVEL_READ_MODEL
    workflow_open = False
    try:
        verification_summary, verification_level = _verify_temporal_workflow_history(
            runtime_root=runtime_root,
            task_id=input_payload["task_id"],
            workflow_id=workflow_id,
            workflow_run_id=handle.result_run_id,
        )
        verification_level = normalize_verification_level(verification_level)
        workflow_open = bool(verification_summary.get("workflow_open"))
    except Exception:
        verification_summary = {"verify_exception": "temporal_workflow_verification_failed"}
        verification_level = VERIFICATION_LEVEL_READ_MODEL

    g2_ref = str(verification_summary.get("summary_ref") or "")
    result = {
        "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
        "generated_at": now(),
        "workflow_id": workflow_id,
        "workflow_run_id": handle.result_run_id,
        "task_queue": task_queue,
        "active_object_id": ACTIVE_OBJECT_ID,
        "task_id": input_payload["task_id"],
        "temporal_workflow_completed": False,
        "temporal_live_route": True,
        "server_bound": True,
        "workflow_open": workflow_open,
        "workflow_completed_partial": bool(workflow_open),
        "verification_level": normalize_verification_level(verification_level),
        "partial_frontier_open": True,
        "workflow_internal_timer_scheduled": False,
        "workflow_kept_open_by_durable_timer": False,
        "mainline_next_hop": "temporal_workflow_internal_timer_or_signal_wait" if workflow_open else "",
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "workflow_completed_is_not_user_complete": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "canonical_completion_source": "/completion/claim",
        "execution_mode": "temporal_server",
        "local_run_observed": False,
        "completion_decision": {"status": "partial", "stop_allowed": False, "not_source_of_truth": True, "not_user_completion": True},
        "user_task_complete": False,
        "g2_temporal_server_verification_ref": g2_ref,
        "g2_temporal_server_verification": verification_summary,
        "activities": [],
        "current_task_owner": current_task_owner_from_input({
            **input_payload,
            "workflow_id": workflow_id,
            "workflow_run_id": handle.result_run_id,
            "task_queue": task_queue,
            "execution_mode": "temporal_server",
            "verification_level": verification_level,
            "local_run_observed": False,
            "worker_service_polling": True,
            "worker_service_evidence": poller_evidence,
            "g2_temporal_server_verification_ref": g2_ref,
        }, live_temporal=True),
        "worker_service_polling": True,
        "worker_service_evidence": poller_evidence,
        "retry_policy": retry_policy_dict(),
        "non_retryable_policy_denials": list(NON_RETRYABLE_ERROR_TYPES),
        "transient_retryable_errors": list(TRANSIENT_ERROR_TYPES),
    }
    return result


async def run_worker_forever(task_queue: str) -> None:
    from temporalio.client import Client
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker

    client = await Client.connect(TEMPORAL_ADDRESS)
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[TemporalCodexTaskWorkflow],
        activities=[
            bind_task_activity,
            run_langgraph_activity,
            codex_worker_turn_activity,
            worker_dispatch_ledger_activity,
            main_execution_loop_tick_activity,
            allocation_plan_activity,
            pre_pass_audit_loop_activity,
            dp_worker_pool_wave_activity,
            draft_staging_fan_in_activity,
            loop_runtime_state_update_activity,
            codex_native_provider_scheduler_phase4_activity,
            durable_parallel_wave_packet_activity,
            source_frontier_durable_consumer_activity,
            source_frontier_workerbrief_bridge_activity,
            source_frontier_workerpool_closure_activity,
            source_family_wave_scheduler_activity,
            source_family_mature_thin_bind_sunset_activity,
            phase0_reusable_kernel_activity,
            wave2_mainchain_hygiene_activity,
            default_main_loop_trigger_candidate_activity,
            scheduler_invocation_packet_activity,
            ledger_auto_dispatch_ingress_activity,
            completion_claim_activity,
            write_status_activity,
            partial_continuation_dispatch_activity,
            segment_audit_gate_activity,
            panel_writeback_zh_activity,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await asyncio.Event().wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Temporal Codex task workflow bound to /completion/claim.")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--user-goal", default="")
    parser.add_argument("--mode", choices=("partial", "complete"), default="partial")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--allow-complete-fixture", action="store_true")
    parser.add_argument("--simulate-transient-failure", action="store_true")
    parser.add_argument("--live-temporal", action="store_true")
    parser.add_argument("--local-temporal-compat-rescue", action="store_true")
    parser.add_argument("--execute-codex-worker", action="store_true")
    parser.add_argument("--codex-worker-prompt", default="")
    parser.add_argument("--codex-worker-task-id", default="")
    parser.add_argument("--codex-worker-timeout-sec", type=int, default=300)
    parser.add_argument("--phase4-skip-codex-exec-canary", action="store_true")
    parser.add_argument("--phase4-codex-exec-timeout-seconds", type=int, default=180)
    parser.add_argument("--phase4-skip-qwen-canary", action="store_true")
    parser.add_argument("--phase4-qwen-timeout-seconds", type=int, default=60)
    parser.add_argument("--segment-pass-next-worker-task-id", default="")
    parser.add_argument("--human-egress-route", default="")
    parser.add_argument("--segment-boundary-headless", action="store_true")
    parser.add_argument("--no-promote-current-task-owner-latest", action="store_true")
    parser.add_argument("--source-ref", action="append", default=[], help="Non-authoritative semantic input file to bind into TaskObject with hash.")
    parser.add_argument("--compiled-task-object-json", default="", help="Path to the already compiled parent TaskObject JSON to pass through Temporal.")
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--worker", action="store_true", help="Run the long-lived Temporal worker service for this task queue.")
    args = parser.parse_args()
    if args.worker:
        asyncio.run(run_worker_forever(args.task_queue))
        return 0
    if not args.task_id:
        parser.error("--task-id is required unless --worker is used")
    runtime_root = pathlib.Path(args.runtime_root)
    source_refs = [file_source_ref(pathlib.Path(path)) for path in args.source_ref]
    compiled_task_object = read_compiled_task_object(pathlib.Path(args.compiled_task_object_json)) if args.compiled_task_object_json else {}
    human_egress_route = str(args.human_egress_route or "").strip()
    segment_boundary_headless = bool(args.segment_boundary_headless or human_egress_route == "grok_report_only")
    if args.live_temporal:
        result = asyncio.run(run_live_temporal_workflow({
            "task_id": args.task_id,
            "user_goal": args.user_goal,
            "mode": args.mode,
            "runtime_root": str(runtime_root),
            "route_profile": "seed_cortex_phase0" if args.task_id == SEED_CORTEX_WORK_ID or "seed_cortex" in args.task_id else "",
            "allow_complete_fixture": args.allow_complete_fixture,
            "source_refs": source_refs,
            "compiled_task_object": compiled_task_object,
            "runtime_subject_loop_required": list(langgraph_task_runner.RUNTIME_SUBJECT_LOOP_REQUIRED),
            "root_repair_constraints": list(langgraph_task_runner.ROOT_REPAIR_CONSTRAINTS),
            "minimum_reality_contact_required": True,
            "no_new_parallel_control_surface": True,
            "execute_codex_worker": args.execute_codex_worker,
            "codex_worker_prompt": args.codex_worker_prompt,
            "codex_worker_task_id": args.codex_worker_task_id,
            "codex_worker_expected_marker": TASK_BOUND_CODEX_WORKER_MARKER,
            "codex_worker_timeout_sec": args.codex_worker_timeout_sec,
            "phase4_invoke_codex_exec": not args.phase4_skip_codex_exec_canary,
            "phase4_codex_exec_timeout_seconds": args.phase4_codex_exec_timeout_seconds,
            "phase4_invoke_qwen": not args.phase4_skip_qwen_canary,
            "phase4_qwen_timeout_seconds": args.phase4_qwen_timeout_seconds,
            "segment_pass_next_worker_task_id": args.segment_pass_next_worker_task_id,
            "human_egress_route": human_egress_route,
            "segment_boundary_headless": segment_boundary_headless,
            "worker_final_user_visible_allowed": False if segment_boundary_headless else True,
            "promote_current_task_owner_latest": not args.no_promote_current_task_owner_latest,
            "task_queue": args.task_queue,
            "workflow_id": args.workflow_id,
        }))
        persist_workflow_result(runtime_root, result)
    elif args.local_temporal_compat_rescue:
        result = run_local_durable_flow(
            task_id=args.task_id,
            user_goal=args.user_goal,
            mode=args.mode,
            runtime_root=runtime_root,
            extra_input={
                "route_profile": "seed_cortex_phase0"
                if args.task_id == SEED_CORTEX_WORK_ID or "seed_cortex" in args.task_id
                else "",
                "segment_pass_next_worker_task_id": args.segment_pass_next_worker_task_id,
                "human_egress_route": human_egress_route,
                "segment_boundary_headless": segment_boundary_headless,
                "worker_final_user_visible_allowed": False if segment_boundary_headless else True,
            },
            allow_complete_fixture=args.allow_complete_fixture,
            simulate_transient_failure=args.simulate_transient_failure,
            source_refs=source_refs,
            compiled_task_object=compiled_task_object,
            execute_codex_worker=args.execute_codex_worker,
            codex_worker_prompt=args.codex_worker_prompt,
            codex_worker_task_id=args.codex_worker_task_id,
            codex_worker_expected_marker=TASK_BOUND_CODEX_WORKER_MARKER,
            codex_worker_timeout_sec=args.codex_worker_timeout_sec,
            promote_current_task_owner_latest=not args.no_promote_current_task_owner_latest,
        )
    else:
        result = {
            "workflow_id": args.workflow_id or "",
            "temporal_workflow_completed": False,
            "user_task_complete": False,
            "completion_decision": {
                "status": "blocked",
                "stop_allowed": False,
                "named_blocker": "BLOCKED_TEMPORAL_LIVE_ROUTE_REQUIRED",
                "reason": "Default workflow CLI requires --live-temporal. The local-run compatibility flow requires explicit --local-temporal-compat-rescue.",
                "not_source_of_truth": True,
                "not_user_completion": True,
            },
            "named_blocker": "BLOCKED_TEMPORAL_LIVE_ROUTE_REQUIRED",
            "not_source_of_truth": True,
            "not_user_completion": True,
        }
        print(json.dumps({
            "workflow_id": result["workflow_id"],
            "temporal_workflow_completed": result["temporal_workflow_completed"],
            "user_task_complete": result["user_task_complete"],
            "completion_decision": result["completion_decision"],
            "named_blocker": result["named_blocker"],
            "sentinel": SENTINEL,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "workflow_id": result["workflow_id"],
        "temporal_workflow_completed": result["temporal_workflow_completed"],
        "user_task_complete": result["user_task_complete"],
        "completion_decision": result["completion_decision"],
        "sentinel": SENTINEL,
    }, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
