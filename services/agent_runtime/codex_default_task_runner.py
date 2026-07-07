import argparse
import asyncio
import datetime as dt
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request
from typing import Any, Literal

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from services.agent_runtime import codex_centric_object_preserving_runtime as runtime
from services.agent_runtime import completion_claim_payload_builder as builder
from services.agent_runtime import memory_budget_rollback_gate, rollback_executor

DEFAULT_RUNTIME = pathlib.Path(r"D:\XINAO_CLEAN_RUNTIME")
SENTINEL = "SENTINEL:XINAO_CODEX_DEFAULT_TASK_RUNNER_PASS"
TASK_BOUND_WORKER_TURN_REQUIRED = True
TASK_BOUND_CODEX_WORKER_REQUIRED = TASK_BOUND_WORKER_TURN_REQUIRED


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def authority_boundary(role: str) -> dict[str, Any]:
    return {
        "source_of_truth": "external_mature_runtime",
        "truth_carriers": [
            "Temporal workflow state",
            "LangGraph checkpoint/store",
            "completion claim gate",
            "policy/verifier evidence",
        ],
        "this_file_role": role,
        "not_source_of_truth": True,
        "not_user_completion": True,
        "pass_means": "default_runner_readback_and_completion_guard_only",
    }


def post_completion_claim(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/completion/claim",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def local_completion_claim(
    payload: dict[str, Any], runtime_root: pathlib.Path = DEFAULT_RUNTIME
) -> dict[str, Any]:
    claim = runtime.CompletionClaim(**payload)
    return runtime.claim_completion_against_runtime_owner(claim, runtime_root).model_dump(
        mode="json"
    )


def worker_task_id(task_id: str) -> str:
    suffix = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in task_id)
    candidate = f"{safe}.default-codex-worker.{suffix}"
    if len(candidate) <= 120:
        return candidate
    digest = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:12]
    return f"default-codex-worker-{digest}-{suffix}"


def build_task_bound_worker_prompt(task_id: str, user_goal: str, marker: str) -> str:
    goal_hash = hashlib.sha256(user_goal.encode("utf-8")).hexdigest() if user_goal else ""
    return f"""You are a task-bound Codex worker turn for the XINAO default runner.

Task id: {task_id}
User goal sha256: {goal_hash}

Bounded worker instruction:
- Treat the goal text as semantic input only.
- Do not edit files.
- Do not make a completion claim.
- Return a compact JSON object with task_id, user_goal_sha256, worker_role, and result_marker.
- The result_marker value must be {marker}.

Final line must contain exactly: {marker}
"""


def codex_worker_evidence_from_durable(durable: dict[str, Any]) -> dict[str, Any]:
    activities = list(durable.get("activities") or [])
    activity = next(
        (item for item in activities if item.get("activity") == "codex_worker_turn"), {}
    )
    evidence = {
        "activity_status": activity.get("status", ""),
        "task_bound_worker": activity.get("task_bound_worker") is True,
        "fallback_canary_only": activity.get("fallback_canary_only") is True,
        "codex_jsonl_is_execution_evidence": activity.get("codex_jsonl_is_execution_evidence")
        is True,
        "jsonl_path": activity.get("jsonl_path", ""),
        "jsonl_exists": activity.get("jsonl_exists") is True,
        "final_path": activity.get("final_path", ""),
        "expected_marker": activity.get("expected_marker", ""),
        "expected_marker_seen": activity.get("expected_marker_seen") is True,
        "worker_task_id": activity.get("worker_task_id", ""),
        "named_blocker": activity.get("named_blocker", ""),
        "command_surface": activity.get("command_surface", ""),
        "execute_worker_turn": activity.get("execute_worker_turn") is True,
        "actual_provider_id": activity.get("actual_provider_id", ""),
        "actual_provider_family": activity.get("actual_provider_family", ""),
        "actual_carrier_provider_id": activity.get("actual_carrier_provider_id", ""),
    }
    evidence["accepted_as_task_bound_worker_evidence"] = (
        evidence["activity_status"] == "activity_gate_checked"
        and evidence["task_bound_worker"] is True
        and evidence["fallback_canary_only"] is False
        and evidence["codex_jsonl_is_execution_evidence"] is True
        and evidence["jsonl_exists"] is True
        and evidence["expected_marker_seen"] is True
    )
    return evidence


def run_task(
    *,
    task_id: str,
    user_goal: str,
    mode: Literal["rejected", "partial", "complete"] = "partial",
    runtime_root: pathlib.Path = DEFAULT_RUNTIME,
    base_url: str = "http://127.0.0.1:19531",
    allow_complete_fixture: bool = False,
    use_temporal_binding: bool = True,
    use_live_temporal: bool = True,
    allow_local_temporal_compat_rescue: bool = False,
    execute_worker_turn: bool | None = None,
    execute_codex_worker: bool = TASK_BOUND_CODEX_WORKER_REQUIRED,
    trigger_rollback_on_partial: bool = False,
    continuation_attempt: int = 0,
) -> dict[str, Any]:
    worker_turn_enabled = (
        execute_codex_worker if execute_worker_turn is None else execute_worker_turn
    )
    if use_temporal_binding:
        from services.agent_runtime import temporal_codex_task_workflow

        if not use_live_temporal and not allow_local_temporal_compat_rescue:
            state = {
                "schema_version": "xinao.codex_default_task_runner.v1",
                "generated_at": now(),
                "status": "blocked_temporal_live_route_required",
                "named_blocker": "BLOCKED_TEMPORAL_LIVE_ROUTE_REQUIRED",
                "message": "Default runner requires live Temporal Event History; local durable flow is rescue-only and must be explicitly allowed.",
                "not_source_of_truth": True,
                "not_user_completion": True,
                "authority_boundary": authority_boundary("default_runner_temporal_live_route_gate"),
                "task_object_id": task_id,
                "user_goal": user_goal,
                "requested_mode": mode,
                "carrier_policy": "live_temporal_required",
                "durable_default_enforced": True,
                "temporal_live_route_required": True,
                "temporal_compat_rescue_allowed": False,
                "legacy_completion_gate_fallback": False,
                "gate_source": "temporal_live_route_hard_gate",
                "required_endpoint": "/completion/claim",
                "claim_path": "",
                "decision": {
                    "status": "blocked",
                    "stop_allowed": False,
                    "not_source_of_truth": True,
                    "not_user_completion": True,
                    "authority_boundary": authority_boundary(
                        "default_runner_temporal_live_route_gate_decision"
                    ),
                },
                "complete_allowed": False,
                "stop_allowed": False,
                "frontier_preserved": True,
                "next_action": "Start or repair the live Temporal route, then re-run through Server Event History; do not create a local-run default.",
                "sentinel": SENTINEL,
            }
            latest = runtime_root / "state" / "codex_default_task_runner" / "latest.json"
            events = runtime_root / "state" / "codex_default_task_runner" / "events.ndjson"
            write_json(latest, state)
            events.parent.mkdir(parents=True, exist_ok=True)
            with events.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(state, ensure_ascii=False) + "\n")
            return state

        temporal_mode = "complete" if mode == "complete" and allow_complete_fixture else "partial"
        marker = temporal_codex_task_workflow.TASK_BOUND_CODEX_WORKER_MARKER
        task_bound_prompt = (
            build_task_bound_worker_prompt(task_id, user_goal, marker)
            if worker_turn_enabled
            else ""
        )
        task_bound_worker_id = worker_task_id(task_id) if worker_turn_enabled else ""
        if use_live_temporal:
            durable = asyncio.run(
                temporal_codex_task_workflow.run_live_temporal_workflow(
                    {
                        "task_id": task_id,
                        "user_goal": user_goal,
                        "mode": temporal_mode,
                        "runtime_root": str(runtime_root),
                        "allow_complete_fixture": allow_complete_fixture,
                        "source_refs": [],
                        "runtime_subject_loop_required": list(
                            temporal_codex_task_workflow.langgraph_task_runner.RUNTIME_SUBJECT_LOOP_REQUIRED
                        ),
                        "root_repair_constraints": list(
                            temporal_codex_task_workflow.langgraph_task_runner.ROOT_REPAIR_CONSTRAINTS
                        ),
                        "minimum_reality_contact_required": True,
                        "no_new_parallel_control_surface": True,
                        "execute_worker_turn": worker_turn_enabled,
                        "execute_codex_worker": execute_codex_worker,
                        "execute_codex_worker_legacy_alias": execute_codex_worker,
                        "codex_worker_prompt": task_bound_prompt,
                        "codex_worker_task_id": task_bound_worker_id,
                        "codex_worker_expected_marker": marker,
                        "codex_worker_timeout_sec": 300,
                        "task_queue": temporal_codex_task_workflow.DEFAULT_TASK_QUEUE,
                    }
                )
            )
            temporal_codex_task_workflow.persist_workflow_result(runtime_root, durable)
        else:
            durable = temporal_codex_task_workflow.run_local_durable_flow(
                task_id=task_id,
                user_goal=user_goal,
                mode=temporal_mode,
                runtime_root=runtime_root,
                allow_complete_fixture=allow_complete_fixture,
                execute_worker_turn=worker_turn_enabled,
                execute_codex_worker=execute_codex_worker,
                codex_worker_prompt=task_bound_prompt,
                codex_worker_task_id=task_bound_worker_id,
                codex_worker_expected_marker=marker,
                codex_worker_timeout_sec=300,
            )
        codex_worker_evidence = codex_worker_evidence_from_durable(durable)
        worker_required_and_missing = (
            worker_turn_enabled
            and not codex_worker_evidence["accepted_as_task_bound_worker_evidence"]
        )
        decision = dict(durable["completion_decision"])
        decision["not_source_of_truth"] = True
        decision["not_user_completion"] = True
        decision["authority_boundary"] = authority_boundary(
            "default_runner_temporal_decision_readback"
        )
        state = {
            "schema_version": "xinao.codex_default_task_runner.v1",
            "generated_at": now(),
            "status": (
                "default_task_temporal_binding_partial_continue"
                if worker_required_and_missing
                else "default_task_live_temporal_binding_checked"
                if use_live_temporal
                else "default_task_temporal_binding_checked"
            ),
            "not_source_of_truth": True,
            "not_user_completion": True,
            "authority_boundary": authority_boundary("default_runner_temporal_readback"),
            "task_object_id": task_id,
            "user_goal": user_goal,
            "requested_mode": mode,
            "carrier_policy": "durable_default",
            "durable_default_enforced": True,
            "temporal_live_route_required": True,
            "temporal_compat_rescue_allowed": bool(allow_local_temporal_compat_rescue),
            "task_bound_worker_turn_required": bool(worker_turn_enabled),
            "task_bound_codex_worker_required": bool(execute_codex_worker),
            "execute_codex_worker_legacy_alias": bool(execute_codex_worker),
            "codex_worker_evidence": codex_worker_evidence,
            "named_blocker": codex_worker_evidence.get("named_blocker", "")
            if worker_required_and_missing
            else "",
            "legacy_completion_gate_fallback": False,
            "gate_source": "live_temporal_codex_task_workflow"
            if use_live_temporal
            else "local_temporal_compat_rescue",
            "required_endpoint": "/completion/claim",
            "claim_path": "",
            "decision": decision,
            "complete_allowed": False
            if worker_required_and_missing
            else durable["user_task_complete"],
            "stop_allowed": False
            if worker_required_and_missing
            else decision.get("stop_allowed") is True,
            "frontier_preserved": decision.get("status") != "complete_allowed",
            "next_action": "Repair task-bound Codex worker evidence, then continue Temporal Server-bound durable task frontier."
            if worker_required_and_missing
            else None
            if durable["user_task_complete"]
            else "Continue Temporal Server-bound durable task frontier."
            if use_live_temporal
            else "Compatibility rescue only; promote no completion claim without Server Event History.",
            "temporal_workflow": durable,
            "current_task_owner": durable.get("current_task_owner", {}),
            "sentinel": SENTINEL,
        }
        latest = runtime_root / "state" / "codex_default_task_runner" / "latest.json"
        events = runtime_root / "state" / "codex_default_task_runner" / "events.ndjson"
        write_json(latest, state)
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(state, ensure_ascii=False) + "\n")
        return state

    if mode == "complete" and not allow_complete_fixture:
        mode = "partial"
    next_action = (
        "Continue via default Codex path; only /completion/claim may convert this to complete."
    )
    claim_payload = builder.build_claim_payload(
        task_id=task_id,
        mode=mode,
        user_goal=user_goal,
        next_action=next_action,
        runtime_root=runtime_root,
    )
    claim_path = builder.write_claim_payload(payload=claim_payload, runtime_root=runtime_root)
    gate_source = "local_runtime_fallback"
    try:
        decision = post_completion_claim(base_url, claim_payload)
        gate_source = "api_post_completion_claim"
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        decision = local_completion_claim(claim_payload, runtime_root)
    rollback_execution_result = claim_payload.get("rollback_execution_result", {})
    if trigger_rollback_on_partial and decision.get("status") != "complete_allowed":
        rollback_execution_result = rollback_executor.prepare_rollback_execution_result(
            rollback_plan_ref=claim_payload.get("rollback_plan_ref", ""),
            runtime_root=runtime_root,
            execute=True,
        )
    evidence_validation = memory_budget_rollback_gate.validate_claim_evidence(claim_payload)
    continuation_plan = evidence_validation.get("continuation_execution_plan") or {}
    if continuation_plan:
        continuation_plan["current_attempt"] = continuation_attempt
        continuation_plan["remaining_recursive_continuation_attempts"] = max(
            0,
            int(continuation_plan.get("default_recursive_continuation_limit", 10))
            - continuation_attempt,
        )

    legacy_decision_status = str(decision.get("status") or "")
    legacy_gate_complete_allowed = legacy_decision_status == "complete_allowed"
    production_completion_forbidden = True
    state = {
        "schema_version": "xinao.codex_default_task_runner.v1",
        "generated_at": now(),
        "status": "default_task_legacy_completion_gate_checked",
        "not_source_of_truth": True,
        "not_user_completion": True,
        "authority_boundary": authority_boundary("default_runner_legacy_gate_readback"),
        "task_object_id": task_id,
        "user_goal": user_goal,
        "requested_mode": mode,
        "carrier_policy": "legacy_completion_gate_explicit_fallback",
        "durable_default_enforced": False,
        "legacy_completion_gate_fallback": True,
        "production_completion_forbidden": production_completion_forbidden,
        "legacy_gate_complete_allowed_readback": legacy_gate_complete_allowed,
        "gate_source": gate_source,
        "required_endpoint": "/completion/claim",
        "claim_path": str(claim_path),
        "completion_evidence": {
            "memory_read_refs": claim_payload.get("memory_read_refs", []),
            "evidence_write_refs": claim_payload.get("evidence_write_refs", []),
            "budget_record": claim_payload.get("budget_record", {}),
            "rollback_plan_ref": claim_payload.get("rollback_plan_ref", ""),
            "rollback_execution_result": rollback_execution_result,
            "human_visible_status": claim_payload.get("human_visible_status", {}),
            "human_visible_side_audit_ref": claim_payload.get("human_visible_side_audit_ref", ""),
        },
        "continuation_execution_plan": continuation_plan,
        "completion_blocked_but_execution_must_continue": bool(continuation_plan),
        "default_recursive_continuation_limit": continuation_plan.get(
            "default_recursive_continuation_limit", 10
        )
        if continuation_plan
        else 10,
        "continuation_attempt": continuation_attempt,
        "rollback_triggered": trigger_rollback_on_partial
        and decision.get("status") != "complete_allowed",
        "decision": {
            **decision,
            "not_source_of_truth": True,
            "not_user_completion": True,
            "authority_boundary": authority_boundary("default_runner_legacy_decision_readback"),
        },
        "complete_allowed": False,
        "stop_allowed": False,
        "frontier_preserved": True,
        "next_action": next_action,
        "named_blocker": (
            "LEGACY_COMPLETION_GATE_FALLBACK_NOT_PRODUCTION_AUTHORITY"
            if legacy_gate_complete_allowed
            else "LEGACY_COMPLETION_GATE_FALLBACK_PARTIAL_CONTINUE"
        ),
        "sentinel": SENTINEL,
    }
    latest = runtime_root / "state" / "codex_default_task_runner" / "latest.json"
    events = runtime_root / "state" / "codex_default_task_runner" / "events.ndjson"
    write_json(latest, state)
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(state, ensure_ascii=False) + "\n")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Codex default task runner with mandatory /completion/claim gate."
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--user-goal", default="")
    parser.add_argument("--mode", choices=("rejected", "partial", "complete"), default="partial")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--base-url", default="http://127.0.0.1:19531")
    parser.add_argument("--allow-complete-fixture", action="store_true")
    parser.add_argument(
        "--use-temporal-binding",
        action="store_true",
        help="Compatibility flag; durable Temporal binding is the default.",
    )
    parser.add_argument(
        "--live-temporal",
        action="store_true",
        help="Compatibility flag; live Temporal is the default when temporal binding is enabled.",
    )
    parser.add_argument(
        "--local-temporal-compat-rescue",
        action="store_true",
        help="Explicit rescue-only escape hatch for the old local-run compatibility flow.",
    )
    parser.add_argument(
        "--execute-worker-turn",
        dest="execute_worker_turn",
        action="store_true",
        default=None,
        help="Inside Temporal, dispatch the task-bound ProviderRouter worker turn. This is the default.",
    )
    parser.add_argument(
        "--skip-worker-turn",
        dest="execute_worker_turn",
        action="store_false",
        help="Compatibility-only escape hatch for legacy fixture tests; not valid for production completion.",
    )
    parser.add_argument(
        "--execute-codex-worker",
        dest="execute_codex_worker",
        action="store_true",
        default=None,
        help="Legacy alias for --execute-worker-turn.",
    )
    parser.add_argument(
        "--skip-codex-worker",
        dest="execute_codex_worker",
        action="store_false",
        help="Legacy alias for --skip-worker-turn.",
    )
    parser.add_argument(
        "--legacy-completion-gate",
        action="store_true",
        help="Explicit fallback to the old non-durable completion gate path.",
    )
    parser.add_argument("--trigger-rollback-on-partial", action="store_true")
    parser.add_argument("--continuation-attempt", type=int, default=0)
    args = parser.parse_args()

    if args.execute_worker_turn is None:
        execute_worker_turn = (
            True if args.execute_codex_worker is None else bool(args.execute_codex_worker)
        )
    else:
        execute_worker_turn = bool(args.execute_worker_turn)
    execute_codex_worker = bool(args.execute_codex_worker)
    state = run_task(
        task_id=args.task_id,
        user_goal=args.user_goal,
        mode=args.mode,
        runtime_root=pathlib.Path(args.runtime_root),
        base_url=args.base_url,
        allow_complete_fixture=args.allow_complete_fixture,
        use_temporal_binding=not args.legacy_completion_gate,
        use_live_temporal=not args.local_temporal_compat_rescue,
        allow_local_temporal_compat_rescue=args.local_temporal_compat_rescue,
        execute_worker_turn=execute_worker_turn,
        execute_codex_worker=execute_codex_worker,
        trigger_rollback_on_partial=args.trigger_rollback_on_partial,
        continuation_attempt=args.continuation_attempt,
    )
    print(
        json.dumps(
            {
                "status": state["status"],
                "decision": state["decision"],
                "claim_path": state["claim_path"],
                "sentinel": state["sentinel"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(SENTINEL)
    return (
        0
        if state["status"]
        in {
            "default_task_temporal_binding_checked",
            "default_task_live_temporal_binding_checked",
            "default_task_legacy_completion_gate_checked",
        }
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
