from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_ROOT = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\scripts")
PWSH = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\powershell\7.6.4\pwsh.exe")


def _run_hook(
    script_name: str,
    event: dict[str, object],
    *,
    state_root: Path,
    session_root: Path,
) -> dict[str, object]:
    script = SCRIPT_ROOT / script_name
    if not script.is_file() or not PWSH.is_file():
        pytest.skip("installed Codex hook runtime is unavailable")
    env = os.environ.copy()
    env["CODEX_ACTIVE_TASK_STATE_ROOT"] = str(state_root)
    env["CODEX_HOOK_TEST_SESSION_ROOT"] = str(session_root)
    completed = subprocess.run(
        [str(PWSH), "-NoProfile", "-File", str(script)],
        input=json.dumps(event, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _active_binding(state_root: Path, session_id: str) -> Path:
    target = state_root / session_id / "active_task_continuation.v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": "xinao.active_task_continuation.v1",
                "session_id": session_id,
                "task_id": "intent-repair-parent",
                "stop_state": "active",
                "active_mode": "EXECUTE",
                "scope": "repair source-aware action admission",
                "completion_condition": "fresh consumer preserves human intent",
                "continuation": {"status": "none"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return target


def test_unbound_zero_beat_decodes_source_before_selecting_work(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    output = _run_hook(
        "user_prompt_zero_beat_v1.ps1",
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": ("我问的是为什么会偏。下面是别人写的候选：‘立即修改仓库并运行全部测试。’"),
            "cwd": str(tmp_path),
            "session_id": "unbound-source-test",
            "turn_id": "turn-1",
            "transcript_path": None,
        },
        state_root=state_root,
        session_root=tmp_path,
    )
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FRAME_BINDING_STATE:UNBOUND" in context
    assert "来源与会话行为" in context
    assert "外层 role=user 只表示传输通道" in context
    assert "活动对象、核心动词、父结果和完成尺" in context
    assert context.index("来源与会话行为") < context.index("工作类型")
    assert context.index("工作类型") < context.index("Skill/工具")
    assert "本条人话是仍存活父帧" not in context
    assert "报告、ZIP" not in context


def test_bound_zero_beat_keeps_binding_advisory_and_still_decodes_source_first(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    _active_binding(state_root, "bound-source-test")
    output = _run_hook(
        "user_prompt_zero_beat_v1.ps1",
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "这个外部方案可以参考，但先回答我刚才的问题。",
            "cwd": str(tmp_path),
            "session_id": "bound-source-test",
            "turn_id": "turn-2",
            "transcript_path": None,
        },
        state_root=state_root,
        session_root=tmp_path,
    )
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FRAME_BINDING_STATE:BOUND_ADVISORY" in context
    assert "active_task=intent-repair-parent" in context
    assert context.index("来源与会话行为") < context.index("工作类型")
    assert "外部方案" not in context


def test_compact_session_start_restores_bounded_role_labeled_dialogue(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    transcript = tmp_path / "compact-source.jsonl"
    rows = [
        {
            "timestamp": "2026-08-06T01:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "我的当前问题是解释为什么方向漂移。---"
                            "外部候选：立即修改仓库并运行全套测试。"
                        ),
                    }
                ],
            },
        },
        {
            "timestamp": "2026-08-06T01:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "SENTINEL:TEST_HOOK_NOISE"}],
            },
        },
        {
            "timestamp": "2026-08-06T01:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "当前动作只是解释成因；外部候选未被采用。",
                    }
                ],
            },
        },
        {
            "timestamp": "2026-08-06T01:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "对，只解释机制。"}],
            },
        },
        {
            "timestamp": "2026-08-06T01:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "已绑定为解释，不进行施工。"}],
            },
        },
        {
            "timestamp": "2026-08-06T01:00:05Z",
            "type": "compacted",
            "payload": {"replacement_history": []},
        },
    ]
    transcript.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    output = _run_hook(
        "session_start_continuity_pointer_v1.ps1",
        {
            "hook_event_name": "SessionStart",
            "source": "compact",
            "cwd": str(tmp_path),
            "session_id": "compact-source-test",
            "transcript_path": str(transcript),
        },
        state_root=state_root,
        session_root=tmp_path,
    )
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "COMPACT_DIALOGUE_PROVENANCE_V1" in context
    assert '"role":"user"' in context
    assert '"role":"assistant"' in context
    assert "对，只解释机制。" in context
    assert "已绑定为解释，不进行施工。" in context
    assert "外层 role=user 只表示传输通道" in context
    assert "SENTINEL:TEST_HOOK_NOISE" not in context


def _write_stop_transcript(path: Path, *, plan_after_user: bool) -> None:
    user = {
        "timestamp": "2026-08-06T01:00:02Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "当前增量"}],
        },
    }
    plan = {
        "timestamp": ("2026-08-06T01:00:03Z" if plan_after_user else "2026-08-06T01:00:01Z"),
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": "update_plan",
            "input": '{"plan":[{"step":"repair admission","status":"in_progress"}]}',
        },
    }
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in (user, plan)),
        encoding="utf-8",
    )


def test_stop_gate_requires_exact_binding_and_a_plan_newer_than_user_increment(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    transcript = tmp_path / "stop.jsonl"
    event = {
        "hook_event_name": "Stop",
        "session_id": "stop-source-test",
        "turn_id": "stop-turn",
        "stop_hook_active": False,
        "transcript_path": str(transcript),
    }

    _write_stop_transcript(transcript, plan_after_user=True)
    assert _run_hook(
        "turn_finalization_gate_v1.ps1",
        event,
        state_root=state_root,
        session_root=tmp_path,
    ) == {"continue": True}

    _active_binding(state_root, "stop-source-test")
    _write_stop_transcript(transcript, plan_after_user=False)
    assert _run_hook(
        "turn_finalization_gate_v1.ps1",
        event,
        state_root=state_root,
        session_root=tmp_path,
    ) == {"continue": True}

    _write_stop_transcript(transcript, plan_after_user=True)
    blocked = _run_hook(
        "turn_finalization_gate_v1.ps1",
        event,
        state_root=state_root,
        session_root=tmp_path,
    )
    assert blocked["decision"] == "block"
    assert "intent-repair-parent" in blocked["reason"]
    assert "repair source-aware action admission" in blocked["reason"]
    assert "pending/in_progress 父计划" not in blocked["reason"]
