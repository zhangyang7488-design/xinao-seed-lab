import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "modular_dynamic_worker_pool_phase1.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "codex_s_modular_dynamic_worker_pool_phase1.v1.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "modular_dynamic_worker_pool_phase1", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_dp_invoker(**kwargs: Any) -> dict[str, Any]:
    runtime = Path(kwargs["runtime_root"])
    mode = str(kwargs["mode"])
    invocation_id = str(kwargs["invocation_id"])
    result_path = runtime / "fake_dp_results" / f"{invocation_id}.{mode}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "draft_ready" if mode == "draft" else "model_ready",
                "mode": mode,
                "invocation_id": invocation_id,
                "completion_claim_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    provider_payload = {
        "mode_invocation_status": "draft_ready" if mode == "draft" else "model_ready",
        "selected_carrier_provider_id": (
            "seed_cortex.local_draft_artifact_provider"
            if mode == "draft"
            else "seed_cortex.local_eval_artifact_provider"
        ),
        "provider_invocation_performed": True,
        "model_invocation_performed": mode != "draft",
        "tool_invocation_performed": mode == "draft",
        "result_path": str(result_path),
        "raw_response_ref": str(result_path),
        "provider_invocation_ref": str(
            runtime / "fake_dp_results" / f"{invocation_id}.provider.json"
        ),
        "evidence_refs": {
            "latest": str(runtime / "fake_dp_results" / "latest.json"),
            "result_path": str(result_path),
        },
        "named_blocker": "",
    }
    return {
        "provider_payload": provider_payload,
        "actual_dispatch_refs": {
            "result_path": str(result_path),
            "provider_invocation_ref": provider_payload["provider_invocation_ref"],
            "provider_latest_ref": provider_payload["evidence_refs"]["latest"],
        },
    }


def test_schema_locks_phase1_draft_main_boundary() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == (
        "xinao.codex_s.modular_dynamic_worker_pool_phase1.v1"
    )
    assert schema["properties"]["task_id"]["const"] == (
        "modular_dynamic_worker_pool_phase1_20260704"
    )
    assert schema["properties"]["mode_counts"]["properties"]["search"]["const"] == 0
    assert schema["properties"]["mode_counts"]["properties"]["provider_probe"]["const"] == 0
    assert schema["properties"]["trigger_binding"]["properties"]["hot_path"]["const"] == (
        "parallel_draft->merge->writer"
    )
    assert "must_do_10" in schema["required"]
    assert "wave_steps_8" in schema["required"]
    assert "spend_entry_count" in schema["required"]


def test_run_wave_stages_drafts_merges_and_records_spend(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.run_wave(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        wave_id="phase1-focused-test-wave",
        target_width=8,
        write=True,
        dp_invoker=_fake_dp_invoker,
        record_meta_rsi=False,
        require_external_draft=False,
    )

    assert payload["validation"]["passed"] is True, (
        [key for key, value in payload["validation"]["checks"].items() if not value],
        payload.get("artifact_acceptance_queue"),
    )
    assert payload["target_width"] == 8
    assert payload["actual_dispatched_width"] == 8
    assert payload["mode_counts"]["draft"] == 5
    assert payload["mode_counts"]["search"] == 0
    assert payload["mode_counts"]["provider_probe"] == 0
    assert payload["draft_count"] == 5
    assert payload["staged_count"] == 5
    assert payload["merged_count"] == 1
    assert payload["spend_entry_count"] == 8
    assert payload["eval_count"] == 1
    assert payload["audit_count"] == 1
    assert payload["provider_tier_usage"]
    assert payload["token_cost_spend"]["total_tokens"] > 0
    assert payload["token_cost_spend"]["metered_usage_entry_count"] == 8
    assert payload["token_cost_spend"]["estimated_usage_entry_count"] == 0
    assert payload["metered"] is True
    assert payload["source_entry"]["source_entry_root"].endswith("新系统")
    assert payload["source_entry"]["sampled_count"] > 0
    assert payload["user_latest_correction_digest"]["task_id"] == (
        "foreground_brain_dp_worker_pool_correction_20260704"
    )
    assert payload["foreground_brain_decision"]["owner"] == "foreground_codex_brain"
    assert payload["foreground_brain_decision"]["required_fields_present"] is True
    assert payload["foreground_brain_decision"]["333_alignment"][
        "333_is_owner_semantic_line"
    ] is True
    assert payload["foreground_brain_decision"]["worker_briefs_generated"][
        "draft_brief_count"
    ] > 0
    assert payload["foreground_brain_decision"]["draft_artifacts_consumed"]
    assert payload["foreground_brain_decision"]["merge_decision"]["adopted_draft_count"] > 0
    assert payload["foreground_brain_decision"]["next_wave_decision"]["should_continue"] is True
    assert payload["validation"]["checks"]["foreground_brain_decision_has_required_fields"] is True
    assert payload["validation"]["checks"]["source_entry_dynamic_read"] is True
    assert payload["trigger_binding"]["status"] == "parallel_draft_to_merge_hot_path_bound"
    assert payload["watchdog_downgrade"]["status"] == "watchdog_downgraded_for_phase1_fast_path"
    assert payload["can_invoke_now"]["search_is_main_task"] is False
    assert payload["can_invoke_now"]["provider_probe_used_as_progress"] is False
    assert Path(payload["merge_artifact"]).is_file()
    merge_text = Path(payload["merge_artifact"]).read_text(encoding="utf-8")
    assert "这波推进了什么" in merge_text
    assert "采用的草稿" in merge_text
    assert "否决或暂缓的草稿" in merge_text
    assert "当前还差什么" in merge_text
    assert "下一波怎么派" in merge_text

    latest = runtime / "state" / "modular_dynamic_worker_pool_phase1" / "latest.json"
    readback = runtime / "readback" / "zh" / "modular_dynamic_worker_pool_phase1_20260704.md"
    trigger = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "trigger_binding"
        / "latest.json"
    )
    assert latest.is_file()
    assert trigger.is_file()
    assert Path(payload["evidence_refs"]["brain_provider_latest"]).is_file()
    assert Path(payload["evidence_refs"]["worker_provider_latest"]).is_file()
    assert Path(payload["evidence_refs"]["model_gateway_route_latest"]).is_file()
    assert Path(payload["evidence_refs"]["executor_adapter_latest"]).is_file()
    assert Path(payload["evidence_refs"]["worker_brief_latest"]).is_file()
    assert Path(payload["evidence_refs"]["dynamic_width_policy_latest"]).is_file()
    assert Path(payload["evidence_refs"]["width_blocker_latest"]).is_file()
    assert Path(payload["evidence_refs"]["parallel_draft_batch"]).is_file()
    assert Path(payload["evidence_refs"]["parallel_cost_ledger"]).is_file()
    assert Path(payload["evidence_refs"]["parallel_merge_review"]).is_file()
    assert Path(payload["evidence_refs"]["worker_assignment"]).is_file()
    assert Path(payload["evidence_refs"]["foreground_brain_decision_latest"]).is_file()
    readback_text = readback.read_text(encoding="utf-8")
    assert "现在能 invoke 什么" in readback_text
    assert "DP 不是第二主脑" in readback_text
    assert "foreground_brain_decision" in readback_text


def test_run_enforced_while_freezes_global_default_for_three_metered_waves(
    tmp_path: Path,
) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.run_enforced_while(
        runtime_root=runtime,
        repo_root=REPO_ROOT,
        chain_id="phase1-enforced-test-chain",
        base_wave_id="phase1-enforced-test",
        wave_count=3,
        target_width=8,
        write=True,
        dp_invoker=_fake_dp_invoker,
        require_external_draft=False,
        max_parallel_workers=3,
    )

    assert payload["validation"]["passed"] is True, [
        key for key, value in payload["validation"]["checks"].items() if not value
    ]
    assert payload["status"] == "global_default_runtime_enforced_while_self_chain_pop_ready"
    assert payload["runtime_enforced"] is True
    assert payload["runtime_enforced_scope"] == (
        "seed_cortex_global_default_modular_dynamic_worker_pool_phase1"
    )
    assert payload["enforced_wave_count"] == 3
    assert payload["metered_wave_count"] == 3
    assert payload["self_chain_wave_count"] == 3
    assert payload["while_pop"]["pop_ready"] is True
    assert payload["validation"]["checks"]["capability_gateway_phase1_runtime_enforced"] is True
    assert all(wave["runtime_enforced"] for wave in payload["waves"])
    assert all(wave["metered"] for wave in payload["waves"])

    global_latest = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "global_default"
        / "latest.json"
    )
    while_latest = (
        runtime
        / "state"
        / "modular_dynamic_worker_pool_phase1"
        / "while_chain"
        / "latest.json"
    )
    gateway_latest = runtime / "state" / "capability_gateway" / "latest.json"
    readback = (
        runtime
        / "readback"
        / "zh"
        / "modular_dynamic_worker_pool_phase1_global_default_20260704.md"
    )
    assert global_latest.is_file()
    assert while_latest.is_file()
    assert gateway_latest.is_file()
    assert readback.is_file()
    readback_text = readback.read_text(encoding="utf-8")
    assert "three_waves_enforced: True" in readback_text
    assert "three_waves_metered: True" in readback_text
    assert "three_waves_self_chained: True" in readback_text
