import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_s_live_backend_watch.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "codex_s_live_backend_watch.v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_s_live_backend_watch", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_static_context(runtime: Path) -> None:
    _write_json(
        runtime / "state" / "current_route" / "latest.json",
        {
            "schema_version": "xinao.research_runtime.current_route.v1",
            "status": "active",
            "work_id": "xinao_seed_cortex_phase0_20260701",
        },
    )
    _write_json(
        runtime
        / "state"
        / "worker_assignment"
        / "xinao_seed_cortex_phase0_20260701.json",
        {
            "schema_version": "xinao.seed_cortex.worker_assignment.v1",
            "status": "active",
            "work_id": "xinao_seed_cortex_phase0_20260701",
            "assignment_dag": {"next_ready_node_id": "frontier_recompute_required"},
        },
    )
    _write_json(
        runtime / "state" / "temporal_dev_server" / "latest.json",
        {
            "schema_version": "xinao.temporal.dev_server.v1",
            "status": "active",
            "temporal_dev_server_process_running": True,
        },
    )


def test_static_route_assignment_and_temporal_process_do_not_trigger_poll(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_static_context(runtime)

    payload = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=True)

    assert payload["schema_version"] == "xinao.codex_s.live_backend_watch.v1"
    assert payload["foreground_poll_required"] is False
    assert payload["decision_categories"] == []
    assert payload["static_context_triggers_poll"] is False
    assert payload["context_sources"]["current_route"]["status"] == "active"
    assert payload["context_sources"]["static_worker_assignment"]["status"] == "active"
    assert (
        payload["context_sources"]["temporal_dev_server"]["temporal_dev_server_process_running"]
        is True
    )
    assert payload["old_backend_mirror_semantics_reused"] is True
    assert payload["old_backend_endpoint_used"] is False
    assert payload["compat_endpoint_used"] is False
    assert payload["not_source_of_truth"] is True
    assert payload["not_user_completion"] is True
    assert payload["not_completion_decision"] is True
    assert payload["not_execution_controller"] is True
    assert payload["validation"]["passed"] is True


def test_non_terminal_categories_trigger_foreground_poll(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _seed_static_context(runtime)
    _write_json(
        runtime / "state" / "parallel_dispatch_plan" / "latest.json",
        {
            "schema_version": "xinao.codex_s.parallel_dispatch_plan.v1",
            "worker_running": True,
            "temporal_pending_activity": True,
            "worker_jsonl_evidence_present": True,
            "next_ready": True,
            "auto_continue_expected": True,
            "active_lane_count": 2,
        },
    )

    payload = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=False)

    assert payload["foreground_poll_required"] is True
    for category in (
        "worker_running",
        "temporal_pending_activity",
        "worker_jsonl_non_terminal",
        "assignment_next_ready",
        "assignment_auto_continue_expected",
        "queue_or_lane_non_terminal",
    ):
        assert category in payload["decision_categories"]
        assert category in payload["old_semantic_categories"]["continue_required_categories"]


def test_output_growth_detected_triggers_without_live_marker(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    watched = runtime / "state" / "parallel_lane_results" / "latest.json"
    _write_json(watched, {"schema_version": "fixture.v1", "status": "completed"})

    first = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=True)
    assert first["foreground_poll_required"] is False

    _write_json(
        watched,
        {
            "schema_version": "fixture.v1",
            "status": "completed",
            "new_output": "this makes the file longer",
        },
    )
    second = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=True)

    assert second["foreground_poll_required"] is True
    assert second["decision_categories"] == ["output_growth_detected"]
    assert second["output_growth_file_count"] == 1
    assert second["output_growth_paths"][0].endswith("parallel_lane_results/latest.json")


def test_explicit_user_stop_override_does_not_poll_even_when_live(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"
    _write_json(
        runtime / "state" / "parallel_capacity" / "latest.json",
        {
            "schema_version": "fixture.v1",
            "worker_running": True,
            "pending_count": 1,
        },
    )

    payload = module.build(
        runtime_root=runtime,
        repo_root=tmp_path / "repo",
        explicit_user_stop=True,
        write=False,
    )

    assert payload["foreground_poll_required"] is False
    assert payload["explicit_user_stop_override"] is True
    assert "explicit_user_stop_override" in payload["decision_categories"]
    assert "worker_running" in payload["decision_categories"]
    assert "queue_or_lane_non_terminal" in payload["decision_categories"]


def test_writes_runtime_latest_and_chinese_readback(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.build(runtime_root=runtime, repo_root=tmp_path / "repo", write=True)
    latest = runtime / "state" / "codex_s_live_backend_watch" / "latest.json"
    readback = runtime / "readback" / "zh" / "codex_s_live_backend_watch_20260702.md"

    assert latest.is_file()
    assert readback.is_file()
    assert json.loads(latest.read_text(encoding="utf-8"))["sentinel"] == (
        "SENTINEL:XINAO_CODEX_S_LIVE_BACKEND_WATCH_READY"
    )
    text = readback.read_text(encoding="utf-8")
    assert "前台应继续轮询" in text or "不能单独触发轮询" in text
    assert "不是事实源" in text
    assert payload["adoption_state"] == "verifier_ready_but_not_hooked"


def test_schema_contract_names_required_fields_and_boundaries() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.live_backend_watch.v1"
    )
    for expected in (
        "foreground_poll_required",
        "old_backend_mirror_semantics_reused",
        "old_backend_endpoint_used",
        "compat_endpoint_used",
        "decision_categories",
        "old_semantic_categories",
        "not_source_of_truth",
        "not_user_completion",
        "not_completion_decision",
        "not_execution_controller",
        "sentinel",
    ):
        assert expected in schema["required"]
    categories = set(
        schema["properties"]["old_semantic_categories"]["properties"][
            "continue_required_categories"
        ]["items"]["$ref"].split("/")
    )
    assert "LiveCategory" in categories
    live_enum = set(schema["$defs"]["LiveCategory"]["enum"])
    assert {
        "worker_running",
        "temporal_pending_activity",
        "worker_jsonl_non_terminal",
        "assignment_next_ready",
        "assignment_auto_continue_expected",
        "queue_or_lane_non_terminal",
        "output_growth_detected",
    }.issubset(live_enum)
