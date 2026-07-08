"""LangGraphPlugin graph + workflow (importable module for Temporal worker)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from langgraph.graph import START, StateGraph
from temporalio import workflow
from temporalio.contrib.langgraph import graph as temporal_graph
from typing_extensions import TypedDict

from phase0_external_seam_invoke import (
    _load_params,
    _now_iso,
    docker_python_exec,
    git_commit_all,
    markitdown_convert,
)

PARAMS_PATH = Path(__file__).with_name("integrated_bus_params.v1.json")
GRAPH_ID = "xinao-integrated-bus"


class BusState(TypedDict, total=False):
    input_path: str
    params_path: str
    content_md: str
    adapter: str
    execution_stdout: str
    execution_backend: str
    proof_path: str
    commit_hash: str


def _activity_options() -> dict[str, Any]:
    return {
        "execute_in": "activity",
        "start_to_close_timeout": timedelta(minutes=5),
    }


async def intake_node(state: BusState) -> dict[str, Any]:
    params = _load_params(Path(state["params_path"]))
    intake = markitdown_convert(Path(state["input_path"]), max_chars=int(params.get("max_md_chars", 2000)))
    return {
        "content_md": str(intake.get("content_md") or ""),
        "adapter": str(intake.get("adapter") or ""),
    }


async def sandbox_node(state: BusState) -> dict[str, Any]:
    params = _load_params(Path(state["params_path"]))
    image = str(params.get("docker_image", "python:3.12-slim"))
    preview = str(state.get("content_md") or "")[:300].replace('"', "'").replace("\n", " ")
    code = (
        "from datetime import datetime\n"
        f'print("IntegratedBus-LangGraphPlugin", datetime.now().isoformat())\n'
        f'print("{preview}...")\n'
    )
    execution = docker_python_exec(code, image=image)
    return {
        "execution_stdout": execution.get("stdout") or execution.get("stderr") or "",
        "execution_backend": execution.get("backend") or f"docker:{image}",
    }


async def finalize_node(state: BusState) -> dict[str, Any]:
    params = _load_params(Path(state["params_path"]))
    repo_root = Path(params["repo_root"])
    proof_name = str(params.get("proof_filename", "integrated_bus_proof.txt"))
    proof_path = repo_root / proof_name
    proof_path.write_text(
        f"{_now_iso()}\n{state.get('execution_stdout', '')}\n",
        encoding="utf-8",
    )
    commit_info = git_commit_all(repo_root, "Integrated bus: LangGraphPlugin external seam invoke")
    return {
        "proof_path": str(proof_path),
        "commit_hash": str(commit_info.get("commit_hash") or ""),
    }


def make_integrated_graph() -> StateGraph:
    g: StateGraph = StateGraph(BusState)
    g.add_node("intake", intake_node, metadata=_activity_options())
    g.add_node("sandbox", sandbox_node, metadata=_activity_options())
    g.add_node("finalize", finalize_node, metadata=_activity_options())
    g.add_edge(START, "intake")
    g.add_edge("intake", "sandbox")
    g.add_edge("sandbox", "finalize")
    return g


@workflow.defn(name="XinaoIntegratedBusWorkflow")
class XinaoIntegratedBusWorkflow:
    @workflow.run
    async def run(self, initial: BusState) -> BusState:
        return await temporal_graph(GRAPH_ID).compile().ainvoke(initial)