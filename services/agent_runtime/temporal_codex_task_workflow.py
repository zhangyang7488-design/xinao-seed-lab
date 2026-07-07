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
from services.agent_runtime import cheap_worker_patch_executor
from services.agent_runtime import codex_native_provider_scheduler_phase4
from services.agent_runtime import codex_s_main_execution_loop_tick
from services.agent_runtime import completion_claim_payload_builder as builder
from services.agent_runtime import default_main_loop_trigger_candidate
from services.agent_runtime import dp_sidecar_execution_port
from services.agent_runtime import durable_parallel_wave_packet
from services.agent_runtime import langgraph_task_runner
from services.agent_runtime import phase0_reusable_kernel
from services.agent_runtime import pre_pass_audit_loop
from services.agent_runtime import scheduler_invocation_packet
from services.agent_runtime import source_frontier_fanin_acceptance
from services.agent_runtime import source_frontier_workerbrief_bridge
from services.agent_runtime import source_frontier_workerpool_closure
from services.agent_runtime import source_family_adapter_smoke
from services.agent_runtime import source_family_adapter_value_eval
from services.agent_runtime import source_family_mature_thin_bind_sunset
from services.agent_runtime import source_family_smoked_candidate_thin_bind
from services.agent_runtime import source_family_wave_scheduler
from services.agent_runtime import task_contract_router
from services.agent_runtime import temporal_activity_no_window_dp_worker_pool_phase3
from services.agent_runtime import wave2_mainchain_hygiene
from services.agent_runtime import modular_dynamic_worker_pool_phase1 as worker_pool_phase1
from services.agent_runtime import current_task_source_intake
from services.agent_runtime import mature_bind_queue_autopop
from services.agent_runtime import next_frontier_continuation_supervisor
from services.agent_runtime import post_continue_as_new_status_refresh
from services.agent_runtime import ucp_tool_surface_resolver
from services.agent_runtime import v4pro_mature_bind_execution_controller
from services.agent_runtime import v4pro_supervisor_orchestrator
from services.agent_runtime import v4pro_tool_bearing_executor_policy
from services.agent_runtime import root_intent_loop_driver
from services.agent_runtime import worker_dispatch_ledger
from services.agent_runtime import codex_333_run_reconciler


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
DEFAULT_CANONICAL_MAINLINE_WORKFLOW_ID = os.environ.get(
    "XINAO_CODEX_S_CANONICAL_MAINLINE_WORKFLOW_ID",
    "codex-s-333-mainline-p0-20260707-r9-task-package-resolver-global-hardened",
)
CURRENT_P0_THREE_TEXT_SOURCE_PACKAGE_ID = "current_p0_three_text_20260707"
P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID = "p0_007_default_main_loop_trigger_bind"
P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID = "p0_008_worker_dispatch_real_receipt"
CURRENT_P0_THREE_TEXT_FILENAMES = frozenset(
    {
        "01_总说明_本项目是什么_20260707.txt",
        "02_P0_底座全自动任务落地_20260707.txt",
        "03_P1_任务落地_20260707.txt",
    }
)
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
V4PRO_NEXT_SEGMENT_BRAIN_DISPATCH_MARKER = "RESULT_XINAO_V4PRO_NEXT_SEGMENT_BRAIN_DISPATCH_OK"
SEGMENT_PASS_NEXT_BOUNDED_WORKER_HOP = "same_workflow_segment_pass_next_bounded_worker"
V4PRO_BRAIN_DISPATCH_PROVIDER = "deepseek_v4_pro"
WORKER_TURN_ROUTE_LOCAL_QWEN = "local_ollama_qwen"
WORKER_TURN_ROUTE_LOCAL_QWEN3 = "local_ollama_qwen3"
WORKER_TURN_ROUTE_LOCAL_QWEN_CODER = "local_ollama_qwen25_coder"
WORKER_TURN_ROUTE_LOCAL_DEEPSEEK_R1 = "local_ollama_deepseek_r1"
WORKER_TURN_ROUTE_QWEN = "qwen_prepaid_cheap_worker"
WORKER_TURN_ROUTE_V4PRO = "deepseek_v4_pro"
WORKER_TURN_ROUTE_CODEX_FINAL = "codex_exec"
WORKER_TURN_LOCAL_POOL_ROUTES = {
    WORKER_TURN_ROUTE_LOCAL_QWEN,
    WORKER_TURN_ROUTE_LOCAL_QWEN3,
    WORKER_TURN_ROUTE_LOCAL_QWEN_CODER,
    WORKER_TURN_ROUTE_LOCAL_DEEPSEEK_R1,
}
WORKER_TURN_COMPLEX_SCOPE_TOKENS = (
    "audit",
    "contradiction",
    "merge",
    "fan_in",
    "fan-in",
    "conflict",
    "architecture",
    "plan_review",
    "supervisor",
    "readback",
    "frontier",
    "synthesis",
)
STRUCTURAL_BLOCKER_REPAIR_ROUTE_KEY = "structural_blocker_repair"
WORKER_TURN_BRAIN_ROUTE_KEYS = frozenset(
    {
        "fan_in_synthesis",
        "conflict_audit",
        "merge_candidate",
        "readback_draft",
        "next_frontier_proposal",
        "codex_brain_decision",
        "complex_audit_contradiction_key_plan_review",
        STRUCTURAL_BLOCKER_REPAIR_ROUTE_KEY,
    }
)
ASSIGNMENT_CONTROL_PLANE_REPAIR_TOKENS = (
    "heartbeat",
    "control_plane",
    "liveness",
    "watch",
    "result_wait",
    "readback",
    "blocker",
    "repair",
)
WORKER_TURN_FINAL_ACCEPTANCE_ROUTE_KEYS = frozenset(
    {
        "final_merge_artifact_acceptance",
        "high_risk_patch_or_repo_mutation",
    }
)
CODEX_ACCEPTANCE_UNAVAILABLE_BLOCKERS = (
    "CODEX_USAGE_LIMIT_RETRY_AFTER",
    "CODEX_ACTIVATOR_EXEC_TIMEOUT",
    "CODEX_USAGE_LIMIT",
    "USAGE LIMIT",
)
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
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH = (
    "seed-cortex-source-family-phase5-post-closure-flush-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH = (
    "seed-cortex-source-family-phase5-final-readmodel-flush-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE = (
    "seed-cortex-source-family-adapter-smoke-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND = (
    "seed-cortex-source-family-smoked-candidate-thin-bind-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL = (
    "seed-cortex-source-family-adapter-value-eval-v1"
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
TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW = (
    "seed-cortex-default-loop-continue-as-new-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_NEXT_FRONTIER_CONTINUATION_SUPERVISOR = (
    "seed-cortex-next-frontier-continuation-supervisor-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR = (
    "seed-cortex-task-control-preemptive-executor-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER = (
    "seed-cortex-task-contract-router-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_POST_CONTINUE_STATUS_REFRESH = (
    "seed-cortex-post-continue-status-refresh-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_V4PRO_SUPERVISOR_ORCHESTRATOR = (
    "seed-cortex-v4pro-supervisor-orchestrator-v1"
)
TEMPORAL_PATCH_SEED_CORTEX_ROOT_INTENT_LOOP_DRIVER_EVERY_WAVE = (
    "seed-cortex-root-intent-loop-driver-every-wave-v1"
)
DEFAULT_LOOP_CONTINUE_AS_NEW_MAX_WAVES_PER_RUN = 4
DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_LENGTH_LIMIT = 9000
DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_SIZE_BYTES_LIMIT = 8_000_000
DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_BUDGET_RATIO = 0.70
TEMPORAL_HISTORY_WARNING_EVENT_COUNT = 10_240
TEMPORAL_HISTORY_WARNING_SIZE_BYTES = 10_000_000
SEED_CORTEX_RUNTIME_ROOT = pathlib.Path(r"D:\XINAO_RESEARCH_RUNTIME")
SEED_CORTEX_ROUTE_PROFILE = "seed_cortex_phase0"
SEED_CORTEX_WORK_ID = "xinao_seed_cortex_phase0_20260701"
ASSIGNMENT_DAG_WORKERPOOL_MIN_TIMEOUT_SECONDS = 1800


def temporal_patch_marker_policy() -> dict[str, Any]:
    return {
        "new_history_continuation_lane": CONTINUATION_AUTHORIZATION_LANE,
        "old_replay_mainchain_authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "patch_markers": {
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
            "seed_cortex_source_family_phase5_post_closure_flush": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH
            ),
            "seed_cortex_source_family_phase5_final_readmodel_flush": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH
            ),
            "seed_cortex_source_family_adapter_smoke": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE
            ),
            "seed_cortex_source_family_smoked_candidate_thin_bind": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND
            ),
            "seed_cortex_source_family_adapter_value_eval": (
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL
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
            "seed_cortex_default_loop_continue_as_new": (
                TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW
            ),
            "seed_cortex_next_frontier_continuation_supervisor": (
                TEMPORAL_PATCH_SEED_CORTEX_NEXT_FRONTIER_CONTINUATION_SUPERVISOR
            ),
            "seed_cortex_task_control_preemptive_executor": (
                TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR
            ),
            "seed_cortex_task_contract_router": (
                TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER
            ),
            "seed_cortex_post_continue_status_refresh": (
                TEMPORAL_PATCH_SEED_CORTEX_POST_CONTINUE_STATUS_REFRESH
            ),
            "seed_cortex_v4pro_supervisor_orchestrator": (
                TEMPORAL_PATCH_SEED_CORTEX_V4PRO_SUPERVISOR_ORCHESTRATOR
            ),
            "seed_cortex_root_intent_loop_driver_every_wave": (
                TEMPORAL_PATCH_SEED_CORTEX_ROOT_INTENT_LOOP_DRIVER_EVERY_WAVE
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


def should_flush_phase5_next_frontier_after_workerpool_closure(
    source_family_phase5_sunset: dict[str, Any],
    source_frontier_workerpool_closure_result: dict[str, Any],
) -> bool:
    if not isinstance(source_family_phase5_sunset, dict) or not source_family_phase5_sunset:
        return False
    if (
        source_family_phase5_sunset.get("activity")
        != "source_family_mature_thin_bind_sunset"
    ):
        return False
    if source_family_phase5_sunset.get("sunset_validation_passed") is not True:
        return False
    if (
        not isinstance(source_frontier_workerpool_closure_result, dict)
        or not source_frontier_workerpool_closure_result
    ):
        return False
    return (
        source_frontier_workerpool_closure_result.get("activity")
        == "source_frontier_workerpool_closure"
        and source_frontier_workerpool_closure_result.get("closure_validation_passed")
        is True
    )


def should_attempt_final_phase5_readmodel_flush(
    source_family_phase5_sunset: dict[str, Any],
    source_frontier_workerpool_closure_result: dict[str, Any],
) -> bool:
    if not isinstance(source_family_phase5_sunset, dict) or not source_family_phase5_sunset:
        return False
    if (
        source_family_phase5_sunset.get("activity")
        != "source_family_mature_thin_bind_sunset"
    ):
        return False
    if (
        not isinstance(source_frontier_workerpool_closure_result, dict)
        or not source_frontier_workerpool_closure_result
    ):
        return False
    return (
        source_frontier_workerpool_closure_result.get("activity")
        == "source_frontier_workerpool_closure"
        and source_frontier_workerpool_closure_result.get("closure_validation_passed")
        is True
    )


def should_invoke_source_family_adapter_smoke(
    source_family_phase5_sunset: dict[str, Any],
) -> bool:
    if not isinstance(source_family_phase5_sunset, dict) or not source_family_phase5_sunset:
        return False
    return (
        source_family_phase5_sunset.get("activity")
        == "source_family_mature_thin_bind_sunset"
        and source_family_phase5_sunset.get("sunset_validation_passed") is True
        and int(source_family_phase5_sunset.get("candidate_adapter_smoke_count") or 0) > 0
    )


def should_invoke_source_family_smoked_candidate_thin_bind(
    source_family_adapter_smoke_result: dict[str, Any],
) -> bool:
    if (
        not isinstance(source_family_adapter_smoke_result, dict)
        or not source_family_adapter_smoke_result
    ):
        return False
    return (
        source_family_adapter_smoke_result.get("activity")
        == "source_family_adapter_smoke"
        and source_family_adapter_smoke_result.get("adapter_smoke_validation_passed")
        is True
        and int(source_family_adapter_smoke_result.get("passed_candidate_count") or 0) > 0
    )


def should_invoke_source_family_adapter_value_eval(
    source_family_smoked_candidate_thin_bind_result: dict[str, Any],
) -> bool:
    if (
        not isinstance(source_family_smoked_candidate_thin_bind_result, dict)
        or not source_family_smoked_candidate_thin_bind_result
    ):
        return False
    return (
        source_family_smoked_candidate_thin_bind_result.get("activity")
        == "source_family_smoked_candidate_thin_bind"
        and source_family_smoked_candidate_thin_bind_result.get(
            "thin_bind_validation_passed"
        )
        is True
        and int(source_family_smoked_candidate_thin_bind_result.get("ready_binding_count") or 0) > 0
    )


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


def _payload_string_fields_for_task_match(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "task_contract_id",
        "phase_scope",
        "assignment_dag_node_id",
        "dag_next_ready_node_id",
        "source_kind",
        "user_goal",
    ):
        value = payload.get(key)
        if value is not None:
            values.append(str(value))
    for section_key in (
        "mature_bind_task",
        "next_mature_bind_task",
        "delivery_contract",
        "work_package",
        "phase_execution",
    ):
        section = payload.get(section_key)
        if isinstance(section, dict):
            for nested_key in (
                "task_id",
                "delivery_id",
                "phase_scope",
                "next_ready_node_id",
                "objective",
            ):
                value = section.get(nested_key)
                if value is not None:
                    values.append(str(value))
    task_package = payload.get("task_package")
    if isinstance(task_package, dict):
        next_task = task_package.get("next_mature_bind_task")
        if isinstance(next_task, dict):
            for nested_key in ("task_id", "delivery_id", "objective", "next_ready_node_id"):
                value = next_task.get(nested_key)
                if value is not None:
                    values.append(str(value))
    return values


def payload_targets_p0_007_default_main_loop_trigger(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(
        P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID in value
        for value in _payload_string_fields_for_task_match(payload)
    )


def payload_targets_p0_008_worker_dispatch_real_receipt(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(
        P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID in value
        for value in _payload_string_fields_for_task_match(payload)
    )


def explicit_contract_requires_default_main_loop_tick(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("force_default_main_loop_tick") is True
        or payload.get("default_main_loop_trigger_bind_required") is True
        or payload.get("current_worker_brief_queue_required") is True
        or payload_targets_p0_007_default_main_loop_trigger(payload)
        or payload_targets_p0_008_worker_dispatch_real_receipt(payload)
    )


def explicit_contract_requires_worker_brief_real_receipts(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        payload.get("worker_dispatch_real_receipt_required") is True
        or payload.get("worker_brief_real_receipt_required") is True
        or payload_targets_p0_008_worker_dispatch_real_receipt(payload)
    )


def current_worker_brief_queue_main_tick_binding(
    runtime_root: pathlib.Path,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    queue_path = runtime_root / "state" / "worker_brief_queue" / "latest.json"
    payload = read_json(queue_path, {})
    briefs = payload.get("briefs") if isinstance(payload.get("briefs"), list) else []
    input_workflow_id = str(input_payload.get("workflow_id") or "")
    input_workflow_run_id = str(
        input_payload.get("workflow_run_id") or input_payload.get("run_id") or ""
    )
    queue_workflow_id = str(payload.get("workflow_id") or "")
    queue_workflow_run_id = str(payload.get("workflow_run_id") or "")
    workflow_id_matches = bool(
        input_workflow_id and queue_workflow_id and input_workflow_id == queue_workflow_id
    )
    workflow_run_id_matches = bool(
        input_workflow_run_id
        and queue_workflow_run_id
        and input_workflow_run_id == queue_workflow_run_id
    )
    workflow_run_id_rollover_allowed_by_continue_as_new = bool(
        workflow_id_matches
        and input_workflow_run_id
        and queue_workflow_run_id
        and input_workflow_run_id != queue_workflow_run_id
    )
    bound_to_input_workflow = (
        workflow_id_matches
        and (
            workflow_run_id_matches
            or workflow_run_id_rollover_allowed_by_continue_as_new
        )
        if input_workflow_id or input_workflow_run_id
        else bool(queue_workflow_id and queue_workflow_run_id)
    )
    ready = (
        queue_path.is_file()
        and payload.get("schema_version") == "xinao.codex_s.worker_brief_queue.v1"
        and payload.get("status") == "worker_brief_queue_ready"
        and payload.get("source_package_id") == CURRENT_P0_THREE_TEXT_SOURCE_PACKAGE_ID
        and int(payload.get("brief_count") or 0) >= 3
        and payload.get("dispatch_ready") is True
        and payload.get("next_frontier_default_outlet") is False
    )
    return {
        "schema_version": "xinao.codex_s.current_worker_brief_queue_main_tick_binding.v1",
        "queue_ref": str(queue_path),
        "queue_exists": queue_path.is_file(),
        "queue_status": str(payload.get("status") or ""),
        "source_package_id": str(payload.get("source_package_id") or ""),
        "brief_count": int(payload.get("brief_count") or len(briefs) or 0),
        "dispatch_ready": payload.get("dispatch_ready") is True,
        "next_frontier_default_outlet": payload.get("next_frontier_default_outlet"),
        "workflow_id": queue_workflow_id,
        "workflow_run_id": queue_workflow_run_id,
        "input_workflow_id": input_workflow_id,
        "input_workflow_run_id": input_workflow_run_id,
        "workflow_id_matches": workflow_id_matches,
        "workflow_run_id_matches": workflow_run_id_matches,
        "workflow_run_id_rollover_allowed_by_continue_as_new": (
            workflow_run_id_rollover_allowed_by_continue_as_new
        ),
        "workflow_chain_scoped_binding": workflow_id_matches
        and (
            workflow_run_id_matches
            or workflow_run_id_rollover_allowed_by_continue_as_new
        ),
        "bound_to_input_workflow": bound_to_input_workflow,
        "brief_ids": [
            str(item.get("brief_id") or item.get("worker_brief_id") or "")
            for item in briefs
            if isinstance(item, dict)
        ],
        "consumed_by_temporal_main_tick": ready and bound_to_input_workflow,
        "ready": ready,
        "completion_claim_allowed": False,
        "not_execution_controller": True,
    }


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
        },
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


def seed_cortex_mainline_start_guard(
    input_payload: dict[str, Any],
    *,
    task_queue: str,
) -> dict[str, Any]:
    """Resolve S default mainline starts without spawning ad-hoc workflow IDs."""
    requested_workflow_id = str(input_payload.get("workflow_id") or "").strip()
    if not is_seed_cortex_s_payload(input_payload):
        return {
            "action": "start",
            "workflow_id": requested_workflow_id
            or f"xinao-codex-task-{input_payload['task_id']}-{run_id()}",
            "seed_cortex_mainline_guard": False,
        }

    list_status = codex_333_run_reconciler.list_running_workflows(
        temporal_address=TEMPORAL_ADDRESS
    )
    classified = [
        codex_333_run_reconciler.workflow_role(
            item,
            task_queue=str(task_queue),
            workflow_type=codex_333_run_reconciler.DEFAULT_WORKFLOW_TYPE,
        )
        for item in list_status.get("workflows", [])
    ]
    running = [item for item in classified if "RUNNING" in str(item.get("status", "")).upper()]
    candidates = [item for item in running if item.get("eligible_mainline") is True]
    exact_matches = [
        item
        for item in running
        if requested_workflow_id and item.get("workflow_id") == requested_workflow_id
    ]
    guard_base = {
        "seed_cortex_mainline_guard": True,
        "workflow_id_conflict_policy": "UseExisting_or_Fail",
        "running_workflow_count": len(running),
        "mainline_candidate_count": len(candidates),
        "requested_workflow_id": requested_workflow_id,
        "list_status": list_status.get("status"),
        "list_error": list_status.get("error", ""),
    }
    if int(list_status.get("returncode") or 0) != 0 and list_status.get("source") != "override":
        return {
            **guard_base,
            "action": "blocked",
            "workflow_id": requested_workflow_id,
            "named_blocker": "TEMPORAL_WORKFLOW_LIST_UNAVAILABLE",
            "completion_claim_allowed": False,
        }
    if exact_matches:
        selected = exact_matches[0]
        return {
            **guard_base,
            "action": "attach_existing",
            "workflow_id": str(selected.get("workflow_id") or ""),
            "workflow_run_id": str(selected.get("run_id") or ""),
            "selected_workflow": selected,
            "attach_reason": "requested_workflow_id_already_running",
        }
    if requested_workflow_id and candidates:
        return {
            **guard_base,
            "action": "blocked",
            "workflow_id": requested_workflow_id,
            "named_blocker": "ACTIVE_333_MAINLINE_EXISTS_USE_EXISTING",
            "selected_workflow": candidates[0] if len(candidates) == 1 else {},
            "completion_claim_allowed": False,
        }
    if not requested_workflow_id and len(candidates) == 1:
        selected = candidates[0]
        return {
            **guard_base,
            "action": "attach_existing",
            "workflow_id": str(selected.get("workflow_id") or ""),
            "workflow_run_id": str(selected.get("run_id") or ""),
            "selected_workflow": selected,
            "attach_reason": "unique_running_mainline_candidate",
        }
    if len(candidates) > 1:
        return {
            **guard_base,
            "action": "blocked",
            "workflow_id": requested_workflow_id,
            "named_blocker": "AMBIGUOUS_ACTIVE_333_MAINLINE",
            "mainline_candidates": candidates,
            "completion_claim_allowed": False,
        }
    return {
        **guard_base,
        "action": "start",
        "workflow_id": requested_workflow_id or DEFAULT_CANONICAL_MAINLINE_WORKFLOW_ID,
        "start_reason": "no_running_mainline_candidate_stable_default_id",
    }


def attached_existing_workflow_result(
    input_payload: dict[str, Any],
    *,
    runtime_root: pathlib.Path,
    task_queue: str,
    workflow_id: str,
    workflow_run_id: str,
    guard: dict[str, Any],
) -> dict[str, Any]:
    verification_summary: dict[str, Any] = {}
    verification_level = VERIFICATION_LEVEL_READ_MODEL
    workflow_open = False
    try:
        verification_summary, verification_level = _verify_temporal_workflow_history(
            runtime_root=runtime_root,
            task_id=input_payload["task_id"],
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
        )
        verification_level = normalize_verification_level(verification_level)
        workflow_open = bool(verification_summary.get("workflow_open"))
    except Exception:
        verification_summary = {"verify_exception": "temporal_workflow_verification_failed"}
    return {
        "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
        "generated_at": now(),
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "task_queue": task_queue,
        "active_object_id": ACTIVE_OBJECT_ID,
        "task_id": input_payload["task_id"],
        "temporal_workflow_completed": False,
        "temporal_live_route": True,
        "server_bound": True,
        "workflow_open": workflow_open,
        "workflow_completed_partial": workflow_open,
        "verification_level": verification_level,
        "partial_frontier_open": workflow_open,
        "workflow_internal_timer_scheduled": False,
        "workflow_kept_open_by_durable_timer": False,
        "mainline_next_hop": "attach_existing_333_mainline_poll" if workflow_open else "",
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "workflow_completed_is_not_user_complete": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "canonical_completion_source": "/completion/claim",
        "execution_mode": "temporal_server",
        "local_run_observed": False,
        "attached_existing_workflow": True,
        "start_workflow_called": False,
        "mainline_start_guard": guard,
        "workflow_id_conflict_policy": "UseExisting_or_Fail",
        "completion_decision": {
            "status": "partial",
            "stop_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
        },
        "user_task_complete": False,
        "g2_temporal_server_verification_ref": str(verification_summary.get("summary_ref") or ""),
        "temporal_history_verification": verification_summary,
        "activities": [],
        "current_task_owner": current_task_owner_from_input(
            {
                **input_payload,
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
                "task_queue": task_queue,
            },
            live_temporal=True,
        ),
        "worker_service_polling": True,
        "retry_policy": retry_policy_dict(),
        "non_retryable_policy_denials": list(NON_RETRYABLE_ERROR_TYPES),
        "transient_retryable_errors": list(TRANSIENT_ERROR_TYPES),
    }


def blocked_mainline_start_result(
    input_payload: dict[str, Any],
    *,
    task_queue: str,
    guard: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "xinao.temporal_codex_task_workflow.result.v1",
        "generated_at": now(),
        "workflow_id": str(guard.get("workflow_id") or input_payload.get("workflow_id") or ""),
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
        "mainline_next_hop": "use_existing_333_mainline_or_reconcile_ambiguity",
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "workflow_completed_is_not_user_complete": True,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "canonical_completion_source": "/completion/claim",
        "execution_mode": "temporal_server",
        "local_run_observed": False,
        "attached_existing_workflow": False,
        "start_workflow_called": False,
        "mainline_start_guard": guard,
        "workflow_id_conflict_policy": "UseExisting_or_Fail",
        "completion_decision": {
            "status": "blocked",
            "stop_allowed": False,
            "named_blocker": guard.get("named_blocker") or "MAINLINE_START_GUARD_BLOCKED",
            "not_source_of_truth": True,
            "not_user_completion": True,
        },
        "named_blocker": guard.get("named_blocker") or "MAINLINE_START_GUARD_BLOCKED",
        "user_task_complete": False,
        "activities": [],
        "current_task_owner": current_task_owner_from_input(input_payload, live_temporal=True),
        "retry_policy": retry_policy_dict(),
        "non_retryable_policy_denials": list(NON_RETRYABLE_ERROR_TYPES),
        "transient_retryable_errors": list(TRANSIENT_ERROR_TYPES),
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
            "ProviderRouter-selected worker when execute_worker_turn is enabled; execute_codex_worker is legacy alias",
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


def is_current_p0_three_text_source_ref(path: pathlib.Path, anchor_package_root: pathlib.Path) -> bool:
    try:
        return (
            path.resolve().parent == anchor_package_root.resolve()
            and path.name in CURRENT_P0_THREE_TEXT_FILENAMES
        )
    except OSError:
        return False


def file_source_ref(
    path: pathlib.Path,
    *,
    current_authority: bool = False,
    authority_package_id: str = "",
) -> dict[str, Any]:
    data = path.read_bytes()
    stat = path.stat()
    ref = {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    if current_authority:
        ref.update(
            {
                "role": "current_p0_task_package_authority",
                "source_text_authority": True,
                "semantic_input_role": "current_authority_source",
                "source_package_id": authority_package_id or CURRENT_P0_THREE_TEXT_SOURCE_PACKAGE_ID,
                "default_hot_path": True,
            }
        )
    else:
        ref.update(
            {
                "role": "non_authoritative_semantic_input",
                "source_text_authority": False,
                "semantic_input_role": "non_authoritative_reference",
            }
        )
    return ref


def read_compiled_task_object(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("compiled TaskObject JSON must be an object")
    return payload


def read_work_package(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("work_package JSON must be an object")
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
        if key == "tool_bearing_patch_executor":
            return {
                "status": compact_history_scalar(value.get("status", "")),
                "named_blocker": compact_history_scalar(value.get("named_blocker", "")),
                "repo_mutation_performed": value.get("repo_mutation_performed") is True,
                "record_path": compact_history_scalar(value.get("record_path", "")),
                "latest_path": compact_history_scalar(value.get("latest_path", "")),
                "diff_path": compact_history_scalar(value.get("diff_path", "")),
                "touched_paths": compact_history_value("touched_paths", value.get("touched_paths", [])),
            }
        if key in {"task_contract", "delivery_contract", "workflow_switches"}:
            return {
                str(k): compact_history_value(str(k), v)
                for k, v in value.items()
                if isinstance(v, (str, int, float, bool)) or str(k).endswith(("_id", "_path", "_ref"))
            }
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
        "worker_brief_id",
        "worker_brief_queue_id",
        "worker_brief_index",
        "source_package_id",
        "source_ledger_entry_id",
        "source_ref",
        "source_sha256",
        "source_role",
        "worker_dispatch_receipt_id",
        "worker_dispatch_real_receipt_required",
        "worker_brief_real_receipt_required",
        "provider_candidates",
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
        "execute_worker_turn",
        "execute_codex_worker_legacy_alias",
        "legacy_execute_codex_worker_alias_consumed",
        "switch_rename",
        "selected_provider_id",
        "actual_provider_id",
        "actual_provider_family",
        "actual_carrier_provider_id",
        "provider_router_active",
        "provider_route_reason",
        "codex_worker_turn_carrier_only",
        "codex_exec_deferred",
        "codex_final_deferred",
        "codex_substituted_by",
        "tool_bearing_patch_executor_enabled",
        "tool_bearing_patch_executor",
        "repo_mutation_performed",
        "patch_executor_record_ref",
        "patch_executor_latest_ref",
        "repo_root",
        "workspace_hint",
        "contract_id",
        "explicit_execution_task",
        "task_contract",
        "delivery_contract",
        "workflow_switches",
        "record_path",
        "latest_path",
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


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _workflow_info_metric(workflow_info: Any, method_name: str, attr_name: str) -> int:
    method = getattr(workflow_info, method_name, None)
    if callable(method):
        try:
            return int(method() or 0)
        except Exception:
            return 0
    try:
        return int(getattr(workflow_info, attr_name, 0) or 0)
    except (TypeError, ValueError):
        return 0


def default_loop_history_metrics(workflow_info: Any) -> dict[str, Any]:
    suggested = False
    method = getattr(workflow_info, "is_continue_as_new_suggested", None)
    if callable(method):
        try:
            suggested = bool(method())
        except Exception:
            suggested = False
    return {
        "history_length": _workflow_info_metric(
            workflow_info,
            "get_current_history_length",
            "current_history_length",
        ),
        "history_size_bytes": _workflow_info_metric(
            workflow_info,
            "get_current_history_size",
            "current_history_size",
        ),
        "is_continue_as_new_suggested": suggested,
    }


def default_loop_rollover_decision(
    input_payload: dict[str, Any],
    workflow_info: Any,
    *,
    waves_completed_in_run: int,
    pending_signal_count: int,
    patch_enabled: bool = True,
) -> dict[str, Any]:
    enabled = (
        patch_enabled
        and input_payload.get("default_loop_continue_as_new", True) is not False
        and pending_signal_count > 0
    )
    max_waves = _bounded_int(
        input_payload.get("default_loop_max_waves_per_run")
        or input_payload.get("max_continue_same_task_waves_per_run"),
        DEFAULT_LOOP_CONTINUE_AS_NEW_MAX_WAVES_PER_RUN,
        minimum=1,
        maximum=20,
    )
    history_length_limit = _bounded_int(
        input_payload.get("default_loop_history_length_limit"),
        DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_LENGTH_LIMIT,
        minimum=1000,
        maximum=50000,
    )
    history_size_limit = _bounded_int(
        input_payload.get("default_loop_history_size_bytes_limit"),
        DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_SIZE_BYTES_LIMIT,
        minimum=1_000_000,
        maximum=49_000_000,
    )
    metrics = default_loop_history_metrics(workflow_info)
    event_budget_used = (
        metrics["history_length"] / TEMPORAL_HISTORY_WARNING_EVENT_COUNT
        if metrics["history_length"]
        else 0.0
    )
    size_budget_used = (
        metrics["history_size_bytes"] / TEMPORAL_HISTORY_WARNING_SIZE_BYTES
        if metrics["history_size_bytes"]
        else 0.0
    )
    estimated_budget_used = max(event_budget_used, size_budget_used)
    try:
        budget_ratio = float(
            input_payload.get("default_loop_history_budget_ratio")
            or DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_BUDGET_RATIO
        )
    except (TypeError, ValueError):
        budget_ratio = DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_BUDGET_RATIO
    budget_ratio = max(0.10, min(0.95, budget_ratio))
    reasons: list[str] = []
    if metrics["is_continue_as_new_suggested"]:
        reasons.append("temporal_is_continue_as_new_suggested")
    if estimated_budget_used >= budget_ratio:
        reasons.append("estimated_history_budget_used")
    if metrics["history_length"] and metrics["history_length"] >= history_length_limit:
        reasons.append("history_length_limit")
    if metrics["history_size_bytes"] and metrics["history_size_bytes"] >= history_size_limit:
        reasons.append("history_size_bytes_limit")
    if waves_completed_in_run >= max_waves:
        reasons.append("max_waves_per_run_fuse")
    return {
        "policy": "default_loop_history_budget_rollover",
        "enabled": enabled,
        "should_continue_as_new": bool(enabled and reasons),
        "reasons": reasons,
        "waves_completed_in_run": waves_completed_in_run,
        "pending_signal_count": pending_signal_count,
        "max_waves_per_run": max_waves,
        "max_waves_per_run_is_hard_fuse": True,
        "history_length_limit": history_length_limit,
        "history_size_bytes_limit": history_size_limit,
        "history_budget_ratio": budget_ratio,
        "estimated_history_budget_used": round(estimated_budget_used, 4),
        "event_history_budget_used": round(event_budget_used, 4),
        "size_history_budget_used": round(size_budget_used, 4),
        **metrics,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
    }


def compact_continue_signal_for_rollover(signal_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(signal_payload, dict):
        return {}
    compact: dict[str, Any] = {}
    keep_keys = {
        "source_kind",
        "assignment_dag_source_kind",
        "assignment_dag_node_id",
        "dag_next_ready_node_id",
        "wave_id",
        "temporal_hot_path_wave_index",
        "runtime_root",
        "repo_root",
        "workspace_hint",
        "worker_kind",
        "phase_scope",
        "worker_assignment_ref",
        "provider_routing_mode",
        "provider_cost_routing_policy_ref",
        "default_token_saving_worker_route",
        "codex_worker_task_id",
        "codex_worker_expected_marker",
        "codex_worker_timeout_sec",
        "implementation_worker_timeout_sec",
        "generated_at",
        "signal_id",
        "source_goal_ref",
        "followup_after_this",
        "completion_claim_allowed",
        "not_user_completion",
    }
    for key, value in signal_payload.items():
        if (
            key in keep_keys
            or key.endswith(("_id", "_ref", "_path", "_index", "_count"))
        ):
            compact_value = compact_history_value(key, value)
            if compact_value not in (None, {}, []):
                compact[key] = compact_value
    for key in ("work_package", "verification"):
        value = signal_payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = _compact_continue_payload_value(key, value)
    phase_execution = (
        signal_payload.get("phase_execution")
        if isinstance(signal_payload.get("phase_execution"), dict)
        else {}
    )
    if phase_execution:
        compact_phase: dict[str, Any] = {}
        for key in (
            "worker_kind",
            "phase_scope",
            "repo_root",
            "provider_routing_mode",
            "provider_cost_routing_policy_ref",
            "default_token_saving_worker_route",
            "timeout_sec",
        ):
            if key in phase_execution:
                compact_phase[key] = _compact_continue_payload_value(
                    key,
                    phase_execution[key],
                )
        for key in ("work_package", "verification"):
            value = phase_execution.get(key)
            if value not in (None, "", [], {}):
                compact_phase[key] = _compact_continue_payload_value(key, value)
        if compact_phase:
            compact["phase_execution"] = compact_phase
    return compact


def _compact_continue_payload_value(key: str, value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return compact_history_scalar(value)
    if isinstance(value, list):
        compact_list = []
        for item in value[:20]:
            compact_item = _compact_continue_payload_value(key, item)
            if compact_item not in (None, {}, []):
                compact_list.append(compact_item)
        return compact_list
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for item_key, item_value in value.items():
            if str(item_key) in {
                "objective",
                "next_ready_node_id",
                "files",
                "acceptance",
                "worker_kind",
                "phase_scope",
                "repo_root",
                "provider_routing_mode",
                "provider_cost_routing_policy_ref",
                "default_token_saving_worker_route",
                "timeout_sec",
                "work_items",
            } or str(item_key).endswith(("_id", "_ref", "_path", "_count")):
                compact_value = _compact_continue_payload_value(str(item_key), item_value)
                if compact_value not in (None, {}, []):
                    compact[str(item_key)] = compact_value
        return compact
    return None


def compact_payload_for_default_loop_continue_as_new(
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    blocked_keys = {
        "activities",
        "graph_result",
        "segment_pass_next_worker",
        "jobs_json_observe",
        "jobs_json_observe_backend_readback",
        "task_bound_worker_command_executions",
        "current_task_owner",
        "default_loop_continue_as_new_resume_state",
    }
    compact: dict[str, Any] = {}
    for key, value in input_payload.items():
        if key in blocked_keys or key.endswith("_activity"):
            continue
        if key in {
            "user_goal",
            "source_refs",
            "compiled_task_object",
            "task_object",
            "acceptance_contract",
            "work_package",
            "verification",
            "runtime_subject_loop_required",
            "root_repair_constraints",
            "mature_execution_carrier_refs",
        }:
            compact_value = _compact_continue_payload_value(key, value)
        else:
            compact_value = compact_history_value(key, value)
        if compact_value not in (None, {}, []):
            compact[key] = compact_value
    return compact


def build_default_loop_continue_as_new_payload(
    input_payload: dict[str, Any],
    *,
    pending_signals: list[dict[str, Any]],
    rollover_decision: dict[str, Any],
    last_result: dict[str, Any],
    initial_worker_task_id: str,
) -> dict[str, Any]:
    base_payload = compact_payload_for_default_loop_continue_as_new(input_payload)
    generation = _bounded_int(
        input_payload.get("default_loop_continue_generation"),
        0,
        minimum=0,
        maximum=100000,
    )
    pending = [
        compact_continue_signal_for_rollover(item)
        for item in pending_signals
        if isinstance(item, dict) and item
    ]
    result_refs = {
        "workflow_result_ref": str(last_result.get("workflow_result_ref") or ""),
        "task_workflow_result_ref": str(last_result.get("task_workflow_result_ref") or ""),
        "task_latest_ref": str(last_result.get("task_latest_ref") or ""),
        "worker_dispatch_ledger_latest_ref": str(
            last_result.get("worker_dispatch_ledger_latest_ref") or ""
        ),
        "main_execution_loop_tick_latest_ref": str(
            last_result.get("main_execution_loop_tick_latest_ref") or ""
        ),
        "ledger_auto_dispatch_ingress_latest_ref": str(
            last_result.get("ledger_auto_dispatch_ingress_latest_ref") or ""
        ),
    }
    base_payload.update(
        {
            "default_loop_continue_generation": generation + 1,
            "default_loop_previous_run_id": str(input_payload.get("workflow_run_id") or ""),
            "default_loop_continue_as_new": True,
            "default_loop_waves_completed_in_run": 0,
            "default_loop_continue_as_new_resume_state": {
                "schema_version": "xinao.temporal_codex_task_workflow.default_loop_resume_state.v1",
                "generation": generation + 1,
                "previous_run_id": str(input_payload.get("workflow_run_id") or ""),
                "pending_continue_same_task_signals": pending,
                "pending_continue_same_task_signal_count": len(pending),
                "rollover_decision": dict(rollover_decision),
                "completion_decision": (
                    dict(last_result.get("completion_decision"))
                    if isinstance(last_result.get("completion_decision"), dict)
                    else {}
                ),
                "result_refs": {
                    key: value for key, value in result_refs.items() if value
                },
                "initial_worker_task_id": initial_worker_task_id,
                "completion_claim_allowed": False,
                "not_user_completion": True,
                "not_execution_controller": True,
            },
        }
    )
    if initial_worker_task_id:
        base_payload["codex_worker_task_id"] = initial_worker_task_id
        base_payload["default_loop_reuse_initial_worker_result"] = True
    return base_payload


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


def _temporal_event_type(event: dict[str, Any]) -> str:
    return str(event.get("eventType") or event.get("event_type", ""))


def _temporal_event_type_matches(event: dict[str, Any], suffix: str) -> bool:
    event_type = _temporal_event_type(event)
    if event_type.endswith(suffix):
        return True
    normalized_event_type = event_type.lower().removeprefix("event_type_").replace("_", "")
    normalized_suffix = suffix.lower().replace("_", "")
    return normalized_event_type.endswith(normalized_suffix)


def _derive_workflow_open_from_events(events: list[dict[str, Any]], status: str) -> bool:
    return status in {
        "RUNNING",
        "running",
        "WorkflowExecutionStatus_RUNNING",
        "WORKFLOW_EXECUTION_STATUS_RUNNING",
        "workflowexecutionstatusrunning",
    } or any(
        _temporal_event_type_matches(event, "WorkflowExecutionStarted")
        for event in events
    ) and not any(
        _temporal_event_type_matches(event, term)
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
    if not status:
        status = _extract_workflow_status(describe_payload).strip()
    workflow_open = _derive_workflow_open_from_events(events, status)
    workflow_completed = any(
        _temporal_event_type_matches(event, term)
        for event in events
        for term in ("WorkflowExecutionCompleted", "WorkflowExecutionFailed", "WorkflowExecutionTerminated", "WorkflowExecutionTimedOut")
    )
    started_seen = any(
        _temporal_event_type_matches(event, "WorkflowExecutionStarted")
        for event in events
    )
    activity_scheduled_count = sum(
        1 for event in events
        if _temporal_event_type_matches(event, "ActivityTaskScheduled")
    )
    activity_started_count = sum(
        1 for event in events
        if _temporal_event_type_matches(event, "ActivityTaskStarted")
    )
    activity_completed_count = sum(
        1 for event in events
        if _temporal_event_type_matches(event, "ActivityTaskCompleted")
    )
    timer_started_seen = any(
        _temporal_event_type_matches(event, "TimerStarted")
        for event in events
    )
    terminal_event_seen = any(
        _temporal_event_type_matches(event, term)
        for event in events
        for term in ("WorkflowExecutionCompleted", "WorkflowExecutionFailed", "WorkflowExecutionTimedOut", "WorkflowExecutionTerminated", "WorkflowExecutionCanceled", "WorkflowExecutionContinuedAsNew")
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


def codex_acceptance_unavailable(runtime_root: pathlib.Path) -> bool:
    policy = codex_native_provider_scheduler_phase4.load_provider_cost_routing_policy(runtime_root)
    credit = (
        policy.get("codex_credit_pressure")
        if isinstance(policy.get("codex_credit_pressure"), dict)
        else {}
    )
    if credit.get("active") is True:
        return True
    return (
        codex_native_provider_scheduler_phase4.detect_codex_credit_pressure(runtime_root).get("active")
        is True
    )


def codex_acceptance_blocked(worker: dict[str, Any]) -> bool:
    if worker.get("status") == "activity_gate_checked":
        return False
    blocker = str(worker.get("named_blocker") or "").upper()
    return any(token in blocker for token in CODEX_ACCEPTANCE_UNAVAILABLE_BLOCKERS)


def _worker_turn_scope_needs_v4pro(*, phase_scope: str, prompt: str, route_key: str) -> bool:
    haystack = f"{phase_scope} {prompt} {route_key}".lower()
    return any(token in haystack for token in WORKER_TURN_COMPLEX_SCOPE_TOKENS)


def worker_turn_local_qwen_ready() -> bool:
    try:
        from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4
    except Exception:
        return False
    try:
        return phase4.local_ollama_status(timeout_seconds=2).get("ready") is True
    except Exception:
        return False


def resolve_worker_turn_provider_decision(input_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        decision = codex_native_provider_scheduler_phase4.worker_turn_provider_decision(input_payload)
        if isinstance(decision, dict) and decision.get("provider_id"):
            return decision
    except Exception as exc:
        return {
            "schema_version": "xinao.codex_s.worker_turn_provider_decision.fallback.v1",
            "provider_id": WORKER_TURN_ROUTE_V4PRO,
            "mode": "audit",
            "route_reason": f"provider_scheduler_decision_failed_v4pro_fallback:{exc.__class__.__name__}",
            "selected_local_model": "",
            "mature_router_alignment": {
                "static_order_is_fallback_only": True,
                "local_first_mandatory": False,
            },
            "not_execution_controller": True,
        }
    route_key = str(
        input_payload.get("provider_route_key")
        or input_payload.get("route_key")
        or input_payload.get("route_class")
        or ""
    ).strip()
    worker_kind = str(input_payload.get("worker_kind") or "").strip()
    phase_scope = str(input_payload.get("phase_scope") or "")
    prompt = str(input_payload.get("codex_worker_prompt") or "")
    if (
        input_payload.get("final_acceptance_only") is True
        or input_payload.get("aaq_final_signoff") is True
        or route_key in WORKER_TURN_FINAL_ACCEPTANCE_ROUTE_KEYS
    ):
        return WORKER_TURN_ROUTE_CODEX_FINAL, "", "final_acceptance_codex_short_signoff"
    if worker_kind == "implementation_worker" or input_payload.get("implementation_worker_required") is True:
        if _worker_turn_scope_needs_v4pro(
            phase_scope=phase_scope,
            prompt=prompt,
            route_key=route_key,
        ):
            return {
                "provider_id": WORKER_TURN_ROUTE_V4PRO,
                "mode": "audit",
                "route_reason": "implementation_worker_complex_v4pro",
                "selected_local_model": "",
                "static_order_is_fallback_only": True,
                "not_execution_controller": True,
            }
        if worker_turn_local_qwen_ready():
            return {
                "provider_id": WORKER_TURN_ROUTE_LOCAL_QWEN,
                "mode": "draft",
                "route_reason": "implementation_worker_fallback_local_ollama_qwen",
                "selected_local_model": "",
                "static_order_is_fallback_only": True,
                "not_execution_controller": True,
            }
        return {
            "provider_id": WORKER_TURN_ROUTE_QWEN,
            "mode": "draft",
            "route_reason": "implementation_worker_fallback_qwen",
            "selected_local_model": "",
            "static_order_is_fallback_only": True,
            "not_execution_controller": True,
        }
    if route_key in WORKER_TURN_BRAIN_ROUTE_KEYS or _worker_turn_scope_needs_v4pro(
        phase_scope=phase_scope,
        prompt=prompt,
        route_key=route_key,
    ):
        return {
            "provider_id": WORKER_TURN_ROUTE_V4PRO,
            "mode": "audit",
            "route_reason": "brain_judgment_v4pro",
            "selected_local_model": "",
            "static_order_is_fallback_only": True,
            "not_execution_controller": True,
        }
    return {
        "provider_id": WORKER_TURN_ROUTE_V4PRO,
        "mode": "audit",
        "route_reason": "codex_worker_turn_carrier_v4pro_default",
        "selected_local_model": "",
        "static_order_is_fallback_only": True,
        "not_execution_controller": True,
    }


def resolve_worker_turn_provider(input_payload: dict[str, Any]) -> tuple[str, str, str]:
    decision = resolve_worker_turn_provider_decision(input_payload)
    return (
        str(decision.get("provider_id") or WORKER_TURN_ROUTE_V4PRO),
        str(decision.get("mode") or ""),
        str(decision.get("route_reason") or "worker_turn_provider_router_decision"),
    )


def _provider_payload_from_runner(runner: dict[str, Any]) -> dict[str, Any]:
    payload = runner.get("provider_payload")
    return payload if isinstance(payload, dict) else {}


def _build_routed_worker_turn_activity_result(
    *,
    input_payload: dict[str, Any],
    worker_task_id: str,
    provider_id: str,
    route_reason: str,
    provider_payload: dict[str, Any],
    carrier_runner: dict[str, Any],
    dp_mode: str,
    expected_marker: str,
    codex_final_deferred: bool = False,
) -> dict[str, Any]:
    model_ok = provider_payload.get("model_invocation_performed") is True
    provider_ok = provider_payload.get("provider_invocation_performed") is True
    artifact_ref = str(
        provider_payload.get("result_path")
        or provider_payload.get("artifact_ref")
        or provider_payload.get("provider_invocation_ref")
        or ""
    )
    content = _v4pro_brain_dispatch_model_content(provider_payload)
    marker_seen = expected_marker in content or expected_marker in json.dumps(provider_payload, ensure_ascii=False)
    patch_executor = (
        provider_payload.get("tool_bearing_patch_executor")
        if isinstance(provider_payload.get("tool_bearing_patch_executor"), dict)
        else {}
    )
    patch_executor_enabled = input_payload.get("tool_bearing_patch_executor_enabled") is True
    patch_executor_ok = (
        not patch_executor_enabled
        or patch_executor.get("status") == "applied_verified"
    )
    status = "activity_gate_checked" if model_ok and provider_ok and patch_executor_ok else "activity_blocked"
    blocker = (
        ""
        if status == "activity_gate_checked"
        else str(
            patch_executor.get("named_blocker")
            or provider_payload.get("named_blocker")
            or "WORKER_TURN_PROVIDER_ROUTER_FAILED"
        )
    )
    return compact_activity_for_history(
        {
            "activity": "codex_worker_turn",
            "status": status,
            "command_surface": (
                f"Temporal codex_worker_turn carrier -> provider_router -> {provider_id}"
            ),
            "dispatch_strategy": f"worker_turn_provider_router_{route_reason}",
            "mature_execution_carrier": (
                "local_ollama_qwen_staging_only"
                if provider_id in WORKER_TURN_LOCAL_POOL_ROUTES
                else
                "qwen_prepaid_cheap_worker_gateway"
                if provider_id == WORKER_TURN_ROUTE_QWEN
                else "deepseek_v4_pro_dp_sidecar_staging_only"
                if provider_id == WORKER_TURN_ROUTE_V4PRO
                else MATURE_EXECUTION_CARRIER
            ),
            "worker_evidence_contract": "provider_router_staging_requires_fan_in_acceptance",
            "task_id": input_payload["task_id"],
            "worker_task_id": worker_task_id,
            "task_bound_worker": True,
            "worker_kind": str(input_payload.get("worker_kind") or ""),
            "phase_scope": str(input_payload.get("phase_scope") or ""),
            "worker_brief_id": str(input_payload.get("worker_brief_id") or ""),
            "worker_brief_queue_id": str(input_payload.get("worker_brief_queue_id") or ""),
            "worker_brief_index": input_payload.get("worker_brief_index"),
            "source_package_id": str(input_payload.get("source_package_id") or ""),
            "source_ledger_entry_id": str(input_payload.get("source_ledger_entry_id") or ""),
            "source_ref": str(input_payload.get("source_ref") or ""),
            "source_sha256": str(input_payload.get("source_sha256") or ""),
            "source_role": str(input_payload.get("source_role") or ""),
            "provider_candidates": list(input_payload.get("provider_candidates") or []),
            "worker_dispatch_receipt_id": f"{worker_task_id}:receipt",
            "worker_dispatch_real_receipt_required": (
                input_payload.get("worker_dispatch_real_receipt_required") is True
            ),
            "worker_brief_real_receipt_required": (
                input_payload.get("worker_brief_real_receipt_required") is True
            ),
            **worker_turn_switch_alias_payload(input_payload),
            "selected_provider_id": provider_id,
            "actual_provider_id": provider_id,
            "actual_provider_family": (
                "local_ollama"
                if provider_id in WORKER_TURN_LOCAL_POOL_ROUTES
                else "qwen"
                if provider_id == WORKER_TURN_ROUTE_QWEN
                else "deepseek"
                if provider_id == WORKER_TURN_ROUTE_V4PRO
                else "codex"
            ),
            "actual_carrier_provider_id": str(
                provider_payload.get("selected_carrier_provider_id")
                or provider_payload.get("carrier_provider_id")
                or provider_id
            ),
            "provider_router_active": True,
            "provider_route_reason": route_reason,
            "execution_routing_unchanged": True,
            "codex_worker_turn_carrier_only": True,
            "codex_exec_deferred": provider_id != WORKER_TURN_ROUTE_CODEX_FINAL,
            "codex_final_deferred": codex_final_deferred,
            "codex_substituted_by": provider_id if provider_id != WORKER_TURN_ROUTE_CODEX_FINAL else "",
            "continuation_allowed_without_codex_acceptance": codex_final_deferred,
            "dp_mode": dp_mode,
            "jsonl_exists": False,
            "codex_jsonl_is_execution_evidence": False,
            "tool_bearing_patch_executor_enabled": patch_executor_enabled,
            "tool_bearing_patch_executor": patch_executor,
            "repo_mutation_performed": patch_executor.get("repo_mutation_performed") is True,
            "patch_executor_record_ref": str(patch_executor.get("record_path") or ""),
            "patch_executor_latest_ref": str(patch_executor.get("latest_path") or ""),
            "dp_artifact_exists": bool(artifact_ref),
            "artifact_ref": artifact_ref,
            "provider_invocation_ref": str(provider_payload.get("provider_invocation_ref") or ""),
            "expected_marker": expected_marker,
            "expected_marker_seen": marker_seen,
            "activator_ok": provider_ok and model_ok,
            "named_blocker": blocker,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "authority_boundary": authority_boundary("worker_turn_provider_router_activity_readback"),
            "backend_evidence_refs": {
                "provider_invocation_ref": str(provider_payload.get("provider_invocation_ref") or ""),
                "artifact_ref": artifact_ref,
                "carrier_runner_latest": str(
                    (carrier_runner.get("evidence_refs") or {}).get("latest", "")
                    if isinstance(carrier_runner.get("evidence_refs"), dict)
                    else ""
                ),
            },
            "carrier_runner": carrier_runner,
        }
    )


async def invoke_routed_worker_turn_carrier(
    *,
    runtime_root: pathlib.Path,
    input_payload: dict[str, Any],
    worker_task_id: str,
    worker_prompt: str,
    provider_id: str,
    dp_mode: str,
    route_reason: str,
    expected_marker: str,
    codex_final_deferred: bool = False,
    route_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = str(input_payload["task_id"])
    invocation_id = worker_task_id.replace(".", "-")[:140]
    objective = str(input_payload.get("user_goal") or f"worker_turn_{route_reason}")[:500]
    route_decision = route_decision or {}
    selected_local_model = str(route_decision.get("selected_local_model") or "")
    selected_pool_provider_id = provider_id if provider_id in WORKER_TURN_LOCAL_POOL_ROUTES else ""
    if provider_id in WORKER_TURN_LOCAL_POOL_ROUTES:
        carrier_runner = await asyncio.to_thread(
            worker_pool_phase1.invoke_local_ollama_qwen_lane,
            runtime_root=runtime_root,
            task_id=task_id,
            request_id=f"worker-turn-local-ollama-{worker_task_id}",
            invocation_id=invocation_id,
            episode_id=f"temporal:{task_id}",
            mode=dp_mode or "draft",
            objective=objective,
            input_text=worker_prompt,
            selected_model=selected_local_model,
            selected_pool_provider_id=selected_pool_provider_id,
            write=True,
        )
        local_payload = _provider_payload_from_runner(carrier_runner)
        if not worker_pool_phase1.provider_payload_succeeded(local_payload):
            local_blocker = str(local_payload.get("named_blocker") or "LOCAL_OLLAMA_QWEN_NOT_READY")
            if (dp_mode or "draft") in {"audit", "contradiction"} or selected_pool_provider_id == WORKER_TURN_ROUTE_LOCAL_DEEPSEEK_R1:
                dp_runner = await asyncio.to_thread(
                    dp_sidecar_execution_port.invoke_dp_sidecar_execution_port,
                    runtime_root=runtime_root,
                    task_id=task_id,
                    request_id=f"worker-turn-v4pro-fallback-{worker_task_id}",
                    invocation_id=f"{invocation_id}-v4pro-fallback"[:140],
                    episode_id=f"temporal:{task_id}",
                    mode=dp_mode or "audit",
                    objective=objective,
                    input_text=worker_prompt,
                    write=True,
                )
                dp_payload = _provider_payload_from_runner(dp_runner)
                dp_payload.update(
                    {
                        "fallback_from_provider_id": provider_id,
                        "fallback_reason": local_blocker,
                        "fallback_allowed": True,
                        "local_ollama_attempt_ref": str(local_payload.get("provider_invocation_ref") or ""),
                        "local_ollama_attempt_status": str(local_payload.get("mode_invocation_status") or ""),
                        "local_ollama_attempt_named_blocker": local_blocker,
                    }
                )
                dp_runner["provider_payload"] = dp_payload
                dp_runner["local_ollama_attempt"] = local_payload
                carrier_runner = dp_runner
                provider_id = WORKER_TURN_ROUTE_V4PRO
                route_reason = f"{route_reason}_fallback_v4pro_after_local"
            else:
                qwen_runner = await asyncio.to_thread(
                    worker_pool_phase1.invoke_qwen_cheap_worker_lane,
                    runtime_root=runtime_root,
                    task_id=task_id,
                    request_id=f"worker-turn-qwen-fallback-{worker_task_id}",
                    invocation_id=f"{invocation_id}-qwen-fallback"[:140],
                    episode_id=f"temporal:{task_id}",
                    mode=dp_mode or "draft",
                    objective=objective,
                    input_text=worker_prompt,
                    write=True,
                )
                qwen_payload = _provider_payload_from_runner(qwen_runner)
                qwen_payload.update(
                    {
                        "fallback_from_provider_id": provider_id,
                        "fallback_reason": local_blocker,
                        "fallback_allowed": True,
                        "local_ollama_attempt_ref": str(local_payload.get("provider_invocation_ref") or ""),
                        "local_ollama_attempt_status": str(local_payload.get("mode_invocation_status") or ""),
                        "local_ollama_attempt_named_blocker": local_blocker,
                    }
                )
                qwen_runner["provider_payload"] = qwen_payload
                qwen_runner["local_ollama_attempt"] = local_payload
                carrier_runner = qwen_runner
                provider_id = WORKER_TURN_ROUTE_QWEN
                route_reason = f"{route_reason}_fallback_qwen_after_local"
    elif provider_id == WORKER_TURN_ROUTE_QWEN:
        carrier_runner = await asyncio.to_thread(
            worker_pool_phase1.invoke_qwen_cheap_worker_lane,
            runtime_root=runtime_root,
            task_id=task_id,
            request_id=f"worker-turn-qwen-{worker_task_id}",
            invocation_id=invocation_id,
            episode_id=f"temporal:{task_id}",
            mode=dp_mode or "draft",
            objective=objective,
            input_text=worker_prompt,
            write=True,
        )
    else:
        carrier_runner = await asyncio.to_thread(
            dp_sidecar_execution_port.invoke_dp_sidecar_execution_port,
            runtime_root=runtime_root,
            task_id=task_id,
            request_id=f"worker-turn-v4pro-{worker_task_id}",
            invocation_id=invocation_id,
            episode_id=f"temporal:{task_id}",
            mode=dp_mode or "audit",
            objective=objective,
            input_text=worker_prompt,
            write=True,
        )
    provider_payload = _provider_payload_from_runner(carrier_runner)
    provider_payload["worker_turn_provider_decision"] = route_decision
    if (
        input_payload.get("tool_bearing_patch_executor_enabled") is True
        and provider_id != WORKER_TURN_ROUTE_CODEX_FINAL
    ):
        patch_executor_result = await asyncio.to_thread(
            cheap_worker_patch_executor.execute_from_provider_payload,
            runtime_root=runtime_root,
            repo_root=input_payload.get("repo_root") or _REPO_ROOT,
            task_id=task_id,
            worker_task_id=worker_task_id,
            provider_payload=provider_payload,
            verification=list(input_payload.get("verification") or []),
        )
        provider_payload["tool_bearing_patch_executor"] = patch_executor_result
    return _build_routed_worker_turn_activity_result(
        input_payload=input_payload,
        worker_task_id=worker_task_id,
        provider_id=provider_id,
        route_reason=route_reason,
        provider_payload=provider_payload,
        carrier_runner=carrier_runner,
        dp_mode=dp_mode,
        expected_marker=expected_marker,
        codex_final_deferred=codex_final_deferred,
    )


def collect_next_segment_dispatch_evidence(
    runtime_root: pathlib.Path,
    task_id: str,
) -> dict[str, str]:
    candidates = [
        runtime_root / "state" / "worker_dispatch_ledger" / "latest.json",
        runtime_root / "state" / "artifact_acceptance_queue" / "latest.json",
        runtime_root / "state" / "modular_dynamic_worker_pool_phase1" / "fan_in_staging_merge_spend" / "latest.json",
        runtime_root / "state" / "worker_assignment" / f"{task_id}.json",
        runtime_root / "state" / "default_auto_dispatch" / "latest.json",
    ]
    return {path.name: str(path) for path in candidates if path.is_file()}


def worker_turn_evidence_ready(worker: dict[str, Any]) -> bool:
    if worker.get("status") != "activity_gate_checked":
        return False
    if worker.get("jsonl_exists") is True:
        return True
    if worker.get("codex_jsonl_is_execution_evidence") is True:
        return True
    if worker.get("dp_artifact_exists") is True:
        return True
    return bool(worker.get("jsonl_path") or worker.get("artifact_ref"))


def _read_next_segment_evidence_digest(
    runtime_root: pathlib.Path,
    task_id: str,
) -> tuple[dict[str, str], str]:
    evidence_refs = collect_next_segment_dispatch_evidence(runtime_root, task_id)
    snippets: list[str] = []
    for name, path in evidence_refs.items():
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8-sig", errors="replace")
            snippets.append(f"=== {name} ===\n{text[:6000]}")
        except OSError:
            continue
    return evidence_refs, "\n\n".join(snippets)


def _v4pro_brain_dispatch_model_content(provider_payload: dict[str, Any]) -> str:
    raw_response = provider_payload.get("raw_response")
    if isinstance(raw_response, dict):
        content = str(raw_response.get("content") or "")
        if content:
            return content
        nested = raw_response.get("response")
        if isinstance(nested, dict):
            return str(nested.get("content") or "")
    return ""


async def invoke_v4pro_next_segment_brain_dispatch(
    *,
    runtime_root: pathlib.Path,
    task_id: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    evidence_refs, evidence_text = _read_next_segment_evidence_digest(runtime_root, task_id)
    if not evidence_text.strip():
        return {
            "status": "v4pro_brain_dispatch_blocked",
            "named_blocker": "V4PRO_BRAIN_DISPATCH_NO_EVIDENCE_REFS",
            "dispatch_layer_only": True,
            "execution_routing_unchanged": True,
        }
    next_worker = (
        input_payload.get("segment_pass_next_worker")
        if isinstance(input_payload.get("segment_pass_next_worker"), dict)
        else {}
    )
    prompt = "\n".join(
        [
            "Role: Codex S brain dispatch coordinator (deepseek_v4_pro).",
            "Codex acceptance/quota is blocked; prepare next-segment dispatch only.",
            "Hard constraints:",
            "- execution_routing_unchanged=true (do NOT reroute Qwen/DP/Codex workers)",
            "- continuation_allowed_without_codex_acceptance when evidence supports next frontier",
            "- not_user_completion, not_completion_decision",
            f"task_id={task_id}",
            f"user_goal={str(input_payload.get('user_goal') or '')[:500]}",
            f"next_worker_status={next_worker.get('status', '')}",
            f"next_worker_blocker={next_worker.get('named_blocker', '')}",
            "",
            evidence_text[:24000],
            "",
            "Respond with: frontier_summary, next_action_cn, continuation_allowed (yes/no), prepared_node_hint.",
            f"Final line exactly: {V4PRO_NEXT_SEGMENT_BRAIN_DISPATCH_MARKER}",
        ]
    )
    invocation_id = f"v4pro-brain-dispatch-{task_id}-{run_id()}"[:140]
    dp_result = await asyncio.to_thread(
        dp_sidecar_execution_port.invoke_dp_sidecar_execution_port,
        runtime_root=runtime_root,
        task_id=task_id,
        request_id=f"v4pro-next-segment-brain-dispatch-{task_id}",
        invocation_id=invocation_id,
        episode_id=f"temporal:{task_id}",
        mode="audit",
        objective="v4pro_next_segment_brain_dispatch_codex_acceptance_substitute",
        input_text=prompt,
        write=True,
    )
    provider_payload = (
        dp_result.get("provider_payload")
        if isinstance(dp_result.get("provider_payload"), dict)
        else {}
    )
    model_invoked = provider_payload.get("model_invocation_performed") is True
    content = _v4pro_brain_dispatch_model_content(provider_payload)
    provider_text = json.dumps(provider_payload, ensure_ascii=False)
    marker_seen = (
        V4PRO_NEXT_SEGMENT_BRAIN_DISPATCH_MARKER in content
        or V4PRO_NEXT_SEGMENT_BRAIN_DISPATCH_MARKER in provider_text
    )
    continuation_allowed = marker_seen and model_invoked
    if "continuation_allowed" in content.lower():
        tail = content.lower().split("continuation_allowed", 1)[-1][:40]
        if "no" in tail and "yes" not in tail:
            continuation_allowed = False
    prepared_signal = assignment_dag_auto_continue_signal(runtime_root, task_id, input_payload)
    dispatch_ref = (
        runtime_root
        / "state"
        / "temporal_codex_task_workflow"
        / "v4pro_brain_dispatch"
        / f"{task_id}.json"
    )
    result = {
        "status": (
            "v4pro_brain_dispatch_ready"
            if continuation_allowed
            else "v4pro_brain_dispatch_blocked"
        ),
        "brain_dispatch_provider": V4PRO_BRAIN_DISPATCH_PROVIDER,
        "dispatch_layer_only": True,
        "execution_routing_unchanged": True,
        "continuation_allowed_without_codex_acceptance": continuation_allowed,
        "codex_acceptance_substituted_by": V4PRO_BRAIN_DISPATCH_PROVIDER,
        "model_invocation_performed": model_invoked,
        "marker_seen": marker_seen,
        "evidence_refs": evidence_refs,
        "prepared_signal": prepared_signal,
        "artifact_ref": str(provider_payload.get("result_path") or ""),
        "provider_invocation_ref": str(provider_payload.get("provider_invocation_ref") or ""),
        "named_blocker": (
            ""
            if continuation_allowed
            else str(provider_payload.get("named_blocker") or "V4PRO_BRAIN_DISPATCH_MODEL_UNAVAILABLE")
        ),
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_source_of_truth": True,
        "authority_boundary": authority_boundary("v4pro_next_segment_brain_dispatch_readback"),
        "dp_sidecar_result": dp_result,
    }
    write_json(dispatch_ref, result)
    result["dispatch_ref"] = str(dispatch_ref)
    return result


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
async def task_contract_router_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    payload = await asyncio.to_thread(
        task_contract_router.build_contract,
        input_payload,
        runtime_root=runtime_root,
        write=True,
    )
    return {
        "activity": "task_contract_router",
        "status": payload.get("status", "task_contract_router_unknown"),
        "task_contract": payload,
        "contract_id": str(payload.get("contract_id") or ""),
        "explicit_execution_task": payload.get("explicit_execution_task") is True,
        "delivery_contract": payload.get("delivery_contract") if isinstance(payload.get("delivery_contract"), dict) else {},
        "workflow_switches": payload.get("workflow_switches") if isinstance(payload.get("workflow_switches"), dict) else {},
        "record_path": str(payload.get("record_path") or ""),
        "latest_path": str(payload.get("latest_path") or ""),
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("task_contract_router_activity"),
    }


@activity.defn
async def post_continue_as_new_status_refresh_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    resume_state = (
        input_payload.get("default_loop_continue_as_new_resume_state")
        if isinstance(input_payload.get("default_loop_continue_as_new_resume_state"), dict)
        else {}
    )
    previous_run_id = str(
        input_payload.get("default_loop_previous_run_id")
        or resume_state.get("previous_run_id")
        or ""
    )
    refresh_source = str(
        input_payload.get("post_continue_as_new_refresh_source")
        or "temporal_workflow_start_after_continue_as_new"
    )
    payload = await asyncio.to_thread(
        post_continue_as_new_status_refresh.build_post_continue_as_new_status_refresh,
        runtime_root=runtime_root,
        repo_root=repo_root,
        workflow_id=str(input_payload.get("workflow_id") or ""),
        workflow_run_id=str(input_payload.get("workflow_run_id") or ""),
        refresh_source=refresh_source,
        write=True,
        write_aaq=bool(input_payload.get("post_continue_as_new_status_refresh_write_aaq")),
    )
    return {
        "activity": "post_continue_as_new_status_refresh",
        "status": payload.get("status", "post_continue_as_new_status_refresh_unknown"),
        "task_id": post_continue_as_new_status_refresh.TASK_ID,
        "post_continue_as_new_status_refresh_ready": payload.get(
            "post_continue_as_new_status_refresh_ready"
        )
        is True,
        "current_workflow_id": str(payload.get("current_workflow_id") or ""),
        "current_workflow_run_id": str(payload.get("current_workflow_run_id") or ""),
        "bounded_result_wait_run_id": str(payload.get("bounded_result_wait_run_id") or ""),
        "previous_run_id": previous_run_id,
        "named_blocker": str(payload.get("named_blocker") or ""),
        "latest_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "latest"
            )
            or ""
        ),
        "readback_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "readback"
            )
            or ""
        ),
        "validation": payload.get("validation") if isinstance(payload.get("validation"), dict) else {},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("post_continue_as_new_status_refresh_activity"),
    }


@activity.defn
async def v4pro_tool_bearing_executor_policy_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    payload = await asyncio.to_thread(
        v4pro_tool_bearing_executor_policy.build_policy,
        runtime_root=runtime_root,
        repo_root=repo_root,
        write=True,
        write_aaq=True,
    )
    return {
        "activity": "v4pro_tool_bearing_executor_policy",
        "status": payload.get("status", "v4pro_tool_bearing_executor_policy_unknown"),
        "task_id": v4pro_tool_bearing_executor_policy.TASK_ID,
        "tool_bearing_executor_eligible": payload.get("tool_bearing_executor_eligible") is True,
        "repo_mutation_allowed": payload.get("repo_mutation_allowed") is True,
        "commit_push_allowed": payload.get("commit_push_allowed") is True,
        "final_acceptance_owner": str(payload.get("final_acceptance_owner") or ""),
        "closure_evidence_bundle_required": list(
            payload.get("closure_evidence_bundle_required") or []
        ),
        "named_blocker": str(payload.get("named_blocker") or ""),
        "latest_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "latest"
            )
            or ""
        ),
        "readback_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "readback"
            )
            or ""
        ),
        "validation": payload.get("validation") if isinstance(payload.get("validation"), dict) else {},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("v4pro_tool_bearing_executor_policy_activity"),
    }


@activity.defn
async def mature_bind_queue_autopop_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    exclude_task_ids = input_payload.get("mature_bind_queue_autopop_exclude_task_ids")
    if not isinstance(exclude_task_ids, list):
        exclude_task_ids = [mature_bind_queue_autopop.TASK_ID]
    payload = await asyncio.to_thread(
        mature_bind_queue_autopop.build_autopop,
        runtime_root=runtime_root,
        repo_root=repo_root,
        write=True,
        send_signal=bool(input_payload.get("mature_bind_queue_autopop_send_signal")),
        exclude_task_ids=[str(item) for item in exclude_task_ids if str(item).strip()],
        write_aaq=True,
    )
    auto_signal = (
        payload.get("auto_continue_same_task_signal")
        if isinstance(payload.get("auto_continue_same_task_signal"), dict)
        else {}
    )
    return {
        "activity": "mature_bind_queue_autopop",
        "status": payload.get("status", "mature_bind_queue_autopop_unknown"),
        "task_id": mature_bind_queue_autopop.TASK_ID,
        "mature_bind_queue_autopop_ready": payload.get("mature_bind_queue_autopop_ready") is True,
        "queue_empty": payload.get("queue_empty") is True,
        "next_mature_bind_task_id": str(payload.get("next_mature_bind_task_id") or ""),
        "contract_id": str(payload.get("contract_id") or ""),
        "signal_path": str(payload.get("signal_path") or ""),
        "auto_continue_same_workflow": bool(payload.get("auto_continue_same_workflow")),
        "auto_continue_same_task_signal": auto_signal,
        "signal_result": payload.get("signal_result") if isinstance(payload.get("signal_result"), dict) else {},
        "validation": payload.get("validation") if isinstance(payload.get("validation"), dict) else {},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("mature_bind_queue_autopop_activity"),
    }


@activity.defn
async def current_task_source_intake_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    task_package_root = pathlib.Path(
        str(
            input_payload.get("task_package_root")
            or os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
        )
    )
    payload = await asyncio.to_thread(
        current_task_source_intake.build_current_task_source_intake,
        runtime_root=runtime_root,
        repo_root=repo_root,
        task_package_root=task_package_root,
        write=True,
    )
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "activity": "current_task_source_intake",
        "status": payload.get("status", "current_task_source_intake_unknown"),
        "task_id": current_task_source_intake.TASK_ID,
        "current_task_source_intake_ready": payload.get("status") == "current_task_source_intake_ready",
        "brief_count": int(payload.get("brief_count") or 0),
        "named_blocker": str(payload.get("named_blocker") or ""),
        "latest_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "latest"
            )
            or ""
        ),
        "validation": validation,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("current_task_source_intake_activity"),
    }


@activity.defn
async def v4pro_mature_bind_execution_controller_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    task_package_root = pathlib.Path(
        str(
            input_payload.get("task_package_root")
            or os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
        )
    )
    payload = await asyncio.to_thread(
        v4pro_mature_bind_execution_controller.build_controller,
        runtime_root=runtime_root,
        repo_root=repo_root,
        task_package_root=task_package_root,
        write=True,
        send_signal=bool(input_payload.get("v4pro_mature_bind_execution_controller_send_signal")),
        run_verification=bool(input_payload.get("v4pro_mature_bind_execution_controller_run_verification")),
        write_aaq=True,
    )
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    return {
        "activity": "v4pro_mature_bind_execution_controller",
        "status": payload.get("status", "v4pro_mature_bind_execution_controller_unknown"),
        "task_id": v4pro_mature_bind_execution_controller.TASK_ID,
        "v4pro_mature_bind_execution_controller_ready": payload.get(
            "v4pro_mature_bind_execution_controller_ready"
        )
        is True,
        "controller_state": str(payload.get("controller_state") or ""),
        "submit_status": str(payload.get("submit_status") or ""),
        "submitted": payload.get("submitted") is True,
        "mature_bind_task_id": str(payload.get("mature_bind_task_id") or ""),
        "named_blocker": str(payload.get("named_blocker") or ""),
        "latest_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "latest"
            )
            or ""
        ),
        "validation": validation,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "is_execution_controller": True,
        "not_execution_controller": False,
        "authority_boundary": authority_boundary("v4pro_mature_bind_execution_controller_activity"),
    }


@activity.defn
async def v4pro_supervisor_orchestrator_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    task_package_root = pathlib.Path(
        str(
            input_payload.get("task_package_root")
            or os.environ.get("XINAO_TASK_PACKAGE_ROOT", r"C:\Users\xx363\Desktop\新系统")
        )
    )
    minimal_bootstrap = input_payload.get("v4pro_supervisor_orchestrator_minimal_bootstrap") is True
    payload = await asyncio.to_thread(
        v4pro_supervisor_orchestrator.build_orchestrator,
        runtime_root=runtime_root,
        repo_root=repo_root,
        task_package_root=task_package_root,
        write=True,
        send_signal=(
            bool(input_payload.get("v4pro_supervisor_orchestrator_send_signal"))
            and not minimal_bootstrap
        ),
        run_verification=(
            bool(input_payload.get("v4pro_supervisor_orchestrator_run_verification"))
            and not minimal_bootstrap
        ),
        dispatch_workers=(
            bool(input_payload.get("v4pro_supervisor_orchestrator_dispatch_workers"))
            and not minimal_bootstrap
        ),
        write_aaq=bool(input_payload.get("v4pro_supervisor_orchestrator_write_aaq", True)),
    )
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    controller = (
        payload.get("execution_controller")
        if isinstance(payload.get("execution_controller"), dict)
        else {}
    )
    return {
        "activity": "v4pro_supervisor_orchestrator",
        "status": payload.get("status", "v4pro_supervisor_orchestrator_unknown"),
        "task_id": v4pro_supervisor_orchestrator.TASK_ID,
        "v4pro_supervisor_orchestrator_ready": payload.get("v4pro_supervisor_orchestrator_ready") is True,
        "orchestrator_state": str(payload.get("orchestrator_state") or ""),
        "minimal_bootstrap_mode": payload.get("minimal_bootstrap_mode") is True,
        "next_mature_bind_task_id": str(
            (payload.get("task_package_snapshot") if isinstance(payload.get("task_package_snapshot"), dict) else {}).get(
                "next_mature_bind_task_id"
            )
            or ""
        ),
        "execution_controller_state": str(controller.get("controller_state") or ""),
        "execution_submit_status": str(controller.get("submit_status") or ""),
        "named_blocker": str(payload.get("named_blocker") or ""),
        "latest_ref": str(
            (payload.get("output_paths") if isinstance(payload.get("output_paths"), dict) else {}).get(
                "latest"
            )
            or ""
        ),
        "validation": validation,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "is_execution_controller": True,
        "not_execution_controller": False,
        "authority_boundary": authority_boundary("v4pro_supervisor_orchestrator_activity"),
    }


@activity.defn
async def root_intent_loop_driver_temporal_tick_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or SEED_CORTEX_RUNTIME_ROOT))
    repo_root = pathlib.Path(str(input_payload.get("repo_root") or _REPO_ROOT))
    worker_ledger_activity_ref = (
        input_payload.get("worker_dispatch_ledger_activity")
        if isinstance(input_payload.get("worker_dispatch_ledger_activity"), dict)
        else {}
    )
    payload = await asyncio.to_thread(
        root_intent_loop_driver.run_temporal_root_driver_tick,
        runtime_root=runtime_root,
        repo_root=repo_root,
        wave_id=str(input_payload.get("wave_id") or ""),
        workflow_id=str(input_payload.get("workflow_id") or ""),
        workflow_run_id=str(input_payload.get("workflow_run_id") or ""),
        worker_dispatch_ledger_activity_ref=worker_ledger_activity_ref,
        write=True,
    )
    return {
        "activity": "root_intent_loop_driver_temporal_tick",
        "status": payload.get("status", "temporal_root_driver_tick_unknown"),
        "task_id": "p0_027_temporal_every_wave_root_driver_tick",
        "temporal_every_wave_root_driver_tick_ready": payload.get(
            "temporal_every_wave_root_driver_tick_ready"
        )
        is True,
        "ledger_succeeded_count": int(payload.get("ledger_succeeded_count") or 0),
        "consumed_ledger_poll_results": payload.get("consumed_ledger_poll_results") is True,
        "fan_in_validation_passed": payload.get("fan_in_validation_passed") is True,
        "bridge_ref": str(payload.get("bridge_ref") or ""),
        "named_blocker": str(payload.get("named_blocker") or ""),
        "validation": payload.get("validation") if isinstance(payload.get("validation"), dict) else {},
        "runtime_enforced": payload.get("temporal_every_wave_root_driver_tick_ready") is True,
        "runtime_enforced_scope": "seed_cortex_temporal_root_intent_loop_driver_every_wave_tick",
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("root_intent_loop_driver_temporal_tick_activity"),
    }


def local_mature_bind_service_required(input_payload: dict[str, Any]) -> bool:
    return any(
        input_payload.get(key) is True
        for key in (
            "post_continue_as_new_status_refresh_required",
            "v4pro_tool_bearing_executor_policy_required",
            "mature_bind_queue_autopop_required",
            "current_task_source_intake_required",
            "v4pro_mature_bind_execution_controller_required",
            "v4pro_supervisor_orchestrator_required",
        )
    )


async def invoke_local_mature_bind_service_activity(
    input_payload: dict[str, Any],
    retry: RetryPolicy,
) -> dict[str, Any]:
    if input_payload.get("post_continue_as_new_status_refresh_required") is True:
        return await workflow.execute_activity(
            post_continue_as_new_status_refresh_activity,
            {
                **input_payload,
                "post_continue_as_new_status_refresh_write_aaq": True,
            },
            start_to_close_timeout=dt.timedelta(minutes=3),
            retry_policy=retry,
        )
    if input_payload.get("v4pro_tool_bearing_executor_policy_required") is True:
        return await workflow.execute_activity(
            v4pro_tool_bearing_executor_policy_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=3),
            retry_policy=retry,
        )
    if input_payload.get("mature_bind_queue_autopop_required") is True:
        return await workflow.execute_activity(
            mature_bind_queue_autopop_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=3),
            retry_policy=retry,
        )
    if input_payload.get("current_task_source_intake_required") is True:
        return await workflow.execute_activity(
            current_task_source_intake_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=retry,
        )
    if input_payload.get("v4pro_mature_bind_execution_controller_required") is True:
        return await workflow.execute_activity(
            v4pro_mature_bind_execution_controller_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=retry,
        )
    if input_payload.get("v4pro_supervisor_orchestrator_required") is True:
        return await workflow.execute_activity(
            v4pro_supervisor_orchestrator_activity,
            input_payload,
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=retry,
        )
    return {}


def local_mature_bind_worker_result(input_payload: dict[str, Any], service_result: dict[str, Any]) -> dict[str, Any]:
    validation = service_result.get("validation") if isinstance(service_result.get("validation"), dict) else {}
    ready = validation.get("passed") is True
    task_id = str(
        service_result.get("task_id")
        or input_payload.get("task_contract_id")
        or input_payload.get("phase_scope")
        or "local_mature_bind_service"
    )
    return {
        "activity": "codex_worker_turn",
        "status": "activity_gate_checked" if ready else "activity_blocked",
        "task_id": str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID),
        "worker_task_id": task_id,
        "worker_kind": "local_deterministic_mature_bind_service",
        "phase_scope": task_id,
        "selected_provider_id": "local_deterministic_mature_bind_service",
        "actual_provider_id": "local_deterministic_mature_bind_service",
        "local_deterministic_mature_bind_service": True,
        "local_mature_bind_service_activity": service_result.get("activity"),
        "local_mature_bind_service_status": service_result.get("status"),
        "latest_ref": str(service_result.get("latest_ref") or service_result.get("signal_path") or ""),
        "named_blocker": "" if ready else str(service_result.get("named_blocker") or "LOCAL_MATURE_BIND_SERVICE_BLOCKED"),
        "worker_dispatch_real_receipt_required": False,
        "synthetic_succeeded_by_driver": False,
        "phase1_worker_pool_receipt": False,
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("local_mature_bind_worker_result"),
    }


def local_mature_bind_task_id(input_payload: dict[str, Any], service_result: dict[str, Any]) -> str:
    mature_bind = (
        input_payload.get("mature_bind_task")
        if isinstance(input_payload.get("mature_bind_task"), dict)
        else {}
    )
    return str(
        service_result.get("task_id")
        or mature_bind.get("task_id")
        or input_payload.get("task_contract_id")
        or input_payload.get("phase_scope")
        or ""
    )


async def autopop_next_mature_bind_after_local_success(
    input_payload: dict[str, Any],
    service_result: dict[str, Any],
    retry: RetryPolicy,
) -> dict[str, Any]:
    validation = service_result.get("validation") if isinstance(service_result.get("validation"), dict) else {}
    if validation.get("passed") is not True:
        return {}
    if input_payload.get("disable_mature_bind_queue_autopop_after_success") is True:
        return {}
    if service_result.get("activity") == "mature_bind_queue_autopop":
        return {}
    current_task_id = local_mature_bind_task_id(input_payload, service_result)
    exclude = [mature_bind_queue_autopop.TASK_ID]
    if current_task_id:
        exclude.append(current_task_id)
    return await workflow.execute_activity(
        mature_bind_queue_autopop_activity,
        {
            **input_payload,
            "mature_bind_queue_autopop_exclude_task_ids": exclude,
            "mature_bind_queue_autopop_send_signal": False,
        },
        start_to_close_timeout=dt.timedelta(minutes=3),
        retry_policy=retry,
    )


def _worker_brief_safe_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return cleaned.strip("-")[:96] or "worker-brief"


def _build_worker_brief_receipt_prompt(
    *,
    brief: dict[str, Any],
    source_text: str,
    require_dp_receipt: bool,
) -> str:
    return "\n".join(
        [
            "Role: Seed Cortex p0_008 WorkerBrief provider lane.",
            "Goal: produce a task-scoped provider receipt for the canonical WorkerBrief.",
            "Hard constraints:",
            "- Do not mutate repo files.",
            "- Do not open next_frontier.",
            "- Return a compact receipt summary tied to the worker_brief_id and source_ledger_entry_id.",
            "- Include actual work based on the source text, not only acknowledgement.",
            f"- require_dp_receipt_for_this_lane={str(require_dp_receipt).lower()}",
            "",
            f"worker_brief_id={brief.get('worker_brief_id') or brief.get('brief_id')}",
            f"lane_id={brief.get('lane_id')}",
            f"lane_class={brief.get('lane_class')}",
            f"source_role={brief.get('source_role')}",
            f"source_ref={brief.get('source_ref')}",
            f"source_sha256={brief.get('source_sha256')}",
            f"source_ledger_entry_id={brief.get('source_ledger_entry_id')}",
            f"objective={brief.get('objective')}",
            "",
            "Source text excerpt:",
            source_text[:12000],
            "",
            "Return fields: receipt_status, worker_brief_id, actual_provider_work_summary, blocker_if_any.",
            f"Final line exactly: {TASK_BOUND_CODEX_WORKER_MARKER}",
        ]
    )


@activity.defn
async def worker_brief_dispatch_plan_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "worker_brief_dispatch_plan",
            "status": "skipped_non_seed_cortex_route",
            "worker_dispatch_real_receipt_ready": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("worker_brief_dispatch_plan_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "worker_brief_dispatch_plan",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_WORKER_BRIEF_DISPATCH_PLAN_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "worker_dispatch_real_receipt_ready": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("worker_brief_dispatch_plan_runtime_root_guard"),
        }
    queue_path = runtime_root / "state" / "worker_brief_queue" / "latest.json"
    queue = read_json(queue_path, {})
    briefs = queue.get("briefs") if isinstance(queue.get("briefs"), list) else []
    limit = int(input_payload.get("worker_brief_dispatch_limit") or len(briefs) or 0)
    selected_briefs = [item for item in briefs if isinstance(item, dict)][: max(0, limit)]
    workflow_id = str(input_payload.get("workflow_id") or "")
    workflow_run_id = str(input_payload.get("workflow_run_id") or input_payload.get("run_id") or "")
    require_dp_receipt = input_payload.get("require_dp_receipt") is not False
    dp_lane_assigned = False
    worker_turn_payloads: list[dict[str, Any]] = []
    brief_summaries: list[dict[str, Any]] = []
    for index, brief in enumerate(selected_briefs, start=1):
        brief_id = str(brief.get("worker_brief_id") or brief.get("brief_id") or f"brief-{index}")
        source_ref = pathlib.Path(str(brief.get("source_ref") or ""))
        source_text = _read_text_if_exists(source_ref, limit=16000)
        candidates = [str(item) for item in brief.get("provider_candidates", []) if str(item)]
        dp_candidate = any("deepseek" in item.lower() or item.lower() == "dp" for item in candidates)
        force_dp_this_lane = bool(require_dp_receipt and dp_candidate and not dp_lane_assigned)
        if force_dp_this_lane:
            dp_lane_assigned = True
        provider_route_key = (
            "architecture_receipt_audit"
            if force_dp_this_lane
            else str(brief.get("provider_route_key") or "draft_extraction_classify_eval")
        )
        worker_task_id = (
            f"{P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID}."
            f"{index:02d}.{_worker_brief_safe_token(str(brief.get('source_role') or brief_id))}"
        )
        prompt = _build_worker_brief_receipt_prompt(
            brief=brief,
            source_text=source_text,
            require_dp_receipt=force_dp_this_lane,
        )
        worker_payload = {
            **input_payload,
            "task_id": task_id,
            "route_profile": SEED_CORTEX_ROUTE_PROFILE,
            "workflow_id": workflow_id,
            "workflow_run_id": workflow_run_id,
            "execute_worker_turn": True,
            "execute_codex_worker": False,
            "codex_worker_task_id": worker_task_id,
            "codex_worker_prompt": prompt,
            "codex_worker_expected_marker": TASK_BOUND_CODEX_WORKER_MARKER,
            "worker_kind": "worker_brief_receipt_worker",
            "phase_scope": P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID,
            "provider_route_key": provider_route_key,
            "worker_brief_id": brief_id,
            "worker_brief_queue_id": str(queue.get("queue_id") or ""),
            "worker_brief_index": index,
            "source_package_id": str(brief.get("source_package_id") or ""),
            "source_ledger_entry_id": str(brief.get("source_ledger_entry_id") or ""),
            "source_ref": str(brief.get("source_ref") or ""),
            "source_sha256": str(brief.get("source_sha256") or ""),
            "source_role": str(brief.get("source_role") or ""),
            "provider_candidates": candidates,
            "worker_dispatch_real_receipt_required": True,
            "worker_brief_real_receipt_required": True,
            "tool_bearing_patch_executor_enabled": False,
            "verification": ["worker_dispatch_real_receipt_ready"],
        }
        worker_turn_payloads.append(worker_payload)
        brief_summaries.append(
            {
                "worker_brief_id": brief_id,
                "worker_task_id": worker_task_id,
                "source_ref": str(brief.get("source_ref") or ""),
                "provider_route_key": provider_route_key,
                "force_dp_receipt": force_dp_this_lane,
                "source_text_read": bool(source_text),
            }
        )
    checks = {
        "queue_ready": queue.get("status") == "worker_brief_queue_ready",
        "queue_current_package": queue.get("source_package_id") == CURRENT_P0_THREE_TEXT_SOURCE_PACKAGE_ID,
        "queue_dispatch_ready": queue.get("dispatch_ready") is True,
        "frontier_not_default": queue.get("next_frontier_default_outlet") is False,
        "brief_payload_count": len(worker_turn_payloads) == int(queue.get("brief_count") or 0) >= 3,
        "dp_lane_assigned": dp_lane_assigned if require_dp_receipt else True,
        "workflow_bound": bool(workflow_id and workflow_run_id),
    }
    status = "worker_brief_dispatch_plan_ready" if all(checks.values()) else "worker_brief_dispatch_plan_blocked"
    state_dir = runtime_root / "state" / "worker_brief_dispatch_plan"
    latest = state_dir / "latest.json"
    record = state_dir / "records" / f"{P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID}.json"
    payload = {
        "schema_version": "xinao.codex_s.worker_brief_dispatch_plan.v1",
        "activity": "worker_brief_dispatch_plan",
        "status": status,
        "task_id": task_id,
        "contract_id": P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "worker_brief_queue_ref": str(queue_path),
        "worker_brief_count": int(queue.get("brief_count") or len(briefs) or 0),
        "planned_worker_count": len(worker_turn_payloads),
        "require_dp_receipt": require_dp_receipt,
        "dp_lane_assigned": dp_lane_assigned,
        "briefs": brief_summaries,
        "worker_turn_payloads": worker_turn_payloads,
        "validation": {"passed": all(checks.values()), "checks": checks, "validated_at": now()},
        "output_paths": {"latest": str(latest), "record": str(record)},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("worker_brief_dispatch_plan_activity"),
    }
    write_json(latest, payload)
    write_json(record, payload)
    return payload


@activity.defn
async def codex_worker_turn_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    if not worker_turn_execution_requested(input_payload):
        named_blocker = str(input_payload.get("named_blocker") or "")
        if named_blocker:
            return {
                "activity": "codex_worker_turn",
                "status": "activity_blocked",
                "named_blocker": named_blocker,
                "assignment_missing_fields": list(input_payload.get("assignment_missing_fields") or []),
                **worker_turn_switch_alias_payload(input_payload),
                "not_source_of_truth": True,
                "not_user_completion": True,
                "authority_boundary": authority_boundary("codex_worker_turn_blocked_readback"),
                "required_for_production_completion": True,
            }
        return {
            "activity": "codex_worker_turn",
            "status": "skipped_until_route_requires_worker_turn_execution",
            **worker_turn_switch_alias_payload(input_payload),
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
        )
        route_decision = resolve_worker_turn_provider_decision(input_payload)
        provider_id = str(route_decision.get("provider_id") or WORKER_TURN_ROUTE_V4PRO)
        dp_mode = str(route_decision.get("mode") or "")
        route_reason = str(route_decision.get("route_reason") or "worker_turn_provider_router_decision")
        codex_final_deferred = False
        if provider_id == WORKER_TURN_ROUTE_CODEX_FINAL and codex_acceptance_unavailable(runtime_root):
            provider_id = WORKER_TURN_ROUTE_V4PRO
            dp_mode = "audit"
            route_reason = "codex_final_acceptance_deferred_v4pro_precheck"
            codex_final_deferred = True
            route_decision = {
                **route_decision,
                "provider_id": provider_id,
                "mode": dp_mode,
                "route_reason": route_reason,
                "codex_final_deferred": True,
            }
        if provider_id != WORKER_TURN_ROUTE_CODEX_FINAL:
            return await invoke_routed_worker_turn_carrier(
                runtime_root=runtime_root,
                input_payload=input_payload,
                worker_task_id=worker_task_id,
                worker_prompt=worker_prompt,
                provider_id=provider_id,
                dp_mode=dp_mode,
                route_reason=route_reason,
                expected_marker=expected_marker,
                codex_final_deferred=codex_final_deferred,
                route_decision=route_decision,
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
            "action_decision": "task_bound_worker_turn_required_by_provider_router",
            "dispatch_strategy": "temporal_codex_task_workflow_to_codex_activator",
            "headless_worker": segment_boundary_headless,
            "segment_boundary_headless": segment_boundary_headless,
            "human_egress_policy": "",
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
            **worker_turn_switch_alias_payload(input_payload),
            "selected_provider_id": WORKER_TURN_ROUTE_CODEX_FINAL,
            "actual_provider_id": WORKER_TURN_ROUTE_CODEX_FINAL,
            "actual_provider_family": "codex",
            "actual_carrier_provider_id": "codex_activator",
            "provider_router_active": True,
            "provider_route_reason": route_reason,
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
            "worker_brief_id": str(input_payload.get("worker_brief_id") or ""),
            "worker_brief_queue_id": str(input_payload.get("worker_brief_queue_id") or ""),
            "worker_brief_index": input_payload.get("worker_brief_index"),
            "source_package_id": str(input_payload.get("source_package_id") or ""),
            "source_ledger_entry_id": str(input_payload.get("source_ledger_entry_id") or ""),
            "source_ref": str(input_payload.get("source_ref") or ""),
            "source_sha256": str(input_payload.get("source_sha256") or ""),
            "source_role": str(input_payload.get("source_role") or ""),
            "provider_candidates": list(input_payload.get("provider_candidates") or []),
            "worker_dispatch_receipt_id": f"{worker_task_id}:receipt",
            "worker_dispatch_real_receipt_required": (
                input_payload.get("worker_dispatch_real_receipt_required") is True
            ),
            "worker_brief_real_receipt_required": (
                input_payload.get("worker_brief_real_receipt_required") is True
            ),
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
    tool_surface = ucp_tool_surface_resolver.resolve_ucp_tool_surface(
        evidence_runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
    )
    tool_root = pathlib.Path(str(tool_surface.get("tool_root") or runtime_root))
    python = pathlib.Path(str(tool_surface.get("python_path") or ""))
    ucp = pathlib.Path(str(tool_surface.get("ucp_path") or ""))
    if not tool_surface.get("ready"):
        return {
            "activity": "codex_worker_turn",
            "status": "activity_blocked",
            "command_surface": "UCP -> codex_exec_direct -> codex exec --json",
            "named_blocker": str(tool_surface.get("named_blocker") or "CODEX_WORKER_UCP_TOOL_SURFACE_MISSING"),
            "tool_root": str(tool_root),
            "tool_root_source": str(tool_surface.get("tool_root_source") or ""),
            "python_exists": tool_surface.get("python_exists") is True,
            "ucp_exists": tool_surface.get("ucp_exists") is True,
            "ucp_tool_surface": tool_surface,
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
    p0_008_required = explicit_contract_requires_worker_brief_real_receipts(input_payload)
    ledger_payload = worker_dispatch_ledger.build_worker_dispatch_ledger(
        repo_root=_REPO_ROOT,
        runtime_root=runtime_root,
        wave_id=wave_id,
        task_id=task_id,
        extra_entries=entries,
        poll_scope_lane_id_prefixes=("temporal-codex-worker-turn-",),
        auto_dispatch_performed=p0_008_required,
        worker_dispatch_real_receipt_required=p0_008_required,
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
        "p0_008_worker_dispatch_real_receipt": ledger_payload.get(
            "p0_008_worker_dispatch_real_receipt",
            {},
        ),
        "worker_dispatch_real_receipt_ready": (
            ledger_payload.get("p0_008_worker_dispatch_real_receipt", {}).get(
                "worker_dispatch_real_receipt_ready"
            )
            is True
        ),
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
    p0_007_required = explicit_contract_requires_default_main_loop_tick(input_payload)
    current_worker_brief_queue = current_worker_brief_queue_main_tick_binding(
        runtime_root,
        input_payload,
    )
    if p0_007_required:
        tick_payload["current_worker_brief_queue"] = current_worker_brief_queue
        tick_payload["p0_007_default_main_loop_trigger_bind"] = {
            "task_id": P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID,
            "status": "current_worker_brief_queue_consumed_by_temporal_main_tick"
            if current_worker_brief_queue["consumed_by_temporal_main_tick"]
            else "current_worker_brief_queue_not_consumed_by_temporal_main_tick",
            "default_main_loop_trigger_runtime_enforced": True,
            "current_worker_brief_queue_required": True,
            "current_worker_brief_queue_consumed_by_temporal_main_tick": (
                current_worker_brief_queue["consumed_by_temporal_main_tick"]
            ),
            "current_worker_brief_queue_ref": current_worker_brief_queue["queue_ref"],
            "brief_count": current_worker_brief_queue["brief_count"],
            "workflow_id": current_worker_brief_queue["input_workflow_id"],
            "workflow_run_id": current_worker_brief_queue["input_workflow_run_id"],
            "next_required_activity": "default_main_loop_trigger_candidate_activity",
            "next_required_task": "p0_008_worker_dispatch_real_receipt",
            "p0_008_receipt_gap_allowed_as_next_blocker": True,
            "accepted_for_next_frontier_default_outlet": False,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }
        validation = (
            dict(tick_payload.get("validation"))
            if isinstance(tick_payload.get("validation"), dict)
            else {}
        )
        checks = (
            dict(validation.get("checks"))
            if isinstance(validation.get("checks"), dict)
            else {}
        )
        checks.update(
            {
                "p0_007_contract_requires_default_main_tick": True,
                "p0_007_current_worker_brief_queue_ready": current_worker_brief_queue[
                    "ready"
                ],
                "p0_007_current_worker_brief_queue_bound_to_workflow": (
                    current_worker_brief_queue["bound_to_input_workflow"]
                ),
                "p0_007_next_frontier_default_outlet_disabled": (
                    current_worker_brief_queue["next_frontier_default_outlet"] is False
                ),
            }
        )
        tick_payload["validation"] = {
            **validation,
            "passed": validation.get("passed") is True and all(checks.values()),
            "checks": checks,
        }
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
    if worker_ledger_activity_ref:
        tick_payload["adoption_state"] = "runtime_enforced_hot_path_hooked"
        tick_payload["runtime_enforced"] = True
        tick_payload["default_mainline_weld_point"] = {
            "welded_by": "temporal_codex_task_workflow.main_execution_loop_tick_activity",
            "scope": "seed_cortex_temporal_main_execution_loop_tick_activity",
            "worker_dispatch_ledger_activity_bound": True,
        }
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
        "current_worker_brief_queue": current_worker_brief_queue if p0_007_required else {},
        "p0_007_default_main_loop_trigger_bind": tick_payload.get(
            "p0_007_default_main_loop_trigger_bind",
            {},
        ),
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
        "codex_brain_only_default": payload.get("codex_brain_only_default") is True,
        "codex_bulk_worker_default_paused": payload.get("codex_bulk_worker_default_paused") is True,
        "default_token_saving_worker_route": payload.get("default_token_saving_worker_route") is True,
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
async def source_family_adapter_smoke_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_family_adapter_smoke",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_adapter_smoke_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_family_adapter_smoke",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FAMILY_ADAPTER_SMOKE_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_adapter_smoke_runtime_root_guard"),
        }
    phase5_sunset = (
        input_payload.get("source_family_mature_thin_bind_sunset_activity")
        if isinstance(input_payload.get("source_family_mature_thin_bind_sunset_activity"), dict)
        else {}
    )
    base_wave_id = str(
        input_payload.get("adapter_smoke_wave_id")
        or phase5_sunset.get("wave_id")
        or input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-source-family-adapter-smoke-{task_id}"
    )
    wave_id = str(
        input_payload.get("adapter_smoke_wave_id")
        or f"{base_wave_id}-adapter-smoke"
    )
    payload = source_family_adapter_smoke.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        wave_id=wave_id,
        probe_mode=str(input_payload.get("adapter_smoke_probe_mode") or "live"),
        timeout_sec=int(input_payload.get("adapter_smoke_timeout_sec") or 20),
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_family_adapter_smoke_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_adapter_smoke_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_source_family_adapter_smoke_activity_only"
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "source_family_adapter_smoke"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "source_family_adapter_smoke" / "latest.json"
    source_family_adapter_smoke.write_json(latest, payload)
    source_family_adapter_smoke.write_json(temporal_activity_latest, payload)
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "source_family_adapter_smoke",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "SOURCE_FAMILY_ADAPTER_SMOKE_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_adapter_smoke_activity",
        "adapter_smoke_validation_passed": passed,
        "source_family_adapter_smoke_latest_ref": str(latest),
        "source_family_adapter_smoke_temporal_activity_latest_ref": str(
            temporal_activity_latest
        ),
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "wave_id": str(payload.get("wave_id") or ""),
        "parent_wave_id": str(payload.get("parent_wave_id") or ""),
        "probe_mode": str(payload.get("probe_mode") or ""),
        "consumed_next_frontier_action": str(payload.get("consumed_next_frontier_action") or ""),
        "candidate_count": payload.get("candidate_count"),
        "passed_candidate_count": payload.get("passed_candidate_count"),
        "next_frontier_ref": str(
            payload.get("output_paths", {}).get("next_frontier_machine_actions_latest")
            or ""
        ),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_family_adapter_smoke_activity_read_model"),
    }


@activity.defn
async def source_family_smoked_candidate_thin_bind_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_family_smoked_candidate_thin_bind",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary(
                "source_family_smoked_candidate_thin_bind_non_seed_cortex_skip"
            ),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_family_smoked_candidate_thin_bind",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary(
                "source_family_smoked_candidate_thin_bind_runtime_root_guard"
            ),
        }
    adapter_smoke = (
        input_payload.get("source_family_adapter_smoke_activity")
        if isinstance(input_payload.get("source_family_adapter_smoke_activity"), dict)
        else {}
    )
    base_wave_id = str(
        input_payload.get("smoked_candidate_thin_bind_wave_id")
        or adapter_smoke.get("wave_id")
        or input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-source-family-smoked-candidate-thin-bind-{task_id}"
    )
    wave_id = str(
        input_payload.get("smoked_candidate_thin_bind_wave_id")
        or f"{base_wave_id}-smoked-candidate-thin-bind"
    )
    payload = source_family_smoked_candidate_thin_bind.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        wave_id=wave_id,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_family_smoked_candidate_thin_bind_activity",
        "invoked": True,
        "runtime_enforced_scope": (
            "seed_cortex_temporal_source_family_smoked_candidate_thin_bind_activity"
        ),
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_source_family_smoked_candidate_thin_bind_activity_only"
    )
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "source_family_smoked_candidate_thin_bind"
        / "temporal_activity_latest.json"
    )
    latest = runtime_root / "state" / "source_family_smoked_candidate_thin_bind" / "latest.json"
    source_family_smoked_candidate_thin_bind.write_json(latest, payload)
    source_family_smoked_candidate_thin_bind.write_json(temporal_activity_latest, payload)
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "source_family_smoked_candidate_thin_bind",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": (
            "seed_cortex_temporal_source_family_smoked_candidate_thin_bind_activity"
        ),
        "thin_bind_validation_passed": passed,
        "source_family_smoked_candidate_thin_bind_latest_ref": str(latest),
        "source_family_smoked_candidate_thin_bind_temporal_activity_latest_ref": str(
            temporal_activity_latest
        ),
        "bindings_ref": str(payload.get("output_paths", {}).get("bindings_latest") or ""),
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "wave_id": str(payload.get("wave_id") or ""),
        "parent_wave_id": str(payload.get("parent_wave_id") or ""),
        "consumed_next_frontier_action": str(payload.get("consumed_next_frontier_action") or ""),
        "binding_count": payload.get("binding_count"),
        "ready_binding_count": payload.get("ready_binding_count"),
        "next_frontier_ref": str(
            payload.get("output_paths", {}).get("next_frontier_machine_actions_latest")
            or ""
        ),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary(
            "source_family_smoked_candidate_thin_bind_activity_read_model"
        ),
    }


@activity.defn
async def source_family_adapter_value_eval_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    route_profile = str(input_payload.get("route_profile") or "").strip()
    if not is_seed_cortex_s_payload({"route_profile": route_profile, "task_id": task_id}):
        return {
            "activity": "source_family_adapter_value_eval",
            "status": "skipped_non_seed_cortex_route",
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_adapter_value_eval_non_seed_cortex_skip"),
        }
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "source_family_adapter_value_eval",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_SOURCE_FAMILY_ADAPTER_VALUE_EVAL_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("source_family_adapter_value_eval_runtime_root_guard"),
        }
    thin_bind = (
        input_payload.get("source_family_smoked_candidate_thin_bind_activity")
        if isinstance(input_payload.get("source_family_smoked_candidate_thin_bind_activity"), dict)
        else {}
    )
    base_wave_id = str(
        input_payload.get("adapter_value_eval_wave_id")
        or thin_bind.get("wave_id")
        or input_payload.get("wave_id")
        or input_payload.get("workflow_id")
        or f"temporal-source-family-adapter-value-eval-{task_id}"
    )
    wave_id = str(
        input_payload.get("adapter_value_eval_wave_id")
        or f"{base_wave_id}-adapter-value-eval"
    )
    payload = source_family_adapter_value_eval.build(
        runtime_root=runtime_root,
        repo_root=_REPO_ROOT,
        anchor_package_root=pathlib.Path(
            str(input_payload.get("anchor_package_root") or r"C:\Users\xx363\Desktop\新系统")
        ),
        wave_id=wave_id,
        write=True,
    )
    payload["runtime_entrypoint_invocation"] = {
        "invoked_by": "temporal_codex_task_workflow.source_family_adapter_value_eval_activity",
        "invoked": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_adapter_value_eval_activity",
        "runtime_enforced": True,
        "not_execution_controller": True,
        "not_completion_gate": True,
    }
    payload["runtime_entrypoint_adoption_state"] = (
        "runtime_enforced_for_temporal_source_family_adapter_value_eval_activity_only"
    )
    if payload.get("validation", {}).get("passed") is True:
        from xinao_seedlab.application.seed_cortex import build_default_service

        service = build_default_service(runtime_root, repo_root=_REPO_ROOT)
        gateway = service.capability_gateway_snapshot(write_runtime=True)
        refresh = source_family_adapter_value_eval.refresh_capability_gateway_snapshot(
            runtime_root=runtime_root,
            wave_id=f"{wave_id}-gateway-refresh",
            parent_payload=payload,
            gateway=gateway,
            write=True,
        )
        payload["capability_gateway_snapshot"] = refresh["capability_gateway_snapshot"]
        payload["gateway_refresh"] = refresh["gateway_refresh"]
        payload["next_frontier_machine_actions"] = refresh["next_frontier_machine_actions"]
        payload["output_paths"].update(refresh["output_paths"])
    temporal_activity_latest = (
        runtime_root
        / "state"
        / "source_family_adapter_value_eval"
        / "temporal_activity_latest.json"
    )
    temporal_activity_wave = (
        runtime_root
        / "state"
        / "source_family_adapter_value_eval"
        / "temporal_activity"
        / "waves"
        / f"{wave_id}.json"
    )
    latest = runtime_root / "state" / "source_family_adapter_value_eval" / "latest.json"
    source_family_adapter_value_eval.write_json(latest, payload)
    source_family_adapter_value_eval.write_json(temporal_activity_latest, payload)
    source_family_adapter_value_eval.write_json(temporal_activity_wave, payload)
    passed = payload.get("validation", {}).get("passed") is True
    return {
        "activity": "source_family_adapter_value_eval",
        "status": "activity_gate_checked" if passed else "activity_blocked",
        "named_blocker": "" if passed else "SOURCE_FAMILY_ADAPTER_VALUE_EVAL_VALIDATION_FAILED",
        "runtime_entrypoint_invocation": payload["runtime_entrypoint_invocation"],
        "runtime_entrypoint_adoption_state": payload["runtime_entrypoint_adoption_state"],
        "runtime_enforced": True,
        "runtime_enforced_scope": "seed_cortex_temporal_source_family_adapter_value_eval_activity",
        "value_eval_validation_passed": passed,
        "source_family_adapter_value_eval_latest_ref": str(latest),
        "source_family_adapter_value_eval_temporal_activity_latest_ref": str(
            temporal_activity_latest
        ),
        "source_family_adapter_value_eval_temporal_activity_wave_ref": str(
            temporal_activity_wave
        ),
        "decisions_ref": str(payload.get("output_paths", {}).get("decisions_latest") or ""),
        "capability_gateway_candidates_ref": str(
            payload.get("output_paths", {}).get("capability_gateway_candidates_latest") or ""
        ),
        "capability_gateway_latest_ref": str(
            payload.get("output_paths", {}).get("capability_gateway_latest") or ""
        ),
        "gateway_refresh_ref": str(
            payload.get("output_paths", {}).get("gateway_refresh_latest") or ""
        ),
        "gateway_refresh_validation_passed": (
            payload.get("gateway_refresh", {}).get("validation", {}).get("passed") is True
        )
        if isinstance(payload.get("gateway_refresh"), dict)
        else False,
        "readback_zh_ref": str(payload.get("output_paths", {}).get("readback_zh") or ""),
        "wave_id": str(payload.get("wave_id") or ""),
        "parent_wave_id": str(payload.get("parent_wave_id") or ""),
        "consumed_next_frontier_action": str(payload.get("consumed_next_frontier_action") or ""),
        "decision_count": payload.get("decision_count"),
        "gateway_candidate_count": payload.get("gateway_candidate_count"),
        "next_frontier_ref": str(
            payload.get("output_paths", {}).get("next_frontier_machine_actions_latest")
            or ""
        ),
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "authority_boundary": authority_boundary("source_family_adapter_value_eval_activity_read_model"),
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
    allocation_plan_activity_ref = (
        input_payload.get("allocation_plan_activity")
        if isinstance(input_payload.get("allocation_plan_activity"), dict)
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
        bind_provider_worker_pool=bool(input_payload.get("bind_provider_worker_pool")),
        phase1_target_width=int(input_payload.get("phase1_target_width") or 0),
        phase1_max_parallel_workers=int(
            input_payload.get("phase1_max_parallel_workers") or 12
        ),
        phase1_require_external_draft=not bool(
            input_payload.get("allow_local_stub_acceptance")
        ),
        allocation_plan_activity=allocation_plan_activity_ref,
        dynamic_width_decision=(
            input_payload.get("dynamic_width_decision")
            if isinstance(input_payload.get("dynamic_width_decision"), dict)
            else None
        ),
        work_package=(
            input_payload.get("work_package")
            if isinstance(input_payload.get("work_package"), dict)
            else None
        ),
        workflow_id=str(input_payload.get("workflow_id") or ""),
        workflow_run_id=str(input_payload.get("workflow_run_id") or ""),
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
    main_tick_p0_007 = (
        main_loop_tick_activity_ref.get(P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID)
        if isinstance(main_loop_tick_activity_ref, dict)
        and isinstance(main_loop_tick_activity_ref.get(P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID), dict)
        else {}
    )
    worker_ledger_latest = read_json(
        runtime_root / "state" / "worker_dispatch_ledger" / "latest.json",
        {},
    )
    worker_ledger_activity_p0_008 = (
        worker_ledger_activity_ref.get(P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID)
        if isinstance(worker_ledger_activity_ref, dict)
        and isinstance(
            worker_ledger_activity_ref.get(P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID),
            dict,
        )
        else {}
    )
    worker_ledger_latest_p0_008 = (
        worker_ledger_latest.get(P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID)
        if isinstance(worker_ledger_latest.get(P0_008_WORKER_DISPATCH_REAL_RECEIPT_TASK_ID), dict)
        else {}
    )
    p0_008_worker_dispatch_real_receipt_ready = (
        worker_ledger_activity_ref.get("worker_dispatch_real_receipt_ready") is True
        or worker_ledger_activity_p0_008.get("worker_dispatch_real_receipt_ready") is True
        or worker_ledger_latest.get("worker_dispatch_real_receipt_ready") is True
        or worker_ledger_latest_p0_008.get("worker_dispatch_real_receipt_ready") is True
    )
    if main_tick_p0_007:
        main_tick_consumed_worker_brief_queue = (
            main_tick_p0_007.get(
                "current_worker_brief_queue_consumed_by_temporal_main_tick"
            )
            is True
        )
        p0_007_task_scoped_runtime_rebind_ready = (
            main_tick_consumed_worker_brief_queue
            and p0_008_worker_dispatch_real_receipt_ready
        )
        if p0_007_task_scoped_runtime_rebind_ready:
            trigger_payload["status"] = "default_main_loop_trigger_task_scoped_runtime_enforced"
            trigger_payload["adoption_state"] = (
                default_main_loop_trigger_candidate.RUNTIME_ENFORCED_ADOPTION_STATE
            )
            trigger_payload["runtime_enforced"] = True
            trigger_payload["runtime_enforced_scope"] = (
                default_main_loop_trigger_candidate.TASK_SCOPED_RUNTIME_SCOPE
            )
            trigger_payload["trigger_installed"] = True
            adoption_boundary = (
                dict(trigger_payload.get("adoption_state_boundary"))
                if isinstance(trigger_payload.get("adoption_state_boundary"), dict)
                else {}
            )
            adoption_boundary.update(
                {
                    "adoption_state": default_main_loop_trigger_candidate.RUNTIME_ENFORCED_ADOPTION_STATE,
                    "scope": default_main_loop_trigger_candidate.TASK_SCOPED_TRIGGER_SCOPE,
                    "state_is_scoped_candidate": False,
                    "task_scoped_runtime_enforcement": True,
                    "not_global_runtime_enforcement": True,
                    "root_loop_every_wave_enforced": False,
                    "runtime_enforced": True,
                    "runtime_enforced_scope": (
                        default_main_loop_trigger_candidate.TASK_SCOPED_RUNTIME_SCOPE
                    ),
                    "trigger_installed": True,
                    "missing_to_runtime_enforced_cn": "",
                }
            )
            trigger_payload["adoption_state_boundary"] = adoption_boundary
            trigger_payload["p0_007_canonical_rebind"] = {
                "status": "p0_007_task_scoped_runtime_rebound",
                "main_tick_consumed_worker_brief_queue": main_tick_consumed_worker_brief_queue,
                "p0_008_worker_dispatch_real_receipt_ready": (
                    p0_008_worker_dispatch_real_receipt_ready
                ),
                "scope": default_main_loop_trigger_candidate.TASK_SCOPED_TRIGGER_SCOPE,
                "runtime_enforced_scope": (
                    default_main_loop_trigger_candidate.TASK_SCOPED_RUNTIME_SCOPE
                ),
                "global_default_runtime_enforcement_claimed": False,
                "root_loop_every_wave_enforced": False,
                "completion_claim_allowed": False,
                "not_execution_controller": True,
            }
        trigger_payload[P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID] = {
            "task_id": P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID,
            "status": "default_main_loop_trigger_runtime_enforced"
            if trigger_payload.get("runtime_enforced") is True
            else "default_main_loop_trigger_activity_ran_but_service_not_runtime_enforced",
            "default_main_loop_trigger_runtime_enforced": trigger_payload.get(
                "runtime_enforced"
            )
            is True,
            "trigger_installed": trigger_payload.get("trigger_installed") is True,
            "root_loop_every_wave_enforced_by_workflow_branch": True,
            "current_worker_brief_queue_consumed_by_temporal_main_tick": (
                main_tick_consumed_worker_brief_queue
            ),
            "current_worker_brief_queue_ref": str(
                main_tick_p0_007.get("current_worker_brief_queue_ref") or ""
            ),
            "p0_008_worker_dispatch_real_receipt_ready": (
                p0_008_worker_dispatch_real_receipt_ready
            ),
            "task_scoped_runtime_rebind_ready": p0_007_task_scoped_runtime_rebind_ready,
            "main_execution_loop_tick_activity_ref": main_loop_tick_activity_ref,
            "durable_parallel_wave_packet_activity_ref": durable_wave_packet_activity_ref,
            "temporal_activity_required": True,
            "accepted_for_next_frontier_default_outlet": False,
            "next_required_task": "p0_008_worker_dispatch_real_receipt",
            "p0_008_receipt_gap_allowed_as_next_blocker": True,
            "completion_claim_allowed": False,
            "not_execution_controller": True,
        }
        validation = (
            dict(trigger_payload.get("validation"))
            if isinstance(trigger_payload.get("validation"), dict)
            else {}
        )
        checks = (
            dict(validation.get("checks"))
            if isinstance(validation.get("checks"), dict)
            else {}
        )
        checks.update(
            {
                "p0_007_temporal_main_tick_consumed_worker_brief_queue": (
                    trigger_payload[P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID][
                        "current_worker_brief_queue_consumed_by_temporal_main_tick"
                    ]
                ),
                "p0_007_default_trigger_activity_runtime_enforced": (
                    trigger_payload[P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID][
                        "default_main_loop_trigger_runtime_enforced"
                    ]
                ),
                "p0_007_default_trigger_installed": (
                    trigger_payload[P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID][
                        "trigger_installed"
                    ]
                ),
                "p0_007_canonical_rebind_has_p0_008_real_receipt_ready": (
                    p0_008_worker_dispatch_real_receipt_ready
                ),
                "p0_007_task_scoped_runtime_rebind_ready": (
                    p0_007_task_scoped_runtime_rebind_ready
                ),
            }
        )
        trigger_payload["validation"] = {
            **validation,
            "passed": validation.get("passed") is True and all(checks.values()),
            "checks": checks,
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
        P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID: trigger_payload.get(
            P0_007_DEFAULT_MAIN_LOOP_TRIGGER_TASK_ID,
            {},
        ),
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


def worker_turn_execution_requested(input_payload: dict[str, Any]) -> bool:
    if "execute_worker_turn" in input_payload:
        return input_payload.get("execute_worker_turn") is True
    return input_payload.get("execute_codex_worker") is True


def worker_turn_switch_alias_payload(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "execute_worker_turn": worker_turn_execution_requested(input_payload),
        "execute_codex_worker_legacy_alias": input_payload.get("execute_codex_worker") is True,
        "legacy_execute_codex_worker_alias_consumed": (
            "execute_worker_turn" not in input_payload
            and input_payload.get("execute_codex_worker") is True
        ),
        "switch_rename": "execute_worker_turn replaces execute_codex_worker; activity name is legacy carrier only",
    }


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
    mature_bind_task = (
        phase_execution.get("mature_bind_task")
        if isinstance(phase_execution.get("mature_bind_task"), dict)
        else signal_payload.get("mature_bind_task")
        if isinstance(signal_payload.get("mature_bind_task"), dict)
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
    provider_routing_mode = str(
        phase_execution.get("provider_routing_mode")
        or signal_payload.get("provider_routing_mode")
        or input_payload.get("provider_routing_mode")
        or ""
    ).strip()
    provider_cost_routing_policy_ref = str(
        phase_execution.get("provider_cost_routing_policy_ref")
        or signal_payload.get("provider_cost_routing_policy_ref")
        or input_payload.get("provider_cost_routing_policy_ref")
        or ""
    ).strip()
    default_token_saving_worker_route = (
        phase_execution.get("default_token_saving_worker_route") is True
        or signal_payload.get("default_token_saving_worker_route") is True
        or input_payload.get("default_token_saving_worker_route") is True
    )
    tool_bearing_patch_executor_enabled = (
        phase_execution.get("tool_bearing_patch_executor_enabled") is True
        or signal_payload.get("tool_bearing_patch_executor_enabled") is True
        or signal_payload.get("cheap_worker_repo_mutation_allowed") is True
        or signal_payload.get("allow_cheap_worker_repo_mutation") is True
        or input_payload.get("tool_bearing_patch_executor_enabled") is True
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
    worker_turn_explicitly_disabled = (
        "execute_worker_turn" in signal_payload
        and signal_payload.get("execute_worker_turn") is not True
    )
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
                f"worker_kind={worker_kind}\n"
                f"phase_scope={phase_scope}\n"
                f"provider_routing_mode={provider_routing_mode or 'runtime_default'}\n"
                f"default_token_saving_worker_route={default_token_saving_worker_route}\n"
                f"provider_cost_routing_policy_ref={provider_cost_routing_policy_ref}\n"
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
                + (
                    "Cheap-worker repo mutation is enabled through the local patch executor: "
                    "return one unified diff fenced as ```diff, and make sure the requested "
                    "verification commands are executable by the local verifier. Do not claim "
                    "the repo changed unless the executor evidence says applied_verified.\n"
                    if tool_bearing_patch_executor_enabled
                    else ""
                )
                +
                "If the phase boundary is not ready, leave a named blocker and next machine "
                "action; do not create an external reviewer gate yourself.\n"
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
        "execute_worker_turn": not assignment_scope_blocked
        and not worker_turn_explicitly_disabled,
        "execute_codex_worker": not assignment_scope_blocked
        and not worker_turn_explicitly_disabled,
        "execute_codex_worker_legacy_alias": not worker_turn_explicitly_disabled,
        "worker_turn_explicitly_disabled": worker_turn_explicitly_disabled,
        "codex_worker_task_id": worker_task_id,
        "codex_worker_prompt": prompt,
        "codex_worker_expected_marker": str(signal_payload.get("codex_worker_expected_marker") or TASK_BOUND_CODEX_WORKER_MARKER),
        "codex_worker_timeout_sec": timeout_sec,
        "codex_worker_activity_timeout_sec": activity_timeout_sec,
        "worker_kind": worker_kind,
        "phase_scope": phase_scope,
        "work_package": work_package,
        "verification": verification,
        "phase_execution": {
            **phase_execution,
            **({"mature_bind_task": mature_bind_task} if mature_bind_task else {}),
        },
        "mature_bind_task": mature_bind_task,
        "assignment_missing_fields": assignment_missing_fields,
        "assignment_invalid_fields": assignment_invalid_fields,
        "assignment_scope_blocked": assignment_scope_blocked,
        "named_blocker": assignment_blocker,
        "worker_assignment_ref": assignment_ref,
        "repo_root": repo_root,
        "workspace_hint": repo_root,
        "provider_routing_mode": provider_routing_mode or "codex_brain_only",
        "provider_cost_routing_policy_ref": provider_cost_routing_policy_ref
        or str(
            pathlib.Path(str(input_payload.get("runtime_root") or DEFAULT_RUNTIME))
            / "state"
            / "provider_cost_routing_policy"
            / "latest.json"
        ),
        "default_token_saving_worker_route": default_token_saving_worker_route,
        "tool_bearing_patch_executor_enabled": tool_bearing_patch_executor_enabled,
        "cheap_worker_repo_mutation_allowed": tool_bearing_patch_executor_enabled,
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
        "human_egress_route": str(signal_payload.get("human_egress_route") or input_payload.get("human_egress_route") or ""),
        "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
        "segment_boundary_headless": True,
        "continue_same_task_signal_worker_required": True,
        "implementation_worker_required": bool(not assignment_scope_blocked and worker_kind == "implementation_worker"),
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


def assignment_dag_node_provider_route_key(next_node_id: str, next_node: dict[str, Any]) -> str:
    lanes = next_node.get("lanes") if isinstance(next_node.get("lanes"), list) else []
    has_draft_lane = any(
        isinstance(lane, dict) and str(lane.get("mode") or "draft") == "draft"
        for lane in lanes
    )
    if has_draft_lane:
        return "assignment_dag_workerpool"
    text_parts = [
        next_node_id,
        str(next_node.get("objective") or ""),
        str(next_node.get("lane_kind") or ""),
        str(next_node.get("provider_route_key") or ""),
    ]
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        text_parts.extend(
            [
                str(lane.get("lane_id") or ""),
                str(lane.get("mode") or ""),
                str(lane.get("lane_kind") or ""),
                str(lane.get("provider_role") or ""),
                str(lane.get("objective") or ""),
            ]
        )
    haystack = " ".join(text_parts).lower()
    if any(token in haystack for token in ASSIGNMENT_CONTROL_PLANE_REPAIR_TOKENS):
        return STRUCTURAL_BLOCKER_REPAIR_ROUTE_KEY
    return "assignment_dag_workerpool"


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
    completed_worker = (
        input_payload.get("segment_pass_next_worker")
        if isinstance(input_payload.get("segment_pass_next_worker"), dict)
        else {}
    )
    completed_worker_signal = (
        completed_worker.get("continue_same_task_signal")
        if isinstance(completed_worker.get("continue_same_task_signal"), dict)
        else {}
    )
    completed_worker_node = str(
        completed_worker_signal.get("assignment_dag_node_id")
        or completed_worker_signal.get("dag_next_ready_node_id")
        or ""
    )
    same_node_worker_completed = (
        completed_worker_node == next_node_id
        and worker_turn_evidence_ready(completed_worker)
    )
    if (
        previously_dispatched_node
        and previously_dispatched_node == next_node_id
        and not same_node_worker_completed
    ):
        return {}
    phase_execution = dict(assignment.get("phase_execution") if isinstance(assignment.get("phase_execution"), dict) else {})
    node_files = next_node.get("files") if isinstance(next_node.get("files"), list) else []
    node_acceptance = next_node.get("acceptance") if isinstance(next_node.get("acceptance"), list) else []
    provider_route_key = assignment_dag_node_provider_route_key(next_node_id, next_node)
    structural_blocker_repair = provider_route_key == STRUCTURAL_BLOCKER_REPAIR_ROUTE_KEY
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
        "worker_kind": "control_plane_repair_worker" if structural_blocker_repair else "implementation_worker",
        "phase_scope": str(phase_execution.get("phase_scope") or assignment.get("dag_scope") or "assignment_dag_auto_continue"),
        "provider_route_key": provider_route_key,
        "structural_blocker_repair": structural_blocker_repair,
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
        "execute_worker_turn": True,
        "execute_codex_worker": True,
        "execute_codex_worker_legacy_alias": True,
        "provider_route_key": provider_route_key,
        "structural_blocker_repair": structural_blocker_repair,
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
    next_worker = input_payload.get("segment_pass_next_worker") if isinstance(input_payload.get("segment_pass_next_worker"), dict) else {}
    next_worker_ok = worker_turn_evidence_ready(next_worker)
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
                "assignment_driven_implementation_worker_dispatched": implementation_worker_ok,
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
    codex_blocked = (
        codex_acceptance_unavailable(runtime_root)
        or codex_acceptance_blocked(next_worker)
        or (
            not next_worker_ok
            and str(next_worker.get("activity") or "") == "codex_worker_turn"
        )
    )
    evidence_refs = collect_next_segment_dispatch_evidence(runtime_root, task_id)
    if codex_blocked and evidence_refs:
        brain_dispatch = await invoke_v4pro_next_segment_brain_dispatch(
            runtime_root=runtime_root,
            task_id=task_id,
            input_payload=input_payload,
        )
        prepared = (
            brain_dispatch.get("prepared_signal")
            if isinstance(brain_dispatch.get("prepared_signal"), dict)
            else {}
        )
        if brain_dispatch.get("continuation_allowed_without_codex_acceptance") and prepared:
            output = {
                **base,
                "status": "v4pro_next_segment_dispatch_prepared",
                "continuation_dispatched": False,
                "external_continuation_worker_dispatched": False,
                "legacy_continuation_worker_allowed": False,
                "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
                "workflow_internal_timer_scheduled": False,
                "workflow_kept_open_by_durable_timer": False,
                "partial_frontier_open": True,
                "workflow_waiting_signal": False,
                "workflow_signal_name": "continue_same_task",
                "one_segment_does_not_wait_for_user": True,
                "continuation_allowed_without_codex_acceptance": True,
                "execution_routing_unchanged": True,
                "brain_dispatch_provider": V4PRO_BRAIN_DISPATCH_PROVIDER,
                "codex_acceptance_substituted_by": V4PRO_BRAIN_DISPATCH_PROVIDER,
                "command_surface": (
                    "Temporal workflow V4 Pro brain dispatch prepared next segment; "
                    "execution worker routing unchanged."
                ),
                "task_id": task_id,
                "worker_task_id": "",
                "next_required_activity": (
                    "Workflow must enqueue the V4 Pro prepared auto_continue_same_task_signal "
                    "without waiting for Codex acceptance."
                ),
                "named_blocker": "",
                "v4pro_brain_dispatch": brain_dispatch,
                "assignment_dag_auto_continue": True,
                "auto_continue_same_workflow": True,
                "auto_continue_same_task_signal": prepared,
                "auto_continue_next_ready_node_id": str(prepared.get("assignment_dag_node_id") or ""),
                **auto_signal_fields,
            }
            write_json(
                runtime_root
                / "state"
                / "temporal_codex_task_workflow"
                / "continuation_dispatch"
                / f"{task_id}.json",
                output,
            )
            return output
        if brain_dispatch.get("continuation_allowed_without_codex_acceptance"):
            output = {
                **base,
                "status": "v4pro_brain_dispatch_continuation_allowed",
                "continuation_dispatched": False,
                "external_continuation_worker_dispatched": False,
                "legacy_continuation_worker_allowed": False,
                "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
                "workflow_internal_timer_scheduled": False,
                "workflow_kept_open_by_durable_timer": False,
                "partial_frontier_open": True,
                "workflow_waiting_signal": False,
                "workflow_signal_name": "continue_same_task",
                "one_segment_does_not_wait_for_user": True,
                "continuation_allowed_without_codex_acceptance": True,
                "execution_routing_unchanged": True,
                "brain_dispatch_provider": V4PRO_BRAIN_DISPATCH_PROVIDER,
                "codex_acceptance_substituted_by": V4PRO_BRAIN_DISPATCH_PROVIDER,
                "command_surface": (
                    "Temporal workflow continues next segment via V4 Pro brain dispatch; "
                    "Codex acceptance deferred."
                ),
                "task_id": task_id,
                "worker_task_id": "",
                "next_required_activity": (
                    "Continue same-task workflow; Codex acceptance unavailable but "
                    "V4 Pro brain dispatch allowed continuation."
                ),
                "named_blocker": "",
                "v4pro_brain_dispatch": brain_dispatch,
                **auto_signal_fields,
            }
            write_json(
                runtime_root
                / "state"
                / "temporal_codex_task_workflow"
                / "continuation_dispatch"
                / f"{task_id}.json",
                output,
            )
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
        "command_surface": "Temporal workflow stays open for same-task continue_same_task signal; no .continuation.N worker",
        "task_id": task_id,
        "worker_task_id": "",
        "partial_keepalive_sleep_seconds": int(input_payload.get("partial_keepalive_sleep_seconds") or PARTIAL_KEEPALIVE_SLEEP_SECONDS),
        "next_required_activity": "Dispatch or wait for a same-task continue_same_task implementation worker.",
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


def _canonical_worker_dispatch_ledger_for_wave(
    runtime_root: pathlib.Path,
    wave_id: str,
) -> dict[str, Any]:
    latest = runtime_root / "state" / "worker_dispatch_ledger" / "latest.json"
    payload = read_json(latest, {})
    if not payload:
        return {}
    payload_wave_id = str(payload.get("wave_id") or "")
    if wave_id and payload_wave_id != wave_id:
        return {}
    return payload


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


def _drain_after_current_wave_request(input_payload: dict[str, Any]) -> dict[str, Any]:
    request = input_payload.get("drain_after_current_wave_request")
    return request if isinstance(request, dict) else {}


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
    prepared_signal_source = "partial_continuation_dispatch"
    if not prepared_signal:
        prepared_signal = assignment_dag_auto_continue_signal(runtime_root, task_id, input_payload)
        if prepared_signal:
            prepared_signal_source = "global_worker_assignment_next_ready"
    drain_request = _drain_after_current_wave_request(input_payload)
    drain_requested = bool(drain_request)
    current_wave_index = int(input_payload.get("wave_index") or 1)
    next_wave_index = current_wave_index + 1
    current_wave_id = str(input_payload.get("wave_id") or "")
    next_wave_id = temporal_hot_path_wave_id(
        input_payload,
        next_wave_index,
        prepared_signal,
    )
    canonical_worker_ledger = _canonical_worker_dispatch_ledger_for_wave(
        runtime_root,
        current_wave_id,
    )
    activity_ledger_succeeded_count = _ledger_succeeded_count_from_activity(worker_ledger)
    canonical_ledger_succeeded_count = _ledger_succeeded_count_from_activity(
        canonical_worker_ledger
    )
    if canonical_ledger_succeeded_count > activity_ledger_succeeded_count:
        ledger_for_dispatch = canonical_worker_ledger
        ledger_source_kind = "canonical_worker_dispatch_ledger_latest"
    else:
        ledger_for_dispatch = worker_ledger
        ledger_source_kind = "worker_dispatch_ledger_activity"
    ledger_succeeded_count = _ledger_succeeded_count_from_activity(ledger_for_dispatch)
    ledger_runtime_enforced = _ledger_runtime_enforced_from_activity(ledger_for_dispatch)
    should_dispatch = (
        not drain_requested
        and
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
        "auto_dispatch_drained_after_current_wave"
        if drain_requested
        else
        "auto_dispatch_ingress_enqueued"
        if should_dispatch
        else "auto_dispatch_waiting_assignment_signal"
        if ledger_runtime_enforced and ledger_succeeded_count > 0
        else "auto_dispatch_blocked_waiting_worker_ledger_succeeded"
    )
    named_blocker = ""
    if drain_requested:
        named_blocker = "USER_REQUESTED_DRAIN_AFTER_CURRENT_WAVE"
    elif not ledger_runtime_enforced:
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
        "drain_after_current_wave_requested": drain_requested,
        "drain_after_current_wave_request": drain_request,
        "worker_dispatch_ledger_runtime_enforced": ledger_runtime_enforced,
        "worker_dispatch_ledger_succeeded_count": ledger_succeeded_count,
        "worker_dispatch_ledger_source_kind": ledger_source_kind,
        "worker_dispatch_ledger_activity_succeeded_count": activity_ledger_succeeded_count,
        "canonical_worker_dispatch_ledger_succeeded_count": canonical_ledger_succeeded_count,
        "canonical_worker_dispatch_ledger_wave_id": str(
            canonical_worker_ledger.get("wave_id") or ""
        ),
        "canonical_worker_dispatch_ledger_ref": str(
            runtime_root / "state" / "worker_dispatch_ledger" / "latest.json"
        )
        if canonical_worker_ledger
        else "",
        "worker_dispatch_ledger_activity_ref": worker_ledger,
        "worker_dispatch_ledger_dispatch_ref": ledger_for_dispatch,
        "main_execution_loop_tick_activity_ref": input_payload.get("main_execution_loop_tick_activity")
        if isinstance(input_payload.get("main_execution_loop_tick_activity"), dict)
        else {},
        "partial_continuation_dispatch_ref": continuation,
        "prepared_signal_source": prepared_signal_source if prepared_signal else "",
        "global_assignment_signal_fallback_used": (
            prepared_signal_source == "global_worker_assignment_next_ready"
        ),
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
                "canonical_ledger_wave_matches_current_wave": (
                    bool(canonical_worker_ledger)
                    and str(canonical_worker_ledger.get("wave_id") or "") == current_wave_id
                ),
                "canonical_ledger_preferred_after_default_trigger": (
                    ledger_source_kind == "canonical_worker_dispatch_ledger_latest"
                ),
                "prepared_continue_signal_present": bool(prepared_signal),
                "drain_after_current_wave_requested": drain_requested,
                "auto_dispatch_suppressed_by_drain_request": (
                    drain_requested and not should_dispatch
                ),
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
async def next_frontier_continuation_supervisor_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(str(input_payload.get("runtime_root") or ""))
    task_id = str(input_payload.get("task_id") or SEED_CORTEX_WORK_ID)
    if not seed_cortex_runtime_root_allowed(runtime_root):
        return {
            "activity": "next_frontier_continuation_supervisor",
            "status": "activity_blocked",
            "named_blocker": "CODEX_S_NEXT_FRONTIER_SUPERVISOR_REJECTED_NON_S_RUNTIME_ROOT",
            "runtime_root": str(runtime_root),
            "required_runtime_root": str(SEED_CORTEX_RUNTIME_ROOT),
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("next_frontier_continuation_supervisor_runtime_root_guard"),
        }
    payload = next_frontier_continuation_supervisor.supervise_latest_next_frontier(
        runtime_root=runtime_root,
        source_kind="temporal_codex_task_workflow.next_frontier_continuation_supervisor_activity",
        workflow_id=str(input_payload.get("workflow_id") or ""),
        workflow_run_id=str(input_payload.get("workflow_run_id") or ""),
        task_queue=str(input_payload.get("task_queue") or DEFAULT_TASK_QUEUE),
        write=True,
    )
    payload.update(
        {
            "activity": "next_frontier_continuation_supervisor",
            "task_id": task_id,
            "workflow_id": str(input_payload.get("workflow_id") or ""),
            "workflow_run_id": str(input_payload.get("workflow_run_id") or ""),
            "task_queue": str(input_payload.get("task_queue") or DEFAULT_TASK_QUEUE),
            "wave_id": str(input_payload.get("wave_id") or payload.get("wave_id") or ""),
            "runtime_enforced_scope": "seed_cortex_temporal_next_frontier_continuation_supervisor_activity",
            "not_source_of_truth": True,
            "not_user_completion": True,
            "not_completion_decision": True,
            "not_execution_controller": True,
            "authority_boundary": authority_boundary("next_frontier_continuation_supervisor_activity_read_model"),
        }
    )
    latest_ref = pathlib.Path(str(payload.get("output_paths", {}).get("latest") or ""))
    readback_ref = pathlib.Path(str(payload.get("output_paths", {}).get("readback_zh") or ""))
    if latest_ref:
        next_frontier_continuation_supervisor.write_json(latest_ref, payload)
    if readback_ref:
        next_frontier_continuation_supervisor.write_text(
            readback_ref,
            next_frontier_continuation_supervisor.render_readback(payload),
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
async def panel_writeback_zh_activity(input_payload: dict[str, Any]) -> dict[str, Any]:
    runtime_root = pathlib.Path(input_payload["runtime_root"])
    task_id = str(input_payload["task_id"])
    decision = input_payload.get("completion_decision") if isinstance(input_payload.get("completion_decision"), dict) else {}
    continuation = input_payload.get("partial_continuation_dispatch") if isinstance(input_payload.get("partial_continuation_dispatch"), dict) else {}
    segment_gate: dict[str, Any] = {}
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
    next_worker_ok = worker_turn_evidence_ready(next_worker)
    next_worker_is_implementation = is_assignment_implementation_worker(next_worker)
    continuation_ok = continuation.get("continuation_dispatched") is True
    internal_timer_ok = continuation.get("workflow_internal_timer_scheduled") is True
    owner_only = not worker_turn_execution_requested(input_payload)
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
    completion_boundary = "Temporal workflow + worker ledger + ArtifactAcceptanceQueue"
    if continuation_ok and next_worker_ok:
        if next_worker_is_implementation:
            next_line = f"同 workflow 已派 WORKER_ASSIGNMENT 驱动的 implementation worker：{next_worker.get('worker_task_id')}；JSONL 已写入，仍保持 partial。"
        else:
            next_line = f"同 workflow 已派 bounded worker：{next_worker.get('worker_task_id')}；JSONL 已写入，仍保持 partial。"
        blocked = "卡在哪：无停机 blocker；仍需后续 ledger/AAQ/completion claim 对齐。"
    elif continuation_ok:
        next_line = "partial 后同 workflow continuation 已登记；不得把 worker PASS 当用户完成。"
    elif internal_timer_ok:
        next_line = "partial 后 workflow 已保持 OPEN，并由 Temporal durable timer/signal wait 承接下一跳；continuation.N 只能 legacy rescue。"
    elif owner_only:
        next_line = "owner_only 已写 current_task_owner；下一步按用户授权再派 worker 或继续 Lobe 眼门验收。"
    elif decision.get("status") == "partial":
        next_line = "partial 但 continuation 未派发；继续读取 completion claim、worker evidence 和 side audit。"
    else:
        next_line = "继续读取 completion claim、worker evidence 和 side audit，再决定下一机器动作。"
    blocked_detail = blocked[len("卡在哪："):] if blocked.startswith("卡在哪：") else blocked
    blocked_line = f"卡在哪：{blocked_detail or '无 blocker。'}"
    segment_audit_status_cn = "段审状态：不参与默认主链"
    next_human_action_cn = ""
    grok_request_ref = ""
    audit_request: dict[str, Any] = {}
    payload = {
        "schema_version": "xinao.codexa_intent_user_visible_status.v1",
        "task_id": task_id,
        "status_cn": summary,
        "user_visible_summary_cn": summary,
        "panel_lines_cn": {
            "status_line_cn": f"一句话状态：默认完成边界 = {completion_boundary}。",
            "blocked_line_cn": blocked_line,
            "next_line_cn": "下一跳：下一机器动作：" + next_line,
            "segment_audit_status_cn": segment_audit_status_cn,
            "next_human_action_cn": next_human_action_cn,
        },
        "segment_audit_status_cn": segment_audit_status_cn,
        "next_human_action_cn": next_human_action_cn,
        "user_must_copy_tui": False,
        "status_line_cn": f"一句话状态：默认完成边界 = {completion_boundary}。",
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
        "segment_pass_must_dispatch_next_bounded_worker": False,
        "assignment_driven_implementation_worker_dispatched": bool(next_worker_ok and is_assignment_implementation_worker(next_worker)),
        "segment_pass_phase_exit_checker_dispatched": False,
        "same_workflow_next_worker_dispatched": bool(next_worker_ok),
        "same_workflow_next_worker_task_id": str(next_worker.get("worker_task_id") or ""),
        "same_workflow_next_worker_jsonl_path": str(next_worker.get("jsonl_path") or ""),
        "segment_pass_next_worker": next_worker,
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
        "backend_only_verdict_allowed": False,
        "tui_self_stop_allowed": False,
        "completion_claim_allowed": False,
        "completion_decision": decision,
        "can_user_use_now": True,
        "can_user_use_scope_cn": "只能从 panel 中文状态看见当前在跑/卡哪和下一机器动作；不代表系统完成或用户完成。",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "authority_boundary": authority_boundary("temporal_panel_writeback_zh_read_model"),
        "updated_at": now(),
    }
    panel_dir = runtime_root / "state" / "codex_a_panel_readback"
    write_json(panel_dir / "tasks" / f"{task_id}.json", payload)
    if input_payload.get("promote_current_task_owner_latest", True) is not False:
        write_json(panel_dir / "latest_intent_status.json", payload)
    if next_worker_ok:
        owner_task = runtime_root / "state" / "current_task_owner" / f"{task_id}.json"
        owner_latest = runtime_root / "state" / "current_task_owner" / "latest.json"
        owner = read_json(owner_task, {})
        if not isinstance(owner, dict) or str(owner.get("task_id") or "") != task_id:
                latest_owner = read_json(owner_latest, {})
                owner = latest_owner if isinstance(latest_owner, dict) and str(latest_owner.get("task_id") or "") == task_id else {"task_id": task_id}
        owner_update = {
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
                "segment_pass_must_dispatch_next_bounded_worker": False,
                "assignment_driven_implementation_worker_dispatched": implementation_worker_ok,
                "segment_pass_phase_exit_checker_dispatched": False,
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


TASK_CONTROL_SIGNAL_SCHEMA = "xinao.codex_s.temporal_task_control_signal.v1"
TASK_CONTROL_VERB_ALIASES = {
    "insert": "insert_front",
    "insert_front": "insert_front",
    "preempt": "insert_front",
    "interrupt": "insert_front",
    "插队": "insert_front",
    "pause": "pause_after_current_wave",
    "pause_after_current_wave": "pause_after_current_wave",
    "暂停": "pause_after_current_wave",
    "drain": "pause_after_current_wave",
    "cancel": "cancel_after_current_wave",
    "cancel_after_current_wave": "cancel_after_current_wave",
    "取消": "cancel_after_current_wave",
    "resume": "resume",
    "恢复": "resume",
    "return": "return_to_mainline",
    "return_to_mainline": "return_to_mainline",
    "return_to_main_tree": "return_to_mainline",
    "回主树": "return_to_mainline",
}
TASK_CONTROL_ROUTING_VERBS = {
    "insert_front",
    "pause_after_current_wave",
    "cancel_after_current_wave",
    "resume",
    "return_to_mainline",
}


def normalize_task_control_signal(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    raw_verb = str(
        source.get("routing_verb")
        or source.get("verb")
        or source.get("action")
        or ""
    ).strip()
    routing_verb = TASK_CONTROL_VERB_ALIASES.get(raw_verb, raw_verb)
    embedded_signal = (
        source.get("continue_same_task_signal")
        if isinstance(source.get("continue_same_task_signal"), dict)
        else source.get("signal_payload")
        if isinstance(source.get("signal_payload"), dict)
        else {}
    )
    if not embedded_signal and str(source.get("assignment_dag_node_id") or ""):
        embedded_signal = {
            key: value
            for key, value in source.items()
            if key
            not in {
                "schema_version",
                "routing_verb",
                "verb",
                "action",
                "control_id",
                "reason",
                "insert_front",
                "signal_payload",
                "continue_same_task_signal",
            }
        }
    if isinstance(embedded_signal, dict) and embedded_signal:
        embedded_signal = dict(embedded_signal)
    routing_insert_front = (
        routing_verb == "insert_front"
        or source.get("insert_front") is True
        or int(source.get("priority") or 0) > 0
    )
    if routing_insert_front and isinstance(embedded_signal, dict) and embedded_signal:
        embedded_signal.setdefault("task_control_insert_front", True)
        embedded_signal.setdefault("preempt_default_bootstrap", True)
        embedded_signal.setdefault("explicit_user_task_control", True)
        embedded_signal.setdefault("task_control_control_id", str(source.get("control_id") or ""))
        embedded_signal.setdefault("task_control_routing_verb", "insert_front")
        embedded_signal.setdefault("completion_claim_allowed", False)
        embedded_signal.setdefault("not_user_completion", True)
    return {
        "schema_version": TASK_CONTROL_SIGNAL_SCHEMA,
        "control_id": str(source.get("control_id") or ""),
        "routing_verb": routing_verb,
        "valid_routing_verb": routing_verb in TASK_CONTROL_ROUTING_VERBS,
        "reason": str(source.get("reason") or ""),
        "priority": int(source.get("priority") or 0),
        "insert_front": routing_insert_front,
        "continue_same_task_signal": dict(embedded_signal)
        if isinstance(embedded_signal, dict)
        else {},
        "cancel_requested": routing_verb == "cancel_after_current_wave",
        "pause_requested": routing_verb == "pause_after_current_wave",
        "resume_requested": routing_verb == "resume",
        "return_to_mainline_requested": routing_verb == "return_to_mainline",
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
    }


def _signal_phase_execution(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("phase_execution") if isinstance(payload.get("phase_execution"), dict) else {}


def _signal_worker_kind(payload: dict[str, Any]) -> str:
    phase_execution = _signal_phase_execution(payload)
    return str(
        phase_execution.get("worker_kind")
        or payload.get("worker_kind")
        or payload.get("phase_worker_kind")
        or ""
    ).strip()


def is_preemptive_continue_same_task_signal(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if (
        payload.get("task_control_insert_front") is True
        or payload.get("preempt_default_bootstrap") is True
        or payload.get("explicit_user_task_control") is True
    ):
        return True
    node_id = str(
        payload.get("assignment_dag_node_id")
        or payload.get("dag_next_ready_node_id")
        or ""
    )
    phase_scope = str(
        _signal_phase_execution(payload).get("phase_scope")
        or payload.get("phase_scope")
        or ""
    )
    if _signal_worker_kind(payload) != "implementation_worker":
        return False
    if node_id.startswith("next-frontier:"):
        return False
    return node_id.startswith("p0_") or phase_scope.startswith("p0_")


@workflow.defn
class TemporalCodexTaskWorkflow:
    def __init__(self) -> None:
        self.continue_same_task_signals: list[dict[str, Any]] = []
        self.drain_after_current_wave_request: dict[str, Any] = {}
        self.task_control_signals: list[dict[str, Any]] = []

    @workflow.signal
    async def continue_same_task(self, payload: dict[str, Any]) -> None:
        self.continue_same_task_signals.append(dict(payload or {}))

    @workflow.signal
    async def drain_after_current_wave(self, payload: dict[str, Any]) -> None:
        self.drain_after_current_wave_request = dict(payload or {})
        if not self.drain_after_current_wave_request:
            self.drain_after_current_wave_request = {"requested": True}

    @workflow.signal
    async def task_control(self, payload: dict[str, Any]) -> None:
        control = normalize_task_control_signal(payload)
        self.task_control_signals.append(control)
        if control["valid_routing_verb"] is not True:
            return
        routing_verb = str(control.get("routing_verb") or "")
        signal_payload = (
            control.get("continue_same_task_signal")
            if isinstance(control.get("continue_same_task_signal"), dict)
            else {}
        )
        if routing_verb == "resume":
            self.drain_after_current_wave_request = {}
            return
        if routing_verb in {"pause_after_current_wave", "cancel_after_current_wave"}:
            self.drain_after_current_wave_request = {
                "requested": True,
                "routing_verb": routing_verb,
                "control_id": control.get("control_id", ""),
                "reason": control.get("reason", ""),
                "cancel_requested": routing_verb == "cancel_after_current_wave",
                "pause_requested": routing_verb == "pause_after_current_wave",
                "completion_claim_allowed": False,
                "not_user_completion": True,
            }
            return
        if not signal_payload:
            return
        if control.get("insert_front") is True:
            self.continue_same_task_signals.insert(0, dict(signal_payload))
        else:
            self.continue_same_task_signals.append(dict(signal_payload))

    def _drain_after_current_wave_requested(self) -> bool:
        return bool(self.drain_after_current_wave_request)

    def _continue_signal_identity(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        if not isinstance(payload, dict):
            return ("", "", "")
        node_id = str(
            payload.get("assignment_dag_node_id")
            or payload.get("dag_next_ready_node_id")
            or (
                payload.get("work_package", {}).get("next_ready_node_id")
                if isinstance(payload.get("work_package"), dict)
                else ""
            )
            or ""
        )
        return (
            node_id,
            str(payload.get("wave_id") or ""),
            str(payload.get("temporal_hot_path_wave_index") or ""),
        )

    def _append_continue_same_task_signal_once(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or not payload:
            return
        identity = self._continue_signal_identity(payload)
        if identity != ("", "", "") and any(
            self._continue_signal_identity(existing) == identity
            for existing in self.continue_same_task_signals
        ):
            return
        self.continue_same_task_signals.append(dict(payload))

    def _has_preemptive_continue_same_task_signal(self) -> bool:
        return any(
            is_preemptive_continue_same_task_signal(item)
            for item in self.continue_same_task_signals
        )

    def _pop_preemptive_continue_same_task_signal(self) -> dict[str, Any]:
        for index, item in enumerate(self.continue_same_task_signals):
            if is_preemptive_continue_same_task_signal(item):
                return self.continue_same_task_signals.pop(index)
        return {}

    def _restore_default_loop_continue_as_new_state(
        self,
        resume_state: dict[str, Any],
    ) -> None:
        pending = resume_state.get("pending_continue_same_task_signals")
        if not isinstance(pending, list):
            return
        for item in pending:
            if isinstance(item, dict):
                self._append_continue_same_task_signal_once(item)

    def _drained_result(
        self,
        result: dict[str, Any],
        *,
        current_wave_id: str,
        drain_point: str,
    ) -> dict[str, Any]:
        drained = dict(result)
        drained.update({
            "workflow_open": False,
            "workflow_completed_partial": False,
            "temporal_workflow_completed": False,
            "user_task_complete": False,
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_completion_decision": True,
            "foreground_watch_drained": True,
            "drain_after_current_wave_requested": True,
            "drain_after_current_wave_request": dict(
                self.drain_after_current_wave_request
            ),
            "task_control_signals": list(self.task_control_signals),
            "drain_after_current_wave_point": drain_point,
            "drain_after_current_wave_id": current_wave_id,
            "mainline_next_hop": "",
            "workflow_state": (
                "cancelled_after_current_wave_by_user_request"
                if self.drain_after_current_wave_request.get("cancel_requested") is True
                else "drained_after_current_wave_by_user_request"
            ),
            "named_blocker": (
                "USER_REQUESTED_CANCEL_AFTER_CURRENT_WAVE"
                if self.drain_after_current_wave_request.get("cancel_requested") is True
                else "USER_REQUESTED_DRAIN_AFTER_CURRENT_WAVE"
            ),
        })
        return drained

    def _enqueue_assignment_dag_auto_continue(self, continuation: dict[str, Any]) -> None:
        if self._drain_after_current_wave_requested():
            return
        if not isinstance(continuation, dict):
            return
        signal_payload = continuation.get("auto_continue_same_task_signal")
        if continuation.get("auto_continue_same_workflow") is True and isinstance(signal_payload, dict) and signal_payload:
            self._append_continue_same_task_signal_once(signal_payload)

    def _enqueue_ledger_auto_dispatch(self, auto_dispatch: dict[str, Any]) -> None:
        if self._drain_after_current_wave_requested():
            return
        if not isinstance(auto_dispatch, dict):
            return
        signal_payload = auto_dispatch.get("auto_continue_same_task_signal")
        if (
            auto_dispatch.get("auto_continue_same_workflow") is True
            and isinstance(signal_payload, dict)
            and signal_payload
        ):
            self._append_continue_same_task_signal_once(signal_payload)

    def _enqueue_next_frontier_continuation(
        self,
        supervisor_result: dict[str, Any],
        auto_dispatch: dict[str, Any],
    ) -> None:
        if self._drain_after_current_wave_requested():
            return
        if (
            temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR)
            and self._has_preemptive_continue_same_task_signal()
        ):
            return
        if isinstance(auto_dispatch, dict) and auto_dispatch.get("auto_continue_same_workflow") is True:
            return
        if not isinstance(supervisor_result, dict):
            return
        signal_payload = supervisor_result.get("auto_continue_same_task_signal")
        if (
            supervisor_result.get("auto_continue_same_workflow") is True
            and isinstance(signal_payload, dict)
            and signal_payload
        ):
            self._append_continue_same_task_signal_once(signal_payload)

    @workflow.run
    async def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        input_payload = {
            **input_payload,
            "workflow_id": workflow.info().workflow_id,
            "workflow_run_id": workflow.info().run_id,
            "task_queue": workflow.info().task_queue,
            "repo_root": str(input_payload.get("repo_root") or _REPO_ROOT),
        }
        default_loop_resume_state = (
            input_payload.get("default_loop_continue_as_new_resume_state")
            if isinstance(input_payload.get("default_loop_continue_as_new_resume_state"), dict)
            else {}
        )
        if default_loop_resume_state:
            self._restore_default_loop_continue_as_new_state(default_loop_resume_state)
        retry = temporal_retry_policy()
        post_continue_status_refresh: dict[str, Any] = {}
        if (
            temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_POST_CONTINUE_STATUS_REFRESH)
            and input_payload.get("disable_post_continue_as_new_status_refresh") is not True
            and (
                bool(default_loop_resume_state)
                or input_payload.get("post_continue_as_new_status_refresh_required") is True
            )
        ):
            post_continue_status_refresh = await workflow.execute_activity(
                post_continue_as_new_status_refresh_activity,
                input_payload,
                start_to_close_timeout=dt.timedelta(minutes=3),
                retry_policy=retry,
            )
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
        preemptive_initial_signal = (
            self._pop_preemptive_continue_same_task_signal()
            if temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTROL_PREEMPTIVE_EXECUTOR)
            else {}
        )
        if preemptive_initial_signal:
            input_payload = continue_same_task_worker_payload(
                input_payload,
                preemptive_initial_signal,
                1,
            )
            input_payload["preemptive_task_control_consumed_before_default_bootstrap"] = True
            input_payload["preemptive_task_control_signal"] = compact_continue_signal_for_rollover(
                preemptive_initial_signal
            )
        task_contract_router_result: dict[str, Any] = {}
        if temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER):
            task_contract_router_result = await workflow.execute_activity(
                task_contract_router_activity,
                input_payload,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            contract_payload = (
                task_contract_router_result.get("task_contract")
                if isinstance(task_contract_router_result.get("task_contract"), dict)
                else {}
            )
            input_payload = task_contract_router.apply_contract_to_payload(
                input_payload,
                contract_payload,
            )
        local_mature_bind_service_result: dict[str, Any] = {}
        local_mature_bind_autopop_result: dict[str, Any] = {}
        if local_mature_bind_service_required(input_payload):
            local_mature_bind_service_result = await invoke_local_mature_bind_service_activity(
                input_payload,
                retry,
            )
            auto_signal = (
                local_mature_bind_service_result.get("auto_continue_same_task_signal")
                if isinstance(
                    local_mature_bind_service_result.get("auto_continue_same_task_signal"),
                    dict,
                )
                else {}
            )
            if local_mature_bind_service_result.get("auto_continue_same_workflow") is True:
                self._append_continue_same_task_signal_once(auto_signal)
            local_mature_bind_autopop_result = await autopop_next_mature_bind_after_local_success(
                input_payload,
                local_mature_bind_service_result,
                retry,
            )
            auto_signal = (
                local_mature_bind_autopop_result.get("auto_continue_same_task_signal")
                if isinstance(
                    local_mature_bind_autopop_result.get("auto_continue_same_task_signal"),
                    dict,
                )
                else {}
            )
            if local_mature_bind_autopop_result.get("auto_continue_same_workflow") is True:
                self._append_continue_same_task_signal_once(auto_signal)
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
        worker_brief_dispatch_plan: dict[str, Any] = {}
        worker_brief_worker_results: list[dict[str, Any]] = []
        if explicit_contract_requires_worker_brief_real_receipts(input_payload):
            worker_brief_dispatch_plan = await workflow.execute_activity(
                worker_brief_dispatch_plan_activity,
                input_payload,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            worker_turn_payloads = (
                worker_brief_dispatch_plan.get("worker_turn_payloads")
                if isinstance(worker_brief_dispatch_plan.get("worker_turn_payloads"), list)
                else []
            )
            if worker_turn_payloads:
                worker_brief_worker_results = list(
                    await asyncio.gather(
                        *[
                            workflow.execute_activity(
                                codex_worker_turn_activity,
                                worker_turn_payload,
                                start_to_close_timeout=codex_worker_activity_timeout(
                                    worker_turn_payload
                                ),
                                retry_policy=retry,
                            )
                            for worker_turn_payload in worker_turn_payloads
                            if isinstance(worker_turn_payload, dict)
                        ]
                    )
                )
                for worker_result in worker_brief_worker_results:
                    if isinstance(worker_result, dict):
                        worker_result.update(
                            {
                                **continuation_authorization_fields(),
                                "worker_dispatch_real_receipt_required": True,
                                "worker_brief_real_receipt_required": True,
                                "synthetic_succeeded_by_driver": False,
                                "phase1_worker_pool_receipt": False,
                            }
                        )
                codex_worker = worker_brief_worker_results[0] if worker_brief_worker_results else {}
            else:
                codex_worker = {
                    "activity": "codex_worker_turn",
                    "status": "activity_blocked",
                    "named_blocker": (
                        worker_brief_dispatch_plan.get("named_blocker")
                        or "WORKER_BRIEF_DISPATCH_PLAN_EMPTY"
                    ),
                    "worker_dispatch_real_receipt_required": True,
                    "worker_brief_real_receipt_required": True,
                    "completion_claim_allowed": False,
                        "not_user_completion": True,
                }
        elif local_mature_bind_service_result:
            codex_worker = local_mature_bind_worker_result(
                input_payload,
                local_mature_bind_service_result,
            )
        else:
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
        decision = claim["completion_decision"]
        status = await workflow.execute_activity(
            write_status_activity,
            {"runtime_root": input_payload["runtime_root"], "completion_decision": decision},
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        activities = []
        if post_continue_status_refresh:
            activities.append(post_continue_status_refresh)
        if task_contract_router_result:
            activities.append(task_contract_router_result)
        if local_mature_bind_service_result:
            activities.append(local_mature_bind_service_result)
        if local_mature_bind_autopop_result:
            activities.append(local_mature_bind_autopop_result)
        activities.extend([bound, graph])
        if worker_brief_dispatch_plan:
            activities.append(compact_activity_for_history(worker_brief_dispatch_plan))
        if worker_brief_worker_results:
            activities.extend(worker_brief_worker_results)
        else:
            activities.append(codex_worker)
        activities.extend([claim, status])
        segment_pass_next_worker: dict[str, Any] = {}
        continuation = await workflow.execute_activity(
            partial_continuation_dispatch_activity,
            {
                **input_payload,
                "completion_decision": decision,
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
                "segment_pass_next_worker": segment_pass_next_worker,
            },
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=retry,
        )
        current_wave_index = 1
        current_wave_id = temporal_hot_path_wave_id(input_payload, current_wave_index)
        explicit_delivery_contract = input_payload.get("execution_contract_ready") is True
        worker_ledger: dict[str, Any] = {}
        if (
            temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER)
            and should_call_seed_cortex_worker_dispatch_ledger(input_payload)
        ):
            worker_evidence = (
                worker_brief_worker_results[:] if worker_brief_worker_results else [codex_worker]
            )
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
        if worker_ledger and (
            not explicit_delivery_contract
            or explicit_contract_requires_default_main_loop_tick(input_payload)
        ):
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
        v4pro_supervisor_orchestrator_tick: dict[str, Any] = {}
        if (
            main_loop_tick
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_V4PRO_SUPERVISOR_ORCHESTRATOR)
            and input_payload.get("disable_v4pro_supervisor_orchestrator_tick") is not True
        ):
            v4pro_supervisor_orchestrator_tick = await workflow.execute_activity(
                v4pro_supervisor_orchestrator_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                    "v4pro_supervisor_orchestrator_minimal_bootstrap": True,
                    "v4pro_supervisor_orchestrator_write_aaq": False,
                },
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=retry,
            )
        root_intent_loop_driver_tick: dict[str, Any] = {}
        if (
            worker_ledger
            and (
                v4pro_supervisor_orchestrator_tick
                or main_loop_tick
            )
            and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_ROOT_INTENT_LOOP_DRIVER_EVERY_WAVE)
            and input_payload.get("disable_root_intent_loop_driver_tick") is not True
        ):
            root_intent_loop_driver_tick = await workflow.execute_activity(
                root_intent_loop_driver_temporal_tick_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "v4pro_supervisor_orchestrator_activity": v4pro_supervisor_orchestrator_tick,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=3),
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
            and input_payload.get("disable_source_family_wave_scheduler") is not True
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
            and input_payload.get("disable_phase0_reusable_kernel") is not True
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
            and input_payload.get("disable_wave2_mainchain_hygiene") is not True
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
        if (
            should_flush_phase5_next_frontier_after_workerpool_closure(
                source_family_phase5_sunset,
                source_frontier_workerpool_closure_result,
            )
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH
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
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                    "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                    "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "phase0_reusable_kernel_activity": phase0_kernel,
                    "wave2_mainchain_hygiene_activity": wave2_hygiene,
                    "allocation_plan_activity": allocation_plan_result,
                    "phase5_sunset_wave_id": (
                        f"{current_wave_id}-post-closure-phase5-mature-thin-bind-sunset"
                    ),
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
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
        if (
            should_attempt_final_phase5_readmodel_flush(
                source_family_phase5_sunset,
                source_frontier_workerpool_closure_result,
            )
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH
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
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
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
                    "phase5_sunset_wave_id": (
                        f"{current_wave_id}-final-readmodel-phase5-mature-thin-bind-sunset"
                    ),
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        source_family_adapter_smoke_result: dict[str, Any] = {}
        if (
            should_invoke_source_family_adapter_smoke(source_family_phase5_sunset)
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE
            )
        ):
            source_family_adapter_smoke_result = await workflow.execute_activity(
                source_family_adapter_smoke_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "pre_pass_audit_loop_activity": pre_pass_audit,
                    "adapter_smoke_wave_id": f"{current_wave_id}-adapter-smoke",
                    "adapter_smoke_probe_mode": str(input_payload.get("adapter_smoke_probe_mode") or "live"),
                    "adapter_smoke_timeout_sec": int(input_payload.get("adapter_smoke_timeout_sec") or 20),
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=retry,
            )
        source_family_smoked_candidate_thin_bind_result: dict[str, Any] = {}
        if (
            should_invoke_source_family_smoked_candidate_thin_bind(
                source_family_adapter_smoke_result
            )
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND
            )
        ):
            source_family_smoked_candidate_thin_bind_result = await workflow.execute_activity(
                source_family_smoked_candidate_thin_bind_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "pre_pass_audit_loop_activity": pre_pass_audit,
                    "smoked_candidate_thin_bind_wave_id": (
                        f"{current_wave_id}-smoked-candidate-thin-bind"
                    ),
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        source_family_adapter_value_eval_result: dict[str, Any] = {}
        if (
            should_invoke_source_family_adapter_value_eval(
                source_family_smoked_candidate_thin_bind_result
            )
            and temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL
            )
        ):
            source_family_adapter_value_eval_result = await workflow.execute_activity(
                source_family_adapter_value_eval_activity,
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                    "source_family_smoked_candidate_thin_bind_activity": source_family_smoked_candidate_thin_bind_result,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "pre_pass_audit_loop_activity": pre_pass_audit,
                    "adapter_value_eval_wave_id": f"{current_wave_id}-adapter-value-eval",
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
        auto_dispatch_ingress: dict[str, Any] = {}
        next_frontier_continuation: dict[str, Any] = {}
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
                    "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                    "source_family_smoked_candidate_thin_bind_activity": source_family_smoked_candidate_thin_bind_result,
                    "source_family_adapter_value_eval_activity": source_family_adapter_value_eval_result,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            self._enqueue_ledger_auto_dispatch(auto_dispatch_ingress)
            if temporal_patch_enabled(
                TEMPORAL_PATCH_SEED_CORTEX_NEXT_FRONTIER_CONTINUATION_SUPERVISOR
            ) and input_payload.get("disable_next_frontier_continuation_supervisor") is not True:
                next_frontier_continuation = await workflow.execute_activity(
                    next_frontier_continuation_supervisor_activity,
                    {
                        **input_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "ledger_auto_dispatch_ingress_activity": auto_dispatch_ingress,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
                self._enqueue_next_frontier_continuation(
                    next_frontier_continuation,
                    auto_dispatch_ingress,
                )
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
        if v4pro_supervisor_orchestrator_tick:
            activities.append(v4pro_supervisor_orchestrator_tick)
        if root_intent_loop_driver_tick:
            activities.append(root_intent_loop_driver_tick)
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
        if source_family_adapter_smoke_result:
            activities.append(source_family_adapter_smoke_result)
        if source_family_smoked_candidate_thin_bind_result:
            activities.append(source_family_smoked_candidate_thin_bind_result)
        if source_family_adapter_value_eval_result:
            activities.append(source_family_adapter_value_eval_result)
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
        if next_frontier_continuation:
            activities.append(next_frontier_continuation)
        result = build_workflow_result(input_payload, activities, live_temporal=True)
        default_loop_waves_completed_in_run = max(
            1,
            _bounded_int(
                input_payload.get("default_loop_waves_completed_in_run"),
                0,
                minimum=0,
                maximum=100000,
            )
            + 1,
        )
        default_loop_initial_worker_task_id = str(
            input_payload.get("default_loop_initial_worker_task_id")
            or codex_worker.get("worker_task_id")
            or input_payload.get("codex_worker_task_id")
            or ""
        )
        result["default_loop_continue_as_new_policy"] = {
            "policy": "default_loop_history_budget_rollover",
            "enabled": input_payload.get("default_loop_continue_as_new", True) is not False,
            "patch_marker": TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW,
            "waves_completed_in_run": default_loop_waves_completed_in_run,
            "max_waves_per_run": _bounded_int(
                input_payload.get("default_loop_max_waves_per_run")
                or input_payload.get("max_continue_same_task_waves_per_run"),
                DEFAULT_LOOP_CONTINUE_AS_NEW_MAX_WAVES_PER_RUN,
                minimum=1,
                maximum=20,
            ),
            "max_waves_per_run_is_hard_fuse": True,
            "history_budget_ratio": DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_BUDGET_RATIO,
            "initial_worker_task_id": default_loop_initial_worker_task_id,
            "mature_pattern": "temporal_continue_as_new_claim_check",
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
        }
        persist_workflow_result(pathlib.Path(input_payload["runtime_root"]), result)
        if decision.get("status") == "complete_allowed" and decision.get("stop_allowed") is True:
            return result
        while True:
            try:
                await workflow.wait_condition(
                    lambda: bool(self.continue_same_task_signals)
                    or self._drain_after_current_wave_requested(),
                    timeout=dt.timedelta(seconds=int(input_payload.get("partial_keepalive_sleep_seconds") or PARTIAL_KEEPALIVE_SLEEP_SECONDS)),
                )
            except (asyncio.TimeoutError, TimeoutError):
                continue
            if self._drain_after_current_wave_requested() and not self.continue_same_task_signals:
                result = self._drained_result(
                    result,
                    current_wave_id="",
                    drain_point="wait_loop_before_next_signal",
                )
                persist_workflow_result(pathlib.Path(input_payload["runtime_root"]), result)
                return result
            if not self.continue_same_task_signals:
                continue
            rollover_decision = default_loop_rollover_decision(
                input_payload,
                workflow.info(),
                waves_completed_in_run=default_loop_waves_completed_in_run,
                pending_signal_count=len(self.continue_same_task_signals),
                patch_enabled=temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW
                ),
            )
            if rollover_decision["should_continue_as_new"]:
                next_payload = build_default_loop_continue_as_new_payload(
                    input_payload,
                    pending_signals=list(self.continue_same_task_signals),
                    rollover_decision=rollover_decision,
                    last_result=result,
                    initial_worker_task_id=default_loop_initial_worker_task_id,
                )
                result["default_loop_continue_as_new_decision"] = rollover_decision
                result["default_loop_continue_as_new_next_payload_summary"] = {
                    "generation": next_payload.get("default_loop_continue_generation"),
                    "pending_continue_same_task_signal_count": len(
                        next_payload.get("default_loop_continue_as_new_resume_state", {}).get(
                            "pending_continue_same_task_signals",
                            [],
                        )
                    )
                    if isinstance(
                        next_payload.get("default_loop_continue_as_new_resume_state"),
                        dict,
                    )
                    else 0,
                    "previous_run_id": next_payload.get("default_loop_previous_run_id", ""),
                    "initial_worker_task_id": next_payload.get("codex_worker_task_id", ""),
                    "completion_claim_allowed": False,
                    "not_user_completion": True,
                    "not_execution_controller": True,
                }
                persist_workflow_result(pathlib.Path(input_payload["runtime_root"]), result)
                workflow.continue_as_new(next_payload)
                return result
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
            continue_task_contract_router_result: dict[str, Any] = {}
            if temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_TASK_CONTRACT_ROUTER):
                continue_task_contract_router_result = await workflow.execute_activity(
                    task_contract_router_activity,
                    continue_worker_input,
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
                contract_payload = (
                    continue_task_contract_router_result.get("task_contract")
                    if isinstance(
                        continue_task_contract_router_result.get("task_contract"),
                        dict,
                    )
                    else {}
                )
                continue_worker_input = task_contract_router.apply_contract_to_payload(
                    continue_worker_input,
                    contract_payload,
                )
            continue_local_mature_bind_service_result: dict[str, Any] = {}
            continue_local_mature_bind_autopop_result: dict[str, Any] = {}
            if local_mature_bind_service_required(continue_worker_input):
                continue_local_mature_bind_service_result = await invoke_local_mature_bind_service_activity(
                    continue_worker_input,
                    retry,
                )
                auto_signal = (
                    continue_local_mature_bind_service_result.get("auto_continue_same_task_signal")
                    if isinstance(
                        continue_local_mature_bind_service_result.get(
                            "auto_continue_same_task_signal"
                        ),
                        dict,
                    )
                    else {}
                )
                if (
                    continue_local_mature_bind_service_result.get("auto_continue_same_workflow")
                    is True
                ):
                    self._append_continue_same_task_signal_once(auto_signal)
                continue_local_mature_bind_autopop_result = await autopop_next_mature_bind_after_local_success(
                    continue_worker_input,
                    continue_local_mature_bind_service_result,
                    retry,
                )
                auto_signal = (
                    continue_local_mature_bind_autopop_result.get("auto_continue_same_task_signal")
                    if isinstance(
                        continue_local_mature_bind_autopop_result.get(
                            "auto_continue_same_task_signal"
                        ),
                        dict,
                    )
                    else {}
                )
                if (
                    continue_local_mature_bind_autopop_result.get("auto_continue_same_workflow")
                    is True
                ):
                    self._append_continue_same_task_signal_once(auto_signal)
            continue_worker_brief_dispatch_plan: dict[str, Any] = {}
            continue_worker_brief_worker_results: list[dict[str, Any]] = []
            if explicit_contract_requires_worker_brief_real_receipts(continue_worker_input):
                continue_worker_brief_dispatch_plan = await workflow.execute_activity(
                    worker_brief_dispatch_plan_activity,
                    continue_worker_input,
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
                worker_turn_payloads = (
                    continue_worker_brief_dispatch_plan.get("worker_turn_payloads")
                    if isinstance(
                        continue_worker_brief_dispatch_plan.get("worker_turn_payloads"),
                        list,
                    )
                    else []
                )
                if worker_turn_payloads:
                    continue_worker_brief_worker_results = list(
                        await asyncio.gather(
                            *[
                                workflow.execute_activity(
                                    codex_worker_turn_activity,
                                    worker_turn_payload,
                                    start_to_close_timeout=codex_worker_activity_timeout(
                                        worker_turn_payload
                                    ),
                                    retry_policy=retry,
                                )
                                for worker_turn_payload in worker_turn_payloads
                                if isinstance(worker_turn_payload, dict)
                            ]
                        )
                    )
                    for worker_result in continue_worker_brief_worker_results:
                        if isinstance(worker_result, dict):
                            worker_result.update(
                                {
                                    **continuation_authorization_fields(),
                                    "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
                                    "segment_pass_next_worker_required": False,
                                    "continue_same_task_signal_worker_required": True,
                                    "segment_pass_same_workflow": True,
                                    "continue_same_task_signal": signal_payload,
                                    "worker_dispatch_real_receipt_required": True,
                                    "worker_brief_real_receipt_required": True,
                                    "synthetic_succeeded_by_driver": False,
                                    "phase1_worker_pool_receipt": False,
                                }
                            )
                    continue_worker = (
                        continue_worker_brief_worker_results[0]
                        if continue_worker_brief_worker_results
                        else {}
                    )
                else:
                    continue_worker = {
                        "activity": "codex_worker_turn",
                        "status": "activity_blocked",
                        "named_blocker": (
                            continue_worker_brief_dispatch_plan.get("named_blocker")
                            or "WORKER_BRIEF_DISPATCH_PLAN_EMPTY"
                        ),
                        **continuation_authorization_fields(),
                        "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
                        "segment_pass_next_worker_required": False,
                        "continue_same_task_signal_worker_required": True,
                        "segment_pass_same_workflow": True,
                        "continue_same_task_signal": signal_payload,
                        "worker_dispatch_real_receipt_required": True,
                        "worker_brief_real_receipt_required": True,
                        "completion_claim_allowed": False,
                        "not_user_completion": True,
                    }
            elif continue_local_mature_bind_service_result:
                continue_worker = local_mature_bind_worker_result(
                    continue_worker_input,
                    continue_local_mature_bind_service_result,
                )
                continue_worker.update(
                    {
                        **continuation_authorization_fields(),
                        "authorization_lane": CONTINUATION_AUTHORIZATION_LANE,
                        "segment_pass_next_worker_required": False,
                        "continue_same_task_signal_worker_required": True,
                        "segment_pass_same_workflow": True,
                        "continue_same_task_signal": signal_payload,
                    }
                )
            else:
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
            followup_payload = (
                continue_worker_input
                if continue_worker_input.get("execution_contract_ready") is True
                else input_payload
            )
            explicit_delivery_contract = (
                followup_payload.get("execution_contract_ready") is True
            )
            continuation = await workflow.execute_activity(
                partial_continuation_dispatch_activity,
                {
                    **followup_payload,
                    "completion_decision": decision,
                    "segment_pass_next_worker": continue_worker,
                    "continue_same_task_signal": signal_payload,
                },
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=retry,
            )
            panel = await workflow.execute_activity(
                panel_writeback_zh_activity,
                {
                    **followup_payload,
                    "completion_decision": decision,
                    "worker_dispatch_evidence": (
                        continue_worker_brief_worker_results
                        if continue_worker_brief_worker_results
                        else continue_worker
                    ),
                    "partial_continuation_dispatch": continuation,
                    "segment_pass_next_worker": continue_worker,
                    "continue_same_task_signal": signal_payload,
                },
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=retry,
            )
            worker_ledger = {}
            if (
                temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_WORKER_DISPATCH_LEDGER)
                and should_call_seed_cortex_worker_dispatch_ledger(followup_payload)
            ):
                worker_ledger = await workflow.execute_activity(
                    worker_dispatch_ledger_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_evidence": (
                            continue_worker_brief_worker_results
                            if continue_worker_brief_worker_results
                            else [continue_worker]
                        ),
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            main_loop_tick = {}
            if worker_ledger and (
                not explicit_delivery_contract
                or explicit_contract_requires_default_main_loop_tick(followup_payload)
            ):
                main_loop_tick = await workflow.execute_activity(
                    main_execution_loop_tick_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            v4pro_supervisor_orchestrator_tick = {}
            if (
                main_loop_tick
                and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_V4PRO_SUPERVISOR_ORCHESTRATOR)
                and followup_payload.get("disable_v4pro_supervisor_orchestrator_tick") is not True
            ):
                v4pro_supervisor_orchestrator_tick = await workflow.execute_activity(
                    v4pro_supervisor_orchestrator_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                        "v4pro_supervisor_orchestrator_minimal_bootstrap": True,
                        "v4pro_supervisor_orchestrator_write_aaq": False,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=retry,
                )
            root_intent_loop_driver_tick: dict[str, Any] = {}
            if (
                worker_ledger
                and (
                    v4pro_supervisor_orchestrator_tick
                    or main_loop_tick
                )
                and temporal_patch_enabled(TEMPORAL_PATCH_SEED_CORTEX_ROOT_INTENT_LOOP_DRIVER_EVERY_WAVE)
                and followup_payload.get("disable_root_intent_loop_driver_tick") is not True
            ):
                root_intent_loop_driver_tick = await workflow.execute_activity(
                    root_intent_loop_driver_temporal_tick_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "v4pro_supervisor_orchestrator_activity": v4pro_supervisor_orchestrator_tick,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=3),
                    retry_policy=retry,
                )
            source_family_phase5_sunset = {}
            main_loop_source_family = (
                main_loop_tick.get("runtime_preflight_refs", {}).get(
                    "source_family_wave_scheduler_surface", {}
                )
                if isinstance(main_loop_tick.get("runtime_preflight_refs"), dict)
                else {}
            )
            main_loop_next_wave_decision = (
                main_loop_tick.get("next_wave_decision", {})
                if isinstance(main_loop_tick.get("next_wave_decision"), dict)
                else {}
            )
            main_loop_phase5_action = str(
                main_loop_source_family.get("next_frontier_action")
                or main_loop_next_wave_decision.get("next_frontier_action")
                or ""
            )
            if (
                main_loop_tick
                and isinstance(main_loop_source_family, dict)
                and main_loop_phase5_action
                == source_family_mature_thin_bind_sunset.PHASE5_ACTION
                and followup_payload.get("disable_source_family_wave_scheduler") is not True
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_MATURE_THIN_BIND_SUNSET
                )
            ):
                source_family_phase5_sunset = await workflow.execute_activity(
                    source_family_mature_thin_bind_sunset_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "phase5_sunset_wave_id": f"{current_wave_id}-phase5-mature-thin-bind-sunset",
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
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
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
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
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
                and followup_payload.get("disable_source_frontier_workerpool_closure") is not True
            ):
                parent_bridge_wave_id = str(
                    source_frontier_workerbrief_bridge_result.get("bridge_wave_id")
                    or f"{current_wave_id}-source-frontier-workerbrief-bridge"
                )
                source_frontier_workerpool_closure_result = await workflow.execute_activity(
                    source_frontier_workerpool_closure_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "parent_wave_id": parent_bridge_wave_id,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=90),
                    retry_policy=retry,
                )
            if (
                should_flush_phase5_next_frontier_after_workerpool_closure(
                    source_family_phase5_sunset,
                    source_frontier_workerpool_closure_result,
                )
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_POST_CLOSURE_FLUSH
                )
            ):
                source_family_phase5_sunset = await workflow.execute_activity(
                    source_family_mature_thin_bind_sunset_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_family_wave_scheduler_activity": main_loop_source_family,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "phase5_sunset_wave_id": (
                            f"{current_wave_id}-post-closure-phase5-mature-thin-bind-sunset"
                        ),
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
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
                        **followup_payload,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
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
                        **followup_payload,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "allocation_plan_activity": allocation_plan_result,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
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
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=retry,
                )
            if (
                should_attempt_final_phase5_readmodel_flush(
                    source_family_phase5_sunset,
                    source_frontier_workerpool_closure_result,
                )
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_PHASE5_FINAL_READMODEL_FLUSH
                )
            ):
                source_family_phase5_sunset = await workflow.execute_activity(
                    source_family_mature_thin_bind_sunset_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "pre_pass_audit_loop_activity": pre_pass_audit,
                        "source_family_wave_scheduler_activity": main_loop_source_family,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "phase5_sunset_wave_id": (
                            f"{current_wave_id}-final-readmodel-phase5-mature-thin-bind-sunset"
                        ),
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            source_family_adapter_smoke_result = {}
            if (
                should_invoke_source_family_adapter_smoke(source_family_phase5_sunset)
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_SMOKE
                )
            ):
                source_family_adapter_smoke_result = await workflow.execute_activity(
                    source_family_adapter_smoke_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "pre_pass_audit_loop_activity": pre_pass_audit,
                        "source_family_wave_scheduler_activity": main_loop_source_family,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "adapter_smoke_wave_id": f"{current_wave_id}-adapter-smoke",
                        "adapter_smoke_probe_mode": str(
                            followup_payload.get("adapter_smoke_probe_mode") or "live"
                        ),
                        "adapter_smoke_timeout_sec": int(
                            followup_payload.get("adapter_smoke_timeout_sec") or 20
                        ),
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=5),
                    retry_policy=retry,
                )
            source_family_smoked_candidate_thin_bind_result = {}
            if (
                should_invoke_source_family_smoked_candidate_thin_bind(
                    source_family_adapter_smoke_result
                )
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_SMOKED_CANDIDATE_THIN_BIND
                )
            ):
                source_family_smoked_candidate_thin_bind_result = await workflow.execute_activity(
                    source_family_smoked_candidate_thin_bind_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "pre_pass_audit_loop_activity": pre_pass_audit,
                        "source_family_wave_scheduler_activity": main_loop_source_family,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "smoked_candidate_thin_bind_wave_id": (
                            f"{current_wave_id}-smoked-candidate-thin-bind"
                        ),
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            source_family_adapter_value_eval_result = {}
            if (
                should_invoke_source_family_adapter_value_eval(
                    source_family_smoked_candidate_thin_bind_result
                )
                and temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_SOURCE_FAMILY_ADAPTER_VALUE_EVAL
                )
            ):
                source_family_adapter_value_eval_result = await workflow.execute_activity(
                    source_family_adapter_value_eval_activity,
                    {
                        **followup_payload,
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "pre_pass_audit_loop_activity": pre_pass_audit,
                        "source_family_wave_scheduler_activity": main_loop_source_family,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                        "source_family_smoked_candidate_thin_bind_activity": source_family_smoked_candidate_thin_bind_result,
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "adapter_value_eval_wave_id": f"{current_wave_id}-adapter-value-eval",
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
            auto_dispatch_ingress = {}
            next_frontier_continuation = {}
            if worker_ledger and not explicit_delivery_contract:
                auto_dispatch_ingress = await workflow.execute_activity(
                    ledger_auto_dispatch_ingress_activity,
                    {
                        **followup_payload,
                        "partial_continuation_dispatch": continuation,
                        "worker_dispatch_evidence": (
                            continue_worker_brief_worker_results
                            if continue_worker_brief_worker_results
                            else [continue_worker]
                        ),
                        "worker_dispatch_ledger_activity": worker_ledger,
                        "main_execution_loop_tick_activity": main_loop_tick,
                        "durable_parallel_wave_packet_activity": durable_wave_packet,
                        "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                        "scheduler_invocation_packet_activity": scheduler_packet,
                        "allocation_plan_activity": allocation_plan_result,
                        "pre_pass_audit_loop_activity": pre_pass_audit,
                        "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                        "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                        "source_family_smoked_candidate_thin_bind_activity": (
                            source_family_smoked_candidate_thin_bind_result
                        ),
                        "source_family_adapter_value_eval_activity": (
                            source_family_adapter_value_eval_result
                        ),
                        "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                        "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                        "drain_after_current_wave_request": dict(
                            self.drain_after_current_wave_request
                        )
                        if self._drain_after_current_wave_requested()
                        else {},
                        "wave_id": current_wave_id,
                        "wave_index": current_wave_index,
                    },
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=retry,
                )
                self._enqueue_ledger_auto_dispatch(auto_dispatch_ingress)
                if temporal_patch_enabled(
                    TEMPORAL_PATCH_SEED_CORTEX_NEXT_FRONTIER_CONTINUATION_SUPERVISOR
                ) and followup_payload.get("disable_next_frontier_continuation_supervisor") is not True:
                    next_frontier_continuation = await workflow.execute_activity(
                        next_frontier_continuation_supervisor_activity,
                        {
                            **followup_payload,
                            "worker_dispatch_ledger_activity": worker_ledger,
                            "ledger_auto_dispatch_ingress_activity": auto_dispatch_ingress,
                            "wave_id": current_wave_id,
                            "wave_index": current_wave_index,
                        },
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=retry,
                    )
                    self._enqueue_next_frontier_continuation(
                        next_frontier_continuation,
                        auto_dispatch_ingress,
                    )
            elif not explicit_delivery_contract:
                self._enqueue_assignment_dag_auto_continue(continuation)
            if continue_task_contract_router_result:
                activities.append(continue_task_contract_router_result)
            if continue_local_mature_bind_service_result:
                activities.append(continue_local_mature_bind_service_result)
            if continue_local_mature_bind_autopop_result:
                activities.append(continue_local_mature_bind_autopop_result)
            if continue_worker_brief_dispatch_plan:
                activities.append(compact_activity_for_history(continue_worker_brief_dispatch_plan))
            if continue_worker_brief_worker_results:
                activities.extend(continue_worker_brief_worker_results)
            else:
                activities.append(continue_worker)
            activities.extend([continuation, panel])
            if worker_ledger:
                activities.append(worker_ledger)
            if main_loop_tick:
                activities.append(main_loop_tick)
            if v4pro_supervisor_orchestrator_tick:
                activities.append(v4pro_supervisor_orchestrator_tick)
            if root_intent_loop_driver_tick:
                activities.append(root_intent_loop_driver_tick)
            if source_family_phase5_sunset:
                activities.append(source_family_phase5_sunset)
            if source_family_adapter_smoke_result:
                activities.append(source_family_adapter_smoke_result)
            if source_family_smoked_candidate_thin_bind_result:
                activities.append(source_family_smoked_candidate_thin_bind_result)
            if source_family_adapter_value_eval_result:
                activities.append(source_family_adapter_value_eval_result)
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
            if next_frontier_continuation:
                activities.append(next_frontier_continuation)
            default_loop_waves_completed_in_run += 1
            result = build_workflow_result(input_payload, activities, live_temporal=True)
            result["default_loop_continue_as_new_policy"] = {
                "policy": "default_loop_history_budget_rollover",
                "enabled": input_payload.get("default_loop_continue_as_new", True) is not False,
                "patch_marker": TEMPORAL_PATCH_SEED_CORTEX_DEFAULT_LOOP_CONTINUE_AS_NEW,
                "waves_completed_in_run": default_loop_waves_completed_in_run,
                "max_waves_per_run": _bounded_int(
                    input_payload.get("default_loop_max_waves_per_run")
                    or input_payload.get("max_continue_same_task_waves_per_run"),
                    DEFAULT_LOOP_CONTINUE_AS_NEW_MAX_WAVES_PER_RUN,
                    minimum=1,
                    maximum=20,
                ),
                "max_waves_per_run_is_hard_fuse": True,
                "history_budget_ratio": DEFAULT_LOOP_CONTINUE_AS_NEW_HISTORY_BUDGET_RATIO,
                "initial_worker_task_id": default_loop_initial_worker_task_id,
                "mature_pattern": "temporal_continue_as_new_claim_check",
                "completion_claim_allowed": False,
                "not_user_completion": True,
                "not_execution_controller": True,
            }
            if self._drain_after_current_wave_requested():
                result = self._drained_result(
                    result,
                    current_wave_id=current_wave_id,
                    drain_point="after_current_wave_persist",
                )
            persist_workflow_result(pathlib.Path(input_payload["runtime_root"]), result)
            if self._drain_after_current_wave_requested():
                return result


def build_workflow_result(input_payload: dict[str, Any], activities: list[dict[str, Any]], *, live_temporal: bool) -> dict[str, Any]:
    completion_activity = next(item for item in activities if item["activity"] == "completion_claim")
    task_contract_router_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "task_contract_router"
        ),
        {},
    )
    post_continue_status_refresh_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "post_continue_as_new_status_refresh"
        ),
        {},
    )
    v4pro_tool_bearing_executor_policy_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "v4pro_tool_bearing_executor_policy"
        ),
        {},
    )
    mature_bind_queue_autopop_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "mature_bind_queue_autopop"
        ),
        {},
    )
    v4pro_supervisor_orchestrator_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "v4pro_supervisor_orchestrator"
        ),
        {},
    )
    graph_activity = next((item for item in activities if item.get("activity") == "run_langgraph" and isinstance(item.get("graph_result"), dict)), {})
    graph_result = graph_activity.get("graph_result") if isinstance(graph_activity.get("graph_result"), dict) else {}
    object_binding = task_object_binding_from_payload({
        **input_payload,
        "graph_result": graph_result,
    })
    decision = completion_activity["completion_decision"]
    segment_audit_activity: dict[str, Any] = {}
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
    same_workflow_next_worker_dispatched = worker_turn_evidence_ready(segment_pass_next_worker)
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
    source_family_adapter_smoke_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_family_adapter_smoke"
        ),
        {},
    )
    source_family_smoked_candidate_thin_bind_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_family_smoked_candidate_thin_bind"
        ),
        {},
    )
    source_family_adapter_value_eval_activity_result = next(
        (
            item
            for item in reversed(activities)
            if item.get("activity") == "source_family_adapter_value_eval"
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
        "task_contract_router_activity": (
            task_contract_router_activity_result
            if isinstance(task_contract_router_activity_result, dict)
            else {}
        ),
        "post_continue_as_new_status_refresh_activity": (
            post_continue_status_refresh_activity_result
            if isinstance(post_continue_status_refresh_activity_result, dict)
            else {}
        ),
        "post_continue_as_new_status_refresh_ready": bool(
            isinstance(post_continue_status_refresh_activity_result, dict)
            and post_continue_status_refresh_activity_result.get(
                "post_continue_as_new_status_refresh_ready"
            )
            is True
        ),
        "post_continue_as_new_status_refresh_latest_ref": str(
            post_continue_status_refresh_activity_result.get("latest_ref") or ""
        )
        if isinstance(post_continue_status_refresh_activity_result, dict)
        else "",
        "v4pro_tool_bearing_executor_policy_activity": (
            v4pro_tool_bearing_executor_policy_activity_result
            if isinstance(v4pro_tool_bearing_executor_policy_activity_result, dict)
            else {}
        ),
        "v4pro_tool_bearing_executor_policy_ready": bool(
            isinstance(v4pro_tool_bearing_executor_policy_activity_result, dict)
            and v4pro_tool_bearing_executor_policy_activity_result.get(
                "tool_bearing_executor_eligible"
            )
            is True
        ),
        "mature_bind_queue_autopop_activity": (
            mature_bind_queue_autopop_activity_result
            if isinstance(mature_bind_queue_autopop_activity_result, dict)
            else {}
        ),
        "mature_bind_queue_autopop_ready": bool(
            isinstance(mature_bind_queue_autopop_activity_result, dict)
            and mature_bind_queue_autopop_activity_result.get("mature_bind_queue_autopop_ready")
            is True
        ),
        "mature_bind_queue_autopop_next_task_id": str(
            mature_bind_queue_autopop_activity_result.get("next_mature_bind_task_id") or ""
        )
        if isinstance(mature_bind_queue_autopop_activity_result, dict)
        else "",
        "v4pro_supervisor_orchestrator_activity": (
            v4pro_supervisor_orchestrator_activity_result
            if isinstance(v4pro_supervisor_orchestrator_activity_result, dict)
            else {}
        ),
        "v4pro_supervisor_orchestrator_ready": bool(
            isinstance(v4pro_supervisor_orchestrator_activity_result, dict)
            and v4pro_supervisor_orchestrator_activity_result.get("v4pro_supervisor_orchestrator_ready")
            is True
        ),
        "v4pro_supervisor_orchestrator_minimal_bootstrap": bool(
            isinstance(v4pro_supervisor_orchestrator_activity_result, dict)
            and v4pro_supervisor_orchestrator_activity_result.get("minimal_bootstrap_mode")
            is True
        ),
        "v4pro_supervisor_orchestrator_latest_ref": str(
            v4pro_supervisor_orchestrator_activity_result.get("latest_ref") or ""
        )
        if isinstance(v4pro_supervisor_orchestrator_activity_result, dict)
        else "",
        "task_contract_id": str(task_contract_router_activity_result.get("contract_id") or "")
        if isinstance(task_contract_router_activity_result, dict)
        else "",
        "task_contract_explicit_execution": bool(
            isinstance(task_contract_router_activity_result, dict)
            and task_contract_router_activity_result.get("explicit_execution_task") is True
        ),
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
        "segment_pass_must_dispatch_next_bounded_worker": False,
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
        "source_family_adapter_smoke_activity": (
            source_family_adapter_smoke_activity_result
            if isinstance(source_family_adapter_smoke_activity_result, dict)
            else {}
        ),
        "source_family_adapter_smoke_latest_ref": str(
            source_family_adapter_smoke_activity_result.get(
                "source_family_adapter_smoke_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_adapter_smoke_activity_result, dict)
        else "",
        "source_family_adapter_smoke_temporal_activity_latest_ref": str(
            source_family_adapter_smoke_activity_result.get(
                "source_family_adapter_smoke_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_adapter_smoke_activity_result, dict)
        else "",
        "source_family_adapter_smoke_candidate_count": int(
            source_family_adapter_smoke_activity_result.get("candidate_count") or 0
        )
        if isinstance(source_family_adapter_smoke_activity_result, dict)
        else 0,
        "source_family_adapter_smoke_passed_candidate_count": int(
            source_family_adapter_smoke_activity_result.get("passed_candidate_count")
            or 0
        )
        if isinstance(source_family_adapter_smoke_activity_result, dict)
        else 0,
        "source_family_adapter_smoke_validation_passed": bool(
            isinstance(source_family_adapter_smoke_activity_result, dict)
            and source_family_adapter_smoke_activity_result.get(
                "adapter_smoke_validation_passed"
            )
            is True
        ),
        "source_family_adapter_smoke_not_execution_controller": True,
        "source_family_adapter_smoke_not_completion_gate": True,
        "source_family_smoked_candidate_thin_bind_activity": (
            source_family_smoked_candidate_thin_bind_activity_result
            if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
            else {}
        ),
        "source_family_smoked_candidate_thin_bind_latest_ref": str(
            source_family_smoked_candidate_thin_bind_activity_result.get(
                "source_family_smoked_candidate_thin_bind_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
        else "",
        "source_family_smoked_candidate_thin_bind_temporal_activity_latest_ref": str(
            source_family_smoked_candidate_thin_bind_activity_result.get(
                "source_family_smoked_candidate_thin_bind_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
        else "",
        "source_family_smoked_candidate_thin_bind_bindings_ref": str(
            source_family_smoked_candidate_thin_bind_activity_result.get("bindings_ref")
            or ""
        )
        if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
        else "",
        "source_family_smoked_candidate_thin_bind_binding_count": int(
            source_family_smoked_candidate_thin_bind_activity_result.get("binding_count")
            or 0
        )
        if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
        else 0,
        "source_family_smoked_candidate_thin_bind_ready_binding_count": int(
            source_family_smoked_candidate_thin_bind_activity_result.get("ready_binding_count")
            or 0
        )
        if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
        else 0,
        "source_family_smoked_candidate_thin_bind_validation_passed": bool(
            isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
            and source_family_smoked_candidate_thin_bind_activity_result.get(
                "thin_bind_validation_passed"
            )
            is True
        ),
        "source_family_smoked_candidate_thin_bind_not_execution_controller": True,
        "source_family_smoked_candidate_thin_bind_not_completion_gate": True,
        "source_family_adapter_value_eval_activity": (
            source_family_adapter_value_eval_activity_result
            if isinstance(source_family_adapter_value_eval_activity_result, dict)
            else {}
        ),
        "source_family_adapter_value_eval_latest_ref": str(
            source_family_adapter_value_eval_activity_result.get(
                "source_family_adapter_value_eval_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_adapter_value_eval_activity_result, dict)
        else "",
        "source_family_adapter_value_eval_temporal_activity_latest_ref": str(
            source_family_adapter_value_eval_activity_result.get(
                "source_family_adapter_value_eval_temporal_activity_latest_ref"
            )
            or ""
        )
        if isinstance(source_family_adapter_value_eval_activity_result, dict)
        else "",
        "source_family_adapter_value_eval_decisions_ref": str(
            source_family_adapter_value_eval_activity_result.get("decisions_ref")
            or ""
        )
        if isinstance(source_family_adapter_value_eval_activity_result, dict)
        else "",
        "source_family_adapter_value_eval_gateway_candidates_ref": str(
            source_family_adapter_value_eval_activity_result.get(
                "capability_gateway_candidates_ref"
            )
            or ""
        )
        if isinstance(source_family_adapter_value_eval_activity_result, dict)
        else "",
        "source_family_adapter_value_eval_decision_count": int(
            source_family_adapter_value_eval_activity_result.get("decision_count") or 0
        )
        if isinstance(source_family_adapter_value_eval_activity_result, dict)
        else 0,
        "source_family_adapter_value_eval_gateway_candidate_count": int(
            source_family_adapter_value_eval_activity_result.get("gateway_candidate_count")
            or 0
        )
        if isinstance(source_family_adapter_value_eval_activity_result, dict)
        else 0,
        "source_family_adapter_value_eval_validation_passed": bool(
            isinstance(source_family_adapter_value_eval_activity_result, dict)
            and source_family_adapter_value_eval_activity_result.get(
                "value_eval_validation_passed"
            )
            is True
        ),
        "source_family_adapter_value_eval_not_execution_controller": True,
        "source_family_adapter_value_eval_not_completion_gate": True,
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
            "source_family_smoked_candidate_thin_bind": str(
                source_family_smoked_candidate_thin_bind_activity_result.get(
                    "source_family_smoked_candidate_thin_bind_latest_ref"
                )
                or ""
            )
            if isinstance(source_family_smoked_candidate_thin_bind_activity_result, dict)
            else "",
            "source_family_adapter_value_eval": str(
                source_family_adapter_value_eval_activity_result.get(
                    "source_family_adapter_value_eval_latest_ref"
                )
                or ""
            )
            if isinstance(source_family_adapter_value_eval_activity_result, dict)
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
        "codex_final_to_user_allowed": panel_activity.get("codex_final_to_user_allowed") is True,
        "worker_final_user_visible_allowed": panel_activity.get("worker_final_user_visible_allowed") is True,
        "no_pytest_wall_to_user": panel_activity.get("no_pytest_wall_to_user") is True,
        "legacy_continuation_policy": "legacy_rescue_only_not_mainline",
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
        "g2_temporal_server_verification_ref": str(input_payload.get("g2_temporal_server_verification_ref") or ""),
        "worker_service_polling": bool(input_payload.get("worker_service_polling", False)),
        "worker_service_evidence": input_payload.get("worker_service_evidence", {}),
        "segment_pass_must_dispatch_next_bounded_worker": bool(input_payload.get("segment_pass_must_dispatch_next_bounded_worker")),
        "same_workflow_next_worker_dispatched": bool(input_payload.get("same_workflow_next_worker_dispatched")),
        "same_workflow_next_worker_task_id": str(input_payload.get("same_workflow_next_worker_task_id") or ""),
        "same_workflow_next_worker_jsonl_path": str(input_payload.get("same_workflow_next_worker_jsonl_path") or ""),
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
    worker_turn_enabled = execute_codex_worker if execute_worker_turn is None else execute_worker_turn
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
        "execute_worker_turn": worker_turn_enabled,
        "execute_codex_worker": execute_codex_worker,
        "execute_codex_worker_legacy_alias": execute_codex_worker,
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
    activities.append(claim)
    overridden_decision = claim["completion_decision"]
    activities.append(asyncio.run(write_status_activity({
        "runtime_root": str(runtime_root),
        "completion_decision": overridden_decision,
    })))
    segment_pass_next_worker: dict[str, Any] = {}
    continuation = asyncio.run(partial_continuation_dispatch_activity({
        **input_payload,
        "completion_decision": overridden_decision,
        "segment_pass_next_worker": segment_pass_next_worker,
    }))
    activities.append(continuation)
    activities.append(asyncio.run(panel_writeback_zh_activity({
        **input_payload,
        "completion_decision": overridden_decision,
        "worker_dispatch_evidence": codex_worker,
        "partial_continuation_dispatch": continuation,
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
        if should_flush_phase5_next_frontier_after_workerpool_closure(
            source_family_phase5_sunset,
            source_frontier_workerpool_closure_result,
        ):
            source_family_phase5_sunset = asyncio.run(source_family_mature_thin_bind_sunset_activity({
                **input_payload,
                "worker_dispatch_ledger_activity": worker_ledger,
                "main_execution_loop_tick_activity": main_loop_tick,
                "durable_parallel_wave_packet_activity": durable_wave_packet,
                "source_frontier_durable_consumer_activity": source_frontier_consumer,
                "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                "default_dp_worker_pool_wave_activity": default_dp_worker_pool_wave,
                "default_dp_draft_staging_fan_in_activity": default_dp_fan_in,
                "default_loop_runtime_state_update_activity": default_loop_runtime_state,
                "source_family_wave_scheduler_activity": source_family_wave,
                "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                "phase0_reusable_kernel_activity": phase0_kernel,
                "wave2_mainchain_hygiene_activity": wave2_hygiene,
                "allocation_plan_activity": allocation_plan_result,
                "phase5_sunset_wave_id": (
                    f"{current_wave_id}-post-closure-phase5-mature-thin-bind-sunset"
                ),
                "wave_id": current_wave_id,
                "wave_index": current_wave_index,
            }))
            activities.append(source_family_phase5_sunset)
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
        if should_attempt_final_phase5_readmodel_flush(
            source_family_phase5_sunset,
            source_frontier_workerpool_closure_result,
        ):
            source_family_phase5_sunset = asyncio.run(source_family_mature_thin_bind_sunset_activity({
                **input_payload,
                "worker_dispatch_ledger_activity": worker_ledger,
                "main_execution_loop_tick_activity": main_loop_tick,
                "durable_parallel_wave_packet_activity": durable_wave_packet,
                "source_frontier_durable_consumer_activity": source_frontier_consumer,
                "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
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
                "phase5_sunset_wave_id": (
                    f"{current_wave_id}-final-readmodel-phase5-mature-thin-bind-sunset"
                ),
                "wave_id": current_wave_id,
                "wave_index": current_wave_index,
            }))
            activities.append(source_family_phase5_sunset)
        source_family_adapter_smoke_result = {}
        if should_invoke_source_family_adapter_smoke(source_family_phase5_sunset):
            source_family_adapter_smoke_result = asyncio.run(source_family_adapter_smoke_activity({
                **input_payload,
                "worker_dispatch_ledger_activity": worker_ledger,
                "main_execution_loop_tick_activity": main_loop_tick,
                "durable_parallel_wave_packet_activity": durable_wave_packet,
                "source_frontier_durable_consumer_activity": source_frontier_consumer,
                "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                "source_family_wave_scheduler_activity": source_family_wave,
                "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                "scheduler_invocation_packet_activity": scheduler_packet,
                "pre_pass_audit_loop_activity": pre_pass_audit,
                "adapter_smoke_wave_id": f"{current_wave_id}-adapter-smoke",
                "adapter_smoke_probe_mode": str(input_payload.get("adapter_smoke_probe_mode") or "synthetic"),
                "adapter_smoke_timeout_sec": int(input_payload.get("adapter_smoke_timeout_sec") or 20),
                "wave_id": current_wave_id,
                "wave_index": current_wave_index,
            }))
            activities.append(source_family_adapter_smoke_result)
        source_family_smoked_candidate_thin_bind_result = {}
        if should_invoke_source_family_smoked_candidate_thin_bind(
            source_family_adapter_smoke_result
        ):
            source_family_smoked_candidate_thin_bind_result = asyncio.run(
                source_family_smoked_candidate_thin_bind_activity({
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "pre_pass_audit_loop_activity": pre_pass_audit,
                    "smoked_candidate_thin_bind_wave_id": (
                        f"{current_wave_id}-smoked-candidate-thin-bind"
                    ),
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                })
            )
            activities.append(source_family_smoked_candidate_thin_bind_result)
        source_family_adapter_value_eval_result = {}
        if should_invoke_source_family_adapter_value_eval(
            source_family_smoked_candidate_thin_bind_result
        ):
            source_family_adapter_value_eval_result = asyncio.run(
                source_family_adapter_value_eval_activity({
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "main_execution_loop_tick_activity": main_loop_tick,
                    "durable_parallel_wave_packet_activity": durable_wave_packet,
                    "source_frontier_durable_consumer_activity": source_frontier_consumer,
                    "source_frontier_workerbrief_bridge_activity": source_frontier_workerbrief_bridge_result,
                    "source_frontier_workerpool_closure_activity": source_frontier_workerpool_closure_result,
                    "source_family_wave_scheduler_activity": source_family_wave,
                    "source_family_mature_thin_bind_sunset_activity": source_family_phase5_sunset,
                    "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
                    "source_family_smoked_candidate_thin_bind_activity": source_family_smoked_candidate_thin_bind_result,
                    "default_main_loop_trigger_candidate_activity": default_trigger_candidate,
                    "scheduler_invocation_packet_activity": scheduler_packet,
                    "pre_pass_audit_loop_activity": pre_pass_audit,
                    "adapter_value_eval_wave_id": f"{current_wave_id}-adapter-value-eval",
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                })
            )
            activities.append(source_family_adapter_value_eval_result)
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
            "source_family_adapter_smoke_activity": source_family_adapter_smoke_result,
            "source_family_smoked_candidate_thin_bind_activity": source_family_smoked_candidate_thin_bind_result,
            "source_family_adapter_value_eval_activity": source_family_adapter_value_eval_result,
            "wave_id": current_wave_id,
            "wave_index": current_wave_index,
        }))
        activities.append(auto_dispatch_ingress)
        next_frontier_continuation = asyncio.run(
            next_frontier_continuation_supervisor_activity(
                {
                    **input_payload,
                    "worker_dispatch_ledger_activity": worker_ledger,
                    "ledger_auto_dispatch_ingress_activity": auto_dispatch_ingress,
                    "wave_id": current_wave_id,
                    "wave_index": current_wave_index,
                }
            )
        )
        activities.append(next_frontier_continuation)
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
    start_guard = seed_cortex_mainline_start_guard(input_payload, task_queue=str(task_queue))
    if start_guard.get("action") == "attach_existing":
        return attached_existing_workflow_result(
            input_payload,
            runtime_root=runtime_root,
            task_queue=str(task_queue),
            workflow_id=str(start_guard.get("workflow_id") or ""),
            workflow_run_id=str(start_guard.get("workflow_run_id") or ""),
            guard=start_guard,
        )
    if start_guard.get("action") == "blocked":
        return blocked_mainline_start_result(
            input_payload,
            task_queue=str(task_queue),
            guard=start_guard,
        )
    workflow_id = str(start_guard.get("workflow_id") or "").strip()
    input_payload = {**input_payload, "workflow_id": workflow_id}
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
        "attached_existing_workflow": False,
        "start_workflow_called": True,
        "mainline_start_guard": start_guard,
        "workflow_id_conflict_policy": (
            start_guard.get("workflow_id_conflict_policy") or "legacy_start_when_not_seed_cortex"
        ),
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
            task_contract_router_activity,
            post_continue_as_new_status_refresh_activity,
            v4pro_tool_bearing_executor_policy_activity,
            mature_bind_queue_autopop_activity,
            current_task_source_intake_activity,
            v4pro_mature_bind_execution_controller_activity,
            v4pro_supervisor_orchestrator_activity,
            root_intent_loop_driver_temporal_tick_activity,
            bind_task_activity,
            run_langgraph_activity,
            worker_brief_dispatch_plan_activity,
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
            source_family_adapter_smoke_activity,
            source_family_smoked_candidate_thin_bind_activity,
            source_family_adapter_value_eval_activity,
            phase0_reusable_kernel_activity,
            wave2_mainchain_hygiene_activity,
            default_main_loop_trigger_candidate_activity,
            scheduler_invocation_packet_activity,
            ledger_auto_dispatch_ingress_activity,
            next_frontier_continuation_supervisor_activity,
            completion_claim_activity,
            write_status_activity,
            partial_continuation_dispatch_activity,
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
    parser.add_argument("--execute-worker-turn", action="store_true")
    parser.add_argument("--execute-codex-worker", action="store_true", help="Legacy alias for --execute-worker-turn.")
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
    parser.add_argument("--work-package-json", default="", help="Path to an explicit assignment_dag work_package JSON for the default trigger worker pool.")
    parser.add_argument("--anchor-package-root", default=r"C:\Users\xx363\Desktop\新系统")
    parser.add_argument("--bind-provider-worker-pool", action="store_true")
    parser.add_argument(
        "--phase1-target-width",
        type=int,
        default=0,
        help="Optional upper cap. Default 0 means dynamic width decision owns the worker-pool width.",
    )
    parser.add_argument("--phase1-max-parallel-workers", type=int, default=12)
    parser.add_argument("--allow-local-stub-acceptance", action="store_true")
    parser.add_argument("--disable-source-frontier-workerpool-closure", action="store_true")
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
    anchor_package_root = pathlib.Path(args.anchor_package_root)
    source_refs = [
        file_source_ref(
            pathlib.Path(path),
            current_authority=is_current_p0_three_text_source_ref(
                pathlib.Path(path),
                anchor_package_root,
            ),
            authority_package_id=CURRENT_P0_THREE_TEXT_SOURCE_PACKAGE_ID,
        )
        for path in args.source_ref
    ]
    compiled_task_object = read_compiled_task_object(pathlib.Path(args.compiled_task_object_json)) if args.compiled_task_object_json else {}
    work_package = read_work_package(pathlib.Path(args.work_package_json)) if args.work_package_json else {}
    human_egress_route = str(args.human_egress_route or "").strip()
    segment_boundary_headless = bool(args.segment_boundary_headless)
    execute_worker_turn = bool(args.execute_worker_turn or args.execute_codex_worker)
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
            "work_package": work_package,
            "runtime_subject_loop_required": list(langgraph_task_runner.RUNTIME_SUBJECT_LOOP_REQUIRED),
            "root_repair_constraints": list(langgraph_task_runner.ROOT_REPAIR_CONSTRAINTS),
            "minimum_reality_contact_required": True,
            "no_new_parallel_control_surface": True,
            "execute_worker_turn": execute_worker_turn,
            "execute_codex_worker": args.execute_codex_worker,
            "execute_codex_worker_legacy_alias": args.execute_codex_worker,
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
            "anchor_package_root": args.anchor_package_root,
            "bind_provider_worker_pool": args.bind_provider_worker_pool,
            "phase1_target_width": args.phase1_target_width,
            "phase1_max_parallel_workers": args.phase1_max_parallel_workers,
            "allow_local_stub_acceptance": args.allow_local_stub_acceptance,
            "disable_source_frontier_workerpool_closure": (
                args.disable_source_frontier_workerpool_closure
            ),
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
                "workflow_id": args.workflow_id
                or f"xinao-codex-task-{args.task_id}-{run_id()}",
                "anchor_package_root": args.anchor_package_root,
                "work_package": work_package,
                "bind_provider_worker_pool": args.bind_provider_worker_pool,
                "phase1_target_width": args.phase1_target_width,
                "phase1_max_parallel_workers": args.phase1_max_parallel_workers,
                "allow_local_stub_acceptance": args.allow_local_stub_acceptance,
                "disable_source_frontier_workerpool_closure": (
                    args.disable_source_frontier_workerpool_closure
                ),
            },
            allow_complete_fixture=args.allow_complete_fixture,
            simulate_transient_failure=args.simulate_transient_failure,
            source_refs=source_refs,
            compiled_task_object=compiled_task_object,
            execute_worker_turn=execute_worker_turn,
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
