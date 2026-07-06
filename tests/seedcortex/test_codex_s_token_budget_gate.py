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


def test_architecture_audit_routes_dp_first(tmp_path: Path) -> None:
    module = _load_module()

    payload = module.build_payload(
        raw_event_json=_event("全局架构冲突审计，找孤岛和断层"),
        repo_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        write=False,
    )

    assert payload["decision"]["route_id"] == "dp_audit_first"
    assert payload["decision"]["provider_order"] == ["dp", "codex"]


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
    assert payload["decision"]["provider_order"][-1] == "codex"
    assert "repo mutation" in payload["decision"]["reason"]


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
