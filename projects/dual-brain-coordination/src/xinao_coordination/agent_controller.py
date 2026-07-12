"""Non-blocking launcher and opportunistic reconciler for agent operations."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .agent_operations import TERMINAL_STATES, AgentOperationStore
from .agent_worker import process_start_time_ms
from .errors import InvalidTransitionError, LeaseError, ValidationError

ACPX_LAUNCHER = Path(
    os.environ.get(
        "XINAO_ACPX_LAUNCHER",
        r"E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination\provisioning\Invoke-XinaoAcpxManaged.ps1",
    )
)


class AgentOperationController:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.store = AgentOperationStore(db_path)

    @staticmethod
    def ensure_transport(timeout_seconds: int = 180) -> None:
        command = [
            "pwsh.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ACPX_LAUNCHER),
            "-Target",
            "ensure",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=False,
            timeout=timeout_seconds,
            creationflags=creationflags,
        )

    def start(self, operation_id: str, *, ensure_timeout_seconds: int = 180) -> dict[str, object]:
        operation = self.store.get(operation_id)["operation"]
        assert isinstance(operation, dict)
        if operation["state"] in TERMINAL_STATES:
            return {
                "ok": True,
                "action": "agent_operation.start",
                "operation": operation,
                "spawned": False,
                "reason": "already_terminal",
            }
        if operation["state"] == "uncertain":
            return {
                "ok": True,
                "action": "agent_operation.start",
                "operation": operation,
                "spawned": False,
                "reason": "uncertain_requires_external_verification",
            }
        if operation["state"] == "cancel_requested":
            return {
                "ok": True,
                "action": "agent_operation.start",
                "operation": operation,
                "spawned": False,
                "reason": "cancel_pending",
            }

        self.ensure_transport(ensure_timeout_seconds)
        launcher_id = f"launcher-{uuid.uuid4().hex}"
        try:
            claimed = self.store.claim(operation_id, worker_id=launcher_id, lease_seconds=60)
        except (InvalidTransitionError, LeaseError):
            return {
                "ok": True,
                "action": "agent_operation.start",
                "operation": self.store.get(operation_id)["operation"],
                "spawned": False,
                "reason": "active_or_session_busy",
            }
        lease_token = str(claimed["lease_token"])
        control_epoch = int(claimed["control_epoch"])
        db_path = self.store.db.path.resolve()
        operation_root = db_path.parent / "operations" / operation_id
        operation_root.mkdir(parents=True, exist_ok=True)
        stdout_path = operation_root / "launcher.stdout.log"
        stderr_path = operation_root / "launcher.stderr.log"
        command = [
            sys.executable,
            "-m",
            "xinao_coordination.agent_worker",
            "--db",
            str(db_path),
            "--operation-id",
            operation_id,
            "--lease-token",
            lease_token,
            "--control-epoch",
            str(control_epoch),
            "--worker-id",
            launcher_id,
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        stdout_handle = stdout_path.open("a", encoding="utf-8", newline="")
        stderr_handle = stderr_path.open("a", encoding="utf-8", newline="")
        try:
            process = subprocess.Popen(
                command,
                cwd=operation["cwd"],
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                close_fds=True,
                creationflags=creationflags,
            )
            start_time_ms = process_start_time_ms(
                int(process._handle) if os.name == "nt" else None  # type: ignore[attr-defined]
            )
        except Exception as exc:
            self.store.finish(
                operation_id,
                lease_token=lease_token,
                control_epoch=control_epoch,
                outcome="failed",
                stop_reason="worker_spawn_failed",
                error=type(exc).__name__,
            )
            raise
        finally:
            stdout_handle.close()
            stderr_handle.close()
        operation_after_spawn = self.store.get(operation_id)["operation"]
        assert isinstance(operation_after_spawn, dict)
        wait_deadline = time.monotonic() + 2.0
        while operation_after_spawn.get("collector_pid") is None and time.monotonic() < wait_deadline:
            time.sleep(0.025)
            operation_after_spawn = self.store.get(operation_id)["operation"]
            assert isinstance(operation_after_spawn, dict)
        return {
            "ok": True,
            "action": "agent_operation.start",
            "operation": operation_after_spawn,
            "spawned": True,
            "bootstrap_pid": process.pid,
            "bootstrap_start_time_ms": start_time_ms,
            "worker_pid": operation_after_spawn.get("collector_pid"),
            "worker_start_time_ms": operation_after_spawn.get("collector_start_time_ms"),
            "identity_pending": operation_after_spawn.get("collector_pid") is None
            and operation_after_spawn.get("state") not in TERMINAL_STATES,
        }

    def enqueue_start(self, operation_id: str) -> dict[str, object]:
        """Start a short-lived launcher and return without provisioning or model work."""

        operation = self.store.get(operation_id)["operation"]
        assert isinstance(operation, dict)
        if operation["state"] in TERMINAL_STATES or operation["state"] in {
            "running",
            "cancel_requested",
            "uncertain",
        }:
            return {
                "ok": True,
                "action": "agent_operation.enqueue_start",
                "operation": operation,
                "spawned": False,
                "reason": "operation_not_enqueueable",
            }
        db_path = self.store.db.path.resolve()
        operation_root = db_path.parent / "operations" / operation_id
        operation_root.mkdir(parents=True, exist_ok=True)
        stdout_path = operation_root / "start-launcher.stdout.log"
        stderr_path = operation_root / "start-launcher.stderr.log"
        command = [
            sys.executable,
            "-m",
            "xinao_coordination.agent_launcher",
            "--db",
            str(db_path),
            "--operation-id",
            operation_id,
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        stdout_handle = stdout_path.open("a", encoding="utf-8", newline="")
        stderr_handle = stderr_path.open("a", encoding="utf-8", newline="")
        try:
            process = subprocess.Popen(
                command,
                cwd=operation["cwd"],
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                close_fds=True,
                creationflags=creationflags,
            )
            start_time_ms = process_start_time_ms(
                int(process._handle) if os.name == "nt" else None  # type: ignore[attr-defined]
            )
        except Exception as exc:
            return {
                "ok": True,
                "action": "agent_operation.enqueue_start",
                "operation": operation,
                "spawned": False,
                "reason": "launcher_spawn_failed_reconcile_will_retry",
                "exception_type": type(exc).__name__,
            }
        finally:
            stdout_handle.close()
            stderr_handle.close()
        return {
            "ok": True,
            "action": "agent_operation.enqueue_start",
            "operation": operation,
            "spawned": True,
            "bootstrap_pid": process.pid,
            "bootstrap_start_time_ms": start_time_ms,
            "start_pending": True,
        }

    def submit_and_start(self, **kwargs: object) -> dict[str, object]:
        submitted = self.store.submit(**kwargs)  # type: ignore[arg-type]
        operation = submitted["operation"]
        assert isinstance(operation, dict)
        started = self.enqueue_start(str(operation["operation_id"]))
        recovery: dict[str, object] | None = None
        if not started["spawned"] and started.get("reason") == "launcher_spawn_failed_reconcile_will_retry":
            try:
                recovery = self.reconcile(
                    str(operation["operation_id"]),
                    limit=1,
                    max_runtime_seconds=90,
                )
            except Exception as exc:
                recovery = {
                    "ok": False,
                    "action": "agent_operation.foreground_reconcile",
                    "bounded": True,
                    "operation_retained": True,
                    "exception_type": type(exc).__name__,
                }
            else:
                recovered = recovery.get("results")
                assert isinstance(recovered, list)
                if recovered:
                    first = recovered[0]
                    assert isinstance(first, dict)
                    started = {
                        **first,
                        "action": "agent_operation.enqueue_start",
                        "start_pending": False,
                        "reason": "foreground_bounded_reconcile",
                    }
        return {
            **submitted,
            "operation": started["operation"],
            "spawned": started["spawned"],
            "bootstrap_pid": started.get("bootstrap_pid"),
            "bootstrap_start_time_ms": started.get("bootstrap_start_time_ms"),
            "worker_pid": None,
            "worker_start_time_ms": None,
            "start_pending": started.get("start_pending", False),
            "start_reason": started.get("reason"),
            "foreground_reconcile": recovery,
        }

    def reconcile(
        self,
        operation_id: str | None = None,
        *,
        limit: int = 20,
        max_runtime_seconds: int = 120,
    ) -> dict[str, object]:
        if max_runtime_seconds <= 0 or max_runtime_seconds > 600:
            raise ValidationError("max_runtime_seconds must be between 1 and 600")
        started_at = time.monotonic()
        deadline = started_at + max_runtime_seconds
        sweep = self.store.sweep()
        if operation_id:
            candidates = [self.store.get(operation_id)["operation"]]
        else:
            candidates = self.store.list(limit=limit)["operations"]
        results: list[dict[str, object]] = []
        now = self.store.now_ms()
        stop_reason: str | None = None
        for candidate in candidates:
            assert isinstance(candidate, dict)
            if candidate["state"] not in {"queued", "retry_wait"}:
                continue
            if int(candidate["available_at_ms"]) > now:
                continue
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                stop_reason = "runtime_limit_reached"
                break
            try:
                results.append(
                    self.start(
                        str(candidate["operation_id"]),
                        ensure_timeout_seconds=min(180, max(1, remaining)),
                    )
                )
            except subprocess.TimeoutExpired:
                stop_reason = "transport_ensure_timeout"
                break
        return {
            "ok": True,
            "action": "agent_operation.reconcile",
            "sweep": sweep,
            "results": results,
            "bounded": True,
            "max_runtime_seconds": max_runtime_seconds,
            "elapsed_ms": int((time.monotonic() - started_at) * 1_000),
            "stop_reason": stop_reason,
        }
