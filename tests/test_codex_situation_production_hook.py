from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import services.agent_runtime.codex_situation_hook as hook_module
from services.agent_runtime.codex_situation_hook import (
    L0_CONTEXT,
    SituationHookError,
    compact_checkpoint,
    handle_hook_event,
    render_checkpoint_context,
    session_store_path,
)
from services.agent_runtime.current_situation import build_snapshot, initialize_store, retire_store

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_A = "019fef07-4cb5-78e1-ab7c-39fcec576ecb"
SESSION_B = "019fef07-4cb5-78e1-ab7c-39fcec576ecc"
SESSION_CLI = "019fef07-4cb5-78e1-ab7c-39fcec576ecd"


def _snapshot(*, activity: str = "continue the whole discussion") -> dict[str, object]:
    return build_snapshot(
        lineage_id="lineage-a",
        generation=0,
        last_event_ref={
            "event_id": "event-a",
            "event_sha256": "a" * 64,
            "relation": "correction",
        },
        current={
            "activity": {"description": activity, "mode": "discussion"},
            "object": {"description": "the current human--Codex relation"},
            "human_relation": {
                "description": "the user corrected the whole framing",
                "user_need_not_repeat": "the corrected parent frame",
            },
            "understandings": [
                {
                    "id": "u1",
                    "source_event_id": "event-a",
                    "statement": "the correction changes the current world before any task",
                }
            ],
            "retracted": [],
            "open_relations": [],
        },
    )


class _Observation:
    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "codex.situation_snapshot.runtime_observation.v1",
            "captured_at": "2026-08-11T00:00:00.000000Z",
            "facts_sha256": "b" * 64,
            "observed": {
                "cwd": r"E:\work",
                "cwd_resolved": r"E:\work",
                "observer_process": {
                    "pid": 1,
                    "parent_pid": 2,
                    "executable": r"D:\python.exe",
                    "executable_resolved": r"D:\python.exe",
                },
                "environment": {"CODEX_HOME": r"C:\Users\u\.codex"},
                "git": {
                    "root": r"E:\work",
                    "head": "c" * 40,
                    "branch": "main",
                    "linked_worktree": False,
                    "detached_head": False,
                    "dirty": False,
                    "porcelain_status_sha256": "d" * 64,
                    "dirty_fingerprint_sha256": "e" * 64,
                    "dirty_fingerprint_complete": True,
                    "snapshot_stable": True,
                },
                "file_candidates": [
                    {
                        "scope": "global",
                        "kind": "agents",
                        "path": r"C:\Users\u\.codex\AGENTS.md",
                        "resolved_target": r"C:\Users\u\.codex\AGENTS.md",
                        "path_redirected": False,
                        "exists": True,
                        "sha256": "f" * 64,
                        "capture_stable": True,
                    },
                    {
                        "scope": "ancestor",
                        "kind": "hooks",
                        "path": r"E:\missing\.codex\hooks.json",
                        "resolved_target": r"E:\missing\.codex\hooks.json",
                        "path_redirected": False,
                        "exists": False,
                        "sha256": None,
                        "capture_stable": True,
                    },
                ],
            },
            "declared": {"invocation": {}, "provenance": "caller_supplied_unverified"},
            "unknown": [
                {
                    "field": "observed.permissions.filesystem_access",
                    "reason": "no_current_process_enforcement_probe",
                }
            ],
            "authority": False,
            "completion_claim_allowed": False,
        }


@pytest.fixture
def fake_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hook_module,
        "collect_runtime_observation",
        lambda **_kwargs: _Observation(),
    )


def test_user_prompt_keeps_l0_first_and_adds_labeled_runtime_without_prompt_echo(
    fake_observation: None,
) -> None:
    event = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "SECRET MATERIAL MUST NOT BE ECHOED",
        "session_id": "session-a",
        "turn_id": "turn-a",
        "cwd": r"E:\work",
        "model": "gpt-test",
        "permission_mode": "dontAsk",
    }
    output = handle_hook_event(event)
    context = output["hookSpecificOutput"]["additionalContext"]

    assert output["continue"] is True
    assert context.startswith(L0_CONTEXT)
    assert "SECRET MATERIAL" not in context
    assert "hook_child_process_not_parent_codex" in context
    assert "caller_supplied_unverified" not in context
    assert "no_current_process_enforcement_probe" in context
    assert r"E:\missing" not in context
    assert '"authority":false' in context


def test_runtime_failure_preserves_l0_and_never_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**_kwargs: object) -> object:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(hook_module, "collect_runtime_observation", fail)
    output = handle_hook_event({"hook_event_name": "UserPromptSubmit", "prompt": "continue"})
    assert output == {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": L0_CONTEXT,
        },
    }


def test_resume_and_compact_consume_only_the_exact_session_checkpoint(
    tmp_path: Path,
    fake_observation: None,
) -> None:
    store = session_store_path(SESSION_A, store_root=tmp_path)
    initialize_store(store, _snapshot())

    output = handle_hook_event(
        {
            "hook_event_name": "SessionStart",
            "source": "compact",
            "session_id": SESSION_A,
            "cwd": r"E:\work",
        },
        store_root=tmp_path,
    )
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "CURRENT SITUATION CHECKPOINT" in context
    assert "continue the whole discussion" in context
    assert '"autonomous_revision_observed":false' in context
    assert '"authority":false' in context

    missing = handle_hook_event(
        {
            "hook_event_name": "SessionStart",
            "source": "resume",
            "session_id": SESSION_B,
            "cwd": r"E:\work",
        },
        store_root=tmp_path,
    )
    missing_context = missing["hookSpecificOutput"]["additionalContext"]
    assert "RUNTIME OBSERVATION" in missing_context
    assert "CURRENT SITUATION CHECKPOINT" not in missing_context


def test_startup_does_not_select_or_revive_any_checkpoint(
    tmp_path: Path,
    fake_observation: None,
) -> None:
    initialize_store(session_store_path(SESSION_A, store_root=tmp_path), _snapshot())
    assert handle_hook_event(
        {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "session_id": SESSION_A,
        },
        store_root=tmp_path,
    ) == {"continue": True}


def test_corrupt_checkpoint_fails_open_to_runtime_context(
    tmp_path: Path,
    fake_observation: None,
) -> None:
    store = session_store_path(SESSION_A, store_root=tmp_path)
    store.mkdir(parents=True)
    (store / "current.json").write_text("not-json", encoding="utf-8")
    output = handle_hook_event(
        {
            "hook_event_name": "SessionStart",
            "source": "resume",
            "session_id": SESSION_A,
            "cwd": r"E:\work",
        },
        store_root=tmp_path,
    )
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "RUNTIME OBSERVATION" in context
    assert "CURRENT SITUATION CHECKPOINT" not in context


def test_checkpoint_render_is_bounded_and_carries_no_task_fields(tmp_path: Path) -> None:
    store = session_store_path(SESSION_A, store_root=tmp_path)
    initialize_store(store, _snapshot(activity="x" * 8_000))
    rendered = render_checkpoint_context(SESSION_A, store_root=tmp_path)
    payload = compact_checkpoint(_snapshot(activity="x" * 8_000))

    assert len(rendered) < 7_500
    assert payload["authority"] is False
    assert payload["autonomous_revision_observed"] is False
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("next_task", "next_action", "goal", "plan", "worker"):
        assert forbidden not in serialized


def test_json_stdio_adapter_returns_utf8_json_and_never_echoes_prompt() -> None:
    script = REPO_ROOT / "scripts" / "codex_situation_context_hook.py"
    event = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "DO-NOT-ECHO-THIS-PROMPT",
        "session_id": "session-cli",
        "turn_id": "turn-cli",
        "cwd": str(REPO_ROOT),
        "model": "gpt-test",
        "permission_mode": "dontAsk",
    }
    completed = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    output = json.loads(completed.stdout.decode("utf-8"))
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("SENTINEL:HUMAN_WORDS_BEFORE_ARTIFACTS_V2")
    assert "DO-NOT-ECHO" not in context
    assert "RUNTIME OBSERVATION" in context


def test_manager_initializes_and_inspects_an_exact_session(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps(_snapshot(), ensure_ascii=False),
        encoding="utf-8",
    )
    script = REPO_ROOT / "scripts" / "manage_current_situation.py"
    store_root = tmp_path / "store"
    initialized = subprocess.run(
        [
            sys.executable,
            str(script),
            "--store-root",
            str(store_root),
            "initialize",
            "--session-id",
            SESSION_CLI,
            "--snapshot-file",
            str(snapshot_file),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=REPO_ROOT,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["authority"] is False

    inspected = subprocess.run(
        [
            sys.executable,
            str(script),
            "--store-root",
            str(store_root),
            "inspect",
            "--session-id",
            SESSION_CLI,
            "--compact",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=REPO_ROOT,
    )
    assert inspected.returncode == 0, inspected.stderr
    result = json.loads(inspected.stdout)
    assert result["lineage_id"] == "lineage-a"
    assert result["authority"] is False

    retired = subprocess.run(
        [
            sys.executable,
            str(script),
            "--store-root",
            str(store_root),
            "retire",
            "--session-id",
            SESSION_CLI,
            "--reason",
            "explicit test retirement",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=REPO_ROOT,
    )
    assert retired.returncode == 0, retired.stderr
    retirement = json.loads(retired.stdout)
    assert retirement["status"] == "retired"
    assert Path(retirement["cold_retirement_receipt"]).is_file()


def test_session_store_rejects_aliases_colons_and_link_redirection(tmp_path: Path) -> None:
    for invalid in (SESSION_A.upper(), "session:alias", "session-a"):
        with pytest.raises(SituationHookError, match="unsupported session_id"):
            session_store_path(invalid, store_root=tmp_path)

    sessions = tmp_path / "sessions"
    target = sessions / SESSION_B
    target.mkdir(parents=True)
    link = sessions / SESSION_A
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(SituationHookError, match="cannot be a link"):
        session_store_path(SESSION_A, store_root=tmp_path)


def test_retired_or_aged_checkpoint_is_not_reinjected(
    tmp_path: Path,
    fake_observation: None,
) -> None:
    store = session_store_path(SESSION_A, store_root=tmp_path)
    initialize_store(store, _snapshot())
    old = time.time() - (8 * 24 * 60 * 60)
    os.utime(store / "current.json", (old, old))
    aged = handle_hook_event(
        {
            "hook_event_name": "SessionStart",
            "source": "resume",
            "session_id": SESSION_A,
            "cwd": r"E:\work",
        },
        store_root=tmp_path,
    )
    assert "CURRENT SITUATION CHECKPOINT" not in aged["hookSpecificOutput"]["additionalContext"]

    os.utime(store / "current.json", None)
    result = retire_store(store, reason="the activity was explicitly replaced")
    assert Path(result["cold_retirement_receipt"]).is_file()
    retired = handle_hook_event(
        {
            "hook_event_name": "SessionStart",
            "source": "compact",
            "session_id": SESSION_A,
            "cwd": r"E:\work",
        },
        store_root=tmp_path,
    )
    assert "CURRENT SITUATION CHECKPOINT" not in retired["hookSpecificOutput"]["additionalContext"]


def test_combined_context_overflow_falls_back_to_l0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hook_module, "render_runtime_context", lambda _event: "x" * 20_000)
    output = handle_hook_event({"hook_event_name": "UserPromptSubmit", "prompt": "discussion"})
    assert output["hookSpecificOutput"]["additionalContext"] == L0_CONTEXT
