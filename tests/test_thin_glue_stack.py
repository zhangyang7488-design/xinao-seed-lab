from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.thin_glue
def test_thin_glue_intake_scans_materials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_INTAKE", "1")
    from services.agent_runtime.thin_glue_intake import build_thin_glue_intake

    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "sample.md").write_text("# hello thin glue\n", encoding="utf-8")

    payload = build_thin_glue_intake(
        runtime_root=tmp_path / "runtime",
        repo_root=tmp_path,
        materials_dir=materials,
        write=True,
    )
    assert payload["validation"]["passed"] is True
    assert payload["source_entry_count"] >= 1
    assert payload["thin_glue"] is True
    assert payload["replaces"] == "current_task_source_intake"


@pytest.mark.thin_glue
def test_thin_glue_provider_scheduler_writes_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_PROVIDER", "1")
    from services.agent_runtime import codex_native_provider_scheduler_phase4 as phase4

    payload = phase4.run_provider_scheduler(
        runtime_root=tmp_path / "runtime",
        repo_root=REPO_ROOT,
        invoke_codex_exec=False,
        invoke_qwen=False,
        write=True,
    )
    assert payload["thin_glue"] is True
    assert payload["replaces"] == "codex_native_provider_scheduler_phase4"
    latest = tmp_path / "runtime" / "state" / "thin_glue_provider" / "latest.json"
    assert latest.is_file()
    saved = json.loads(latest.read_text(encoding="utf-8"))
    assert saved["task_id"] == "thin_glue_provider_scheduler"


@pytest.mark.thin_glue
def test_thin_glue_l9_ledger_reads_passed_readback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_LEDGER", "1")
    from services.agent_runtime.thin_glue_l9_ledger import run_thin_glue_ledger_mirror

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_20260708_test.json").write_text(
        '{"run_id": "20260708_test", "validation": {"passed": true}, "timestamp": "2026-07-08"}',
        encoding="utf-8",
    )
    payload = run_thin_glue_ledger_mirror(runtime_root=runtime, repo_root=REPO_ROOT, write=True)
    assert payload["thin_glue"] is True
    assert payload["succeeded_count"] >= 1
    assert payload["validation"]["passed"] is True
    assert (runtime / "state" / "thin_glue_ledger" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_thin_glue_loop_glue_and_closure_together(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_INTAKE", "1")
    monkeypatch.setenv("XINAO_THIN_GLUE_PROVIDER", "1")
    monkeypatch.setenv("XINAO_THIN_GLUE_LEDGER", "1")
    from services.agent_runtime.thin_glue_loop import run_thin_glue_loop

    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    (materials / "thin_bootstrap_input.md").write_text("# loop smoke\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# loop smoke marker\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

    payload = run_thin_glue_loop(
        materials / "thin_bootstrap_input.md",
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        prefer_docker=False,
        write=True,
    )
    assert payload["glue_and_closure_together"] is True
    assert payload["layers"]["L0_intake_pool"]["source_entry_count"] >= 1
    l4 = payload["layers"]["L4_search"]
    assert l4["thin_glue"] is True
    assert l4["local_hit_count"] >= 1
    assert payload["layers"]["L9_provider_gateway"]["thin_glue"] is True
    assert payload["layers"]["L8_commit"]["created_new"] is True
    assert payload["validation"]["checks"]["L4_local_rg_search"] is True
    assert list((tmp_path / "runtime" / "readback" / "zh").glob("thin_glue_loop_*.md"))


def test_default_plus_dynamic_escalate_policy_helpers() -> None:
    from services.agent_runtime.default_plus_dynamic_escalate import (
        is_banned_default_qwen_model,
        resolve_draft_role_binding,
        resolve_pro_review_role_binding,
        sanitize_default_draft_model,
        should_escalate_search,
    )

    assert is_banned_default_qwen_model("qwen-local") is True
    assert is_banned_default_qwen_model("ollama/qwen3:8b") is True
    assert sanitize_default_draft_model("qwen-local") == "qwen3.6-flash"
    assert sanitize_default_draft_model("qwen3.6-flash") == "qwen3.6-flash"

    draft = resolve_draft_role_binding()
    review = resolve_pro_review_role_binding()
    assert draft["tier"] == "T0_DEFAULT"
    assert draft["route_role"] == "default_draft_worker_first"
    assert draft["adapter"] == "cloud_qwen_via_litellm"
    assert review["tier"] == "T1_SECONDARY"
    assert review["route_role"] == "pro_review_after_draft"

    assert should_escalate_search(
        "x",
        searx_result={"ok": False},
        ddgs_hits=0,
        context={"difficulty": "hard"},
    ) is False
    assert should_escalate_search(
        "x",
        searx_result={"ok": False},
        ddgs_hits=0,
        context={"heal_repair_required": True},
    ) is False


@pytest.mark.thin_glue
def test_thin_glue_l4_search_local_rg(tmp_path) -> None:
    from services.agent_runtime.thin_glue_l4_search import run_thin_glue_search

    repo = tmp_path / "repo"
    (repo / "services").mkdir(parents=True)
    (repo / "services" / "needle.txt").write_text("thin_glue_l4_search marker\n", encoding="utf-8")

    payload = run_thin_glue_search(
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        run_id="test_l4",
        local_query="thin_glue_l4",
        external_query="searxng",
        write=True,
    )
    assert payload["validation"]["passed"] is True
    assert payload["local_hit_count"] >= 1
    latest = tmp_path / "runtime" / "state" / "thin_glue_search" / "latest.json"
    assert latest.is_file()


@pytest.mark.thin_glue
def test_thin_glue_worker_pool_parallel_lanes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_WORKER_POOL", "1")
    from services.agent_runtime.thin_glue_l9_worker_pool import run_thin_glue_worker_pool_wave

    repo = tmp_path / "repo"
    (repo / "services").mkdir(parents=True)
    (repo / "services" / "thin_glue_worker_pool_marker.txt").write_text(
        "thin_glue_worker_pool lane draft\n",
        encoding="utf-8",
    )
    payload = run_thin_glue_worker_pool_wave(
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        wave_id="test-pool-wave",
        target_width=3,
        use_temporal=False,
        write=True,
    )
    assert payload["thin_glue"] is True
    assert payload["validation"]["passed"] is True
    assert payload["succeeded_count"] >= 1
    assert payload["draft_count"] >= 1
    assert (tmp_path / "runtime" / "state" / "thin_glue_worker_pool" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_modular_worker_pool_delegates_to_thin_glue(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_WORKER_POOL", "1")
    from services.agent_runtime import modular_dynamic_worker_pool_phase1 as pool

    repo = tmp_path / "repo"
    (repo / "services").mkdir(parents=True)
    (repo / "services" / "thin_glue_worker_pool_marker.txt").write_text(
        "thin_glue_worker_pool delegated\n",
        encoding="utf-8",
    )
    payload = pool.run_wave(
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        wave_id="delegation-test",
        target_width=2,
        write=True,
    )
    assert payload.get("hand_rolled_run_wave_bypassed") is True
    assert payload.get("validation", {}).get("passed") is True


@pytest.mark.thin_glue
def test_thin_glue_l8_token_stack_compresses_readback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_TOKEN_STACK", "1")
    from services.agent_runtime.thin_glue_l8_token_stack import run_thin_glue_token_stack

    runtime = tmp_path / "runtime"
    zh = runtime / "readback" / "zh"
    zh.mkdir(parents=True)
    long_body = "# title\n\n" + "\n".join([f"- bullet {i} repeated" for i in range(40)])
    (zh / "sample_readback.md").write_text(long_body, encoding="utf-8")
    payload = run_thin_glue_token_stack(runtime_root=runtime, write=True)
    assert payload["validation"]["passed"] is True
    assert payload["average_compression_ratio"] > 0
    assert (runtime / "readback" / "zh" / "compressed" / "sample_readback.md").is_file()


@pytest.mark.thin_glue
def test_l8_write_zh_readback_writes_compressed_sibling(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_TOKEN_STACK", "1")
    from services.agent_runtime.thin_glue_stack import l8_write_zh_readback

    runtime = tmp_path / "runtime"
    l8_write_zh_readback(runtime, run_id="loop_test", title="t", lines=["- a", "- a", "- b"])
    assert (runtime / "readback" / "zh" / "compressed" / "loop_test.md").is_file()


@pytest.mark.thin_glue
def test_thin_glue_l1_task_package_structured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_TASK_PACKAGE", "1")
    from services.agent_runtime.thin_glue_l1_task_package import resolve_thin_glue_task_package

    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    (materials / "thin_bootstrap_input.md").write_text(
        "# task\n用户意图：薄胶 L1 结构化任务包\n",
        encoding="utf-8",
    )
    payload = resolve_thin_glue_task_package(
        materials,
        repo_root=repo,
        runtime_root=tmp_path / "runtime",
        write=True,
    )
    assert payload["thin_glue"] is True
    assert payload["validation"]["passed"] is True
    assert payload["structured_task_package"]["task_id"].startswith("thin-glue-task-")
    assert (tmp_path / "runtime" / "state" / "thin_glue_task_package" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_task_package_resolver_delegates_to_l1(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_TASK_PACKAGE", "1")
    from services.agent_runtime import task_package_resolver as resolver

    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    (materials / "thin_bootstrap_input.md").write_text("# x\n薄胶委托测试\n", encoding="utf-8")
    payload = resolver.resolve_task_package(
        materials,
        runtime_root=tmp_path / "runtime",
        entry_path=materials / "thin_bootstrap_input.md",
    )
    assert payload.get("delegated_from") == "task_package_resolver.resolve_task_package"
    assert payload.get("validation", {}).get("passed") is True


@pytest.mark.thin_glue
def test_thin_glue_l2_root_intent_reads_evidence_chain(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_ROOT_INTENT", "1")
    monkeypatch.setenv("XINAO_THIN_GLUE_LEDGER", "1")
    from services.agent_runtime.thin_glue_l2_root_intent import run_thin_glue_root_intent_tick

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_20260708_test.json").write_text(
        '{"validation": {"passed": true}, "run_id": "test"}',
        encoding="utf-8",
    )
    payload = run_thin_glue_root_intent_tick(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="l2-test",
        write=True,
    )
    assert payload["thin_glue"] is True
    assert payload["validation"]["passed"] is True
    assert (runtime / "state" / "thin_glue_root_intent" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_root_driver_build_delegates_to_thin_l2(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_ROOT_INTENT", "1")
    monkeypatch.setenv("XINAO_THIN_GLUE_LEDGER", "1")
    from services.agent_runtime.root_intent_loop_driver import build

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_green.json").write_text(
        '{"validation": {"passed": true}}',
        encoding="utf-8",
    )
    payload = build(runtime_root=runtime, repo_root=REPO_ROOT, write=True)
    assert payload.get("hand_rolled_build_bypassed") is True
    assert payload.get("validation", {}).get("passed") is True


@pytest.mark.thin_glue
def test_phase0_minimal_weld_local(tmp_path, monkeypatch) -> None:
    from services.agent_runtime.phase0_minimal_weld_activity import run_phase0_minimal_weld

    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    input_md = materials / "phase0_test_input.md"
    input_md.write_text("# phase0\nphase0_minimal_weld smoke\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)

    payload = run_phase0_minimal_weld(
        input_md,
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        prefer_e2b=False,
        prefer_docker=False,
        write=True,
    )
    assert payload["validation"]["passed"] is True
    assert payload.get("commit_hash")
    readback = tmp_path / "runtime" / "readback"
    assert list(readback.glob("phase0_*.json")) or list(readback.glob("integrated_bus_*.json"))


@pytest.mark.thin_glue
def test_thin_glue_status_rollup(tmp_path) -> None:
    from services.agent_runtime.thin_glue_status import build_thin_glue_status

    runtime = tmp_path / "runtime"
    for rel, body in (
        ("state/thin_glue_intake/latest.json", '{"validation":{"passed":true},"thin_glue":true,"status":"ready"}'),
        ("state/thin_glue_task_package/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_root_intent/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_search/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_provider/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_ledger/latest.json", '{"validation":{"passed":true},"thin_glue":true,"status":"thin_glue_ledger_poll_ready"}'),
        ("state/thin_glue_worker_pool/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_token_stack/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_l3_execute/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_l5_verify/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_self_heal/latest.json", '{"validation":{"passed":true},"thin_glue":true}'),
        ("state/thin_glue_mainline_bridge/latest.json", '{"latest_thin_glue_loop_passed":true}'),
        ("readback/thin_glue_loop_test.json", '{"validation":{"passed":true},"thin_glue_loop":true}'),
    ):
        path = runtime / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    payload = build_thin_glue_status(runtime_root=runtime, write=True)
    assert payload["validation"]["passed"] is True
    assert payload["summary"]["green"] >= 9
    assert (runtime / "state" / "thin_glue_status" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_thin_glue_l6_self_heal_green_when_loop_green(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_SELF_HEAL", "1")
    from services.agent_runtime.thin_glue_l6_self_heal import run_thin_glue_self_heal

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_green.json").write_text(
        '{"validation": {"passed": true}}',
        encoding="utf-8",
    )
    payload = run_thin_glue_self_heal(runtime_root=runtime, write=True)
    assert payload["validation"]["passed"] is True
    assert payload["critic"]["decision"] == "all_pass_final_allowed"
    assert (runtime / "state" / "thin_glue_self_heal" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_pre_pass_audit_loop_delegates_to_l6(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_SELF_HEAL", "1")
    from services.agent_runtime import pre_pass_audit_loop

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_green.json").write_text(
        '{"validation": {"passed": true}}',
        encoding="utf-8",
    )
    payload = pre_pass_audit_loop.build(runtime_root=runtime, write=True)
    assert payload.get("delegated_from") == "pre_pass_audit_loop.build"
    assert payload.get("validation", {}).get("passed") is True


@pytest.mark.thin_glue
def test_thin_glue_l5_verify_layer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_VERIFY", "1")
    from services.agent_runtime.thin_glue_l5_verify import run_thin_glue_l5_verify_layer

    repo = REPO_ROOT
    payload = run_thin_glue_l5_verify_layer(
        runtime_root=tmp_path / "runtime",
        repo_root=repo,
        test_paths=["tests/test_thin_glue_work_proof.py"],
        write=True,
    )
    assert payload["thin_glue"] is True
    assert payload["validation"]["passed"] is True
    assert (tmp_path / "runtime" / "state" / "thin_glue_l5_verify" / "latest.json").is_file()


@pytest.mark.thin_glue
def test_cheap_worker_patch_executor_verify_ps1_bypass(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_VERIFY", "1")
    from services.agent_runtime.cheap_worker_patch_executor import verifier_argv

    argv, blocker = verifier_argv("scripts\\verify_thin_glue_stack.ps1", REPO_ROOT)
    assert not blocker
    assert "pytest" in " ".join(argv)


@pytest.mark.thin_glue
def test_facade_hard_redirect_blocks_handroll_on_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_INTEGRATED_BUS_DEFAULT", "1")
    monkeypatch.delenv("XINAO_FACADE_ALLOW_HANDROLL", raising=False)
    from services.agent_runtime import current_task_source_intake as intake

    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    materials = repo / "materials"
    materials.mkdir(parents=True)
    (materials / "probe.md").write_text("# facade redirect\n", encoding="utf-8")
    payload = intake.build_current_task_source_intake(runtime_root=runtime, repo_root=repo, write=True)
    assert payload.get("facade_hard_redirect") is True
    assert payload.get("handroll_blocked") is True
    assert payload.get("delegated_from") == "current_task_source_intake.build_current_task_source_intake"


@pytest.mark.thin_glue
def test_integrated_bus_local_replaces_phase0_handroll(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_INTEGRATED_BUS_DEFAULT", "1")
    from services.agent_runtime.integrated_bus_runner import run_integrated_bus

    input_path = REPO_ROOT / "materials" / "phase0_test_input.md"
    assert input_path.is_file()
    payload = run_integrated_bus(
        input_path,
        runtime_root=tmp_path / "runtime",
        repo_root=REPO_ROOT,
        temporal=False,
        mainline_default=True,
    )
    assert payload["validation"]["passed"] is True
    assert payload["integration_pattern"] == "temporalio.contrib.langgraph.LangGraphPlugin"
    assert payload["validation"]["checks"]["handroll_driver_replaced"] is True
    assert payload["validation"]["checks"]["L1_pydantic_validate"] is True
    assert payload["graph_id"] == "xinao-integrated-bus-v2"


@pytest.mark.thin_glue
def test_worker_lane_shape_fields_cloud_qwen_not_ollama(tmp_path, monkeypatch) -> None:
    """Worker lane smoke — draft_model cloud qwen + tier_used; no ollama default."""
    from services.agent_runtime import codex_s_worker_lane_carrier as carrier
    from services.agent_runtime.routing_policy_reader import (
        TIER_CHEAP_DRAFT,
        TIER_STRONG_REVIEW,
        is_cloud_draft_model,
    )

    def _fake_chat(messages, *, model, base_url, timeout_s=60.0):
        del messages, base_url, timeout_s
        return {
            "ok": True,
            "base_url": "http://test-gateway/v1",
            "response": {
                "choices": [{"message": {"content": "- [ ] smoke draft bullet"}}],
                "usage": {"total_tokens": 12},
            },
        }

    monkeypatch.setattr(carrier, "probe_gateway", lambda **_: {"ok": True})
    monkeypatch.setattr(carrier, "resolve_gateway_base_url", lambda *_, **__: "http://test-gateway/v1")
    monkeypatch.setattr(carrier, "chat_completion", _fake_chat)

    runtime = tmp_path / "runtime"
    payload = carrier.run_worker_lane_bus_activity(
        runtime_root=runtime,
        workflow_id="shape-smoke",
        mode="draft",
        objective="dynamic loop shape smoke",
        input_text="# smoke\nphase0_minimal_weld",
        provider="qwen",
        write=True,
        integrated_bus_bound=True,
        gateway_base_url="http://test-gateway/v1",
    )
    assert payload.get("worker_lane_ok") is True
    assert payload.get("draft_model") == "qwen3.6-flash"
    assert is_cloud_draft_model(payload.get("draft_model"))
    assert payload.get("tier_used", {}).get("draft") == TIER_CHEAP_DRAFT
    assert "ollama" not in str(payload.get("draft_model")).lower()


@pytest.mark.thin_glue
def test_dynamic_loop_shape_metadata_contract() -> None:
    from services.agent_runtime.routing_policy_reader import (
        build_dynamic_loop_shape_metadata,
        resolve_parallel_semantic,
    )

    result = {
        "draft_model": "qwen3.6-flash",
        "review_model": "deepseek-v4-pro",
        "parallel_semantic": "barrier",
        "parallel_succeeded": 2,
        "parallel_lane_models": [
            {"lane_id": 0, "model": "local_rg_search", "tier_used": "tier_local_search"},
            {"lane_id": 1, "model": "local_rg_search", "tier_used": "tier_local_search"},
        ],
        "tier_used": {"draft": "tier_cheap_draft", "review": "tier_strong_review"},
    }
    shape = build_dynamic_loop_shape_metadata(result, params={"parallel_semantic": "barrier"})
    assert shape["draft_model"] == "qwen3.6-flash"
    assert shape["review_model"] == "deepseek-v4-pro"
    assert shape["parallel_semantic"] == "barrier"
    assert shape["parallel_succeeded"] == 2
    assert len(shape["parallel_lane_models"]) == 2
    assert shape["draft_cloud_not_ollama"] is True
    assert shape["tier_used"]["review"] == "tier_strong_review"
    assert resolve_parallel_semantic({}) == "barrier"


@pytest.mark.thin_glue
def test_integrated_bus_promotion_slice_contract() -> None:
    """PromotionGate slice: default-hot-path contract without full hermetic bus invoke."""
    from services.agent_runtime.integrated_bus_graph import GRAPH_ID
    from services.agent_runtime.integrated_bus_runner import SENTINEL
    from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

    assert GRAPH_ID == "xinao-integrated-bus-v2"
    assert SENTINEL == "SENTINEL:XINAO_INTEGRATED_BUS_RUNNER_READY"
    assert summarize_sunset_registry().get("handroll_intact") is False


def test_thin_glue_status_reads_sunset_handroll(tmp_path, monkeypatch) -> None:
    from services.agent_runtime.thin_glue_status import build_thin_glue_status

    payload = build_thin_glue_status(runtime_root=tmp_path / "runtime", write=False)
    assert payload["handroll_intact"] is False
    assert payload["validation"]["checks"]["handroll_intact"] is False


def test_thin_glue_mainline_bridge_reads_latest_loop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XINAO_THIN_GLUE_MAINLINE_SPAWN", "auto")
    from services.agent_runtime.thin_glue_mainline_bridge import attach_thin_glue_bridge_evidence

    runtime = tmp_path / "runtime"
    readback = runtime / "readback"
    readback.mkdir(parents=True)
    (readback / "thin_glue_loop_20260708_test.json").write_text(
        '{"validation": {"passed": true}}',
        encoding="utf-8",
    )
    bridge = attach_thin_glue_bridge_evidence(runtime)
    assert bridge["latest_thin_glue_loop_passed"] is True
    assert bridge["thin_glue_mainline_seam"]["enabled"] is True
    assert (runtime / "state" / "thin_glue_mainline_bridge" / "latest.json").is_file()