import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "services" / "agent_runtime" / "codex_s_token_budget_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("codex_s_token_budget_gate", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event(prompt: str) -> str:
    return json.dumps({"hook_event_name": "UserPromptSubmit", "user_prompt": prompt}, ensure_ascii=False)


def test_small_file_routes_codex_direct(tmp_path: Path) -> None:
    module = _load_module()
    small_file = tmp_path / "small.txt"
    small_file.write_text("short local text\n", encoding="utf-8")

    payload = module.build_payload(
        raw_event_json=_event(f"读取 {small_file} 然后人话说下"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "codex_direct_small_read"
    assert payload["decision"]["provider_order"] == ["codex"]
    assert payload["decision"]["estimated_roundtrip_waste"] is True


def test_large_file_summary_routes_qwen_or_local_candidate_before_codex(tmp_path: Path) -> None:
    module = _load_module()
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * (module.LARGE_FILE_BYTES + 1024), encoding="utf-8")

    payload = module.build_payload(
        raw_event_json=_event(f"总结 {large_file} 的关键点"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "qwen_pre_extract"
    assert payload["decision"]["provider_order"] == ["qwen_or_local_candidate", "codex"]
    assert payload["decision"]["codex_read_policy"] == "do_not_read_full_raw_context_first"
    assert payload["global_router"]["router_name"] == "GlobalCostQualityQuotaRouter"
    assert payload["global_router"]["qwen_quota_priority_applies"] is True
    assert payload["global_router"]["fixed_deepseek_share_target_used"] is False
    assert payload["global_router"]["provider_scheduler_hint"]["local_model_candidate_when_scored"] is True
    assert payload["global_router"]["provider_scheduler_hint"]["local_first_mandatory"] is False


def test_architecture_audit_routes_qwen_then_deepseek_pro_before_codex(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event("全局架构冲突审计，找孤岛和断层"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "qwen_then_deepseek_pro_audit"
    assert payload["decision"]["provider_order"] == [
        "qwen_extract_or_quality",
        "deepseek_v4_pro_audit",
        "codex_fan_in",
    ]
    assert payload["global_router"]["qwen_quota_priority_applies"] is True
    assert payload["global_router"]["deepseek_codex_replacement_applies"] is True
    assert payload["global_router"]["codex_boundary"] == "final_judgment_and_acceptance"


def test_dialogue_does_not_create_worker_evidence(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event("这个机制是什么意思，先讨论"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "codex_direct_human_dialogue"
    assert payload["decision"]["action"] == "answer_directly_no_worker_evidence"
    assert payload["completion_claim_allowed"] is False
    assert payload["not_execution_controller"] is True


def test_repo_mutation_stays_codex_owned(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event("修复这个 hook 并提交 commit"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "codex_mutation_final_owner"
    assert payload["decision"]["provider_order"][-1] == "codex_final_patch_aaq"
    assert "repo mutation" in payload["decision"]["reason"]
    assert payload["global_router"]["codex_boundary"] == "final_patch_merge_aaq_high_risk_owner"


def test_large_architecture_file_uses_qwen_extract_and_deepseek_pro(tmp_path: Path) -> None:
    module = _load_module()
    large_file = tmp_path / "architecture.txt"
    large_file.write_text("architecture conflict\n" * 8000, encoding="utf-8")

    payload = module.build_payload(
        raw_event_json=_event(f"全局架构冲突审计 {large_file}，找孤岛和断层"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "qwen_then_deepseek_pro_large_architecture_audit"
    assert payload["decision"]["provider_order"] == [
        "qwen_extract",
        "deepseek_v4_pro_audit",
        "codex_fan_in",
    ]
    assert payload["decision"]["codex_read_policy"] == "do_not_read_full_raw_context_first"
    assert payload["global_router"]["must_not"][0] == "do_not_make_deepseek_fixed_80_90_target"


def test_inventory_architecture_audit_does_not_degrade_to_qwen_only(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event(
            "global architecture audit, conflict inventory, capability islands, old repo gaps"
        ),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "qwen_then_deepseek_pro_audit"
    assert payload["decision"]["provider_order"] == [
        "qwen_extract_or_quality",
        "deepseek_v4_pro_audit",
        "codex_fan_in",
    ]
    assert payload["global_router"]["qwen_quota_priority_applies"] is True
    assert payload["global_router"]["deepseek_codex_replacement_applies"] is True


def test_audit_with_final_fanin_text_does_not_become_repo_mutation(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event(
            "RootIntentLoop verifier large architecture audit should use Qwen quota first, "
            "DeepSeek V4 Pro for hard audit, Codex final fan-in only."
        ),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["flags"]["audit"] is True
    assert payload["flags"]["mutation"] is False
    assert payload["decision"]["route_id"] == "qwen_then_deepseek_pro_audit"
    assert payload["decision"]["provider_order"] == [
        "qwen_extract_or_quality",
        "deepseek_v4_pro_audit",
        "codex_fan_in",
    ]
    assert payload["global_router"]["fixed_deepseek_share_target_used"] is False


def test_external_search_is_retrieval_and_local_qwen_are_draft_consumers(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event(
            "搜索外部开源项目代码架构，用 Exa/SourceLedger 找资料，本地模型和千问只写草稿"
        ),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "search_then_local_qwen_dp_claimcards"
    assert payload["decision"]["provider_order"][0] == "search_exa_or_sourceledger"
    assert payload["decision"]["search_lane_boundary"].startswith("search/exa is retrieval only")
    assert payload["decision"]["local_model_role"] == "cheap_draft_summary_classify_compress_staging_only"
    assert payload["decision"]["light_research_loop_entrypoint"].endswith("light-research-loop")
    assert "local_ollama_candidate_when_router_scores_positive" in payload["global_router"]["default_ladder"]
    assert "do_not_treat_search_exa_as_deepseek_execution" in payload["global_router"]["must_not"]
    assert payload["global_router"]["provider_scheduler_hint"]["local_ollama_qwen_default_first_when_configured"] is False
    assert payload["global_router"]["provider_scheduler_hint"]["ollama_resource_limits_not_route_policy"] is True
    assert payload["global_router"]["provider_scheduler_hint"]["search_provider_boundary"].startswith("search/exa retrieves")
    assert payload["global_router"]["provider_scheduler_hint"]["light_research_loop_scope"] == "foreground_temporary_search_audit_not_333_mainline"


def test_write_records_latest_and_readback(tmp_path: Path) -> None:
    module = _load_module()
    runtime = tmp_path / "runtime"

    payload = module.build_payload(
        raw_event_json=_event("全局能力盘点"),
        repo_root=tmp_path,
        runtime_root=runtime,
        write=True,
    )

    latest = runtime / "state" / module.STATE_NAME / "latest.json"
    readback = runtime / "readback" / "zh" / f"{module.STATE_NAME}.md"
    assert latest.is_file()
    assert readback.is_file()
    assert json.loads(latest.read_text(encoding="utf-8"))["prompt_sha256"] == payload["prompt_sha256"]
