"""One-process extension of the existing Docker control broker.

The original OpenHands queue remains unchanged.  A second, fixed Temporal
binding handles only the pgBackRest maintenance Activity.  This file exists to
avoid a second Docker-socket owner or a second scheduler.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_workflow_registry import (
    collect_openhands_worker_binding,
)
from services.agent_runtime.openhands_execution_worker import (
    SCHEMA_VERSION as OPENHANDS_WORKER_SCHEMA,
)
from services.agent_runtime.openhands_execution_worker import (
    SENTINEL as OPENHANDS_SENTINEL,
)

SCHEMA_VERSION = "xinao.platform_control_worker.v1"
SENTINEL = "SENTINEL:XINAO_PLATFORM_CONTROL_WORKER_READY"
MAINTENANCE_TASK_QUEUE = "xinao-platform-maintenance-v1"
DEFAULT_BROKER_IMAGE_ID = "sha256:e74057f05d1f337180e32372296cda91146890b7854d31bc0ab7b78b9e4a85b0"


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _require_file_hash(path: Path, environment_name: str) -> str:
    expected = os.environ.get(environment_name, "").strip().lower()
    if len(expected) != 64:
        raise ValueError(f"{environment_name} must pin a SHA-256")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"{environment_name} does not match {path.name}")
    return actual


def _validate_worker_input() -> dict[str, str]:
    worker_path = Path(__file__).resolve()
    return {
        "worker_sha256": _require_file_hash(worker_path, "XINAO_PLATFORM_CONTROL_WORKER_SHA256"),
    }


def _validate_maintenance_inputs() -> dict[str, str]:
    worker_path = Path(__file__).resolve()
    module_path = worker_path.with_name("platform_capacity_maintenance.py")
    policy_path = Path(os.environ.get("XINAO_CAPACITY_POLICY", ""))
    if not policy_path.is_file():
        raise ValueError("XINAO_CAPACITY_POLICY must name the mounted policy file")
    config_path = Path(os.environ.get("XINAO_PGBACKREST_CONFIG", ""))
    if not config_path.is_file():
        raise ValueError("XINAO_PGBACKREST_CONFIG must name the mounted config file")
    result = {
        "maintenance_module_sha256": _require_file_hash(
            module_path, "XINAO_PLATFORM_CAPACITY_MODULE_SHA256"
        ),
        "policy_sha256": _require_file_hash(policy_path, "XINAO_PLATFORM_CAPACITY_POLICY_SHA256"),
        "pgbackrest_config_sha256": _require_file_hash(
            config_path, "XINAO_PGBACKREST_CONFIG_SHA256"
        ),
    }
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if (
        policy.get("postgres", {}).get("expected_pgbackrest_config_sha256")
        != result["pgbackrest_config_sha256"]
    ):
        raise ValueError("capacity policy does not bind the mounted pgBackRest config")
    return result


def _validate_broker_identity() -> dict[str, Any]:
    import docker

    expected_image = os.environ.get(
        "XINAO_PLATFORM_BROKER_IMAGE_ID", DEFAULT_BROKER_IMAGE_ID
    ).strip()
    client = docker.from_env()
    try:
        broker = client.containers.get("mowei-zhixing")
        broker.reload()
        attrs = broker.attrs
        labels = (attrs.get("Config") or {}).get("Labels") or {}
        failures = []
        if attrs.get("Image") != expected_image:
            failures.append("image_id")
        if labels.get("com.docker.compose.project") != "xinao-base":
            failures.append("compose_project")
        if labels.get("com.docker.compose.service") != "mowei-zhixing":
            failures.append("compose_service")
        if labels.get("xinao.endpoint_owner") != "openhands-execution-broker-v1":
            failures.append("endpoint_owner")
        if (attrs.get("State") or {}).get("Status") != "running":
            failures.append("running")
        socket_owners: list[dict[str, str]] = []
        for container in client.containers.list():
            container.reload()
            current = container.attrs
            if any(
                str(mount.get("Destination") or "") == "/var/run/docker.sock"
                for mount in (current.get("Mounts") or [])
            ):
                socket_owners.append(
                    {
                        "container_id": str(current.get("Id") or container.id),
                        "container_name": str(current.get("Name") or "").lstrip("/"),
                    }
                )
        if socket_owners != [
            {
                "container_id": str(attrs.get("Id") or broker.id),
                "container_name": "mowei-zhixing",
            }
        ]:
            failures.append("unique_docker_socket_owner")
        if failures:
            raise ValueError(f"Docker control broker identity failed: {failures}")
        return {
            "container_id": str(attrs.get("Id") or broker.id),
            "image_id": str(attrs.get("Image") or ""),
            "endpoint_owner": str(labels.get("xinao.endpoint_owner") or ""),
            "docker_socket_owner_count": len(socket_owners),
        }
    finally:
        client.close()


async def run_platform_control_worker(
    *,
    address: str,
    namespace: str,
    runtime_root: Path,
    identity: str,
    maintenance_only: bool,
) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    worker_input = _validate_worker_input()
    broker_identity = _validate_broker_identity()
    client = await Client.connect(address, namespace=namespace)
    maintenance_state = runtime_root / "state" / "platform_capacity_maintenance_worker"

    with ThreadPoolExecutor(max_workers=4) as activity_executor:
        async with AsyncExitStack() as stack:
            openhands = None
            if not maintenance_only:
                openhands = collect_openhands_worker_binding()
                openhands_worker = Worker(
                    client,
                    task_queue=openhands.task_queue,
                    workflows=openhands.workflows,
                    activities=openhands.activities,
                    activity_executor=activity_executor,
                    identity=identity,
                )
                await stack.enter_async_context(openhands_worker)

            maintenance_inputs: dict[str, str] = {}
            maintenance_workflows: list[type] = []
            maintenance_activities: list[Any] = []
            maintenance_enabled = False
            maintenance_error: str | None = None
            try:
                maintenance_inputs = _validate_maintenance_inputs()
                module = importlib.import_module(
                    "services.agent_runtime.platform_capacity_maintenance"
                )
                if module.TASK_QUEUE != MAINTENANCE_TASK_QUEUE:
                    raise ValueError("maintenance module task queue drifted")
                maintenance_workflows, maintenance_activities = module.temporal_exports()
                maintenance_worker = Worker(
                    client,
                    task_queue=MAINTENANCE_TASK_QUEUE,
                    workflows=maintenance_workflows,
                    activities=maintenance_activities,
                    activity_executor=activity_executor,
                    identity=f"{identity}-platform-maintenance",
                )
                await stack.enter_async_context(maintenance_worker)
                maintenance_enabled = True
            except Exception as exc:
                if maintenance_only:
                    raise
                maintenance_error = f"{type(exc).__name__}: {str(exc)[:512]}"

            generated_at = datetime.now().astimezone().isoformat()
            state = {
                "schema_version": SCHEMA_VERSION,
                "sentinel": SENTINEL,
                "status": "polling" if maintenance_enabled else "openhands_only",
                "identity": identity,
                "address": address,
                "namespace": namespace,
                "maintenance_only": maintenance_only,
                "maintenance_enabled": maintenance_enabled,
                "maintenance_error": maintenance_error,
                "maintenance_task_queue": MAINTENANCE_TASK_QUEUE,
                "maintenance_workflow_count": len(maintenance_workflows),
                "maintenance_activity_count": len(maintenance_activities),
                "scheduler_created_by_this_worker": False,
                "worker_input": worker_input,
                "maintenance_inputs": maintenance_inputs,
                "broker_identity": broker_identity,
                "generated_at": generated_at,
            }
            state_name = "canary-latest.json" if maintenance_only else "latest.json"
            _write_json_atomic(maintenance_state / state_name, state)
            if not maintenance_only:
                assert openhands is not None
                _write_json_atomic(
                    runtime_root / "state" / "openhands_execution_worker" / "latest.json",
                    {
                        "schema_version": OPENHANDS_WORKER_SCHEMA,
                        "sentinel": OPENHANDS_SENTINEL,
                        "status": "polling",
                        "identity": identity,
                        "address": address,
                        "namespace": namespace,
                        "task_queue": openhands.task_queue,
                        "workflow_count": len(openhands.workflows),
                        "activity_count": len(openhands.activities),
                        "docker_control_owner": True,
                        "model_worker": False,
                        "orchestrator": False,
                        "completion_claim_allowed": False,
                        "platform_maintenance_extension": {
                            "enabled": maintenance_enabled,
                            "error": maintenance_error,
                            "task_queue": MAINTENANCE_TASK_QUEUE,
                            "worker_state": str(maintenance_state / "latest.json"),
                        },
                        "generated_at": generated_at,
                    },
                )
            await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Combined fixed-role Docker control worker")
    parser.add_argument("--address", default=os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233"))
    parser.add_argument("--namespace", default=os.environ.get("TEMPORAL_NAMESPACE", "default"))
    parser.add_argument(
        "--runtime-root",
        default=os.environ.get("XINAO_RESEARCH_RUNTIME", r"D:\XINAO_RESEARCH_RUNTIME"),
    )
    parser.add_argument(
        "--identity",
        default=os.environ.get(
            "XINAO_OPENHANDS_WORKER_IDENTITY", "xinao-openhands-execution-broker-v1"
        ),
    )
    parser.add_argument("--maintenance-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        asyncio.run(
            run_platform_control_worker(
                address=args.address,
                namespace=args.namespace,
                runtime_root=Path(args.runtime_root),
                identity=args.identity,
                maintenance_only=args.maintenance_only,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
