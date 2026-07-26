from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

ANALYSIS_SCHEMA_VERSION = "xinao.codex_rollout_token_analysis.v1"
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
WAIT_TOOL_NAMES = frozenset({"wait", "write_stdin"})
_NESTED_TOOL_PATTERN = re.compile(
    r"\btools(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\])\s*\("
)
_YIELDED_CELL_PATTERN = re.compile(r"Script running with cell ID\s+([^\s\\\"']+)")


class CodexRolloutAnalysisError(ValueError):
    """Raised when a rollout cannot be measured without inventing evidence."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_mapping(value: object, field: str, line_number: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CodexRolloutAnalysisError(f"line {line_number}: {field} must be an object")
    return dict(value)


def _require_nonnegative_int(value: object, field: str, line_number: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CodexRolloutAnalysisError(f"line {line_number}: {field} must be an integer")
    if value < 0:
        raise CodexRolloutAnalysisError(f"line {line_number}: {field} must be nonnegative")
    return value


def _zero_usage() -> dict[str, int]:
    return {field: 0 for field in TOKEN_FIELDS}


def _usage(value: object, field: str, line_number: int) -> dict[str, int]:
    raw = _require_mapping(value, field, line_number)
    result = {
        name: _require_nonnegative_int(raw.get(name, 0), f"{field}.{name}", line_number)
        for name in TOKEN_FIELDS
    }
    if result["total_tokens"] < result["input_tokens"] + result["output_tokens"]:
        raise CodexRolloutAnalysisError(
            f"line {line_number}: {field}.total_tokens is smaller than input_tokens + output_tokens"
        )
    if result["cached_input_tokens"] + result["cache_write_input_tokens"] > result["input_tokens"]:
        raise CodexRolloutAnalysisError(
            f"line {line_number}: cached and cache-write input exceed input_tokens"
        )
    if result["reasoning_output_tokens"] > result["output_tokens"]:
        raise CodexRolloutAnalysisError(
            f"line {line_number}: reasoning_output_tokens exceed output_tokens"
        )
    return result


def _add_usage(target: dict[str, int], value: Mapping[str, int]) -> None:
    for field in TOKEN_FIELDS:
        target[field] += int(value[field])


def _subtract_usage(
    current: Mapping[str, int],
    previous: Mapping[str, int],
    line_number: int,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        delta = int(current[field]) - int(previous[field])
        if delta < 0:
            raise CodexRolloutAnalysisError(
                f"line {line_number}: cumulative {field} decreased from "
                f"{previous[field]} to {current[field]}"
            )
        result[field] = delta
    return result


def _derived_usage(value: Mapping[str, int]) -> dict[str, int]:
    result = dict(value)
    result["unattributed_total_tokens"] = (
        value["total_tokens"] - value["input_tokens"] - value["output_tokens"]
    )
    result["uncached_read_input_tokens"] = (
        value["input_tokens"] - value["cached_input_tokens"] - value["cache_write_input_tokens"]
    )
    result["non_reasoning_output_tokens"] = (
        value["output_tokens"] - value["reasoning_output_tokens"]
    )
    return result


def _text_chars(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_text_chars(item) for item in value)
    if isinstance(value, Mapping):
        text = value.get("text")
        if isinstance(text, str):
            return len(text)
        for key in ("content", "output", "data"):
            if key in value:
                return _text_chars(value[key])
        return sum(_text_chars(item) for key, item in value.items() if key != "type")
    return len(str(value))


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _distribution(values: Sequence[int]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "sum": 0, "min": 0, "median": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        median: int | float = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "count": len(ordered),
        "sum": sum(ordered),
        "min": ordered[0],
        "median": median,
        "p90": _nearest_rank(ordered, 0.90),
        "max": ordered[-1],
    }


def _call_input(payload: Mapping[str, object]) -> str:
    for key in ("input", "arguments"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if value is not None:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ""


def _call_parameters(payload: Mapping[str, object]) -> dict[str, object]:
    raw = _call_input(payload)
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _find_nearest_token_total(
    token_rows: Sequence[dict[str, object]],
    line_number: int,
    *,
    before: bool,
) -> dict[str, object] | None:
    candidates = [
        row
        for row in token_rows
        if (int(row["line"]) < line_number if before else int(row["line"]) > line_number)
        and int(row["charged_delta"]["total_tokens"]) > 0  # type: ignore[index]
    ]
    if not candidates:
        return None
    chosen = (
        max(candidates, key=lambda row: int(row["line"]))
        if before
        else min(candidates, key=lambda row: int(row["line"]))
    )
    return {
        "line": chosen["line"],
        "timestamp": chosen["timestamp"],
        "basis": chosen["basis"],
        "total_usage": chosen["total_usage"],
        "charged_delta": chosen["charged_delta"],
    }


def _elapsed_seconds(start: object, end: object) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        elapsed = (end_dt - start_dt).total_seconds()
    except (TypeError, ValueError):
        return None
    return round(elapsed, 6) if elapsed >= 0 else None


def _linear_slope(values: Sequence[int]) -> float | None:
    if len(values) < 2:
        return None
    x_mean = (len(values) - 1) / 2
    y_mean = sum(values) / len(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    return round(numerator / denominator, 6)


def _pair_compaction_events(
    events: Sequence[dict[str, object]],
    token_rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    measured_rows = [
        row
        for row in token_rows
        if int(row["charged_delta"]["total_tokens"]) > 0  # type: ignore[index]
    ]
    episodes: list[dict[str, object]] = []
    index = 0
    while index < len(events):
        first = events[index]
        last = first
        pairing = "single_marker"
        if (
            first.get("kind") == "compacted"
            and index + 1 < len(events)
            and events[index + 1].get("kind") == "context_compacted"
        ):
            last = events[index + 1]
            pairing = "paired_top_level_and_event_marker"
            index += 1
        before = first.get("before")
        after = last.get("after")
        before_input = None
        after_input = None
        if isinstance(before, Mapping) and isinstance(before.get("charged_delta"), Mapping):
            before_input = int(before["charged_delta"]["input_tokens"])  # type: ignore[index]
        if isinstance(after, Mapping) and isinstance(after.get("charged_delta"), Mapping):
            after_input = int(after["charged_delta"]["input_tokens"])  # type: ignore[index]
        post_line = int(after["line"]) if isinstance(after, Mapping) else None
        next_marker_line = int(events[index + 1]["line"]) if index + 1 < len(events) else None
        regrowth_rows = [
            row
            for row in measured_rows
            if post_line is not None
            and int(row["line"]) > post_line
            and (next_marker_line is None or int(row["line"]) < next_marker_line)
        ]
        recovery: dict[str, object] = {}
        for label, fraction in (("t50", 0.50), ("t75", 0.75), ("t90", 0.90)):
            target = math.ceil(before_input * fraction) if before_input else None
            hit = next(
                (
                    (rounds, row)
                    for rounds, row in enumerate(regrowth_rows, start=1)
                    if target is not None and int(row["charged_delta"]["input_tokens"]) >= target  # type: ignore[index]
                ),
                None,
            )
            recovery[label] = {
                "rounds": hit[0] if hit else None,
                "wall_seconds": (
                    _elapsed_seconds(after.get("timestamp"), hit[1].get("timestamp"))
                    if hit and isinstance(after, Mapping)
                    else None
                ),
            }
        episodes.append(
            {
                "pairing": pairing,
                "marker_count": 2 if last is not first else 1,
                "marker_line_start": int(first["line"]),
                "marker_line_end": int(last["line"]),
                "pre_model_input_tokens": before_input,
                "post_model_input_tokens": after_input,
                "released_model_input_tokens": (
                    before_input - after_input
                    if before_input is not None and after_input is not None
                    else None
                ),
                "recovery": recovery,
            }
        )
        index += 1
    return episodes


def _summarize_context_epoch(
    *,
    epoch_index: int,
    start_line_exclusive: int,
    end_line_exclusive: int,
    token_rows: Sequence[dict[str, object]],
    tool_output_rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    model_rows = [
        row
        for row in token_rows
        if start_line_exclusive < int(row["line"]) < end_line_exclusive
        and int(row["charged_delta"]["total_tokens"]) > 0  # type: ignore[index]
    ]
    input_values = [int(row["charged_delta"]["input_tokens"]) for row in model_rows]  # type: ignore[index]
    cached_values = [
        int(row["charged_delta"]["cached_input_tokens"])
        for row in model_rows  # type: ignore[index]
    ]
    uncached_values = [
        int(row["charged_delta"]["uncached_read_input_tokens"])
        for row in model_rows  # type: ignore[index]
    ]
    return {
        "epoch": epoch_index,
        "model_round_count": len(model_rows),
        "first_model_input_tokens": input_values[0] if input_values else None,
        "last_model_input_tokens": input_values[-1] if input_values else None,
        "input_growth_tokens_per_round": _linear_slope(input_values),
        "input_tokens": sum(input_values),
        "cached_input_tokens": sum(cached_values),
        "uncached_read_input_tokens": sum(uncached_values),
        "tool_output_text_chars": sum(
            int(row["chars"])
            for row in tool_output_rows
            if start_line_exclusive < int(row["line"]) < end_line_exclusive
        ),
    }


def _parse_jsonl(raw: bytes) -> list[tuple[int, dict[str, Any]]]:
    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            decoded = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexRolloutAnalysisError(
                f"line {line_number}: invalid UTF-8 JSONL record"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise CodexRolloutAnalysisError(f"line {line_number}: record must be an object")
        records.append((line_number, dict(decoded)))
    if not records:
        raise CodexRolloutAnalysisError("rollout is empty")
    return records


def analyze_codex_rollout(path: Path) -> dict[str, object]:
    """Measure a Codex rollout deterministically without invoking a model or network."""

    resolved = path.resolve()
    if not resolved.is_file():
        raise CodexRolloutAnalysisError(f"rollout is not a file: {resolved}")
    raw = resolved.read_bytes()
    records = _parse_jsonl(raw)

    first_task_started_index: int | None = None
    for index, (_, record) in enumerate(records):
        if record.get("type") != "event_msg":
            continue
        payload = record.get("payload")
        if isinstance(payload, Mapping) and payload.get("type") == "task_started":
            first_task_started_index = index
            break
    if first_task_started_index is None:
        raise CodexRolloutAnalysisError("rollout has no task_started event")

    prefix_records = records[:first_task_started_index]
    scoped_records = records[first_task_started_index:]
    prefix_baseline: dict[str, int] | None = None
    for line_number, record in prefix_records:
        payload = record.get("payload")
        if (
            record.get("type") == "event_msg"
            and isinstance(payload, Mapping)
            and payload.get("type") == "token_count"
        ):
            info = _require_mapping(payload.get("info"), "token_count.info", line_number)
            prefix_baseline = _usage(
                info.get("total_token_usage"), "total_token_usage", line_number
            )

    record_counts: Counter[str] = Counter()
    payload_counts: Counter[str] = Counter()
    token_rows: list[dict[str, object]] = []
    compaction_markers: list[dict[str, object]] = []
    task_rows: list[dict[str, object]] = []
    task_by_turn: dict[str, dict[str, object]] = {}
    active_turn_id: str | None = None
    turn_context_count = 0
    rate_limit_snapshots: list[dict[str, object]] = []
    previous_rate_limit_identity: str | None = None

    call_names: Counter[str] = Counter()
    call_name_by_id: dict[str, str] = {}
    call_inputs: dict[tuple[str, str], list[int]] = defaultdict(list)
    output_chars_by_tool: dict[str, list[int]] = defaultdict(list)
    orphan_output_chars: list[int] = []
    tool_output_rows: list[dict[str, object]] = []
    exec_cells: list[dict[str, object]] = []
    direct_wait_calls: list[dict[str, object]] = []
    wait_exec_lines: dict[str, int] = {}
    yielded_wait_cells: dict[str, tuple[int, int]] = {}
    double_hop_pairs: list[dict[str, object]] = []

    previous_total = prefix_baseline
    spend = _zero_usage()
    unattributed_spend = _zero_usage()
    unattributed_advance_lines: list[int] = []
    reported_last_sum = _zero_usage()
    residual_sum = _zero_usage()
    unique_advances = 0
    duplicate_cumulative_snapshots = 0
    duplicate_with_nonzero_last: list[dict[str, object]] = []

    for line_number, record in scoped_records:
        top_type = str(record.get("type") or "missing")
        record_counts[top_type] += 1
        payload = record.get("payload")
        payload_type = str(payload.get("type") or "missing") if isinstance(payload, Mapping) else ""
        if payload_type:
            payload_counts[payload_type] += 1
        if top_type == "turn_context":
            turn_context_count += 1

        if top_type == "event_msg" and isinstance(payload, Mapping):
            if payload_type == "task_started":
                turn_id = str(payload.get("turn_id") or f"line-{line_number}")
                active_turn_id = turn_id
                row = {
                    "turn_id": turn_id,
                    "start_line": line_number,
                    "complete_line": None,
                    "status": "in_progress",
                    "token_spend": _zero_usage(),
                }
                task_rows.append(row)
                task_by_turn[turn_id] = row
            elif payload_type == "task_complete":
                turn_id = str(payload.get("turn_id") or active_turn_id or f"line-{line_number}")
                row = task_by_turn.get(turn_id)
                if row is not None:
                    row["complete_line"] = line_number
                    row["status"] = "complete"
                if active_turn_id == turn_id:
                    active_turn_id = None
            elif payload_type == "context_compacted":
                compaction_markers.append({"line": line_number, "kind": payload_type})
            elif payload_type == "token_count":
                info = _require_mapping(payload.get("info"), "token_count.info", line_number)
                total = _usage(info.get("total_token_usage"), "total_token_usage", line_number)
                last = _usage(info.get("last_token_usage"), "last_token_usage", line_number)
                _add_usage(reported_last_sum, last)

                if previous_total is None:
                    if last["total_tokens"]:
                        delta = dict(last)
                        basis = "first_last_usage"
                    elif total["total_tokens"]:
                        delta = dict(total)
                        basis = "first_total_fallback_last_was_zero"
                    else:
                        delta = _zero_usage()
                        basis = "first_zero_usage"
                elif total["total_tokens"] == previous_total["total_tokens"]:
                    if total != previous_total:
                        raise CodexRolloutAnalysisError(
                            f"line {line_number}: cumulative usage components changed without a "
                            "total_tokens advance"
                        )
                    delta = _zero_usage()
                    basis = "duplicate_cumulative_snapshot"
                    duplicate_cumulative_snapshots += 1
                    if last["total_tokens"]:
                        duplicate_with_nonzero_last.append(
                            {"line": line_number, "last_usage": _derived_usage(last)}
                        )
                else:
                    delta = _subtract_usage(total, previous_total, line_number)
                    basis = "cumulative_delta"

                if delta["total_tokens"]:
                    unique_advances += 1
                    _add_usage(spend, delta)
                    if active_turn_id and active_turn_id in task_by_turn:
                        _add_usage(task_by_turn[active_turn_id]["token_spend"], delta)  # type: ignore[arg-type]
                    else:
                        _add_usage(unattributed_spend, delta)
                        unattributed_advance_lines.append(line_number)
                residual = {field: last[field] - delta[field] for field in TOKEN_FIELDS}
                _add_usage(residual_sum, residual)
                token_rows.append(
                    {
                        "line": line_number,
                        "timestamp": record.get("timestamp"),
                        "turn_id": active_turn_id,
                        "basis": basis,
                        "total_usage": _derived_usage(total),
                        "last_usage": _derived_usage(last),
                        "charged_delta": _derived_usage(delta),
                        "last_minus_delta": _derived_usage(residual),
                        "model_context_window": info.get("model_context_window"),
                    }
                )
                previous_total = total

                rate_limits = payload.get("rate_limits")
                identity = json.dumps(
                    rate_limits, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                if identity != previous_rate_limit_identity:
                    rate_limit_snapshots.append({"line": line_number, "rate_limits": rate_limits})
                    previous_rate_limit_identity = identity

        if top_type == "compacted":
            compaction_markers.append({"line": line_number, "kind": top_type})

        if top_type != "response_item" or not isinstance(payload, Mapping):
            continue
        if payload_type in {"custom_tool_call", "function_call"}:
            name = str(payload.get("name") or "unknown")
            call_id = str(payload.get("call_id") or payload.get("id") or f"line-{line_number}")
            call_input = _call_input(payload)
            call_names[name] += 1
            call_name_by_id[call_id] = name
            fingerprint = _sha256_bytes(call_input.encode("utf-8"))
            call_inputs[(name, fingerprint)].append(line_number)
            if name in WAIT_TOOL_NAMES:
                direct_wait_calls.append({"line": line_number, "name": name})
                parameters = _call_parameters(payload)
                cell_id = parameters.get("cell_id")
                yielded = yielded_wait_cells.pop(str(cell_id), None)
                if yielded and 0 < line_number - yielded[1] <= 15:
                    double_hop_pairs.append(
                        {
                            "exec_call_line": yielded[0],
                            "exec_output_line": yielded[1],
                            "direct_wait_line": line_number,
                            "cell_id": str(cell_id),
                        }
                    )
            if name == "exec":
                nested_names = [
                    dot_name or bracket_name
                    for dot_name, bracket_name in _NESTED_TOOL_PATTERN.findall(call_input)
                ]
                wait_only = bool(nested_names) and set(nested_names).issubset(WAIT_TOOL_NAMES)
                cell = {
                    "line": line_number,
                    "nested_call_count": len(nested_names),
                    "nested_tools": dict(sorted(Counter(nested_names).items())),
                    "uses_promise_all": "Promise.all(" in call_input,
                    "uses_promise_all_settled": "Promise.allSettled(" in call_input,
                    "wait_only": wait_only,
                }
                exec_cells.append(cell)
                if wait_only:
                    wait_exec_lines[call_id] = line_number
        elif payload_type in {"custom_tool_call_output", "function_call_output"}:
            call_id = str(payload.get("call_id") or payload.get("id") or "")
            chars = _text_chars(payload.get("output"))
            name = call_name_by_id.get(call_id)
            output_text = payload.get("output")
            if call_id in wait_exec_lines and isinstance(output_text, str):
                yielded = _YIELDED_CELL_PATTERN.search(output_text)
                if yielded:
                    yielded_wait_cells[yielded.group(1)] = (
                        wait_exec_lines[call_id],
                        line_number,
                    )
            tool_output_rows.append({"line": line_number, "chars": chars})
            if name is None:
                orphan_output_chars.append(chars)
            else:
                output_chars_by_tool[name].append(chars)

    compaction_events: list[dict[str, object]] = []
    for marker in compaction_markers:
        line_number = int(marker["line"])
        compaction_events.append(
            {
                **marker,
                "before": _find_nearest_token_total(token_rows, line_number, before=True),
                "after": _find_nearest_token_total(token_rows, line_number, before=False),
            }
        )
    compaction_episodes = _pair_compaction_events(compaction_events, token_rows)
    context_epochs: list[dict[str, object]] = []
    previous_marker_end = 0
    for episode in compaction_episodes:
        context_epochs.append(
            _summarize_context_epoch(
                epoch_index=len(context_epochs),
                start_line_exclusive=previous_marker_end,
                end_line_exclusive=int(episode["marker_line_start"]),
                token_rows=token_rows,
                tool_output_rows=tool_output_rows,
            )
        )
        previous_marker_end = int(episode["marker_line_end"])
    context_epochs.append(
        _summarize_context_epoch(
            epoch_index=len(context_epochs),
            start_line_exclusive=previous_marker_end,
            end_line_exclusive=records[-1][0] + 1,
            token_rows=token_rows,
            tool_output_rows=tool_output_rows,
        )
    )

    repeated_inputs = [
        {"tool": name, "input_sha256": fingerprint, "count": len(lines), "lines": lines}
        for (name, fingerprint), lines in sorted(call_inputs.items())
        if len(lines) > 1
    ]
    all_output_chars = [
        value for values in output_chars_by_tool.values() for value in values
    ] + orphan_output_chars
    per_tool_outputs = {
        name: _distribution(values) for name, values in sorted(output_chars_by_tool.items())
    }
    if orphan_output_chars:
        per_tool_outputs["__orphan__"] = _distribution(orphan_output_chars)

    task_output: list[dict[str, object]] = []
    for row in task_rows:
        copied = dict(row)
        copied["token_spend"] = _derived_usage(row["token_spend"])  # type: ignore[arg-type]
        task_output.append(copied)

    multi_call_cells = [row for row in exec_cells if int(row["nested_call_count"]) > 1]
    batched_cells = [
        row
        for row in multi_call_cells
        if bool(row["uses_promise_all"]) or bool(row["uses_promise_all_settled"])
    ]
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "authority": False,
        "completion_claim_allowed": False,
        "measurement_contract": {
            "cumulative_snapshots_are_never_summed": True,
            "spend_is_unique_cumulative_delta": True,
            "first_checkpoint_uses_prefix_baseline_or_last_usage": True,
            "duplicate_cumulative_snapshots_are_excluded_from_spend": True,
            "quality_or_intent_is_not_inferred_from_token_volume": True,
            "component_change_without_total_advance_fails_closed": True,
            "classification_metrics_are_lexical_heuristics": True,
        },
        "input": {
            "path": str(resolved),
            "sha256": _sha256_bytes(raw),
            "bytes": len(raw),
            "jsonl_records": len(records),
        },
        "scope": {
            "first_task_started_line": scoped_records[0][0],
            "excluded_prefix_records": len(prefix_records),
            "excluded_prefix_token_baseline": (
                _derived_usage(prefix_baseline) if prefix_baseline is not None else None
            ),
            "analyzed_records": len(scoped_records),
        },
        "records": {
            "top_level_types": dict(sorted(record_counts.items())),
            "payload_types": dict(sorted(payload_counts.items())),
        },
        "tokens": {
            "token_count_records": len(token_rows),
            "model_rounds_by_unique_counter_advance": unique_advances,
            "duplicate_cumulative_snapshots": duplicate_cumulative_snapshots,
            "duplicate_snapshots_with_nonzero_last_usage": duplicate_with_nonzero_last,
            "charged_spend": _derived_usage(spend),
            "unattributed_spend_between_tasks": _derived_usage(unattributed_spend),
            "unattributed_advance_lines": unattributed_advance_lines,
            "reported_last_usage_sum_diagnostic_only": _derived_usage(reported_last_sum),
            "reported_last_minus_charged_delta": _derived_usage(residual_sum),
            "last_cumulative_usage": (token_rows[-1]["total_usage"] if token_rows else None),
            "checkpoints": token_rows,
        },
        "boundaries": {
            "task_count": len(task_rows),
            "completed_task_count": sum(row["status"] == "complete" for row in task_rows),
            "turn_context_count": turn_context_count,
            "tasks": task_output,
        },
        "tools": {
            "calls_by_name": dict(sorted(call_names.items())),
            "code_mode_exec_cells": len(exec_cells),
            "multi_nested_call_cells": len(multi_call_cells),
            "promise_batched_multi_call_cells": len(batched_cells),
            "single_nested_call_cells": sum(
                int(row["nested_call_count"]) == 1 for row in exec_cells
            ),
            "wait_only_exec_cells": [row for row in exec_cells if row["wait_only"]],
            "direct_wait_calls": direct_wait_calls,
            "wait_diagnostics": {
                "double_hop_count": len(double_hop_pairs),
                "double_hop_pairs": double_hop_pairs,
            },
            "repeated_identical_inputs": repeated_inputs,
            "exec_cell_details": exec_cells,
            "output_text_chars": {
                "overall": _distribution(all_output_chars),
                "by_tool": per_tool_outputs,
            },
        },
        "compaction": {
            "marker_count": len(compaction_events),
            "events": compaction_events,
            "episode_count": len(compaction_episodes),
            "episodes": compaction_episodes,
            "context_epochs": context_epochs,
        },
        "rate_limits": {
            "snapshot_or_change_count": len(rate_limit_snapshots),
            "changes_after_initial": max(0, len(rate_limit_snapshots) - 1),
            "snapshots": rate_limit_snapshots,
        },
    }


def write_codex_rollout_analysis(path: Path, analysis: Mapping[str, object]) -> str:
    """Write canonical JSON atomically and return its SHA-256."""

    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{resolved.name}.", suffix=".tmp", dir=resolved.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256_bytes(raw)
