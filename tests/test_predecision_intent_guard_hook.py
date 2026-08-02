from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "predecision_intent_guard_v1.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="pwsh not found on PATH")


def _invoke(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    return subprocess.run(
        [PWSH, "-NoProfile", "-File", str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def test_user_prompt_submit_injects_predecision_guard() -> None:
    result = _invoke(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-a",
            "turn_id": "turn-a",
            "prompt": "我不需要自己动手，类似某个功能，可能被你调用。",
        }
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["continue"] is True
    hook = output["hookSpecificOutput"]
    assert hook["hookEventName"] == "UserPromptSubmit"
    context = hook["additionalContext"]
    assert "XINAO_PREDECISION_INTENT_GUARD_V1" in context
    assert "类似/可能" in context
    assert "必要意图推理 token" in context
    assert "不产生授权" in context
    assert "XINAO_GLOBAL_ATTENTION_RECONSIDERATION_V1" in context
    assert "全局注意力重置" in context
    assert "下一实际动作受约束" in context
    assert "只读 fail-open" in context
    assert "薄记忆" in context
    assert "自动派工/续跑" in context
    assert "XINAO_ATTENTION_LIVE_DELTA_V1" not in context
    assert "researcher_container" not in context


def test_compact_session_start_reinjects_same_guard() -> None:
    result = _invoke(
        {
            "hook_event_name": "SessionStart",
            "session_id": "session-a",
            "source": "compact",
        }
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    hook = output["hookSpecificOutput"]
    assert hook["hookEventName"] == "SessionStart"
    context = hook["additionalContext"]
    assert "XINAO_PREDECISION_INTENT_GUARD_V1" in context
    assert "XINAO_GLOBAL_ATTENTION_RECONSIDERATION_V1" in context
    assert "子意图生存裁决、父效果差分、前沿重算和 disposition" in context
    assert "XINAO_ATTENTION_LIVE_DELTA_V1" not in context
    assert "researcher_container" not in context


def test_non_compact_session_start_emits_nothing() -> None:
    result = _invoke(
        {
            "hook_event_name": "SessionStart",
            "session_id": "session-a",
            "source": "startup",
        }
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_hook_remains_fail_open_and_continue_true_on_valid_input() -> None:
    result = _invoke({"hook_event_name": "UserPromptSubmit", "prompt": "继续"})
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["continue"] is True
    assert "hookSpecificOutput" in output
    assert "additionalContext" in output["hookSpecificOutput"]
