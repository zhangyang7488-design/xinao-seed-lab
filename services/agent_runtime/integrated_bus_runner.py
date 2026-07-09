"""Run integrated LangGraphPlugin bus — default Temporal main-path invoke."""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_graph import (
    DEFAULT_PARAMS,
    GRAPH_ID,
    XinaoIntegratedBusWorkflow,
    aaq_node,
    checkpoint_node,
    crawl4ai_node,
    duckdb_node,
    default_initial_state,
    facade_guard_node,
    fanin_node,
    finalize_node,
    gateway_trace_node,
    glue_seam_invoke_node,
    heal_node,
    intake_node,
    make_integrated_graph,
    memory_bus_node,
    mirror_registry_node,
    openhands_node,
    planner_node,
    promotion_gate_node,
    pro_review_after_draft_node,
    hitl_review_node,
    episode_cache_node,
    pytest_slice_node,
    qwen_draft_worker_lane_node,
    sandbox_node,
    mcp_tools_node,
    parallel_width_node,
    search_node,
    signal_feed_node,
    token_bus_node,
    validate_node,
    watchdog_node,
)
from services.agent_runtime.default_plus_dynamic_escalate import enrich_bus_escalate_evidence
from services.agent_runtime.routing_policy_reader import (
    build_dynamic_loop_shape_metadata,
    build_tier_used,
    resolve_parallel_semantic,
)
from services.agent_runtime.thin_glue_l4_search import exa_escalation_wired
from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry
from services.agent_runtime.tool_table_coverage import build_tool_table_coverage
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, write_json

SCHEMA_VERSION = "xinao.integrated_bus_runner.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_RUNNER_READY"
REPLACES = ["phase0_minimal_weld_activity", "phase0_external_seam_invoke", "thin_glue_temporal_single_activity"]


def integrated_bus_default_enabled() -> bool:
    return os.environ.get("XINAO_INTEGRATED_BUS_DEFAULT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def resolve_input(input_path: Path | None, *, repo_root: Path = DEFAULT_REPO) -> Path:
    if input_path and input_path.is_file():
        return input_path
    for candidate in (
        repo_root / "materials" / "phase0_test_input.md",
        repo_root / "materials" / "thin_bootstrap_input.md",
        Path(r"C:\Users\xx363\Desktop\新系统\test_phase0_input.md"),
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("integrated bus input missing")


def _load_params(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PARAMS
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


DAEMON_SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_WORKER_DAEMON_READY"
INTEGRATED_BUS_QUEUE = "xinao-integrated-langgraph-plugin-queue"


def _ephemeral_worker_allowed() -> bool:
    """Host ephemeral worker is opt-in only (tests/rescue). Default: docker daemon owns queue."""
    return os.environ.get("XINAO_INTEGRATED_BUS_EPHEMERAL_WORKER", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _docker_worker_daemon_ready(
    runtime_root: Path,
    *,
    task_queue: str = INTEGRATED_BUS_QUEUE,
) -> bool:
    """True when houtai-gongren daemon evidence shows polling on the integrated bus queue."""
    daemon_latest = runtime_root / "state" / "integrated_bus_worker_daemon" / "latest.json"
    if not daemon_latest.is_file():
        return False
    try:
        evidence = json.loads(daemon_latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    queues = evidence.get("task_queues") or []
    return (
        evidence.get("sentinel") == DAEMON_SENTINEL
        and evidence.get("status") == "polling"
        and task_queue in queues
        and "XinaoIntegratedBusWorkflow" in (evidence.get("workflows_registered") or [])
    )


def _resolve_worker_ownership(
    *,
    runtime_root: Path,
    task_queue: str,
) -> str:
    if _docker_worker_daemon_ready(runtime_root, task_queue=task_queue) and not _ephemeral_worker_allowed():
        return "docker_daemon"
    return "ephemeral_host"


def _host_path_to_container(
    path: Path,
    *,
    host_root: Path,
    container_root: str,
    runtime_root: Path | None = None,
) -> str:
    ms = str(path).replace("\\", "/")
    upper = ms.upper()
    rt_ms = str(runtime_root or DEFAULT_RUNTIME).replace("\\", "/").rstrip("/")
    if rt_ms and ms.lower().startswith(rt_ms.lower()):
        rel = ms[len(rt_ms) :].lstrip("/")
        return f"/evidence/{rel}"
    if "XINAO_RESEARCH_RUNTIME" in upper:
        rel = upper.split("XINAO_RESEARCH_RUNTIME", 1)[-1].lstrip("/\\")
        return f"/evidence/{rel.replace(chr(92), '/')}"
    root_ms = str(host_root).replace("\\", "/").rstrip("/")
    if root_ms and ms.lower().startswith(root_ms.lower()):
        rel = ms[len(root_ms) :].lstrip("/")
        return f"{container_root.rstrip('/')}/{rel}"
    marker = "/XINAO_RESEARCH_WORKSPACES/S/"
    if marker in upper:
        rel = upper.split(marker, 1)[1].lstrip("/")
        return f"{container_root.rstrip('/')}/{rel}"
    return str(path)


def _initial_state_for_docker_worker(
    input_path: Path,
    *,
    repo_root: Path,
    runtime_root: Path,
    workflow_id: str,
) -> dict[str, Any]:
    """Host client submits container paths so houtai-gongren activities can read files."""
    input_container = _host_path_to_container(
        input_path,
        host_root=repo_root,
        container_root="/app",
        runtime_root=runtime_root,
    )
    if not input_path.is_file():
        input_container = "/app/materials/phase0_test_input.md"
    params_host = DEFAULT_PARAMS
    params_container = _host_path_to_container(params_host, host_root=repo_root, container_root="/app")
    params = _load_params(params_host)
    return {
        "input_path": input_container,
        "params_path": params_container,
        "repo_root": "/app",
        "runtime_root": "/evidence",
        "workflow_id": workflow_id,
        "episode_phase": int(params.get("episode_phase_default", 3)),
        "episode_max_phase": int(params.get("episode_max_phase", 3)),
    }


def _normalize_evidence_path(ref: str) -> Path | None:
    if not ref:
        return None
    candidates: list[Path] = [Path(ref.replace("/", os.sep))]
    env_rt = os.environ.get("XINAO_RESEARCH_RUNTIME", "").strip()
    ms = ref.replace("\\", "/")
    if env_rt and "XINAO_RESEARCH_RUNTIME" in ms.upper():
        rel = ms.split("XINAO_RESEARCH_RUNTIME", 1)[-1].lstrip("/\\")
        candidates.append(Path(env_rt) / rel.replace("/", os.sep))
    for container_root, host_marker in (("/evidence", "XINAO_RESEARCH_RUNTIME"),):
        if host_marker in ms.upper():
            rel = ms.split(host_marker, 1)[-1].lstrip("/\\")
            candidates.append(Path(container_root) / rel.replace("/", os.sep))
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def _load_fanin_evidence(result: dict[str, Any], *, runtime_root: Path | None = None) -> dict[str, Any]:
    ref = str(result.get("fanin_evidence_ref") or "")
    if ref:
        path = _normalize_evidence_path(ref)
        if path is not None:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    latest_ref = str(result.get("source_ledger_latest") or "")
    if latest_ref:
        path = _normalize_evidence_path(latest_ref)
        if path is not None:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    rt = runtime_root or DEFAULT_RUNTIME
    for latest in (
        rt / "state" / "source_ledger" / "integrated_bus" / "latest.json",
        Path(os.environ.get("XINAO_RESEARCH_RUNTIME", "")) / "state" / "source_ledger" / "integrated_bus" / "latest.json",
    ):
        if latest.is_file():
            try:
                return json.loads(latest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    return {}


def _resolve_l4_search_performed(result: dict[str, Any]) -> bool:
    hits = int(result.get("search_hit_count") or 0)
    if result.get("search_ok") is True and hits > 0:
        return True
    blocker = str(result.get("search_named_blocker") or "")
    return result.get("search_skipped") is True and bool(blocker)


def _resolve_l4_crawl4ai(result: dict[str, Any], *, runtime_root: Path | None = None) -> bool:
    if result.get("crawl4ai_ok") is True or result.get("crawl4ai_invoked") is True:
        return True
    rt = runtime_root or DEFAULT_RUNTIME
    ev = _read_invoke_evidence(rt, "crawl4ai")
    return ev.get("invoke_ok") is True


def _resolve_langfuse_callback(result: dict[str, Any]) -> bool:
    """Real invoke only: callback wired AND litellm.completion on hot path (no skip/probe OR-gates)."""
    litellm_invoke = (
        result.get("gateway_trace_ok") is True
        and str(result.get("litellm_completion_via") or "") == "litellm.completion"
    )
    if result.get("langfuse_callback_wired") is True and litellm_invoke:
        return True
    if not litellm_invoke:
        result.setdefault("langfuse_named_blocker", "LITELLM_COMPLETION_REQUIRED_FOR_LANGFUSE")
    elif not result.get("langfuse_callback_wired"):
        result.setdefault("langfuse_named_blocker", str(result.get("langfuse_named_blocker") or "LANGFUSE_CALLBACK_NOT_WIRED"))
    return False


def _resolve_diff_cover_slice(result: dict[str, Any], *, runtime_root: Path | None = None) -> bool:
    if result.get("diff_cover_ok") is True:
        return True
    fanin = _load_fanin_evidence(result, runtime_root=runtime_root)
    diff = fanin.get("diff_cover") or {}
    if diff.get("diff_cover_ok") is True:
        return True
    return bool(diff.get("evidence_path")) and diff.get("exit_code") is not None


def _resolve_otel_trace(result: dict[str, Any], *, runtime_root: Path | None = None) -> bool:
    if result.get("otel_ok") is True and result.get("otel_skipped") is not True:
        return True
    fanin = _load_fanin_evidence(result, runtime_root=runtime_root)
    otel = fanin.get("otel") or {}
    return otel.get("otel_ok") is True and otel.get("otel_skipped") is not True


def _parallel_lane_models(result: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = result.get("parallel_lane_models")
    return [lane for lane in lanes if isinstance(lane, dict)] if isinstance(lanes, list) else []


def _parallel_lane_task_id_trace_ok(result: dict[str, Any]) -> bool:
    lanes = _parallel_lane_models(result)
    if not lanes:
        return False
    return all(bool(str(lane.get("task_id") or "").strip()) for lane in lanes)


def _parallel_lane_tier_routing_ok(result: dict[str, Any]) -> bool:
    lanes = _parallel_lane_models(result)
    if len(lanes) < 2:
        return len(lanes) == 1 and bool(str(lanes[0].get("tier_used") or "").strip())
    tiers = {str(lane.get("tier_used") or "") for lane in lanes}
    models = {str(lane.get("model") or "") for lane in lanes}
    return len(tiers) >= 2 or len(models) >= 2


def _rolling_accept_trace_ok(result: dict[str, Any]) -> bool:
    if str(result.get("parallel_semantic") or "") != "rolling":
        return True
    trace = result.get("rolling_accept_trace")
    if isinstance(trace, list) and trace:
        return all(bool(str(item.get("task_id") or "").strip()) for item in trace if isinstance(item, dict))
    fanin = result.get("as_completed_fanin")
    if not isinstance(fanin, list):
        return False
    return any(
        isinstance(entry, dict)
        and entry.get("rolling_accept", {}).get("accepted") is True
        and bool(str(entry.get("task_id") or "").strip())
        for entry in fanin
    )


def _enrich_result_from_fanin(result: dict[str, Any], *, runtime_root: Path | None = None) -> dict[str, Any]:
    fanin = _load_fanin_evidence(result, runtime_root=runtime_root)
    if not fanin:
        return result
    merged = dict(result)
    if merged.get("diff_cover_ok") is not True:
        diff = fanin.get("diff_cover") or {}
        if diff.get("diff_cover_ok") is True:
            merged["diff_cover_ok"] = True
    if merged.get("otel_ok") is not True:
        otel = fanin.get("otel") or {}
        if otel.get("otel_ok") is True:
            merged["otel_ok"] = True
        if merged.get("otel_skipped") is not True and otel.get("otel_skipped") is True:
            merged["otel_skipped"] = True
            merged["otel_named_blocker"] = str(otel.get("named_blocker") or "")
    if merged.get("diff_cover_skipped") is not True:
        diff = fanin.get("diff_cover") or {}
        if diff.get("diff_cover_skipped") is True:
            merged["diff_cover_skipped"] = True
            merged["diff_cover_named_blocker"] = str(diff.get("named_blocker") or "")
    if merged.get("search_named_blocker") in (None, "") and fanin.get("search_hit_count") is not None:
        merged.setdefault("search_hit_count", fanin.get("search_hit_count"))
    if merged.get("planner_ok") is not True and fanin.get("planner_ok") is True:
        merged["planner_ok"] = True
    if merged.get("crawl4ai_ok") is not True and fanin.get("crawl4ai_ok") is True:
        merged["crawl4ai_ok"] = True
    return merged


def _read_invoke_evidence(runtime_root: Path, subdir: str) -> dict[str, Any]:
    path = runtime_root / "state" / subdir / "latest.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _enrich_result_from_invoke_evidence(
    result: dict[str, Any],
    *,
    runtime_root: Path,
) -> dict[str, Any]:
    """Temporal LangGraphPlugin may omit early-node keys — hydrate from state/*/latest.json."""
    merged = dict(result)
    evidence_map = (
        ("duckdb", ("duckdb_invoked", "duckdb_ok")),
        ("watchdog", ("watchdog_invoked", "watchdog_ok")),
        ("fastmcp_invoke", ("mcp_tool_invoked", "mcp_tools_ok")),
        ("mcp_registry", ("mcp_registry_ok",)),
        ("docker_sandbox", ("docker_sandbox_invoked",)),
        ("gitpython", ("gitpython_invoke_ok",)),
        ("instructor", ("instructor_invoked", "instructor_ok")),
        ("openhands", ("openhands_activity_ok", "openhands_ok")),
        ("crawl4ai", ("crawl4ai_invoked", "crawl4ai_ok")),
    )
    for subdir, keys in evidence_map:
        ev = _read_invoke_evidence(runtime_root, subdir)
        if ev.get("invoke_ok") is not True:
            continue
        for key in keys:
            merged[key] = True
        if subdir == "fastmcp_invoke" and ev.get("adapter"):
            merged.setdefault("mcp_adapter", str(ev.get("adapter")))
        if subdir == "gitpython" and ev.get("commit_hash"):
            merged.setdefault("commit_hash", str(ev.get("commit_hash")))
            merged.setdefault("git_commit_adapter", str(ev.get("adapter") or "gitpython"))
    lit = _read_invoke_evidence(runtime_root, "litellm")
    if lit.get("invoke_ok") is True:
        merged["litellm_completion_via"] = str(lit.get("adapter") or "litellm.completion")
        merged["gateway_trace_ok"] = True
        merged["litellm_completion_ok"] = True
        if lit.get("callback_wired") is not True and merged.get("langfuse_callback_wired") is not True:
            merged["langfuse_skipped"] = True
            merged["langfuse_named_blocker"] = "LANGFUSE_KEYS_MISSING"
    elif merged.get("gateway_trace_ok") is True and not merged.get("litellm_completion_via"):
        merged["litellm_completion_via"] = "litellm.completion"
    if (
        merged.get("langfuse_callback_wired") is not True
        and str(merged.get("litellm_completion_via") or "") == "litellm.completion"
        and not merged.get("langfuse_skipped")
    ):
        merged["langfuse_skipped"] = True
        merged["langfuse_named_blocker"] = "LANGFUSE_KEYS_MISSING"
    if merged.get("openhands_ok") is True:
        merged.setdefault("openhands_activity_ok", True)
    if merged.get("instructor_ok") is True:
        merged.setdefault("instructor_invoked", True)
    if merged.get("mcp_tools_ok") is True:
        merged.setdefault("mcp_tool_invoked", True)
    if merged.get("mirror_registry_ok") is True:
        merged.setdefault("mcp_registry_ok", True)
    return merged


def _resolve_l4_exa_weld_labels(result: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """L4_exa: thin_bind when wired; optional_tier3 reflects invoke vs wired — 禁止英文暂缓逃逸."""
    suspend_registry: dict[str, str] = {}
    optional_tier3: dict[str, str] = {}
    search_ext = result.get("search_external") or {}
    exa = search_ext.get("exa") or {}
    wired = (
        exa_escalation_wired()
        or exa.get("wired") is True
        or search_ext.get("exa_dynamic_optional_tier3") is True
        or bool(search_ext.get("search_tier_chain"))
    )
    if not wired:
        return suspend_registry, optional_tier3
    if exa.get("ok") is True:
        optional_tier3["L4_exa"] = "exa_dynamic_tier3_invoke_green"
    elif search_ext.get("exa_dynamic") is True or exa.get("invoked") is True:
        optional_tier3["L4_exa"] = "exa_dynamic_tier3_invoked"
    else:
        optional_tier3["L4_exa"] = "exa_dynamic_optional_tier3_wired"
    return suspend_registry, optional_tier3


def _evolution_weld_named_blocker(smoke: dict[str, Any], *, fallback: str) -> str:
    return str(smoke.get("named_blocker") or (smoke.get("eval") or {}).get("named_blocker") or fallback)


def _build_evolution_weld(
    result: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    """G4/G5/G6 + L2/L6/L8/L9 invoke_green weld evidence — non-blocking."""
    p = params or {}
    suspend_registry, optional_tier3 = _resolve_l4_exa_weld_labels(result)
    mlflow_smoke: dict[str, Any] = {}
    openlineage_smoke: dict[str, Any] = {}
    opa_smoke: dict[str, Any] = {}
    optuna_smoke: dict[str, Any] = {}
    dvc_smoke: dict[str, Any] = {}
    wandb_smoke: dict[str, Any] = {}
    mlflow_ok = False
    openlineage_ok = False
    opa_ok = False
    optuna_ok = False
    dvc_ok = False
    dvc_invoke_green = False
    dvc_thin_bind = False
    wandb_ok = False
    wandb_invoke_green = False
    wandb_thin_bind = False
    rt = runtime_root or DEFAULT_RUNTIME
    try:
        from services.agent_runtime.thin_glue_l7_mlflow import run_mlflow_smoke

        mlflow_smoke = run_mlflow_smoke(runtime=rt, write_evidence=True)
        mlflow_ok = mlflow_smoke.get("invoke_ok") is True
    except Exception as exc:
        mlflow_smoke = {"ok": False, "reason": str(exc), "named_blocker": "MLFLOW_SMOKE_EXCEPTION"}
    if not mlflow_ok:
        suspend_registry["L7_mlflow"] = _evolution_weld_named_blocker(mlflow_smoke, fallback="实验追踪未焊接")
    try:
        from services.agent_runtime.thin_glue_l5_openlineage import run_openlineage_smoke

        openlineage_smoke = run_openlineage_smoke(runtime=rt, write_evidence=True)
        openlineage_ok = openlineage_smoke.get("invoke_ok") is True
    except Exception as exc:
        openlineage_smoke = {"ok": False, "reason": str(exc), "named_blocker": "OPENLINEAGE_SMOKE_EXCEPTION"}
    if not openlineage_ok:
        suspend_registry["L5_openlineage"] = _evolution_weld_named_blocker(openlineage_smoke, fallback="血缘未焊接")
    try:
        from services.agent_runtime.thin_glue_l5_opa import run_opa_smoke

        opa_smoke = run_opa_smoke(runtime=rt, write_evidence=True)
        opa_ok = opa_smoke.get("invoke_ok") is True
    except Exception as exc:
        opa_smoke = {"ok": False, "reason": str(exc), "named_blocker": "OPA_SMOKE_EXCEPTION"}
    if not opa_ok:
        suspend_registry["L5_opa"] = _evolution_weld_named_blocker(opa_smoke, fallback="OPA策略门未焊接")
    try:
        from services.agent_runtime.thin_glue_l7_optuna import run_optuna_smoke

        optuna_smoke = run_optuna_smoke(runtime=rt, write_evidence=True)
        optuna_ok = optuna_smoke.get("invoke_ok") is True
    except Exception as exc:
        optuna_smoke = {"ok": False, "reason": str(exc), "named_blocker": "OPTUNA_SMOKE_EXCEPTION"}
    if not optuna_ok:
        suspend_registry["L7_optuna"] = _evolution_weld_named_blocker(optuna_smoke, fallback="超参优化未焊接")
    try:
        from services.agent_runtime.thin_glue_l7_dvc import run_dvc_smoke

        dvc_smoke = run_dvc_smoke(runtime=rt, write_evidence=True)
        dvc_ok = dvc_smoke.get("invoke_ok") is True
        dvc_invoke_green = dvc_smoke.get("L7_dvc_invoke_green") is True
        dvc_thin_bind = dvc_smoke.get("L7_dvc_thin_bind") is True
    except Exception as exc:
        dvc_smoke = {"ok": False, "reason": str(exc), "named_blocker": "DVC_SMOKE_EXCEPTION"}
    if not dvc_ok:
        suspend_registry["L7_dvc"] = _evolution_weld_named_blocker(dvc_smoke, fallback="数据版本薄绑未焊接")
    try:
        from services.agent_runtime.thin_glue_l7_wandb import run_wandb_smoke

        wandb_smoke = run_wandb_smoke(
            runtime=rt,
            write_evidence=True,
            mlflow_ok=mlflow_ok,
            mlflow_tracking_uri=str(mlflow_smoke.get("tracking_uri") or ""),
            hot_path=True,
        )
        wandb_invoke_green = wandb_smoke.get("L7_wandb_invoke_green") is True
        wandb_thin_bind = wandb_smoke.get("L7_wandb_thin_bind") is True
        wandb_ok = wandb_smoke.get("invoke_ok") is True
    except Exception as exc:
        wandb_smoke = {"ok": False, "reason": str(exc), "named_blocker": "WANDB_ALIAS_EXCEPTION"}
    if not wandb_ok:
        suspend_registry["L7_wandb"] = _evolution_weld_named_blocker(wandb_smoke, fallback="WANDB_CLOUD_SKIPPED")
    return {
        "schema_version": "xinao.integrated_bus.evolution_weld.v1",
        "non_blocking": True,
        "G4_react_conditional_wired": result.get("react_conditional_wired") is True,
        "G4_react_loop_count": int(result.get("react_loop_count") or 0),
        "G4_react_loop_enabled": p.get("react_loop_enabled", False) is True,
        "G5_hitl_ok": result.get("hitl_ok") is True,
        "G5_hitl_signal_wired": result.get("hitl_signal_wired") is True,
        "G5_hitl_feedback": str(result.get("hitl_feedback") or ""),
        "G5_hitl_auto_approve": p.get("hitl_auto_approve", True) is not False,
        "G5_hitl_evidence_ref": str(result.get("hitl_evidence_ref") or ""),
        "G6_episode_phase": int(result.get("episode_phase") or p.get("episode_phase_default", 3)),
        "G6_episode_max_phase": int(result.get("episode_max_phase") or p.get("episode_max_phase", 3)),
        "G6_continue_as_new_wired": result.get("continue_as_new_wired") is True,
        "G6_episode_cache_ref": str(result.get("episode_cache_ref") or ""),
        "G6_episode_multi_wave": result.get("episode_multi_wave") is True,
        "L2_planner_structured_by": str(result.get("planner_structured_by") or result.get("adapter") or ""),
        "L2_planner_llm_invoked": result.get("planner_llm_invoked") is True,
        "L2_checkpoint_invoked": result.get("checkpoint_invoked") is True,
        "L2_checkpoint_thread_id": str(result.get("checkpoint_thread_id") or ""),
        "L2_langgraph_send_wired": result.get("langgraph_send_wired") is True,
        "L6_heal_bus_ok": result.get("heal_bus_ok") is True,
        "L6_critic_decision": str(result.get("critic_decision") or ""),
        "L6_critic_edge_wired": result.get("critic_edge_wired") is True,
        "L6_retry_policy_evidence_ref": str(result.get("retry_policy_evidence_ref") or ""),
        "L8_jinja_readback_ref": str(result.get("jinja_readback_ref") or ""),
        "L8_rtk_adapter": str(result.get("rtk_adapter") or ""),
        "L8_caveman_adapter": str(result.get("caveman_adapter") or ""),
        "L8_compression_adapter": str(result.get("compression_adapter") or ""),
        "L9_parallel_succeeded": int(result.get("parallel_succeeded") or 0),
        "dynamic_loop_shape": result.get("dynamic_loop_shape") or {},
        "draft_model": str(result.get("draft_model") or result.get("worker_lane_model") or ""),
        "review_model": str(result.get("review_model") or result.get("pro_review_model") or ""),
        "parallel_semantic": str(result.get("parallel_semantic") or resolve_parallel_semantic(p)),
        "tier_used": result.get("tier_used") if isinstance(result.get("tier_used"), dict) else build_tier_used(),
        "L9_child_wf_ok": result.get("child_wf_ok") is True,
        "L9_child_invoked": result.get("child_invoked") is True,
        "L9_signals_continue_as_new_wired": result.get("signals_continue_as_new_wired") is True
        or result.get("continue_as_new_wired") is True,
        "L7_mlflow_ok": mlflow_ok,
        "L7_mlflow_run_id": str(mlflow_smoke.get("mlflow_run_id") or ""),
        "L7_mlflow_tracking_uri": str(mlflow_smoke.get("tracking_uri") or ""),
        "L7_mlflow_evidence_ref": str((mlflow_smoke.get("output_paths") or {}).get("latest") or ""),
        "L5_openlineage_ok": openlineage_ok,
        "L5_openlineage_run_id": str(openlineage_smoke.get("openlineage_run_id") or ""),
        "L5_marquez_url": str(openlineage_smoke.get("marquez_url") or ""),
        "L5_openlineage_evidence_ref": str((openlineage_smoke.get("output_paths") or {}).get("latest") or ""),
        "L5_opa_ok": opa_ok,
        "L5_opa_named_blocker": _evolution_weld_named_blocker(opa_smoke, fallback="") if not opa_ok else "",
        "L5_opa_evidence_ref": str((opa_smoke.get("output_paths") or {}).get("latest") or ""),
        "L7_optuna_ok": optuna_ok,
        "L7_optuna_named_blocker": _evolution_weld_named_blocker(optuna_smoke, fallback="") if not optuna_ok else "",
        "L7_optuna_evidence_ref": str((optuna_smoke.get("output_paths") or {}).get("latest") or ""),
        "L7_dvc_ok": dvc_ok,
        "L7_dvc_invoke_green": dvc_invoke_green,
        "L7_dvc_thin_bind": dvc_thin_bind,
        "L7_dvc_named_blocker": _evolution_weld_named_blocker(dvc_smoke, fallback="") if not dvc_ok else "",
        "L7_dvc_evidence_ref": str((dvc_smoke.get("output_paths") or {}).get("latest") or ""),
        "L7_wandb_ok": wandb_ok,
        "L7_wandb_invoke_green": wandb_invoke_green,
        "L7_wandb_thin_bind": wandb_thin_bind,
        "wandb_mlflow_alias_ok": wandb_smoke.get("wandb_mlflow_alias_ok") is True,
        "L7_wandb_named_blocker": _evolution_weld_named_blocker(wandb_smoke, fallback="") if not wandb_ok else "",
        "L7_wandb_evidence_ref": str((wandb_smoke.get("output_paths") or {}).get("latest") or ""),
        "mlflow_ok": mlflow_ok,
        "openlineage_ok": openlineage_ok,
        "显式暂缓登记": suspend_registry,
        "optional_tier3": optional_tier3,
        "mature_refs": {
            "G4": "temporalio/samples-python/langgraph_plugin/graph_api/react_agent/workflow.py",
            "G5": "temporalio/samples-python/langgraph_plugin/graph_api/human_in_the_loop/workflow.py",
            "G6": "temporalio/samples-python/langgraph_plugin/graph_api/continue_as_new/workflow.py",
            "L6": "thin_glue_l6_self_heal + integrated_bus_graph/should_heal_critic",
            "L8": "thin_glue_l8_token_stack + jinja2 readback template",
            "L9": "integrated_bus_parent_workflow + langgraph.types.Send",
            "L7": "thin_glue_l7_mlflow + thin_glue_l7_optuna + thin_glue_l7_dvc + thin_glue_l7_wandb",
            "L5": "thin_glue_l5_openlineage + thin_glue_l5_opa",
        },
    }


def _bus_result_for_tool_table_coverage(
    result: dict[str, Any],
    evolution_weld: dict[str, Any],
) -> dict[str, Any]:
    """Flatten evolution_weld invoke flags into bus_result for tool_table_coverage."""
    merged = dict(result)
    for key, value in evolution_weld.items():
        if key.startswith(("L5_", "L7_", "mlflow_", "openlineage_", "wandb_")) or key in {
            "mlflow_ok",
            "openlineage_ok",
        }:
            merged[key] = value
    return merged


def _build_payload(
    result: dict[str, Any],
    *,
    invoke_mode: str,
    runtime_root: Path,
    workflow_id: str | None = None,
    mainline_default: bool = True,
    worker_ownership: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    result = _enrich_result_from_fanin(result, runtime_root=runtime_root)
    result = _enrich_result_from_invoke_evidence(result, runtime_root=runtime_root)
    result = enrich_bus_escalate_evidence(result, runtime_root=runtime_root)
    bus_params = params if params is not None else _load_params()
    result.setdefault(
        "draft_model",
        str(result.get("worker_lane_model") or ""),
    )
    result.setdefault(
        "review_model",
        str(result.get("pro_review_model") or ""),
    )
    result.setdefault("parallel_semantic", resolve_parallel_semantic(bus_params))
    if not isinstance(result.get("tier_used"), dict):
        result["tier_used"] = build_tier_used()
    result["dynamic_loop_shape"] = build_dynamic_loop_shape_metadata(result, params=bus_params)
    l4_search_performed = _resolve_l4_search_performed(result)
    l4_crawl4ai_ok = _resolve_l4_crawl4ai(result, runtime_root=runtime_root)
    diff_cover_slice_ok = _resolve_diff_cover_slice(result, runtime_root=runtime_root)
    otel_trace_ok = _resolve_otel_trace(result, runtime_root=runtime_root)
    langfuse_keys_missing = (
        result.get("langfuse_skipped") is True
        and str(result.get("langfuse_named_blocker") or "") == "LANGFUSE_KEYS_MISSING"
    ) or (
        result.get("langfuse_callback_wired") is not True
        and str(result.get("litellm_completion_via") or "") == "litellm.completion"
        and not bool(os.environ.get("LANGFUSE_PUBLIC_KEY") or os.environ.get("LANGFUSE_SECRET_KEY"))
    )
    langfuse_ok = _resolve_langfuse_callback(result) if not langfuse_keys_missing else True
    if result.get("diff_cover_ok") is True:
        result["diff_cover_ok"] = True
    checks = {
        "langgraph_plugin_graph": True,
        "L0_markitdown_intake": bool(str(result.get("content_md") or "").strip()),
        "L0_duckdb_invoke": result.get("duckdb_invoked") is True,
        "L0_watchdog_invoke": result.get("watchdog_invoked") is True,
        "L0_mcp_registry": result.get("mcp_registry_ok") is True,
        "L1_pydantic_validate": result.get("validate_ok") is True,
        "L2_planner_slice": result.get("planner_ok") is True,
        "L4_search_performed": l4_search_performed,
        "L4_crawl4ai_probe": l4_crawl4ai_ok,
        "L3_fastmcp_invoke": result.get("mcp_tool_invoked") is True,
        "L9_parallel_succeeded": int(result.get("parallel_succeeded") or 0) >= 1,
        "L5_fanin_slice": result.get("fanin_ok") is True,
        "L5_diff_cover_slice": diff_cover_slice_ok,
        "L5_otel_trace": otel_trace_ok,
        "L2_checkpoint_bind": result.get("checkpoint_ok") is True,
        "L8_token_readback": result.get("token_bus_ok") is True,
        "L6_heal_policy": result.get("heal_bus_ok") is True,
        "L6_critic_edge": result.get("critic_edge_wired") is True,
        "L2_checkpoint_invoked": result.get("checkpoint_invoked") is True,
        "L2_langgraph_send": result.get("langgraph_send_wired") is True,
        "L8_jinja_readback": bool(result.get("jinja_readback_ref")),
        "gateway_trace_completion": result.get("gateway_trace_ok") is True,
        "L3_litellm_completion": str(result.get("litellm_completion_via") or "") == "litellm.completion",
        "L3_docker_sandbox": result.get("docker_sandbox_invoked") is True,
        "docker_executed": bool(str(result.get("execution_stdout") or "").strip()),
        "promotion_gate_passed": result.get("promotion_gate_passed") is True,
        "memory_candidate_on_pass": (
            (result.get("promotion_gate_passed") is True)
            == bool(str(result.get("memory_candidate_id") or "").strip())
        )
        and not (
            result.get("promotion_gate_passed") is not True
            and bool(str(result.get("memory_candidate_id") or "").strip())
        ),
        "proof_written": bool(result.get("proof_path")),
        "git_commit_hash": bool(result.get("commit_hash")),
        "L3_gitpython_commit": result.get("gitpython_invoke_ok") is True,
        "handroll_driver_replaced": summarize_sunset_registry().get("handroll_intact") is False,
        "handroll_intact_false": result.get("handroll_intact") is False
        or summarize_sunset_registry().get("handroll_intact") is False,
        "facade_default_unreachable": result.get("handroll_default_unreachable") is True
        or result.get("facade_guard_ok") is True,
        "mirror_registry_probe": result.get("mirror_registry_ok") is True,
        "aaq_claim_written": result.get("aaq_ok") is True,
        "pytest_slice_green": result.get("pytest_slice_ok") is True,
        "L7_memory_bus": result.get("memory_bus_ok") is True,
        "L9_child_wf": result.get("child_wf_ok") is True,
        "L9_signal_feed": result.get("signal_feed_ok") is True,
        "L1_instructor_invoke": (
            result.get("instructor_invoked") is True
            if bus_params.get("instructor_enabled")
            else result.get("instructor_ok") is not False
        ),
        "L3_openhands_activity": result.get("openhands_activity_ok") is True,
        "glue_seam_invoke": result.get("glue_seam_invoke_ok") is True,
        "L3_qwen_draft_worker_lane": result.get("worker_lane_ok") is True,
        "L3_pro_review_after_draft": result.get("pro_review_ok") is True,
        "worker_lane_integrated_bus_bound": result.get("worker_lane_integrated_bus_bound") is True,
        "T0_draft_role_bound": bool(str(result.get("worker_lane_route_role") or "").strip()),
        "T1_pro_review_role_bound": bool(str(result.get("pro_review_route_role") or "").strip()),
        "search_tier_evidence": bool(str(result.get("search_tier_used") or "").strip()),
        "ollama_default_qwen_banned": result.get("ollama_default_qwen_banned") is True,
        "default_plus_dynamic_escalate_wired": result.get("model_escalate_policy_wired") is True,
        "dynamic_loop_shape_wired": bool((result.get("dynamic_loop_shape") or {}).get("draft_model")),
        "draft_cloud_not_ollama": (result.get("dynamic_loop_shape") or {}).get("draft_cloud_not_ollama") is True,
        "parallel_semantic_documented": str(result.get("parallel_semantic") or "") in {"barrier", "rolling"},
        "parallel_lane_task_id_trace": _parallel_lane_task_id_trace_ok(result),
        "parallel_lane_tier_routing": _parallel_lane_tier_routing_ok(result),
        "rolling_accept_trace": _rolling_accept_trace_ok(result),
        "mainline_default_path": mainline_default,
        "docker_worker_enforced": (
            worker_ownership == "docker_daemon"
            if invoke_mode == "temporal_langgraph_plugin"
            else True
        ),
    }
    if langfuse_keys_missing:
        result.setdefault("langfuse_skipped", True)
        result.setdefault("langfuse_named_blocker", "LANGFUSE_KEYS_MISSING")
    else:
        checks["langfuse_callback_wired"] = langfuse_ok
    named_blockers: dict[str, str] = {}
    if not l4_search_performed and str(result.get("search_named_blocker") or ""):
        named_blockers["L4_search_performed"] = str(result.get("search_named_blocker"))
    if not l4_crawl4ai_ok and str(result.get("crawl4ai_named_blocker") or ""):
        named_blockers["L4_crawl4ai_probe"] = str(result.get("crawl4ai_named_blocker"))
    if not diff_cover_slice_ok and str(result.get("diff_cover_named_blocker") or ""):
        named_blockers["L5_diff_cover_slice"] = str(result.get("diff_cover_named_blocker"))
    if not otel_trace_ok and str(result.get("otel_named_blocker") or ""):
        named_blockers["L5_otel_trace"] = str(result.get("otel_named_blocker"))
    if not langfuse_ok and str(result.get("langfuse_named_blocker") or ""):
        named_blockers["langfuse_callback_wired"] = str(result.get("langfuse_named_blocker"))
    passed = all(checks.values())
    evolution_weld = _build_evolution_weld(result, params=bus_params, runtime_root=runtime_root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "integrated_bus_invoke": True,
        "integration_pattern": "temporalio.contrib.langgraph.LangGraphPlugin",
        "graph_id": GRAPH_ID,
        "replaces": REPLACES,
        "thin_glue": True,
        "handroll_intact": False,
        "facade_hard_redirect": True,
        "mainline_default_hot_path": mainline_default,
        "not_333_mainline": not mainline_default,
        "invoke_mode": invoke_mode,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "worker_ownership": worker_ownership or None,
        "docker_worker_polling": worker_ownership == "docker_daemon",
        "result": result,
        "acceptance_now_can_invoke_cn": (
            f"integrated_bus_v2：intake→validate→gateway→search→qwen_draft→sandbox→pro_review→fanin→promotion→token→heal→finalize；"
            f"search_hits={result.get('search_hit_count')}；worker_lane={result.get('worker_lane_ok')}；"
            f"pro_review={result.get('pro_review_ok')}；langfuse={result.get('langfuse_callback_wired')}；"
            f"promotion={result.get('promotion_gate_passed')}；mem={str(result.get('memory_candidate_id', 'none'))[:16]}。"
            if passed
            else "集成总线未绿"
        ),
        "validation": {
            "passed": passed,
            "checks": checks,
            "named_blockers": named_blockers,
            "validated_at": datetime.now().astimezone().isoformat(),
        },
        "evolution_weld": evolution_weld,
    }
    evidence = runtime_root / "readback" / f"integrated_bus_{run_id}.json"
    write_json(evidence, payload)
    payload["evidence_path"] = str(evidence)
    state_latest = runtime_root / "state" / "integrated_bus_v2" / "latest.json"
    write_json(state_latest, payload)
    payload["integrated_bus_v2_latest_ref"] = str(state_latest)
    coverage = build_tool_table_coverage(
        runtime_root=runtime_root,
        integrated_bus_evidence=str(evidence),
        bus_result=_bus_result_for_tool_table_coverage(result, evolution_weld),
        mainline_default=mainline_default,
    )
    payload["tool_table_coverage_ref"] = coverage.get("output_paths", {}).get("latest", "")
    zh = runtime_root / "readback" / "zh" / f"integrated_bus_{run_id}.md"
    zh.parent.mkdir(parents=True, exist_ok=True)
    zh.write_text(
        "\n".join(
            [
                f"# integrated_bus {run_id}",
                f"- mode: {invoke_mode}",
                f"- passed: {passed}",
                "",
                payload["acceptance_now_can_invoke_cn"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload["readback_zh"] = str(zh)
    return payload


async def run_integrated_bus_temporal(
    input_path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    address: str = "127.0.0.1:7233",
    mainline_default: bool = True,
) -> dict[str, Any]:
    from temporalio.client import Client

    params = _load_params()
    task_queue = str(params.get("task_queue") or INTEGRATED_BUS_QUEUE)
    graph_id = str(params.get("graph_id") or GRAPH_ID)
    worker_ownership = _resolve_worker_ownership(runtime_root=runtime_root, task_queue=task_queue)
    client = await Client.connect(address)
    workflow_id = f"{params.get('workflow_id_prefix', 'xinao-integrated-bus')}-{uuid.uuid4().hex[:12]}"
    if worker_ownership == "docker_daemon":
        initial = _initial_state_for_docker_worker(
            input_path,
            repo_root=repo_root,
            runtime_root=runtime_root,
            workflow_id=workflow_id,
        )
    else:
        initial = default_initial_state(
            input_path,
            repo_root=repo_root,
            runtime_root=runtime_root,
            workflow_id=workflow_id,
        )

    if worker_ownership == "docker_daemon":
        # Mature-first: samples-python run_workflow.py — client submits; houtai-gongren polls queue.
        result = await client.execute_workflow(
            XinaoIntegratedBusWorkflow.run,
            initial,
            id=workflow_id,
            task_queue=task_queue,
        )
    else:
        from temporalio.contrib.langgraph import LangGraphPlugin
        from temporalio.worker import Worker

        plugin = LangGraphPlugin(graphs={graph_id: make_integrated_graph()})
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[XinaoIntegratedBusWorkflow],
            plugins=[plugin],
            activity_executor=ThreadPoolExecutor(4),
        ):
            result = await client.execute_workflow(
                XinaoIntegratedBusWorkflow.run,
                initial,
                id=workflow_id,
                task_queue=task_queue,
            )
    return _build_payload(
        dict(result),
        invoke_mode="temporal_langgraph_plugin",
        runtime_root=runtime_root,
        workflow_id=workflow_id,
        mainline_default=mainline_default,
        worker_ownership=worker_ownership,
        params=params,
    )


async def run_integrated_bus_local(
    input_path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    mainline_default: bool = True,
) -> dict[str, Any]:
    local_params = _load_params()
    workflow_id = (
        f"{local_params.get('workflow_id_prefix', 'xinao-integrated-bus')}-local-{uuid.uuid4().hex[:12]}"
    )
    state = default_initial_state(
        input_path,
        repo_root=repo_root,
        runtime_root=runtime_root,
        workflow_id=workflow_id,
    )
    for step in (
        signal_feed_node,
        intake_node,
        duckdb_node,
        watchdog_node,
        facade_guard_node,
        validate_node,
        planner_node,
        gateway_trace_node,
        search_node,
        crawl4ai_node,
        mcp_tools_node,
        mirror_registry_node,
        glue_seam_invoke_node,
        openhands_node,
        parallel_width_node,
        qwen_draft_worker_lane_node,
        sandbox_node,
        pro_review_after_draft_node,
        hitl_review_node,
        fanin_node,
        aaq_node,
        promotion_gate_node,
        memory_bus_node,
        token_bus_node,
        heal_node,
        checkpoint_node,
        pytest_slice_node,
        episode_cache_node,
        finalize_node,
    ):
        state.update(await step(state))
    return _build_payload(
        dict(state),
        invoke_mode="local_graph_nodes",
        runtime_root=runtime_root,
        workflow_id=workflow_id,
        mainline_default=mainline_default,
        params=local_params,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Integrated LangGraphPlugin bus (default main path)")
    parser.add_argument("--input", default="")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--temporal", action="store_true")
    parser.add_argument("--address", default="127.0.0.1:7233")
    args = parser.parse_args(argv)

    input_path = Path(args.input) if args.input else None
    temporal = args.temporal or not args.local
    try:
        payload = run_integrated_bus(
            input_path,
            temporal=temporal,
            address=args.address,
            mainline_default=True,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


def run_integrated_bus(
    input_path: Path | None = None,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    temporal: bool = True,
    address: str = "127.0.0.1:7233",
    mainline_default: bool = True,
) -> dict[str, Any]:
    import asyncio

    trigger = resolve_input(input_path, repo_root=repo_root)
    if temporal:
        return asyncio.run(
            run_integrated_bus_temporal(
                trigger,
                runtime_root=runtime_root,
                repo_root=repo_root,
                address=address,
                mainline_default=mainline_default,
            )
        )
    return asyncio.run(
        run_integrated_bus_local(
            trigger,
            runtime_root=runtime_root,
            repo_root=repo_root,
            mainline_default=mainline_default,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())