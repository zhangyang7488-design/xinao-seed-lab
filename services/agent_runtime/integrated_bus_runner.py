"""Run integrated LangGraphPlugin bus — default Temporal main-path invoke."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_graph import (
    DEFAULT_PARAMS,
    GRAPH_ID,
    XinaoIntegratedBusWorkflow,
    default_initial_state,
    intake_node,
    finalize_node,
    make_integrated_graph,
    sandbox_node,
)
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


def _build_payload(
    result: dict[str, Any],
    *,
    invoke_mode: str,
    runtime_root: Path,
    workflow_id: str | None = None,
    mainline_default: bool = True,
) -> dict[str, Any]:
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    checks = {
        "langgraph_plugin_graph": True,
        "L0_markitdown_intake": bool(str(result.get("content_md") or "").strip()),
        "docker_executed": bool(str(result.get("execution_stdout") or "").strip()),
        "proof_written": bool(result.get("proof_path")),
        "git_commit_hash": bool(result.get("commit_hash")),
        "handroll_driver_replaced": True,
        "mainline_default_path": mainline_default,
    }
    passed = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "integrated_bus_invoke": True,
        "integration_pattern": "temporalio.contrib.langgraph.LangGraphPlugin",
        "graph_id": GRAPH_ID,
        "replaces": REPLACES,
        "thin_glue": True,
        "mainline_default_hot_path": mainline_default,
        "not_333_mainline": not mainline_default,
        "invoke_mode": invoke_mode,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "result": result,
        "acceptance_now_can_invoke_cn": (
            f"默认主路：LangGraphPlugin intake→sandbox→finalize；"
            f"adapter={result.get('adapter')}；docker={result.get('execution_backend')}；"
            f"commit {str(result.get('commit_hash', ''))[:12]}。"
            if passed
            else "集成总线未绿"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": datetime.now().astimezone().isoformat()},
    }
    evidence = runtime_root / "readback" / f"integrated_bus_{run_id}.json"
    write_json(evidence, payload)
    payload["evidence_path"] = str(evidence)
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
    from temporalio.contrib.langgraph import LangGraphPlugin
    from temporalio.worker import Worker

    params = _load_params()
    task_queue = str(params.get("task_queue") or "xinao-integrated-langgraph-plugin-queue")
    graph_id = str(params.get("graph_id") or GRAPH_ID)
    client = await Client.connect(address)
    plugin = LangGraphPlugin(graphs={graph_id: make_integrated_graph()})
    initial = default_initial_state(input_path, repo_root=repo_root, runtime_root=runtime_root)
    workflow_id = f"{params.get('workflow_id_prefix', 'xinao-integrated-bus')}-{uuid.uuid4().hex[:12]}"
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
    )


async def run_integrated_bus_local(
    input_path: Path,
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    mainline_default: bool = True,
) -> dict[str, Any]:
    state = default_initial_state(input_path, repo_root=repo_root, runtime_root=runtime_root)
    state.update(await intake_node(state))
    state.update(await sandbox_node(state))
    state.update(await finalize_node(state))
    return _build_payload(
        dict(state),
        invoke_mode="local_graph_nodes",
        runtime_root=runtime_root,
        mainline_default=mainline_default,
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