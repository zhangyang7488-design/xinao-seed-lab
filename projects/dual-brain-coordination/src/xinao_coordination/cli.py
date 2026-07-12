"""JSON-first local CLI for Codex, Grok, Admin, and human operators."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .a2a_adapter import export_task_dict
from .agent_controller import AgentOperationController
from .errors import CoordinationError, ValidationError
from .service import CoordinationService


def _json_object(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("expected a JSON object")
    return parsed


def _json_list(value: str) -> list[dict[str, object]]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise argparse.ArgumentTypeError("expected a JSON array of objects")
    return parsed


def _json_str_list(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise argparse.ArgumentTypeError("expected a JSON array of strings")
    return parsed


def _idem(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--idempotency-key")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xinao-coord",
        description="Durable local dual-brain discussion and Admin task coordination.",
    )
    parser.add_argument("--db", type=Path, help="SQLite path; defaults to the D: runtime state")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("doctor")
    sub.add_parser("sweep")
    sub.add_parser("self-smoke")
    backup = sub.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)

    route = sub.add_parser("route-assess")
    for name in (
        "uncertainty",
        "impact",
        "disagreement",
        "complementarity",
        "parallelism",
        "novelty",
        "latency-cost",
        "coordination-cost",
        "context-cost",
    ):
        route.add_argument(f"--{name}", type=float, default=0.0)
    route.add_argument("--needs-artifact", action="store_true")
    route.add_argument("--benefit-weights", type=_json_object)
    route.add_argument("--cost-weights", type=_json_object)
    route.add_argument("--discussion-margin", type=float, default=0.0)
    route.add_argument(
        "--requested-mode",
        choices=["direct", "discuss", "task", "discuss_then_task", "background", "hybrid"],
    )

    p = sub.add_parser("thread-open")
    p.add_argument("--actor", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--body")
    p.add_argument("--thread-id")
    p.add_argument("--ttl-seconds", type=int, default=7_200)
    p.add_argument("--max-rounds", type=int, default=24)
    p.add_argument("--metadata", type=_json_object, default={})
    _idem(p)

    p = sub.add_parser("thread-post")
    p.add_argument("--actor", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--kind", default="note")
    p.add_argument("--recipient", default="*")
    p.add_argument("--expected-version", type=int)
    _idem(p)

    p = sub.add_parser("thread-close")
    p.add_argument("--actor", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument(
        "--decision", required=True, choices=["accept", "reject", "each_close", "escalate_to_user"]
    )
    p.add_argument("--resolution-key", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--expected-version", type=int)
    _idem(p)

    # T5 discuss/close semantic surface (thin wrappers over thread-close CAS)
    p = sub.add_parser("propose-close")
    p.add_argument("--actor", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--decision-hash", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument(
        "--decision", default="accept", choices=["accept", "reject", "each_close", "escalate_to_user"]
    )
    p.add_argument("--proposal-id")
    p.add_argument("--expected-version", type=int)
    p.add_argument("--unresolved-points", type=_json_str_list, default=[])
    _idem(p)

    p = sub.add_parser("respond")
    p.add_argument("--actor", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--decision-hash", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument(
        "--decision", default="accept", choices=["accept", "reject", "each_close", "escalate_to_user"]
    )
    p.add_argument("--proposal-id")
    p.add_argument("--expected-version", type=int)
    p.add_argument("--unresolved-points", type=_json_str_list, default=[])
    _idem(p)

    p = sub.add_parser("thread-get")
    p.add_argument("--thread-id", required=True)
    p = sub.add_parser("thread-list")
    p.add_argument("--state")
    p.add_argument("--limit", type=int, default=100)

    p = sub.add_parser("operation-submit")
    p.add_argument("--actor", choices=["user", "codex"], default="codex")
    prompt_source = p.add_mutually_exclusive_group(required=True)
    prompt_source.add_argument("--prompt")
    prompt_source.add_argument("--prompt-file", type=Path)
    p.add_argument("--session", default="xinao-main")
    p.add_argument("--cwd", type=Path, default=Path.cwd())
    p.add_argument("--deadline-seconds", type=int, default=1_800)
    p.add_argument("--max-attempts", type=int, default=1)
    p.add_argument("--replay-safe", action="store_true")
    p.add_argument("--metadata", type=_json_object, default={})
    p.add_argument("--idempotency-key", required=True)

    p = sub.add_parser("operation-get")
    p.add_argument("--operation-id", required=True)
    p = sub.add_parser("operation-list")
    p.add_argument("--state")
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("operation-cancel")
    p.add_argument("--actor", choices=["user", "codex"], default="codex")
    p.add_argument("--operation-id", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("operation-reconcile")
    p.add_argument("--operation-id")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--max-runtime-seconds", type=int, default=120)

    p = sub.add_parser("task-dispatch")
    p.add_argument("--actor", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--source-thread-id")
    p.add_argument("--explicit-non-consensus", action="store_true")
    p.add_argument("--priority", type=int, default=100)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--task-id")
    p.add_argument("--metadata", type=_json_object, default={})
    _idem(p)

    p = sub.add_parser("task-list")
    p.add_argument("--state")
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("task-get")
    p.add_argument("--task-id", required=True)

    p = sub.add_parser("task-claim")
    p.add_argument("--worker-id", default="admin")
    p.add_argument("--lease-seconds", type=int, default=300)
    _idem(p)

    for command in ("task-start", "task-heartbeat"):
        p = sub.add_parser(command)
        p.add_argument("--task-id", required=True)
        p.add_argument("--lease-token", required=True)
        if command == "task-heartbeat":
            p.add_argument("--lease-seconds", type=int, default=300)
        _idem(p)

    p = sub.add_parser("task-complete")
    p.add_argument("--task-id", required=True)
    p.add_argument("--lease-token", required=True)
    p.add_argument("--result-summary", required=True)
    p.add_argument("--evidence", type=_json_list, required=True)
    p.add_argument("--artifacts", type=_json_list, default=[])
    _idem(p)

    p = sub.add_parser("task-fail")
    p.add_argument("--task-id", required=True)
    p.add_argument("--lease-token", required=True)
    p.add_argument("--error", required=True)
    p.add_argument("--no-retry", action="store_true")
    p.add_argument("--retry-delay-seconds", type=int, default=0)
    _idem(p)

    for command in ("task-pause", "task-resume", "task-cancel"):
        p = sub.add_parser(command)
        p.add_argument("--actor", required=True)
        p.add_argument("--task-id", required=True)
        p.add_argument("--reason", required=True)
        _idem(p)

    p = sub.add_parser("artifact-add")
    p.add_argument("--actor", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--path", type=Path, required=True)
    p.add_argument("--name")
    p.add_argument("--media-type", default="application/octet-stream")
    _idem(p)

    p = sub.add_parser("notification-pull")
    p.add_argument("--actor", required=True)
    p.add_argument("--recipient", required=True)
    p.add_argument("--adapter-id", required=True)
    p.add_argument("--lease-seconds", type=int, default=60)
    _idem(p)

    p = sub.add_parser("notification-ack")
    p.add_argument("--actor", required=True)
    p.add_argument("--notification-id", required=True)
    p.add_argument("--lease-token", required=True)
    _idem(p)

    p = sub.add_parser("receipt-record")
    p.add_argument("--actor", required=True)
    p.add_argument("--item-type", required=True)
    p.add_argument("--item-id", required=True)
    p.add_argument("--receipt-type", default="observed")

    p = sub.add_parser("events")
    p.add_argument("--stream-type")
    p.add_argument("--stream-id")
    p.add_argument("--after-seq", type=int, default=0)
    p.add_argument("--limit", type=int, default=200)

    p = sub.add_parser("a2a-export")
    p.add_argument("--task-id", required=True)

    # T1+T2+T5 vertical slice: explicit promote, stop, AMQ thin bind
    p = sub.add_parser("promote")
    p.add_argument("--actor", required=True)
    p.add_argument("--source-thread-id", required=True)
    p.add_argument("--decision-hash", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--owner", default="admin")
    p.add_argument("--writer-scope", default="default")
    p.add_argument("--acceptance")
    p.add_argument("--budget")
    p.add_argument("--stop-scope", default="global")
    p.add_argument("--priority", type=int, default=100)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--task-id")
    p.add_argument("--metadata", type=_json_object, default={})
    _idem(p)

    p = sub.add_parser("stop")
    p.add_argument("--actor", default="user")
    p.add_argument("--reason", required=True)
    p.add_argument("--scope", default="global")
    p.add_argument("--no-cancel-tasks", action="store_true")
    _idem(p)

    p = sub.add_parser("stop-clear")
    p.add_argument("--actor", default="user")
    p.add_argument("--reason", required=True)
    _idem(p)

    sub.add_parser("stop-status")

    # T6/T8: advisory route already via route-assess; M-BG explicit only
    sub.add_parser("mbg-status")
    sub.add_parser("mkeep-status")
    p = sub.add_parser("mkeep-observe")
    p.add_argument("--snapshot", type=_json_object, required=True)
    p.add_argument("--binding", type=_json_object)
    p.add_argument("--expected-binding", type=_json_object)
    p.add_argument("--pause-active", action="store_true")
    p = sub.add_parser("mbg-dispatch")
    p.add_argument("--actor", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--session")
    p.add_argument("--cwd", type=Path)
    p.add_argument("--deadline-seconds", type=int, default=1800)
    p.add_argument("--max-attempts", type=int, default=1)
    p.add_argument("--start-transport", action="store_true")
    _idem(p)

    p = sub.add_parser("mbg-finish")
    p.add_argument("--actor", default="admin")
    p.add_argument("--task-id", required=True)
    p.add_argument("--lease-token", required=True)
    p.add_argument("--result-summary", required=True)
    p.add_argument("--fail", action="store_true")
    p.add_argument("--error")
    p.add_argument("--evidence", type=_json_object)
    _idem(p)

    sub.add_parser(
        "temporal-status",
        description=(
            "T9 Temporal policy probe (mode/connectivity/poller_count). "
            "Live mode is env-only: XINAO_TEMPORAL_LIVE=1 (no --live flag)."
        ),
    )
    p = sub.add_parser(
        "temporal-start-promoted",
        description=(
            "Explicit promoted-task Temporal start. JSON includes mode, run_id, replayed. "
            "Live mode is env-only: XINAO_TEMPORAL_LIVE=1 (no --live flag)."
        ),
    )
    p.add_argument("--actor", required=True)
    p.add_argument("--task-id", required=True)
    _idem(p)

    p = sub.add_parser("amq-send")
    p.add_argument("--me", required=True, help="AMQ handle or kernel role")
    p.add_argument("--to", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--subject", default="")
    p.add_argument("--kind", default="status")
    p.add_argument("--thread")
    p.add_argument("--amq-root", type=Path)
    p.add_argument("--amq-bin", type=Path)

    p = sub.add_parser("amq-ingest")
    p.add_argument("--recipient-role", required=True, help="kernel role that drains inbox")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--amq-root", type=Path)
    p.add_argument("--amq-bin", type=Path)

    p = sub.add_parser("amq-outbox-flush")
    p.add_argument("--sender-role", required=True)
    p.add_argument("--recipient-role", required=True)
    p.add_argument("--max-items", type=int, default=10)
    p.add_argument("--amq-root", type=Path)
    p.add_argument("--amq-bin", type=Path)

    return parser


def _self_smoke(service: CoordinationService) -> dict[str, object]:
    suffix = __import__("uuid").uuid4().hex
    opened = service.open_thread(
        actor="grok_4_5",
        title="self smoke",
        body="proposal",
        idempotency_key=f"smoke-open-{suffix}",
    )
    thread = opened["thread"]
    assert isinstance(thread, dict)
    thread_id = thread["thread_id"]
    service.close_thread(
        actor="grok_4_5",
        thread_id=thread_id,
        decision="accept",
        resolution_key="smoke-v1",
        summary="accept",
        idempotency_key=f"smoke-close-a-{suffix}",
    )
    closed = service.close_thread(
        actor="codex",
        thread_id=thread_id,
        decision="accept",
        resolution_key="smoke-v1",
        summary="accept",
        idempotency_key=f"smoke-close-b-{suffix}",
    )
    task_result = service.dispatch_task(
        actor="codex",
        title="self smoke task",
        goal="exercise lease and evidence",
        source_thread_id=thread_id,
        idempotency_key=f"smoke-dispatch-{suffix}",
    )
    task = task_result["task"]
    assert isinstance(task, dict)
    claimed = service.claim_task(idempotency_key=f"smoke-claim-{suffix}")
    claimed_task = claimed["task"]
    assert isinstance(claimed_task, dict)
    if claimed_task["task_id"] != task["task_id"]:
        raise RuntimeError("self-smoke database was not empty; claimed a different task")
    token = str(claimed["lease_token"])
    service.start_task(task_id=task["task_id"], lease_token=token, idempotency_key=f"smoke-start-{suffix}")
    completed = service.complete_task(
        task_id=task["task_id"],
        lease_token=token,
        result_summary="self smoke complete",
        evidence=[{"kind": "self_smoke", "ok": True}],
        idempotency_key=f"smoke-complete-{suffix}",
    )
    final_thread = closed["thread"]
    final_task = completed["task"]
    assert isinstance(final_thread, dict) and isinstance(final_task, dict)
    return {
        "ok": final_thread["state"] == "ACCEPTED" and final_task["state"] == "completed",
        "action": "self-smoke",
        "thread_id": thread_id,
        "thread_state": final_thread["state"],
        "task_id": task["task_id"],
        "task_state": final_task["state"],
        "health": service.db.health(),
    }


def execute(args: argparse.Namespace, service: CoordinationService) -> dict[str, object]:
    command = args.command
    if command.startswith("operation-") and os.environ.get(
        "XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS", ""
    ).strip().lower() not in {"1", "true", "yes"}:
        raise ValidationError(
            "agent operations are experimental and disabled on the default route",
            details={"enable_with": "XINAO_COORD_EXPERIMENTAL_AGENT_OPERATIONS=1"},
        )
    if command in {"status", "doctor"}:
        return service.status()
    if command == "sweep":
        return service.sweep()
    if command == "self-smoke":
        return _self_smoke(service)
    if command == "backup":
        return service.backup(args.output)
    if command == "route-assess":
        return service.assess(
            {
                "uncertainty": args.uncertainty,
                "impact": args.impact,
                "disagreement": args.disagreement,
                "complementarity": args.complementarity,
                "parallelism": args.parallelism,
                "novelty": args.novelty,
                "latency_cost": args.latency_cost,
                "coordination_cost": args.coordination_cost,
                "context_cost": args.context_cost,
                "needs_artifact": args.needs_artifact,
                "requested_mode": args.requested_mode,
                "benefit_weights": args.benefit_weights,
                "cost_weights": args.cost_weights,
                "discussion_margin": args.discussion_margin,
            }
        )
    if command == "thread-open":
        return service.open_thread(
            actor=args.actor,
            title=args.title,
            body=args.body,
            thread_id=args.thread_id,
            ttl_seconds=args.ttl_seconds,
            max_rounds=args.max_rounds,
            metadata=args.metadata,
            idempotency_key=args.idempotency_key,
        )
    if command == "thread-post":
        return service.post_message(
            actor=args.actor,
            thread_id=args.thread_id,
            body=args.body,
            kind=args.kind,
            recipient=args.recipient,
            expected_version=args.expected_version,
            idempotency_key=args.idempotency_key,
        )
    if command == "thread-close":
        return service.close_thread(
            actor=args.actor,
            thread_id=args.thread_id,
            decision=args.decision,
            resolution_key=args.resolution_key,
            summary=args.summary,
            expected_version=args.expected_version,
            idempotency_key=args.idempotency_key,
        )
    if command == "propose-close":
        return service.propose_close(
            actor=args.actor,
            thread_id=args.thread_id,
            decision_hash=args.decision_hash,
            summary=args.summary,
            decision=args.decision,
            proposal_id=args.proposal_id,
            expected_version=args.expected_version,
            unresolved_points=list(args.unresolved_points or []),
            idempotency_key=args.idempotency_key,
        )
    if command == "respond":
        return service.respond(
            actor=args.actor,
            thread_id=args.thread_id,
            decision_hash=args.decision_hash,
            summary=args.summary,
            decision=args.decision,
            proposal_id=args.proposal_id,
            expected_version=args.expected_version,
            unresolved_points=list(args.unresolved_points or []),
            idempotency_key=args.idempotency_key,
        )
    if command == "thread-get":
        return service.get_thread(args.thread_id)
    if command == "thread-list":
        return service.list_threads(state=args.state, limit=args.limit)
    if command == "operation-submit":
        prompt = args.prompt
        if args.prompt_file is not None:
            prompt = args.prompt_file.read_text(encoding="utf-8")
        controller = AgentOperationController(service.db.path)
        return controller.submit_and_start(
            actor=args.actor,
            prompt=prompt,
            session_name=args.session,
            cwd=args.cwd,
            deadline_seconds=args.deadline_seconds,
            max_attempts=args.max_attempts,
            replay_safe=args.replay_safe,
            idempotency_key=args.idempotency_key,
            metadata=args.metadata,
        )
    if command == "operation-get":
        return AgentOperationController(service.db.path).store.get(args.operation_id)
    if command == "operation-list":
        return AgentOperationController(service.db.path).store.list(state=args.state, limit=args.limit)
    if command == "operation-cancel":
        return AgentOperationController(service.db.path).store.request_cancel(
            args.operation_id,
            actor=args.actor,
            reason=args.reason,
        )
    if command == "operation-reconcile":
        return AgentOperationController(service.db.path).reconcile(
            args.operation_id,
            limit=args.limit,
            max_runtime_seconds=args.max_runtime_seconds,
        )
    if command == "mbg-status":
        return service.mbg_status()
    if command == "mkeep-status":
        return service.mkeep_status()
    if command == "mkeep-observe":
        return service.mkeep_observe(
            snapshot=args.snapshot,
            binding=args.binding,
            expected_binding=args.expected_binding,
            pause_active=args.pause_active,
        )
    if command == "mbg-dispatch":
        return service.mbg_dispatch(
            actor=args.actor,
            task_id=args.task_id,
            session_name=args.session,
            cwd=args.cwd,
            deadline_seconds=args.deadline_seconds,
            max_attempts=args.max_attempts,
            idempotency_key=args.idempotency_key,
            start_transport=bool(args.start_transport),
        )
    if command == "mbg-finish":
        evidence = args.evidence
        if isinstance(evidence, dict):
            evidence = [evidence]
        return service.mbg_finish(
            actor=args.actor,
            task_id=args.task_id,
            lease_token=args.lease_token,
            result_summary=args.result_summary,
            evidence=evidence,
            success=not bool(args.fail),
            error=args.error,
            idempotency_key=args.idempotency_key,
        )
    if command == "temporal-status":
        return service.temporal_status()
    if command == "temporal-start-promoted":
        return service.temporal_start_promoted(
            actor=args.actor,
            task_id=args.task_id,
            idempotency_key=args.idempotency_key,
        )
    if command == "task-dispatch":
        return service.dispatch_task(
            actor=args.actor,
            title=args.title,
            goal=args.goal,
            source_thread_id=args.source_thread_id,
            explicit_non_consensus=args.explicit_non_consensus,
            priority=args.priority,
            max_attempts=args.max_attempts,
            task_id=args.task_id,
            metadata=args.metadata,
            idempotency_key=args.idempotency_key,
        )
    if command == "task-list":
        return service.list_tasks(state=args.state, limit=args.limit)
    if command == "task-get":
        return service.get_task(args.task_id)
    if command == "task-claim":
        return service.claim_task(
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            idempotency_key=args.idempotency_key,
        )
    if command == "task-start":
        return service.start_task(
            task_id=args.task_id,
            lease_token=args.lease_token,
            idempotency_key=args.idempotency_key,
        )
    if command == "task-heartbeat":
        return service.heartbeat_task(
            task_id=args.task_id,
            lease_token=args.lease_token,
            lease_seconds=args.lease_seconds,
            idempotency_key=args.idempotency_key,
        )
    if command == "task-complete":
        return service.complete_task(
            task_id=args.task_id,
            lease_token=args.lease_token,
            result_summary=args.result_summary,
            evidence=args.evidence,
            artifacts=args.artifacts,
            idempotency_key=args.idempotency_key,
        )
    if command == "task-fail":
        return service.fail_task(
            task_id=args.task_id,
            lease_token=args.lease_token,
            error=args.error,
            retryable=not args.no_retry,
            retry_delay_seconds=args.retry_delay_seconds,
            idempotency_key=args.idempotency_key,
        )
    if command in {"task-pause", "task-resume", "task-cancel"}:
        method = {
            "task-pause": service.pause_task,
            "task-resume": service.resume_task,
            "task-cancel": service.cancel_task,
        }[command]
        return method(
            actor=args.actor,
            task_id=args.task_id,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
    if command == "artifact-add":
        return service.register_local_artifact(
            actor=args.actor,
            task_id=args.task_id,
            path=args.path,
            name=args.name,
            media_type=args.media_type,
            idempotency_key=args.idempotency_key,
        )
    if command == "notification-pull":
        return service.pull_notification(
            actor=args.actor,
            recipient=args.recipient,
            adapter_id=args.adapter_id,
            lease_seconds=args.lease_seconds,
            idempotency_key=args.idempotency_key,
        )
    if command == "notification-ack":
        return service.ack_notification(
            actor=args.actor,
            notification_id=args.notification_id,
            lease_token=args.lease_token,
            idempotency_key=args.idempotency_key,
        )
    if command == "receipt-record":
        return service.record_receipt(
            actor=args.actor,
            item_type=args.item_type,
            item_id=args.item_id,
            receipt_type=args.receipt_type,
        )
    if command == "events":
        return service.events(
            stream_type=args.stream_type,
            stream_id=args.stream_id,
            after_seq=args.after_seq,
            limit=args.limit,
        )
    if command == "a2a-export":
        return {"ok": True, "a2a_task": export_task_dict(service, args.task_id)}
    if command == "promote":
        return service.promote_to_task(
            actor=args.actor,
            source_thread_id=args.source_thread_id,
            decision_hash=args.decision_hash,
            title=args.title,
            goal=args.goal,
            owner=args.owner,
            writer_scope=args.writer_scope,
            acceptance=args.acceptance,
            budget=args.budget,
            stop_scope=args.stop_scope,
            priority=args.priority,
            max_attempts=args.max_attempts,
            task_id=args.task_id,
            metadata=args.metadata,
            idempotency_key=args.idempotency_key,
        )
    if command == "stop":
        return service.user_stop(
            actor=args.actor,
            reason=args.reason,
            scope=args.scope,
            cancel_active_tasks=not args.no_cancel_tasks,
            idempotency_key=args.idempotency_key,
        )
    if command == "stop-clear":
        return service.clear_stop(
            actor=args.actor,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
    if command == "stop-status":
        return service.stop_status()
    if command in {"amq-send", "amq-ingest", "amq-outbox-flush"}:
        from .amq import AmqIngestor, AmqOutbox, AmqTransport
        from .amq.mapping import role_to_handle

        transport = AmqTransport(bin_path=args.amq_bin, root=args.amq_root)
        if command == "amq-send":
            try:
                me = role_to_handle(args.me)
            except ValueError:
                me = args.me
            try:
                to = role_to_handle(args.to)
            except ValueError:
                to = args.to
            result = transport.send(
                me=me,
                to=to,
                body=args.body,
                subject=args.subject,
                kind=args.kind,
                thread=args.thread,
            )
            return {"ok": True, "action": "amq.send", "amq": result, "receipt_stage": "RAW_SPOOL"}
        if command == "amq-ingest":
            return AmqIngestor(service, transport).ingest_for_role(
                recipient_role=args.recipient_role,
                limit=args.limit,
            )
        return AmqOutbox(service, transport).flush_for_role(
            sender_role=args.sender_role,
            recipient_role=args.recipient_role,
            max_items=args.max_items,
        )
    raise RuntimeError(f"unhandled command: {command}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args, CoordinationService(args.db))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result.get("ok", False) else 1
    except CoordinationError as exc:
        print(
            json.dumps(
                exc.as_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
                default=lambda _value: "<non-serializable>",
            )
        )
        return 2
    except Exception as exc:  # adapter boundary: keep ordinary callers JSON-first and stack-free
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "internal_error",
                    "message": "operation failed; inspect local test logs for details",
                    "details": {"exception_type": type(exc).__name__},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
