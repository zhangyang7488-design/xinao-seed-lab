from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import services.agent_runtime.codex_situation_hook as hook_module
from services.agent_runtime.codex_situation_hook import L0_CONTEXT, handle_hook_event
from services.agent_runtime.context_fabric import (
    append_projection,
    append_relation,
    capture_hook_event,
    create_snapshot,
    evaluate_mount,
    import_codex_rollout,
    initialize_context_fabric,
    lexical_terms,
    read_event,
    render_hook_context,
    render_materialized_context,
    search_events,
    store_inventory,
    verify_event_chain,
)

SESSION = "019ff75c-703c-7972-96cd-b0d257b13baa"
TURN_A = "019ff75d-1749-7662-9e80-aafa605718ab"
TURN_B = "019ff75d-1749-7662-9e80-aafa605718ac"


def _mount(tmp_path: Path) -> tuple[Path, dict[str, str], dict[str, str]]:
    home = tmp_path / ".codex"
    home.mkdir()
    allowed = {str(home): "s-primary"}
    environ = {"CODEX_HOME": str(home)}
    return home, allowed, environ


def _hook(
    *,
    name: str,
    session: str = SESSION,
    turn: str = TURN_A,
    prompt: str = "",
    assistant: str = "",
    cwd: str = r"E:\XINAO_RESEARCH_WORKSPACES\S",
) -> dict[str, object]:
    event: dict[str, object] = {
        "hook_event_name": name,
        "session_id": session,
        "turn_id": turn,
        "cwd": cwd,
        "model": "gpt-test",
    }
    if prompt:
        event["prompt"] = prompt
    if assistant:
        event["last_assistant_message"] = assistant
    return event


def test_mount_policy_is_allowlist_first_and_cleanroom_denied(tmp_path: Path) -> None:
    home, allowed, environ = _mount(tmp_path)
    admitted = evaluate_mount(
        {"cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S"},
        environ=environ,
        allowed_homes=allowed,
    )
    assert admitted.mounted is True
    assert admitted.carrier_id == "s-primary"

    unknown = evaluate_mount(
        {"cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S"},
        environ={"CODEX_HOME": str(home.parent / ".codex-cleanroom")},
        allowed_homes=allowed,
    )
    assert unknown.mounted is False
    assert unknown.reason == "codex_home_not_in_s_b_allowlist"

    cleanroom = evaluate_mount(
        {"cwd": r"E:\CODEX_CLEANROOM\new-research"},
        environ=environ,
        allowed_homes=allowed,
    )
    assert cleanroom.mounted is False
    assert cleanroom.reason == "cwd_is_cleanroom_or_research_body"

    with pytest.raises(ValueError, match="state cannot live under cleanroom"):
        initialize_context_fabric(Path(r"E:\CODEX_CLEANROOM\__context_fabric_forbidden_test__"))


def test_raw_messages_are_exact_append_only_idempotent_and_chain_verified(tmp_path: Path) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    event = _hook(name="UserPromptSubmit", prompt="原始人话\n第二行")
    first = capture_hook_event(event, root=root, environ=environ, allowed_homes=allowed)
    second = capture_hook_event(event, root=root, environ=environ, allowed_homes=allowed)
    assert first is not None and second is not None
    assert first.status == "appended"
    assert second.status == "duplicate"
    assert second.event_id == first.event_id
    assert read_event(first.event_id, root=root)["raw_text"] == "原始人话\n第二行"
    assert verify_event_chain(root)["event_count"] == 1

    database = root / "context_fabric.sqlite3"
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE events SET speaker='other'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM events")


def test_secret_like_surface_is_hash_only_and_never_retrieved(tmp_path: Path) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    secret = "authorization: Bearer abcdefghijklmnopqrstuvwxyz"
    result = capture_hook_event(
        _hook(name="UserPromptSubmit", prompt=secret),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    assert result is not None
    event = read_event(result.event_id, root=root)
    assert event["raw_storage"] == "hash_only_secret_withheld"
    assert secret not in event["raw_text"]
    assert "abcdefghijklmnopqrstuvwxyz" not in render_materialized_context(
        query="authorization", root=root
    )
    assert store_inventory(root)["secret_like_events_withheld"] == 1

    with pytest.raises(ValueError, match="projection content resembles a secret"):
        append_projection(
            {
                "kind": "semantic_cluster",
                "semantic_key": "must-not-store-secrets",
                "statement": "derived content remains credential-free",
                "source_event_ids": [result.event_id],
                "content": {"token": "abcdefghijklmnopqrstuvwxyz"},
            },
            root=root,
        )


def test_lexical_index_is_bounded_but_keeps_both_ends() -> None:
    terms = lexical_terms("head-marker " + ("超" * 1_000_000) + " tail-marker")
    assert len(terms) <= 96
    assert "head-marker" in terms
    assert "tail-marker" in terms


def test_projection_and_correction_lineage_rehydrate_short_chinese_query(tmp_path: Path) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    old = capture_hook_event(
        _hook(name="UserPromptSubmit", prompt="我先前误把 C 当成实验 arm C"),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    correction = capture_hook_event(
        _hook(
            name="UserPromptSubmit",
            turn=TURN_B,
            prompt="A/C 只是账号额度入口，不改变研究协议",
        ),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    assert old is not None and correction is not None
    projection = append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "account-slot-selection",
            "statement": "A/C 是 S/B 之外对应身体的账号额度快捷选择；字母不分配研究协议。",
            "aliases": ["C", "A/C", "C并发研究", "账号额度入口"],
            "temporal_scope": "current local launcher/runtime meaning",
            "status_label": "current",
            "source_event_ids": [correction.event_id],
            "content": {"identity": "account_slot", "authority": False},
        },
        root=root,
    )
    duplicate = append_projection(
        {
            "kind": "semantic_identity",
            "semantic_key": "account-slot-selection",
            "statement": "A/C 是 S/B 之外对应身体的账号额度快捷选择；字母不分配研究协议。",
            "aliases": ["C", "A/C", "C并发研究", "账号额度入口"],
            "temporal_scope": "current local launcher/runtime meaning",
            "status_label": "current",
            "source_event_ids": [correction.event_id],
            "content": {"identity": "account_slot", "authority": False},
        },
        root=root,
    )
    assert duplicate["status"] == "duplicate"
    assert duplicate["projection_id"] == projection["projection_id"]
    append_relation(
        {
            "kind": "corrects",
            "from_ref": old.event_id,
            "to_ref": projection["projection_id"],
            "source_event_id": correction.event_id,
            "temporal_scope": "current runtime",
            "note": "preserve the old attractor as corrected history",
        },
        root=root,
    )
    current, context = render_hook_context(
        _hook(
            name="UserPromptSubmit", turn="019ff75d-1749-7662-9e80-aafa605718ad", prompt="C并发研究"
        ),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    assert current is not None
    assert "C并发研究" not in context
    assert "account-slot-selection" in context
    assert "账号额度" in context
    assert '"kind":"corrects"' in context
    assert '"authority":false' in context
    assert '"instruction_source":false' in context
    hits = search_events("A/C 账号额度", root=root)
    assert hits[0]["event_id"] == correction.event_id

    with pytest.raises(ValueError, match="relation from_ref does not exist"):
        append_relation(
            {
                "kind": "corrects",
                "from_ref": "evt_does_not_exist",
                "to_ref": projection["projection_id"],
                "source_event_id": correction.event_id,
            },
            root=root,
        )


def test_rollout_import_uses_only_surfaced_item_events_and_is_idempotent(tmp_path: Path) -> None:
    home, allowed, _ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    session_dir = home / "sessions" / "2026" / "08" / "13"
    session_dir.mkdir(parents=True)
    rollout = session_dir / f"rollout-2026-08-13T00-00-00-{SESSION}.jsonl"
    records = [
        {
            "timestamp": "2026-08-12T16:00:00Z",
            "ordinal": 0,
            "type": "session_meta",
            "payload": {
                "id": SESSION,
                "session_id": SESSION,
                "cwd": r"E:\XINAO_RESEARCH_WORKSPACES\S",
                "source": "cli",
                "thread_source": "user",
            },
        },
        {
            "timestamp": "2026-08-12T16:00:01Z",
            "ordinal": 1,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "INJECTED AGENTS MATERIAL"}],
            },
        },
        {
            "timestamp": "2026-08-12T16:00:02Z",
            "ordinal": 2,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": SESSION,
                "turn_id": TURN_A,
                "item": {
                    "type": "UserMessage",
                    "id": "user-one",
                    "content": [{"type": "text", "text": "真正用户消息"}],
                },
            },
        },
        {
            "timestamp": "2026-08-12T16:00:03Z",
            "ordinal": 3,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": SESSION,
                "turn_id": TURN_A,
                "item": {
                    "type": "AgentMessage",
                    "id": "assistant-one",
                    "phase": "final_answer",
                    "content": [{"type": "Text", "text": "真正助手消息"}],
                },
            },
        },
        {
            "timestamp": "2026-08-12T16:00:04Z",
            "ordinal": 4,
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": SESSION,
                "turn_id": TURN_A,
                "item": {"type": "CommandExecution", "content": "SECRET TOOL OUTPUT"},
            },
        },
    ]
    rollout.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    first = import_codex_rollout(rollout, carrier_home=home, root=root, allowed_homes=allowed)
    second = import_codex_rollout(rollout, carrier_home=home, root=root, allowed_homes=allowed)
    cross_source_duplicate = capture_hook_event(
        _hook(name="UserPromptSubmit", prompt="真正用户消息"),
        root=root,
        environ={"CODEX_HOME": str(home)},
        allowed_homes=allowed,
    )
    assert first["appended"] == 2
    assert second["duplicate"] == 2
    assert cross_source_duplicate is not None
    assert cross_source_duplicate.status == "duplicate"
    assert store_inventory(root)["events"] == 2
    context = render_materialized_context(query="真正", root=root)
    assert "真正用户消息" in context
    assert "真正助手消息" in context
    assert "INJECTED AGENTS" not in context
    assert "SECRET TOOL OUTPUT" not in context

    escaped = json.loads(rollout.read_text(encoding="utf-8").splitlines()[2])
    escaped["payload"]["thread_id"] = "019ff778-e326-7b91-9784-4fe809585e03"
    escaped_rollout = session_dir / f"rollout-escaped-{SESSION}.jsonl"
    escaped_rollout.write_text(
        json.dumps(records[0], ensure_ascii=False)
        + "\n"
        + json.dumps(escaped, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="escaped its session identity"):
        import_codex_rollout(
            escaped_rollout,
            carrier_home=home,
            root=root,
            allowed_homes=allowed,
        )


def test_hook_integration_is_bounded_fail_open_and_does_not_echo_current_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    monkeypatch.setattr(hook_module, "render_runtime_context", lambda _event: "RUNTIME")
    first = handle_hook_event(
        _hook(name="UserPromptSubmit", prompt="第一条问题"),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_environ=environ,
        context_fabric_allowed_homes=allowed,
    )
    assert first["hookSpecificOutput"]["additionalContext"] == L0_CONTEXT + "\nRUNTIME"

    stopped = handle_hook_event(
        _hook(name="Stop", assistant="第一条回答"),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_environ=environ,
        context_fabric_allowed_homes=allowed,
    )
    assert stopped == {"continue": True}

    second_prompt = "继续刚才这个"
    second = handle_hook_event(
        _hook(name="UserPromptSubmit", turn=TURN_B, prompt=second_prompt),
        context_fabric_enabled=True,
        context_fabric_root=root,
        context_fabric_environ=environ,
        context_fabric_allowed_homes=allowed,
    )
    context = second["hookSpecificOutput"]["additionalContext"]
    assert context.startswith(L0_CONTEXT)
    assert "S CONTEXT FABRIC" in context
    assert "第一条问题" in context
    assert "第一条回答" in context
    assert second_prompt not in context
    assert len(context) < 10_000


def test_concurrent_hook_appends_leave_one_valid_chain(tmp_path: Path) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)

    def append(index: int) -> None:
        turn = f"turn-{index:03d}"
        result = capture_hook_event(
            _hook(name="UserPromptSubmit", turn=turn, prompt=f"并发消息 {index}"),
            root=root,
            environ=environ,
            allowed_homes=allowed,
        )
        assert result is not None

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(append, range(12)))
    assert verify_event_chain(root)["event_count"] == 12


def test_lifecycle_hooks_append_boundaries_without_injecting_or_blocking(
    tmp_path: Path,
) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    events = (
        {**_hook(name="SessionStart"), "source": "startup"},
        _hook(name="PreCompact"),
        _hook(name="PostCompact"),
        _hook(name="SessionEnd"),
    )
    for event in events:
        assert handle_hook_event(
            event,
            context_fabric_enabled=True,
            context_fabric_root=root,
            context_fabric_environ=environ,
            context_fabric_allowed_homes=allowed,
        ) == {"continue": True}
    assert store_inventory(root)["events"] == 4
    assert verify_event_chain(root)["event_count"] == 4


def test_snapshot_is_consistent_and_does_not_follow_later_source_appends(
    tmp_path: Path,
) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    capture_hook_event(
        _hook(name="UserPromptSubmit", prompt="快照前事件"),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    snapshot_root = tmp_path / "snapshot"
    snapshot = create_snapshot(snapshot_root, root=root)
    assert snapshot["event_count"] == 1
    assert len(snapshot["database_sha256"]) == 64
    assert verify_event_chain(snapshot_root)["event_count"] == 1

    capture_hook_event(
        _hook(name="Stop", assistant="快照后事件"),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    assert verify_event_chain(root)["event_count"] == 2
    assert verify_event_chain(snapshot_root)["event_count"] == 1


def test_denied_body_neither_creates_nor_reads_context(tmp_path: Path) -> None:
    home, allowed, _ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    captured, context = render_hook_context(
        _hook(name="UserPromptSubmit", prompt="should not mount"),
        root=root,
        environ={"CODEX_HOME": str(home.parent / ".codex-cleanroom")},
        allowed_homes=allowed,
    )
    assert captured is None
    assert context == ""
    assert store_inventory(root)["events"] == 0


def test_hot_tail_prefers_current_session_over_parallel_tui(tmp_path: Path) -> None:
    _, allowed, environ = _mount(tmp_path)
    root = tmp_path / "fabric"
    initialize_context_fabric(root)
    other_session = "019ff778-e326-7b91-9784-4fe809585e03"
    capture_hook_event(
        _hook(
            name="UserPromptSubmit",
            session=other_session,
            prompt="另一个并行 TUI 的局部活动",
        ),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )
    capture_hook_event(
        _hook(name="UserPromptSubmit", prompt="本窗口正在落地持续上下文"),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )

    _, context = render_hook_context(
        _hook(name="UserPromptSubmit", turn=TURN_B, prompt="继续落地"),
        root=root,
        environ=environ,
        allowed_homes=allowed,
    )

    assert "本窗口正在落地持续上下文" in context
    assert "另一个并行 TUI 的局部活动" not in context
