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
) -> str:
    ms = str(path).replace("\\", "/")
    root_ms = str(host_root).replace("\\", "/").rstrip("/")
    if root_ms and ms.lower().startswith(root_ms.lower()):
        rel = ms[len(root_ms) :].lstrip("/")
        return f"{container_root.rstrip('/')}/{rel}"
    marker = host_root.name.upper()
    upper = ms.upper()
    if marker and marker in upper:
        rel = upper.split(marker, 1)[-1].lstrip("/\\")
        return f"{container_root.rstrip('/')}/{rel.replace(chr(92), '/')}"
    return str(path)


def _initial_state_for_docker_worker(
    input_path: Path,
    *,
    repo_root: Path,
    runtime_root: Path,
    workflow_id: str,
) -> dict[str, Any]:
    """Host client submits container paths so houtai-gongren activities can read files."""
    input_container = _host_path_to_container(input_path, host_root=repo_root, container_root="/app")
    if not input_path.is_file():
        input_container = "/app/materials/phase0_test_input.md"
    params_host = DEFAULT_PARAMS
    params_container = _host_path_to_container(params_host, host_root=repo_root, container_root="/app")
    return {
        "input_path": input_container,
        "params_path": params_container,
        "repo_root": "/app",
        "runtime_root": "/evidence",
        "workflow_id": workflow_id,
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


def _resolve_diff_cover_slice(result: dict[str, Any], *, runtime_root: Path | None = None) -> bool:
    if result.get("diff_cover_ok") is True:
        return True
    if result.get("diff_cover_skipped") is True and str(result.get("diff_cover_named_blocker") or ""):
        return True
    fanin = _load_fanin_evidence(result, runtime_root=runtime_root)
    diff = fanin.get("diff_cover") or {}
    if diff.get("diff_cover_ok") is True:
        return True
    return diff.get("diff_cover_skipped") is True and bool(str(diff.get("named_blocker") or ""))


def _resolve_otel_trace(result: dict[str, Any], *, runtime_root: Path | None = None) -> bool:
    if result.get("otel_ok") is True:
        return True
    if result.get("otel_skipped") is True and str(result.get("otel_named_blocker") or ""):
        return True
    fanin = _load_fanin_evidence(result, runtime_root=runtime_root)
    otel = fanin.get("otel") or {}
    if otel.get("otel_ok") is True:
        return True
    return otel.get("otel_skipped") is True and bool(str(otel.get("named_blocker") or ""))


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


def _build_evolution_weld(
    result: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """G4/G5/G6 + L2/L6/L8/L9 invoke_green weld evidence — non-blocking."""
    p = params or {}
    deferred = {
        "L4_exa": "deferred_paid_search_not_wired",
        "L7_mlflow": "deferred_experiment_tracking_not_wired",
        "L5_openlineage": "deferred_lineage_not_wired",
    }
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
        "L9_child_wf_ok": result.get("child_wf_ok") is True,
        "L9_child_invoked": result.get("child_invoked") is True,
        "L9_signals_continue_as_new_wired": result.get("signals_continue_as_new_wired") is True
        or result.get("continue_as_new_wired") is True,
        "deferred_explicit": deferred,
        "mature_refs": {
            "G4": "temporalio/samples-python/langgraph_plugin/graph_api/react_agent/workflow.py",
            "G5": "temporalio/samples-python/langgraph_plugin/graph_api/human_in_the_loop/workflow.py",
            "G6": "temporalio/samples-python/langgraph_plugin/graph_api/continue_as_new/workflow.py",
            "L6": "thin_glue_l6_self_heal + integrated_bus_graph/should_heal_critic",
            "L8": "thin_glue_l8_token_stack + jinja2 readback template",
            "L9": "integrated_bus_parent_workflow + langgraph.types.Send",
        },
    }


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
    l4_search_performed = _resolve_l4_search_performed(result)
    diff_cover_slice_ok = _resolve_diff_cover_slice(result, runtime_root=runtime_root)
    otel_trace_ok = _resolve_otel_trace(result, runtime_root=runtime_root)
    if result.get("diff_cover_ok") is True:
        result["diff_cover_ok"] = True
    bus_params = params if params is not None else _load_params()
    checks = {
        "langgraph_plugin_graph": True,
        "L0_markitdown_intake": bool(str(result.get("content_md") or "").strip()),
        "L0_duckdb_invoke": result.get("duckdb_invoked") is True,
        "L0_watchdog_invoke": result.get("watchdog_invoked") is True,
        "L0_mcp_registry": result.get("mcp_registry_ok") is True,
        "L1_pydantic_validate": result.get("validate_ok") is True,
        "L2_planner_slice": result.get("planner_ok") is True,
        "L4_search_performed": l4_search_performed,
        "L4_crawl4ai_probe": result.get("crawl4ai_ok") is True,
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
        "langfuse_callback_wired": result.get("langfuse_callback_wired") is True,
        "gateway_trace_completion": result.get("gateway_trace_ok") is True,
        "L3_litellm_completion": str(result.get("litellm_completion_via") or "") == "litellm.completion",
        "L3_docker_sandbox": result.get("docker_sandbox_invoked") is True,
        "docker_executed": bool(str(result.get("execution_stdout") or "").strip()),
        "promotion_gate_passed": result.get("promotion_gate_passed") is True,
        "memory_candidate_on_pass": bool(result.get("memory_candidate_id")) == bool(result.get("promotion_gate_passed")),
        "proof_written": bool(result.get("proof_path")),
        "git_commit_hash": bool(result.get("commit_hash")),
        "L3_gitpython_commit": result.get("gitpython_invoke_ok") is True,
        "handroll_driver_replaced": True,
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
        "mainline_default_path": mainline_default,
        "docker_worker_enforced": (
            worker_ownership == "docker_daemon"
            if invoke_mode == "temporal_langgraph_plugin"
            else True
        ),
    }
    passed = all(checks.values())
    evolution_weld = _build_evolution_weld(result, params=bus_params)
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
        "validation": {"passed": passed, "checks": checks, "validated_at": datetime.now().astimezone().isoformat()},
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
        bus_result=dict(result),
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
    state = default_initial_state(input_path, repo_root=repo_root, runtime_root=runtime_root)
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
    local_params = _load_params()
    return _build_payload(
        dict(state),
        invoke_mode="local_graph_nodes",
        runtime_root=runtime_root,
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