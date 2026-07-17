"""XinaoPromotedTaskWorkflowV1 — Temporal workflow + signal/query/cancellation.

Official patterns (docs.temporal.io develop/python):
- @workflow.defn / @workflow.run
- @workflow.signal / @workflow.query (message-passing)
- workflow.execute_activity + RetryPolicy
- asyncio.CancelledError / request_cancel for graceful interrupt
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior
from temporalio.exceptions import ApplicationError, TemporalError
from temporalio.exceptions import CancelledError as TemporalCancelledError

with workflow.unsafe.imports_passed_through():
    from xinao_coordination.temporal.activities import (
        DEFAULT_ACTIVITY_RETRY,
        DEFAULT_START_TO_CLOSE,
        execute_promoted_step,
        finalize_promoted_task,
        record_promoted_started,
        validate_promoted_envelope,
    )
    from xinao_coordination.temporal.grok_parallel import (
        DEFAULT_MODEL as GROK_DEFAULT_MODEL,
    )
    from xinao_coordination.temporal.grok_parallel import (
        LEGACY_DEFAULT_MODEL as GROK_LEGACY_DEFAULT_MODEL,
    )
    from xinao_coordination.temporal.grok_parallel import (
        PROVIDER_ID as GROK_PROVIDER_ID,
    )
    from xinao_coordination.temporal.grok_parallel import (
        execute_grok_acpx_lane,
        is_completed_grok_lane,
        materialize_grok_acpx_fanin,
        validate_ready_frontier,
    )

WORKFLOW_TYPE = "XinaoPromotedTaskWorkflowV1"
DEFAULT_TASK_QUEUE = "xinao-dualbrain-promoted-v1"
LANGGRAPH_CHILD_PATCH_ID = "promoted-langgraph-child-v1"
GROK_FRONTIER_PATCH_ID = "promoted-grok-acpx-frontier-v1"
GROK_PREFAN_ACCEPTANCE_PATCH_ID = "promoted-grok-prefan-acceptance-v1"
GROK_FULL_FRONTIER_ACCEPTANCE_PATCH_ID = "promoted-grok-full-frontier-v1"
GROK_FULL_FRONTIER_DEFAULT_PATCH_ID = "promoted-grok-full-frontier-default-v2"
GROK_COMPOSER_DEFAULT_PATCH_ID = "promoted-grok-composer-default-v1"
GROK_EXPLICIT_SUPERVISOR_SELECTION_PATCH_ID = "promoted-grok-explicit-supervisor-selection-v1"
GROK_SUPERVISOR_SELECTION_RECEIPT_PATCH_ID = "promoted-grok-supervisor-selection-receipt-v1"
GROK_ATTESTED_LANE_ACCEPTANCE_PATCH_ID = "promoted-grok-attested-lane-acceptance-v1"
GROK_DOCKER_FIRST_PATCH_ID = "promoted-grok-docker-first-v1"
LANGGRAPH_GROK_ONLY_ACCEPTANCE_PATCH_ID = "promoted-langgraph-grok-only-acceptance-v1"
LANGGRAPH_DYNAMIC_PROVIDER_ACCEPTANCE_PATCH_ID = "promoted-langgraph-dynamic-provider-acceptance-v2"
# Before formal Worker Versioning was enabled, this recorded build enforced
# child_wf_ok on the no-prefan path.  Temporal exposes the historical Workflow
# Task build ID deterministically during replay, so keep this bounded migration
# fence instead of branching on workflow IDs, timestamps, or business payloads.
LEGACY_CHILD_WF_REQUIRED_BUILD_IDS = frozenset({"4d914c0249ea40d9d666e2832812436f"})
DEFAULT_LANGGRAPH_CHILD_QUEUE = "xinao-integrated-langgraph-plugin-queue"
DEFAULT_LANGGRAPH_CHILD_WORKFLOW = "XinaoIntegratedBusWorkflow"
DEFAULT_LANGGRAPH_INPUT_REF = "/app/materials/phase0_test_input.md"
DEFAULT_LANGGRAPH_PARAMS_REF = "/app/materials/authority_glue/seams/integrated_bus_params.v1.json"
LEGACY_REQUIRED_LANGGRAPH_TRUE_CHECKS = (
    "validate_ok",
    "planner_ok",
    "gateway_trace_ok",
    "mcp_tool_invoked",
    "fanin_ok",
    "checkpoint_ok",
    "token_bus_ok",
    "heal_bus_ok",
    "critic_edge_wired",
    "checkpoint_invoked",
    "langgraph_send_wired",
    "promotion_gate_passed",
    "gitpython_invoke_ok",
    "facade_guard_ok",
    "mirror_registry_ok",
    "aaq_ok",
    "pytest_slice_ok",
    "memory_bus_ok",
    "child_wf_ok",
    "signal_feed_ok",
    "instructor_ok",
    "openhands_activity_ok",
    "glue_seam_invoke_ok",
    "worker_lane_ok",
    "pro_review_ok",
    "worker_lane_integrated_bus_bound",
)
REQUIRED_LANGGRAPH_TRUE_CHECKS = tuple(
    "pro_review_contract_satisfied" if name == "pro_review_ok" else name
    for name in LEGACY_REQUIRED_LANGGRAPH_TRUE_CHECKS
)


def _strict_grok_frontier_enabled(workflow_input: dict[str, Any]) -> bool:
    """Default new histories to full-frontier acceptance; replay old histories unchanged."""

    if workflow.patched(GROK_FULL_FRONTIER_DEFAULT_PATCH_ID):
        return True
    return (
        workflow.patched(GROK_FULL_FRONTIER_ACCEPTANCE_PATCH_ID)
        and workflow_input.get("grok_full_frontier_acceptance_v1") is True
    )


def _is_legacy_completed_grok_lane(item: object) -> bool:
    """Replay-only acceptance for histories recorded before model attestation."""

    return bool(
        isinstance(item, dict)
        and item.get("ok") is True
        and str(item.get("provider_id") or "") == GROK_PROVIDER_ID
        and str(item.get("operation_state") or "") == "completed"
        and str(item.get("operation_id") or "").strip()
        and str(item.get("model") or "").lower().startswith("grok")
        and str(item.get("result_text") or "").strip()
    )


def _is_accepted_grok_lane(item: object, *, attested_lane_acceptance: bool) -> bool:
    """Select the result predicate behind its own replay-safe patch boundary."""

    if attested_lane_acceptance:
        return is_completed_grok_lane(item)
    return _is_legacy_completed_grok_lane(item)


def _containerize_input_ref(value: object) -> str:
    """Map the runtime and both launcher-backed repo identities into container mounts."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return DEFAULT_LANGGRAPH_INPUT_REF
    if raw.startswith("/app/") or raw.startswith("/evidence/"):
        return raw

    folded = raw.casefold()
    runtime_prefix = "d:/xinao_research_runtime/"
    repo_prefix = "e:/xinao_research_workspaces/s/"
    active_repo_prefix = "e:/xinao_research_workspaces/nianhua-new-route-active/"
    if folded.startswith(runtime_prefix):
        return "/evidence/" + raw[len(runtime_prefix) :]
    if folded.startswith(repo_prefix):
        return "/app/" + raw[len(repo_prefix) :]
    if folded.startswith(active_repo_prefix):
        return "/app/" + raw[len(active_repo_prefix) :]
    raise ValueError(f"input ref is outside canonical container mounts: {raw}")


def build_langgraph_child_spec(
    workflow_input: dict[str, Any],
    *,
    step_index: int,
    started: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic child-workflow command for the Docker worker."""
    raw_cfg = workflow_input.get("langgraph_child")
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    configured_ref = str(cfg.get("input_ref") or "").strip()
    intake = (started or {}).get("intake")
    materialized_ref = ""
    if isinstance(intake, dict) and intake.get("ok") is True:
        materialized_ref = str(intake.get("container_path") or "").strip()
    input_ref = configured_ref
    if not input_ref or input_ref == DEFAULT_LANGGRAPH_INPUT_REF:
        input_ref = materialized_ref or configured_ref

    parent_id = str(workflow_input.get("workflow_id") or workflow_input.get("task_id") or "")
    child_id = f"{parent_id}-langgraph-s{step_index}"
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "workflow_id": child_id,
        "workflow_type": str(cfg.get("workflow_type") or DEFAULT_LANGGRAPH_CHILD_WORKFLOW),
        "task_queue": str(cfg.get("task_queue") or DEFAULT_LANGGRAPH_CHILD_QUEUE),
        "input": {
            "input_path": _containerize_input_ref(input_ref),
            "params_path": DEFAULT_LANGGRAPH_PARAMS_REF,
            "repo_root": "/app",
            "runtime_root": "/evidence",
            "workflow_id": child_id,
            "episode_phase": 3,
            "episode_max_phase": 3,
            "react_loop_count": 0,
            "heal_retry_count": 0,
            "heal_failed_checks": [],
        },
    }


def summarize_langgraph_child(
    spec: dict[str, Any],
    result: object,
    *,
    required_worker_provider: str = "",
    parent_grok_fanin: dict[str, Any] | None = None,
    strict_parent_fanin: bool = True,
    strict_grok_only: bool = True,
    dynamic_provider_acceptance: bool = True,
    legacy_require_child_wf: bool = False,
) -> dict[str, Any]:
    """Keep only acceptance evidence from the large LangGraph result payload."""
    value = result if isinstance(result, dict) else {}
    required_true_checks = (
        REQUIRED_LANGGRAPH_TRUE_CHECKS
        if dynamic_provider_acceptance
        else LEGACY_REQUIRED_LANGGRAPH_TRUE_CHECKS
    )
    checks = {name: value.get(name) is True for name in required_true_checks}
    checks.update(
        {
            "content_present": bool(str(value.get("content_md") or "").strip()),
            "parallel_succeeded": int(value.get("parallel_succeeded") or 0) >= 1,
            "worker_lane_provider_present": bool(str(value.get("worker_lane_provider") or "").strip()),
            "worker_lane_model_present": bool(str(value.get("worker_lane_model") or "").strip()),
            "promotion_evidence_present": bool(str(value.get("promotion_evidence_ref") or "").strip()),
            "pytest_slice_ref_present": bool(str(value.get("pytest_slice_ref") or "").strip()),
            "proof_path_present": bool(str(value.get("proof_path") or "").strip()),
        }
    )
    if dynamic_provider_acceptance:
        checks.update(
            {
                "selected_provider_fail_closed": (value.get("selected_provider_fail_closed") is True),
                "provider_fanin_ok": value.get("provider_fanin_ok") is True,
                "provider_validator_present": bool(str(value.get("provider_validator_id") or "").strip()),
                "provider_evidence_bound": value.get("provider_evidence_bound") is True,
                "fallback_model_invocation_not_performed": (
                    value.get("fallback_model_invocation_performed") is False
                ),
                "memory_model_bind_frozen": (value.get("memory_model_bind_frozen") is True),
            }
        )
    elif strict_grok_only:
        checks.update(
            {
                "grok_only_mode": value.get("grok_only_mode") is True,
                "grok_fanin_ok": value.get("grok_fanin_ok") is True,
                "grok_fanin_manifest_present": bool(str(value.get("grok_fanin_manifest_ref") or "").strip()),
                "non_grok_model_invocations_zero": (value.get("non_grok_model_invocations") == 0),
                "fallback_model_invocation_not_performed": (
                    value.get("fallback_model_invocation_performed") is False
                ),
                "memory_model_bind_frozen": (value.get("memory_model_bind_frozen") is True),
                "pro_review_provider_is_grok": (
                    str(value.get("pro_review_provider") or "") == GROK_PROVIDER_ID
                ),
            }
        )
    if required_worker_provider:
        checks["worker_lane_provider_matches_required"] = (
            str(value.get("worker_lane_provider") or "") == required_worker_provider
        )
    # This summary is produced only after the parent Temporal workflow has
    # awaited the canonical XinaoIntegratedBusWorkflow child.  Requiring that
    # child to report another nested ``child_wf_ok`` would turn an already
    # proven parent->child boundary into an accidental recursion requirement.
    # Keep the raw value visible, but classify that legacy inner-child probe as
    # not applicable at this boundary.
    not_applicable_checks: set[str] = set()
    not_applicable_reasons: list[str] = []
    if not legacy_require_child_wf:
        not_applicable_checks.add("child_wf_ok")
        not_applicable_reasons.append("parent_temporal_langgraph_child")
    strict_selected_provider = strict_grok_only or dynamic_provider_acceptance
    if parent_grok_fanin is not None and not strict_selected_provider:
        # Histories created before the Grok-only child acceptance contract did
        # not emit the newer child-side fan-in fields.  The parent frontier had
        # already performed that work, so preserve their original acceptance
        # shape during replay without weakening any new execution.
        not_applicable_checks.update({"langgraph_send_wired", "parallel_succeeded"})
        not_applicable_reasons.append("legacy_parent_grok_ready_frontier_fanin")
    if parent_grok_fanin is not None and strict_selected_provider:
        checks["parent_grok_fanin_ok"] = parent_grok_fanin.get("ok") is True
        checks["parent_grok_fanin_provider_matches"] = (
            str(parent_grok_fanin.get("provider_id") or "") == GROK_PROVIDER_ID
        )
        succeeded = int(parent_grok_fanin.get("succeeded") or 0)
        failed = int(parent_grok_fanin.get("failed") or 0)
        lane_count = int(parent_grok_fanin.get("lane_count") or 0)
        ready_width = int(parent_grok_fanin.get("ready_width") or 0)
        if strict_parent_fanin:
            checks["parent_grok_fanin_succeeded"] = (
                succeeded >= 1 and failed == 0 and succeeded == lane_count and ready_width == lane_count
            )
            checks["parent_grok_fanin_width_present"] = lane_count >= 1 and ready_width == lane_count
            checks["child_grok_width_matches_parent"] = (
                int(value.get("grok_fanin_lane_count") or 0) == lane_count
            )
            checks["parent_grok_fanin_model_matches_child"] = str(
                parent_grok_fanin.get("model") or ""
            ) == str(value.get("worker_lane_model") or "")
        else:
            legacy_width = lane_count or ready_width
            checks["parent_grok_fanin_succeeded"] = succeeded >= 1
            checks["parent_grok_fanin_width_present"] = legacy_width >= 1
            checks["child_grok_width_matches_parent"] = (
                int(value.get("grok_fanin_lane_count") or 0) == legacy_width
            )
        parent_prefan_valid = (
            all(
                checks[name]
                for name in (
                    "parent_grok_fanin_ok",
                    "parent_grok_fanin_provider_matches",
                    "parent_grok_fanin_succeeded",
                    "parent_grok_fanin_width_present",
                    "worker_lane_provider_matches_required",
                    "child_grok_width_matches_parent",
                    *(("parent_grok_fanin_model_matches_child",) if strict_parent_fanin else ()),
                )
            )
            and str(value.get("worker_lane_mode") or "") == "grok_ready_frontier_fanin"
        )
        if parent_prefan_valid:
            # These checks describe fan-out performed inside the child graph.  A
            # Temporal Grok frontier has already completed that fan-out and the
            # child is consuming its verified fan-in, so repeating it would be
            # duplicate work.  Keep the raw false values visible; mark them N/A
            # instead of manufacturing green evidence.
            not_applicable_checks.update(
                {
                    "langgraph_send_wired",
                    "parallel_succeeded",
                }
            )
            if parent_grok_fanin.get("execution_location") == "docker:houtai-gongren":
                not_applicable_reasons.append("docker_native_langgraph_grok_fanin")
            else:
                not_applicable_reasons.append("parent_grok_ready_frontier_fanin")
    failed_checks = sorted(
        name for name, passed in checks.items() if not passed and name not in not_applicable_checks
    )
    return {
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "not_applicable_checks": sorted(not_applicable_checks),
        "not_applicable_reason": "+".join(not_applicable_reasons),
        "workflow_id": spec["workflow_id"],
        "workflow_type": spec["workflow_type"],
        "task_queue": spec["task_queue"],
        "input_path": spec["input"]["input_path"],
        "proof_path": str(value.get("proof_path") or ""),
        "promotion_evidence_ref": str(value.get("promotion_evidence_ref") or ""),
        "pytest_slice_ref": str(value.get("pytest_slice_ref") or ""),
        "worker_lane_mode": str(value.get("worker_lane_mode") or ""),
        "worker_lane_provider": str(value.get("worker_lane_provider") or ""),
        "worker_lane_model": str(value.get("worker_lane_model") or ""),
        "parallel_width_n": int(value.get("parallel_width_n") or 0),
        "parallel_succeeded": int(value.get("parallel_succeeded") or 0),
    }


def _activity_kwargs(
    retry_policy: RetryPolicy | None = None,
) -> dict[str, Any]:
    return {
        "start_to_close_timeout": DEFAULT_START_TO_CLOSE,
        "heartbeat_timeout": timedelta(seconds=15),
        "retry_policy": retry_policy or DEFAULT_ACTIVITY_RETRY,
    }


@workflow.defn(name=WORKFLOW_TYPE, versioning_behavior=VersioningBehavior.PINNED)
class XinaoPromotedTaskWorkflowV1:
    """Promoted-task only durable workflow (never chat/discuss bus owner)."""

    def __init__(self) -> None:
        self._status: str = "pending"
        self._paused: bool = False
        self._cancel_requested: bool = False
        self._cancel_reason: str = ""
        self._progress: float = 0.0
        self._note: str = ""
        self._task_id: str = ""
        self._generation: int = 0
        self._last_phase: str = "init"
        self._steps_completed: int = 0
        self._current_child_workflow_id: str = ""
        self._langgraph_children: list[dict[str, Any]] = []
        self._step_evidence: list[dict[str, Any]] = []
        self._use_langgraph_child: bool = False
        self._use_grok_frontier: bool = False
        self._grok_lanes: list[dict[str, Any]] = []
        self._grok_fanin: dict[str, Any] = {}
        self._correlation_id: str = ""
        self._parent_operation_id: str = ""

    # --- Signals (mutate state; no return) ---------------------------------

    @workflow.signal
    def request_cancel(self, reason: str = "") -> None:
        """Soft cancel signal (also works with handle.cancel())."""
        self._cancel_requested = True
        self._cancel_reason = reason or "signal:request_cancel"
        self._note = self._cancel_reason

    @workflow.signal
    def pause(self) -> None:
        self._paused = True
        self._note = "paused"

    @workflow.signal
    def resume(self) -> None:
        self._paused = False
        if self._status == "paused":
            self._status = "running"
        self._note = "resumed"

    @workflow.signal
    def set_note(self, note: str) -> None:
        self._note = str(note or "")

    # --- Queries (read-only; sync def) -------------------------------------

    @workflow.query
    def get_status(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "paused": self._paused,
            "cancel_requested": self._cancel_requested,
            "cancel_reason": self._cancel_reason,
            "progress": self._progress,
            "note": self._note,
            "task_id": self._task_id,
            "generation": self._generation,
            "last_phase": self._last_phase,
            "steps_completed": self._steps_completed,
            "current_child_workflow_id": self._current_child_workflow_id,
            "langgraph_children": list(self._langgraph_children),
            "step_evidence": list(self._step_evidence),
            "grok_lanes": list(self._grok_lanes),
            "grok_fanin": dict(self._grok_fanin),
            "correlation_id": self._correlation_id,
            "parent_operation_id": self._parent_operation_id,
            "workflow_type": WORKFLOW_TYPE,
        }

    @workflow.query
    def get_progress(self) -> float:
        return float(self._progress)

    # --- Run ---------------------------------------------------------------

    @workflow.run
    async def run(self, workflow_input: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(workflow_input, dict):
            raise TypeError("workflow_input must be a dict envelope")
        if not workflow_input.get("promoted_only", True):
            raise ValueError("chat/discuss-shaped payload cannot enter Temporal")

        self._task_id = str(workflow_input.get("task_id") or "")
        self._generation = int(workflow_input.get("generation") or 0)
        self._correlation_id = str(workflow_input.get("correlation_id") or "").strip()
        self._parent_operation_id = str(workflow_input.get("parent_operation_id") or "").strip()
        self._status = "validating"
        self._last_phase = "validating"

        try:
            validated = await workflow.execute_activity(
                validate_promoted_envelope,
                {**workflow_input, "operation_id": f"validate:{self._task_id}"},
                **_activity_kwargs(),
            )
            self._progress = 0.15
            self._last_phase = str(validated.get("phase") or "validated")
            self._status = "starting"

            started = await workflow.execute_activity(
                record_promoted_started,
                {
                    **workflow_input,
                    "operation_id": f"start:{self._task_id}:g{self._generation}",
                },
                **_activity_kwargs(),
            )
            self._progress = 0.30
            self._last_phase = str(started.get("phase") or "started")
            self._status = "running"

            use_langgraph_child = workflow.patched(LANGGRAPH_CHILD_PATCH_ID)
            self._use_langgraph_child = use_langgraph_child
            use_grok_frontier = workflow.patched(GROK_FRONTIER_PATCH_ID)
            self._use_grok_frontier = use_grok_frontier
            docker_first_grok = bool(
                use_langgraph_child and use_grok_frontier and workflow.patched(GROK_DOCKER_FIRST_PATCH_ID)
            )

            if use_grok_frontier and not docker_first_grok:
                started = await self._execute_grok_frontier(workflow_input, started)
                if self._cancel_requested:
                    return await self._finalize(workflow_input, terminal="cancelled")

            # Optional pause gate before work steps
            await self._wait_while_paused_or_cancel()

            step_count = int(workflow_input.get("step_count") or 1)
            step_count = max(1, min(step_count, 8))
            for step_index in range(step_count):
                await self._wait_while_paused_or_cancel()
                if self._cancel_requested:
                    break
                child_summary: dict[str, Any] | None = None
                try:
                    child_spec = build_langgraph_child_spec(
                        workflow_input,
                        step_index=step_index,
                        started=started,
                    )
                except ValueError as exc:
                    self._status = "failed"
                    raise ApplicationError(
                        str(exc),
                        type="LangGraphInputRefError",
                        non_retryable=True,
                    ) from exc
                if docker_first_grok:
                    child_spec["input"].update(
                        {
                            "grok_ready_frontier": workflow_input.get("grok_ready_frontier"),
                            "grok_serial_reason": str(workflow_input.get("grok_serial_reason") or ""),
                            "correlation_id": self._correlation_id,
                            "parent_operation_id": self._parent_operation_id,
                        }
                    )
                    if workflow.patched(GROK_SUPERVISOR_SELECTION_RECEIPT_PATCH_ID):
                        child_spec["input"].update(
                            {
                                "supervisor_selection_required": True,
                                "supervisor_worker_decision": workflow_input.get(
                                    "supervisor_worker_decision"
                                ),
                            }
                        )
                if use_langgraph_child and child_spec["enabled"] is not True:
                    self._status = "failed"
                    raise ApplicationError(
                        "canonical LangGraph child cannot be disabled for a new promoted workflow",
                        type="LangGraphChildDisabledError",
                        non_retryable=True,
                    )
                if use_langgraph_child and child_spec["enabled"]:
                    self._last_phase = "langgraph_child"
                    child_result = await self._execute_langgraph_child(child_spec)
                    if self._cancel_requested:
                        break
                    if docker_first_grok:
                        child_lanes = (
                            child_result.get("grok_lanes")
                            if isinstance(child_result.get("grok_lanes"), list)
                            else []
                        )
                        child_fanin = (
                            child_result.get("grok_fanin")
                            if isinstance(child_result.get("grok_fanin"), dict)
                            else {}
                        )
                        self._grok_lanes = [dict(item) for item in child_lanes if isinstance(item, dict)]
                        self._grok_fanin = dict(child_fanin)
                        if not self._grok_lanes or self._grok_fanin.get("ok") is not True:
                            self._status = "failed"
                            raise ApplicationError(
                                "Docker LangGraph child did not complete its Grok frontier",
                                {
                                    "grok_lanes": self._grok_lanes,
                                    "grok_fanin": self._grok_fanin,
                                },
                                type="DockerNativeGrokFrontierError",
                                non_retryable=True,
                            )
                    legacy_strict_child_acceptance = workflow.patched(LANGGRAPH_GROK_ONLY_ACCEPTANCE_PATCH_ID)
                    dynamic_provider_acceptance = workflow.patched(
                        LANGGRAPH_DYNAMIC_PROVIDER_ACCEPTANCE_PATCH_ID
                    )
                    strict_child_acceptance = (
                        legacy_strict_child_acceptance and not dynamic_provider_acceptance
                    )
                    parent_grok_fanin = (
                        self._grok_fanin
                        if self._grok_lanes
                        and (docker_first_grok or workflow.patched(GROK_PREFAN_ACCEPTANCE_PATCH_ID))
                        else None
                    )
                    legacy_require_child_wf = (
                        not strict_child_acceptance
                        and parent_grok_fanin is None
                        and workflow.info().get_current_build_id() in LEGACY_CHILD_WF_REQUIRED_BUILD_IDS
                    )
                    child_summary = summarize_langgraph_child(
                        child_spec,
                        child_result,
                        required_worker_provider=(GROK_PROVIDER_ID if self._grok_lanes else ""),
                        parent_grok_fanin=parent_grok_fanin,
                        strict_parent_fanin=_strict_grok_frontier_enabled(workflow_input),
                        strict_grok_only=strict_child_acceptance,
                        dynamic_provider_acceptance=dynamic_provider_acceptance,
                        legacy_require_child_wf=legacy_require_child_wf,
                    )
                    self._langgraph_children.append(child_summary)
                    if child_summary["passed"] is not True:
                        self._status = "failed"
                        raise ApplicationError(
                            "LangGraph child did not meet the promoted-task acceptance gate",
                            child_summary,
                            type="LangGraphChildAcceptanceError",
                            non_retryable=True,
                        )
                step_payload = {
                    **workflow_input,
                    "operation_id": (f"step:{self._task_id}:g{self._generation}:{step_index}"),
                    "step_index": step_index,
                }
                if use_langgraph_child:
                    step_payload["langgraph_child"] = child_summary
                step_result = await workflow.execute_activity(
                    execute_promoted_step,
                    step_payload,
                    **_activity_kwargs(),
                )
                if step_result.get("ok") is not True:
                    self._status = "failed"
                    raise ApplicationError(
                        "promoted step evidence write failed",
                        step_result,
                        type="PromotedStepEvidenceError",
                        non_retryable=True,
                    )
                artifact = step_result.get("artifact")
                self._step_evidence.append(
                    {
                        "step_index": step_index,
                        "operation_id": step_result.get("operation_id"),
                        "artifact": artifact if isinstance(artifact, dict) else {},
                        "langgraph_evidence": step_result.get("langgraph_evidence"),
                    }
                )
                self._steps_completed += 1
                self._last_phase = str(step_result.get("phase") or "step_done")
                self._progress = 0.30 + (0.55 * (step_index + 1) / step_count)

            if self._cancel_requested:
                return await self._finalize(workflow_input, terminal="cancelled")

            return await self._finalize(workflow_input, terminal="completed")

        except (asyncio.CancelledError, TemporalCancelledError):
            self._cancel_requested = True
            self._cancel_reason = self._cancel_reason or "workflow_cancelled"
            # Best-effort finalize; re-raise so Temporal records cancellation.
            with contextlib.suppress(Exception):
                await self._finalize(
                    workflow_input,
                    terminal="cancelled",
                    # Cancellation path: limited retries
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        backoff_coefficient=1.5,
                        maximum_interval=timedelta(seconds=5),
                        maximum_attempts=3,
                    ),
                )
            raise

        except TemporalError:
            self._status = "failed"
            if not self._last_phase.startswith("finalize:"):
                with contextlib.suppress(TemporalError):
                    await self._finalize(workflow_input, terminal="failed")
            raise

    async def _execute_langgraph_child(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Run one child while preserving soft-cancel propagation from the parent."""
        self._current_child_workflow_id = str(spec["workflow_id"])
        child_task = asyncio.create_task(
            workflow.execute_child_workflow(
                str(spec["workflow_type"]),
                spec["input"],
                id=str(spec["workflow_id"]),
                task_queue=str(spec["task_queue"]),
                result_type=dict,
                cancellation_type=(workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED),
                parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
                execution_timeout=timedelta(minutes=30),
            )
        )
        cancel_wait = asyncio.create_task(workflow.wait_condition(lambda: self._cancel_requested))
        try:
            done, _ = await workflow.wait(
                [child_task, cancel_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_wait in done and self._cancel_requested:
                child_task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    TemporalCancelledError,
                ):
                    await child_task
                return {}
            return await child_task
        finally:
            if not cancel_wait.done():
                cancel_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_wait
            if not child_task.done():
                child_task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError,
                    TemporalCancelledError,
                ):
                    await child_task
            self._current_child_workflow_id = ""

    async def _execute_grok_frontier(
        self,
        workflow_input: dict[str, Any],
        started: dict[str, Any],
    ) -> dict[str, Any]:
        serial_reason = str(workflow_input.get("grok_serial_reason") or "")
        composer_model_policy = workflow.patched(GROK_COMPOSER_DEFAULT_PATCH_ID)
        explicit_supervisor_selection = workflow.patched(GROK_EXPLICIT_SUPERVISOR_SELECTION_PATCH_ID)
        attested_lane_acceptance = workflow.patched(GROK_ATTESTED_LANE_ACCEPTANCE_PATCH_ID)
        default_model = GROK_DEFAULT_MODEL if composer_model_policy else GROK_LEGACY_DEFAULT_MODEL
        try:
            lanes = validate_ready_frontier(
                workflow_input.get("grok_ready_frontier"),
                serial_reason=serial_reason,
                default_model=default_model,
                require_explicit_model=explicit_supervisor_selection,
                require_explicit_cwd=explicit_supervisor_selection,
            )
        except ValueError as exc:
            raise ApplicationError(
                str(exc),
                type="GrokReadyFrontierError",
                non_retryable=True,
            ) from exc
        if not lanes:
            return started

        self._status = "running"
        self._last_phase = "grok_ready_frontier"
        tasks: list[asyncio.Task[dict[str, Any]]] = []
        for lane in lanes:
            payload = {
                **lane,
                "workflow_id": str(workflow_input.get("workflow_id") or ""),
                "serial_reason": serial_reason,
            }
            if self._correlation_id:
                payload["correlation_id"] = self._correlation_id
            if self._parent_operation_id:
                payload["parent_operation_id"] = self._parent_operation_id
            tasks.append(
                asyncio.create_task(
                    workflow.execute_activity(
                        execute_grok_acpx_lane,
                        payload,
                        start_to_close_timeout=timedelta(seconds=int(lane["deadline_seconds"]) + 180),
                        heartbeat_timeout=timedelta(seconds=15),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=2),
                            backoff_coefficient=2.0,
                            maximum_interval=timedelta(seconds=30),
                            maximum_attempts=2,
                            non_retryable_error_types=["ValueError", "TypeError"],
                        ),
                    )
                )
            )
        all_lanes = asyncio.create_task(self._gather_grok_tasks(tasks))
        cancel_wait = asyncio.create_task(workflow.wait_condition(lambda: self._cancel_requested))
        try:
            done, _ = await workflow.wait(
                [all_lanes, cancel_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_wait in done and self._cancel_requested:
                all_lanes.cancel()
                with contextlib.suppress(asyncio.CancelledError, TemporalCancelledError):
                    await all_lanes
                return started
            self._grok_lanes = await all_lanes
        finally:
            if not cancel_wait.done():
                cancel_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_wait
            for task in tasks:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(
                        asyncio.CancelledError,
                        TemporalCancelledError,
                    ):
                        await task

        require_full_frontier = _strict_grok_frontier_enabled(workflow_input)
        if require_full_frontier and not all(
            _is_accepted_grok_lane(
                item,
                attested_lane_acceptance=attested_lane_acceptance,
            )
            for item in self._grok_lanes
        ):
            raise ApplicationError(
                "Grok ready-frontier did not complete every lane",
                {"lanes": self._grok_lanes},
                type="GrokReadyFrontierPartial",
                non_retryable=True,
            )
        if not require_full_frontier and not any(item.get("ok") is True for item in self._grok_lanes):
            raise ApplicationError(
                "no Grok ready-frontier lane completed",
                {"lanes": self._grok_lanes},
                type="GrokReadyFrontierFailed",
                non_retryable=True,
            )
        intake = started.get("intake")
        base_path = str(intake.get("artifact_path") or "") if isinstance(intake, dict) else ""
        fanin_payload = {
            "workflow_id": str(workflow_input.get("workflow_id") or ""),
            "base_intake_path": base_path,
            "lane_results": self._grok_lanes,
            "serial_reason": serial_reason,
            "require_full_frontier": require_full_frontier,
        }
        if self._correlation_id:
            fanin_payload["correlation_id"] = self._correlation_id
        if self._parent_operation_id:
            fanin_payload["parent_operation_id"] = self._parent_operation_id
        self._grok_fanin = await workflow.execute_activity(
            materialize_grok_acpx_fanin,
            fanin_payload,
            **_activity_kwargs(),
        )
        return {**started, "intake": self._grok_fanin["intake"]}

    @staticmethod
    async def _gather_grok_tasks(
        tasks: list[asyncio.Task[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        return list(await asyncio.gather(*tasks))

    async def _wait_while_paused_or_cancel(self) -> None:
        """Block while paused; exit early if cancel requested or workflow cancelled."""
        while self._paused and not self._cancel_requested:
            self._status = "paused"
            # wait_condition wakes on signals / cancel
            await workflow.wait_condition(
                lambda: (not self._paused) or self._cancel_requested,
                timeout=timedelta(hours=24),
            )
        if self._cancel_requested:
            return
        if self._status == "paused":
            self._status = "running"

    async def _finalize(
        self,
        workflow_input: dict[str, Any],
        *,
        terminal: str,
        retry_policy: RetryPolicy | None = None,
    ) -> dict[str, Any]:
        self._status = terminal
        self._last_phase = f"finalize:{terminal}"
        self._progress = 1.0 if terminal == "completed" else self._progress
        finalize_payload = {
            **workflow_input,
            "operation_id": f"finalize:{self._task_id}:{terminal}",
            "terminal_status": terminal,
            "note": self._note or self._cancel_reason,
        }
        if self._use_langgraph_child:
            finalize_payload["langgraph_children"] = list(self._langgraph_children)
            finalize_payload["step_evidence"] = list(self._step_evidence)
        if self._use_grok_frontier:
            finalize_payload["grok_lanes"] = list(self._grok_lanes)
            finalize_payload["grok_fanin"] = dict(self._grok_fanin)
        finalized = await workflow.execute_activity(
            finalize_promoted_task,
            finalize_payload,
            **_activity_kwargs(retry_policy),
        )
        if finalized.get("ok") is not True:
            raise ApplicationError(
                "kernel terminal convergence failed",
                finalized,
                type="KernelTerminalConvergenceError",
                non_retryable=True,
            )
        result = {
            "ok": terminal == "completed",
            "terminal_status": terminal,
            "task_id": self._task_id,
            "generation": self._generation,
            "steps_completed": self._steps_completed,
            "progress": self._progress,
            "note": self._note,
            "cancel_requested": self._cancel_requested,
            "langgraph_children": list(self._langgraph_children),
            "step_evidence": list(self._step_evidence),
            "grok_lanes": list(self._grok_lanes),
            "grok_fanin": dict(self._grok_fanin),
            "finalize": finalized,
            "workflow_type": WORKFLOW_TYPE,
        }
        if self._correlation_id:
            result["correlation_id"] = self._correlation_id
        if self._parent_operation_id:
            result["parent_operation_id"] = self._parent_operation_id
        return result


PROMOTED_WORKFLOWS = (XinaoPromotedTaskWorkflowV1,)

__all__ = [
    "DEFAULT_LANGGRAPH_CHILD_QUEUE",
    "DEFAULT_LANGGRAPH_CHILD_WORKFLOW",
    "DEFAULT_LANGGRAPH_INPUT_REF",
    "DEFAULT_TASK_QUEUE",
    "GROK_DOCKER_FIRST_PATCH_ID",
    "GROK_EXPLICIT_SUPERVISOR_SELECTION_PATCH_ID",
    "GROK_FRONTIER_PATCH_ID",
    "GROK_SUPERVISOR_SELECTION_RECEIPT_PATCH_ID",
    "LANGGRAPH_CHILD_PATCH_ID",
    "LANGGRAPH_GROK_ONLY_ACCEPTANCE_PATCH_ID",
    "LEGACY_CHILD_WF_REQUIRED_BUILD_IDS",
    "PROMOTED_WORKFLOWS",
    "REQUIRED_LANGGRAPH_TRUE_CHECKS",
    "WORKFLOW_TYPE",
    "XinaoPromotedTaskWorkflowV1",
    "_containerize_input_ref",
    "build_langgraph_child_spec",
    "summarize_langgraph_child",
]
