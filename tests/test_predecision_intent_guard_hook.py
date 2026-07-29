from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "predecision_intent_guard_v1.ps1"
PWSH = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")


def _invoke(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PWSH), "-NoProfile", "-File", str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
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
    assert "XINAO_PREDECISION_INTENT_GUARD_V1" in hook["additionalContext"]


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
