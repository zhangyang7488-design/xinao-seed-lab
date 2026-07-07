"""Minimal LangGraph-style plan for closure_test — plan → execute → verify."""

from __future__ import annotations

from typing import Any, TypedDict


class ClosureState(TypedDict, total=False):
    run_id: str
    task_package: dict[str, Any]
    plan: list[str]
    execute_result: dict[str, Any]
    verify_result: dict[str, Any]
    status: str


def plan_closure_tasks(task_package: dict[str, Any]) -> list[str]:
    content = str(task_package.get("content_md") or "")
    tasks = ["execute_proof_patch", "verify_pytest"]
    if "closure_test_proof" in content or "closure_ok" in content:
        return tasks
    return tasks


def run_closure_graph(state: ClosureState) -> ClosureState:
    """Thin plan node — no LangGraph dependency required for v1 smoke."""
    package = state.get("task_package") or {}
    plan = plan_closure_tasks(package)
    return {
        **state,
        "plan": plan,
        "status": "planned",
    }