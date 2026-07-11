from __future__ import annotations

import inspect
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_integrated_bus_promotion_slice_contract() -> None:
    from services.agent_runtime.integrated_bus_graph import GRAPH_ID
    from services.agent_runtime.integrated_bus_runner import SENTINEL
    from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

    assert GRAPH_ID == "xinao-integrated-bus-v2"
    assert SENTINEL == "SENTINEL:XINAO_INTEGRATED_BUS_RUNNER_READY"
    assert summarize_sunset_registry().get("handroll_intact") is False


def test_integrated_bus_default_route_is_readonly_at_finalize() -> None:
    from services.agent_runtime.integrated_bus_graph import finalize_node

    params = json.loads(
        (REPO_ROOT / "materials/authority_glue/seams/integrated_bus_params.v1.json").read_text(
            encoding="utf-8"
        )
    )
    source = inspect.getsource(finalize_node)
    assert params["task_queue"] == "xinao-integrated-langgraph-plugin-queue"
    assert params["git_finalize_mode"] == "gitpython_readonly_snapshot"
    assert "git_commit_all" not in source
    assert 'runtime / "state" / "integrated_bus_proof"' in source


def test_parallel_lane_routing_accepts_explicit_same_tier() -> None:
    from services.agent_runtime.integrated_bus_runner import _parallel_lane_tier_routing_ok

    result = {
        "parallel_lane_models": [
            {
                "lane_id": 0,
                "task_id": "wf-lane-0",
                "model": "qwen3.6-flash",
                "tier_used": "tier_cheap_draft",
            },
            {
                "lane_id": 1,
                "task_id": "wf-lane-1",
                "model": "qwen3.6-flash",
                "tier_used": "tier_cheap_draft",
            },
        ]
    }
    assert _parallel_lane_tier_routing_ok(result) is True


def test_integrated_bus_worker_registry_contains_real_temporal_langgraph_route() -> None:
    from services.agent_runtime.integrated_bus_workflow_registry import registry_summary

    registry = registry_summary()
    assert "xinao-integrated-langgraph-plugin-queue" in registry["langgraph_plugin_queues"]
    assert "XinaoIntegratedBusWorkflow" in registry["workflows_registered"]
    assert "xinao-integrated-bus-v2" in registry["graph_ids"]


def test_diff_cover_uses_retained_hot_path_test() -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_diff_cover_slice

    default = inspect.signature(run_diff_cover_slice).parameters["pytest_node"].default
    assert default == (
        "tests/test_integrated_bus_hot_path.py::"
        "test_integrated_bus_default_route_is_readonly_at_finalize"
    )
