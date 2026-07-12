"""Temporal client — mock registry for canary/CI; optional live temporalio SDK."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

from .envelope import PromotedTaskEnvelope
from .policy import temporal_policy

_MOCK_REGISTRY: dict[str, dict[str, object]] = {}
_REGISTRY_LOCK = threading.Lock()


def reset_mock_registry() -> None:
    with _REGISTRY_LOCK:
        _MOCK_REGISTRY.clear()


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def _import_temporal_client() -> type[Any]:
    from ..errors import ValidationError

    try:
        from temporalio.client import Client
    except ImportError as exc:
        raise ValidationError(
            "temporalio SDK is not installed; add temporalio to project dependencies",
            details={"import_error": type(exc).__name__, "message": str(exc)},
        ) from exc
    return Client


async def _connect_live_client(address: str, namespace: str) -> Any:
    from ..errors import ValidationError

    Client = _import_temporal_client()
    try:
        return await Client.connect(address, namespace=namespace)
    except Exception as exc:
        raise ValidationError(
            "Temporal live connect failed",
            details={
                "address": address,
                "namespace": namespace,
                "error": type(exc).__name__,
                "message": str(exc),
            },
        ) from exc


async def _describe_namespace(client: Any, namespace: str) -> dict[str, object]:
    from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest

    request = DescribeNamespaceRequest(namespace=namespace)
    response = await client.workflow_service.describe_namespace(request)
    info = response.namespace_info
    return {
        "namespace": info.name or namespace,
        "state": str(info.state),
        "id": info.id,
    }


async def _count_task_queue_pollers(client: Any, task_queue: str) -> int:
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

    request = DescribeTaskQueueRequest(
        namespace=client.namespace,
        task_queue=TaskQueue(name=task_queue),
        task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        report_stats=True,
        report_pollers=True,
    )
    response = await client.workflow_service.describe_task_queue(request)
    return len(response.pollers)


@dataclass
class TemporalClient:
    """Thin client: mock by default; live only when explicitly enabled."""

    address: str
    namespace: str
    task_queue: str
    workflow_type: str
    mock_mode: bool
    live_connect: bool

    @classmethod
    def from_policy(cls, policy: dict[str, object] | None = None) -> TemporalClient:
        pol = policy or temporal_policy()
        return cls(
            address=str(pol.get("address") or "127.0.0.1:7233"),
            namespace=str(pol.get("namespace") or "default"),
            task_queue=str(pol.get("task_queue") or "xinao-dualbrain-promoted-v1"),
            workflow_type=str(pol.get("workflow_type") or "XinaoPromotedTaskWorkflowV1"),
            mock_mode=bool(pol.get("mock_mode")),
            live_connect=bool(pol.get("live_connect")),
        )

    def _is_mock_path(self) -> bool:
        return self.mock_mode and not self.live_connect

    def _is_live_path(self) -> bool:
        return self.live_connect and not self.mock_mode

    async def _async_connectivity_probe_live(self) -> dict[str, object]:
        client = await _connect_live_client(self.address, self.namespace)
        try:
            ns_info = await _describe_namespace(client, self.namespace)
            pollers = await _count_task_queue_pollers(client, self.task_queue)
            return {
                "reachable": True,
                "mode": "live",
                "address": self.address,
                "namespace": self.namespace,
                "task_queue": self.task_queue,
                "namespace_info": ns_info,
                "pollers": pollers,
            }
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()

    def connectivity_probe(self) -> dict[str, object]:
        if not temporal_policy().get("enabled"):
            return {
                "reachable": False,
                "mode": "disabled",
                "note_cn": "XINAO_TEMPORAL_ENABLED=0",
            }
        if self._is_mock_path():
            return {
                "reachable": True,
                "mode": "mock",
                "address": self.address,
                "namespace": self.namespace,
                "task_queue": self.task_queue,
            }
        if self._is_live_path():
            try:
                return _run_async(self._async_connectivity_probe_live())
            except Exception as exc:
                from ..errors import ValidationError

                if isinstance(exc, ValidationError):
                    details = dict(exc.details)
                    details.setdefault("mode", "live")
                    return {
                        "reachable": False,
                        "mode": "live",
                        "address": self.address,
                        "namespace": self.namespace,
                        "error": type(exc).__name__,
                        "message": str(exc),
                        "details": details,
                    }
                return {
                    "reachable": False,
                    "mode": "live",
                    "address": self.address,
                    "namespace": self.namespace,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
        # Enabled but neither mock nor live (e.g. MOCK=0 without LIVE=1): socket best-effort.
        try:
            import socket

            host, _, port_s = self.address.partition(":")
            port = int(port_s or "7233")
            with socket.create_connection((host or "127.0.0.1", port), timeout=0.5):
                return {
                    "reachable": True,
                    "mode": "live_probe",
                    "address": self.address,
                    "namespace": self.namespace,
                    "task_queue": self.task_queue,
                }
        except OSError as exc:
            return {
                "reachable": False,
                "mode": "live_probe",
                "error": type(exc).__name__,
                "message": str(exc),
                "address": self.address,
            }

    async def _async_start_promoted_workflow_live(self, envelope: PromotedTaskEnvelope) -> dict[str, object]:
        from temporalio.exceptions import WorkflowAlreadyStartedError

        client = await _connect_live_client(self.address, self.namespace)
        try:
            try:
                handle = await client.start_workflow(
                    self.workflow_type,
                    envelope.to_workflow_input(),
                    id=envelope.workflow_id,
                    task_queue=envelope.task_queue,
                )
                run_id = getattr(handle, "result_run_id", None) or getattr(
                    handle, "first_execution_run_id", None
                )
                return {
                    "ok": True,
                    "workflow_id": envelope.workflow_id,
                    "workflow_type": envelope.workflow_type,
                    "task_queue": envelope.task_queue,
                    "run_id": run_id,
                    "mode": "live",
                    "replayed": False,
                }
            except WorkflowAlreadyStartedError:
                existing = client.get_workflow_handle(envelope.workflow_id)
                description = await existing.describe()
                return {
                    "ok": True,
                    "workflow_id": envelope.workflow_id,
                    "workflow_type": envelope.workflow_type,
                    "task_queue": envelope.task_queue,
                    "run_id": description.run_id,
                    "mode": "live",
                    "replayed": True,
                }
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()

    async def _async_request_cancel_promoted_workflow_live(
        self,
        workflow_id: str,
        run_id: str,
        reason: str,
    ) -> dict[str, object]:
        client = await _connect_live_client(self.address, self.namespace)
        try:
            handle = client.get_workflow_handle(workflow_id, run_id=run_id)
            description = await handle.describe()
            if str(description.run_id) != run_id:
                return {
                    "ok": False,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "observed_run_id": str(description.run_id),
                    "terminal_confirmed": False,
                    "error_type": "TemporalRunIdentityMismatch",
                    "reason": reason,
                }
            status_before = str(getattr(description.status, "name", description.status))
            if status_before == "CANCELED":
                return {
                    "ok": True,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "status_before": status_before,
                    "status_after": status_before,
                    "signal": "request_cancel",
                    "native_cancel_requested": False,
                    "terminal_confirmed": True,
                    "already_terminal": True,
                    "reason": reason,
                }
            if status_before in {"COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT"}:
                return {
                    "ok": False,
                    "workflow_id": workflow_id,
                    "run_id": run_id,
                    "status_before": status_before,
                    "status_after": status_before,
                    "native_cancel_requested": False,
                    "terminal_confirmed": False,
                    "already_terminal": True,
                    "error_type": "TemporalAlreadyTerminalNotCanceled",
                    "reason": reason,
                }
            await handle.signal("request_cancel", reason)
            # A signal alone only proves that cancellation was requested.  Issue
            # the native Temporal cancellation too, then wait for the exact run
            # to reach a terminal CANCELED state before reporting success.
            await handle.cancel()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 30.0
            terminal_names = {
                "COMPLETED",
                "FAILED",
                "CANCELED",
                "TERMINATED",
                "TIMED_OUT",
            }
            while True:
                current = await handle.describe()
                raw_status = current.status
                status_name = str(getattr(raw_status, "name", raw_status))
                if status_name in terminal_names:
                    cancelled = status_name == "CANCELED"
                    return {
                        "ok": cancelled,
                        "workflow_id": workflow_id,
                        "run_id": description.run_id,
                        "status_before": str(getattr(description.status, "name", description.status)),
                        "status_after": status_name,
                        "signal": "request_cancel",
                        "native_cancel_requested": True,
                        "terminal_confirmed": cancelled,
                        "reason": reason,
                    }
                if loop.time() >= deadline:
                    return {
                        "ok": False,
                        "workflow_id": workflow_id,
                        "run_id": description.run_id,
                        "status_before": str(getattr(description.status, "name", description.status)),
                        "status_after": status_name,
                        "signal": "request_cancel",
                        "native_cancel_requested": True,
                        "terminal_confirmed": False,
                        "error_type": "TemporalCancelUnconfirmed",
                        "reason": reason,
                    }
                await asyncio.sleep(0.1)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()

    def request_cancel_promoted_workflow(
        self,
        workflow_id: str,
        *,
        run_id: str,
        reason: str,
    ) -> dict[str, object]:
        """Cancel one exact recorded live workflow run; safe to repeat."""
        if not workflow_id.strip():
            raise ValueError("workflow_id is required")
        if not run_id.strip():
            raise ValueError("run_id is required; workflow-id-only cancellation is ambiguous")
        return _run_async(
            self._async_request_cancel_promoted_workflow_live(
                workflow_id.strip(),
                run_id.strip(),
                reason.strip() or "kernel user stop",
            )
        )

    def start_promoted_workflow(self, envelope: PromotedTaskEnvelope) -> dict[str, object]:
        from ..errors import ValidationError

        pol = temporal_policy()
        if not pol.get("enabled"):
            raise ValidationError(
                "Temporal adapter disabled (XINAO_TEMPORAL_ENABLED=0)",
                details={"enabled": False},
            )
        if pol.get("auto_start_on_promote"):
            raise ValidationError(
                "auto_start_on_promote must remain false",
                details={"auto_start_on_promote": True},
            )
        if self._is_mock_path():
            with _REGISTRY_LOCK:
                existing = _MOCK_REGISTRY.get(envelope.workflow_id)
                if existing:
                    return {
                        "ok": True,
                        "workflow_id": envelope.workflow_id,
                        "workflow_type": envelope.workflow_type,
                        "task_queue": envelope.task_queue,
                        "run_id": existing.get("run_id"),
                        "mode": "mock",
                        "replayed": True,
                    }
                run_id = f"mock-run-{envelope.workflow_id}"
                record = {
                    "workflow_id": envelope.workflow_id,
                    "workflow_type": envelope.workflow_type,
                    "task_queue": envelope.task_queue,
                    "run_id": run_id,
                    "input": envelope.to_workflow_input(),
                }
                _MOCK_REGISTRY[envelope.workflow_id] = record
                return {
                    "ok": True,
                    "workflow_id": envelope.workflow_id,
                    "workflow_type": envelope.workflow_type,
                    "task_queue": envelope.task_queue,
                    "run_id": run_id,
                    "mode": "mock",
                    "replayed": False,
                }
        if self._is_live_path():
            return _run_async(self._async_start_promoted_workflow_live(envelope))
        raise ValidationError(
            "live Temporal workflow start requires XINAO_TEMPORAL_LIVE=1, "
            "XINAO_TEMPORAL_MOCK=0, and worker registration",
            details={"live_connect": self.live_connect, "mock_mode": self.mock_mode},
        )

    def describe_promoted_queue(self) -> dict[str, object]:
        probe = self.connectivity_probe()
        if self._is_mock_path():
            with _REGISTRY_LOCK:
                backlog = len(_MOCK_REGISTRY)
            return {
                "mode": "mock",
                "task_queue": self.task_queue,
                "workflow_type": self.workflow_type,
                "connectivity": probe,
                "mock_backlog": backlog,
                "pollers": 1,
                "poller_source": "mock_synthetic",
            }
        if self._is_live_path():
            pollers = int(probe.get("pollers") or 0) if probe.get("reachable") else 0
            return {
                "mode": "live",
                "task_queue": self.task_queue,
                "workflow_type": self.workflow_type,
                "connectivity": probe,
                "mock_backlog": 0,
                "pollers": pollers,
                "poller_source": "temporal_describe_task_queue",
            }
        return {
            "mode": str(probe.get("mode") or "unknown"),
            "task_queue": self.task_queue,
            "workflow_type": self.workflow_type,
            "connectivity": probe,
            "mock_backlog": 0,
            "pollers": 0,
            "poller_source": "unavailable",
        }


def describe_promoted_queue(client: TemporalClient | None = None) -> dict[str, object]:
    cli = client or TemporalClient.from_policy()
    return cli.describe_promoted_queue()
