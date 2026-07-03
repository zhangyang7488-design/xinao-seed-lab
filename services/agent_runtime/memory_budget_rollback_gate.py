import argparse
import datetime as dt
import json
import os
import pathlib
import sys
from json import JSONDecodeError
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
ACTIVE_OBJECT_ID = "XINAO_HUMAN_INTENT_CONTINUITY_RUNTIME"
SENTINEL = "SENTINEL:XINAO_MEMORY_BUDGET_ROLLBACK_GATE_PASS"
REQUIRED_CLAIM_FIELDS = (
    "memory_read_refs",
    "evidence_write_refs",
    "budget_record",
    "rollback_plan_ref",
    "rollback_execution_result",
    "human_visible_status",
    "human_visible_side_audit_ref",
)
DEFAULT_TOKEN_BUDGET_LIMIT = 100_000
DEFAULT_COST_BUDGET_USD_LIMIT = 1.0
DEFAULT_HUMAN_VISIBLE_RECURSION_LIMIT = 10


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
    return normalized[:120] or "xinao_task"


def read_json_if_exists(path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except JSONDecodeError as exc:
        return {"_read_error": f"json_decode_error:{exc.msg}", "_source_path": str(path)}


def read_jsonl_if_exists(path: pathlib.Path, *, limit: int = 200) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines()[-limit:]:
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except JSONDecodeError:
            continue
    return rows


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def authority_boundary(role: str) -> dict[str, Any]:
    return {
        "schema_version": "xinao.authority_boundary.v1",
        "role": role,
        "source_of_truth": "external_mature_runtime",
        "fact_authority": "temporal_event_history_and_external_trace",
        "user_completion_authority": "human_visible_completion_decision",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_execution_controller": True,
        "demotion_reason": "memory_budget_rollback_gate_outputs_are_evidence_and_read_models_only",
    }


def demote_read_model(payload: dict[str, Any], role: str) -> dict[str, Any]:
    payload["authority_boundary"] = authority_boundary(role)
    payload["not_source_of_truth"] = True
    payload["not_user_completion"] = True
    payload["not_completion_decision"] = True
    payload["not_execution_controller"] = True
    return payload


def existing_refs(paths: list[pathlib.Path]) -> list[str]:
    refs: list[str] = []
    for path in paths:
        if path.exists():
            refs.append(str(path))
    return refs


def write_minimal_rollback_plan(
    *,
    task_id: str,
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    reason: str = "completion_claim_evidence_required",
) -> pathlib.Path:
    path = runtime_root / "state" / "rollback_plans" / f"{safe_name(task_id)}.json"
    payload = {
        "schema_version": "xinao.rollback_plan.v1",
        "generated_at": now(),
        "task_object_id": task_id,
        "reason": reason,
        "rollback_scope": "minimal_state_and_writeback_reversal",
        "temporal_workflow_id": f"xinao-codex-task-{safe_name(task_id)}",
        "steps": [
            {
                "step_id": "preserve_frontier",
                "action": "Keep frontier/checkpoint state; never replace TaskObject to fake completion.",
            },
            {
                "step_id": "revert_completion_like_events",
                "action": "If a completion-like writeback is later found invalid, append a rejected/partial correction event rather than editing history.",
            },
            {
                "step_id": "resume_from_checkpoint",
                "action": "Resume from latest checkpoint and rerun /completion/claim after evidence is complete.",
            },
        ],
        "non_destructive": True,
    }
    demote_read_model(payload, "rollback_plan_evidence")
    write_json(path, payload)
    return path


def write_pending_human_visible_side_audit_request(
    *,
    task_id: str,
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    human_visible_status: dict[str, Any] | None = None,
) -> pathlib.Path:
    path = runtime_root / "state" / "human_visible_completion_audit" / f"{safe_name(task_id)}.json"
    latest = runtime_root / "state" / "human_visible_completion_audit" / "latest.json"
    status = human_visible_status or {}
    payload = {
        "schema_version": "xinao.human_visible_completion_side_audit.v1",
        "generated_at": now(),
        "task_object_id": task_id,
        "status": "pending_external_human_visual_ai_audit",
        "audit_lane": "external_ai_human_visual_completion_side_audit",
        "required_auditor_role": "independent_ai_auditor_not_primary_executor",
        "primary_executor_may_not_self_sign": True,
        "mature_carriers": {
            "temporal": "Visibility/Search Attributes for workflow state",
            "opentelemetry": "Logs/Events for correlated audit records",
            "langgraph": "checkpoints/interrupts for resumable human-in-the-loop state",
            "dify": "workflow run detail and Human Input node as visible control surface",
        },
        "human_visible_status": status,
        "completion_semantics": {
            "external_ai_human_visual_audit_required_for_any_completion": True,
            "text_report_cannot_replace_execution": True,
            "machine_terminal_not_enough_without_human_visible_status": True,
            "primary_ai_report_cannot_replace_side_audit": True,
            "dify_or_report_cannot_override_completion_claim": True,
        },
        "required_reader_outcome_cn": {
            "current_goal": status.get("current_goal") or status.get("goal") or "未提供",
            "current_state": status.get("current_state") or status.get("status") or "需要读取后端 decision",
            "what_is_complete": status.get("what_is_complete") or [],
            "what_is_not_complete": status.get("what_is_not_complete") or [],
            "next_action_cn": status.get("next_action_cn") or status.get("next_action") or "继续执行到人类可判定的完成",
        },
    }
    demote_read_model(payload, "pending_human_visible_side_audit_request")
    write_json(path, payload)
    write_json(latest, payload)
    return path


def human_visible_side_audit_passed(audit: dict[str, Any], task_id: str | None = None) -> bool:
    if not audit or audit.get("_read_error"):
        return False
    if audit.get("schema_version") != "xinao.human_visible_completion_side_audit.v1":
        return False
    if task_id and audit.get("task_object_id") not in (task_id, ACTIVE_OBJECT_ID, None, ""):
        return False
    if audit.get("status") not in ("external_ai_human_visual_audit_passed", "human_visible_side_audit_passed"):
        return False
    if audit.get("primary_executor_may_not_self_sign") is not True:
        return False
    auditor = str(audit.get("auditor_id") or audit.get("auditor") or "").strip().lower()
    if not auditor or auditor in {"codex-a", "codex_main", "primary", "self", "same_ai"}:
        return False
    if audit.get("auditor_independent_of_primary") is not True:
        return False
    findings = audit.get("human_visual_findings") or audit.get("findings") or {}
    if isinstance(findings, list):
        return bool(findings) and (
            audit.get("completion_claim_allowed_by_this_audit") is True
            or audit.get("audit_lane_evidence_accepted") is True
        )
    if not isinstance(findings, dict):
        return False
    required_flags = (
        "user_can_understand_current_state",
        "no_machine_terminal_disguised_as_user_completion",
        "unfinished_items_visible",
        "next_action_visible",
    )
    return all(findings.get(flag) is True for flag in required_flags)


def build_continuation_execution_plan(
    *,
    task_id: str,
    blockers: list[str],
    attempt: int = 0,
    recursion_limit: int = DEFAULT_HUMAN_VISIBLE_RECURSION_LIMIT,
) -> dict[str, Any]:
    remaining = max(0, recursion_limit - attempt)
    return demote_read_model({
        "schema_version": "xinao.completion_blocked_continue_execution_plan.v1",
        "task_object_id": task_id,
        "status": "continue_execution_until_human_visible_completion",
        "completion_claim_blocked": True,
        "stop_allowed": False,
        "must_continue_without_textual_terminal": remaining > 0,
        "current_attempt": attempt,
        "default_recursive_continuation_limit": recursion_limit,
        "remaining_recursive_continuation_attempts": remaining,
        "named_blockers": blockers,
        "next_actions": [
            "Preserve TaskObject, frontier, checkpoint, and rollback evidence.",
            "Request or run an independent external AI human-visual completion side audit.",
            "Expose the backend claim decision and unfinished frontier in the human-visible surface.",
            "Rebuild /completion/claim payload with the external side audit evidence.",
            "Call /completion/claim again; only complete_allowed with stop_allowed=true may end the transaction.",
        ],
        "forbidden_terminal_substitutes": [
            "desktop_txt",
            "final_md",
            "result_json",
            "handoff_text",
            "continuation_envelope",
            "primary_ai_self_report",
        ],
    }, "continuation_execution_plan")


def build_budget_record(
    *,
    task_id: str = "",
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    over_budget: bool = False,
    user_confirmed_over_budget: bool = False,
    token_budget_limit: int | None = None,
    cost_budget_usd_limit: float | None = None,
) -> dict[str, Any]:
    litellm_path = runtime_root / "state" / "litellm_live_gateway_canary" / "latest.json"
    langfuse_path = runtime_root / "state" / "langfuse_live_trace_canary" / "latest.json"
    litellm_state = read_json_if_exists(litellm_path)
    langfuse_state = read_json_if_exists(langfuse_path)
    litellm_events = read_jsonl_if_exists(runtime_root / "state" / "litellm_live_gateway_canary" / "events.ndjson")
    langfuse_events = read_jsonl_if_exists(runtime_root / "state" / "langfuse_live_trace_canary" / "events.ndjson")
    aggregate = aggregate_budget_usage(
        litellm_state=litellm_state,
        langfuse_state=langfuse_state,
        litellm_events=litellm_events,
        langfuse_events=langfuse_events,
        task_id=task_id,
        token_budget_limit=token_budget_limit,
        cost_budget_usd_limit=cost_budget_usd_limit,
    )
    effective_over_budget = bool(over_budget or aggregate["over_budget"])
    return demote_read_model({
        "schema_version": "xinao.budget_record.v1",
        "generated_at": now(),
        "task_object_id": task_id,
        "budget_source": "LiteLLM+Langfuse",
        "litellm_state_ref": str(litellm_path),
        "langfuse_state_ref": str(langfuse_path),
        "litellm_events_ref": str(runtime_root / "state" / "litellm_live_gateway_canary" / "events.ndjson"),
        "langfuse_events_ref": str(runtime_root / "state" / "langfuse_live_trace_canary" / "events.ndjson"),
        "litellm_status": litellm_state.get("status", "missing"),
        "langfuse_status": langfuse_state.get("status", "missing"),
        "usage_aggregation": aggregate,
        "aggregation_window": aggregate["aggregation_window"],
        "actual_total_tokens": aggregate["actual_total_tokens"],
        "actual_prompt_tokens": aggregate["actual_prompt_tokens"],
        "actual_completion_tokens": aggregate["actual_completion_tokens"],
        "actual_cost_usd": aggregate["actual_cost_usd"],
        "token_budget_limit": aggregate["token_budget_limit"],
        "cost_budget_usd_limit": aggregate["cost_budget_usd_limit"],
        "over_budget": effective_over_budget,
        "blocked_by_budget": effective_over_budget and not bool(user_confirmed_over_budget),
        "user_confirmed_over_budget": bool(user_confirmed_over_budget),
        "budget_interception": {
            "checked_at": now(),
            "hard_block_complete": effective_over_budget and not bool(user_confirmed_over_budget),
            "reason": "OVER_BUDGET_WITHOUT_USER_CONFIRMATION" if effective_over_budget and not bool(user_confirmed_over_budget) else "",
            "remaining_token_ratio": aggregate["remaining_token_ratio"],
            "remaining_cost_ratio": aggregate["remaining_cost_ratio"],
            "scoped_usage_observed": aggregate["aggregation_window"]["scoped_usage_observed"],
        },
        "budget_policy": "over_budget_requires_explicit_user_confirmation_before_complete_allowed",
    }, "budget_record_evidence")


def number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def int_number(value: Any) -> int:
    return int(number(value, 0.0))


def parse_json_text(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except JSONDecodeError:
        return {}


def nested_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(nested_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(nested_values(item))
    elif value is not None:
        values.append(str(value))
    return values


def record_matches_task(record: dict[str, Any], task_id: str) -> bool:
    if not task_id:
        return True
    direct_keys = ("task_id", "task_object_id", "xinao_task_id", "run_id", "trace_id", "workflow_id")
    for key in direct_keys:
        if str(record.get(key) or "") == task_id:
            return True
    metadata = record.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in direct_keys:
            if str(metadata.get(key) or "") == task_id:
                return True
        attrs = parse_json_text(metadata.get("attributes"))
        for key in direct_keys:
            if str(attrs.get(key) or "") == task_id:
                return True
    return task_id in nested_values(record)


def scoped_records(records: list[dict[str, Any]], task_id: str) -> tuple[list[dict[str, Any]], bool]:
    if not task_id:
        return records, False
    scoped = [record for record in records if record_matches_task(record, task_id)]
    return (scoped, True) if scoped else (records, False)


def usage_from_litellm_state(litellm_state: dict[str, Any]) -> dict[str, Any]:
    usage = ((litellm_state.get("redacted_response") or {}).get("usage") or {})
    return {
        "prompt_tokens": int_number(usage.get("prompt_tokens")),
        "completion_tokens": int_number(usage.get("completion_tokens")),
        "total_tokens": int_number(usage.get("total_tokens")),
        "cost_usd": number((litellm_state.get("redacted_response") or {}).get("cost") or usage.get("cost")),
        "trace_count": 1 if usage else 0,
    }


def usage_from_langfuse_state(langfuse_state: dict[str, Any]) -> dict[str, Any]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_usd = 0.0
    trace_count = 0
    for trace in langfuse_state.get("traces") or []:
        metadata = trace.get("metadata") or {}
        attrs = parse_json_text(metadata.get("attributes"))
        if not attrs:
            continue
        trace_count += 1
        prompt_tokens += int_number(attrs.get("llm.token_count.prompt"))
        completion_tokens += int_number(attrs.get("llm.token_count.completion"))
        total_tokens += int_number(attrs.get("llm.token_count.total"))
        cost_usd += number(attrs.get("llm.cost.total") or attrs.get("llm.response.cost"))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_usd": round(cost_usd, 10),
        "trace_count": trace_count,
    }


def aggregate_budget_usage(
    *,
    litellm_state: dict[str, Any],
    langfuse_state: dict[str, Any],
    litellm_events: list[dict[str, Any]] | None = None,
    langfuse_events: list[dict[str, Any]] | None = None,
    task_id: str = "",
    token_budget_limit: int | None = None,
    cost_budget_usd_limit: float | None = None,
) -> dict[str, Any]:
    litellm_events = litellm_events or []
    langfuse_events = langfuse_events or []
    litellm_records, litellm_scoped = scoped_records([litellm_state, *litellm_events], task_id)
    langfuse_records, langfuse_scoped = scoped_records([langfuse_state, *langfuse_events], task_id)
    litellm_usages = [usage_from_litellm_state(state) for state in litellm_records]
    langfuse_usages = [usage_from_langfuse_state(state) for state in langfuse_records]
    litellm_usage = {
        "prompt_tokens": sum(item["prompt_tokens"] for item in litellm_usages),
        "completion_tokens": sum(item["completion_tokens"] for item in litellm_usages),
        "total_tokens": sum(item["total_tokens"] for item in litellm_usages),
        "cost_usd": round(sum(item["cost_usd"] for item in litellm_usages), 10),
        "trace_count": sum(item["trace_count"] for item in litellm_usages),
        "record_count": len([item for item in litellm_usages if item["trace_count"] or item["total_tokens"] or item["cost_usd"]]),
    }
    langfuse_usage = {
        "prompt_tokens": sum(item["prompt_tokens"] for item in langfuse_usages),
        "completion_tokens": sum(item["completion_tokens"] for item in langfuse_usages),
        "total_tokens": sum(item["total_tokens"] for item in langfuse_usages),
        "cost_usd": round(sum(item["cost_usd"] for item in langfuse_usages), 10),
        "trace_count": sum(item["trace_count"] for item in langfuse_usages),
        "record_count": len([item for item in langfuse_usages if item["trace_count"] or item["total_tokens"] or item["cost_usd"]]),
    }
    token_limit = (
        int_number(token_budget_limit)
        if token_budget_limit is not None
        else int_number(os.environ.get("XINAO_TOKEN_BUDGET_LIMIT", DEFAULT_TOKEN_BUDGET_LIMIT))
    )
    cost_limit = (
        number(cost_budget_usd_limit)
        if cost_budget_usd_limit is not None
        else number(os.environ.get("XINAO_COST_BUDGET_USD_LIMIT", DEFAULT_COST_BUDGET_USD_LIMIT))
    )
    actual_prompt = langfuse_usage["prompt_tokens"] or litellm_usage["prompt_tokens"]
    actual_completion = langfuse_usage["completion_tokens"] or litellm_usage["completion_tokens"]
    actual_total = langfuse_usage["total_tokens"] or litellm_usage["total_tokens"]
    actual_cost = langfuse_usage["cost_usd"] or litellm_usage["cost_usd"]
    token_remaining = token_limit - actual_total
    cost_remaining = round(cost_limit - actual_cost, 10)
    return {
        "schema_version": "xinao.budget_usage_aggregation.v1",
        "actual_prompt_tokens": actual_prompt,
        "actual_completion_tokens": actual_completion,
        "actual_total_tokens": actual_total,
        "actual_cost_usd": round(actual_cost, 10),
        "token_budget_limit": token_limit,
        "cost_budget_usd_limit": cost_limit,
        "token_remaining": token_remaining,
        "cost_remaining_usd": cost_remaining,
        "remaining_token_ratio": round(token_remaining / token_limit, 6) if token_limit > 0 else 0,
        "remaining_cost_ratio": round(cost_remaining / cost_limit, 6) if cost_limit > 0 else 0,
        "over_token_budget": actual_total > token_limit,
        "over_cost_budget": actual_cost > cost_limit,
        "over_budget": actual_total > token_limit or actual_cost > cost_limit,
        "actual_usage_observed": bool(litellm_usage["record_count"] or langfuse_usage["record_count"]),
        "aggregation_policy": "prefer_task_scoped_langfuse_traces_when_available_else_task_scoped_litellm_proxy_usage_else_recent_global_usage",
        "aggregation_window": {
            "task_object_id": task_id,
            "scoped_usage_observed": bool(litellm_scoped or langfuse_scoped),
            "litellm_records_considered": len(litellm_records),
            "langfuse_records_considered": len(langfuse_records),
            "litellm_total_records_available": 1 + len(litellm_events),
            "langfuse_total_records_available": 1 + len(langfuse_events),
            "fallback_to_recent_global_usage": bool(task_id and not (litellm_scoped or langfuse_scoped)),
        },
        "sources": {
            "litellm": litellm_usage,
            "langfuse": langfuse_usage,
        },
    }


def build_evidence_fields(
    *,
    task_id: str,
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    over_budget: bool = False,
    user_confirmed_over_budget: bool = False,
    token_budget_limit: int | None = None,
    cost_budget_usd_limit: float | None = None,
    human_visible_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_root = pathlib.Path(runtime_root)
    rollback_plan = write_minimal_rollback_plan(task_id=task_id, runtime_root=runtime_root)
    visible_status = human_visible_status or {
        "source": "codex_default_path",
        "status": "backend_claim_decision_visible_after_gate",
        "current_goal": task_id,
        "current_state": "backend_claim_decision_visible_after_gate",
        "what_is_complete": [],
        "what_is_not_complete": ["human-visible completion must still be read from backend claim decision"],
        "next_action_cn": "继续执行到后端 claim decision 与人类可见状态一致",
        "evidence_only": True,
    }
    task_side_audit_path = runtime_root / "state" / "human_visible_completion_audit" / f"{safe_name(task_id)}.json"
    latest_side_audit_path = runtime_root / "state" / "human_visible_completion_audit" / "latest.json"
    task_side_audit = read_json_if_exists(task_side_audit_path)
    latest_side_audit = read_json_if_exists(latest_side_audit_path)
    if human_visible_side_audit_passed(task_side_audit, task_id=task_id):
        human_visible_side_audit = task_side_audit_path
    elif human_visible_side_audit_passed(latest_side_audit, task_id=task_id):
        human_visible_side_audit = latest_side_audit_path
    else:
        human_visible_side_audit = write_pending_human_visible_side_audit_request(
            task_id=task_id,
            runtime_root=runtime_root,
            human_visible_status=visible_status,
        )
    memory_refs = existing_refs([
        runtime_root / "projections" / "current_context.json",
        runtime_root / "projections" / "current_facts.json",
        runtime_root / "state" / "project_projection_radar" / "latest.json",
        runtime_root / "state" / "project_projection_ops" / "latest.json",
        runtime_root / "event_store" / "events.ndjson",
    ])
    if not memory_refs:
        memory_refs = [str(runtime_root / "state" / "memory_budget_rollback_gate" / "latest.json")]
    evidence_refs = [
        str(runtime_root / "state" / "completion_claim_payloads" / f"{safe_name(task_id)}.json"),
        str(runtime_root / "state" / "codex_default_task_runner" / "latest.json"),
        str(runtime_root / "state" / "langgraph_task_runner" / "latest.json"),
        str(runtime_root / "state" / "temporal_codex_task_workflow" / "latest.json"),
        str(runtime_root / "state" / "dify_completion_claim_bridge" / "latest.json"),
    ]
    return demote_read_model({
        "memory_read_refs": tuple(memory_refs),
        "evidence_write_refs": tuple(evidence_refs),
        "budget_record": build_budget_record(
            task_id=task_id,
            runtime_root=runtime_root,
            over_budget=over_budget,
            user_confirmed_over_budget=user_confirmed_over_budget,
            token_budget_limit=token_budget_limit,
            cost_budget_usd_limit=cost_budget_usd_limit,
        ),
        "rollback_plan_ref": str(rollback_plan),
        "rollback_execution_result": build_rollback_execution_result(
            rollback_plan_ref=str(rollback_plan),
            runtime_root=runtime_root,
        ),
        "human_visible_status": visible_status,
        "human_visible_side_audit_ref": str(human_visible_side_audit),
    }, "claim_evidence_fields")


def build_rollback_execution_result(*, rollback_plan_ref: str, runtime_root: pathlib.Path) -> dict[str, Any]:
    from services.agent_runtime import rollback_executor

    return rollback_executor.prepare_rollback_execution_result(
        rollback_plan_ref=rollback_plan_ref,
        runtime_root=runtime_root,
        execute=False,
    )


def validate_claim_evidence(claim_payload: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    for field in REQUIRED_CLAIM_FIELDS:
        value = claim_payload.get(field)
        if value in (None, "", [], {}, ()):
            missing.append(field)
    budget_record = claim_payload.get("budget_record") or {}
    over_budget_without_confirmation = (
        budget_record.get("over_budget") is True
        and budget_record.get("user_confirmed_over_budget") is not True
    )
    rollback_execution = claim_payload.get("rollback_execution_result") or {}
    rollback_not_executable = bool(rollback_execution) and (
        rollback_execution.get("rollback_executable") is not True
        or rollback_execution.get("claim_evidence_ready") is not True
        or rollback_execution.get("can_cancel_temporal_workflow") is not True
        or "langgraph_checkpoint_restore" not in (rollback_execution.get("rollback_actions_supported") or [])
    )
    human_visible_status = claim_payload.get("human_visible_status") or {}
    human_visible_side_audit_ref = claim_payload.get("human_visible_side_audit_ref") or ""
    human_visible_missing = not isinstance(human_visible_status, dict) or not human_visible_status
    human_visible_side_audit_missing = not isinstance(human_visible_side_audit_ref, str) or not human_visible_side_audit_ref.strip()
    human_visible_side_audit = read_json_if_exists(pathlib.Path(human_visible_side_audit_ref)) if not human_visible_side_audit_missing else {}
    human_visible_side_audit_not_passed = not human_visible_side_audit_missing and not human_visible_side_audit_passed(
        human_visible_side_audit,
        task_id=str(claim_payload.get("task_object_id") or ""),
    )
    blockers = []
    if missing:
        blockers.append("MEMORY_BUDGET_ROLLBACK_EVIDENCE_MISSING")
    if over_budget_without_confirmation:
        blockers.append("OVER_BUDGET_WITHOUT_USER_CONFIRMATION")
    if rollback_not_executable:
        blockers.append("ROLLBACK_EXECUTION_NOT_READY")
    if human_visible_missing:
        blockers.append("HUMAN_VISIBLE_STATUS_MISSING")
    if human_visible_side_audit_missing:
        blockers.append("HUMAN_VISIBLE_SIDE_AUDIT_MISSING")
    if human_visible_side_audit_not_passed:
        blockers.append("EXTERNAL_AI_HUMAN_VISUAL_SIDE_AUDIT_NOT_PASSED")
    passed = (
        not missing
        and not over_budget_without_confirmation
        and not rollback_not_executable
        and not human_visible_missing
        and not human_visible_side_audit_missing
        and not human_visible_side_audit_not_passed
    )
    task_id = str(claim_payload.get("task_object_id") or "unknown_task")
    continuation_plan = (
        {}
        if passed
        else build_continuation_execution_plan(task_id=task_id, blockers=blockers)
    )
    return demote_read_model({
        "schema_version": "xinao.memory_budget_rollback_claim_evidence_validation.v1",
        "generated_at": now(),
        "status": "memory_budget_rollback_claim_evidence_passed" if passed else "memory_budget_rollback_claim_evidence_partial",
        "passed": passed,
        "missing_fields": missing,
        "over_budget_without_confirmation": over_budget_without_confirmation,
        "rollback_not_executable": rollback_not_executable,
        "human_visible_missing": human_visible_missing,
        "human_visible_side_audit_missing": human_visible_side_audit_missing,
        "human_visible_side_audit_not_passed": human_visible_side_audit_not_passed,
        "named_blockers": blockers,
        "completion_claim_blocked_but_execution_must_continue": not passed,
        "default_recursive_continuation_limit": DEFAULT_HUMAN_VISIBLE_RECURSION_LIMIT,
        "continuation_execution_plan": continuation_plan,
        "decision_reason": "memory_budget_rollback_evidence_ready" if passed else ";".join(blockers),
    }, "claim_evidence_validation")


def build(
    *,
    task_id: str = "memory_budget_rollback_gate",
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    over_budget: bool = False,
    user_confirmed_over_budget: bool = False,
    token_budget_limit: int | None = None,
    cost_budget_usd_limit: float | None = None,
) -> dict[str, Any]:
    evidence = build_evidence_fields(
        task_id=task_id,
        runtime_root=runtime_root,
        over_budget=over_budget,
        user_confirmed_over_budget=user_confirmed_over_budget,
        token_budget_limit=token_budget_limit,
        cost_budget_usd_limit=cost_budget_usd_limit,
    )
    validation = validate_claim_evidence(evidence)
    payload = {
        "schema_version": "xinao.memory_budget_rollback_gate.v1",
        "generated_at": now(),
        "active_object_id": ACTIVE_OBJECT_ID,
        "status": "memory_budget_rollback_gate_passed" if validation["passed"] else "memory_budget_rollback_gate_partial",
        "required_claim_fields": list(REQUIRED_CLAIM_FIELDS),
        "evidence": evidence,
        "validation": validation,
        "sentinel": SENTINEL,
    }
    demote_read_model(payload, "memory_budget_rollback_gate_read_model")
    latest = pathlib.Path(runtime_root) / "state" / "memory_budget_rollback_gate" / "latest.json"
    write_json(latest, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate memory/budget/rollback evidence for /completion/claim.")
    parser.add_argument("--task-id", default="memory_budget_rollback_gate")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--over-budget", action="store_true")
    parser.add_argument("--user-confirmed-over-budget", action="store_true")
    parser.add_argument("--token-budget-limit", type=int, default=None)
    parser.add_argument("--cost-budget-usd-limit", type=float, default=None)
    args = parser.parse_args()
    payload = build(
        task_id=args.task_id,
        runtime_root=pathlib.Path(args.runtime_root),
        over_budget=args.over_budget,
        user_confirmed_over_budget=args.user_confirmed_over_budget,
        token_budget_limit=args.token_budget_limit,
        cost_budget_usd_limit=args.cost_budget_usd_limit,
    )
    print(json.dumps({
        "status": payload["status"],
        "validation": payload["validation"],
        "sentinel": payload["sentinel"],
    }, ensure_ascii=False, indent=2))
    print(SENTINEL)
    return 0 if payload["validation"]["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
