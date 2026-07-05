from services.codex_activator import codex_activator


def test_choose_target_accepts_codex_s_without_legacy_fallback() -> None:
    selection, blocker = codex_activator.choose_target({"target": "codex-s"})

    assert blocker == ""
    assert selection == {
        "original_target": "codex-s",
        "effective_target": "codex-s",
        "fallback_reason": "",
    }


def test_choose_target_keeps_blank_legacy_default_to_codex_a() -> None:
    selection, blocker = codex_activator.choose_target({})

    assert blocker == ""
    assert selection["effective_target"] == "codex-a"
    assert selection["fallback_reason"] == "legacy_hardmode_codex_a_default"


def test_choose_target_rejects_unknown_target() -> None:
    selection, blocker = codex_activator.choose_target({"target": "codex-z"})

    assert selection is None
    assert blocker == "CODEX_ACTIVATOR_UNKNOWN_TARGET"


def test_classify_codex_usage_limit_from_jsonl(tmp_path) -> None:
    jsonl = tmp_path / "codex-events.jsonl"
    jsonl.write_text(
        '{"type":"error","message":"You\\u0027ve hit your usage limit. try again at 2:16 AM."}\n',
        encoding="utf-8",
    )

    classification = codex_activator.classify_codex_failure({"jsonl": jsonl})

    assert classification["named_blocker"] == "CODEX_USAGE_LIMIT_RETRY_AFTER"
    assert classification["retryable"] is True
    assert classification["external_condition"] is True
    assert classification["retry_after_text"] == "2:16 AM"


def test_codex_a_intent_route_defaults_to_codex_s_transport_compat() -> None:
    payload = codex_activator.normalize_compat_ingress_payload(
        "/codex-a/intent",
        {"prompt": "hello"},
    )

    assert payload["target"] == "codex-s"
    assert payload["codex_a_path_is_transport_compat_label_not_codex_a_identity"] is True
    assert str(payload["workspace_hint"]).endswith(r"XINAO_RESEARCH_WORKSPACES\S")


def test_observation_snapshot_reads_assignment_dag(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "runtime"
    assignment_dir = runtime / "state" / "worker_assignment"
    assignment_dir.mkdir(parents=True)
    (assignment_dir / "task-1.json").write_text(
        '{"assignment_dag":{"next_ready_node_id":"node-2"},"named_blocker":"none"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_activator, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(codex_activator, "RESULT_ROOT", runtime / "state" / "codex_results")

    snapshot = codex_activator.build_observation_snapshot("task-1")

    assert snapshot["ok"] is True
    assert snapshot["assignment_dag"]["next_ready_node_id"] == "node-2"
    assert snapshot["resolved_blocker_cn"] == ""
