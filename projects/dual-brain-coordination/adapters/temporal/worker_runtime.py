"""Temporal Worker runtime — official Client.connect + Worker.run pattern.

docs.temporal.io develop/python/workers/run-worker-process:

    client = await Client.connect(...)
    worker = Worker(client, task_queue=..., workflows=[...], activities=[...])
    await worker.run()

G8 mature-bind anchors (path+line map):
  evidence/.../G8_mature_bind/MATURE_BIND_MAP.json  → binds B1_worker_entity, B7_start_workflow_tooling
  RetryPolicy / execute_activity live in package workflow.py + activities.py (B2/B3).

Does not touch kernel client.py (mock registry). This module is the live poller
attachment surface for queue xinao-dualbrain-promoted-v1.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from temporalio.client import Client
from temporalio.common import VersioningBehavior, WorkerDeploymentVersion
from temporalio.worker import Worker, WorkerDeploymentConfig

# Adapter SSOT — keep string names aligned with package registrations
from adapters.temporal.names import (
    WORKFLOW_TYPE as ADAPTER_WORKFLOW_TYPE,
)
from xinao_coordination.temporal.activities import PROMOTED_ACTIVITIES
from xinao_coordination.temporal.workflow import (
    DEFAULT_TASK_QUEUE,
    PROMOTED_WORKFLOWS,
    WORKFLOW_TYPE,
    XinaoPromotedTaskWorkflowV1,
)

if ADAPTER_WORKFLOW_TYPE != WORKFLOW_TYPE:
    raise RuntimeError(
        f"workflow name drift: package={WORKFLOW_TYPE!r} adapters.names={ADAPTER_WORKFLOW_TYPE!r}"
    )

DEFAULT_ADDRESS = "127.0.0.1:7233"
DEFAULT_NAMESPACE = "default"


DEFAULT_WORKER_IDENTITY = "xinao-promoted-worker-g1"
DEFAULT_DEPLOYMENT_NAME = "xinao-dualbrain-promoted"


@dataclass(frozen=True)
class WorkerRuntimeConfig:
    address: str = DEFAULT_ADDRESS
    namespace: str = DEFAULT_NAMESPACE
    task_queue: str = DEFAULT_TASK_QUEUE
    workflow_type: str = WORKFLOW_TYPE
    identity: str = DEFAULT_WORKER_IDENTITY
    deployment_name: str = DEFAULT_DEPLOYMENT_NAME
    worker_build_id: str = ""
    use_worker_versioning: bool = False

    @classmethod
    def from_env(cls) -> WorkerRuntimeConfig:
        versioning_raw = os.environ.get("XINAO_TEMPORAL_WORKER_VERSIONING", "0").strip().lower()
        if versioning_raw not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
            raise RuntimeError("XINAO_TEMPORAL_WORKER_VERSIONING_INVALID")
        use_worker_versioning = versioning_raw in {"1", "true", "yes", "on"}
        worker_build_id = os.environ.get("XINAO_TEMPORAL_WORKER_BUILD_ID", "").strip()
        deployment_name = os.environ.get(
            "XINAO_TEMPORAL_WORKER_DEPLOYMENT_NAME", DEFAULT_DEPLOYMENT_NAME
        ).strip()
        if use_worker_versioning and (not deployment_name or not worker_build_id):
            raise RuntimeError("XINAO_TEMPORAL_WORKER_VERSIONING_IDENTITY_REQUIRED")
        if worker_build_id and not use_worker_versioning:
            raise RuntimeError("XINAO_TEMPORAL_WORKER_VERSIONING_FLAG_REQUIRED")
        return cls(
            address=os.environ.get("XINAO_TEMPORAL_ADDRESS", DEFAULT_ADDRESS).strip() or DEFAULT_ADDRESS,
            namespace=os.environ.get("XINAO_TEMPORAL_NAMESPACE", DEFAULT_NAMESPACE).strip()
            or DEFAULT_NAMESPACE,
            task_queue=os.environ.get("XINAO_TEMPORAL_TASK_QUEUE", DEFAULT_TASK_QUEUE).strip()
            or DEFAULT_TASK_QUEUE,
            workflow_type=os.environ.get("XINAO_TEMPORAL_WORKFLOW_TYPE", WORKFLOW_TYPE).strip()
            or WORKFLOW_TYPE,
            identity=os.environ.get("XINAO_TEMPORAL_WORKER_IDENTITY", DEFAULT_WORKER_IDENTITY).strip()
            or DEFAULT_WORKER_IDENTITY,
            deployment_name=deployment_name or DEFAULT_DEPLOYMENT_NAME,
            worker_build_id=worker_build_id,
            use_worker_versioning=use_worker_versioning,
        )

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "address": self.address,
            "namespace": self.namespace,
            "task_queue": self.task_queue,
            "workflow_type": self.workflow_type,
            "identity": self.identity,
            "deployment_name": self.deployment_name,
            "worker_build_id": self.worker_build_id,
            "use_worker_versioning": self.use_worker_versioning,
        }


def build_worker_deployment_config(
    cfg: WorkerRuntimeConfig,
) -> WorkerDeploymentConfig | None:
    """Return the official GA Worker Deployment config for the promoted worker."""
    if not cfg.use_worker_versioning:
        return None
    if not cfg.deployment_name or not cfg.worker_build_id:
        raise RuntimeError("XINAO_TEMPORAL_WORKER_VERSIONING_IDENTITY_REQUIRED")
    return WorkerDeploymentConfig(
        version=WorkerDeploymentVersion(
            deployment_name=cfg.deployment_name,
            build_id=cfg.worker_build_id,
        ),
        use_worker_versioning=True,
        default_versioning_behavior=VersioningBehavior.PINNED,
    )


async def connect_temporal_client(
    *,
    address: str | None = None,
    namespace: str | None = None,
) -> Client:
    """Client.connect — minimal official connect for worker + starter."""
    cfg = WorkerRuntimeConfig.from_env()
    return await Client.connect(
        address or cfg.address,
        namespace=namespace or cfg.namespace,
    )


def build_promoted_worker(
    client: Client,
    *,
    task_queue: str | None = None,
    workflows: Sequence[type] | None = None,
    activities: Sequence[Any] | None = None,
    identity: str | None = None,
) -> Worker:
    """Construct Worker entity polling the promoted task queue."""
    cfg = WorkerRuntimeConfig.from_env()
    deployment_config = build_worker_deployment_config(cfg)
    return Worker(
        client,
        task_queue=task_queue or cfg.task_queue,
        workflows=list(workflows) if workflows is not None else list(PROMOTED_WORKFLOWS),
        activities=list(activities) if activities is not None else list(PROMOTED_ACTIVITIES),
        identity=identity or cfg.identity,
        deployment_config=deployment_config,
    )


async def run_promoted_worker(
    *,
    address: str | None = None,
    namespace: str | None = None,
    task_queue: str | None = None,
) -> None:
    """Connect + poll until cancelled (SIGINT / process stop)."""
    cfg = WorkerRuntimeConfig.from_env()
    client = await connect_temporal_client(address=address, namespace=namespace)
    worker = build_promoted_worker(
        client,
        task_queue=task_queue or cfg.task_queue,
        identity=cfg.identity,
    )
    await worker.run()


async def start_promoted_workflow(
    client: Client,
    workflow_input: dict[str, Any],
    *,
    workflow_id: str | None = None,
    task_queue: str | None = None,
):
    """start_workflow — official Client API (docs.temporal.io develop/python/client).

    Prefer this from worker-side tooling / self-tests. Kernel live start remains
    in client.py (out of G8 writer scope).
    """
    cfg = WorkerRuntimeConfig.from_env()
    wid = workflow_id or str(workflow_input.get("workflow_id") or "")
    if not wid:
        task_id = str(workflow_input.get("task_id") or "unknown")
        gen = int(workflow_input.get("generation") or 0)
        wid = f"xinao-task-{task_id}-g{gen}"
    handle = await client.start_workflow(
        XinaoPromotedTaskWorkflowV1.run,
        workflow_input,
        id=wid,
        task_queue=task_queue or cfg.task_queue,
    )
    return handle


__all__ = [
    "DEFAULT_ADDRESS",
    "DEFAULT_DEPLOYMENT_NAME",
    "DEFAULT_NAMESPACE",
    "DEFAULT_WORKER_IDENTITY",
    "WorkerRuntimeConfig",
    "build_promoted_worker",
    "build_worker_deployment_config",
    "connect_temporal_client",
    "run_promoted_worker",
    "start_promoted_workflow",
]
