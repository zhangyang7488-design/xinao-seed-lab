import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PYTEST_WALL_PATTERN = re.compile(
    r"(?i)(\bpytest\b|\bunittest\b|\b\d+\s+OK\b|\bPASS\b|Ran\s+\d+\s+tests?|"
    r"验收结果|测试结果|py_compile|JSONL|final\.md|codex-events\.jsonl)"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def filter_required(request_payload: dict[str, Any]) -> bool:
    policy = str(request_payload.get("human_egress_policy") or request_payload.get("human_egress_route") or "")
    return bool(
        policy in {
            "grok_report_only",
            "segment_boundary_grok_report_only",
            "reports_stay_backend_task_bound_frontend_tui_only_summons_grok_audit",
        }
        or request_payload.get("segment_boundary_headless") is True
        or request_payload.get("headless_worker") is True
        or request_payload.get("segment_audit_ready") is True
        or request_payload.get("workflow_waiting_grok_segment_audit") is True
        or request_payload.get("worker_final_user_visible_allowed") is False
    )


def user_wait_message(task_id: str) -> str:
    return "\n".join(
        [
            "段边界后台 worker 已执行；详细验收留在后台证据。",
            "用户面只等 Grok 中文报告；Codex 不直出测试墙。",
            f"task_id: {task_id}",
            "",
        ]
    )


def sanitize_user_sink_text(text: str, *, task_id: str = "") -> tuple[str, bool]:
    if not PYTEST_WALL_PATTERN.search(str(text or "")):
        return str(text or ""), False
    return user_wait_message(task_id or "unknown"), True


MATURE_PATTERN_REFS = [
    "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\community\\jamesrochabrun__CodexSDK",
    "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\community\\joshrotenberg__codex-wrapper",
    "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\community\\kingbootoshi__codex-orchestrator",
    "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\community\\six-ddc__codex-dynamic-workflows",
    "E:\\XINAO_EXTERNAL_MATURE\\codex_20260627\\community\\humanlayer__12-factor-agents",
]


def _iter_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not path.is_file():
        return items
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def _event_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = [item]
    for key in ("item", "payload", "params", "message", "event"):
        nested = item.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return candidates


def _event_type(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in _event_candidates(item):
        for key in ("type", "event", "method", "name"):
            value = candidate.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
    return "|".join(parts)


def _text_values(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("text", "message", "content", "delta", "answer", "aggregatedOutput", "summary"):
        value = candidate.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value if isinstance(item, (str, int, float)))
    return values


def _jsonl_agent_message_texts(path: Path) -> list[str]:
    texts: list[str] = []
    for item in _iter_jsonl_objects(path):
        whole_event_kind = _event_type(item).lower()
        if "agent" in whole_event_kind or "assistant" in whole_event_kind:
            for candidate in _event_candidates(item):
                texts.extend(_text_values(candidate))
            continue
        candidates: list[Any] = [item]
        for key in ("item", "payload", "params"):
            nested = item.get(key) if isinstance(item, dict) else None
            if isinstance(nested, dict):
                candidates.append(nested)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            kind = str(candidate.get("type") or candidate.get("event") or candidate.get("method") or "")
            if "agent" not in kind.lower() and "assistant" not in kind.lower():
                continue
            texts.extend(_text_values(candidate))
    return texts


def summarize_jsonl_events(path: Path) -> dict[str, Any]:
    events = _iter_jsonl_objects(path)
    event_type_counts: dict[str, int] = {}
    agent_texts: list[str] = []
    command_executions: list[dict[str, Any]] = []
    files_modified: list[str] = []
    token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    turn_completed_count = 0

    for item in events:
        event_type = _event_type(item) or "unknown"
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
        lower_type = event_type.lower()
        if "turn.completed" in lower_type:
            turn_completed_count += 1

        for candidate in _event_candidates(item):
            kind = str(candidate.get("type") or candidate.get("event") or candidate.get("method") or "").lower()
            if "agent" in kind or "assistant" in kind or "agent" in lower_type or "assistant" in lower_type:
                agent_texts.extend(_text_values(candidate))
            if "command_execution" in kind or "commandexecution" in kind:
                command_executions.append(
                    {
                        "command": candidate.get("command") or candidate.get("cmd") or "",
                        "exit_code": candidate.get("exitCode", candidate.get("exit_code", "")),
                        "output_chars": len(str(candidate.get("aggregatedOutput") or candidate.get("output") or "")),
                    }
                )
            usage = candidate.get("usage")
            if isinstance(usage, dict):
                for src, dst in (
                    ("input_tokens", "input_tokens"),
                    ("output_tokens", "output_tokens"),
                    ("total_tokens", "total_tokens"),
                    ("prompt_tokens", "input_tokens"),
                    ("completion_tokens", "output_tokens"),
                ):
                    value = usage.get(src)
                    if isinstance(value, int):
                        token_usage[dst] += value
            for key in ("file", "path"):
                value = candidate.get(key)
                if isinstance(value, str) and value:
                    files_modified.append(value)
            value = candidate.get("files_modified") or candidate.get("files")
            if isinstance(value, list):
                files_modified.extend(str(item) for item in value if isinstance(item, (str, int, float)))

    if not token_usage["total_tokens"]:
        token_usage["total_tokens"] = token_usage["input_tokens"] + token_usage["output_tokens"]

    unique_files = sorted({item for item in files_modified if item})
    return {
        "schema_version": "xinao.codex_jsonl_observe_summary.v1",
        "event_count": len(events),
        "event_type_counts": event_type_counts,
        "agent_message_count": len(agent_texts),
        "command_execution_count": len(command_executions),
        "turn_completed_count": turn_completed_count,
        "token_usage": token_usage,
        "files_modified": unique_files,
        "files_modified_count": len(unique_files),
        "last_agent_message_preview": (agent_texts[-1][:240] if agent_texts else ""),
        "command_executions": command_executions[-20:],
        "mature_pattern_refs": MATURE_PATTERN_REFS,
        "mature_pattern_summary": (
            "CodexSDK/codex-wrapper JSONL stream parsing + codex-orchestrator jobs-json style "
            "task summary + 12-factor human-as-tool egress boundary."
        ),
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_filter(
    *,
    task_id: str,
    paths: dict[str, Path],
    request_payload: dict[str, Any],
    expected_marker: str = "",
) -> dict[str, Any]:
    required = filter_required(request_payload)
    raw_final = paths["raw_final"] if required else paths["final"]
    final_path = paths["final"]
    raw_text = raw_final.read_text(encoding="utf-8", errors="replace") if raw_final.is_file() else ""
    agent_texts = _jsonl_agent_message_texts(paths["jsonl"])
    observe_summary = summarize_jsonl_events(paths["jsonl"])
    leaked_text = "\n".join([raw_text, *agent_texts])
    pytest_wall_detected = bool(PYTEST_WALL_PATTERN.search(leaked_text))
    marker_seen = bool(expected_marker and expected_marker in raw_text)
    blocked_user_egress = bool(required and pytest_wall_detected)
    if required:
        final_path.write_text(user_wait_message(task_id), encoding="utf-8")
    payload = {
        "schema_version": "xinao.human_egress_jsonl_filter.v1",
        "generated_at": now_iso(),
        "task_id": task_id,
        "status": "SEGMENT_BOUNDARY_USER_EGRESS_BLOCKED" if blocked_user_egress else "egress_filtered" if required else "not_required",
        "human_egress_policy": (
            str(request_payload.get("human_egress_policy") or request_payload.get("human_egress_route") or "")
            or ("grok_report_only" if required else "")
        ),
        "headless_worker": bool(request_payload.get("headless_worker") or request_payload.get("segment_boundary_headless")),
        "jsonl_path": str(paths["jsonl"]),
        "raw_final_path": str(raw_final),
        "user_visible_final_path": str(final_path),
        "raw_final_backend_evidence_only": required,
        "worker_final_user_visible_allowed": not required,
        "codex_final_to_user_allowed": not required,
        "no_pytest_wall_to_user": required,
        "pytest_wall_detected_in_backend": pytest_wall_detected,
        "segment_boundary_user_egress_blocked": blocked_user_egress,
        "marker_seen_in_raw_final": marker_seen,
        "agent_message_count": len(agent_texts),
        "codex_jsonl_event_contract": "CodexSDK/codex-wrapper compatible event stream consumer",
        "jobs_json_observe": observe_summary,
        "human_as_tool_boundary": "12-factor-agents factor7 local policy: user sees Grok Chinese report boundary, not raw worker stdout/final",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
    }
    write_json(paths["egress_filter"], payload)
    return payload
