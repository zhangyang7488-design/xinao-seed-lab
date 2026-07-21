"""Create and operate the single Temporal capacity-maintenance Schedule.

The Schedule is created paused, canaried with an explicit trigger, and only
then unpaused.  No OS task, cron entry, watchdog or second scheduler is used.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.openhands_execution_contract import (
    SCHEMA_VERSION as OPENHANDS_SCHEMA,
)
from services.agent_runtime.openhands_execution_contract import (
    TASK_QUEUE as OPENHANDS_TASK_QUEUE,
)
from services.agent_runtime.openhands_execution_contract import (
    XinaoOpenHandsExecuteWorkflowV1,
    execute_request_hash,
)
from services.agent_runtime.platform_capacity_maintenance import (
    REQUEST_SCHEMA,
    RESULT_SCHEMA,
    load_policy,
)
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    WorkflowExecutionStatus,
)
from temporalio.common import RetryPolicy
from temporalio.service import RPCError, RPCStatusCode

DEFAULT_POLICY = REPO_ROOT / "infra" / "capacity" / "maintenance-policy.v1.json"
DEFAULT_VERIFIED_RESULT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\platform_capacity_maintenance\latest.json"
)
_STATIC_SUMMARY = "Catalog-aware local PostgreSQL backup and capacity maintenance"
_STATIC_DETAILS = "Fixed pgBackRest full/check/verify through the existing Docker control owner."
_OPENHANDS_CANARY_COMMAND = "printf platform-control-openhands-admission-ok"
_OPENHANDS_WORKER_IDENTITY = "xinao-openhands-execution-broker-v1"


def _paused_note(policy_hash: str) -> str:
    return f"policy_sha256={policy_hash}; create paused, trigger canary, then unpause"


def _active_note(policy_hash: str) -> str:
    return f"canary verified; policy_sha256={policy_hash}"


def _desired_schedule(policy: dict[str, Any], policy_hash: str, *, paused: bool) -> Schedule:
    temporal = policy["temporal"]
    return Schedule(
        action=ScheduleActionStartWorkflow(
            temporal["workflow_type"],
            {"schema_version": REQUEST_SCHEMA, "policy_sha256": policy_hash},
            id=temporal["workflow_id"],
            task_queue=temporal["task_queue"],
            run_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=100),
                maximum_attempts=1,
            ),
            static_summary=_STATIC_SUMMARY,
            static_details=_STATIC_DETAILS,
        ),
        spec=ScheduleSpec(
            cron_expressions=[temporal["cron"]],
            time_zone_name=temporal["time_zone"],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(minutes=int(temporal["catchup_window_minutes"])),
            pause_on_failure=True,
        ),
        state=ScheduleState(
            note=_paused_note(policy_hash),
            paused=paused,
        ),
    )


def _ranges(value: Any, name: str) -> list[tuple[int, int, int]]:
    return [(int(item.start), int(item.end), int(item.step)) for item in getattr(value, name)]


def _is_exact_daily_0330_spec(spec: Any, temporal: dict[str, Any]) -> bool:
    common = (
        list(spec.intervals) == []
        and list(spec.skip) == []
        and spec.start_at is None
        and spec.end_at is None
        and spec.jitter is None
        and spec.time_zone_name == temporal["time_zone"]
    )
    if not common:
        return False
    if list(spec.cron_expressions) == [temporal["cron"]] and list(spec.calendars) == []:
        return True
    calendars = list(spec.calendars)
    if list(spec.cron_expressions) or len(calendars) != 1:
        return False
    calendar = calendars[0]
    return (
        _ranges(calendar, "second") == [(0, 0, 1)]
        and _ranges(calendar, "minute") == [(30, 30, 1)]
        and _ranges(calendar, "hour") == [(3, 3, 1)]
        and _ranges(calendar, "day_of_month") == [(1, 31, 1)]
        and _ranges(calendar, "month") == [(1, 12, 1)]
        and _ranges(calendar, "year") == []
        and _ranges(calendar, "day_of_week") == [(0, 6, 1)]
        and calendar.comment is None
    )


async def _require_live_schedule(
    value: Any,
    data_converter: Any,
    policy: dict[str, Any],
    policy_hash: str,
    *,
    paused: bool,
    expected_note: str,
) -> dict[str, Any]:
    temporal = policy["temporal"]
    schedule = value.schedule
    action = schedule.action
    if getattr(action, "_from_raw", False):
        args = await data_converter.decode(action.args)
        summary = (
            (await data_converter.decode([action.static_summary]))[0]
            if action.static_summary is not None
            else None
        )
        details = (
            (await data_converter.decode([action.static_details]))[0]
            if action.static_details is not None
            else None
        )
    else:
        args = list(action.args)
        summary = action.static_summary
        details = action.static_details

    retry = action.retry_policy
    drift: list[str] = []
    checks = {
        "schedule_id": value.id == temporal["schedule_id"],
        "workflow_type": str(action.workflow) == temporal["workflow_type"],
        "workflow_input": args
        == [{"schema_version": REQUEST_SCHEMA, "policy_sha256": policy_hash}],
        "workflow_id": action.id == temporal["workflow_id"],
        "task_queue": action.task_queue == temporal["task_queue"],
        "execution_timeout": action.execution_timeout is None,
        "run_timeout": action.run_timeout == timedelta(minutes=30),
        "task_timeout": action.task_timeout is None,
        "retry_initial": retry is not None and retry.initial_interval == timedelta(seconds=1),
        "retry_backoff": retry is not None and retry.backoff_coefficient == 2.0,
        "retry_maximum": retry is not None and retry.maximum_interval == timedelta(seconds=100),
        "retry_attempts": retry is not None and retry.maximum_attempts == 1,
        "static_summary": summary == _STATIC_SUMMARY,
        "static_details": details == _STATIC_DETAILS,
        "schedule_spec": _is_exact_daily_0330_spec(schedule.spec, temporal),
        "overlap": schedule.policy.overlap == ScheduleOverlapPolicy.SKIP,
        "catchup": schedule.policy.catchup_window
        == timedelta(minutes=int(temporal["catchup_window_minutes"])),
        "pause_on_failure": schedule.policy.pause_on_failure is True,
        "paused": schedule.state.paused is paused,
        "state_note": schedule.state.note == expected_note,
        "limited_actions": schedule.state.limited_actions is False,
        "remaining_actions": schedule.state.remaining_actions == 0,
        "running_actions": len(value.info.running_actions) == 0,
    }
    drift.extend(name for name, passed in checks.items() if not passed)
    if drift:
        raise ValueError(f"live capacity Schedule drifted: {drift}")
    return _description(value)


async def _require_latest_completed_execution(
    schedule_description: Any,
    client: Any,
    verified: dict[str, Any],
) -> None:
    recent = list(schedule_description.info.recent_actions)
    if not recent or schedule_description.info.running_actions:
        raise ValueError("capacity Schedule has no uniquely closed latest action")
    latest = max(recent, key=lambda item: item.started_at)
    action = latest.action
    identity = verified.get("identity") or {}
    workflow_id = str(identity.get("workflow_id") or "")
    workflow_run_id = str(identity.get("workflow_run_id") or "")
    if action.workflow_id != workflow_id or action.first_execution_run_id != workflow_run_id:
        raise ValueError("latest capacity result is not the latest Schedule action")
    workflow_handle = client.get_workflow_handle(workflow_id, run_id=workflow_run_id)
    workflow_description = await workflow_handle.describe()
    if workflow_description.status != WorkflowExecutionStatus.COMPLETED:
        raise ValueError("latest capacity Schedule Workflow is not COMPLETED")
    closed_result = await workflow_handle.result()
    if not isinstance(closed_result, dict):
        raise ValueError("latest capacity Schedule Workflow result is invalid")
    if closed_result != verified:
        raise ValueError("latest capacity receipt differs from the full closed Workflow result")


async def _require_task_queue_pollers(
    client: Any,
    *,
    namespace: str,
    task_queue: str,
    expected_identity: str,
) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for queue_type, type_name in (
        (TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW, "workflow"),
        (TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY, "activity"),
    ):
        deadline = asyncio.get_running_loop().time() + 20
        while True:
            response = await client.workflow_service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace=namespace,
                    task_queue=TaskQueue(name=task_queue),
                    task_queue_type=queue_type,
                )
            )
            now = datetime.now(timezone.utc)
            fresh = []
            for poller in response.pollers:
                last_access = poller.last_access_time.ToDatetime(tzinfo=timezone.utc)
                age = now - last_access
                if timedelta(minutes=-1) <= age <= timedelta(minutes=2):
                    fresh.append((poller, last_access))
            unexpected = [poller.identity for poller, _ in fresh if poller.identity != expected_identity]
            if unexpected:
                raise ValueError(
                    f"{task_queue} {type_name} has unexpected fresh pollers: {unexpected}"
                )
            expected = [(poller, seen) for poller, seen in fresh if poller.identity == expected_identity]
            if expected:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise ValueError(f"{task_queue} {type_name} has no fresh expected poller")
            await asyncio.sleep(1)
        backlog = int(response.task_queue_status.backlog_count_hint)
        if backlog != 0:
            raise ValueError(f"{task_queue} {type_name} queue has backlog")
        newest_access = max(seen for _, seen in expected)
        observed.append(
            {
                "task_queue": task_queue,
                "task_type": type_name,
                "identity": expected_identity,
                "fresh_poller_records": len(expected),
                "last_access_utc": newest_access.isoformat(),
                "backlog": backlog,
            }
        )
    return observed


def _require_unique_docker_owner(policy: dict[str, Any]) -> str:
    import docker

    expected = policy["docker_control_broker"]
    client = docker.from_env()
    try:
        owners: list[Any] = []
        for container in client.containers.list():
            container.reload()
            if any(
                str(mount.get("Destination") or "") == "/var/run/docker.sock"
                for mount in (container.attrs.get("Mounts") or [])
            ):
                owners.append(container)
        if len(owners) != 1:
            raise ValueError("Docker socket must have exactly one running container owner")
        owner = owners[0]
        attrs = owner.attrs
        labels = (attrs.get("Config") or {}).get("Labels") or {}
        checks = {
            "container_name": str(attrs.get("Name") or "").lstrip("/")
            == expected["container_name"],
            "image_id": attrs.get("Image") == expected["expected_image_id"],
            "compose_project": labels.get("com.docker.compose.project")
            == expected["compose_project"],
            "compose_service": labels.get("com.docker.compose.service")
            == expected["compose_service"],
            "endpoint_owner": labels.get("xinao.endpoint_owner") == expected["endpoint_owner"],
            "running": (attrs.get("State") or {}).get("Status") == "running",
            "healthy": (attrs.get("State") or {}).get("Health", {}).get("Status")
            in (None, "healthy"),
        }
        drift = [name for name, passed in checks.items() if not passed]
        if drift:
            raise ValueError(f"unique Docker control owner drifted: {drift}")
        return str(attrs.get("Id") or owner.id)
    finally:
        client.close()


async def _run_openhands_admission_canary(
    client: Any,
    *,
    policy_hash: str,
    broker_container_id: str,
) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:12]
    request = {
        "schema_version": OPENHANDS_SCHEMA,
        "operation_key": f"capacity-admission-{suffix}",
        "command": _OPENHANDS_CANARY_COMMAND,
        "timeout_seconds": 60,
        "parent_operation_id": f"capacity-policy-{policy_hash[:16]}",
        "parent_workflow_id": "capacity-schedule-unpause-admission",
        "lane_id": "platform-control-admission",
    }
    workflow_id = f"xinao-openhands-capacity-admission-{broker_container_id[:12]}-{suffix}"
    result = await client.execute_workflow(
        XinaoOpenHandsExecuteWorkflowV1.run,
        request,
        id=workflow_id,
        task_queue=OPENHANDS_TASK_QUEUE,
        run_timeout=timedelta(minutes=5),
    )
    expected_hash = execute_request_hash(request)
    cleanup = result.get("cleanup") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != OPENHANDS_SCHEMA
        or result.get("request_hash") != expected_hash
        or result.get("ok") is not True
        or result.get("exit_code") != 0
        or result.get("stdout") != "platform-control-openhands-admission-ok"
        or result.get("stderr") != ""
        or result.get("timeout_occurred") is not False
        or result.get("error_type") != ""
        or not isinstance(cleanup, dict)
        or cleanup.get("removed") is not True
        or (cleanup.get("container") or {}).get("removed") is not True
        or (cleanup.get("network") or {}).get("removed") is not True
    ):
        raise ValueError("OpenHands admission canary did not close cleanly")

    import docker

    docker_client = docker.from_env()
    try:
        label = f"xinao.request_hash={expected_hash}"
        if docker_client.containers.list(all=True, filters={"label": label}):
            raise ValueError("OpenHands admission canary left a container")
        if docker_client.networks.list(filters={"label": label}):
            raise ValueError("OpenHands admission canary left a network")
    finally:
        docker_client.close()
    return {
        "workflow_id": workflow_id,
        "request_hash": expected_hash,
        "exit_code": 0,
        "stdout_sha256": hashlib.sha256(b"platform-control-openhands-admission-ok").hexdigest(),
        "cleanup_removed": True,
    }


async def _require_platform_runtime(
    client: Any,
    *,
    namespace: str,
    policy: dict[str, Any],
    policy_hash: str,
) -> dict[str, Any]:
    broker_id = _require_unique_docker_owner(policy)
    owner_identity = _OPENHANDS_WORKER_IDENTITY
    pollers = await _require_task_queue_pollers(
        client,
        namespace=namespace,
        task_queue=OPENHANDS_TASK_QUEUE,
        expected_identity=owner_identity,
    )
    pollers.extend(
        await _require_task_queue_pollers(
            client,
            namespace=namespace,
            task_queue=str(policy["temporal"]["task_queue"]),
            expected_identity=f"{owner_identity}-platform-maintenance",
        )
    )
    canary = await _run_openhands_admission_canary(
        client,
        policy_hash=policy_hash,
        broker_container_id=broker_id,
    )
    if _require_unique_docker_owner(policy) != broker_id:
        raise ValueError("Docker control owner changed during OpenHands admission")
    return {
        "broker_container_id": broker_id,
        "docker_socket_owner_count": 1,
        "pollers": pollers,
        "openhands_canary": canary,
    }


def _description(value: Any) -> dict[str, Any]:
    schedule = value.schedule
    info = value.info
    action = schedule.action
    return {
        "schedule_id": value.id,
        "paused": schedule.state.paused,
        "note": schedule.state.note,
        "workflow_type": str(getattr(action, "workflow", "")),
        "workflow_id": getattr(action, "id", None),
        "task_queue": getattr(action, "task_queue", None),
        "cron_expressions": list(schedule.spec.cron_expressions),
        "time_zone": schedule.spec.time_zone_name,
        "overlap_policy": schedule.policy.overlap.name,
        "catchup_window_seconds": int(schedule.policy.catchup_window.total_seconds()),
        "pause_on_failure": schedule.policy.pause_on_failure,
        "action_count": info.num_actions,
        "missed_catchup_window": info.num_actions_missed_catchup_window,
        "overlap_skipped": info.num_actions_skipped_overlap,
        "running_actions": len(info.running_actions),
        "recent_actions": len(info.recent_actions),
        "next_action_times": [item.isoformat() for item in info.next_action_times],
    }


def _require_verified_result(
    path: Path, policy: dict[str, Any], policy_hash: str
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema_version") != RESULT_SCHEMA
        or value.get("status") != "verified"
        or value.get("policy_sha256") != policy_hash
    ):
        raise ValueError("latest capacity result is not verified for the current policy")
    if value.get("explicit_delete_command_count") != 0:
        raise ValueError("latest capacity result contains an explicit delete command")
    if value.get("repo_status_code") != 0 or not value.get("newest_backup_label"):
        raise ValueError("latest capacity result lacks a healthy pgBackRest catalog result")
    broker_result = value.get("docker_control_broker") or {}
    broker_policy = policy["docker_control_broker"]
    for field, expected in (
        ("container_name", broker_policy["container_name"]),
        ("image_id", broker_policy["expected_image_id"]),
        ("compose_project", broker_policy["compose_project"]),
        ("compose_service", broker_policy["compose_service"]),
    ):
        if broker_result.get(field) != expected:
            raise ValueError(f"latest capacity result used another Docker broker {field}")
    postgres_result = value.get("postgres") or {}
    postgres_policy = policy["postgres"]
    for field, expected in (
        ("container_name", postgres_policy["container_name"]),
        ("image_id", postgres_policy["expected_image_id"]),
        ("compose_project", postgres_policy["compose_project"]),
        ("compose_service", postgres_policy["compose_service"]),
        (
            "pgbackrest_config_sha256",
            postgres_policy["expected_pgbackrest_config_sha256"],
        ),
    ):
        if postgres_result.get(field) != expected:
            raise ValueError(f"latest capacity result used another PostgreSQL {field}")
    steps = value.get("steps") or []
    expected_steps = [
        ("preflight", postgres_policy["commands"]["preflight"]),
        ("info", postgres_policy["commands"]["info"]),
        ("backup", postgres_policy["commands"]["backup"]),
        ("verify", postgres_policy["commands"]["verify"]),
        ("info", postgres_policy["commands"]["info"]),
    ]
    if len(steps) != len(expected_steps):
        raise ValueError("latest capacity result pgBackRest step count drifted")
    for step, (expected_name, expected_argv) in zip(steps, expected_steps, strict=True):
        if (
            step.get("step") != expected_name
            or step.get("argv") != expected_argv
            or step.get("exec_os_user") != "postgres"
            or step.get("exit_code") != 0
            or step.get("skipped") is True
        ):
            raise ValueError("latest capacity result pgBackRest step identity drifted")
    completed = datetime.fromisoformat(str(value.get("completed_at_utc")))
    age = datetime.now(timezone.utc) - completed if completed.tzinfo is not None else None
    if age is None or age < timedelta(minutes=-5) or age > timedelta(hours=24):
        raise ValueError("latest capacity result is stale")
    workflow_id = str(value.get("identity", {}).get("workflow_id") or "")
    workflow_run_id = str(value.get("identity", {}).get("workflow_run_id") or "")
    schedule_prefix = str(policy["temporal"]["schedule_id"]) + "-"
    if not workflow_id.startswith(schedule_prefix) or not workflow_run_id:
        raise ValueError("latest capacity result is not owned by the capacity Schedule")
    labels_after = value.get("backup_labels_after")
    if (
        not isinstance(labels_after, list)
        or value["newest_backup_label"] not in labels_after
        or not isinstance(value.get("catalog_labels_expired"), list)
    ):
        raise ValueError("latest capacity result catalog identity is incomplete")
    return value


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    policy_path = Path(args.policy).resolve()
    policy, policy_hash = load_policy(policy_path)
    schedule_id = str(policy["temporal"]["schedule_id"])
    client = await Client.connect(args.address, namespace=args.namespace)
    handle = client.get_schedule_handle(schedule_id)

    if args.action == "ensure":
        desired = _desired_schedule(policy, policy_hash, paused=True)
        created = False
        try:
            await handle.describe()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
            handle = await client.create_schedule(schedule_id, desired)
            created = True
        else:
            await handle.update(lambda _input: ScheduleUpdate(schedule=desired))
        current = await handle.describe()
        description = await _require_live_schedule(
            current,
            client.data_converter,
            policy,
            policy_hash,
            paused=True,
            expected_note=_paused_note(policy_hash),
        )
        return {
            "status": "ensured_paused",
            "created": created,
            "policy_sha256": policy_hash,
            "description": description,
        }

    if args.action == "describe":
        return {
            "status": "described",
            "policy_sha256": policy_hash,
            "description": _description(await handle.describe()),
        }
    if args.action == "trigger":
        await _require_live_schedule(
            await handle.describe(),
            client.data_converter,
            policy,
            policy_hash,
            paused=True,
            expected_note=_paused_note(policy_hash),
        )
        await handle.trigger(overlap=ScheduleOverlapPolicy.SKIP)
        return {
            "status": "triggered",
            "policy_sha256": policy_hash,
            "description": _description(await handle.describe()),
        }
    if args.action == "pause":
        await handle.pause(note=f"operator pause; policy_sha256={policy_hash}")
        return {"status": "paused", "description": _description(await handle.describe())}
    if args.action == "unpause":
        verified = _require_verified_result(
            Path(args.verified_result).resolve(), policy, policy_hash
        )
        current = await handle.describe()
        await _require_live_schedule(
            current,
            client.data_converter,
            policy,
            policy_hash,
            paused=True,
            expected_note=_paused_note(policy_hash),
        )
        await _require_latest_completed_execution(current, client, verified)
        runtime_admission = await _require_platform_runtime(
            client,
            namespace=args.namespace,
            policy=policy,
            policy_hash=policy_hash,
        )
        await handle.unpause(note=_active_note(policy_hash))
        description = await _require_live_schedule(
            await handle.describe(),
            client.data_converter,
            policy,
            policy_hash,
            paused=False,
            expected_note=_active_note(policy_hash),
        )
        return {
            "status": "unpaused",
            "verified_result": str(Path(args.verified_result).resolve()),
            "verified_backup_label": verified["newest_backup_label"],
            "runtime_admission": runtime_admission,
            "description": description,
        }
    if args.action == "delete":
        if args.confirm_delete != schedule_id:
            raise ValueError(f"--confirm-delete must equal {schedule_id}")
        await handle.delete()
        return {"status": "deleted", "schedule_id": schedule_id}
    raise ValueError(f"unsupported action: {args.action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the canonical capacity Temporal Schedule")
    parser.add_argument(
        "action", choices=("ensure", "describe", "trigger", "pause", "unpause", "delete")
    )
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--verified-result", default=str(DEFAULT_VERIFIED_RESULT))
    parser.add_argument("--confirm-delete", default="")
    args = parser.parse_args(argv)
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
