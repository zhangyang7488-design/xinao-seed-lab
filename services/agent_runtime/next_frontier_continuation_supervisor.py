from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "xinao.codex_s.next_frontier_continuation_supervisor.v1"
SENTINEL = "SENTINEL:XINAO_NEXT_FRONTIER_CONTINUATION_SUPERVISOR_READY"
DEFAULT_RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_REPO = Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\S"))
DEFAULT_TASK_QUEUE = "xinao-codex-task-default"
WORK_ID = "xinao_seed_cortex_phase0_20260701"
LEGACY_RUNTIME_ROOT = r"D:\XINAO_CLEAN_RUNTIME"

ACTION_RANKS = {
    "continue_source_frontier_claimcard_absorption": 10,
    "consume_source_frontier_batch": 12,
    "queue_wave2_hygiene_after_wave5_or_if_parallel_safe": 18,
    "enter_wave2_mainchain_hygiene": 20,
    "enter_phase5_mature_thin_bind_sunset": 30,
    "smoke_mature_carrier_adapter_candidates": 40,
    "retry_source_family_adapter_smoke_or_write_named_blocker": 40,
    "implement_thin_bind_adapter_for_smoked_candidates": 50,
    "evaluate_smoked_candidate_adapter_bindings_for_capability_gateway": 60,
    "refresh_capability_gateway_snapshot_with_evaluated_source_candidates": 70,
    "monitor_temporal_source_family_adapter_value_eval_activity": 80,
    "continue_default_temporal_chain_after_source_family_adapter_value_eval_monitor": 90,
    "keep_default_temporal_chain_polling": 90,
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in text)
    return "-".join(part for part in cleaned.split("-") if part)[:96] or "frontier"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    last_error: PermissionError | None = None
    for attempt in range(20):
        temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.{attempt}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.04 * (attempt + 1))
    if last_error is not None:
        raise last_error


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def paths(runtime: Path) -> dict[str, Path]:
    root = runtime / "state" / "next_frontier_continuation_supervisor"
    return {
        "root": root,
        "latest": root / "latest.json",
        "records": root / "records",
        "canonical_latest": runtime / "state" / "next_frontier_machine_actions" / "latest.json",
        "canonical_records": root / "canonical_records",
        "dispatch_latest": root / "dispatch_intent" / "latest.json",
        "dispatch_records": root / "dispatch_intent" / "records",
        "lock": root / ".promotion.lock",
        "readback": runtime / "readback" / "zh" / "next_frontier_continuation_supervisor.md",
        "dynamic_fanout_latest": runtime / "state" / "worker_assignment_dynamic_fanout" / "latest.json",
    }


class PromotionLock:
    def __init__(self, lock_path: Path, timeout_sec: float = 10.0) -> None:
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec
        self.fd: int | None = None

    def __enter__(self) -> "PromotionLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_sec
        while True:
            try:
                self.fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self.fd, str(os.getpid()).encode("ascii", errors="ignore"))
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                    if age > self.timeout_sec:
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out acquiring {self.lock_path}")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def first_frontier_item(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("next_frontier")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                return item
    return {}


def first_frontier_action(payload: dict[str, Any]) -> str:
    return str(first_frontier_item(payload).get("action") or "")


def first_frontier_action_id(payload: dict[str, Any]) -> str:
    item = first_frontier_item(payload)
    return str(
        item.get("action_id")
        or item.get("frontier_id")
        or item.get("id")
        or item.get("action")
        or ""
    )


def action_rank(payload: dict[str, Any]) -> int:
    return ACTION_RANKS.get(first_frontier_action(payload), 0)


def frontier_identity(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("work_id") or WORK_ID),
        str(payload.get("task_id") or ""),
        str(payload.get("wave_id") or ""),
        first_frontier_action_id(payload),
        first_frontier_action(payload),
    ]
    return ":".join(parts)


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            found.extend(_walk_strings(item))
        return found
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            found.append(str(key))
            found.extend(_walk_strings(item))
        return found
    return []


def legacy_hot_path_violations(payload: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    haystack = "\n".join(_walk_strings(payload)).lower()
    if LEGACY_RUNTIME_ROOT.lower() in haystack:
        violations.append("D_CLEAN_RUNTIME_REFERENCE_IN_HOT_PATH")
    if "current_task_owner" in haystack and "authority_boundary" not in haystack:
        violations.append("OLD_CURRENT_TASK_OWNER_HOT_PATH_REFERENCE")
    if "worker pass" in haystack or "pass_as_completion" in haystack:
        violations.append("OLD_PASS_COMPLETION_GATE_REFERENCE")
    return violations


def _current_sequence(current: dict[str, Any]) -> int:
    supervisor = current.get("_continuation_supervisor")
    if isinstance(supervisor, dict):
        try:
            return int(supervisor.get("sequence") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _promotion_decision(
    *,
    candidate: dict[str, Any],
    current: dict[str, Any],
    candidate_digest: str,
) -> tuple[str, str]:
    violations = legacy_hot_path_violations(candidate)
    if violations:
        return "legacy_rejected", ",".join(violations)
    if not first_frontier_action(candidate) and (
        candidate.get("should_continue_loop") is False
        or candidate.get("stop_allowed") is True
    ):
        return "promoted", "terminal_no_pending_action"
    if not first_frontier_action(candidate):
        return "blocked", "NEXT_FRONTIER_ACTION_MISSING"
    current_supervisor = current.get("_continuation_supervisor")
    current_digest = (
        str(current_supervisor.get("candidate_digest") or "")
        if isinstance(current_supervisor, dict)
        else ""
    )
    if current_digest and current_digest == candidate_digest:
        return "deduped", "same_candidate_digest"
    if current and frontier_identity(current) == frontier_identity(candidate):
        if not isinstance(current_supervisor, dict) or not current_supervisor.get("sentinel"):
            return "promoted", "same_frontier_identity_metadata_upgrade"
        return "deduped", "same_frontier_identity"
    current_rank = action_rank(current)
    incoming_rank = action_rank(candidate)
    current_stop_allowed = current.get("stop_allowed") is True
    if current and not current_stop_allowed and incoming_rank < current_rank:
        return "stale_rejected", f"incoming_rank_{incoming_rank}_below_current_rank_{current_rank}"
    return "promoted", "accepted"


def build_continue_same_task_signal(
    *,
    runtime: Path,
    canonical: dict[str, Any],
    sequence: int,
    workflow_id: str = "",
    workflow_run_id: str = "",
    task_queue: str = DEFAULT_TASK_QUEUE,
) -> dict[str, Any]:
    item = first_frontier_item(canonical)
    action = str(item.get("action") or "")
    action_id = first_frontier_action_id(canonical)
    signal_id = hashlib.sha256(
        f"{frontier_identity(canonical)}:{sequence}".encode("utf-8", errors="replace")
    ).hexdigest()[:24]
    objective = str(item.get("why") or item.get("objective") or action or "continue next frontier")
    timeout_sec = 1800
    work_package = {
        "next_ready_node_id": f"next-frontier:{safe_id(action_id)}",
        "frontier_action_id": action_id,
        "frontier_action": action,
        "objective": objective,
        "source_kind": "next_frontier_continuation_supervisor",
        "canonical_next_frontier_ref": str(paths(runtime)["canonical_latest"]),
        "supervisor_latest_ref": str(paths(runtime)["latest"]),
        "requires": item.get("requires") if isinstance(item.get("requires"), list) else [],
        "frontier_item": item,
    }
    phase_execution = {
        "worker_kind": "implementation_worker",
        "phase_scope": action or "next_frontier_continuation",
        "provider_routing_mode": "default_token_saving_worker_route",
        "default_token_saving_worker_route": True,
        "repo_root": str(DEFAULT_REPO),
        "timeout_sec": timeout_sec,
        "max_activity_timeout_sec": timeout_sec,
        "work_package": work_package,
        "verification": [
            str(paths(runtime)["canonical_latest"]),
            str(paths(runtime)["dispatch_latest"]),
            "D-runtime evidence and Chinese readback updated",
            "no user completion claim",
        ],
        "segment_pass_checker_default": False,
        "segment_pass_checker_allowed": False,
    }
    return {
        "schema_version": "xinao.codex_s.next_frontier_continue_same_task_signal.v1",
        "signal_id": signal_id,
        "task_id": str(canonical.get("parent_task_id") or canonical.get("work_id") or WORK_ID),
        "source_task_id": str(canonical.get("task_id") or ""),
        "routing_verb": "continue_same_task",
        "source_kind": "next_frontier_continuation_supervisor",
        "execute_policy": "auto",
        "execute_worker_turn": True,
        "execute_codex_worker": True,
        "execute_codex_worker_legacy_alias": True,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "task_queue": task_queue,
        "assignment_dag_node_id": f"next-frontier:{safe_id(action_id)}",
        "dag_next_ready_node_id": f"next-frontier:{safe_id(action_id)}",
        "phase_scope": phase_execution["phase_scope"],
        "phase_execution": phase_execution,
        "work_package": work_package,
        "verification": phase_execution["verification"],
        "codex_worker_timeout_sec": timeout_sec,
        "implementation_worker_timeout_sec": timeout_sec,
        "user_goal": objective,
        "message": f"next_frontier auto-continue action={action}",
        "next_frontier_auto_continue": True,
        "spawn_new_owner_allowed": False,
        "manual_cli_required": False,
        "watch_window_required": False,
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_execution_controller": True,
        "generated_at": now_iso(),
    }


def render_readback(payload: dict[str, Any]) -> str:
    signal = payload.get("auto_continue_same_task_signal")
    action = payload.get("frontier_action") or ""
    lines = [
        "# Next Frontier 后台续跑监督器",
        "",
        SENTINEL,
        "",
        f"- status: `{payload.get('status')}`",
        f"- promotion_status: `{payload.get('promotion_status')}`",
        f"- sequence: `{payload.get('sequence')}`",
        f"- action: `{action}`",
        f"- auto_continue_same_workflow: `{payload.get('auto_continue_same_workflow')}`",
        f"- named_blocker: `{payload.get('named_blocker') or ''}`",
        f"- canonical_latest: `{payload.get('output_paths', {}).get('canonical_latest')}`",
        f"- dispatch_intent: `{payload.get('output_paths', {}).get('dispatch_latest')}`",
        "",
        "人话：后台下一跳现在由 supervisor 统一提升和派发；旧 latest/PASS/current_task_owner 不再当热路径权威。",
    ]
    if isinstance(signal, dict) and signal:
        lines.append(f"- next worker node: `{signal.get('assignment_dag_node_id')}`")
    lines.extend(["", SENTINEL, ""])
    return "\n".join(lines)


def promote_candidate_next_frontier(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    candidate: dict[str, Any],
    source_kind: str,
    source_ref: str = "",
    workflow_id: str = "",
    workflow_run_id: str = "",
    task_queue: str = DEFAULT_TASK_QUEUE,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    out = paths(runtime)
    candidate_payload = dict(candidate or {})
    candidate_digest = sha256_json(candidate_payload)
    if not write:
        current = read_json(out["canonical_latest"])
        decision, reason = _promotion_decision(
            candidate=candidate_payload,
            current=current,
            candidate_digest=candidate_digest,
        )
        sequence = _current_sequence(current) + (1 if decision == "promoted" else 0)
        canonical = dict(candidate_payload if decision == "promoted" else current)
    else:
        with PromotionLock(out["lock"]):
            current = read_json(out["canonical_latest"])
            decision, reason = _promotion_decision(
                candidate=candidate_payload,
                current=current,
                candidate_digest=candidate_digest,
            )
            sequence = _current_sequence(current) + (1 if decision == "promoted" else 0)
            canonical = dict(candidate_payload if decision == "promoted" else current)
            if decision == "promoted":
                canonical["_continuation_supervisor"] = {
                    "schema_version": f"{SCHEMA_VERSION}.canonical.v1",
                    "sentinel": SENTINEL,
                    "sequence": sequence,
                    "candidate_digest": candidate_digest,
                    "frontier_identity": frontier_identity(candidate_payload),
                    "frontier_action": first_frontier_action(candidate_payload),
                    "frontier_action_id": first_frontier_action_id(candidate_payload),
                    "frontier_action_rank": action_rank(candidate_payload),
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "workflow_id": workflow_id,
                    "workflow_run_id": workflow_run_id,
                    "task_queue": task_queue,
                    "promotion_status": decision,
                    "promotion_reason": reason,
                    "promoted_at": now_iso(),
                    "runtime_enforced": True,
                    "adoption_state": "runtime_enforced_default_next_frontier_continuation_supervisor",
                    "completion_claim_allowed": False,
                    "not_user_completion": True,
                    "not_completion_gate": True,
                }
                write_json(out["canonical_latest"], canonical)
                write_json(
                    out["canonical_records"]
                    / f"{sequence:08d}-{safe_id(first_frontier_action_id(canonical))}.json",
                    canonical,
                )
    signal = (
        build_continue_same_task_signal(
            runtime=runtime,
            canonical=canonical,
            sequence=max(sequence, _current_sequence(canonical)),
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            task_queue=task_queue,
        )
        if first_frontier_action(canonical) and canonical.get("stop_allowed") is not True
        else {}
    )
    candidate_rejection_reason = (
        reason if decision in {"blocked", "legacy_rejected", "stale_rejected"} else ""
    )
    canonical_violations = legacy_hot_path_violations(canonical)
    named_blocker = ",".join(canonical_violations) if canonical_violations else ""
    if not signal and candidate_rejection_reason and not named_blocker:
        named_blocker = candidate_rejection_reason
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": (
            "next_frontier_continuation_supervisor_ready"
            if signal and not named_blocker
            else "next_frontier_continuation_supervisor_blocked"
        ),
        "promotion_status": decision,
        "promotion_reason": reason,
        "candidate_rejection_reason": candidate_rejection_reason,
        "named_blocker": named_blocker,
        "sequence": _current_sequence(canonical) or sequence,
        "runtime_root": str(runtime),
        "work_id": str(canonical.get("work_id") or WORK_ID),
        "task_id": str(canonical.get("task_id") or ""),
        "wave_id": str(canonical.get("wave_id") or ""),
        "source_kind": source_kind,
        "source_ref": source_ref,
        "frontier_identity": frontier_identity(canonical),
        "frontier_action": first_frontier_action(canonical),
        "frontier_action_id": first_frontier_action_id(canonical),
        "frontier_action_rank": action_rank(canonical),
        "candidate_digest": candidate_digest,
        "canonical_digest": sha256_json(canonical) if canonical else "",
        "canonical_next_frontier": canonical,
        "auto_continue_same_workflow": bool(signal and not named_blocker),
        "auto_continue_same_task_signal": signal if not named_blocker else {},
        "manual_cli_required": False,
        "watch_window_required": False,
        "restart_recovery_source": str(out["canonical_latest"]),
        "legacy_runtime_hot_path_allowed": False,
        "old_current_task_owner_hot_path_allowed": False,
        "old_pass_latest_completion_gate_allowed": False,
        "runtime_enforced": bool(signal and not named_blocker),
        "runtime_enforced_scope": "seed_cortex_next_frontier_continuation_supervisor",
        "adoption_state": "runtime_enforced_default_next_frontier_continuation_supervisor",
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_completion_decision": True,
        "not_completion_gate": True,
        "not_execution_controller": True,
        "validation": {
            "passed": bool(signal and not named_blocker),
            "checks": {
                "canonical_latest_written_or_reused": bool(canonical),
                "candidate_digest_present": bool(candidate_digest),
                "sequence_present": (_current_sequence(canonical) or sequence) > 0,
                "legacy_runtime_hot_path_denied": LEGACY_RUNTIME_ROOT.lower()
                not in "\n".join(_walk_strings(canonical)).lower(),
                "pending_action_signal_prepared": bool(signal and not named_blocker),
                "manual_cli_required_false": True,
                "watch_window_required_false": True,
            },
        },
        "output_paths": {
            "latest": str(out["latest"]),
            "canonical_latest": str(out["canonical_latest"]),
            "canonical_records": str(out["canonical_records"]),
            "dispatch_latest": str(out["dispatch_latest"]),
            "readback_zh": str(out["readback"]),
        },
        "generated_at": now_iso(),
    }
    if write:
        record = out["records"] / f"{int(payload['sequence'] or 0):08d}-{safe_id(payload['frontier_action_id'])}.json"
        write_json(record, payload)
        write_json(out["latest"], payload)
        dispatch = {
            "schema_version": f"{SCHEMA_VERSION}.dispatch_intent.v1",
            "status": "next_frontier_dispatch_intent_ready"
            if payload["auto_continue_same_workflow"]
            else "next_frontier_dispatch_intent_blocked",
            "sequence": payload["sequence"],
            "frontier_action": payload["frontier_action"],
            "frontier_action_id": payload["frontier_action_id"],
            "auto_continue_same_workflow": payload["auto_continue_same_workflow"],
            "auto_continue_same_task_signal": payload["auto_continue_same_task_signal"],
            "named_blocker": named_blocker,
            "canonical_latest_ref": str(out["canonical_latest"]),
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
            "generated_at": now_iso(),
        }
        write_json(out["dispatch_latest"], dispatch)
        write_json(
            out["dispatch_records"]
            / f"{int(payload['sequence'] or 0):08d}-{safe_id(payload['frontier_action_id'])}.json",
            dispatch,
        )
        write_text(out["readback"], render_readback(payload))
        if payload["auto_continue_same_workflow"]:
            write_json(
                out["dynamic_fanout_latest"],
                {
                    "schema_version": "xinao.worker_assignment_dynamic_fanout.v1",
                    "status": "next_frontier_auto_continue_enqueued",
                    "source_kind": "next_frontier_continuation_supervisor",
                    "task_id": payload["task_id"],
                    "wave_id": payload["wave_id"],
                    "frontier_action": payload["frontier_action"],
                    "worker_running": True,
                    "temporal_pending_activity": True,
                    "next_ready": True,
                    "auto_continue_expected": True,
                    "manual_cli_required": False,
                    "watch_window_required": False,
                    "supervisor_latest_ref": str(out["latest"]),
                    "dispatch_intent_ref": str(out["dispatch_latest"]),
                    "completion_claim_allowed": False,
                    "not_user_completion": True,
                    "not_execution_controller": True,
                    "generated_at": now_iso(),
                },
            )
    return payload


def supervise_latest_next_frontier(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    source_kind: str = "restart_recovery_latest_read_model",
    workflow_id: str = "",
    workflow_run_id: str = "",
    task_queue: str = DEFAULT_TASK_QUEUE,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    canonical_path = paths(runtime)["canonical_latest"]
    candidate = read_json(canonical_path)
    if not candidate:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sentinel": SENTINEL,
            "status": "next_frontier_continuation_supervisor_idle",
            "promotion_status": "idle",
            "named_blocker": "NEXT_FRONTIER_CANONICAL_LATEST_MISSING",
            "runtime_root": str(runtime),
            "auto_continue_same_workflow": False,
            "auto_continue_same_task_signal": {},
            "manual_cli_required": False,
            "watch_window_required": False,
            "runtime_enforced": False,
            "completion_claim_allowed": False,
            "not_user_completion": True,
            "not_execution_controller": True,
            "output_paths": {
                "latest": str(paths(runtime)["latest"]),
                "canonical_latest": str(canonical_path),
                "dispatch_latest": str(paths(runtime)["dispatch_latest"]),
                "readback_zh": str(paths(runtime)["readback"]),
            },
            "generated_at": now_iso(),
        }
        if write:
            write_json(paths(runtime)["latest"], payload)
            write_text(paths(runtime)["readback"], render_readback(payload))
        return payload
    return promote_candidate_next_frontier(
        runtime_root=runtime,
        candidate=candidate,
        source_kind=source_kind,
        source_ref=str(canonical_path),
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        task_queue=task_queue,
        write=write,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Promote and supervise next_frontier continuation.")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--candidate-json", default="")
    parser.add_argument("--source-kind", default="cli")
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--task-queue", default=DEFAULT_TASK_QUEUE)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    if args.candidate_json:
        candidate = read_json(Path(args.candidate_json))
        payload = promote_candidate_next_frontier(
            runtime_root=args.runtime_root,
            candidate=candidate,
            source_kind=args.source_kind,
            source_ref=args.source_ref or args.candidate_json,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
            task_queue=args.task_queue,
            write=not args.no_write,
        )
    else:
        payload = supervise_latest_next_frontier(
            runtime_root=args.runtime_root,
            source_kind=args.source_kind,
            workflow_id=args.workflow_id,
            workflow_run_id=args.workflow_run_id,
            task_queue=args.task_queue,
            write=not args.no_write,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print(SENTINEL)
    return 0 if payload.get("validation", {}).get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
