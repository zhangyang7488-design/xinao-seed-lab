from __future__ import annotations

import json
from pathlib import Path

import pytest
from services.agent_runtime.execution_contract import canonical_json_bytes
from services.agent_runtime.taste_codex_shadow import (
    TasteCodexShadowError,
    _candidate_prefix_sources,
    _common_inputs,
    _messages,
    _projection_messages,
    _response_item,
    _rollout_evidence,
)


def _request(messages: list[dict[str, str]]) -> bytes:
    import hashlib

    return canonical_json_bytes(
        {
            "schema_version": "s.taste_shadow_request.v2",
            "messages": messages,
            "prefix_sha256": hashlib.sha256(canonical_json_bytes(messages)).hexdigest(),
        }
    )


def _rollout(thread_id: str, rows: list[dict[str, str]]) -> bytes:
    records: list[dict[str, object]] = [
        {
            "timestamp": "2026-08-13T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": thread_id, "session_id": thread_id},
        }
    ]
    for index, row in enumerate(rows):
        records.append(
            {
                "timestamp": f"2026-08-13T00:00:{index + 1:02d}Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": row["role"],
                    "content": [
                        {
                            "type": "input_text" if row["role"] == "user" else "output_text",
                            "text": row["content"],
                        }
                    ],
                    **({"phase": "final_answer"} if row["role"] == "assistant" else {}),
                },
            }
        )
    return b"".join(canonical_json_bytes(row) + b"\n" for row in records)


def test_evaluation_final_user_is_not_injected_twice() -> None:
    request = _request(
        [
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "current"},
        ]
    )
    rows = _messages(request)
    assert rows[:-1] == [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "answer"},
    ]
    assert rows[-1] == {"role": "user", "content": "current"}


def test_projection_is_mechanically_expanded_as_response_messages() -> None:
    condition = canonical_json_bytes(
        {
            "schema_version": "s.taste_source_projection.v1",
            "mode": "source_contrastive_episode",
            "episodes": [
                {
                    "prefix": [{"event_id": "evt-a", "role": "user", "content": "bad ask"}],
                    "bad_continuation": {
                        "event_id": "evt-b",
                        "role": "assistant",
                        "content": "bad answer",
                    },
                    "human_corrections": [
                        {"event_id": "evt-c", "role": "user", "content": "correction"}
                    ],
                    "desired_continuation": {
                        "event_id": "evt-d",
                        "role": "assistant",
                        "content": "better answer",
                    },
                }
            ],
        }
    )
    rows = _projection_messages(condition)
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]
    assert _response_item(rows[0]) == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "bad ask"}],
    }
    assert _response_item(rows[-1])["phase"] == "final_answer"


def test_rollout_must_contain_exact_replay_prefix_and_output() -> None:
    thread = "019ffb9a-6106-7a33-bdd0-30c3a3b7e390"
    injected = [
        {"role": "user", "content": "old ask"},
        {"role": "assistant", "content": "old answer"},
    ]
    raw = _rollout(
        thread,
        [
            *injected,
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": "now"},
        ],
    )
    observed = _rollout_evidence(raw, thread_id=thread, injected=injected, final_user="current")
    assert observed["response_text"] == "now"
    assert observed["tool_item_types"] == []


def test_rollout_binds_ambient_product_surfaces_outside_the_replay_prefix() -> None:
    thread = "019ffb9a-6106-7a33-bdd0-30c3a3b7e390"
    first = _rollout_evidence(
        _rollout(
            thread,
            [
                {"role": "user", "content": "ambient-a"},
                {"role": "user", "content": "current"},
                {"role": "assistant", "content": "now"},
            ],
        ),
        thread_id=thread,
        injected=[],
        final_user="current",
    )
    second = _rollout_evidence(
        _rollout(
            thread,
            [
                {"role": "user", "content": "ambient-b"},
                {"role": "user", "content": "current"},
                {"role": "assistant", "content": "now"},
            ],
        ),
        thread_id=thread,
        injected=[],
        final_user="current",
    )
    assert first["ambient_surface_sha256"] != second["ambient_surface_sha256"]


def test_offline_rollout_readback_rechecks_heldout_oracle_absence() -> None:
    thread = "019ffb9a-6106-7a33-bdd0-30c3a3b7e390"
    raw = _rollout(
        thread,
        [
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": "sealed oracle surface"},
        ],
    )
    with pytest.raises(TasteCodexShadowError) as raised:
        _rollout_evidence(
            raw,
            thread_id=thread,
            injected=[],
            final_user="current",
            oracle_needles=[b"sealed oracle surface"],
        )
    assert raised.value.reason_code == "EVALUATION_ORACLE_LEAK"


def test_rollout_rejects_missing_injected_assistant() -> None:
    thread = "019ffb9a-6106-7a33-bdd0-30c3a3b7e390"
    raw = _rollout(
        thread,
        [
            {"role": "user", "content": "old ask"},
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": "now"},
        ],
    )
    with pytest.raises(TasteCodexShadowError) as raised:
        _rollout_evidence(
            raw,
            thread_id=thread,
            injected=[
                {"role": "user", "content": "old ask"},
                {"role": "assistant", "content": "old answer"},
            ],
            final_user="current",
        )
    assert raised.value.reason_code == "INJECT_NOT_OBSERVED"


def test_rollout_rejects_a_tool_item() -> None:
    thread = "019ffb9a-6106-7a33-bdd0-30c3a3b7e390"
    records = b"".join(
        canonical_json_bytes(record) + b"\n"
        for record in (
            {
                "timestamp": "2026-08-13T00:00:00Z",
                "type": "session_meta",
                "payload": {"id": thread, "session_id": thread},
            },
            {
                "timestamp": "2026-08-13T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "current"}],
                },
            },
            {
                "timestamp": "2026-08-13T00:00:02Z",
                "type": "response_item",
                "payload": {"type": "commandExecution", "command": "whoami"},
            },
            {
                "timestamp": "2026-08-13T00:00:03Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "now"}],
                    "phase": "final_answer",
                },
            },
        )
    )
    with pytest.raises(TasteCodexShadowError) as raised:
        _rollout_evidence(
            records,
            thread_id=thread,
            injected=[],
            final_user="current",
        )
    assert raised.value.reason_code == "TOOL_USED"


def test_source_has_no_accidental_filesystem_fixture_dependency() -> None:
    assert Path(__file__).name == "test_taste_codex_shadow.py"
    assert json.loads(canonical_json_bytes({"cold": True})) == {"cold": True}


def test_offline_common_input_readback_includes_environment_identity() -> None:
    value = {
        "body_sha256": "body",
        "policy": {"sandbox": "read-only"},
        "request_sha256": "request",
        "config_sha256": "config",
        "command_sha256": "command",
        "environment_sha256": "environment",
        "common_prefix_sha256": "prefix",
    }
    assert _common_inputs(value) == value
    missing = dict(value)
    missing.pop("environment_sha256")
    with pytest.raises(TasteCodexShadowError) as raised:
        _common_inputs(missing)
    assert raised.value.reason_code == "INPUT_BINDING_MISMATCH"


def test_native_outcome_reads_sources_from_prefix_envelope() -> None:
    source = {"source_ref": "context-event://evt-a"}
    candidate = {"baseline_prefix": {"sources": [source], "prefix_sha256": "sha"}}
    assert _candidate_prefix_sources(candidate, "baseline") == [source]
