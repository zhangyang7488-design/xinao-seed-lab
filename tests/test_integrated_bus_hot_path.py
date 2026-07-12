from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_integrated_bus_promotion_slice_contract() -> None:
    from services.agent_runtime.integrated_bus_graph import GRAPH_ID
    from services.agent_runtime.integrated_bus_runner import SENTINEL
    from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

    assert GRAPH_ID == "xinao-integrated-bus-v2"
    assert SENTINEL == "SENTINEL:XINAO_INTEGRATED_BUS_RUNNER_READY"
    assert summarize_sunset_registry().get("handroll_intact") is False


def test_integrated_bus_workflow_sandbox_prepares_with_selective_passthrough() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import XinaoIntegratedBusWorkflow
    from services.agent_runtime.integrated_bus_runner import integrated_bus_workflow_runner
    from temporalio import workflow

    async def prepare() -> object:
        runner = integrated_bus_workflow_runner()
        definition = workflow._Definition.must_from_class(XinaoIntegratedBusWorkflow)
        runner.prepare_workflow(definition)
        return runner

    runner = asyncio.run(prepare())
    assert runner.restrictions.passthrough_all_modules is False
    assert {
        "langgraph",
        "langchain_core",
        "portalocker",
        "rich",
        "services.agent_runtime.integrated_bus_bus_nodes",
    }.issubset(runner.restrictions.passthrough_modules)


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
    expected_queues = {
        "xinao-integrated-langgraph-plugin-queue",
        "xinao-integrated-bus-parent-queue",
        "xinao-integrated-bus-child-queue",
    }
    assert set(registry["task_queues"]) == expected_queues
    assert registry["langgraph_plugin_queues"] == ["xinao-integrated-langgraph-plugin-queue"]
    assert registry["workflows_registered"] == [
        "XinaoIntegratedBusWorkflow",
        "XinaoIntegratedBusParentWorkflow",
        "XinaoIntegratedBusChildWorkflow",
    ]
    assert registry["activity_count"] == 2
    assert not any("ThinGlue" in name for name in registry["workflows_registered"])
    assert not any(queue.startswith("xinao-thin-glue-") for queue in registry["task_queues"])
    assert "xinao-integrated-bus-v2" in registry["graph_ids"]


def test_promoted_grok_fanin_bypasses_legacy_qwen_worker(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        _grok_fanin_worker_lane,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
        "Grok worker result\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "ok": True,
                "sentinel": GROK_FANIN_SENTINEL,
                "provider_id": GROK_FANIN_PROVIDER,
                "model": "grok-4.5",
                "models": ["grok-4.5"],
                "workflow_id": "parent-wf",
                "succeeded": 2,
                "failed": 0,
                "ready_width": 2,
                "lanes": [
                    {
                        "lane_id": "research",
                        "mode": "research",
                        "model": "grok-4.5",
                        "operation_id": "op-research",
                        "operation_state": "completed",
                    },
                    {
                        "lane_id": "audit",
                        "mode": "audit",
                        "model": "grok-4.5",
                        "operation_id": "op-audit",
                        "operation_state": "completed",
                    },
                ],
                "intake_sha256": hashlib.sha256(intake.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "parent-wf-langgraph-s0",
            "input_path": str(intake),
            "content_md": content,
        }
    )
    assert lane is not None
    assert lane["worker_lane_ok"] is True
    assert lane["worker_lane_provider"] == GROK_FANIN_PROVIDER
    assert lane["worker_lane_adapter"] == "temporal_acpx_fanin"


def test_promoted_grok_fanin_rejects_partial_or_model_drift(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        _grok_fanin_worker_lane,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
    )
    intake.write_text(content, encoding="utf-8")
    base = {
        "ok": True,
        "sentinel": GROK_FANIN_SENTINEL,
        "provider_id": GROK_FANIN_PROVIDER,
        "model": "grok-4.5",
        "models": ["grok-4.5"],
        "workflow_id": "parent-wf",
        "succeeded": 2,
        "failed": 0,
        "ready_width": 2,
        "intake_sha256": hashlib.sha256(intake.read_bytes()).hexdigest(),
        "lanes": [
            {
                "lane_id": "one",
                "model": "grok-4.5",
                "operation_id": "op-one",
                "operation_state": "completed",
            },
            {
                "lane_id": "two",
                "model": "grok-4.5",
                "operation_id": "op-two",
                "operation_state": "completed",
            },
        ],
    }
    cases = [
        {**base, "model": "grok-composer-2.5-fast"},
        {**base, "succeeded": 1, "failed": 1},
    ]
    for payload in cases:
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        lane = _grok_fanin_worker_lane(
            {
                "runtime_root": str(runtime),
                "repo_root": str(REPO_ROOT),
                "workflow_id": "parent-wf-langgraph-s0",
                "input_path": str(intake),
                "content_md": content,
            }
        )
        assert lane is not None
        assert lane["worker_lane_ok"] is False
        assert lane["worker_lane_named_blocker"] == "GROK_FANIN_FULL_FRONTIER_OR_MODEL_INVALID"


def test_route_parallel_send_never_creates_child_side_model_fanout() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import route_parallel_send

    route = asyncio.run(
        route_parallel_send(
            {
                "content_md": "plain intake",
                "parallel_width_n": 2,
                "repo_root": str(REPO_ROOT),
                "runtime_root": str(REPO_ROOT),
                "workflow_id": "parent-wf",
            }
        )
    )
    assert route == "grok_worker_fanin"


def test_route_parallel_send_skips_send_for_grok_fanin_marker() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_SENTINEL,
        route_parallel_send,
    )

    route = asyncio.run(
        route_parallel_send(
            {
                "content_md": f"<!-- {GROK_FANIN_SENTINEL} -->\n",
                "parallel_width_n": 2,
            }
        )
    )
    assert route == "grok_worker_fanin"


def test_hot_graph_registers_no_legacy_model_worker_nodes() -> None:
    from services.agent_runtime.integrated_bus_graph import BusState, make_integrated_graph

    graph = make_integrated_graph()
    node_names = set(graph.nodes)
    assert "grok_worker_fanin" in node_names
    assert not any(
        marker in node_name.lower()
        for node_name in node_names
        for marker in ("qwen", "deepseek", "ollama", "codex_subagent", "admin_worker")
    )
    assert {
        "grok_only_mode",
        "grok_fanin_ok",
        "grok_fanin_manifest_ref",
        "grok_fanin_lane_count",
        "non_grok_model_invocations",
        "fallback_model_invocation_performed",
        "memory_model_bind_frozen",
    }.issubset(BusState.__annotations__)


def test_grok_only_model_nodes_fail_closed_without_valid_fanin() -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        gateway_trace_node,
        grok_worker_fanin_node,
        pro_review_after_draft_node,
        validate_node,
    )

    state = {
        "content_md": "plain intake without a Grok fan-in manifest",
        "input_path": "missing.md",
        "workflow_id": "wf-no-grok",
        "repo_root": str(REPO_ROOT),
        "runtime_root": str(REPO_ROOT),
    }
    payloads = asyncio.run(
        _run_nodes(
            state,
            validate_node,
            gateway_trace_node,
            grok_worker_fanin_node,
            pro_review_after_draft_node,
        )
    )
    assert payloads[0]["validate_ok"] is False
    assert payloads[1]["gateway_trace_ok"] is False
    assert payloads[2]["worker_lane_ok"] is False
    assert payloads[3]["pro_review_ok"] is False
    assert all(payload["non_grok_model_invocations"] == 0 for payload in payloads)
    assert all(payload.get("fallback_model_invocation_performed") is False for payload in payloads)


async def _run_nodes(
    state: dict[str, object],
    *nodes: Callable[[dict[str, object]], Awaitable[dict[str, object]]],
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for node in nodes:
        payloads.append(await node(state))
    return payloads


def test_params_freeze_every_non_grok_model_worker() -> None:
    params = json.loads(
        (
            REPO_ROOT / "materials" / "authority_glue" / "seams" / "integrated_bus_params.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert params["model_worker_policy"] == "grok_only_fail_closed"
    assert params["allowed_model_worker_providers"] == ["grok_acpx_headless"]
    assert set(params["frozen_model_worker_providers"]) == {
        "admin",
        "codex_subagent",
        "qwen",
        "deepseek",
        "ollama",
    }
    assert params["gateway_model_invocation_enabled"] is False
    assert params["mem0_bind_enabled"] is False
    assert params["instructor_enabled"] is False


def test_parallel_width_plan_never_sets_langgraph_send_from_width(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_parallel_width_bus

    runtime = tmp_path / "runtime"
    parallel = run_parallel_width_bus(
        params={"parallel_width_default": 2},
        runtime_root=runtime,
        workflow_id="wf-plan-only",
        repo_root=REPO_ROOT,
        content_md="plan-only intake",
        plan_only=True,
    )
    assert parallel["parallel_width_n"] == 2
    assert parallel["langgraph_send_wired"] is False
    assert parallel["adapter"] == "langgraph_send_plan"
    assert parallel["parallel_lane_models"] == []


def test_parallel_fanin_sets_langgraph_send_only_from_lane_results(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_parallel_fanin_bus

    runtime = tmp_path / "runtime"
    lane = {
        "lane_id": 0,
        "task_id": "wf-lane-0",
        "search_ok": True,
        "lane_ok": True,
        "model": "local_rg_search",
        "lane_role": "parallel_search_slice",
        "tier_used": "tier_local_search",
    }
    single = run_parallel_fanin_bus(
        lane_results=[lane],
        params={"parallel_width_default": 2},
        runtime_root=runtime,
        workflow_id="wf-fanin-single",
    )
    assert single["langgraph_send_wired"] is False

    multi = run_parallel_fanin_bus(
        lane_results=[{**lane, "lane_id": 0}, {**lane, "lane_id": 1, "task_id": "wf-lane-1"}],
        params={"parallel_width_default": 2},
        runtime_root=runtime,
        workflow_id="wf-fanin-multi",
    )
    assert multi["langgraph_send_wired"] is True
    assert len(multi["parallel_lane_models"]) == 2


def test_promoted_grok_fanin_uses_parent_dynamic_width(tmp_path: Path) -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_SENTINEL,
        parallel_width_node,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    intake = fanin / "input.md"
    manifest = fanin / "manifest.json"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "ok": True,
                "sentinel": GROK_FANIN_SENTINEL,
                "provider_id": "grok_acpx_headless",
                "workflow_id": "parent-wf",
                "succeeded": 3,
                "intake_sha256": hashlib.sha256(intake.read_bytes()).hexdigest(),
                "lanes": [
                    {
                        "lane_id": "research",
                        "mode": "research",
                        "model": "grok-4.5",
                        "operation_id": "op-research",
                        "operation_state": "completed",
                    },
                    {
                        "lane_id": "audit",
                        "mode": "audit",
                        "model": "grok-4.5",
                        "operation_id": "op-audit",
                        "operation_state": "completed",
                    },
                    {
                        "lane_id": "draft",
                        "mode": "draft",
                        "model": "grok-4.5",
                        "operation_id": "op-draft",
                        "operation_state": "completed",
                    },
                ],
                "model": "grok-4.5",
                "models": ["grok-4.5"],
                "failed": 0,
                "ready_width": 3,
            }
        ),
        encoding="utf-8",
    )
    payload = asyncio.run(
        parallel_width_node(
            {
                "content_md": content,
                "input_path": str(intake),
                "workflow_id": "parent-wf-langgraph-s0",
                "repo_root": str(REPO_ROOT),
                "runtime_root": str(runtime),
            }
        )
    )
    assert payload["grok_fanin_parallel_bypass"] is True
    assert payload["langgraph_send_wired"] is False
    assert payload["parallel_width_n"] == 3
    assert payload["parallel_succeeded"] == 3


def test_promoted_grok_fanin_is_the_only_model_worker(tmp_path: Path) -> None:
    import asyncio

    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        grok_worker_fanin_node,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
        "Grok worker result\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "ok": True,
                "sentinel": GROK_FANIN_SENTINEL,
                "provider_id": GROK_FANIN_PROVIDER,
                "model": "grok-4.5",
                "models": ["grok-4.5"],
                "workflow_id": "parent-wf",
                "succeeded": 1,
                "failed": 0,
                "ready_width": 1,
                "lanes": [
                    {
                        "lane_id": "only",
                        "mode": "audit",
                        "model": "grok-4.5",
                        "operation_id": "op-only",
                        "operation_state": "completed",
                    }
                ],
                "intake_sha256": hashlib.sha256(intake.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    lane = asyncio.run(
        grok_worker_fanin_node(
            {
                "runtime_root": str(runtime),
                "repo_root": str(REPO_ROOT),
                "workflow_id": "parent-wf-langgraph-s0",
                "input_path": str(intake),
                "content_md": content,
            }
        )
    )
    assert lane["worker_lane_provider"] == GROK_FANIN_PROVIDER
    assert lane["worker_lane_adapter"] == "temporal_acpx_fanin"
    assert lane["non_grok_model_invocations"] == 0


def test_promoted_grok_fanin_marker_fails_closed_on_hash_drift(tmp_path: Path) -> None:
    from services.agent_runtime.integrated_bus_graph import (
        GROK_FANIN_PROVIDER,
        GROK_FANIN_SENTINEL,
        _grok_fanin_worker_lane,
    )

    runtime = tmp_path / "runtime"
    fanin = runtime / "state" / "grok" / "fanin"
    fanin.mkdir(parents=True)
    manifest = fanin / "manifest.json"
    intake = fanin / "input.md"
    content = (
        f"<!-- {GROK_FANIN_SENTINEL} -->\n"
        "<!-- grok_manifest_path=/evidence/state/grok/fanin/manifest.json -->\n"
    )
    intake.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "ok": True,
                "sentinel": GROK_FANIN_SENTINEL,
                "provider_id": GROK_FANIN_PROVIDER,
                "workflow_id": "parent-wf",
                "succeeded": 1,
                "intake_sha256": "stale",
            }
        ),
        encoding="utf-8",
    )
    lane = _grok_fanin_worker_lane(
        {
            "runtime_root": str(runtime),
            "repo_root": str(REPO_ROOT),
            "workflow_id": "parent-wf-langgraph-s0",
            "input_path": str(intake),
            "content_md": content,
        }
    )
    assert lane is not None
    assert lane["worker_lane_ok"] is False
    assert lane["worker_lane_named_blocker"] == "GROK_FANIN_INPUT_HASH_MISMATCH"


def test_diff_cover_uses_retained_hot_path_test() -> None:
    from services.agent_runtime.integrated_bus_bus_nodes import run_diff_cover_slice

    default = inspect.signature(run_diff_cover_slice).parameters["pytest_node"].default
    assert default == (
        "tests/test_integrated_bus_hot_path.py::"
        "test_integrated_bus_default_route_is_readonly_at_finalize"
    )


def test_fanin_evidence_paths_are_unique_lineage_bound_and_atomic(
    tmp_path: Path, monkeypatch
) -> None:
    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(
        nodes,
        "_temporal_evidence_lineage",
        lambda workflow_id: (workflow_id, "019f-run/id"),
    )
    monkeypatch.setattr(
        nodes,
        "run_diff_cover_slice",
        lambda **_kwargs: {"diff_cover_ok": True, "diff_cover_skipped": False},
    )
    monkeypatch.setattr(nodes, "run_otel_trace_slice", lambda **_kwargs: {"otel_ok": True})

    first = nodes.run_fanin_bus(
        {}, runtime_root=runtime, workflow_id="wf/fanin", repo_root=REPO_ROOT
    )
    second = nodes.run_fanin_bus(
        {}, runtime_root=runtime, workflow_id="wf/fanin", repo_root=REPO_ROOT
    )

    first_path = Path(first["fanin_evidence_ref"])
    second_path = Path(second["fanin_evidence_ref"])
    assert first_path != second_path
    assert "wf_fanin" in first_path.name
    assert "019f-run_id" in first_path.name
    assert len(first_path.stem.rsplit("_", 1)[-1]) == 32
    assert json.loads(first_path.read_text(encoding="utf-8"))["temporal_run_id"] == ("019f-run/id")
    assert json.loads(second_path.read_text(encoding="utf-8"))["workflow_id"] == "wf/fanin"
    assert not list(runtime.rglob("*.tmp"))

    lane = {"lane_id": 0, "task_id": "lane-0", "search_ok": True, "lane_ok": True}
    parallel_first = nodes.run_parallel_fanin_bus(
        lane_results=[lane],
        params={"parallel_width_default": 1},
        runtime_root=runtime,
        workflow_id="wf/parallel",
    )
    parallel_second = nodes.run_parallel_fanin_bus(
        lane_results=[lane],
        params={"parallel_width_default": 1},
        runtime_root=runtime,
        workflow_id="wf/parallel",
    )
    assert parallel_first["parallel_evidence_ref"] != parallel_second["parallel_evidence_ref"]
    assert "wf_parallel" in Path(parallel_first["parallel_evidence_ref"]).name
    assert not list(runtime.rglob("*.tmp"))


def test_parallel_fanin_concurrent_writes_do_not_collide(tmp_path: Path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from services.agent_runtime import integrated_bus_bus_nodes as nodes

    runtime = tmp_path / "runtime"
    monkeypatch.setattr(
        nodes,
        "_temporal_evidence_lineage",
        lambda workflow_id: (workflow_id, "run-concurrent"),
    )
    lane = {"lane_id": 0, "task_id": "lane-0", "search_ok": True, "lane_ok": True}

    def write_one(index: int) -> str:
        result = nodes.run_parallel_fanin_bus(
            lane_results=[{**lane, "task_id": f"lane-{index}"}],
            params={"parallel_width_default": 1},
            runtime_root=runtime,
            workflow_id="wf-concurrent",
        )
        return str(result["parallel_evidence_ref"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(write_one, range(16)))

    assert len(paths) == len(set(paths)) == 16
    assert all(json.loads(Path(path).read_text(encoding="utf-8")) for path in paths)
    latest = runtime / "state" / "integrated_bus_parallel" / "latest.json"
    assert json.loads(latest.read_text(encoding="utf-8"))["evidence_id"] in {
        json.loads(Path(path).read_text(encoding="utf-8"))["evidence_id"] for path in paths
    }
    assert not list(runtime.rglob("*.tmp"))
