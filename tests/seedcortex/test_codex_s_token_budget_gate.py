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


def test_large_file_summary_routes_qwen_first(tmp_path: Path) -> None:
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
    assert payload["decision"]["provider_order"] == ["qwen", "codex"]
    assert payload["decision"]["codex_read_policy"] == "do_not_read_full_raw_context_first"
    assert payload["global_router"]["router_name"] == "GlobalCostQualityQuotaRouter"
    assert payload["global_router"]["qwen_quota_priority_applies"] is True
    assert payload["global_router"]["fixed_deepseek_share_target_used"] is False


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
