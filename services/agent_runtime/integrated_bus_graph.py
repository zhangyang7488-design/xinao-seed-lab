"""Temporal LangGraphPlugin integrated bus — mature external seam (not hand-roll driver)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from langgraph.graph import START, StateGraph
from temporalio import workflow
from temporalio.contrib.langgraph import graph as temporal_graph
from typing_extensions import TypedDict

from services.agent_runtime.thin_bootstrap_runner import git_commit_all
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, l0_intake_markdown, l3_run_sandbox, now_iso

GRAPH_ID = "xinao-integrated-bus"
DEFAULT_PARAMS = DEFAULT_REPO / "materials" / "authority_glue" / "seams" / "integrated_bus_params.v1.json"


class BusState(TypedDict, total=False):
    input_path: str
    params_path: str
    repo_root: str
    runtime_root: str
    content_md: str
    adapter: str
    execution_stdout: str
    execution_backend: str
    proof_path: str
    commit_hash: str


def _params_path(state: BusState) -> Path:
    raw = state.get("params_path") or ""
    p = Path(raw) if raw else DEFAULT_PARAMS
    return p if p.is_file() else DEFAULT_PARAMS


def _repo_root(state: BusState) -> Path:
    if state.get("repo_root"):
        return Path(state["repo_root"])
    return DEFAULT_REPO


def _activity_options() -> dict[str, Any]:
    return {
        "execute_in": "activity",
        "start_to_close_timeout": timedelta(minutes=5),
    }


async def intake_node(state: BusState) -> dict[str, Any]:
    intake = l0_intake_markdown(Path(state["input_path"]), max_chars=2000)
    return {
        "content_md": str(intake.get("content_md") or ""),
        "adapter": str(intake.get("adapter") or ""),
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


async def finalize_node(state: BusState) -> dict[str, Any]:
    repo = _repo_root(state)
    proof_path = repo / "integrated_bus_proof.txt"
    proof_path.write_text(f"{now_iso()}\n{state.get('execution_stdout', '')}\n", encoding="utf-8")
    commit_info = git_commit_all(repo, "Integrated bus: LangGraphPlugin default main path")
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


def default_initial_state(
    input_path: Path,
    *,
    repo_root: Path = DEFAULT_REPO,
    runtime_root: Path | None = None,
    params_path: Path | None = None,
) -> BusState:
    return {
        "input_path": str(input_path),
        "params_path": str(params_path or DEFAULT_PARAMS),
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root or ""),
    }