"""CLI entry for integrated LangGraphPlugin bus invoke."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.worker import Worker

from integrated_bus_graph import (
    GRAPH_ID,
    PARAMS_PATH,
    BusState,
    XinaoIntegratedBusWorkflow,
    finalize_node,
    intake_node,
    make_integrated_graph,
    sandbox_node,
)
from phase0_external_seam_invoke import _load_params, _now_iso, _resolve_input, _write_json

SCHEMA_VERSION = "xinao.integrated_langgraph_plugin_invoke.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_LANGGRAPH_PLUGIN_INVOKE_READY"


def _build_evidence(
    params: dict[str, Any],
    result: BusState,
    *,
    invoke_mode: str,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    runtime_root = Path(params["runtime_root"])
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    checks = {
        "langgraph_plugin_graph": True,
        "L0_markitdown_intake": bool(str(result.get("content_md") or "").strip()),
        "docker_executed": bool(str(result.get("execution_stdout") or "").strip()),
        "proof_written": bool(result.get("proof_path")),
        "git_commit_hash": bool(result.get("commit_hash")),
    }
    passed = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "not_333_mainline": True,
        "integrated_bus_invoke": True,
        "integration_pattern": "temporalio.contrib.langgraph.LangGraphPlugin",
        "graph_id": GRAPH_ID,
        "external_seam_refs": params.get("external_seam_refs"),
        "params_path": str(PARAMS_PATH),
        "invoke_mode": invoke_mode,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "result": dict(result),
        "acceptance_now_can_invoke_cn": (
            f"集成总线：LangGraphPlugin 图 intake→sandbox→finalize 真跑；"
            f"markitdown={result.get('adapter')}；docker={result.get('execution_backend')}；"
            f"commit {str(result.get('commit_hash', ''))[:12]}；证据 D 盘 readback。"
            if passed
            else "集成总线未绿：检查 LangGraphPlugin/markitdown/docker/git"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": _now_iso()},
    }
    evidence_path = runtime_root / "readback" / f"integrated_bus_{run_id}.json"
    payload["evidence_path"] = str(evidence_path)
    _write_json(evidence_path, payload)
    zh_path = runtime_root / "readback" / "zh" / f"integrated_bus_{run_id}.md"
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.write_text(
        "\n".join(
            [
                f"# Integrated bus LangGraphPlugin {run_id}",
                f"- mode: `{invoke_mode}`",
                f"- graph: `{GRAPH_ID}`",
                f"- intake: `{result.get('adapter')}`",
                f"- sandbox: `{result.get('execution_backend')}`",
                f"- commit: `{str(result.get('commit_hash', ''))[:12]}`",
                f"- passed: {passed}",
                "",
                payload["acceptance_now_can_invoke_cn"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload["readback_zh"] = str(zh_path)
    return payload


async def run_temporal_invoke(params: dict[str, Any], input_path: Path) -> dict[str, Any]:
    target = str(params.get("temporal_target", "127.0.0.1:7233"))
    task_queue = str(params["task_queue"])
    graph_id = str(params.get("graph_id", GRAPH_ID))
    client = await Client.connect(target)
    plugin = LangGraphPlugin(graphs={graph_id: make_integrated_graph()})
    initial: BusState = {
        "input_path": str(input_path),
        "params_path": str(PARAMS_PATH),
    }
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
    return _build_evidence(params, result, invoke_mode="temporal_langgraph_plugin", workflow_id=workflow_id)


async def run_local_graph_invoke(params: dict[str, Any], input_path: Path) -> dict[str, Any]:
    state: BusState = {
        "input_path": str(input_path),
        "params_path": str(PARAMS_PATH),
    }
    state.update(await intake_node(state))
    state.update(await sandbox_node(state))
    state.update(await finalize_node(state))
    return _build_evidence(params, state, invoke_mode="local_graph_nodes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Integrated LangGraphPlugin bus invoke (not_333_mainline)")
    parser.add_argument("--params", default=str(PARAMS_PATH))
    parser.add_argument("--input", default="")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--temporal", action="store_true")
    args = parser.parse_args(argv)

    params = _load_params(Path(args.params))
    input_path = Path(args.input) if args.input else _resolve_input(params)
    use_temporal = args.temporal or not args.local

    try:
        if use_temporal:
            payload = asyncio.run(run_temporal_invoke(params, input_path))
        else:
            payload = asyncio.run(run_local_graph_invoke(params, input_path))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "mode": "failed"}, ensure_ascii=False), file=sys.stderr)
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())