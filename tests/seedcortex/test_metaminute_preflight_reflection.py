import json
from pathlib import Path

from services.agent_runtime import metaminute_preflight_reflection as metaminute


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_metaminute_writes_global_self_prelude_without_keyword(tmp_path: Path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"
    monkeypatch.setenv("XINAO_RUNTIME_REPO_READBACK_WRITE", "1")

    payload = metaminute.build(
        trigger="window_start_first_hop",
        current_user_object="unit global prelude",
        latest_user_delta="ordinary task with no productivity keyword",
        repo_root=repo,
        runtime_root=runtime,
        write=True,
    )

    prelude = payload["global_self_prelude"]
    assert payload["validation"]["passed"] is True
    assert payload["validation"]["checks"]["global_self_prelude_present"] is True
    assert prelude["scope"] == "global_always_on_for_codex_s"
    assert prelude["trigger_required"] is False
    assert prelude["keyword_required"] is False
    assert "human_dialogue / diagnosis / execution / watch" in prelude["prompt_zh"]
    assert "foreground mirror watch" in prelude["prompt_zh"]
    assert "Stop/final/report/PASS/readback/latest" in prelude["prompt_zh"]
    assert "外部成熟搜索" in prelude["prompt_zh"]
    assert "默认锚定这些缺口继续派发" in prelude["prompt_zh"]
    assert prelude["classification_gate"]["classes"] == [
        "human_dialogue",
        "diagnosis",
        "execution",
        "watch",
    ]
    assert prelude["foreground_mirror_watch"]["not_execution_controller"] is True
    assert prelude["foreground_mirror_watch"]["source_ref"].endswith("前台长watch_后台镜像语义.txt")
    assert prelude["mandatory_default_mainline_hardening"]["default"] is True
    assert prelude["incomplete_text_anchor_dispatch"]["report_only_forbidden"] is True
    assert "不需要用户二次提醒" in prelude["prompt_zh"]
    assert "cwd/project" in prelude["user_prompt_submit_additional_context"]

    latest = Path(payload["output_paths"]["global_self_prelude_latest"])
    prompt = Path(payload["output_paths"]["global_self_prelude_prompt"])
    decode_index = Path(payload["output_paths"]["intent_decode_index_latest"])
    repo_decode_index = Path(payload["output_paths"]["repo_intent_decode_index"])
    readback = Path(payload["output_paths"]["runtime_readback_zh"])
    assert latest.is_file()
    assert prompt.is_file()
    assert decode_index.is_file()
    assert repo_decode_index.is_file()
    assert readback.is_file()
    assert _read_json(latest)["prelude_id"] == "codex_s_global_self_prelude_v1"
    assert "Codex S 全局自检前置" in prompt.read_text(encoding="utf-8")
    assert "轮询 / 盯后台 / 监工" in repo_decode_index.read_text(encoding="utf-8")
    assert "前台长watch_后台镜像语义.txt" in repo_decode_index.read_text(encoding="utf-8")
    assert "next dispatch/repair/bind" in repo_decode_index.read_text(encoding="utf-8")
    assert _read_json(decode_index)["index_id"] == "codex_s_user_prompt_submit_intake_decode_index_v1"
    assert _read_json(decode_index)["entries"][0]["source_ref"].endswith("前台长watch_后台镜像语义.txt")
    assert any(
        entry["entry_id"] == "incomplete_text_anchor_dispatch"
        for entry in _read_json(decode_index)["entries"]
    )
    assert "Invoke-CodexSUserPromptSubmitHook.ps1" in payload["default_hot_path_triggers"]["user_prompt_submit"]
    assert "全局 Codex self-prelude" in readback.read_text(encoding="utf-8")
