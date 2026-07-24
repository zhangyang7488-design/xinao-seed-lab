"""Temporal LangGraphPlugin integrated bus — Langfuse + PromotionGate on default hot path."""

from __future__ import annotations

import hashlib
import json
import operator
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Mapping

from langgraph.graph import START, StateGraph
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.contrib.langgraph import cache
from temporalio.contrib.langgraph import graph as temporal_graph
from temporalio.exceptions import ApplicationError
from typing_extensions import TypedDict

from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
    artifact_json_bytes,
    build_common_receipt_binding,
    canonical_json_bytes,
    logical_contract_sha256,
    validate_attempt_receipt,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DOCKER_CONSUMER_ID,
    expected_docker_grok_backend_models,
    grok_docker_model_identity_binding,
    validate_grok_session_model_evidence,
)
from services.agent_runtime.integrated_bus_bus_nodes import (
    resolve_bus_file_path,
    resolve_repo_root,
    resolve_runtime_root,
    run_aaq_fanin_bus,
    run_checkpoint_bus,
    run_crawl4ai_bus,
    run_duckdb_bus,
    run_episode_cache_bus,
    run_facade_guard_bus,
    run_fanin_bus,
    run_glue_seam_invoke_bus,
    run_heal_bus,
    run_hitl_review_bus,
    run_mcp_tools_bus,
    run_memory_bus,
    run_mirror_registry_bus,
    run_openhands_bus,
    run_planner_bus,
    run_pytest_slice_bus,
    run_search_bus,
    run_signal_feed_bus,
    run_token_bus,
    run_validate_bus,
    run_watchdog_bus,
)
from services.agent_runtime.integrated_bus_promotion_gate import run_promotion_gate
from services.agent_runtime.routing_policy_reader import resolve_parallel_semantic
from services.agent_runtime.thin_glue_stack import (
    DEFAULT_REPO,
    DEFAULT_RUNTIME,
    default_intake_candidates,
    l0_intake_markdown,
    l3_run_sandbox,
    now_iso,
    resolve_intake_source,
)

GRAPH_ID = "xinao-integrated-bus-v2"
GROK_HEARTBEAT_GRAPH_ID = "xinao-integrated-bus-v2-grok-heartbeat-v1"
GROK_HEARTBEAT_PATCH_ID = "integrated-bus-grok-heartbeat-v1"
GROK_RECOVERY_GRAPH_ID = "xinao-integrated-bus-v2-grok-recovery-v1"
GROK_RECOVERY_PATCH_ID = "integrated-bus-grok-recovery-v1"
GROK_FANIN_SENTINEL = "XINAO_GROK_TEMPORAL_FANIN_V1"
GROK_FANIN_PROVIDER = "grok_acpx_headless"
GROK_FANIN_PROFILE = "grok.com.cached_profile"
GROK_FANIN_TRANSPORT = "temporal-docker-langgraph"
GROK_FANIN_DEFAULT_MODEL = "grok-composer-2.5-fast"
GROK_FANIN_ESCALATION_MODEL = "grok-4.5"
GROK_FANIN_ALLOWED_MODELS = frozenset({GROK_FANIN_DEFAULT_MODEL, GROK_FANIN_ESCALATION_MODEL})
GROK_MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v2"
GROK_FANIN_SCHEMA_VERSION = "xinao.grok.temporal_acpx_fanin.v2"
GROK_EXECUTION_CONTRACT_VERSION = "xinao.grok.shared_execution_contract.v1"
_GROK_MANIFEST_RE = re.compile(r"grok_manifest_path=([^\s>]+)")
DEFAULT_PARAMS = (
    DEFAULT_REPO / "materials" / "authority_glue" / "seams" / "integrated_bus_params.v1.json"
)


def _grok_invocation_accounting_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    total = int(value.get("total_tokens") or 0)
    accepted = int(value.get("accepted_tokens") or 0)
    cancelled = int(value.get("cancelled_tokens") or 0)
    failed = int(value.get("failed_tokens") or 0)
    return bool(
        int(value.get("invocation_count") or 0) >= 1
        and total > 0
        and accepted > 0
        and total == accepted + cancelled + failed
    )


def _grok_embedded_artifact_binding_valid(
    value: dict[str, Any],
    *,
    declared_sha256: object,
    raw_ref: object,
    runtime: Path,
    repo_root: Path,
) -> bool:
    """Bind an embedded common record to its exact evidence artifact bytes."""

    declared = str(declared_sha256 or "")
    expected_raw = artifact_json_bytes(value)
    if hashlib.sha256(expected_raw).hexdigest() != declared:
        return False
    ref = str(raw_ref or "").strip()
    if not ref:
        return True
    try:
        artifact_path = resolve_bus_file_path(
            ref,
            repo_root=repo_root,
            runtime_root=runtime,
        ).resolve()
        artifact_path.relative_to(runtime)
        raw = artifact_path.read_bytes()
        decoded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return hashlib.sha256(raw).hexdigest() == declared and raw == expected_raw and decoded == value


def _grok_raw_model_identity_valid(
    lane: dict[str, Any],
    *,
    requested_model: str,
    runtime: Path,
    repo_root: Path,
) -> bool:
    """Verify Docker model identity from the bound CLI payload, not wrapper claims."""

    ref = str(lane.get("model_identity_ref") or "").strip()
    declared = str(lane.get("model_identity_sha256") or "").strip()
    if not ref or not declared:
        return False
    try:
        identity_path = resolve_bus_file_path(
            ref,
            repo_root=repo_root,
            runtime_root=runtime,
        ).resolve()
        identity_path.relative_to(runtime)
        raw = identity_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    model_usage = payload.get("modelUsage")
    if not isinstance(model_usage, dict):
        return False
    observed_models = sorted(
        str(model)
        for model, stats in model_usage.items()
        if isinstance(stats, dict) and int(stats.get("modelCalls") or 0) > 0
    )
    evidence = lane.get("session_model_evidence")
    receipt = lane.get("cross_seam_attempt_receipt")
    receipt_observed = receipt.get("observed") if isinstance(receipt, dict) else None
    receipt_invocations = receipt.get("invocations") if isinstance(receipt, dict) else None
    try:
        expected_backend_models = expected_docker_grok_backend_models(requested_model)
        expected_identity_binding = grok_docker_model_identity_binding(requested_model)
        if not isinstance(evidence, dict):
            return False
        validated_session_evidence = validate_grok_session_model_evidence(
            evidence,
            selected_model=requested_model,
            session_id=str(lane.get("agent_session_id") or ""),
        )
    except ValueError:
        return False
    return bool(
        hashlib.sha256(raw).hexdigest() == declared
        and observed_models == expected_backend_models
        and lane.get("observed_model") == expected_backend_models[0]
        and lane.get("observed_models") == expected_backend_models
        and lane.get("observed_backend_models") == expected_backend_models
        and lane.get("model_identity_binding") == expected_identity_binding
        and evidence == validated_session_evidence
        and lane.get("session_model_evidence_valid") is True
        and _grok_embedded_artifact_binding_valid(
            evidence,
            declared_sha256=lane.get("session_model_evidence_sha256"),
            raw_ref=lane.get("session_model_evidence_ref"),
            runtime=runtime,
            repo_root=repo_root,
        )
        and isinstance(receipt_observed, dict)
        and receipt_observed.get("model_id") == requested_model
        and receipt.get("provider_evidence_ref") == ref
        and receipt.get("provider_evidence_sha256") == declared
        and isinstance(receipt_invocations, list)
        and bool(receipt_invocations)
        and all(
            isinstance(invocation, dict) and invocation.get("observed_model") == requested_model
            for invocation in receipt_invocations
        )
    )


class BusState(TypedDict, total=False):
    input_path: str
    science_episode_admission: dict[str, Any]
    science_instrument_mode: str
    science_instrument_admission_consumed: bool
    science_trial_appends: int
    research_progress_claim_allowed: bool
    completion_claim_allowed: bool
    evaluation_outcome_access: bool
    legacy_parent_scope_consumed: bool
    intake_named_blocker: str
    intake_requested_path: str
    intake_used_fallback_text: bool
    duckdb_ok: bool
    duckdb_invoked: bool
    watchdog_ok: bool
    watchdog_invoked: bool
    params_path: str
    repo_root: str
    runtime_root: str
    workflow_id: str
    correlation_id: str
    parent_operation_id: str
    content_md: str
    adapter: str
    execution_stdout: str
    execution_backend: str
    docker_sandbox_invoked: bool
    gateway_trace_ok: bool
    gateway_trace_skipped: bool
    litellm_completion_ok: bool
    litellm_completion_via: str
    langfuse_callback_wired: bool
    langfuse_skipped: bool
    langfuse_named_blocker: str
    gateway_named_blocker: str
    promotion_gate_passed: bool
    memory_candidate_id: str
    memory_candidate_ref: str
    memory_candidate_sha256: str
    promotion_evidence_ref: str
    promotion_source_ledger_ref: str
    promotion_source_ledger_sha256: str
    proof_path: str
    commit_hash: str
    git_commit_adapter: str
    git_snapshot_adapter: str
    gitpython_invoke_ok: bool
    validate_ok: bool
    task_package: dict[str, Any]
    search_ok: bool
    search_query: str
    search_hit_count: int
    search_external_hits: list[dict[str, Any]]
    search_external: dict[str, Any]
    fanin_ok: bool
    fanin_evidence_ref: str
    diff_cover_ok: bool
    otel_ok: bool
    planner_ok: bool
    crawl4ai_ok: bool
    checkpoint_ok: bool
    token_bus_ok: bool
    readback_zh_ref: str
    heal_bus_ok: bool
    heal_repair_required: bool
    heal_retry_count: int
    heal_failed_checks: list[str]
    critic_decision: str
    critic_edge: str
    critic_edge_wired: bool
    retry_policy_evidence_ref: str
    checkpoint_thread_id: str
    checkpoint_invoked: bool
    checkpoint_evidence_ref: str
    jinja_readback_ref: str
    jinja_adapter: str
    planner_structured_by: str
    langgraph_send_wired: Annotated[bool, operator.or_]
    parallel_lane_ok: bool
    parallel_lane_id: int
    signals_continue_as_new_wired: bool
    child_invoked: bool
    mcp_tools_ok: bool
    mcp_tool_invoked: bool
    mcp_adapter: str
    mcp_registry_ok: bool
    parallel_ok: bool
    parallel_width_n: int
    parallel_succeeded: int
    parallel_evidence_ref: str
    facade_guard_ok: bool
    handroll_default_unreachable: bool
    mirror_registry_ok: bool
    mirror_registry_ref: str
    aaq_ok: bool
    aaq_claim_ref: str
    aaq_claim_sha256: str
    aaq_fanin_evidence_sha256: str
    pytest_slice_ok: bool
    pytest_slice_ref: str
    handroll_intact: bool
    signal_feed_ok: bool
    auto_feed_count: int
    child_wf_ok: bool
    child_wf_evidence_ref: str
    instructor_ok: bool
    instructor_invoked: bool
    instructor_enabled: bool
    openhands_ok: bool
    openhands_activity_ok: bool
    memory_bus_ok: bool
    memory_bus_ref: str
    glue_seam_invoke_ok: bool
    glue_seam_invoke_count: int
    glue_seam_invoke_ref: str
    pro_review_ok: bool
    pro_review_status: str
    pro_review_model: str
    pro_review_named_blocker: str
    pro_review_evidence_ref: str
    pro_review_runtime_enforced: bool
    pro_review_trigger_installed: bool
    worker_lane_ok: bool
    worker_lane_status: str
    worker_lane_mode: str
    worker_lane_provider: str
    worker_lane_model: str
    worker_lane_artifact_ref: str
    worker_lane_draft_content: str
    worker_lane_named_blocker: str
    worker_lane_evidence_ref: str
    worker_lane_runtime_enforced: bool
    worker_lane_integrated_bus_bound: bool
    worker_lane_cross_seam_contract_version: str
    worker_lane_cross_seam_receipt_version: str
    worker_lane_cross_seam_receipt_set_sha256: str
    worker_lane_cross_seam_receipt_ok: bool
    worker_lane_adapter: str
    worker_lane_tier: str
    worker_lane_route_role: str
    draft_model: str
    review_model: str
    grok_only_mode: bool
    selected_provider_fail_closed: bool
    grok_fanin_ok: bool
    provider_fanin_ok: bool
    provider_validator_id: str
    provider_evidence_bound: bool
    provider_evidence_ref: str
    provider_evidence_sha256: str
    fanin_evidence_sha256: str
    grok_fanin_manifest_ref: str
    grok_fanin_manifest_sha256: str
    grok_fanin_evidence_ref: str
    grok_fanin_evidence_sha256: str
    grok_fanin_lane_count: int
    grok_fanin_lane_modes: list[str]
    grok_fanin_audit_lane_count: int
    pro_review_reused_fanin_audit: bool
    pro_review_model_invocation_performed: bool
    pro_review_contract_satisfied: bool
    review_required: bool
    post_draft_review: dict[str, Any]
    fanin_audit_presence: bool
    grok_fanin_model_identity_ok: bool
    grok_fanin_requested_model: str
    grok_fanin_observed_model: str
    grok_fanin_parallel_bypass: bool
    grok_ready_frontier: list[dict[str, Any]]
    dispatch_envelope_ref: dict[str, str]
    dispatch_route_claim_ref: str
    dispatch_task_run_dir: str
    dispatch_task_run_id: str
    supervisor_selection_required: bool
    supervisor_worker_decision: dict[str, Any] | None
    grok_serial_reason: str
    grok_lanes: list[dict[str, Any]]
    grok_fanin: dict[str, Any]
    grok_fanin_result_text: str
    grok_total_tokens: int
    grok_execution_location: str
    grok_container_id: str
    non_grok_model_invocations: int
    fallback_model_invocation_performed: bool
    model_worker_phase: str
    model_worker_provider: str
    model_worker_named_blocker: str
    memory_model_bind_frozen: bool
    pro_review_provider: str
    provider_invocation_performed: bool
    model_invocation_performed: bool
    ollama_default_qwen_banned: bool
    parallel_semantic: str
    tier_used: dict[str, str]
    parallel_lane_models: list[dict[str, Any]]
    parallel_lane_results: Annotated[list[dict[str, Any]], operator.add]
    dynamic_loop_shape_ref: str
    rtk_adapter: str
    caveman_adapter: str
    react_loop_count: int
    react_conditional_wired: bool
    hitl_ok: bool
    hitl_signal_wired: bool
    hitl_feedback: str
    hitl_evidence_ref: str
    episode_phase: int
    episode_max_phase: int
    episode_multi_wave: bool
    episode_cache: dict[str, Any]
    continue_as_new_wired: bool
    episode_cache_ref: str


def _load_params_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _params_path(state: BusState) -> Path:
    raw = state.get("params_path") or ""
    if not raw:
        return DEFAULT_PARAMS
    p = resolve_bus_file_path(
        raw,
        repo_root=_repo_root(state),
        runtime_root=_runtime_root(state),
    )
    return p if p.is_file() else DEFAULT_PARAMS


def _repo_root(state: BusState) -> Path:
    return resolve_repo_root(state.get("repo_root") or DEFAULT_REPO)


def _runtime_root(state: BusState) -> Path:
    if state.get("runtime_root"):
        return resolve_runtime_root(state["runtime_root"])
    params = _load_params_file(_params_path(state))
    return resolve_runtime_root(str(params.get("runtime_root") or DEFAULT_RUNTIME))


def _supervisor_selection_evidence(state: BusState) -> dict[str, Any]:
    required = state.get("supervisor_selection_required") is True
    raw = state.get("supervisor_worker_decision")
    if not required and not isinstance(raw, dict):
        return {
            "supervisor_selection_required": False,
            "supervisor_selection_ok": False,
            "supervisor_selection_status": "legacy_unbound",
            "supervisor_worker_decision_sha256": "",
        }
    if not isinstance(raw, dict):
        return {
            "supervisor_selection_required": required,
            "supervisor_selection_ok": False,
            "supervisor_selection_status": "missing",
            "supervisor_worker_decision_sha256": "",
        }
    selected = raw.get("selected_candidate")
    declared_sha256 = str(raw.get("decision_sha256") or "")
    hash_input = dict(raw)
    hash_input.pop("decision_sha256", None)
    observed_sha256 = hashlib.sha256(
        json.dumps(
            hash_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    frontier = state.get("grok_ready_frontier")
    requested_models = sorted(
        {
            str(item.get("model") or "")
            for item in (frontier if isinstance(frontier, list) else [])
            if isinstance(item, dict)
        }
    )
    identity_ok = bool(
        raw.get("decision") == "selected"
        and isinstance(selected, dict)
        and selected.get("provider_id") == GROK_FANIN_PROVIDER
        and selected.get("profile_ref") == GROK_FANIN_PROFILE
        and selected.get("transport_id") == GROK_FANIN_TRANSPORT
        and requested_models == [str(selected.get("model_id") or "")]
        and len(str(raw.get("policy_sha256") or "")) == 64
        and declared_sha256 == observed_sha256
    )
    return {
        "supervisor_selection_required": required,
        "supervisor_selection_ok": identity_ok,
        "supervisor_selection_status": "bound" if identity_ok else "invalid",
        "supervisor_worker_decision_sha256": declared_sha256,
        "supervisor_selected_provider": (
            str(selected.get("provider_id") or "") if isinstance(selected, dict) else ""
        ),
        "supervisor_selected_model": (
            str(selected.get("model_id") or "") if isinstance(selected, dict) else ""
        ),
        "supervisor_selected_transport": (
            str(selected.get("transport_id") or "") if isinstance(selected, dict) else ""
        ),
    }


def _grok_fanin_worker_lane(state: BusState) -> dict[str, Any] | None:
    """Consume a durable host-legacy or Docker-native Grok fan-in."""

    content = str(state.get("content_md") or "")
    runtime = _runtime_root(state).resolve()

    def failed(reason: str) -> dict[str, Any]:
        return {
            "worker_lane_ok": False,
            "worker_lane_status": "failed",
            "worker_lane_mode": "grok_ready_frontier_fanin",
            "worker_lane_provider": GROK_FANIN_PROVIDER,
            "worker_lane_model": "",
            "worker_lane_named_blocker": reason,
            "worker_lane_runtime_enforced": True,
            "worker_lane_integrated_bus_bound": True,
            "worker_lane_cross_seam_contract_version": "",
            "worker_lane_cross_seam_receipt_version": "",
            "worker_lane_cross_seam_receipt_set_sha256": "",
            "worker_lane_cross_seam_receipt_ok": False,
            "worker_lane_adapter": "temporal_acpx_fanin",
            "grok_fanin_ok": False,
            "grok_only_mode": False,
            "selected_provider_fail_closed": True,
            "non_grok_model_invocations": 0,
        }

    raw_manifest = str(state.get("grok_fanin_manifest_ref") or "").strip()
    if not raw_manifest:
        if GROK_FANIN_SENTINEL not in content:
            return None
        match = _GROK_MANIFEST_RE.search(content)
        if match is None:
            return failed("GROK_FANIN_MANIFEST_MARKER_MISSING")
        raw_manifest = match.group(1)
    raw_manifest = raw_manifest.replace("\\", "/")
    manifest_path = (
        runtime / raw_manifest[len("/evidence/") :]
        if raw_manifest.startswith("/evidence/")
        else Path(raw_manifest)
    ).resolve()
    try:
        manifest_path.relative_to(runtime)
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return failed("GROK_FANIN_MANIFEST_INVALID")
    if not isinstance(manifest, dict):
        return failed("GROK_FANIN_MANIFEST_INVALID")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    declared_manifest_sha256 = str(
        state.get("grok_fanin_manifest_sha256") or state.get("grok_fanin_evidence_sha256") or ""
    ).strip()
    canonical_package_mode = (
        manifest.get("package_contract_mode") == "xinao.worker_package_batch.v3"
    )
    if declared_manifest_sha256 and declared_manifest_sha256 != manifest_sha256:
        return failed("GROK_FANIN_MANIFEST_HASH_MISMATCH")
    if canonical_package_mode and declared_manifest_sha256 != manifest_sha256:
        return failed("GROK_FANIN_MANIFEST_HASH_REQUIRED")
    workflow_id = str(state.get("workflow_id") or "")
    source_workflow_id = str(manifest.get("workflow_id") or "")
    lineage_ok = workflow_id == source_workflow_id or workflow_id.startswith(
        source_workflow_id + "-langgraph-s"
    )
    if (
        manifest.get("ok") is not True
        or manifest.get("sentinel") != GROK_FANIN_SENTINEL
        or manifest.get("provider_id") != GROK_FANIN_PROVIDER
        or int(manifest.get("succeeded") or 0) < 1
        or not source_workflow_id
        or not lineage_ok
    ):
        return failed("GROK_FANIN_LINEAGE_OR_ACCEPTANCE_INVALID")
    try:
        input_path = resolve_bus_file_path(
            str(state.get("input_path") or ""),
            repo_root=_repo_root(state),
            runtime_root=runtime,
        ).resolve()
        input_path.relative_to(runtime)
        intake_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return failed("GROK_FANIN_INPUT_INVALID")
    if intake_hash != str(manifest.get("intake_sha256") or ""):
        return failed("GROK_FANIN_INPUT_HASH_MISMATCH")
    model = str(manifest.get("model") or "")
    docker_native = str(manifest.get("execution_location") or "") == "docker:houtai-gongren"
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), list) else []
    succeeded = int(manifest.get("succeeded") or 0)
    failed_count = int(manifest.get("failed") or 0)
    ready_width = int(manifest.get("ready_width") or 0)
    models = manifest.get("models") if isinstance(manifest.get("models"), list) else []
    token_accounting = (
        manifest.get("token_accounting")
        if isinstance(manifest.get("token_accounting"), dict)
        else {}
    )
    selection_evidence = _supervisor_selection_evidence(state)
    required_decision_sha256 = str(
        selection_evidence.get("supervisor_worker_decision_sha256") or ""
    )
    if not (
        manifest.get("schema_version") == GROK_FANIN_SCHEMA_VERSION
        and manifest.get("execution_contract_version") == GROK_EXECUTION_CONTRACT_VERSION
        and manifest.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
        and manifest.get("cross_seam_attempt_receipt_version") == ATTEMPT_RECEIPT_VERSION
        and manifest.get("model_policy_id") == GROK_MODEL_POLICY_ID
        and docker_native
        and model in GROK_FANIN_ALLOWED_MODELS
        and models == [model]
        and manifest.get("observed_model") == expected_docker_grok_backend_models(model)[0]
        and manifest.get("observed_models") == expected_docker_grok_backend_models(model)
        and manifest.get("observed_backend_models") == expected_docker_grok_backend_models(model)
        and manifest.get("model_identity_binding") == grok_docker_model_identity_binding(model)
        and manifest.get("model_identity_ok") is True
        and failed_count == 0
        and succeeded == ready_width == len(lanes)
        and succeeded >= 1
        and _grok_invocation_accounting_valid(token_accounting)
        and (
            selection_evidence.get("supervisor_selection_required") is not True
            or (
                selection_evidence.get("supervisor_selection_ok") is True
                and manifest.get("supervisor_worker_decision_sha256") == required_decision_sha256
            )
        )
    ):
        return failed("GROK_FANIN_FULL_FRONTIER_OR_MODEL_INVALID")
    if any(not isinstance(item, dict) for item in lanes):
        return failed("GROK_FANIN_LANE_PROVIDER_OR_STATE_INVALID")
    if canonical_package_mode:
        top_package_sha256 = str(manifest.get("package_manifest_sha256") or "")
        top_envelope_sha256 = str(manifest.get("dispatch_envelope_sha256") or "")
        canonical_work_keys = manifest.get("canonical_work_keys")
        observed_work_keys = sorted(str(item.get("work_key") or "") for item in lanes)
        if not (
            re.fullmatch(r"[0-9a-f]{64}", top_package_sha256)
            and re.fullmatch(r"[0-9a-f]{64}", top_envelope_sha256)
            and canonical_work_keys == observed_work_keys
            and str(manifest.get("dispatch_task_run_id") or "")
            == str(state.get("dispatch_task_run_id") or "")
            and len(set(observed_work_keys)) == len(observed_work_keys)
            and all(observed_work_keys)
            and all(
                str(item.get("package_manifest_sha256") or "") == top_package_sha256
                and str(item.get("dispatch_envelope_sha256") or "") == top_envelope_sha256
                for item in lanes
            )
        ):
            return failed("GROK_FANIN_CANONICAL_PACKAGE_BINDING_INVALID")
    lane_accounting = [item.get("invocation_accounting") for item in lanes]
    if any(not isinstance(item, dict) for item in lane_accounting) or any(
        int(token_accounting.get(key) or 0)
        != sum(int(item.get(key) or 0) for item in lane_accounting if isinstance(item, dict))
        for key in (
            "invocation_count",
            "total_tokens",
            "accepted_tokens",
            "cancelled_tokens",
            "failed_tokens",
        )
    ):
        return failed("GROK_FANIN_TOKEN_ACCOUNTING_INVALID")
    common_receipt_bindings: list[dict[str, str]] = []
    try:
        repo_root = _repo_root(state)
        for item in lanes:
            logical_contract = item.get("cross_seam_logical_contract")
            attempt_receipt = item.get("cross_seam_attempt_receipt")
            if not isinstance(logical_contract, dict) or not isinstance(attempt_receipt, dict):
                raise ValueError("missing common contract or receipt")
            verdict = validate_attempt_receipt(
                logical_contract,
                attempt_receipt,
                expected_consumer_id=GROK_DOCKER_CONSUMER_ID,
            )
            contract_sha256 = logical_contract_sha256(logical_contract)
            receipt_sha256 = str(item.get("cross_seam_attempt_receipt_sha256") or "")
            contract_artifact_ref = str(item.get("cross_seam_logical_contract_ref") or "").strip()
            contract_artifact_sha256 = str(
                item.get("cross_seam_logical_contract_artifact_sha256") or ""
            ).strip()
            contract_artifact_ok = not (contract_artifact_ref or contract_artifact_sha256) or (
                bool(contract_artifact_ref and contract_artifact_sha256)
                and _grok_embedded_artifact_binding_valid(
                    logical_contract,
                    declared_sha256=contract_artifact_sha256,
                    raw_ref=contract_artifact_ref,
                    runtime=runtime,
                    repo_root=repo_root,
                )
            )
            if not (
                verdict.accepted
                and item.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
                and item.get("cross_seam_attempt_receipt_version") == ATTEMPT_RECEIPT_VERSION
                and item.get("cross_seam_contract_sha256") == contract_sha256
                and contract_artifact_ok
                and _grok_embedded_artifact_binding_valid(
                    attempt_receipt,
                    declared_sha256=receipt_sha256,
                    raw_ref=item.get("cross_seam_attempt_receipt_ref"),
                    runtime=runtime,
                    repo_root=repo_root,
                )
                and (
                    not docker_native
                    or _grok_raw_model_identity_valid(
                        item,
                        requested_model=model,
                        runtime=runtime,
                        repo_root=repo_root,
                    )
                )
            ):
                raise ValueError("common contract or receipt rejected")
            common_receipt_bindings.append(
                build_common_receipt_binding(
                    logical_contract,
                    lane_id=str(item.get("lane_id") or ""),
                    attempt_receipt_sha256=receipt_sha256,
                    attempt_receipt=attempt_receipt,
                    work_key=(str(item.get("work_key") or "") if canonical_package_mode else ""),
                    package_manifest_sha256=(
                        str(item.get("package_manifest_sha256") or "")
                        if canonical_package_mode
                        else ""
                    ),
                    prior_accepted_ancestor_binding=(
                        item.get("prior_accepted_ancestor_binding")
                        if canonical_package_mode
                        and isinstance(item.get("prior_accepted_ancestor_binding"), dict)
                        else None
                    ),
                )
            )
    except (TypeError, ValueError):
        return failed("GROK_FANIN_COMMON_RECEIPT_INVALID")
    common_receipt_set_sha256 = hashlib.sha256(
        canonical_json_bytes(common_receipt_bindings)
    ).hexdigest()
    if not (
        manifest.get("cross_seam_receipt_bindings") == common_receipt_bindings
        and manifest.get("cross_seam_receipt_set_sha256") == common_receipt_set_sha256
    ):
        return failed("GROK_FANIN_COMMON_RECEIPT_SET_INVALID")
    if any(
        item.get("ok") is not True
        or str(item.get("stop_reason") or "").casefold() != "endturn"
        or not str(item.get("result_text") or "").strip()
        or item.get("execution_contract_version") != GROK_EXECUTION_CONTRACT_VERSION
        or item.get("model_capability_ok") is not True
        or item.get("rules_snapshot_ok") is not True
        or item.get("rules_projection_ok") is not True
        or str(item.get("requested_rules_snapshot_sha256") or "")
        != str(item.get("observed_rules_snapshot_sha256") or "")
        or not _grok_invocation_accounting_valid(item.get("invocation_accounting"))
        for item in lanes
    ):
        return failed("GROK_FANIN_LANE_EFFECTIVE_OUTPUT_INVALID")
    lane_ids = [str(item.get("lane_id") or "") for item in lanes]
    operation_ids = [str(item.get("operation_id") or "") for item in lanes]
    if (
        any(
            str(item.get("model") or "") != model
            or str(item.get("requested_model") or "") != model
            or str(item.get("observed_model") or "")
            != expected_docker_grok_backend_models(model)[0]
            or item.get("model_identity_ok") is not True
            or not str(item.get("agent_session_id") or "")
            or not str(item.get("model_identity_ref") or "")
            or not str(item.get("model_identity_sha256") or "")
            or str(item.get("operation_state") or "") != "completed"
            or (
                selection_evidence.get("supervisor_selection_required") is True
                and item.get("supervisor_worker_decision_sha256") != required_decision_sha256
            )
            for item in lanes
        )
        or any(not value for value in lane_ids + operation_ids)
        or len(set(lane_ids)) != len(lane_ids)
        or len(set(operation_ids)) != len(operation_ids)
    ):
        return failed("GROK_FANIN_LANE_PROVIDER_OR_STATE_INVALID")
    lane_modes = [str(item.get("mode") or "") for item in lanes if isinstance(item, dict)]
    lane_count = len(lanes)
    route_roles = {str(item.get("model_route_role") or "") for item in lanes} - {""}
    route_role = (
        next(iter(route_roles))
        if len(route_roles) == 1
        else ("mixed_grok_frontier" if route_roles else "default_background_worker")
    )
    return {
        "worker_lane_ok": True,
        "worker_lane_status": "completed",
        "worker_lane_mode": "grok_ready_frontier_fanin",
        "worker_lane_provider": GROK_FANIN_PROVIDER,
        "worker_lane_model": model,
        "worker_lane_artifact_ref": str(manifest_path),
        "worker_lane_draft_content": str(state.get("grok_fanin_result_text") or content),
        "worker_lane_named_blocker": "",
        "worker_lane_evidence_ref": str(manifest_path),
        "worker_lane_runtime_enforced": True,
        "worker_lane_integrated_bus_bound": True,
        "worker_lane_cross_seam_contract_version": LOGICAL_CONTRACT_VERSION,
        "worker_lane_cross_seam_receipt_version": ATTEMPT_RECEIPT_VERSION,
        "worker_lane_cross_seam_receipt_set_sha256": common_receipt_set_sha256,
        "worker_lane_cross_seam_receipt_ok": True,
        "worker_lane_tier": (
            "T1_ESCALATED_GROK"
            if any(item.get("is_escalated") is True for item in lanes)
            else "T0_DEFAULT_GROK"
        ),
        "worker_lane_route_role": route_role,
        "worker_lane_adapter": (
            "grok_build_cli_docker_native" if docker_native else "temporal_acpx_fanin"
        ),
        "draft_model": model,
        "grok_fanin_ok": True,
        "grok_fanin_model_identity_ok": True,
        "grok_fanin_requested_model": model,
        "grok_fanin_observed_model": str(manifest.get("observed_model") or ""),
        "grok_fanin_manifest_ref": str(manifest_path),
        "grok_fanin_manifest_sha256": manifest_sha256,
        "grok_fanin_evidence_sha256": manifest_sha256,
        "grok_fanin_lane_count": lane_count,
        "grok_fanin_lane_modes": lane_modes,
        "grok_fanin_audit_lane_count": sum(
            mode in {"audit", "review", "external_research"} for mode in lane_modes
        ),
        "grok_execution_location": str(manifest.get("execution_location") or ""),
        "grok_container_id": str(manifest.get("container_id") or ""),
        "supervisor_worker_decision_sha256": str(
            manifest.get("supervisor_worker_decision_sha256") or ""
        ),
        "grok_only_mode": False,
        "selected_provider_fail_closed": True,
        "non_grok_model_invocations": 0,
        "ollama_default_qwen_banned": True,
    }


def _grok_only_block(phase: str) -> dict[str, Any]:
    """Fail the already-selected Grok adapter without activating another provider."""
    return {
        "ok": False,
        "grok_only_mode": False,
        "selected_provider_fail_closed": True,
        "grok_fanin_ok": False,
        "model_worker_phase": phase,
        "model_worker_provider": GROK_FANIN_PROVIDER,
        "model_worker_named_blocker": "GROK_FANIN_REQUIRED",
        "non_grok_model_invocations": 0,
        "fallback_model_invocation_performed": False,
    }


def _activity_options(
    *,
    heartbeat: bool = False,
    grok_retry: bool = False,
) -> dict[str, Any]:
    options = {
        "execute_in": "activity",
        "start_to_close_timeout": timedelta(minutes=5),
    }
    if heartbeat:
        options["heartbeat_timeout"] = timedelta(seconds=15)
    if grok_retry:
        options["start_to_close_timeout"] = timedelta(seconds=7_380)
        options["schedule_to_close_timeout"] = timedelta(seconds=22_500)
        options["retry_policy"] = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=15),
            maximum_attempts=3,
            non_retryable_error_types=[
                "DockerGrokPermanentError",
                "ValueError",
                "TypeError",
            ],
        )
    return options


def _resolve_gateway_base_url(params: dict[str, Any]) -> str:
    from services.agent_runtime.thin_provider_client import resolve_gateway_base_url

    return resolve_gateway_base_url(str(params.get("gateway_base_url") or "").strip() or None)


def consume_science_instrument_contract(state: BusState) -> dict[str, Any]:
    """Fail closed when the reusable bus is entered through a science episode."""

    raw_admission = state.get("science_episode_admission")
    mode = str(state.get("science_instrument_mode") or "").strip().upper()
    if raw_admission is None and not mode:
        return {}
    if not isinstance(raw_admission, Mapping):
        raise ValueError("science instrument admission must be an object")
    if mode == "SCIENCE_STARTUP_VALIDATION":
        raise ValueError("startup validation must use the direct science worker activity")
    if mode != "RESEARCH":
        raise ValueError("science instrument mode is missing or unsupported")
    claim_intent = str(raw_admission.get("claim_intent") or "").strip().upper()
    if (
        raw_admission.get("allowed") is not True
        or raw_admission.get("active_parent_id") != "XINAO_SCIENCE_PROTOCOL_ACTIVE"
        or raw_admission.get("old_g6_equivalent") is not False
        or raw_admission.get("evaluation_outcome_access") is not False
    ):
        raise ValueError("science instrument admission is not current-parent safe")
    if claim_intent not in {"EXPLORATORY", "CONFIRMATORY"}:
        raise ValueError("research instrument cannot consume a startup-only claim")
    return {
        "science_instrument_mode": mode,
        "science_instrument_admission_consumed": True,
        "science_trial_appends": 0,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
        "evaluation_outcome_access": False,
        "legacy_parent_scope_consumed": False,
    }


async def intake_node(state: BusState) -> dict[str, Any]:
    """
    L0 intake activity. Never raise on host Desktop\\*.lnk (container cannot see it).
    Prefer /evidence or materials; missing path → named_blocker + synthetic fallback text.
    """
    params = _load_params_file(_params_path(state))
    max_chars = int(params.get("max_md_chars", 2000))
    repo = _repo_root(state)
    runtime = _runtime_root(state)
    raw_input = str(state.get("input_path") or params.get("input_path") or "")
    mapped = (
        resolve_bus_file_path(raw_input, repo_root=repo, runtime_root=runtime)
        if raw_input
        else None
    )
    resolved = resolve_intake_source(
        mapped if mapped is not None else raw_input,
        repo_root=repo,
        runtime_root=runtime,
    )
    intake_target = resolved.get("path") or mapped or Path(raw_input or "missing_intake")
    intake = l0_intake_markdown(Path(str(intake_target)), max_chars=max_chars)
    named_blocker = str(intake.get("named_blocker") or resolved.get("named_blocker") or "")
    # Prefer evidence-resolved path for downstream nodes; keep requested for evidence.
    effective_path = str(intake.get("source") or intake_target)
    return {
        **consume_science_instrument_contract(state),
        "content_md": str(intake.get("content_md") or ""),
        "adapter": str(intake.get("adapter") or ""),
        "input_path": effective_path,
        "intake_named_blocker": named_blocker,
        "intake_requested_path": str(resolved.get("requested") or raw_input),
        "intake_used_fallback_text": bool(intake.get("used_fallback_text")),
    }


async def duckdb_node(state: BusState) -> dict[str, Any]:
    return run_duckdb_bus(
        runtime_root=_runtime_root(state),
        content_md=str(state.get("content_md") or ""),
    )


async def watchdog_node(state: BusState) -> dict[str, Any]:
    return run_watchdog_bus(runtime_root=_runtime_root(state))


async def facade_guard_node(state: BusState) -> dict[str, Any]:
    guarded = run_facade_guard_bus(repo_root=_repo_root(state))
    guarded["handroll_intact"] = False
    return guarded


async def _validate_node_impl(
    state: BusState,
    *,
    propagate_transient: bool,
) -> dict[str, Any]:
    native_fanin: dict[str, Any] = {}
    selection_evidence = _supervisor_selection_evidence(state)
    selection_rejected = (
        selection_evidence["supervisor_selection_required"] is True
        and selection_evidence["supervisor_selection_ok"] is not True
    )
    grok_lane = None if selection_rejected else _grok_fanin_worker_lane(state)
    if selection_rejected:
        native_fanin = {
            "grok_fanin_ok": False,
            "grok_execution_location": "docker:houtai-gongren",
            "model_worker_named_blocker": "SUPERVISOR_SELECTION_INVALID",
            "provider_invocation_performed": False,
            "model_invocation_performed": False,
            "fallback_model_invocation_performed": False,
            "non_grok_model_invocations": 0,
        }
    elif grok_lane is None:
        from services.agent_runtime.grok_build_docker_worker import (
            DockerGrokTransientError,
            docker_native_grok_enabled,
            run_docker_native_grok_fanin,
        )

        if docker_native_grok_enabled():
            try:
                native_fanin = await run_docker_native_grok_fanin(
                    runtime_root=_runtime_root(state),
                    workflow_id=str(state.get("workflow_id") or ""),
                    input_path=resolve_bus_file_path(
                        str(state.get("input_path") or ""),
                        repo_root=_repo_root(state),
                        runtime_root=_runtime_root(state),
                    ),
                    content_md=str(state.get("content_md") or ""),
                    ready_frontier=state.get("grok_ready_frontier"),
                    serial_reason=str(state.get("grok_serial_reason") or ""),
                    correlation_id=str(state.get("correlation_id") or ""),
                    parent_operation_id=str(state.get("parent_operation_id") or ""),
                    supervisor_worker_decision=state.get("supervisor_worker_decision"),
                    supervisor_selection_required=(
                        state.get("supervisor_selection_required") is True
                    ),
                    dispatch_envelope_ref=state.get("dispatch_envelope_ref"),
                    dispatch_route_claim_ref=state.get("dispatch_route_claim_ref"),
                    dispatch_task_run_dir=state.get("dispatch_task_run_dir"),
                    dispatch_task_run_id=state.get("dispatch_task_run_id"),
                )
                grok_lane = _grok_fanin_worker_lane({**state, **native_fanin})
            except DockerGrokTransientError as exc:
                if propagate_transient:
                    raise ApplicationError(
                        str(exc),
                        type="DockerGrokTransientError",
                    ) from exc
                native_fanin = {
                    "grok_fanin_ok": False,
                    "grok_execution_location": "docker:houtai-gongren",
                    "model_worker_named_blocker": (f"DockerGrokTransientError:{str(exc)[:240]}"),
                    "fallback_model_invocation_performed": False,
                    "non_grok_model_invocations": 0,
                }
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                native_fanin = {
                    "grok_fanin_ok": False,
                    "grok_execution_location": "docker:houtai-gongren",
                    "model_worker_named_blocker": f"{type(exc).__name__}:{str(exc)[:240]}",
                    "fallback_model_invocation_performed": False,
                    "non_grok_model_invocations": 0,
                }
    validated = run_validate_bus(
        input_path=str(state.get("input_path") or ""),
        content_md=str(state.get("content_md") or ""),
    )
    validated["instructor_ok"] = bool(grok_lane and grok_lane.get("worker_lane_ok") is True)
    validated["instructor_invoked"] = False
    validated["instructor_enabled"] = False
    validated["instructor_adapter"] = "grok_fanin_structured_validation"
    validated["model_worker_provider"] = GROK_FANIN_PROVIDER
    validated["non_grok_model_invocations"] = 0
    if not validated["instructor_ok"]:
        validated["validate_ok"] = False
        validated.update(_grok_only_block("validate"))
        if selection_rejected:
            validated["model_worker_named_blocker"] = "SUPERVISOR_SELECTION_INVALID"
    return {
        **selection_evidence,
        **native_fanin,
        **validated,
        **(grok_lane or {}),
    }


async def validate_node(state: BusState) -> dict[str, Any]:
    """Replay-compatible validate Activity used by retained graph versions."""

    return await _validate_node_impl(state, propagate_transient=False)


async def validate_node_retry_v2(state: BusState) -> dict[str, Any]:
    """New-version validate Activity that exposes transient failures to Temporal retry."""

    return await _validate_node_impl(state, propagate_transient=True)


async def signal_feed_node(state: BusState) -> dict[str, Any]:
    return run_signal_feed_bus(runtime_root=_runtime_root(state))


async def planner_node(state: BusState) -> dict[str, Any]:
    return run_planner_bus(
        task_package=state.get("task_package"),
        heal_repair_required=state.get("heal_repair_required") is True,
        failed_checks=state.get("heal_failed_checks") or [],
    )


async def search_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    max_results = int(params.get("search_max_results", 6))
    search_context = {
        "heal_repair_required": state.get("heal_repair_required") is True,
        "difficulty": str(params.get("search_difficulty") or params.get("task_difficulty") or ""),
        "failure_count": int(state.get("heal_retry_count") or 0),
        "low_github_hits": int(state.get("search_hit_count") or 0) < 2,
    }
    return run_search_bus(
        repo_root=_repo_root(state),
        content_md=str(state.get("content_md") or ""),
        max_results=max_results,
        context=search_context,
    )


async def crawl4ai_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_crawl4ai_bus(
        params=params,
        query=str(state.get("search_query") or ""),
        runtime_root=_runtime_root(state),
        search_external_hits=list(state.get("search_external_hits") or []),
        search_external=dict(state.get("search_external") or {}),
    )


async def mcp_tools_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    payload = run_mcp_tools_bus(
        params=params,
        repo_root=_repo_root(state),
        runtime_root=_runtime_root(state),
    )
    payload["react_loop_count"] = int(state.get("react_loop_count") or 0) + 1
    payload["react_conditional_wired"] = True
    return payload


async def should_heal_critic(state: BusState) -> str:
    """L6 LangGraph critic conditional edge — heal → planner repair or checkpoint."""
    if state.get("heal_repair_required") is True and int(state.get("heal_retry_count") or 0) <= 1:
        return "planner"
    return "checkpoint"


async def should_planner_route(state: BusState) -> str:
    """Short-circuit to checkpoint when planner is servicing an L6 heal repair."""
    if int(state.get("heal_retry_count") or 0) >= 1:
        return "checkpoint"
    return "gateway_trace"


async def route_parallel_send(state: BusState) -> str:
    """Grok fan-out happens in the Temporal parent; child-side fallback is frozen."""
    del state
    return "grok_worker_fanin"


async def should_react_continue(state: BusState) -> str:
    """G4 ReAct router — mcp_tools ↔ planner loop or continue to mirror_registry."""
    params = _load_params_file(_params_path(state))
    max_loops = max(1, int(params.get("react_max_loops", 1)))
    loop_count = int(state.get("react_loop_count") or 0)
    if (
        params.get("react_loop_enabled", False) is True
        and loop_count < max_loops
        and state.get("mcp_tools_ok") is True
    ):
        return "planner"
    return "mirror_registry"


async def mirror_registry_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_mirror_registry_bus(
        params=params,
        runtime_root=_runtime_root(state),
        repo_root=_repo_root(state),
    )


async def glue_seam_invoke_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_glue_seam_invoke_bus(
        params=params,
        runtime_root=_runtime_root(state),
        repo_root=_repo_root(state),
    )


async def openhands_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_openhands_bus(params=params, runtime_root=_runtime_root(state))


async def parallel_width_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    grok_lane = _grok_fanin_worker_lane(state)
    if grok_lane and grok_lane.get("worker_lane_ok") is True:
        lane_count = max(1, int(grok_lane.get("grok_fanin_lane_count") or 0))
        return {
            "parallel_ok": True,
            "parallel_width_n": lane_count,
            "parallel_succeeded": lane_count,
            "parallel_semantic": resolve_parallel_semantic(params),
            "parallel_lane_models": [],
            "langgraph_send_wired": False,
            "adapter": "temporal_parent_grok_ready_frontier_fanin",
            "grok_fanin_parallel_bypass": True,
            "grok_fanin_lane_count": lane_count,
            "grok_only_mode": False,
            "selected_provider_fail_closed": True,
            "non_grok_model_invocations": 0,
        }
    return {
        **_grok_only_block("parallel_width"),
        "parallel_ok": False,
        "parallel_width_n": 0,
        "parallel_succeeded": 0,
        "parallel_semantic": resolve_parallel_semantic(params),
        "parallel_lane_models": [],
        "langgraph_send_wired": False,
        "adapter": "grok_fanin_required_no_child_fallback",
    }


async def memory_bus_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    payload = run_memory_bus(
        runtime_root=_runtime_root(state),
        state=dict(state),
        params={
            **params,
            "mem0_bind_enabled": False,
            "mem0_oss_mode": False,
        },
    )
    payload["memory_model_bind_frozen"] = True
    payload["non_grok_model_invocations"] = 0
    return payload


async def grok_worker_fanin_node(state: BusState) -> dict[str, Any]:
    """Consume the sole permitted background model worker: Temporal/ACPX Grok."""
    grok_lane = _grok_fanin_worker_lane(state)
    if grok_lane is not None:
        return grok_lane
    return {
        **_grok_only_block("default_worker"),
        "worker_lane_ok": False,
        "worker_lane_status": "blocked",
        "worker_lane_provider": GROK_FANIN_PROVIDER,
        "worker_lane_model": "",
        "worker_lane_adapter": "selected_grok_provider_fail_closed",
        "worker_lane_named_blocker": "GROK_FANIN_REQUIRED",
        "ollama_default_qwen_banned": True,
    }


async def hitl_review_node(state: BusState) -> dict[str, Any]:
    """G5 HITL review — signal/query compat; auto-approve on default smoke."""
    params = _load_params_file(_params_path(state))
    draft = str(state.get("worker_lane_draft_content") or state.get("content_md") or "")
    return run_hitl_review_bus(
        runtime_root=_runtime_root(state),
        draft_excerpt=draft,
        pro_review_ok=state.get("pro_review_ok") is True,
        params=params,
    )


async def pro_review_after_draft_node(state: BusState) -> dict[str, Any]:
    grok_lane = _grok_fanin_worker_lane(state)
    if not grok_lane or grok_lane.get("worker_lane_ok") is not True:
        return {
            **_grok_only_block("pro_review"),
            "pro_review_ok": False,
            "review_model": "",
            "pro_review_model": "",
        }
    audit_lane_count = int(grok_lane.get("grok_fanin_audit_lane_count") or 0)
    review_required = state.get("review_required") is True
    if not review_required:
        return {
            "pro_review_ok": False,
            "pro_review_contract_satisfied": True,
            "review_required": False,
            "pro_review_status": "not_required",
            "review_model": "",
            "pro_review_model": "",
            "pro_review_named_blocker": "",
            "fanin_audit_presence": audit_lane_count > 0,
            "pro_review_reused_fanin_audit": False,
            "pro_review_model_invocation_performed": False,
            "model_invocation_performed": False,
            "provider_invocation_performed": False,
            "fallback_model_invocation_performed": False,
        }
    review = state.get("post_draft_review")
    if not isinstance(review, dict):
        review = {}
    draft_text = str(state.get("worker_lane_draft_content") or state.get("content_md") or "")
    draft_sha256 = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
    evidence_ref = str(review.get("evidence_ref") or "")
    evidence_sha256 = str(review.get("evidence_sha256") or "")
    evidence_bound = False
    if evidence_ref and evidence_sha256:
        path = resolve_bus_file_path(
            evidence_ref,
            repo_root=_repo_root(state),
            runtime_root=_runtime_root(state),
        )
        try:
            resolved = path.resolve()
            resolved.relative_to(_runtime_root(state).resolve())
            evidence_bound = (
                resolved.is_file()
                and hashlib.sha256(resolved.read_bytes()).hexdigest() == evidence_sha256
            )
        except (OSError, ValueError):
            evidence_bound = False
    review_ok = bool(
        review.get("provider_id") == GROK_FANIN_PROVIDER
        and str(review.get("model") or "") in GROK_FANIN_ALLOWED_MODELS
        and review.get("target_draft_sha256") == draft_sha256
        and str(review.get("verdict") or "") in {"APPROVED", "CHANGES_REQUESTED", "REJECTED"}
        and review.get("stop_reason") == "EndTurn"
        and int(review.get("total_tokens") or 0) > 0
        and evidence_bound
    )
    if not review_ok:
        return {
            **_grok_only_block("pro_review"),
            "pro_review_ok": False,
            "pro_review_contract_satisfied": False,
            "review_required": True,
            "pro_review_status": "blocked",
            "review_model": "",
            "pro_review_model": "",
            "pro_review_named_blocker": "POST_DRAFT_REVIEW_EVIDENCE_REQUIRED",
            "fanin_audit_presence": audit_lane_count > 0,
            "pro_review_reused_fanin_audit": False,
            "pro_review_model_invocation_performed": False,
        }
    review_model = str(review.get("model") or "")
    return {
        "pro_review_ok": True,
        "pro_review_contract_satisfied": True,
        "review_required": True,
        "pro_review_status": "completed_from_bound_post_draft_review",
        "pro_review_provider": GROK_FANIN_PROVIDER,
        "pro_review_tier": "T0_DEFAULT_GROK",
        "pro_review_route_role": "grok_fanin_validation",
        "pro_review_adapter": "temporal_acpx_fanin_validation",
        "pro_review_model": review_model,
        "review_model": review_model,
        "pro_review_evidence_ref": evidence_ref,
        "grok_fanin_audit_lane_count": audit_lane_count,
        "fanin_audit_presence": audit_lane_count > 0,
        "pro_review_reused_fanin_audit": False,
        "pro_review_model_invocation_performed": True,
        "model_invocation_performed": True,
        "provider_invocation_performed": True,
        "grok_only_mode": False,
        "selected_provider_fail_closed": True,
        "non_grok_model_invocations": 0,
        "fallback_model_invocation_performed": False,
    }


async def fanin_node(state: BusState) -> dict[str, Any]:
    return run_fanin_bus(
        dict(state),
        runtime_root=_runtime_root(state),
        workflow_id=str(state.get("workflow_id") or ""),
        repo_root=_repo_root(state),
    )


async def aaq_node(state: BusState) -> dict[str, Any]:
    payload = run_aaq_fanin_bus(
        runtime_root=_runtime_root(state),
        state=dict(state),
        workflow_id=str(state.get("workflow_id") or ""),
    )
    payload["handroll_intact"] = False
    return payload


async def episode_cache_node(state: BusState) -> dict[str, Any]:
    """G6 episode cache evidence — continue-as-new wiring recorded per phase."""
    params = _load_params_file(_params_path(state))
    phase = int(state.get("episode_phase") or params.get("episode_phase_default", 3))
    max_phase = int(state.get("episode_max_phase") or params.get("episode_max_phase", 3))
    payload = run_episode_cache_bus(
        runtime_root=_runtime_root(state),
        episode_phase=phase,
        workflow_id=str(state.get("workflow_id") or ""),
    )
    payload["episode_phase"] = phase
    payload["episode_max_phase"] = max_phase
    payload["episode_multi_wave"] = phase < max_phase
    payload["continue_as_new_wired"] = True
    return payload


async def pytest_slice_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_pytest_slice_bus(
        params=params,
        repo_root=_repo_root(state),
        runtime_root=_runtime_root(state),
        workflow_id=str(state.get("workflow_id") or ""),
    )


async def token_bus_node(state: BusState) -> dict[str, Any]:
    from services.agent_runtime.thin_glue_l8_token_stack import (
        compress_readback_text,
        try_caveman_compress,
        try_rtk_compress,
    )

    summary = (
        f"integrated_bus workflow={state.get('workflow_id')}\n"
        f"validate={state.get('validate_ok')} search_hits={state.get('search_hit_count')}\n"
        f"gateway={state.get('gateway_trace_ok')} worker_lane={state.get('worker_lane_ok')} "
        f"pro_review={state.get('pro_review_ok')} promotion={state.get('promotion_gate_passed')}\n"
        f"memory_bus={state.get('memory_bus_ok')} glue_seam={state.get('glue_seam_invoke_count')}\n"
    )
    compressed = compress_readback_text(summary, max_chars=2000)
    payload = run_token_bus(
        summary_text=summary,
        runtime_root=_runtime_root(state),
        compressed=compressed,
    )
    adapter = str(payload.get("compression_adapter") or "")
    rtk_probe = try_rtk_compress(summary)
    caveman_probe = try_caveman_compress(summary)
    payload["rtk_adapter"] = "rtk" if (adapter == "rtk" or (rtk_probe or {}).get("ok")) else ""
    payload["caveman_adapter"] = (
        "caveman" if (adapter == "caveman" or (caveman_probe or {}).get("ok")) else ""
    )
    payload["rtk_named_blocker"] = str(compressed.get("rtk_named_blocker") or "")
    payload["caveman_named_blocker"] = str(compressed.get("caveman_named_blocker") or "")
    return payload


async def heal_node(state: BusState) -> dict[str, Any]:
    return run_heal_bus(
        params=_load_params_file(_params_path(state)),
        state=dict(state),
        runtime_root=_runtime_root(state),
    )


async def checkpoint_node(state: BusState) -> dict[str, Any]:
    return run_checkpoint_bus(
        runtime_root=_runtime_root(state),
        workflow_id=str(state.get("workflow_id") or ""),
        state_snapshot={
            "validate_ok": state.get("validate_ok"),
            "fanin_ok": state.get("fanin_ok"),
            "promotion_gate_passed": state.get("promotion_gate_passed"),
            "critic_decision": state.get("critic_decision"),
            "heal_retry_count": state.get("heal_retry_count"),
        },
    )


async def gateway_trace_node(state: BusState) -> dict[str, Any]:
    grok_lane = _grok_fanin_worker_lane(state)
    accepted = bool(grok_lane and grok_lane.get("worker_lane_ok") is True)
    return {
        "gateway_trace_ok": accepted,
        "litellm_completion_ok": False,
        "litellm_completion_via": "grok_fanin_provider_trace",
        "gateway_trace_skipped": True,
        "langfuse_callback_wired": False,
        "langfuse_skipped": True,
        "langfuse_named_blocker": "NON_GROK_MODEL_GATEWAY_FROZEN",
        "gateway_named_blocker": "" if accepted else "GROK_FANIN_REQUIRED",
        "litellm_evidence_ref": "",
        "grok_fanin_evidence_ref": (
            str(grok_lane.get("grok_fanin_manifest_ref") or "") if grok_lane else ""
        ),
        "grok_only_mode": False,
        "selected_provider_fail_closed": True,
        "non_grok_model_invocations": 0,
        "fallback_model_invocation_performed": False,
    }


async def sandbox_node(state: BusState) -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_bus_nodes import _write_invoke_evidence

    params = _load_params_file(_params_path(state))
    preview = str(state.get("content_md") or "")[:300].replace('"', "'").replace("\n", " ")
    code = (
        "from datetime import datetime\n"
        f'print("IntegratedBus-LangGraphPlugin", datetime.now().isoformat())\n'
        f'print("{preview}...")\n'
    )
    execution = l3_run_sandbox(
        code,
        prefer_docker=True,
        prefer_e2b=False,
        docker_image=str(params.get("docker_image") or "python:3.12-slim"),
    )
    stdout = str(execution.get("stdout") or execution.get("stderr") or "")
    backend = str(execution.get("adapter") or execution.get("backend") or "")
    docker_invoked = backend.startswith("docker:")
    evidence_ref = _write_invoke_evidence(
        _runtime_root(state),
        "docker_sandbox",
        {
            "schema_version": "xinao.integrated_bus.docker_sandbox.v1",
            "invoke_ok": bool(stdout.strip()) and int(execution.get("exit_code") or 0) == 0,
            "adapter": backend or "sandbox_invoke_failed",
            "docker_invoked": docker_invoked,
            "exit_code": int(execution.get("exit_code") or 0),
            "stdout_excerpt": stdout[:500],
        },
    )
    return {
        "execution_stdout": stdout,
        "execution_backend": backend,
        "docker_sandbox_invoked": docker_invoked,
        "docker_sandbox_evidence_ref": evidence_ref,
    }


async def promotion_gate_node(state: BusState) -> dict[str, Any]:
    promotion = run_promotion_gate(
        dict(state),
        runtime_root=_runtime_root(state),
        repo_root=_repo_root(state),
        workflow_id=str(state.get("workflow_id") or ""),
    )
    return {
        "promotion_gate_passed": promotion.get("validation", {}).get("passed") is True,
        "memory_candidate_id": str(promotion.get("memory_candidate_id") or ""),
        "memory_candidate_ref": str(promotion.get("memory_candidate_ref") or ""),
        "memory_candidate_sha256": str(promotion.get("memory_candidate_sha256") or ""),
        "promotion_evidence_ref": str(promotion.get("promotion_evidence_ref") or ""),
        "promotion_source_ledger_ref": str(promotion.get("source_ledger_ref") or ""),
        "promotion_source_ledger_sha256": str(promotion.get("source_ledger_sha256") or ""),
    }


def _gitpython_readonly_snapshot(repo: Path) -> dict[str, Any]:
    """Read repository identity without staging, committing, or changing the worktree."""
    try:
        import git
    except ImportError as exc:
        return _git_cli_readonly_snapshot(repo, fallback_error=str(exc))

    try:
        git_repo = git.Repo(repo, search_parent_directories=False)
        commit_hash = git_repo.head.commit.hexsha
        untracked = list(git_repo.untracked_files)
        dirty = git_repo.is_dirty(untracked_files=True)
        return {
            "invoke_ok": bool(commit_hash),
            "adapter": "gitpython_readonly",
            "commit_hash": commit_hash,
            "created_new": False,
            "worktree_mutated": False,
            "worktree_dirty": dirty,
            "untracked_count": len(untracked),
        }
    except Exception as exc:
        return _git_cli_readonly_snapshot(repo, fallback_error=str(exc))


def _git_cli_readonly_snapshot(repo: Path, *, fallback_error: str = "") -> dict[str, Any]:
    import subprocess

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    commit_hash = (head.stdout or "").strip() if head.returncode == 0 else ""
    rows = [line for line in (status.stdout or "").splitlines() if line.strip()]
    return {
        "invoke_ok": bool(commit_hash) and status.returncode == 0,
        "adapter": "git_cli_readonly",
        "commit_hash": commit_hash,
        "created_new": False,
        "worktree_mutated": False,
        "worktree_dirty": bool(rows),
        "untracked_count": sum(1 for line in rows if line.startswith("??")),
        "fallback_error": fallback_error,
    }


async def finalize_node(state: BusState) -> dict[str, Any]:
    repo = _repo_root(state)
    runtime = _runtime_root(state)
    workflow_id = str(state.get("workflow_id") or "integrated-bus-latest")
    proof_stem = "".join(char if char.isalnum() or char in "-_." else "_" for char in workflow_id)[
        :120
    ]
    proof_dir = runtime / "state" / "integrated_bus_proof"
    proof_dir.mkdir(parents=True, exist_ok=True)
    proof_path = proof_dir / f"{proof_stem or 'integrated-bus-latest'}.txt"
    lines = [
        now_iso(),
        str(state.get("execution_stdout") or ""),
        f"validate_ok={state.get('validate_ok')}",
        f"search_hits={state.get('search_hit_count')}",
        f"fanin_ok={state.get('fanin_ok')}",
        f"planner_ok={state.get('planner_ok')}",
        f"crawl4ai_ok={state.get('crawl4ai_ok')}",
        f"diff_cover_ok={state.get('diff_cover_ok')}",
        f"otel_ok={state.get('otel_ok')}",
        f"checkpoint_ok={state.get('checkpoint_ok')}",
        f"gateway_trace_ok={state.get('gateway_trace_ok')}",
        f"worker_lane_ok={state.get('worker_lane_ok')}",
        f"worker_lane_provider={state.get('worker_lane_provider') or 'none'}",
        f"draft_model={state.get('draft_model') or state.get('worker_lane_model') or 'none'}",
        f"pro_review_ok={state.get('pro_review_ok')}",
        f"pro_review_model={state.get('pro_review_model') or 'none'}",
        f"review_model={state.get('review_model') or state.get('pro_review_model') or 'none'}",
        f"parallel_semantic={state.get('parallel_semantic') or 'barrier'}",
        f"parallel_succeeded={state.get('parallel_succeeded') or 0}",
        f"tier_used={state.get('tier_used') or {}}",
        f"langfuse_callback_wired={state.get('langfuse_callback_wired')}",
        f"promotion_gate_passed={state.get('promotion_gate_passed')}",
        f"memory_candidate_id={state.get('memory_candidate_id') or 'none'}",
        f"memory_bus_ref={state.get('memory_bus_ref') or 'none'}",
        f"child_wf={state.get('child_wf_ok')}",
        f"signal_feed={state.get('signal_feed_ok')}",
        f"glue_seam_invoke={state.get('glue_seam_invoke_count')}",
        f"readback_zh={state.get('readback_zh_ref') or 'none'}",
        f"react_conditional_wired={state.get('react_conditional_wired')}",
        f"react_loop_count={state.get('react_loop_count')}",
        f"hitl_ok={state.get('hitl_ok')}",
        f"hitl_signal_wired={state.get('hitl_signal_wired')}",
        f"hitl_feedback={state.get('hitl_feedback') or 'none'}",
        f"episode_phase={state.get('episode_phase')}",
        f"continue_as_new_wired={state.get('continue_as_new_wired')}",
        f"episode_cache_ref={state.get('episode_cache_ref') or 'none'}",
    ]
    proof_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from services.agent_runtime.integrated_bus_bus_nodes import _write_invoke_evidence

    git_snapshot = _gitpython_readonly_snapshot(repo)
    git_adapter = str(git_snapshot.get("adapter") or "gitpython_readonly_failed")
    gitpython_invoke = git_snapshot.get("invoke_ok") is True
    git_evidence_ref = _write_invoke_evidence(
        runtime,
        "gitpython",
        {
            "schema_version": "xinao.integrated_bus.gitpython_readonly.v1",
            "invoke_ok": gitpython_invoke,
            "adapter": git_adapter,
            "commit_hash": str(git_snapshot.get("commit_hash") or ""),
            "created_new": False,
            "worktree_mutated": False,
            "worktree_dirty": git_snapshot.get("worktree_dirty"),
            "untracked_count": git_snapshot.get("untracked_count"),
            "error": git_snapshot.get("error"),
        },
    )
    return {
        "proof_path": str(proof_path),
        "commit_hash": str(git_snapshot.get("commit_hash") or ""),
        "git_commit_adapter": git_adapter,
        "git_snapshot_adapter": git_adapter,
        "gitpython_invoke_ok": gitpython_invoke,
        "gitpython_evidence_ref": git_evidence_ref,
        "handroll_intact": False,
    }


def make_integrated_graph(
    *,
    grok_heartbeat: bool = False,
    grok_retry: bool = False,
) -> StateGraph:
    g: StateGraph = StateGraph(BusState)
    validate_activity = validate_node_retry_v2 if grok_retry else validate_node
    g.add_node("intake", intake_node, metadata=_activity_options())
    g.add_node("signal_feed", signal_feed_node, metadata=_activity_options())
    g.add_node("duckdb", duckdb_node, metadata=_activity_options())
    g.add_node("watchdog", watchdog_node, metadata=_activity_options())
    g.add_node("facade_guard", facade_guard_node, metadata=_activity_options())
    g.add_node(
        "validate",
        validate_activity,
        metadata=_activity_options(heartbeat=grok_heartbeat, grok_retry=grok_retry),
    )
    g.add_node("planner", planner_node, metadata=_activity_options())
    g.add_node("gateway_trace", gateway_trace_node, metadata=_activity_options())
    g.add_node("search", search_node, metadata=_activity_options())
    g.add_node("crawl4ai", crawl4ai_node, metadata=_activity_options())
    g.add_node("mcp_tools", mcp_tools_node, metadata=_activity_options())
    g.add_node("mirror_registry", mirror_registry_node, metadata=_activity_options())
    g.add_node("glue_seam_invoke", glue_seam_invoke_node, metadata=_activity_options())
    g.add_node("openhands", openhands_node, metadata=_activity_options())
    g.add_node("parallel_width", parallel_width_node, metadata=_activity_options())
    g.add_node("memory_bus", memory_bus_node, metadata=_activity_options())
    g.add_node("grok_worker_fanin", grok_worker_fanin_node, metadata=_activity_options())
    g.add_node("sandbox", sandbox_node, metadata=_activity_options())
    g.add_node("pro_review_after_draft", pro_review_after_draft_node, metadata=_activity_options())
    g.add_node("hitl_review", hitl_review_node, metadata=_activity_options())
    g.add_node("fanin", fanin_node, metadata=_activity_options())
    g.add_node("aaq", aaq_node, metadata=_activity_options())
    g.add_node("promotion_gate", promotion_gate_node, metadata=_activity_options())
    g.add_node("token_bus", token_bus_node, metadata=_activity_options())
    g.add_node("heal", heal_node, metadata=_activity_options())
    g.add_node("checkpoint", checkpoint_node, metadata=_activity_options())
    g.add_node("pytest_slice", pytest_slice_node, metadata=_activity_options())
    g.add_node("episode_cache", episode_cache_node, metadata=_activity_options())
    g.add_node("finalize", finalize_node, metadata=_activity_options())
    g.add_edge(START, "signal_feed")
    g.add_edge("signal_feed", "intake")
    g.add_edge("intake", "duckdb")
    g.add_edge("duckdb", "watchdog")
    g.add_edge("watchdog", "facade_guard")
    g.add_edge("facade_guard", "validate")
    g.add_edge("validate", "planner")
    g.add_conditional_edges("planner", should_planner_route)
    g.add_edge("gateway_trace", "search")
    g.add_edge("search", "crawl4ai")
    g.add_edge("crawl4ai", "mcp_tools")
    g.add_conditional_edges("mcp_tools", should_react_continue)
    g.add_edge("mirror_registry", "glue_seam_invoke")
    g.add_edge("glue_seam_invoke", "openhands")
    g.add_edge("openhands", "parallel_width")
    g.add_conditional_edges(
        "parallel_width",
        route_parallel_send,
        ["grok_worker_fanin"],
    )
    g.add_edge("grok_worker_fanin", "sandbox")
    g.add_edge("sandbox", "pro_review_after_draft")
    g.add_edge("pro_review_after_draft", "hitl_review")
    g.add_edge("hitl_review", "fanin")
    g.add_edge("fanin", "aaq")
    g.add_edge("aaq", "promotion_gate")
    g.add_edge("promotion_gate", "memory_bus")
    g.add_edge("memory_bus", "token_bus")
    g.add_edge("token_bus", "heal")
    g.add_conditional_edges("heal", should_heal_critic)
    g.add_edge("checkpoint", "pytest_slice")
    g.add_edge("pytest_slice", "episode_cache")
    g.add_edge("episode_cache", "finalize")
    return g


def integrated_temporal_graphs() -> dict[str, StateGraph]:
    return {
        GRAPH_ID: make_integrated_graph(),
        GROK_HEARTBEAT_GRAPH_ID: make_integrated_graph(grok_heartbeat=True),
        GROK_RECOVERY_GRAPH_ID: make_integrated_graph(
            grok_heartbeat=True,
            grok_retry=True,
        ),
    }


@workflow.defn(name="XinaoIntegratedBusWorkflow")
class XinaoIntegratedBusWorkflow:
    """Integrated bus WF — G5 HITL signals + G6 continue-as-new episode phases."""

    def __init__(self) -> None:
        self._hitl_feedback: str | None = None
        self._pending_draft: str | None = None

    @workflow.signal
    async def provide_hitl_feedback(self, feedback: str) -> None:
        """G5 signal — receives human approve/revise feedback (mature HITL compat)."""
        self._hitl_feedback = feedback

    @workflow.query
    def get_pending_draft(self) -> str | None:
        """G5 query — exposes pending draft for external review UI."""
        return self._pending_draft

    @workflow.run
    async def run(self, initial: BusState) -> BusState:
        phase = int(initial.get("episode_phase") or 3)
        max_phase = int(initial.get("episode_max_phase") or 3)
        episode_cache = initial.get("episode_cache")
        if workflow.patched(GROK_RECOVERY_PATCH_ID):
            graph_id = GROK_RECOVERY_GRAPH_ID
        elif workflow.patched(GROK_HEARTBEAT_PATCH_ID):
            graph_id = GROK_HEARTBEAT_GRAPH_ID
        else:
            graph_id = GRAPH_ID
        app = temporal_graph(graph_id, cache=episode_cache).compile()
        result = await app.ainvoke(initial)
        merged: BusState = dict(result)
        draft = str(merged.get("worker_lane_draft_content") or merged.get("content_md") or "")
        if draft:
            self._pending_draft = draft[:2000]
        merged.setdefault("continue_as_new_wired", True)
        merged.setdefault("episode_phase", phase)
        merged.setdefault("episode_max_phase", max_phase)
        if phase < max_phase:
            next_initial: BusState = dict(initial)
            next_initial.update(
                {
                    "episode_phase": phase + 1,
                    "episode_cache": cache(),
                    "continue_as_new_wired": True,
                }
            )
            workflow.continue_as_new(next_initial)
        return merged


def default_initial_state(
    input_path: Path,
    *,
    repo_root: Path = DEFAULT_REPO,
    runtime_root: Path | None = None,
    params_path: Path | None = None,
    workflow_id: str = "",
    dispatch_envelope_ref: Mapping[str, object] | None = None,
    dispatch_route_claim_ref: str = "",
    dispatch_task_run_dir: Path | None = None,
    dispatch_task_run_id: str = "",
) -> BusState:
    rt = resolve_runtime_root(runtime_root or DEFAULT_RUNTIME)
    repo = resolve_repo_root(repo_root)
    resolved_input = resolve_bus_file_path(input_path, repo_root=repo, runtime_root=rt)
    if not resolved_input.is_file():
        for candidate in default_intake_candidates(repo_root=repo, runtime_root=rt):
            if candidate.is_file():
                resolved_input = candidate
                break
    resolved_params = resolve_bus_file_path(
        params_path or DEFAULT_PARAMS,
        repo_root=repo,
        runtime_root=rt,
    )
    params = _load_params_file(
        resolved_params if resolved_params.is_file() else (params_path or DEFAULT_PARAMS)
    )
    initial: BusState = {
        "input_path": str(resolved_input),
        "params_path": str(
            resolved_params if resolved_params.is_file() else (params_path or DEFAULT_PARAMS)
        ),
        "repo_root": str(repo),
        "runtime_root": str(rt),
        "workflow_id": workflow_id,
        "episode_phase": int(params.get("episode_phase_default", 3)),
        "episode_max_phase": int(params.get("episode_max_phase", 3)),
        "react_loop_count": 0,
        "heal_retry_count": 0,
        "heal_failed_checks": [],
    }
    if dispatch_envelope_ref is not None:
        initial["dispatch_envelope_ref"] = {
            "path": str(dispatch_envelope_ref.get("path") or ""),
            "sha256": str(dispatch_envelope_ref.get("sha256") or "").lower(),
        }
    if dispatch_route_claim_ref:
        initial["dispatch_route_claim_ref"] = str(dispatch_route_claim_ref)
    if dispatch_task_run_dir is not None:
        initial["dispatch_task_run_dir"] = str(dispatch_task_run_dir)
    if dispatch_task_run_id:
        initial["dispatch_task_run_id"] = str(dispatch_task_run_id)
    return initial
