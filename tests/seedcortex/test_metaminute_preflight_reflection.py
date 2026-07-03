import json
from pathlib import Path

from services.agent_runtime import metaminute_preflight_reflection as metaminute


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_metaminute_writes_global_self_prelude_without_keyword(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    repo = tmp_path / "repo"

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
    assert "审查/报告/守门人模式" in prelude["prompt_zh"]
    assert "artifact" in prelude["prompt_zh"]

    latest = Path(payload["output_paths"]["global_self_prelude_latest"])
    prompt = Path(payload["output_paths"]["global_self_prelude_prompt"])
    readback = Path(payload["output_paths"]["runtime_readback_zh"])
    assert latest.is_file()
    assert prompt.is_file()
    assert readback.is_file()
    assert _read_json(latest)["prelude_id"] == "codex_s_global_self_prelude_v1"
    assert "Codex S 全局自检前置" in prompt.read_text(encoding="utf-8")
    assert "全局 Codex self-prelude" in readback.read_text(encoding="utf-8")
