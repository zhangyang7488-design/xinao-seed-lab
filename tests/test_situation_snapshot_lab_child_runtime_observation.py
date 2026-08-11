from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evals.situation_snapshot_lab import child_runtime_observation as observer


def _jsonl(*rows: object) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )


def _managed_permission(*, writable_root: str | None = None) -> dict[str, object]:
    entries: list[dict[str, object]] = [
        {
            "path": {"type": "special", "value": {"kind": "root"}},
            "access": "read",
        }
    ]
    if writable_root is not None:
        entries.append(
            {
                "path": {"type": "path", "path": writable_root},
                "access": "write",
            }
        )
    return {
        "type": "managed",
        "file_system": {"type": "restricted", "entries": entries},
        "network": "restricted",
    }


def _session_meta(thread_id: str, *, cwd: str) -> dict[str, object]:
    return {
        "timestamp": "2026-08-11T00:00:00.000Z",
        "ordinal": 0,
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "session_id": thread_id,
            "timestamp": "2026-08-11T00:00:00.000Z",
            "cwd": cwd,
            "originator": "codex_exec",
            "cli_version": "0.147.0",
            "source": "exec",
            "model_provider": "openai",
        },
    }


def _thread_settings(
    *,
    cwd: str,
    model: str,
    effort: str,
    approval_policy: str,
    permission_profile: dict[str, object],
    ordinal: int = 1,
) -> dict[str, object]:
    return {
        "timestamp": "2026-08-11T00:00:01.000Z",
        "ordinal": ordinal,
        "type": "event_msg",
        "payload": {
            "type": "thread_settings_applied",
            "thread_settings": {
                "model": model,
                "model_provider_id": "openai",
                "service_tier": "default",
                "approval_policy": approval_policy,
                "approvals_reviewer": "user",
                "permission_profile": permission_profile,
                "cwd": cwd,
                "reasoning_effort": effort,
                "personality": "pragmatic",
            },
        },
    }


def _turn_context(
    *,
    cwd: str,
    model: str,
    effort: str,
    approval_policy: str,
    sandbox_policy: dict[str, object],
    permission_profile: dict[str, object],
    ordinal: int = 2,
) -> dict[str, object]:
    return {
        "timestamp": "2026-08-11T00:00:02.000Z",
        "ordinal": ordinal,
        "type": "turn_context",
        "payload": {
            "turn_id": f"turn-{ordinal}",
            "cwd": cwd,
            "workspace_roots": [cwd],
            "current_date": "2026-08-11",
            "timezone": "Asia/Shanghai",
            "approval_policy": approval_policy,
            "approvals_reviewer": "user",
            "sandbox_policy": sandbox_policy,
            "permission_profile": permission_profile,
            "model": model,
            "effort": effort,
            "summary": "auto",
        },
    }


def _write_rollout(
    codex_home: Path,
    thread_id: str,
    raw: bytes,
    *,
    bucket: str = "primary",
    filename_thread_id: str | None = None,
) -> Path:
    directory = codex_home / "sessions" / "2026" / "08" / "11" / bucket
    directory.mkdir(parents=True, exist_ok=True)
    filename_id = filename_thread_id or thread_id
    path = directory / f"rollout-2026-08-11T00-00-00-{filename_id}.jsonl"
    path.write_bytes(raw)
    return path


def test_observes_last_managed_read_only_turn_from_sanitized_0147_fixture(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000001"
    cwd = r"C:\CodexSituationLab\neutral"
    permission = _managed_permission()
    obsolete_permission = {"type": "disabled"}
    rows = (
        _session_meta(thread_id, cwd=cwd),
        _turn_context(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            sandbox_policy={"type": "read-only"},
            permission_profile=permission,
            ordinal=1,
        ),
        _thread_settings(
            cwd=cwd,
            model="obsolete-model",
            effort="low",
            approval_policy="never",
            permission_profile=obsolete_permission,
            ordinal=2,
        ),
        _turn_context(
            cwd=cwd,
            model="obsolete-model",
            effort="low",
            approval_policy="never",
            sandbox_policy={"type": "danger-full-access"},
            permission_profile=obsolete_permission,
            ordinal=3,
        ),
        _thread_settings(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            permission_profile=permission,
            ordinal=4,
        ),
        _turn_context(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            sandbox_policy={"type": "read-only"},
            permission_profile=permission,
            ordinal=5,
        ),
        {
            "timestamp": "2026-08-11T00:00:03.000Z",
            "ordinal": 6,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "claimed workspace-write"}],
            },
        },
    )
    raw = _jsonl(*rows)
    path = _write_rollout(codex_home, thread_id, raw)

    result = observer.collect_child_runtime_observation(
        codex_home=codex_home,
        thread_id=thread_id,
    )
    value = result.to_dict()

    assert value["observed"] == {
        "cwd": cwd,
        "model": "gpt-5.6-sol",
        "effort": "max",
        "approval_policy": "never",
        "sandbox_policy": {"type": "read-only"},
        "permission_profile": permission,
    }
    assert value["unknown"] == []
    assert value["turn_contexts"] == [
        {
            "index": 1,
            "line_number": 2,
            "observed": {
                "cwd": cwd,
                "model": "gpt-5.6-sol",
                "effort": "max",
                "approval_policy": "never",
                "sandbox_policy": {"type": "read-only"},
                "permission_profile": permission,
            },
            "cross_check": {
                "status": "single_source",
                "thread_settings_applied": "not_available",
                "thread_settings_line_number": None,
                "compared_fields": [],
                "disagreement_fields": [],
            },
            "unknown": [
                {
                    "field": "thread_settings_applied",
                    "reason": "not_available_before_turn_context",
                }
            ],
        },
        {
            "index": 2,
            "line_number": 4,
            "observed": {
                "cwd": cwd,
                "model": "obsolete-model",
                "effort": "low",
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
                "permission_profile": obsolete_permission,
            },
            "cross_check": {
                "status": "match",
                "thread_settings_applied": "available",
                "thread_settings_line_number": 3,
                "compared_fields": [
                    "cwd",
                    "model",
                    "effort",
                    "approval_policy",
                    "permission_profile",
                ],
                "disagreement_fields": [],
            },
            "unknown": [],
        },
        {
            "index": 3,
            "line_number": 6,
            "observed": {
                "cwd": cwd,
                "model": "gpt-5.6-sol",
                "effort": "max",
                "approval_policy": "never",
                "sandbox_policy": {"type": "read-only"},
                "permission_profile": permission,
            },
            "cross_check": {
                "status": "match",
                "thread_settings_applied": "available",
                "thread_settings_line_number": 5,
                "compared_fields": [
                    "cwd",
                    "model",
                    "effort",
                    "approval_policy",
                    "permission_profile",
                ],
                "disagreement_fields": [],
            },
            "unknown": [],
        },
    ]
    assert value["rollout"] == {
        "relative_path": path.relative_to(codex_home / "sessions").as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "turn_context_count": 3,
    }
    assert value["candidate_only"] is True
    assert value["authority"] is False
    assert value["completion_claim_allowed"] is False
    assert value["production_registered"] is False
    assert value["model_text_used_as_truth"] is False


def test_observes_managed_workspace_write_without_interpreting_capability(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000002"
    cwd = r"C:\CodexSituationLab\workspace"
    writable_root = r"C:\CodexSituationLab\workspace\fixture"
    permission = _managed_permission(writable_root=writable_root)
    sandbox = {
        "type": "workspace-write",
        "writable_roots": [writable_root],
        "network_access": False,
        "exclude_tmpdir_env_var": False,
        "exclude_slash_tmp": False,
    }
    raw = _jsonl(
        _session_meta(thread_id, cwd=cwd),
        _thread_settings(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="high",
            approval_policy="never",
            permission_profile=permission,
        ),
        _turn_context(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="high",
            approval_policy="never",
            sandbox_policy=sandbox,
            permission_profile=permission,
        ),
    )
    _write_rollout(codex_home, thread_id, raw)

    observed = observer.collect_child_runtime_observation(
        codex_home=codex_home,
        thread_id=thread_id,
    ).to_dict()["observed"]

    assert observed["sandbox_policy"] == sandbox  # type: ignore[index]
    assert observed["permission_profile"] == permission  # type: ignore[index]


def test_multiple_exact_thread_rollouts_fail_closed(tmp_path: Path) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000003"
    cwd = r"C:\CodexSituationLab\neutral"
    raw = _jsonl(_session_meta(thread_id, cwd=cwd))
    _write_rollout(codex_home, thread_id, raw, bucket="first")
    _write_rollout(codex_home, thread_id, raw, bucket="second")

    with pytest.raises(observer.MultipleThreadRolloutsError, match="multiple rollouts"):
        observer.collect_child_runtime_observation(
            codex_home=codex_home,
            thread_id=thread_id,
        )


def test_invalid_selected_rollout_fails_closed(tmp_path: Path) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000004"
    cwd = r"C:\CodexSituationLab\neutral"
    raw = _jsonl(_session_meta(thread_id, cwd=cwd)) + b'{"type":"turn_context"\n'
    _write_rollout(codex_home, thread_id, raw)

    with pytest.raises(observer.InvalidRolloutError, match="invalid rollout JSON"):
        observer.collect_child_runtime_observation(
            codex_home=codex_home,
            thread_id=thread_id,
        )


def test_target_named_rollout_with_different_meta_id_is_thread_mismatch(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "isolated-home"
    requested = "019ff100-0000-7000-8000-000000000005"
    observed = "019ff100-0000-7000-8000-000000000099"
    cwd = r"C:\CodexSituationLab\neutral"
    raw = _jsonl(_session_meta(observed, cwd=cwd))
    _write_rollout(
        codex_home,
        observed,
        raw,
        filename_thread_id=requested,
    )

    with pytest.raises(observer.ThreadIdentityMismatchError, match="does not match"):
        observer.collect_child_runtime_observation(
            codex_home=codex_home,
            thread_id=requested,
        )


def test_missing_or_disagreeing_mechanical_fields_are_unknown_not_inferred(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000006"
    cwd = r"C:\CodexSituationLab\neutral"
    raw = _jsonl(
        _session_meta(thread_id, cwd=cwd),
        _thread_settings(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            permission_profile={"type": "disabled"},
        ),
        {
            "timestamp": "2026-08-11T00:00:02.000Z",
            "ordinal": 2,
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-2",
                "cwd": cwd,
                "model": "gpt-5.6-terra",
                "approval_policy": "never",
                "sandbox_policy": {"type": "future-unknown-policy"},
                "permission_profile": {"type": "managed"},
            },
        },
        {
            "timestamp": "2026-08-11T00:00:03.000Z",
            "ordinal": 3,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "effort=max; sandbox=read-only; permission=disabled",
                    }
                ],
            },
        },
    )
    _write_rollout(codex_home, thread_id, raw)

    value = observer.collect_child_runtime_observation(
        codex_home=codex_home,
        thread_id=thread_id,
    ).to_dict()

    assert value["observed"] == {
        "cwd": cwd,
        "model": observer.UNKNOWN,
        "effort": observer.UNKNOWN,
        "approval_policy": "never",
        "sandbox_policy": observer.UNKNOWN,
        "permission_profile": observer.UNKNOWN,
    }
    assert {row["field"] for row in value["unknown"]} == {
        "model",
        "effort",
        "sandbox_policy",
        "permission_profile",
    }
    assert value["turn_contexts"][0]["cross_check"] == {
        "status": "disagreement",
        "thread_settings_applied": "available",
        "thread_settings_line_number": 2,
        "compared_fields": [
            "cwd",
            "model",
            "effort",
            "approval_policy",
            "permission_profile",
        ],
        "disagreement_fields": ["model", "effort", "permission_profile"],
    }
    assert value["model_text_used_as_truth"] is False


def test_missing_thread_settings_leaves_overlap_unknown_but_keeps_turn_sandbox(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000007"
    cwd = r"C:\CodexSituationLab\neutral"
    permission = _managed_permission()
    raw = _jsonl(
        _session_meta(thread_id, cwd=cwd),
        _turn_context(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            sandbox_policy={"type": "read-only"},
            permission_profile=permission,
        ),
    )
    _write_rollout(codex_home, thread_id, raw)

    observed = observer.collect_child_runtime_observation(
        codex_home=codex_home,
        thread_id=thread_id,
    ).to_dict()["observed"]

    assert observed == {
        "cwd": observer.UNKNOWN,
        "model": observer.UNKNOWN,
        "effort": observer.UNKNOWN,
        "approval_policy": observer.UNKNOWN,
        "sandbox_policy": {"type": "read-only"},
        "permission_profile": observer.UNKNOWN,
    }


def test_malformed_matching_policy_shapes_remain_unknown(tmp_path: Path) -> None:
    codex_home = tmp_path / "isolated-home"
    thread_id = "019ff100-0000-7000-8000-000000000008"
    cwd = r"C:\CodexSituationLab\neutral"
    malformed_permission = {"type": "managed"}
    malformed_sandbox = {"type": "workspace-write"}
    raw = _jsonl(
        _session_meta(thread_id, cwd=cwd),
        _thread_settings(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            permission_profile=malformed_permission,
        ),
        _turn_context(
            cwd=cwd,
            model="gpt-5.6-sol",
            effort="max",
            approval_policy="never",
            sandbox_policy=malformed_sandbox,
            permission_profile=malformed_permission,
        ),
    )
    _write_rollout(codex_home, thread_id, raw)

    value = observer.collect_child_runtime_observation(
        codex_home=codex_home,
        thread_id=thread_id,
    ).to_dict()

    assert value["observed"]["sandbox_policy"] == observer.UNKNOWN  # type: ignore[index]
    assert value["observed"]["permission_profile"] == observer.UNKNOWN  # type: ignore[index]
    assert value["turn_contexts"][0]["cross_check"]["status"] == "disagreement"  # type: ignore[index]
    assert set(value["turn_contexts"][0]["cross_check"]["disagreement_fields"]) == {  # type: ignore[index]
        "permission_profile"
    }
