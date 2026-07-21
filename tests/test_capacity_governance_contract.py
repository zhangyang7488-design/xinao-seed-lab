from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.manage_platform_capacity_schedule import (
    _desired_schedule,
    _paused_note,
    _require_latest_completed_execution,
    _require_live_schedule,
    _require_verified_result,
)
from services.agent_runtime.platform_capacity_maintenance import RESULT_SCHEMA, load_policy
from temporalio.client import ScheduleOverlapPolicy, WorkflowExecutionStatus

ROOT = Path(__file__).resolve().parents[1]


def test_docker_projection_has_bounded_native_gc_and_rotated_local_logs() -> None:
    value = json.loads((ROOT / "infra" / "docker" / "daemon.capacity.json").read_text())
    assert value["builder"]["gc"] == {"defaultKeepStorage": "20GB", "enabled": True}
    assert value["log-driver"] == "local"
    assert value["log-opts"] == {"max-file": "3", "max-size": "10m"}


def test_schedule_is_paused_by_default_and_uses_temporal_safety_policy() -> None:
    policy, policy_hash = load_policy(ROOT / "infra" / "capacity" / "maintenance-policy.v1.json")
    schedule = _desired_schedule(policy, policy_hash, paused=True)
    assert schedule.state.paused is True
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.pause_on_failure is True
    assert int(schedule.policy.catchup_window.total_seconds()) == 1800
    assert schedule.spec.cron_expressions == ["30 3 * * *"]
    assert schedule.spec.time_zone_name == "Asia/Shanghai"

    described = SimpleNamespace(
        id=policy["temporal"]["schedule_id"],
        schedule=schedule,
        info=SimpleNamespace(
            num_actions=0,
            num_actions_missed_catchup_window=0,
            num_actions_skipped_overlap=0,
            running_actions=[],
            recent_actions=[],
            next_action_times=[],
        ),
    )
    asyncio.run(
        _require_live_schedule(
            described,
            None,
            policy,
            policy_hash,
            paused=True,
            expected_note=_paused_note(policy_hash),
        )
    )
    schedule.action.task_queue = "drifted-queue"
    with pytest.raises(ValueError, match="task_queue"):
        asyncio.run(
            _require_live_schedule(
                described,
                None,
                policy,
                policy_hash,
                paused=True,
                expected_note=_paused_note(policy_hash),
            )
        )


def test_capacity_path_does_not_create_an_os_scheduler_or_generic_cleanup() -> None:
    paths = [
        ROOT / "services" / "agent_runtime" / "platform_capacity_maintenance.py",
        ROOT / "services" / "agent_runtime" / "platform_control_worker.py",
        ROOT / "scripts" / "manage_platform_capacity_schedule.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
    for forbidden in (
        "register-scheduledtask",
        "new-scheduledtask",
        "schtasks.exe",
        "docker system prune",
        "docker volume prune",
        "remove-item",
        "archive_cleanup_command",
    ):
        assert forbidden not in text


def _valid_result(policy: dict[str, object], policy_hash: str) -> dict[str, object]:
    postgres = policy["postgres"]
    broker = policy["docker_control_broker"]
    assert isinstance(postgres, dict) and isinstance(broker, dict)
    commands = postgres["commands"]
    assert isinstance(commands, dict)
    return {
        "schema_version": RESULT_SCHEMA,
        "status": "verified",
        "policy_sha256": policy_hash,
        "explicit_delete_command_count": 0,
        "repo_status_code": 0,
        "newest_backup_label": "20260717-TESTF",
        "backup_labels_after": ["20260717-TESTF"],
        "catalog_labels_expired": [],
        "docker_control_broker": {
            "container_name": broker["container_name"],
            "image_id": broker["expected_image_id"],
            "compose_project": broker["compose_project"],
            "compose_service": broker["compose_service"],
        },
        "postgres": {
            "container_name": postgres["container_name"],
            "image_id": postgres["expected_image_id"],
            "compose_project": postgres["compose_project"],
            "compose_service": postgres["compose_service"],
            "pgbackrest_config_sha256": postgres["expected_pgbackrest_config_sha256"],
        },
        "steps": [
            {
                "step": name,
                "argv": commands[name],
                "exec_os_user": "postgres",
                "exit_code": 0,
            }
            for name in ("preflight", "info", "backup", "verify", "info")
        ],
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "identity": {
            "workflow_id": str(policy["temporal"]["schedule_id"]) + "-canary",
            "workflow_run_id": "run-canary",
        },
    }


def test_unpause_gate_requires_exact_current_receipt(tmp_path: Path) -> None:
    policy, policy_hash = load_policy(ROOT / "infra" / "capacity" / "maintenance-policy.v1.json")
    result = _valid_result(policy, policy_hash)
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    assert _require_verified_result(path, policy, policy_hash)["status"] == "verified"

    mutations = []
    missing = copy.deepcopy(result)
    missing["steps"].pop()
    mutations.append(missing)
    extra = copy.deepcopy(result)
    extra["steps"].append(copy.deepcopy(extra["steps"][-1]))
    mutations.append(extra)
    reordered = copy.deepcopy(result)
    reordered["steps"][0], reordered["steps"][1] = (
        reordered["steps"][1],
        reordered["steps"][0],
    )
    mutations.append(reordered)
    bad_argv = copy.deepcopy(result)
    bad_argv["steps"][2]["argv"] = ["pgbackrest", "delete"]
    mutations.append(bad_argv)
    wrong_user = copy.deepcopy(result)
    wrong_user["steps"][2]["exec_os_user"] = "root"
    mutations.append(wrong_user)
    nonzero = copy.deepcopy(result)
    nonzero["steps"][3]["exit_code"] = 1
    mutations.append(nonzero)
    skipped = copy.deepcopy(result)
    skipped["steps"][2]["skipped"] = True
    mutations.append(skipped)
    wrong_config = copy.deepcopy(result)
    wrong_config["postgres"]["pgbackrest_config_sha256"] = "0" * 64
    mutations.append(wrong_config)
    future = copy.deepcopy(result)
    future["completed_at_utc"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    mutations.append(future)
    stale = copy.deepcopy(result)
    stale["completed_at_utc"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    mutations.append(stale)

    for bad in mutations:
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            _require_verified_result(path, policy, policy_hash)


def test_closed_temporal_result_must_equal_full_local_receipt() -> None:
    policy, policy_hash = load_policy(ROOT / "infra" / "capacity" / "maintenance-policy.v1.json")
    closed = _valid_result(policy, policy_hash)
    identity = closed["identity"]

    class FakeHandle:
        async def describe(self) -> SimpleNamespace:
            return SimpleNamespace(status=WorkflowExecutionStatus.COMPLETED)

        async def result(self) -> dict[str, object]:
            return copy.deepcopy(closed)

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str, *, run_id: str) -> FakeHandle:
            assert workflow_id == identity["workflow_id"]
            assert run_id == identity["workflow_run_id"]
            return FakeHandle()

    schedule_description = SimpleNamespace(
        info=SimpleNamespace(
            running_actions=[],
            recent_actions=[
                SimpleNamespace(
                    started_at=datetime.now(timezone.utc),
                    action=SimpleNamespace(
                        workflow_id=identity["workflow_id"],
                        first_execution_run_id=identity["workflow_run_id"],
                    ),
                )
            ],
        )
    )
    asyncio.run(
        _require_latest_completed_execution(
            schedule_description,
            FakeClient(),
            copy.deepcopy(closed),
        )
    )

    rewritten = copy.deepcopy(closed)
    rewritten["steps"][2]["exec_os_user"] = "root"
    with pytest.raises(ValueError, match="full closed Workflow"):
        asyncio.run(
            _require_latest_completed_execution(
                schedule_description,
                FakeClient(),
                rewritten,
            )
        )
