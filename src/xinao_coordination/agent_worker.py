"""Transient worker for one durable Grok ACP operation."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .agent_operations import AgentOperationStore
from .errors import CoordinationError, InvalidTransitionError, LeaseError

ACPX_CURRENT = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\acpx\current.json")
ACPX_STATE = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\acpx-runtime-grok")
DEFAULT_GROK_HOME = Path(r"C:\Users\xx363\.grok-bg-workers")


def process_start_time_ms(process_handle: int | None = None) -> int:
    """Read the Windows kernel creation time, not an estimated wall-clock timestamp."""

    if os.name != "nt":
        return time.time_ns() // 1_000_000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    handle = process_handle or kernel32.GetCurrentProcess()
    created = ctypes.c_ulonglong()
    exited = ctypes.c_ulonglong()
    kernel = ctypes.c_ulonglong()
    user = ctypes.c_ulonglong()
    if not kernel32.GetProcessTimes(
        ctypes.c_void_p(handle),
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
    return int((created.value - 116_444_736_000_000_000) // 10_000)


class KillOnCloseJob:
    """Own a Windows child tree so worker death cannot leave an orphaned agent."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.handle: int | None = None
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            ctypes.c_void_p(job), 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            ctypes.c_void_p(job),
            ctypes.c_void_p(process._handle),  # type: ignore[attr-defined]
        )
        if not assigned:
            kernel32.CloseHandle(ctypes.c_void_p(job))
            return
        self.handle = int(job)

    def close(self) -> None:
        if self.handle is None or os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(ctypes.c_void_p(self.handle))
        self.handle = None


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def file_evidence(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "size_bytes": len(data),
    }


def read_acpx_runtime() -> dict[str, Path]:
    current = json.loads(ACPX_CURRENT.read_text(encoding="utf-8"))
    generation = Path(current["generation_path"]).resolve()
    expected_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\tools\acpx\generations").resolve()
    if generation != expected_root and expected_root not in generation.parents:
        raise RuntimeError("acpx generation escaped its managed root")
    values = {
        "node": Path(current["node_path"]).resolve(),
        "runner": Path(current["runner_path"]).resolve(),
        "runtime_module": generation / "node_modules" / "acpx" / "dist" / "runtime.js",
    }
    if not all(path.is_file() for path in values.values()):
        raise RuntimeError("managed acpx runtime is incomplete")
    return values


def read_lines(pipe: Any, output: queue.Queue[str | None]) -> None:
    try:
        for line in pipe:
            output.put(line)
    finally:
        output.put(None)


def finish_cancel_before_start(
    store: AgentOperationStore,
    operation_id: str,
    lease_token: str,
) -> bool:
    """Consume a cancel that raced the controller-to-worker handoff."""

    current = store.get(operation_id)["operation"]
    assert isinstance(current, dict)
    if current["state"] != "cancel_requested" or current["lease_token"] != lease_token:
        return False
    store.finish(
        operation_id,
        lease_token=lease_token,
        control_epoch=int(current["control_epoch"]),
        outcome="canceled",
        stop_reason="canceled_before_transport_start",
        error=str(current.get("error") or "cancel requested before transport start"),
    )
    return True


def record_transport_fenced(
    store: AgentOperationStore,
    operation_id: str,
    lease_token: str,
    control_epoch: int,
    **values: object,
) -> int:
    """Retry one evidence write only when cancellation is the sole fence change."""

    try:
        store.record_transport(
            operation_id,
            lease_token=lease_token,
            control_epoch=control_epoch,
            **values,
        )
        return control_epoch
    except LeaseError:
        current = store.get(operation_id)["operation"]
        assert isinstance(current, dict)
        if current["state"] != "cancel_requested" or current["lease_token"] != lease_token:
            raise
        refreshed_epoch = int(current["control_epoch"])
        store.record_transport(
            operation_id,
            lease_token=lease_token,
            control_epoch=refreshed_epoch,
            **values,
        )
        return refreshed_epoch


def run(
    operation_id: str,
    db_path: Path,
    *,
    lease_token: str | None = None,
    control_epoch: int | None = None,
    worker_id: str | None = None,
) -> int:
    store = AgentOperationStore(db_path)
    bootstrap_worker_id = worker_id or f"agent-worker-bootstrap-{uuid.uuid4().hex}"
    if lease_token is None or control_epoch is None:
        claimed = store.claim(operation_id, worker_id=bootstrap_worker_id, lease_seconds=60)
        lease_token = str(claimed["lease_token"])
        control_epoch = int(claimed["control_epoch"])
        operation = claimed["operation"]
    else:
        try:
            adopted = store.heartbeat(
                operation_id,
                lease_token=lease_token,
                control_epoch=control_epoch,
                lease_seconds=60,
            )
        except LeaseError:
            if finish_cancel_before_start(store, operation_id, lease_token):
                return 1
            raise
        operation = adopted["operation"]
    assert isinstance(operation, dict)
    collector_start_time_ms = process_start_time_ms()
    runtime_worker_id = f"agent-worker-{os.getpid()}-{collector_start_time_ms}"

    operation_root = db_path.resolve().parent / "operations" / operation_id
    attempt = int(operation["attempt_count"]) + 1
    attempt_root = operation_root / f"attempt-{attempt:03d}"
    event_path = attempt_root / "events.ndjson"
    stderr_path = attempt_root / "stderr.log"
    final_path = attempt_root / "final.txt"
    manifest_path = attempt_root / "manifest.json"
    spec_path = attempt_root / "operation-spec.json"
    attempt_root.mkdir(parents=True, exist_ok=True)

    runtime = read_acpx_runtime()
    metadata = operation["metadata"] if isinstance(operation["metadata"], dict) else {}
    permission_mode = str(metadata.get("permission_mode", "approve-reads"))
    if permission_mode not in {"approve-reads", "approve-all", "deny-all"}:
        permission_mode = "approve-reads"
    non_interactive_permissions = str(metadata.get("non_interactive_permissions", "fail"))
    if non_interactive_permissions not in {"deny", "fail"}:
        non_interactive_permissions = "fail"
    remaining_ms = max(1_000, int(operation["deadline_at_ms"]) - store.now_ms())
    timeout_ms = min(remaining_ms, int(metadata.get("turn_timeout_ms", remaining_ms)))
    prompt = (
        "[Coordination metadata; this identifier is not additional authority.]\n"
        f"{operation['operation_token']}\n"
        "Task:\n"
        f"{operation['prompt']}"
    )
    spec: dict[str, object] = {
        "runtime_module": str(runtime["runtime_module"]),
        "state_dir": str(ACPX_STATE / "sessions"),
        "cwd": operation["cwd"],
        "session_key": operation["session_name"],
        "request_id": operation["request_id"],
        "prompt": prompt,
        "permission_mode": permission_mode,
        "non_interactive_permissions": non_interactive_permissions,
        "timeout_ms": timeout_ms,
        "model": str(metadata.get("model", "grok-4.5")),
        "agent_env": {
            "GROK_HOME": str(Path(os.environ.get("XINAO_GROK_HOME", DEFAULT_GROK_HOME)).resolve()),
            "XINAO_COORD_ROLE": "grok_4_5",
            "XINAO_OPERATION_ID": operation_id,
            "XINAO_TEMPORAL_PARENT_WORKFLOW_ID": str(metadata.get("temporal_workflow_id") or ""),
            "XINAO_TEMPORAL_LANE_ID": str(metadata.get("temporal_lane_id") or ""),
        },
    }
    if isinstance(metadata.get("allowed_tools"), list):
        spec["allowed_tools"] = metadata["allowed_tools"]
    if isinstance(metadata.get("max_turns"), int):
        spec["max_turns"] = metadata["max_turns"]
    write_json_atomic(spec_path, spec)

    try:
        store.mark_running(
            operation_id,
            lease_token=lease_token,
            control_epoch=control_epoch,
            worker_id=runtime_worker_id,
            collector_pid=os.getpid(),
            collector_start_time_ms=collector_start_time_ms,
            event_log_path=str(event_path),
            stderr_log_path=str(stderr_path),
        )
    except (InvalidTransitionError, LeaseError):
        if finish_cancel_before_start(store, operation_id, lease_token):
            return 1
        raise

    child_env = os.environ.copy()
    child_env.update(
        {
            "USERPROFILE": str(ACPX_STATE),
            "HOME": str(ACPX_STATE),
            "GROK_HOME": spec["agent_env"]["GROK_HOME"],  # type: ignore[index]
            "XINAO_COORD_ROLE": "grok_4_5",
            "NO_COLOR": "1",
        }
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    stderr_handle = stderr_path.open("w", encoding="utf-8", newline="")
    try:
        process = subprocess.Popen(
            [str(runtime["node"]), str(runtime["runner"]), str(spec_path)],
            cwd=operation["cwd"],
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except Exception as exc:
        stderr_handle.close()
        if not finish_cancel_before_start(store, operation_id, lease_token):
            store.finish(
                operation_id,
                lease_token=lease_token,
                control_epoch=control_epoch,
                outcome="failed",
                stop_reason="runner_spawn_failed",
                error=type(exc).__name__,
            )
        return 2

    job = KillOnCloseJob(process)
    if os.name == "nt" and job.handle is None:
        process.kill()
        process.wait(timeout=5)
        stderr_handle.close()
        if not finish_cancel_before_start(store, operation_id, lease_token):
            store.finish(
                operation_id,
                lease_token=lease_token,
                control_epoch=control_epoch,
                outcome="failed",
                stop_reason="job_object_assignment_failed",
                error="Windows child tree could not be fenced",
            )
        return 2
    if finish_cancel_before_start(store, operation_id, lease_token):
        job.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        stderr_handle.close()
        return 1
    assert process.stdin is not None
    try:
        process.stdin.write(json.dumps({"action": "start"}) + "\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError):
        job.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        stderr_handle.close()
        store.mark_uncertain(
            operation_id,
            lease_token=lease_token,
            control_epoch=control_epoch,
            error="runner start-gate delivery outcome unknown",
        )
        return 2

    lines: queue.Queue[str | None] = queue.Queue()
    assert process.stdout is not None
    reader = threading.Thread(target=read_lines, args=(process.stdout, lines), daemon=True)
    reader.start()
    terminal: dict[str, Any] | None = None
    turn_may_have_started = False
    cancel_sent_at: float | None = None
    last_heartbeat = time.monotonic()
    last_progress = last_heartbeat
    progress_pending = False
    no_progress_seconds = int(metadata.get("no_progress_seconds", 900))

    with event_path.open("a", encoding="utf-8", newline="") as event_handle:
        stream_ended = False
        while not stream_ended or process.poll() is None or not lines.empty():
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                line = ""
            if line is None:
                stream_ended = True
            elif line:
                event_handle.write(line)
                event_handle.flush()
                os.fsync(event_handle.fileno())
                progress_pending = True
                last_progress = time.monotonic()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "invalid_json"}
                if event.get("type") == "session_resolved":
                    control_epoch = record_transport_fenced(
                        store,
                        operation_id,
                        lease_token,
                        control_epoch,
                        acpx_record_id=event.get("acpxRecordId"),
                        agent_session_id=(event.get("agentSessionId") or event.get("backendSessionId")),
                    )
                elif event.get("type") == "terminal":
                    terminal = event
                elif event.get("type") in {
                    "turn_starting",
                    "text_delta",
                    "thought_progress",
                    "tool_call",
                }:
                    turn_may_have_started = True

            current = store.get(operation_id)["operation"]
            assert isinstance(current, dict)
            if current["state"] == "cancel_requested":
                control_epoch = int(current["control_epoch"])
                if cancel_sent_at is None or time.monotonic() - cancel_sent_at >= 5:
                    if process.stdin is not None:
                        process.stdin.write(
                            json.dumps({"action": "cancel", "reason": current.get("error")}) + "\n"
                        )
                        process.stdin.flush()
                    cancel_sent_at = time.monotonic()
            elif store.now_ms() >= int(current["deadline_at_ms"]):
                store.request_cancel(operation_id, actor="codex", reason="deadline reached")
                continue
            elif time.monotonic() - last_progress > no_progress_seconds:
                store.request_cancel(operation_id, actor="codex", reason="no progress deadline reached")
                continue

            if time.monotonic() - last_heartbeat >= 5:
                try:
                    store.heartbeat(
                        operation_id,
                        lease_token=lease_token,
                        control_epoch=control_epoch,
                        lease_seconds=60,
                        made_progress=progress_pending,
                    )
                except LeaseError:
                    refreshed = store.get(operation_id)["operation"]
                    assert isinstance(refreshed, dict)
                    if refreshed["state"] != "cancel_requested":
                        raise
                    control_epoch = int(refreshed["control_epoch"])
                last_heartbeat = time.monotonic()
                progress_pending = False

            if cancel_sent_at is not None and time.monotonic() - cancel_sent_at > 30:
                job.close()
                if process.poll() is None:
                    process.kill()
                break

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job.close()
            process.kill()
            process.wait(timeout=5)
    stderr_handle.close()
    job.close()

    current = store.get(operation_id)["operation"]
    assert isinstance(current, dict)
    control_epoch = int(current["control_epoch"])
    terminal_is_unknown = bool(
        terminal and terminal.get("turnStarted") is True and terminal.get("resultAuthoritative") is not True
    )
    if terminal is None or terminal_is_unknown:
        detail = f"runner exited without terminal event (exit={process.returncode})"
        if terminal_is_unknown:
            detail = "runner lost the authoritative ACP result after turn start"
        if turn_may_have_started or terminal_is_unknown:
            store.mark_uncertain(
                operation_id,
                lease_token=lease_token,
                control_epoch=control_epoch,
                error=detail,
            )
        else:
            store.finish(
                operation_id,
                lease_token=lease_token,
                control_epoch=control_epoch,
                outcome="failed",
                stop_reason="runner_exited_pre_accept",
                error=detail,
                retryable=bool(operation["replay_safe"]),
                retry_delay_seconds=5,
            )
        outcome_state = "uncertain" if turn_may_have_started or terminal_is_unknown else "failed"
    else:
        result = terminal.get("result") if isinstance(terminal.get("result"), dict) else {}
        result_status = result.get("status") or terminal.get("status")
        final_text = terminal.get("finalText") if isinstance(terminal.get("finalText"), str) else ""
        if final_text:
            final_path.write_text(final_text, encoding="utf-8")
        control_epoch = record_transport_fenced(
            store,
            operation_id,
            lease_token,
            control_epoch,
            acpx_record_id=terminal.get("acpxRecordId"),
            agent_session_id=(terminal.get("agentSessionId") or terminal.get("backendSessionId")),
            result_text=final_text or None,
        )
        refreshed = store.get(operation_id)["operation"]
        assert isinstance(refreshed, dict)
        control_epoch = int(refreshed["control_epoch"])
        stop_reason = str(result.get("stopReason") or result_status or "unknown")
        if result_status == "completed" and refreshed["state"] != "cancel_requested":
            outcome = "completed"
        elif result_status == "cancelled" or refreshed["state"] == "cancel_requested":
            outcome = (
                "deadline_exceeded" if store.now_ms() >= int(refreshed["deadline_at_ms"]) else "canceled"
            )
        else:
            outcome = "failed"
        error_value = terminal.get("error") or result.get("error")
        error_text = json.dumps(error_value, ensure_ascii=False) if error_value else None
        store.finish(
            operation_id,
            lease_token=lease_token,
            control_epoch=control_epoch,
            outcome=outcome,
            stop_reason=stop_reason,
            result_text=final_text or None,
            error=error_text,
            retryable=(
                outcome == "failed"
                and bool(refreshed["replay_safe"])
                and bool(isinstance(error_value, dict) and error_value.get("retryable"))
            ),
            retry_delay_seconds=5,
        )
        outcome_state = outcome

    evidence_files = [path for path in (event_path, stderr_path, final_path) if path.exists()]
    evidence = [file_evidence(path) for path in evidence_files]
    manifest = {
        "schema_version": 1,
        "operation_id": operation_id,
        "request_id": operation["request_id"],
        "outcome": outcome_state,
        "collector_pid": os.getpid(),
        "collector_start_time_ms": collector_start_time_ms,
        "runner_exit_code": process.returncode,
        "files": evidence,
        "raw_chain_of_thought_stored": False,
    }
    write_json_atomic(manifest_path, manifest)
    for item in [*evidence, file_evidence(manifest_path)]:
        path = Path(str(item["path"]))
        store.add_artifact(
            operation_id,
            name=path.name,
            uri=str(path),
            media_type=("application/x-ndjson" if path.suffix == ".ndjson" else "text/plain"),
            sha256=str(item["sha256"]),
            size_bytes=int(item["size_bytes"]),
            metadata={"attempt": attempt},
        )
    return 0 if outcome_state == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--lease-token")
    parser.add_argument("--control-epoch", type=int)
    parser.add_argument("--worker-id")
    args = parser.parse_args(argv)
    try:
        return run(
            args.operation_id,
            args.db,
            lease_token=args.lease_token,
            control_epoch=args.control_epoch,
            worker_id=args.worker_id,
        )
    except CoordinationError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": "agent_worker_failed", "exception_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
