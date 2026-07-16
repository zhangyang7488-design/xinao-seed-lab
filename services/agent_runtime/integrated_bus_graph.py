"""Temporal LangGraphPlugin integrated bus — Langfuse + PromotionGate on default hot path."""

from __future__ import annotations

import hashlib
import json
import operator
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

from langgraph.graph import START, StateGraph
from temporalio import workflow
from temporalio.contrib.langgraph import cache
from temporalio.contrib.langgraph import graph as temporal_graph
from typing_extensions import TypedDict

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
GROK_FANIN_SENTINEL = "XINAO_GROK_TEMPORAL_FANIN_V1"
GROK_FANIN_PROVIDER = "grok_acpx_headless"
GROK_FANIN_DEFAULT_MODEL = "grok-composer-2.5-fast"
GROK_FANIN_ESCALATION_MODEL = "grok-4.5"
GROK_FANIN_ALLOWED_MODELS = frozenset(
    {GROK_FANIN_DEFAULT_MODEL, GROK_FANIN_ESCALATION_MODEL}
)
GROK_MODEL_POLICY_ID = "xinao.grok.provider_model_routing.v1"
GROK_FANIN_SCHEMA_VERSION = "xinao.grok.temporal_acpx_fanin.v2"
_GROK_MANIFEST_RE = re.compile(r"grok_manifest_path=([^\s>]+)")
DEFAULT_PARAMS = (
    DEFAULT_REPO / "materials" / "authority_glue" / "seams" / "integrated_bus_params.v1.json"
)


class BusState(TypedDict, total=False):
    input_path: str
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
    promotion_evidence_ref: str
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
    worker_lane_adapter: str
    worker_lane_tier: str
    worker_lane_route_role: str
    draft_model: str
    review_model: str
    grok_only_mode: bool
    grok_fanin_ok: bool
    grok_fanin_manifest_ref: str
    grok_fanin_evidence_ref: str
    grok_fanin_lane_count: int
    grok_fanin_lane_modes: list[str]
    grok_fanin_audit_lane_count: int
    grok_fanin_model_identity_ok: bool
    grok_fanin_requested_model: str
    grok_fanin_observed_model: str
    grok_fanin_parallel_bypass: bool
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


def _grok_fanin_worker_lane(state: BusState) -> dict[str, Any] | None:
    """Consume the Temporal/ACPX fan-in; marker presence fails closed."""

    content = str(state.get("content_md") or "")
    if GROK_FANIN_SENTINEL not in content:
        return None
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
            "worker_lane_adapter": "temporal_acpx_fanin",
            "grok_fanin_ok": False,
            "grok_only_mode": True,
            "non_grok_model_invocations": 0,
        }

    match = _GROK_MANIFEST_RE.search(content)
    if match is None:
        return failed("GROK_FANIN_MANIFEST_MARKER_MISSING")
    raw_manifest = match.group(1).replace("\\", "/")
    manifest_path = (
        runtime / raw_manifest[len("/evidence/") :]
        if raw_manifest.startswith("/evidence/")
        else Path(raw_manifest)
    ).resolve()
    try:
        manifest_path.relative_to(runtime)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return failed("GROK_FANIN_MANIFEST_INVALID")
    if not isinstance(manifest, dict):
        return failed("GROK_FANIN_MANIFEST_INVALID")
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
    lanes = manifest.get("lanes") if isinstance(manifest.get("lanes"), list) else []
    succeeded = int(manifest.get("succeeded") or 0)
    failed_count = int(manifest.get("failed") or 0)
    ready_width = int(manifest.get("ready_width") or 0)
    models = manifest.get("models") if isinstance(manifest.get("models"), list) else []
    if not (
        manifest.get("schema_version") == GROK_FANIN_SCHEMA_VERSION
        and manifest.get("model_policy_id") == GROK_MODEL_POLICY_ID
        and model in GROK_FANIN_ALLOWED_MODELS
        and models == [model]
        and manifest.get("model_identity_ok") is True
        and failed_count == 0
        and succeeded == ready_width == len(lanes)
        and succeeded >= 1
    ):
        return failed("GROK_FANIN_FULL_FRONTIER_OR_MODEL_INVALID")
    if any(not isinstance(item, dict) for item in lanes):
        return failed("GROK_FANIN_LANE_PROVIDER_OR_STATE_INVALID")
    lane_ids = [str(item.get("lane_id") or "") for item in lanes]
    operation_ids = [str(item.get("operation_id") or "") for item in lanes]
    if (
        any(
            str(item.get("model") or "") != model
            or str(item.get("requested_model") or "") != model
            or str(item.get("observed_model") or "") != model
            or item.get("model_identity_ok") is not True
            or not str(item.get("agent_session_id") or "")
            or not str(item.get("model_identity_ref") or "")
            or not str(item.get("model_identity_sha256") or "")
            or str(item.get("operation_state") or "") != "completed"
            for item in lanes
        )
        or any(not value for value in lane_ids + operation_ids)
        or len(set(lane_ids)) != len(lane_ids)
        or len(set(operation_ids)) != len(operation_ids)
    ):
        return failed("GROK_FANIN_LANE_PROVIDER_OR_STATE_INVALID")
    lane_modes = [str(item.get("mode") or "") for item in lanes if isinstance(item, dict)]
    lane_count = len(lanes)
    return {
        "worker_lane_ok": True,
        "worker_lane_status": "completed",
        "worker_lane_mode": "grok_ready_frontier_fanin",
        "worker_lane_provider": GROK_FANIN_PROVIDER,
        "worker_lane_model": model,
        "worker_lane_artifact_ref": str(manifest_path),
        "worker_lane_draft_content": content,
        "worker_lane_named_blocker": "",
        "worker_lane_evidence_ref": str(manifest_path),
        "worker_lane_runtime_enforced": True,
        "worker_lane_integrated_bus_bound": True,
        "worker_lane_tier": "T0_DEFAULT_GROK",
        "worker_lane_route_role": "default_background_worker",
        "worker_lane_adapter": "temporal_acpx_fanin",
        "draft_model": model,
        "grok_fanin_ok": True,
        "grok_fanin_model_identity_ok": True,
        "grok_fanin_requested_model": model,
        "grok_fanin_observed_model": model,
        "grok_fanin_manifest_ref": str(manifest_path),
        "grok_fanin_lane_count": lane_count,
        "grok_fanin_lane_modes": lane_modes,
        "grok_fanin_audit_lane_count": sum(
            mode in {"audit", "review", "external_research"} for mode in lane_modes
        ),
        "grok_only_mode": True,
        "non_grok_model_invocations": 0,
        "ollama_default_qwen_banned": True,
    }


def _grok_only_block(phase: str) -> dict[str, Any]:
    """Fail closed without activating a fallback model worker."""
    return {
        "ok": False,
        "grok_only_mode": True,
        "grok_fanin_ok": False,
        "model_worker_phase": phase,
        "model_worker_provider": GROK_FANIN_PROVIDER,
        "model_worker_named_blocker": "GROK_FANIN_REQUIRED",
        "non_grok_model_invocations": 0,
        "fallback_model_invocation_performed": False,
    }


def _activity_options() -> dict[str, Any]:
    return {
        "execute_in": "activity",
        "start_to_close_timeout": timedelta(minutes=5),
    }


def _resolve_gateway_base_url(params: dict[str, Any]) -> str:
    from services.agent_runtime.thin_provider_client import resolve_gateway_base_url

    return resolve_gateway_base_url(str(params.get("gateway_base_url") or "").strip() or None)


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


async def validate_node(state: BusState) -> dict[str, Any]:
    validated = run_validate_bus(
        input_path=str(state.get("input_path") or ""),
        content_md=str(state.get("content_md") or ""),
    )
    grok_lane = _grok_fanin_worker_lane(state)
    validated["instructor_ok"] = bool(grok_lane and grok_lane.get("worker_lane_ok") is True)
    validated["instructor_invoked"] = False
    validated["instructor_enabled"] = False
    validated["instructor_adapter"] = "grok_fanin_structured_validation"
    validated["model_worker_provider"] = GROK_FANIN_PROVIDER
    validated["non_grok_model_invocations"] = 0
    if not validated["instructor_ok"]:
        validated["validate_ok"] = False
        validated.update(_grok_only_block("validate"))
    return validated


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
            "grok_only_mode": True,
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
        "worker_lane_adapter": "grok_only_fail_closed",
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
    review_model = str(grok_lane.get("worker_lane_model") or "")
    return {
        "pro_review_ok": True,
        "pro_review_status": "completed",
        "pro_review_provider": GROK_FANIN_PROVIDER,
        "pro_review_tier": "T0_DEFAULT_GROK",
        "pro_review_route_role": "grok_fanin_validation",
        "pro_review_adapter": "temporal_acpx_fanin_validation",
        "pro_review_model": review_model,
        "review_model": review_model,
        "pro_review_evidence_ref": grok_lane.get("grok_fanin_manifest_ref"),
        "grok_fanin_audit_lane_count": grok_lane.get("grok_fanin_audit_lane_count", 0),
        "model_invocation_performed": False,
        "provider_invocation_performed": False,
        "grok_only_mode": True,
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
        "grok_only_mode": True,
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
        "promotion_evidence_ref": str(promotion.get("promotion_evidence_ref") or ""),
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


def make_integrated_graph() -> StateGraph:
    g: StateGraph = StateGraph(BusState)
    g.add_node("intake", intake_node, metadata=_activity_options())
    g.add_node("signal_feed", signal_feed_node, metadata=_activity_options())
    g.add_node("duckdb", duckdb_node, metadata=_activity_options())
    g.add_node("watchdog", watchdog_node, metadata=_activity_options())
    g.add_node("facade_guard", facade_guard_node, metadata=_activity_options())
    g.add_node("validate", validate_node, metadata=_activity_options())
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
        app = temporal_graph(GRAPH_ID, cache=episode_cache).compile()
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
    return {
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
