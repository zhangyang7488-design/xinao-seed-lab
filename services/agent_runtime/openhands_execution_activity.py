"""Hardened Activity adapter for the pinned OpenHands agent-server image."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import docker
import httpx
from docker.errors import NotFound
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.exceptions import CancelledError as TemporalCancelledError

from services.agent_runtime.openhands_execution_contract import (
    ACTIVITY_NAME,
    BROKER_CONTAINER_NAME,
    BROKER_ENDPOINT_ID,
    CONTROL_NETWORK,
    IMAGE,
    NETWORK_ENDPOINT_ID,
    PER_REQUEST_NETWORK_PREFIX,
    SCHEMA_VERSION,
    SDK_VERSION,
    execute_request_hash,
    validate_execute_request,
)

ENDPOINT_ID = "openhands-agent-server-hardened-v2"
MAX_RETURN_BYTES = 262_144
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_IDENTITY_LABELS = {
    "workflow_id": "xinao.temporal.workflow_id",
    "workflow_run_id": "xinao.temporal.workflow_run_id",
    "activity_id": "xinao.temporal.activity_id",
    "activity_run_id": "xinao.temporal.activity_run_id",
}


def _runtime_root() -> Path:
    return Path(os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"))


def _docker_client() -> Any:
    return docker.from_env()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _bounded(value: str) -> str:
    raw = value.encode("utf-8", errors="replace")[:MAX_RETURN_BYTES]
    return raw.decode("utf-8", errors="replace")


def _safe_name(value: str, *, limit: int = 36) -> str:
    return (_SAFE.sub("-", value).strip("-.") or "operation")[:limit]


def _heartbeat(details: dict[str, Any]) -> None:
    try:
        activity.heartbeat(details)
    except RuntimeError:
        # Pure unit tests call this helper outside a Temporal Activity context.
        pass


def _cancelled() -> bool:
    try:
        return activity.is_cancelled()
    except RuntimeError:
        return False


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _broker_container(client: Any) -> Any:
    name = os.environ.get("XINAO_OPENHANDS_BROKER_CONTAINER", BROKER_CONTAINER_NAME)
    broker = client.containers.get(name)
    broker.reload()
    labels = (broker.attrs.get("Config") or {}).get("Labels") or {}
    if (
        labels.get("com.docker.compose.service") != BROKER_CONTAINER_NAME
        or labels.get("xinao.endpoint_owner") != BROKER_ENDPOINT_ID
    ):
        raise RuntimeError("OpenHands broker container identity mismatch")
    return broker


def _network_name(request_hash: str, identity: dict[str, Any]) -> str:
    return f"{PER_REQUEST_NETWORK_PREFIX}_{request_hash[:12]}_a{int(identity['attempt'])}"


def _network_labels(request_hash: str, identity: dict[str, Any]) -> dict[str, str]:
    return {
        "xinao.endpoint": NETWORK_ENDPOINT_ID,
        "xinao.request_hash": request_hash,
        **_identity_labels(identity),
    }


def _validate_request_network(
    network: Any,
    request_hash: str,
    identity: dict[str, Any],
    *,
    expected_member_ids: set[str],
) -> dict[str, Any]:
    network.reload()
    value = network.attrs
    network_name = str(value.get("Name") or "")
    labels = {str(key): str(item) for key, item in (value.get("Labels") or {}).items()}
    members = set((value.get("Containers") or {}).keys())
    failures: list[str] = []
    if value.get("Internal") is not True:
        failures.append("internal")
    if str(value.get("Driver")) != "bridge":
        failures.append("driver")
    if labels.get("xinao.endpoint") != NETWORK_ENDPOINT_ID:
        failures.append("endpoint_label")
    if labels.get("xinao.request_hash") != request_hash:
        failures.append("request_hash_label")
    if not _labels_match_identity(labels, identity):
        failures.append("temporal_execution_identity")
    if network_name == CONTROL_NETWORK or not network_name.startswith(
        f"{PER_REQUEST_NETWORK_PREFIX}_"
    ):
        failures.append("per_request_network_name")
    if members != expected_member_ids:
        failures.append("network_members")
    if failures:
        raise RuntimeError(f"sandbox request network admission failed: {failures}")
    return {
        "network_id": str(network.id),
        "network_name": network_name,
        "driver": "bridge",
        "internal": True,
        "member_container_ids": sorted(members),
        "temporal_attempt": int(identity["attempt"]),
    }


def _create_request_network(
    client: Any,
    request_hash: str,
    identity: dict[str, Any],
) -> Any:
    name = _network_name(request_hash, identity)
    network = client.networks.create(
        name,
        driver="bridge",
        internal=True,
        attachable=False,
        check_duplicate=True,
        labels=_network_labels(request_hash, identity),
    )
    return network


def _normalize_execution_identity(
    request: dict[str, Any],
    request_hash: str,
    execution_identity: dict[str, Any] | None,
) -> dict[str, Any]:
    source = execution_identity or {}
    identity = {
        "workflow_id": str(source.get("workflow_id") or request["parent_workflow_id"]),
        "workflow_run_id": str(source.get("workflow_run_id") or "direct"),
        "activity_id": str(source.get("activity_id") or ACTIVITY_NAME),
        "activity_run_id": str(source.get("activity_run_id") or request_hash),
        "attempt": int(source.get("attempt") or 1),
    }
    if identity["attempt"] < 1:
        raise ValueError("activity attempt must be positive")
    if any(not identity[field].strip() for field in _IDENTITY_LABELS):
        raise ValueError("Temporal execution identity must be complete")
    return identity


def _identity_labels(identity: dict[str, Any]) -> dict[str, str]:
    labels = {label: str(identity[field]) for field, label in _IDENTITY_LABELS.items()}
    labels["xinao.temporal.attempt"] = str(identity["attempt"])
    return labels


def _container_labels(container: Any) -> dict[str, str]:
    container.reload()
    labels = (container.attrs.get("Config") or {}).get("Labels") or {}
    return {str(key): str(value) for key, value in labels.items()}


def _labels_match_identity(labels: dict[str, str], identity: dict[str, Any]) -> bool:
    expected = _identity_labels(identity)
    return all(labels.get(key) == value for key, value in expected.items())


def _reconcile_prior_attempts(
    client: Any,
    request_hash: str,
    identity: dict[str, Any],
    broker: Any,
) -> dict[str, Any]:
    """Remove only exact older attempt containers and networks after a crash."""

    matches = client.containers.list(
        all=True,
        filters={
            "label": [
                "xinao.endpoint=openhands-execution-v1",
                f"xinao.request_hash={request_hash}",
            ]
        },
    )
    removed_containers: list[str] = []
    for container in matches:
        labels = _container_labels(container)
        same_execution = all(
            labels.get(label) == str(identity[field]) for field, label in _IDENTITY_LABELS.items()
        )
        try:
            prior_attempt = int(labels.get("xinao.temporal.attempt") or 0)
        except ValueError as exc:
            raise RuntimeError("sandbox reconciliation attempt label is invalid") from exc
        if not same_execution:
            raise RuntimeError("sandbox reconciliation identity mismatch")
        if prior_attempt < 1 or prior_attempt >= int(identity["attempt"]):
            raise RuntimeError("sandbox reconciliation found a non-prior attempt")
        container_id = str(container.id)
        container.remove(force=True)
        try:
            client.containers.get(container_id)
        except NotFound:
            removed_containers.append(container_id)
        else:
            raise RuntimeError("sandbox reconciliation could not remove prior attempt")
    network_matches = client.networks.list(
        filters={
            "label": [
                f"xinao.endpoint={NETWORK_ENDPOINT_ID}",
                f"xinao.request_hash={request_hash}",
            ]
        }
    )
    removed_networks: list[str] = []
    broker_id = str(broker.id)
    for network in network_matches:
        network.reload()
        value = network.attrs
        labels = {str(key): str(item) for key, item in (value.get("Labels") or {}).items()}
        same_execution = all(
            labels.get(label) == str(identity[field]) for field, label in _IDENTITY_LABELS.items()
        )
        try:
            prior_attempt = int(labels.get("xinao.temporal.attempt") or 0)
        except ValueError as exc:
            raise RuntimeError("network reconciliation attempt label is invalid") from exc
        if not same_execution:
            raise RuntimeError("network reconciliation identity mismatch")
        if prior_attempt < 1 or prior_attempt >= int(identity["attempt"]):
            raise RuntimeError("network reconciliation found a non-prior attempt")
        members = set((value.get("Containers") or {}).keys())
        if members - {broker_id}:
            raise RuntimeError("network reconciliation found an unexpected member")
        if broker_id in members:
            network.disconnect(broker, force=True)
        network_id = str(network.id)
        network.remove()
        try:
            client.networks.get(network_id)
        except NotFound:
            removed_networks.append(network_id)
        else:
            raise RuntimeError("network reconciliation could not remove prior attempt")
    return {
        "containers_scanned": len(matches),
        "containers_removed": len(removed_containers),
        "removed_container_ids": removed_containers,
        "networks_scanned": len(network_matches),
        "networks_removed": len(removed_networks),
        "removed_network_ids": removed_networks,
        "current_attempt": int(identity["attempt"]),
    }


def _start_container(
    client: Any,
    *,
    name: str,
    request: dict[str, Any],
    request_hash: str,
    identity: dict[str, Any],
    network_name: str,
) -> Any:
    client.images.get(IMAGE)
    labels = {
        "xinao.endpoint": "openhands-execution-v1",
        "xinao.operation_key": request["operation_key"],
        "xinao.request_hash": request_hash,
        **_identity_labels(identity),
    }
    return client.containers.run(
        IMAGE,
        command=["--host", "0.0.0.0", "--port", "8000"],
        name=name,
        detach=True,
        remove=False,
        platform="linux/amd64",
        labels=labels,
        network=network_name,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        pids_limit=128,
        mem_limit="1g",
        nano_cpus=1_000_000_000,
        read_only=True,
        tmpfs={
            # The official binary extracts shared objects under /tmp at start.
            # It therefore requires executable mappings there; the container
            # boundary, dropped capabilities, internal network, and no binds
            # remain the security boundary.
            "/tmp": "rw,exec,nosuid,size=256m,mode=1777",
            "/workspace": "rw,exec,nosuid,size=512m,uid=10001,gid=10001,mode=0700",
            "/home/openhands": "rw,nosuid,size=256m,uid=10001,gid=10001,mode=0700",
        },
    )


def _validate_container(
    container: Any,
    request_hash: str,
    identity: dict[str, Any],
    network_name: str,
) -> dict[str, Any]:
    container.reload()
    value = container.attrs
    container_id = str(container.id)
    host = value.get("HostConfig") or {}
    config = value.get("Config") or {}
    labels = config.get("Labels") or {}
    networks = ((value.get("NetworkSettings") or {}).get("Networks") or {}).keys()
    failures: list[str] = []
    if labels.get("xinao.request_hash") != request_hash:
        failures.append("request_hash_label")
    if not _labels_match_identity(labels, identity):
        failures.append("temporal_execution_identity")
    if host.get("Privileged") is not False:
        failures.append("privileged")
    if host.get("ReadonlyRootfs") is not True:
        failures.append("readonly_rootfs")
    if host.get("NetworkMode") != network_name:
        failures.append("network_mode")
    if set(networks) != {network_name}:
        failures.append("network_attachment")
    if host.get("Binds"):
        failures.append("host_binds")
    if host.get("PortBindings"):
        failures.append("published_ports")
    if "ALL" not in set(host.get("CapDrop") or []):
        failures.append("cap_drop")
    security_options = set(host.get("SecurityOpt") or [])
    if not any(item.startswith("no-new-privileges") for item in security_options):
        failures.append("no_new_privileges")
    if int(host.get("PidsLimit") or 0) != 128:
        failures.append("pids_limit")
    if int(host.get("Memory") or 0) != 1_073_741_824:
        failures.append("memory_limit")
    if int(host.get("NanoCpus") or 0) != 1_000_000_000:
        failures.append("cpu_limit")
    if failures:
        raise RuntimeError(f"sandbox admission failed: {failures}")
    return {
        "container_id": container_id,
        "container_name": str(value.get("Name") or "").lstrip("/"),
        "image_id": str(value.get("Image") or ""),
        "user": str(config.get("User") or ""),
        "network": network_name,
        "readonly_rootfs": True,
        "privileged": False,
        "host_bind_count": 0,
        "published_port_count": 0,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 128,
        "memory_bytes": 1_073_741_824,
        "nano_cpus": 1_000_000_000,
        "temporal_attempt": int(identity["attempt"]),
    }


def _wait_for_health(base_url: str, container: Any, *, timeout: float = 120.0) -> None:
    container_id = str(container.id)
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if _cancelled():
                raise asyncio.CancelledError("sandbox Activity cancelled during startup")
            try:
                response = client.get(f"{base_url}/health")
                if 200 <= response.status_code < 300:
                    return
            except httpx.HTTPError:
                # Startup refusal is expected; the bounded deadline and container state decide failure.
                pass
            try:
                container.reload()
            except NotFound as exc:
                raise RuntimeError("agent-server disappeared before health") from exc
            if container.status != "running":
                logs = container.logs(tail=80).decode("utf-8", errors="replace")
                raise RuntimeError(f"agent-server stopped before health: {logs[-2000:]}")
            _heartbeat({"phase": "health", "container_id": container_id})
            time.sleep(0.25)
    raise RuntimeError("agent-server health deadline exceeded")


def _execute_remote(base_url: str, command: str, timeout: int) -> dict[str, Any]:
    with httpx.Client(timeout=httpx.Timeout(timeout + 5.0, connect=5.0)) as client:
        response = client.post(
            f"{base_url}/api/bash/start_bash_command",
            json={"command": command, "timeout": timeout, "cwd": "/workspace"},
        )
        response.raise_for_status()
        command_id = str(response.json()["id"])
        deadline = time.monotonic() + timeout
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        seen: set[str] = set()
        last_order = -1
        exit_code: int | None = None
        while time.monotonic() < deadline:
            if _cancelled():
                raise asyncio.CancelledError("sandbox Activity cancelled during command")
            params: dict[str, str | int] = {
                "command_id__eq": command_id,
                "sort_order": "TIMESTAMP",
                "limit": 100,
                "kind__eq": "BashOutput",
            }
            if last_order >= 0:
                params["order__gt"] = last_order
            events = client.get(f"{base_url}/api/bash/bash_events/search", params=params)
            events.raise_for_status()
            for item in events.json().get("items", []):
                event_id = str(item.get("id") or "")
                if event_id and event_id in seen:
                    raise RuntimeError("duplicate OpenHands BashOutput event")
                if event_id:
                    seen.add(event_id)
                order = item.get("order")
                if isinstance(order, int):
                    last_order = max(last_order, order)
                if item.get("stdout"):
                    stdout_parts.append(str(item["stdout"]))
                if item.get("stderr"):
                    stderr_parts.append(str(item["stderr"]))
                if item.get("exit_code") is not None:
                    exit_code = int(item["exit_code"])
            _heartbeat({"phase": "command", "command_id": command_id})
            if exit_code is not None:
                break
            time.sleep(0.1)
        if exit_code is None:
            exit_code = -1
            stderr_parts.append(f"command timed out after {timeout} seconds")
        return {
            "command_id": command_id,
            "exit_code": exit_code,
            "stdout": _bounded("".join(stdout_parts)),
            "stderr": _bounded("".join(stderr_parts)),
            "timeout_occurred": exit_code == -1,
        }


def _cleanup_exact(
    client: Any,
    container_id: str,
    request_hash: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    try:
        container = client.containers.get(container_id)
    except NotFound:
        return {"attempted": True, "removed": True, "already_absent": True}
    labels = (container.attrs.get("Config") or {}).get("Labels") or {}
    if labels.get("xinao.request_hash") != request_hash or not _labels_match_identity(
        {str(key): str(value) for key, value in labels.items()}, identity
    ):
        return {"attempted": False, "removed": False, "identity_mismatch": True}
    container.remove(force=True)
    try:
        client.containers.get(container_id)
        removed = False
    except NotFound:
        removed = True
    return {
        "attempted": True,
        "removed": removed,
        "already_absent": False,
    }


def _cleanup_request_network_exact(
    client: Any,
    network_id: str,
    request_hash: str,
    identity: dict[str, Any],
    broker: Any,
) -> dict[str, Any]:
    try:
        network = client.networks.get(network_id)
    except NotFound:
        return {"attempted": True, "removed": True, "already_absent": True}
    network.reload()
    value = network.attrs
    labels = {str(key): str(item) for key, item in (value.get("Labels") or {}).items()}
    if (
        labels.get("xinao.endpoint") != NETWORK_ENDPOINT_ID
        or labels.get("xinao.request_hash") != request_hash
        or not _labels_match_identity(labels, identity)
    ):
        return {"attempted": False, "removed": False, "identity_mismatch": True}
    broker_id = str(broker.id)
    members = set((value.get("Containers") or {}).keys())
    if members - {broker_id}:
        return {
            "attempted": False,
            "removed": False,
            "unexpected_member_ids": sorted(members - {broker_id}),
        }
    if broker_id in members:
        network.disconnect(broker, force=True)
    network.remove()
    try:
        client.networks.get(network_id)
        removed = False
    except NotFound:
        removed = True
    return {
        "attempted": True,
        "removed": removed,
        "already_absent": False,
        "disconnected_broker": broker_id in members,
    }


def _return_or_raise_endpoint_failure(result: dict[str, Any]) -> dict[str, Any]:
    """Turn infrastructure failures into Temporal retries, not false completions."""

    error_type = str(result.get("error_type") or "")
    error_message = str(result.get("error_message") or "")
    cleanup = result.get("cleanup") or {}
    if error_type:
        admission_failure = any(
            marker in error_message
            for marker in (
                "sandbox admission failed",
                "sandbox request network admission failed",
                "OpenHands broker container identity mismatch",
                "sandbox reconciliation identity mismatch",
                "sandbox reconciliation found a non-prior attempt",
                "sandbox reconciliation attempt label is invalid",
                "network reconciliation identity mismatch",
                "network reconciliation found a non-prior attempt",
                "network reconciliation attempt label is invalid",
                "network reconciliation found an unexpected member",
                "docker did not return an exact container ID",
                "docker did not return an exact network ID",
            )
        )
        raise ApplicationError(
            error_message or error_type,
            {"endpoint_error_type": error_type},
            type=(
                "OpenHandsEndpointAdmissionError"
                if admission_failure
                else "OpenHandsEndpointInfrastructureError"
            ),
            non_retryable=admission_failure,
        )
    if cleanup.get("removed") is not True:
        raise ApplicationError(
            "OpenHands endpoint exact cleanup did not complete",
            type="OpenHandsEndpointInfrastructureError",
            non_retryable=False,
        )
    return result


def execute_openhands_command_core(
    payload: dict[str, Any],
    *,
    execution_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one request in a fresh, admitted OpenHands container."""

    request = validate_execute_request(payload)
    request_hash = execute_request_hash(request)
    identity = _normalize_execution_identity(request, request_hash, execution_identity)
    started = time.monotonic()
    container_id = ""
    network_id = ""
    network_name = ""
    cleanup: dict[str, Any] = {
        "container": {"attempted": False, "removed": True, "not_created": True},
        "network": {"attempted": False, "removed": True, "not_created": True},
        "removed": True,
    }
    reconciliation: dict[str, Any] = {
        "containers_scanned": 0,
        "containers_removed": 0,
        "removed_container_ids": [],
        "networks_scanned": 0,
        "networks_removed": 0,
        "removed_network_ids": [],
        "current_attempt": int(identity["attempt"]),
    }
    admission: dict[str, Any] = {}
    network_admission: dict[str, Any] = {}
    remote: dict[str, Any] = {}
    error_type = ""
    error_message = ""
    cancelled = False
    cancelled_error: BaseException | None = None
    operation = _safe_name(request["operation_key"])
    name = f"xinao-oh-{operation}-{request_hash[:12]}-a{identity['attempt']}"
    client: Any | None = None
    broker: Any | None = None
    try:
        client = _docker_client()
        broker = _broker_container(client)
        reconciliation = _reconcile_prior_attempts(client, request_hash, identity, broker)
        network = _create_request_network(client, request_hash, identity)
        network_id = str(network.id)
        if not re.fullmatch(r"[0-9a-f]{64}", network_id):
            raise RuntimeError("docker did not return an exact network ID")
        network_name = _network_name(request_hash, identity)
        network.connect(broker, aliases=[BROKER_CONTAINER_NAME])
        network_admission = _validate_request_network(
            network,
            request_hash,
            identity,
            expected_member_ids={str(broker.id)},
        )
        container = _start_container(
            client,
            name=name,
            request=request,
            request_hash=request_hash,
            identity=identity,
            network_name=network_name,
        )
        container_id = str(container.id)
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise RuntimeError("docker did not return an exact container ID")
        admission = _validate_container(container, request_hash, identity, network_name)
        network_admission = _validate_request_network(
            network,
            request_hash,
            identity,
            expected_member_ids={str(broker.id), container_id},
        )
        base_url = f"http://{name}:8000"
        _wait_for_health(base_url, container)
        remote = _execute_remote(
            base_url,
            request["command"],
            request["timeout_seconds"],
        )
    except (asyncio.CancelledError, TemporalCancelledError) as exc:
        cancelled = True
        cancelled_error = exc
        error_type = type(exc).__name__
        error_message = str(exc)[:2000]
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)[:2000]
    finally:
        container_cleanup = {
            "attempted": False,
            "removed": True,
            "not_created": True,
        }
        if client is not None and container_id:
            try:
                container_cleanup = _cleanup_exact(client, container_id, request_hash, identity)
            except Exception as exc:
                container_cleanup = {
                    "attempted": True,
                    "removed": False,
                    "cleanup_error_type": type(exc).__name__,
                    "cleanup_error_message": str(exc)[:2000],
                }
        network_cleanup = {
            "attempted": False,
            "removed": True,
            "not_created": True,
        }
        if client is not None and broker is not None and network_id:
            try:
                network_cleanup = _cleanup_request_network_exact(
                    client, network_id, request_hash, identity, broker
                )
            except Exception as exc:
                network_cleanup = {
                    "attempted": True,
                    "removed": False,
                    "cleanup_error_type": type(exc).__name__,
                    "cleanup_error_message": str(exc)[:2000],
                }
        cleanup = {
            "container": container_cleanup,
            "network": network_cleanup,
            "removed": (
                container_cleanup.get("removed") is True and network_cleanup.get("removed") is True
            ),
        }
        if client is not None:
            client.close()
    elapsed_ms = int((time.monotonic() - started) * 1000)
    stdout = str(remote.get("stdout") or "")
    stderr = str(remote.get("stderr") or "")
    ok = not error_type and remote.get("exit_code") == 0 and cleanup.get("removed") is True
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "endpoint_id": ENDPOINT_ID,
        "sdk_version": SDK_VERSION,
        "image": IMAGE,
        "request_hash": request_hash,
        "operation_key": request["operation_key"],
        "parent_operation_id": request["parent_operation_id"],
        "parent_workflow_id": request["parent_workflow_id"],
        "lane_id": request["lane_id"],
        "temporal_execution": identity,
        "startup_reconciliation": reconciliation,
        "command_sha256": _sha(request["command"]),
        "container": admission,
        "network": network_admission,
        "exit_code": remote.get("exit_code"),
        "stdout_sha256": _sha(stdout),
        "stderr_sha256": _sha(stderr),
        "timeout_occurred": remote.get("timeout_occurred", False),
        "cancelled": cancelled,
        "cleanup": cleanup,
        "error_type": error_type,
        "error_message": error_message,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "generated_at": datetime.now().astimezone().isoformat(),
        "completion_claim_allowed": False,
    }
    evidence_dir = (
        _runtime_root() / "state" / "openhands_execution_endpoint" / request_hash / "result.json"
    ).parent
    attempt_evidence_path = evidence_dir / f"attempt-{int(identity['attempt']):03d}.json"
    evidence_path = evidence_dir / "result.json"
    _write_json_atomic(attempt_evidence_path, evidence)
    _write_json_atomic(evidence_path, evidence)
    if cancelled_error is not None:
        raise cancelled_error
    return {
        "schema_version": SCHEMA_VERSION,
        "endpoint_id": ENDPOINT_ID,
        "request_hash": request_hash,
        "ok": ok,
        "exit_code": remote.get("exit_code"),
        "stdout": stdout,
        "stderr": stderr,
        "timeout_occurred": remote.get("timeout_occurred", False),
        "error_type": error_type,
        "error_message": error_message,
        "cleanup": cleanup,
        "evidence_path": str(evidence_path),
        "attempt_evidence_path": str(attempt_evidence_path),
        "elapsed_ms": elapsed_ms,
    }


@activity.defn(name=ACTIVITY_NAME)
def execute_openhands_command_activity(payload: dict[str, Any]) -> dict[str, Any]:
    info = activity.info()
    return _return_or_raise_endpoint_failure(
        execute_openhands_command_core(
            payload,
            execution_identity={
                "workflow_id": info.workflow_id,
                "workflow_run_id": info.workflow_run_id,
                "activity_id": info.activity_id,
                "activity_run_id": info.activity_run_id,
                "attempt": info.attempt,
            },
        )
    )


__all__ = [
    "ENDPOINT_ID",
    "_reconcile_prior_attempts",
    "_return_or_raise_endpoint_failure",
    "execute_openhands_command_activity",
    "execute_openhands_command_core",
]
