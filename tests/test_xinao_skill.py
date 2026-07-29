from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "xinao"


def _module():
    path = SKILL_ROOT / "scripts" / "xinao.py"
    spec = importlib.util.spec_from_file_location("xinao_skill_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_metadata_and_registry_define_one_dedicated_entry() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    meta = (SKILL_ROOT / "references" / "meta.md").read_text(encoding="utf-8")
    registry = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    assert "name: xinao" in skill
    assert "ordinary WorkerPool" in skill
    assert "唯一稳定入口" in meta
    assert registry["ordinary_worker_chain_allowed"] is False
    statuses = {item["capability_id"]: item["source_status"] for item in registry["capabilities"]}
    assert statuses == {
        "researcher-container": "available",
        "shadow-account": "planned",
        "decision-freeze": "planned",
        "settlement": "planned",
        "walk-forward-replay": "planned",
    }


def test_charter_has_open_research_and_separate_nonbinding_prior() -> None:
    charter = json.loads(
        (SKILL_ROOT / "references" / "researcher-charter.v1.json").read_text(encoding="utf-8")
    )
    assert charter["research_space"] == "open"
    assert "research_topic_whitelist" not in charter
    assert "ResearchTopicWhitelist" not in charter
    assert "allowed_topics" not in charter
    assert charter["seven_family_attention_prior"]["binding"] is False
    assert len(charter["seven_family_attention_prior"]["families"]) == 7
    assert charter["action_support_reference"]["binding_on_research"] is False


def test_arbitrary_research_question_is_compiled_without_family_admission() -> None:
    module = _module()
    charter = module._validate_charter()
    question = "研究量子退火类启发式与开奖序列结构之间是否存在可证伪联系"
    prompt = module._compile_prompt(question, "2026-07-29T00:00:00Z", charter)
    assert question in prompt
    assert "there is no topic whitelist" in prompt
    assert "nearest family" in prompt


def test_inspection_fails_open_for_absent_runtime_without_user_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("XINAO_RESEARCHER_RUN_ROOT", str(tmp_path / "runs"))
    inspection = module.inspect_capability()
    assert inspection["runtime_status"] == "ABSENT"
    assert inspection["runtime_reason_code"] == "JSON_READ_FAILED"
    assert inspection["user_operations_required"] == []


def test_cross_chain_namespace_is_rejected_before_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    release = {
        "generic_worker_route_allowed": False,
        "state_namespace": "grok_worker_pool/science",
        "run_namespace": "xinao_researcher",
    }
    with pytest.raises(module.XinaoError, match="grok_worker_pool") as captured:
        module._validate_release_for_invoke(release)
    assert captured.value.reason_code == "CROSS_CHAIN_NAMESPACE_FORBIDDEN"


def test_dockerfile_has_dedicated_identity_and_no_generic_entrypoint() -> None:
    dockerfile = (ROOT / "docker" / "xinao-researcher" / "Dockerfile").read_text(encoding="utf-8")
    assert 'io.xinao.researcher.chain="dedicated-xinao-science"' in dockerfile
    assert 'io.xinao.researcher.generic-worker-route="forbidden"' in dockerfile
    assert "integrated_bus_worker_daemon" not in dockerfile
    assert "Invoke-GrokWorkerPool" not in dockerfile


def test_skill_does_not_register_downstream_effects_as_available() -> None:
    registry = json.loads(
        (SKILL_ROOT / "references" / "capabilities.v1.json").read_text(encoding="utf-8")
    )
    downstream = {
        item["capability_id"]: item["source_status"]
        for item in registry["capabilities"]
        if item["capability_id"] != "researcher-container"
    }
    assert set(downstream.values()) == {"planned"}


def test_provider_effect_requires_real_terminal_usage() -> None:
    module = _module()
    valid = {
        "provider_stop_reason": "EndTurn",
        "provider_num_turns": 1,
        "provider_session_id_present": True,
        "provider_request_id_present": True,
        "provider_model_usage": {"grok-4.5-build": {"modelCalls": 1}},
        "usage": {"total_tokens": 12},
    }
    assert module._provider_effect_valid(valid) is True
    assert module._provider_effect_valid({**valid, "usage": {"total_tokens": 0}}) is False


def test_generic_worker_arguments_get_typed_rejection(capsys: pytest.CaptureFixture[str]) -> None:
    module = _module()
    exit_code = module.main(["research", "--question", "q", "--CommonWorkKey", "wrong-chain"])
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["status"] == "PREFLIGHT_FAILED"
    assert result["reason_codes"] == ["INVOCATION_ARGUMENTS_INVALID"]
    assert result["user_operations_required"] == []


def test_rollback_switches_only_current_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    state = tmp_path / "state"
    monkeypatch.setenv("XINAO_SKILL_STATE_ROOT", str(state))
    release_root = state / "researcher_container" / "releases"
    a_path = release_root / "a" / "release.json"
    b_path = release_root / "b" / "release.json"
    module._write_json_atomic(a_path, {"release_id": "a"}, create_new=True)
    module._write_json_atomic(b_path, {"release_id": "b"}, create_new=True)
    pointer_path = state / "researcher_container" / "current.json"
    module._write_json_atomic(
        pointer_path,
        {
            "schema_version": "xinao.researcher_current_pointer.v1",
            "release_id": "b",
            "release_manifest_path": str(b_path),
            "release_manifest_sha256": module._sha256(b_path),
            "previous_release_id": "a",
            "previous_release_manifest_path": str(a_path),
            "previous_release_manifest_sha256": module._sha256(a_path),
        },
        create_new=True,
    )
    receipt = module.rollback_release()
    current = module._load_json(pointer_path)
    assert receipt["status"] == "ROLLED_BACK"
    assert current["release_id"] == "a"
    assert current["previous_release_id"] == "b"
    assert module._load_json(a_path) == {"release_id": "a"}
    assert module._load_json(b_path) == {"release_id": "b"}
