"""Read-only mapping from the local durable model to official A2A 1.0 objects."""

from __future__ import annotations

from typing import Any

from a2a.types import Artifact, Message, Part, Role, Task, TaskState, TaskStatus
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp

from .service import CoordinationService

TASK_STATE_MAP = {
    "queued": TaskState.TASK_STATE_SUBMITTED,
    "leased": TaskState.TASK_STATE_WORKING,
    "running": TaskState.TASK_STATE_WORKING,
    "paused": TaskState.TASK_STATE_INPUT_REQUIRED,
    "completed": TaskState.TASK_STATE_COMPLETED,
    "failed": TaskState.TASK_STATE_FAILED,
    "canceled": TaskState.TASK_STATE_CANCELED,
}


def _struct(value: dict[str, Any]) -> Struct:
    result = Struct()
    result.update(value)
    return result


def _timestamp(milliseconds: int) -> Timestamp:
    value = Timestamp()
    value.FromMilliseconds(milliseconds)
    return value


def export_task(service: CoordinationService, task_id: str) -> Task:
    """Build an official protobuf Task without creating a second persistent snapshot store."""

    result = service.get_task(task_id)
    task = result["task"]
    artifacts = result["artifacts"]
    assert isinstance(task, dict)
    assert isinstance(artifacts, list)

    history: list[Message] = []
    source_thread_id = task.get("source_thread_id")
    if source_thread_id:
        thread = service.get_thread(str(source_thread_id))
        for item in thread["messages"]:
            assert isinstance(item, dict)
            metadata = _struct(
                {
                    "xinao_sender": item["sender"],
                    "xinao_recipient": item["recipient"],
                    "xinao_kind": item["kind"],
                }
            )
            history.append(
                Message(
                    message_id=item["message_id"],
                    context_id=task["context_id"],
                    task_id=task["task_id"],
                    role=(Role.ROLE_USER if item["sender"] == "user" else Role.ROLE_AGENT),
                    parts=[Part(text=item["body"], media_type="text/plain")],
                    metadata=metadata,
                )
            )

    a2a_artifacts = [
        Artifact(
            artifact_id=item["artifact_id"],
            name=item["name"],
            parts=[
                Part(
                    url=item["uri"],
                    filename=item["name"],
                    media_type=item["media_type"],
                )
            ],
            metadata=_struct(
                {
                    "sha256": item.get("sha256") or "",
                    "size_bytes": item.get("size_bytes") or 0,
                    "created_by": item["created_by"],
                }
            ),
        )
        for item in artifacts
    ]

    return Task(
        id=task["task_id"],
        context_id=task["context_id"],
        status=TaskStatus(
            state=TASK_STATE_MAP[task["state"]],
            timestamp=_timestamp(task["updated_at_ms"]),
        ),
        artifacts=a2a_artifacts,
        history=history,
        metadata=_struct(
            {
                "xinao_title": task["title"],
                "xinao_goal": task["goal"],
                "xinao_consensus_status": task["consensus_status"],
                "xinao_assigned_role": task["assigned_role"],
                "xinao_version": task["version"],
            }
        ),
    )


def export_task_dict(service: CoordinationService, task_id: str) -> dict[str, Any]:
    return MessageToDict(
        export_task(service, task_id),
        preserving_proto_field_name=True,
        use_integers_for_enums=False,
    )
