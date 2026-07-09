"""Temporal LangGraphPlugin integrated bus — Langfuse + PromotionGate on default hot path."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from temporalio import workflow
from temporalio.contrib.langgraph import cache
from temporalio.contrib.langgraph import graph as temporal_graph
from typing_extensions import TypedDict

from services.agent_runtime.integrated_bus_bus_nodes import (
    ensure_git_repo,
    resolve_bus_file_path,
    resolve_repo_root,
    resolve_runtime_root,
    run_aaq_fanin_bus,
    run_checkpoint_bus,
    run_child_wf_bus,
    run_crawl4ai_bus,
    run_duckdb_bus,
    run_facade_guard_bus,
    run_fanin_bus,
    run_glue_seam_invoke_bus,
    run_heal_bus,
    run_instructor_bus,
    run_memory_bus,
    run_mirror_registry_bus,
    run_mcp_tools_bus,
    run_openhands_bus,
    run_parallel_width_bus,
    run_planner_bus,
    run_pytest_slice_bus,
    run_search_bus,
    run_episode_cache_bus,
    run_hitl_review_bus,
    run_signal_feed_bus,
    run_token_bus,
    run_validate_bus,
    run_watchdog_bus,
)
from services.agent_runtime.integrated_bus_litellm_langfuse import run_gateway_trace_smoke
from services.agent_runtime.thin_provider_client import DEFAULT_BASE_URL, probe_gateway
from services.agent_runtime.integrated_bus_promotion_gate import run_promotion_gate
from services.agent_runtime.codex_s_worker_lane_carrier import run_worker_lane_bus_activity
from services.agent_runtime.pro_review_after_draft import run_pro_review_bus
from services.agent_runtime.thin_bootstrap_runner import git_commit_all
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, l0_intake_markdown, l3_run_sandbox, now_iso

GRAPH_ID = "xinao-integrated-bus-v2"
DEFAULT_PARAMS = DEFAULT_REPO / "materials" / "authority_glue" / "seams" / "integrated_bus_params.v1.json"


class BusState(TypedDict, total=False):
    input_path: str
    duckdb_ok: bool
    watchdog_ok: bool
    params_path: str
    repo_root: str
    runtime_root: str
    workflow_id: str
    content_md: str
    adapter: str
    execution_stdout: str
    execution_backend: str
    gateway_trace_ok: bool
    gateway_trace_skipped: bool
    langfuse_callback_wired: bool
    gateway_named_blocker: str
    promotion_gate_passed: bool
    memory_candidate_id: str
    promotion_evidence_ref: str
    proof_path: str
    commit_hash: str
    validate_ok: bool
    task_package: dict[str, Any]
    search_ok: bool
    search_query: str
    search_hit_count: int
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
    mcp_tools_ok: bool
    mcp_adapter: str
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
    openhands_ok: bool
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


def _activity_options() -> dict[str, Any]:
    return {
        "execute_in": "activity",
        "start_to_close_timeout": timedelta(minutes=5),
    }


def _resolve_gateway_base_url(params: dict[str, Any]) -> str:
    from services.agent_runtime.thin_provider_client import resolve_gateway_base_url

    return resolve_gateway_base_url(str(params.get("gateway_base_url") or "").strip() or None)


async def intake_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    max_chars = int(params.get("max_md_chars", 2000))
    input_path = resolve_bus_file_path(
        state["input_path"],
        repo_root=_repo_root(state),
        runtime_root=_runtime_root(state),
    )
    intake = l0_intake_markdown(input_path, max_chars=max_chars)
    return {
        "content_md": str(intake.get("content_md") or ""),
        "adapter": str(intake.get("adapter") or ""),
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
    params = _load_params_file(_params_path(state))
    instructor = run_instructor_bus(
        content_md=str(state.get("content_md") or ""),
        task_package=validated.get("task_package"),
        params=params,
    )
    validated["task_package"] = instructor.get("task_package") or validated.get("task_package")
    validated["instructor_ok"] = instructor.get("instructor_ok") is True
    return validated


async def signal_feed_node(state: BusState) -> dict[str, Any]:
    return run_signal_feed_bus(runtime_root=_runtime_root(state))


async def planner_node(state: BusState) -> dict[str, Any]:
    return run_planner_bus(task_package=state.get("task_package"))


async def search_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    max_results = int(params.get("search_max_results", 6))
    return run_search_bus(
        repo_root=_repo_root(state),
        content_md=str(state.get("content_md") or ""),
        max_results=max_results,
    )


async def crawl4ai_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_crawl4ai_bus(
        params=params,
        query=str(state.get("search_query") or ""),
    )


async def mcp_tools_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    payload = run_mcp_tools_bus(params=params, repo_root=_repo_root(state))
    payload["react_loop_count"] = int(state.get("react_loop_count") or 0) + 1
    payload["react_conditional_wired"] = True
    return payload


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
    return run_mirror_registry_bus(params=params, runtime_root=_runtime_root(state))


async def glue_seam_invoke_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_glue_seam_invoke_bus(
        params=params,
        runtime_root=_runtime_root(state),
        repo_root=_repo_root(state),
    )


async def openhands_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_openhands_bus(params=params)


async def parallel_width_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    parallel = run_parallel_width_bus(
        params=params,
        runtime_root=_runtime_root(state),
        workflow_id=str(state.get("workflow_id") or ""),
    )
    if int(parallel.get("parallel_width_n") or 0) > 1:
        child = run_child_wf_bus(
            runtime_root=_runtime_root(state),
            workflow_id=str(state.get("workflow_id") or ""),
        )
        parallel.update(child)
    return parallel


async def memory_bus_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    return run_memory_bus(
        runtime_root=_runtime_root(state),
        state=dict(state),
        params=params,
    )


async def qwen_draft_worker_lane_node(state: BusState) -> dict[str, Any]:
    """Qwen default_draft_worker_first — Temporal activity via thin carrier."""
    params = _load_params_file(_params_path(state))
    objective = str(
        (state.get("task_package") or {}).get("user_intent_cn")
        if isinstance(state.get("task_package"), dict)
        else ""
    ) or "333 integrated_bus qwen draft worker lane"
    input_text = "\n".join(
        [
            str(state.get("content_md") or ""),
            "",
            f"planner_ok={state.get('planner_ok')}",
            f"search_query={state.get('search_query') or ''}",
            f"search_hits={state.get('search_hit_count') or 0}",
        ]
    ).strip()
    return run_worker_lane_bus_activity(
        runtime_root=_runtime_root(state),
        workflow_id=str(state.get("workflow_id") or ""),
        mode="draft",
        objective=objective,
        input_text=input_text,
        provider=str(params.get("default_draft_worker") or "qwen"),
        write=True,
        integrated_bus_bound=True,
        gateway_base_url=_resolve_gateway_base_url(params),
    )


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
    params = _load_params_file(_params_path(state))
    draft_ref = str(state.get("worker_lane_artifact_ref") or "")
    draft_content = str(state.get("worker_lane_draft_content") or "")
    review_input = "\n".join(
        [
            "## worker_draft",
            draft_content,
            "",
            "## sandbox_stdout",
            str(state.get("execution_stdout") or ""),
            "",
            "## intake_excerpt",
            str(state.get("content_md") or "")[:4000],
        ]
    ).strip()
    return run_pro_review_bus(
        runtime_root=_runtime_root(state),
        content_md=review_input,
        workflow_id=str(state.get("workflow_id") or ""),
        gateway_base_url=_resolve_gateway_base_url(params),
        draft_artifact_ref=draft_ref or "integrated_bus:worker_lane_draft",
        write=True,
    )


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
    )


async def token_bus_node(state: BusState) -> dict[str, Any]:
    summary = (
        f"integrated_bus workflow={state.get('workflow_id')}\n"
        f"validate={state.get('validate_ok')} search_hits={state.get('search_hit_count')}\n"
        f"gateway={state.get('gateway_trace_ok')} worker_lane={state.get('worker_lane_ok')} "
        f"pro_review={state.get('pro_review_ok')} promotion={state.get('promotion_gate_passed')}\n"
        f"memory_bus={state.get('memory_bus_ok')} glue_seam={state.get('glue_seam_invoke_count')}\n"
    )
    payload = run_token_bus(summary_text=summary, runtime_root=_runtime_root(state))
    adapter = str(payload.get("compression_adapter") or "")
    payload["rtk_adapter"] = adapter if adapter == "rtk" else ""
    payload["caveman_adapter"] = adapter if adapter == "caveman" else ""
    return payload


async def heal_node(state: BusState) -> dict[str, Any]:
    return run_heal_bus(params=_load_params_file(_params_path(state)))


async def checkpoint_node(state: BusState) -> dict[str, Any]:
    return run_checkpoint_bus(runtime_root=_runtime_root(state))


async def gateway_trace_node(state: BusState) -> dict[str, Any]:
    params = _load_params_file(_params_path(state))
    trace = run_gateway_trace_smoke(
        prompt=str(params.get("gateway_smoke_prompt") or "reply with exactly: integrated_bus_trace_ok"),
        model=str(params.get("gateway_model") or "auto"),
        base_url=_resolve_gateway_base_url(params),
    )
    cb = trace.get("callback_config") or {}
    probe_ok = (trace.get("gateway_probe") or {}).get("ok") is True
    completion_ok = trace.get("completion_ok") is True
    skipped = trace.get("skipped_completion") is True or cb.get("skipped") is True
    return {
        "gateway_trace_ok": completion_ok or (probe_ok and cb.get("callback_wired")),
        "gateway_trace_skipped": skipped and not completion_ok,
        "langfuse_callback_wired": cb.get("callback_wired") is True,
        "gateway_named_blocker": str(trace.get("named_blocker") or ""),
    }


async def sandbox_node(state: BusState) -> dict[str, Any]:
    preview = str(state.get("content_md") or "")[:300].replace('"', "'").replace("\n", " ")
    code = (
        "from datetime import datetime\n"
        f'print("IntegratedBus-LangGraphPlugin", datetime.now().isoformat())\n'
        f'print("{preview}...")\n'
    )
    execution = l3_run_sandbox(code, prefer_docker=True, prefer_e2b=False)
    stdout = str(execution.get("stdout") or execution.get("stderr") or "")
    return {
        "execution_stdout": stdout,
        "execution_backend": str(execution.get("adapter") or "docker"),
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


async def finalize_node(state: BusState) -> dict[str, Any]:
    repo = _repo_root(state)
    proof_path = repo / "integrated_bus_proof.txt"
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
        f"pro_review_ok={state.get('pro_review_ok')}",
        f"pro_review_model={state.get('pro_review_model') or 'none'}",
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
    ensure_git_repo(repo)
    commit_info = git_commit_all(repo, "Integrated bus: LangGraphPlugin + Langfuse + PromotionGate")
    return {
        "proof_path": str(proof_path),
        "commit_hash": str(commit_info.get("commit_hash") or ""),
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
    g.add_node("qwen_draft_worker_lane", qwen_draft_worker_lane_node, metadata=_activity_options())
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
    g.add_edge("planner", "gateway_trace")
    g.add_edge("gateway_trace", "search")
    g.add_edge("search", "crawl4ai")
    g.add_edge("crawl4ai", "mcp_tools")
    g.add_conditional_edges("mcp_tools", should_react_continue)
    g.add_edge("mirror_registry", "glue_seam_invoke")
    g.add_edge("glue_seam_invoke", "openhands")
    g.add_edge("openhands", "parallel_width")
    g.add_edge("parallel_width", "qwen_draft_worker_lane")
    g.add_edge("qwen_draft_worker_lane", "sandbox")
    g.add_edge("sandbox", "pro_review_after_draft")
    g.add_edge("pro_review_after_draft", "hitl_review")
    g.add_edge("hitl_review", "fanin")
    g.add_edge("fanin", "aaq")
    g.add_edge("aaq", "promotion_gate")
    g.add_edge("promotion_gate", "memory_bus")
    g.add_edge("memory_bus", "token_bus")
    g.add_edge("token_bus", "heal")
    g.add_edge("heal", "checkpoint")
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
        for candidate in (
            repo / "materials" / "phase0_test_input.md",
            DEFAULT_REPO / "materials" / "phase0_test_input.md",
            Path("/app") / "materials" / "phase0_test_input.md",
        ):
            if candidate.is_file():
                resolved_input = candidate
                break
    resolved_params = resolve_bus_file_path(
        params_path or DEFAULT_PARAMS,
        repo_root=repo,
        runtime_root=rt,
    )
    params = _load_params_file(resolved_params if resolved_params.is_file() else (params_path or DEFAULT_PARAMS))
    return {
        "input_path": str(resolved_input),
        "params_path": str(resolved_params if resolved_params.is_file() else (params_path or DEFAULT_PARAMS)),
        "repo_root": str(repo),
        "runtime_root": str(rt),
        "workflow_id": workflow_id,
        "episode_phase": int(params.get("episode_phase_default", 3)),
        "episode_max_phase": int(params.get("episode_max_phase", 3)),
        "react_loop_count": 0,
    }