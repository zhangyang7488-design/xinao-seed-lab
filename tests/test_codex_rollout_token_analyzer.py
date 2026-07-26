from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from services.agent_runtime.codex_rollout_token_analyzer import (
    ANALYSIS_SCHEMA_VERSION,
    CodexRolloutAnalysisError,
    analyze_codex_rollout,
)


def _usage(total: int, *, cached: int = 0, reasoning: int = 1) -> dict[str, int]:
    output = 0 if total == 0 else max(1, total // 10)
    input_tokens = total - output
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": min(cached, input_tokens),
        "cache_write_input_tokens": 0,
        "output_tokens": output,
        "reasoning_output_tokens": min(reasoning, output),
        "total_tokens": total,
    }


def _token(total: int, last: int, *, cached: int = 0) -> dict[str, object]:
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": _usage(total, cached=cached),
                "last_token_usage": _usage(last),
                "model_context_window": 258_400,
            },
            "rate_limits": {"primary": {"used_percent": 3}},
        },
    }


def _write_rollout(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
        newline="\n",
    )


def _base_records() -> list[dict[str, object]]:
    return [
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-1"},
        },
        _token(100, 100),
        {
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "turn-1"},
        },
    ]


def test_cumulative_snapshots_are_differenced_and_duplicates_are_not_spend(
    tmp_path: Path,
) -> None:
    rollout = tmp_path / "rollout.jsonl"
    records = _base_records()
    records.insert(2, _token(160, 60, cached=20))
    records.insert(3, _token(160, 7, cached=20))
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)

    assert analysis["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert analysis["tokens"]["charged_spend"]["total_tokens"] == 160
    assert analysis["tokens"]["model_rounds_by_unique_counter_advance"] == 2
    assert analysis["tokens"]["duplicate_cumulative_snapshots"] == 1
    assert analysis["tokens"]["reported_last_usage_sum_diagnostic_only"]["total_tokens"] == 167
    assert analysis["tokens"]["reported_last_minus_charged_delta"]["total_tokens"] == 7


def test_copied_prefix_uses_baseline_without_counting_prefix_rounds(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    records = [
        {"type": "session_meta", "payload": {}},
        _token(500, 50),
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-live"},
        },
        _token(540, 40),
        {
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "turn-live"},
        },
    ]
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)

    assert analysis["scope"]["excluded_prefix_records"] == 2
    assert analysis["tokens"]["charged_spend"]["total_tokens"] == 40
    assert analysis["boundaries"]["tasks"][0]["token_spend"]["total_tokens"] == 40


def test_first_zero_last_usage_falls_back_to_total(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    first = _token(100, 1)
    first["payload"]["info"]["last_token_usage"] = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }
    _write_rollout(
        rollout,
        [
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            },
            first,
        ],
    )

    analysis = analyze_codex_rollout(rollout)

    assert analysis["tokens"]["charged_spend"]["total_tokens"] == 100
    assert analysis["tokens"]["checkpoints"][0]["basis"] == "first_total_fallback_last_was_zero"


def test_component_reclassification_without_total_advance_fails_closed(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    reclassified = _token(100, 0)
    reclassified["payload"]["info"]["total_token_usage"] = {
        "input_tokens": 91,
        "cached_input_tokens": 10,
        "cache_write_input_tokens": 0,
        "output_tokens": 9,
        "reasoning_output_tokens": 1,
        "total_tokens": 100,
    }
    _write_rollout(
        rollout,
        [
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            },
            _token(100, 100),
            reclassified,
        ],
    )

    with pytest.raises(CodexRolloutAnalysisError, match="without a total_tokens advance"):
        analyze_codex_rollout(rollout)


@pytest.mark.parametrize("bad_value", ["100", 100.5, True])
def test_noninteger_usage_values_fail_closed(tmp_path: Path, bad_value: object) -> None:
    rollout = tmp_path / "rollout.jsonl"
    token = _token(100, 100)
    token["payload"]["info"]["total_token_usage"]["input_tokens"] = bad_value
    _write_rollout(
        rollout,
        [
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn-1"},
            },
            token,
        ],
    )

    with pytest.raises(CodexRolloutAnalysisError, match="must be an integer"):
        analyze_codex_rollout(rollout)


def test_classifies_batching_waits_repeated_inputs_and_output_chars(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    batch = "const r = await Promise.all([tools.exec_command({}), tools.wait({})]);"
    records = [
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-1"},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "a",
                "input": batch,
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "a",
                "output": [{"type": "input_text", "text": "12345"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "b",
                "input": batch,
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "c",
                "input": "await tools['wait']({cell_id: 'x'});",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "wait",
                "call_id": "d",
                "input": "{}",
            },
        },
        _token(100, 100),
    ]
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)
    tools = analysis["tools"]

    assert tools["code_mode_exec_cells"] == 3
    assert tools["multi_nested_call_cells"] == 2
    assert tools["promise_batched_multi_call_cells"] == 2
    assert len(tools["wait_only_exec_cells"]) == 1
    assert tools["direct_wait_calls"] == [{"line": 6, "name": "wait"}]
    assert tools["repeated_identical_inputs"][0]["count"] == 2
    assert tools["output_text_chars"]["by_tool"]["exec"]["sum"] == 5


def test_usage_between_tasks_is_explicitly_unattributed(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    records = _base_records()
    records.append(_token(140, 40))
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)

    assert analysis["tokens"]["charged_spend"]["total_tokens"] == 140
    assert analysis["tokens"]["unattributed_spend_between_tasks"]["total_tokens"] == 40
    assert analysis["tokens"]["unattributed_advance_lines"] == [4]


def test_compaction_records_nearest_before_and_after_usage(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    records = [
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-1"},
        },
        _token(100, 100),
        {"type": "compacted", "payload": {"message": "bounded fixture"}},
        {"type": "event_msg", "payload": {"type": "context_compacted"}},
        _token(140, 40),
    ]
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)

    assert analysis["compaction"]["marker_count"] == 2
    for event in analysis["compaction"]["events"]:
        assert event["before"]["total_usage"]["total_tokens"] == 100
        assert event["after"]["total_usage"]["total_tokens"] == 140


def test_compaction_only_last_total_is_preserved_as_unattributed_diagnostic(
    tmp_path: Path,
) -> None:
    rollout = tmp_path / "rollout.jsonl"
    compact_last = _token(100, 1)
    compact_last["payload"]["info"]["last_token_usage"] = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 27,
    }
    records = [
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-1"},
        },
        _token(100, 100),
        compact_last,
    ]
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)

    duplicate = analysis["tokens"]["duplicate_snapshots_with_nonzero_last_usage"][0]
    assert duplicate["last_usage"]["total_tokens"] == 27
    assert duplicate["last_usage"]["unattributed_total_tokens"] == 27
    assert analysis["tokens"]["charged_spend"]["total_tokens"] == 100


def test_rate_limit_changes_are_deduplicated(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    records = _base_records()
    changed = _token(150, 50)
    changed["payload"]["rate_limits"]["primary"]["used_percent"] = 4
    records.insert(2, changed)
    _write_rollout(rollout, records)

    analysis = analyze_codex_rollout(rollout)

    assert analysis["rate_limits"]["snapshot_or_change_count"] == 2
    assert analysis["rate_limits"]["changes_after_initial"] == 1


def test_fails_closed_for_invalid_json_and_missing_task(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(CodexRolloutAnalysisError, match="line 1"):
        analyze_codex_rollout(malformed)

    no_task = tmp_path / "no-task.jsonl"
    _write_rollout(no_task, [{"type": "session_meta", "payload": {}}])
    with pytest.raises(CodexRolloutAnalysisError, match="no task_started"):
        analyze_codex_rollout(no_task)


def test_cli_writes_deterministic_atomic_json(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout.jsonl"
    output = tmp_path / "analysis.json"
    _write_rollout(rollout, _base_records())
    script = Path(__file__).resolve().parents[1] / "scripts" / "analyze_codex_rollout_tokens.py"

    first = subprocess.run(
        [sys.executable, str(script), "--rollout", str(rollout), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    first_bytes = output.read_bytes()
    second = subprocess.run(
        [sys.executable, str(script), "--rollout", str(rollout), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(first.stdout)["charged_total_tokens"] == 100
    assert (
        json.loads(second.stdout)["analysis_sha256"] == json.loads(first.stdout)["analysis_sha256"]
    )
    assert output.read_bytes() == first_bytes
    assert list(tmp_path.glob(".analysis.json.*.tmp")) == []


def test_cli_returns_structured_error_without_output(tmp_path: Path) -> None:
    rollout = tmp_path / "bad.jsonl"
    output = tmp_path / "analysis.json"
    rollout.write_text("{bad json}\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "analyze_codex_rollout_tokens.py"

    result = subprocess.run(
        [sys.executable, str(script), "--rollout", str(rollout), "--output", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert json.loads(result.stderr)["ok"] is False
    assert not output.exists()
