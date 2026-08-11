from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from evals.situation_snapshot_lab import codex_exec_driver as driver


def _event_bytes(*events: dict[str, object]) -> bytes:
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode("utf-8")


def _successful_events(*, thread_id: str = "thread-first", text: str = "candidate") -> bytes:
    return _event_bytes(
        {"type": "thread.started", "thread_id": thread_id},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {"id": "message-1", "type": "agent_message"},
        },
        {
            "type": "item.completed",
            "item": {"id": "message-1", "type": "agent_message", "text": text},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
    )


def _make_config(tmp_path: Path, *, auth_text: str = '{"account":"lab"}') -> driver.CodexExecConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    home = tmp_path / "codex-home"
    home.mkdir()
    auth_source = tmp_path / "caller-auth.json"
    auth_source.write_text(auth_text, encoding="utf-8")
    (home / "auth.json").symlink_to(auth_source)
    return driver.CodexExecConfig(
        codex_executable="fake-codex.exe",
        codex_home=home,
        cwd=cwd,
        model="gpt-lab-explicit",
        auth_target=auth_source,
        allowed_lab_root=tmp_path,
        disabled_features=("hooks", "plugins", "memories"),
        timeout_seconds=23,
    )


def test_first_invocation_uses_argument_list_and_explicit_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []
    removed_environment_keys = [
        "CODEX_API_KEY",
        "CODEX_MANAGED_BY_NPM",
        "CODEX_MANAGED_PACKAGE_ROOT",
        "CODEX_THREAD_ID",
        "OPENAI_API_KEY",
    ]
    for key in removed_environment_keys:
        monkeypatch.setenv(key, f"inherited-{key.lower()}")
    monkeypatch.setenv("CODEX_HOME", "inherited-home-must-be-overridden")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, _successful_events(), b"progress")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.invoke_first(config=config, prompt="interpret this sealed case")

    assert result.ok is True
    assert result.final_agent_text == "candidate"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [
        "fake-codex.exe",
        "exec",
        "--json",
        "--strict-config",
        "-m",
        "gpt-lab-explicit",
        "-c",
        'sandbox_mode="read-only"',
        "-c",
        'approval_policy="never"',
        "-c",
        'model_reasoning_effort="max"',
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "hooks",
        "--disable",
        "plugins",
        "--disable",
        "memories",
        "--sandbox",
        "read-only",
        "-C",
        str(config.cwd),
        "-",
    ]
    assert kwargs["cwd"] == str(config.cwd)
    assert kwargs["input"] == b"interpret this sealed case"
    assert kwargs["env"]["CODEX_HOME"] == str(config.codex_home)  # type: ignore[index]
    assert all(key not in kwargs["env"] for key in removed_environment_keys)  # type: ignore[operator]
    assert kwargs["check"] is False
    assert "shell" not in kwargs
    assert "interpret this sealed case" not in argv

    receipt = result.receipt
    assert receipt["raw_jsonl_sha256"] == hashlib.sha256(result.raw_jsonl).hexdigest()
    assert receipt["authority"] is False
    assert receipt["production_registered"] is False
    assert receipt["driver_scope"] == "unregistered_candidate_transport"
    assert receipt["model_output_is_runtime_truth"] is False
    declared = receipt["declared_invocation"]
    assert declared["sandbox_mode"] == "read-only"  # type: ignore[index]
    assert declared["approval_policy"] == "never"  # type: ignore[index]
    assert declared["model_reasoning_effort"] == "max"  # type: ignore[index]
    assert declared["allowed_lab_root"] == str(config.allowed_lab_root)  # type: ignore[index]
    environment_contract = declared["child_environment_contract"]  # type: ignore[index]
    assert environment_contract["removed_inherited_keys"] == tuple(  # type: ignore[index]
        removed_environment_keys
    )
    assert environment_contract["codex_home_overridden"] is True  # type: ignore[index]
    entrypoint = declared["codex_entrypoint_contract"]  # type: ignore[index]
    assert entrypoint["kind"] == "direct_native_executable"  # type: ignore[index]
    assert entrypoint["npm_wrapper_accepted"] is False  # type: ignore[index]
    assert entrypoint["identity_assurance"] == (  # type: ignore[index]
        "caller_supplied_path_contract_only"
    )
    boundary = receipt["path_boundary_detection"]
    assert boundary["assurance"] == "resolved_path_containment_only"  # type: ignore[index]
    assert boundary["contained"] is True  # type: ignore[index]
    assert boundary["isolation_established"] is False  # type: ignore[index]
    with pytest.raises(TypeError):
        receipt["status"] = "rewritten"  # type: ignore[index]
    with pytest.raises(TypeError):
        receipt["declared_invocation"]["requested_model"] = "rewritten"  # type: ignore[index]


def test_prompt_accepts_multiline_utf8_but_rejects_nul(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    captured_inputs: list[bytes] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured_inputs.append(kwargs["input"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(argv, 0, _successful_events(), b"")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    prompt = "第一行：解释当前关系\nsecond line\twith tab\nemoji: 🧭"
    result = driver.invoke_first(config=config, prompt=prompt)

    assert result.ok is True
    assert captured_inputs == [prompt.encode("utf-8")]
    with pytest.raises(driver.CodexExecDriverError, match="NUL"):
        driver.invoke_first(config=config, prompt="valid prefix\x00hidden suffix")
    assert len(captured_inputs) == 1


def test_resume_invocation_uses_resume_parser_flags_and_subprocess_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            _successful_events(thread_id="thread-resume", text="continued candidate"),
            b"",
        )

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.invoke_resume(
        config=config,
        thread_id="thread-resume",
        prompt="continue this sealed case",
    )

    assert result.ok is True
    argv, kwargs = calls[0]
    assert argv == [
        "fake-codex.exe",
        "exec",
        "resume",
        "--json",
        "--strict-config",
        "-m",
        "gpt-lab-explicit",
        "-c",
        'sandbox_mode="read-only"',
        "-c",
        'approval_policy="never"',
        "-c",
        'model_reasoning_effort="max"',
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "hooks",
        "--disable",
        "plugins",
        "--disable",
        "memories",
        "thread-resume",
        "-",
    ]
    assert kwargs["cwd"] == str(config.cwd)
    declared = result.receipt["declared_invocation"]
    assert declared["mode"] == "resume"  # type: ignore[index]
    assert declared["requested_thread_id"] == "thread-resume"  # type: ignore[index]
    assert declared["sandbox_mode"] == "read-only"  # type: ignore[index]
    assert declared["approval_policy"] == "never"  # type: ignore[index]
    assert declared["model_reasoning_effort"] == "max"  # type: ignore[index]


def test_resume_observed_thread_must_equal_requested_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            argv,
            0,
            _successful_events(thread_id="thread-observed"),
            b"",
        )

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.invoke_resume(
        config=config,
        thread_id="thread-requested",
        prompt="resume exact thread only",
    )

    assert result.ok is False
    assert result.receipt["status"] == "thread_identity_mismatch"
    trajectory = result.receipt["trajectory_observation"]
    assert trajectory["thread_id"] == "thread-observed"  # type: ignore[index]
    assert trajectory["thread_identity_matches_request"] is False  # type: ignore[index]


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("sandbox_mode", "bypass"),
        ("approval_policy", "on-failure"),
        ("model_reasoning_effort", "unbounded"),
    ],
)
def test_permission_and_reasoning_identity_rejects_unsupported_values(
    tmp_path: Path,
    field_name: str,
    invalid_value: str,
) -> None:
    config = _make_config(tmp_path)

    with pytest.raises(driver.CodexExecDriverError, match=field_name):
        replace(config, **{field_name: invalid_value})


def test_default_disabled_features_include_live_0147_lab_surfaces(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    defaulted = replace(config, disabled_features=driver.DEFAULT_DISABLED_FEATURES)
    required = {"goals", "skill_search", "skill_mcp_dependency_install"}

    assert required.issubset(defaulted.disabled_features)
    argv = driver.build_first_argv(defaulted)
    disabled = {argv[index + 1] for index, value in enumerate(argv) if value == "--disable"}
    assert required.issubset(disabled)


def test_npm_wrapper_is_not_accepted_as_direct_native_entrypoint(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    with pytest.raises(driver.CodexExecDriverError, match="direct native"):
        replace(config, codex_executable="codex.ps1")


def test_jsonl_parser_extracts_turn_item_tool_and_final_agent_text() -> None:
    raw = _event_bytes(
        {"type": "thread.started", "thread_id": "thread-trace"},
        {"type": "turn.started", "turn_id": "turn-1"},
        {
            "type": "item.started",
            "item": {
                "id": "tool-1",
                "type": "command_execution",
                "command": "do-not-copy-command-into-receipt",
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "tool-1", "type": "command_execution", "status": "completed"},
        },
        {
            "type": "item.started",
            "item": {"id": "message-1", "type": "agent_message"},
        },
        {
            "type": "item.completed",
            "item": {"id": "message-1", "type": "agent_message", "text": "final candidate"},
        },
        {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 3}},
    )

    parsed = driver.parse_codex_jsonl(raw)

    assert parsed.thread_id == "thread-trace"
    assert parsed.final_agent_text == "final candidate"
    assert parsed.turn_completed is True
    assert parsed.turn_failed is False
    assert len(parsed.turn_trace) == 2
    assert [row["event_type"] for row in parsed.item_trace] == [
        "item.started",
        "item.completed",
        "item.started",
        "item.completed",
    ]
    assert [row["event_type"] for row in parsed.tool_trace] == [
        "item.started",
        "item.completed",
    ]
    assert all(row["item_id"] == "tool-1" for row in parsed.tool_trace)
    assert parsed.terminal_usage == {"input_tokens": 12, "output_tokens": 3}


def test_jsonl_parser_accepts_exact_0147_completion_only_agent_message_shape() -> None:
    raw = _event_bytes(
        {"type": "thread.started", "thread_id": "thread-live-shape"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "item-live-shape", "type": "agent_message", "text": "probe_ok"},
        },
        {"type": "turn.completed"},
    )

    parsed = driver.parse_codex_jsonl(raw)

    assert parsed.thread_id == "thread-live-shape"
    assert parsed.final_agent_text == "probe_ok"
    assert [row["event_type"] for row in parsed.item_trace] == ["item.completed"]
    assert parsed.turn_completed is True


@pytest.mark.parametrize(
    "raw,match",
    [
        (b"not-json\n", "not valid JSON"),
        (_event_bytes({"type": "future.event"}), "unsupported event type"),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-bad"},
                {"type": "turn.started"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "x"}},
            ),
            "requires an id",
        ),
    ],
)
def test_bad_event_is_rejected(raw: bytes, match: str) -> None:
    with pytest.raises(driver.CodexEventError, match=match):
        driver.parse_codex_jsonl(raw)


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.completed"},
            ),
            "requires turn.started",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
            ),
            "exactly one terminal turn",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {"type": "turn.completed"},
                {"type": "turn.failed"},
            ),
            "exactly one terminal turn",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-1",
                        "type": "agent_message",
                        "text": "first completion",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-1",
                        "type": "agent_message",
                        "text": "duplicate completion",
                    },
                },
                {"type": "turn.completed"},
            ),
            "cannot follow item.completed",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-1",
                        "type": "agent_message",
                        "text": "completion",
                    },
                },
                {
                    "type": "item.updated",
                    "item": {"id": "message-1", "type": "agent_message"},
                },
                {"type": "turn.completed"},
            ),
            "cannot follow item.completed",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-1",
                        "type": "agent_message",
                        "text": "completion",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {"id": "message-1", "type": "reasoning"},
                },
                {"type": "turn.completed"},
            ),
            "type changed",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {
                    "type": "item.started",
                    "item": {"id": "message-1", "type": "agent_message"},
                },
                {"type": "turn.completed"},
            ),
            "incomplete item lifecycles",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {"type": "turn.completed"},
                {
                    "type": "item.started",
                    "item": {"id": "late-item", "type": "reasoning"},
                },
            ),
            "after terminal turn",
        ),
        (
            _event_bytes(
                {"type": "thread.started", "thread_id": "thread-order"},
                {"type": "turn.started"},
                {"type": "turn.started"},
                {"type": "turn.completed"},
            ),
            "exactly once",
        ),
    ],
)
def test_jsonl_parser_rejects_invalid_single_turn_lifecycle(raw: bytes, match: str) -> None:
    with pytest.raises(driver.CodexEventError, match=match):
        driver.parse_codex_jsonl(raw)


def test_invoked_bad_event_still_returns_immutable_hashed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    raw = b'{"type":"thread.started","thread_id":"thread-bad"}\nnot-json\n'

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 0, raw, b"secret stderr is not copied")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.invoke_first(config=config, prompt="sealed bad event case")

    assert result.ok is False
    assert result.parsed is None
    assert result.receipt["status"] == "invalid_jsonl"
    assert result.receipt["raw_jsonl_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result.receipt["trajectory_observation"]["parse_error"] == (  # type: ignore[index]
        "invalid_codex_event_stream"
    )


def test_auth_link_must_exist_and_resolve_to_declared_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path)
    (config.codex_home / "auth.json").unlink()
    (config.codex_home / "auth.json").write_text("not a link", encoding="utf-8")
    called = False

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess(argv, 0, _successful_events(), b"")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    with pytest.raises(driver.AuthLinkError, match="symbolic link"):
        driver.invoke_first(config=config, prompt="must not invoke")
    assert called is False


@pytest.mark.parametrize("escaped_field", ["codex_home", "cwd"])
def test_allowed_lab_root_rejects_shared_or_production_runtime_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    escaped_field: str,
) -> None:
    allowed_root = tmp_path / "declared-lab-root"
    config = _make_config(allowed_root)
    outside = tmp_path / "shared-production-path"
    outside.mkdir()
    escaped = replace(config, **{escaped_field: outside})
    called = False

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess(argv, 0, _successful_events(), b"")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    with pytest.raises(driver.LabPathBoundaryError, match=escaped_field):
        driver.invoke_first(config=escaped, prompt="must remain under declared lab root")
    assert called is False


def test_auth_source_hash_and_link_are_verified_unchanged_after_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_config(tmp_path, auth_text="auth-before")

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        config.auth_target.write_text("auth-after", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, _successful_events(), b"")

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.invoke_first(config=config, prompt="detect source drift")

    auth = result.receipt["auth_pre_post_detection"]
    assert result.ok is False
    assert result.receipt["status"] == "auth_integrity_failed"
    assert auth["link_verified_before"] is True  # type: ignore[index]
    assert auth["link_verified_after"] is True  # type: ignore[index]
    assert auth["unchanged"] is False  # type: ignore[index]
    assert auth["source_sha256_before"] != auth["source_sha256_after"]  # type: ignore[index]
    assert auth["assurance"] == "pre_post_detection_only"  # type: ignore[index]
    assert auth["credential_model"] == "shared_live_credential_link"  # type: ignore[index]
    assert auth["continuous_monitoring"] is False  # type: ignore[index]
    assert auth["mutation_prevention"] is False  # type: ignore[index]


def test_auth_model_stderr_and_prompt_secrets_do_not_enter_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-super-secret-receipt-canary"
    stderr_canary = "stderr-payload-canary-7319"
    config = _make_config(tmp_path, auth_text=json.dumps({"access_token": secret}))
    raw = _successful_events(text=f"candidate repeated {secret}")

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 0, raw, f"{stderr_canary} {secret}".encode())

    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    result = driver.invoke_first(config=config, prompt=f"prompt {secret}")
    serialized = json.dumps(result.receipt_dict(), sort_keys=True)

    assert result.ok is True
    assert result.final_agent_text == f"candidate repeated {secret}"
    assert secret not in serialized
    assert "candidate repeated" not in serialized
    assert stderr_canary not in serialized
    assert secret not in repr(result)
    assert "candidate repeated" not in repr(result)
    assert result.receipt["candidate_model_output"]["classification"] == (  # type: ignore[index]
        "candidate_only_not_runtime_truth"
    )
