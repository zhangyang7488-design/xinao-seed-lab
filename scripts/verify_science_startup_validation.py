#!/usr/bin/env python3
"""Run the bounded, non-research cold-start acceptance for the science parent.

This is a one-shot verifier, not a scheduler or a research runner. It starts one
validation-only science episode in a paused state, restarts the exact existing
``houtai-gongren`` container, resumes the same Temporal run, exercises the
world/ledger/Grok instrument chain, runs negative cases, and exits.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from temporalio.api.enums.v1 import EventType, TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import (
    Client,
    WorkflowExecutionStatus,
    WorkflowFailureError,
)
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.worker import Replayer

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.build_s_runtime_release import verify_release  # noqa: E402
from scripts.verify_houtai_gongren_restart_resume import (  # noqa: E402
    CONTAINER_NAME,
    _docker_restart,
    _rollback_start_if_exact_stopped,
    _static_identity,
    _wait_daemon_and_queues,
    docker_identity,
)
from services.agent_runtime.grok_build_docker_worker import (  # noqa: E402
    PROVIDER_ID,
    READ_ONLY_PERMISSION_MODE,
    READ_ONLY_SANDBOX_PROFILE,
)
from services.agent_runtime.grok_execution_contract_adapter import (  # noqa: E402
    expected_docker_grok_backend_models,
)
from services.agent_runtime.integrated_bus_worker_daemon import (  # noqa: E402
    SOURCE_RELEASE_CRITICAL_FILES,
)
from services.agent_runtime.xinao_mainline_canary import (  # noqa: E402
    XinaoResearchCampaignWorkflow,
)
from services.agent_runtime.xinao_science_episode_workflow import (  # noqa: E402
    SCIENCE_EPISODE_WORKFLOW_NAME,
    TASK_QUEUE,
    XinaoScienceEpisodeWorkflowV1,
)
from xinao.science import (  # noqa: E402
    canonical_world_measurement_bindings,
    load_science_active_parent,
)
from xinao.world import science_episode_world_root  # noqa: E402

RUNTIME = Path(r"D:\XINAO_RESEARCH_RUNTIME")
DEFAULT_RUN_DIR = (
    RUNTIME
    / "state"
    / "Codex_Situation_Island"
    / "runs"
    / "xinao-science-active-parent-20260724"
    / "evidence"
    / "science_startup_validation"
)
KNOWN_QUEUES = {
    TASK_QUEUE,
    "xinao-integrated-langgraph-plugin-queue",
    "xinao-integrated-bus-parent-queue",
    "xinao-integrated-bus-child-queue",
}
WINDOWLESS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_ACTIVE_WORKFLOW_IDS: set[str] = set()
RPC_TIMEOUT_SECONDS = 30.0
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_APP_MOUNTS = {
    "/app/AGENTS.md": "AGENTS.md",
    "/app/services": "services",
    "/app/projects": "projects",
    "/app/scripts": "scripts",
    "/app/docs": "docs",
    "/app/evals": "evals",
    "/app/pyproject.toml": "pyproject.toml",
    "/app/uv.lock": "uv.lock",
    "/app/xinao_discovery/src": "xinao_discovery/src",
    "/app/tests": "tests",
    "/app/materials": "materials",
    "/app/policies": "policies",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _host_to_container(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    marker = "D:/XINAO_RESEARCH_RUNTIME/"
    if not resolved.casefold().startswith(marker.casefold()):
        raise ValueError(f"validation artifact is outside the mounted runtime: {path}")
    return "/evidence/" + resolved[len(marker) :]


def _container_to_host(value: str) -> Path:
    normalized = value.replace("\\", "/")
    if normalized == "/evidence" or normalized.startswith("/evidence/"):
        relative = normalized.removeprefix("/evidence").lstrip("/")
        return RUNTIME / Path(relative)
    if normalized == "/mainline" or normalized.startswith("/mainline/"):
        relative = normalized.removeprefix("/mainline").lstrip("/")
        return Path(r"C:\Users\xx363\Desktop\主线") / Path(relative)
    path = Path(value)
    if path.is_absolute():
        return path
    raise ValueError(f"runtime receipt path is not a mounted absolute path: {value}")


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
        creationflags=WINDOWLESS,
    )
    value = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(value) != 40:
        raise RuntimeError("cannot resolve the repository Git commit")
    return value


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left.resolve(strict=False)))) == os.path.normcase(
        os.path.normpath(str(right.resolve(strict=False)))
    )


def _expected_source_release(
    *,
    release_dir: Path,
    manifest_path: Path,
    git_repo: Path,
    code_git_sha: str,
) -> dict[str, Any]:
    release_dir = release_dir.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    if not _same_path(REPO, release_dir):
        raise RuntimeError("startup verifier is not executing from the selected source release")
    verification = verify_release(
        release_dir,
        manifest_path,
        git_repo=git_repo,
    )
    if (
        verification.get("commit") != code_git_sha
        or verification.get("git_commit_verified") is not True
    ):
        raise RuntimeError("selected source release does not match --code-git-sha")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise RuntimeError("selected source release manifest has no file identities")
    critical_files: dict[str, str] = {}
    for relative in SOURCE_RELEASE_CRITICAL_FILES:
        binding = files.get(relative)
        if not isinstance(binding, dict) or not _HASH_RE.fullmatch(
            str(binding.get("sha256") or "")
        ):
            raise RuntimeError(f"selected source release omitted critical file: {relative}")
        critical_files[relative] = str(binding["sha256"])
    return {
        "status": "VERIFIED",
        "commit": code_git_sha,
        "tree": str(verification["tree"]),
        "git_commit_verified": True,
        "release_dir": str(release_dir),
        "manifest_ref": str(manifest_path),
        "manifest_sha256": str(verification["manifest_sha256"]),
        "file_count": int(verification["file_count"]),
        "critical_files": critical_files,
    }


def _verify_container_release_mounts(
    container: dict[str, Any],
    *,
    release_dir: Path,
) -> dict[str, Any]:
    by_destination = {
        str(item.get("destination") or "").rstrip("/"): item
        for item in container.get("mounts") or []
        if str(item.get("destination") or "").startswith("/app/")
    }
    if set(by_destination) != set(RELEASE_APP_MOUNTS):
        raise RuntimeError(
            "worker /app mount set differs from the source release contract: "
            f"missing={sorted(set(RELEASE_APP_MOUNTS) - set(by_destination))}, "
            f"extra={sorted(set(by_destination) - set(RELEASE_APP_MOUNTS))}"
        )
    verified: dict[str, dict[str, object]] = {}
    for destination, relative in RELEASE_APP_MOUNTS.items():
        mount = by_destination[destination]
        expected_source = release_dir.joinpath(*relative.split("/"))
        observed_source = Path(str(mount.get("source") or ""))
        if not _same_path(observed_source, expected_source):
            raise RuntimeError(f"worker mount is not from the selected release: {destination}")
        if mount.get("rw") is not False:
            raise RuntimeError(f"worker release mount is writable: {destination}")
        verified[destination] = {
            "source": str(observed_source),
            "relative": relative,
            "read_only": True,
        }
    return {
        "ok": True,
        "release_dir": str(release_dir.resolve(strict=True)),
        "mount_count": len(verified),
        "mounts": verified,
    }


def _verify_daemon_source_release(
    marker: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> dict[str, Any]:
    observed = marker.get("source_release")
    if not isinstance(observed, dict):
        raise RuntimeError("worker daemon did not report a source release identity")
    for name in ("status", "commit", "manifest_sha256", "critical_files"):
        if observed.get(name) != expected.get(name):
            raise RuntimeError(f"worker daemon source release drifted: {name}")
    return dict(observed)


def _materialize_validation_episode(
    run_dir: Path,
    *,
    active_parent_sha256: str,
    background_contract_sha256: str,
) -> dict[str, Any]:
    episode_id = f"science-startup-validation-{uuid.uuid4().hex[:12]}"
    material_dir = run_dir / "episode_materials" / episode_id
    world_path = material_dir / "world_measurement_bundle.json"
    exposure_path = material_dir / "exposure_inventory.json"
    ledger_path = material_dir / "science_trial_ledger.json"
    pin_path = material_dir / "protocol_pin.json"
    input_path = material_dir / "instrument_intake.md"
    frozen = datetime.now(UTC)
    target = frozen + timedelta(days=1)
    frozen_text = frozen.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    world_frozen_text = (
        (frozen - timedelta(seconds=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    target_text = target.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    world = {
        "schema_version": "xinao.world_measurement_bundle.v1",
        "episode_id": episode_id,
        "status": "WORLD_BOUND",
        "knowledge_cutoff": "2026-07-01T21:32:32Z",
        "target_open_time": target_text,
        "frozen_at": world_frozen_text,
        "bindings": canonical_world_measurement_bindings(
            background_contract_sha256=background_contract_sha256,
        ),
    }
    exposure = {
        "schema_version": "xinao.exposure_inventory.v1",
        "episode_id": episode_id,
        "status": "UNKNOWN",
        "items": [
            {
                "window_id": "startup-runtime-health",
                "fields": [
                    "active_parent_identity",
                    "world_replay_integrity",
                    "worker_recovery",
                    "instrument_bus_receipts",
                ],
                "disclosure_granularity": "aggregate-runtime-evidence-only",
                "status": "UNKNOWN",
                "evidence_refs": ["validation://no-evaluation-outcome-access"],
            }
        ],
    }
    ledger = {
        "schema_version": "xinao.science_trial_ledger.v1",
        "episode_id": episode_id,
        "append_only": True,
        "entries": [],
    }
    _write_json(world_path, world)
    _write_json(exposure_path, exposure)
    _write_json(ledger_path, ledger)
    pin = {
        "schema_version": "xinao.science_protocol_pin.v1",
        "episode_id": episode_id,
        "protocol_pin_id": f"{episode_id}-pin",
        "frozen_at": frozen_text,
        "active_parent_sha256": active_parent_sha256,
        "claim_intent": "STARTUP_VALIDATION",
        "research_question": {
            "question_id": "science-startup-runtime-readiness",
            "target": (
                "verify that the migrated software instruments start and recover "
                "without producing a scientific result"
            ),
            "non_goals": [
                "test a Xinao hypothesis",
                "inspect an evaluation outcome",
                "advance the scientific mainline",
            ],
        },
        "hypothesis": {
            "claim": "the migrated runtime resumes the same validation workflow",
            "counterexample": "one required instrument or recovery boundary fails",
        },
        "null_hypothesis": {
            "claim": "runtime validation establishes no domain-science finding",
            "falsification_rule": "not applicable to this validation-only episode",
        },
        "world_measurement_bundle": {
            "ref": str(world_path),
            "sha256": _sha256(world_path),
        },
        "exposure_inventory": {
            "ref": str(exposure_path),
            "sha256": _sha256(exposure_path),
            "status": "UNKNOWN",
        },
        "trial_ledger": {
            "ref": str(ledger_path),
            "sha256": _sha256(ledger_path),
        },
        "science_instrument_minimum": {
            "world_replay": True,
            "worker_bus": True,
            "checkpoint": True,
            "append_only_trial_ledger": True,
        },
        "protocol_controls": {
            "split_id": "startup-validation-no-research-split",
            "metrics": [
                "active_parent_integrity",
                "world_replay_integrity",
                "same_temporal_run_recovery",
                "instrument_bus_consumption",
            ],
            "baselines": ["pre-switch-reusable-instrument-runtime"],
            "negative_controls": [
                "world-binding-hash-drift",
                "startup-pin-used-as-research",
                "legacy-campaign-fresh-start",
            ],
            "stopping_rule": "stop after one bounded restart and all negative controls",
            "trial_family_id": "startup-validation-only",
            "error_budget_ledger_id": "startup-validation-no-science-error-budget",
            "e4_eligibility_rule": "never eligible for E4 or a research claim",
            "confirmation_query_budget": {"total": 0, "remaining": 0},
            "power_plan": {
                "power_plan_id": "startup-validation-not-applicable",
                "status": "NOT_APPLICABLE_STARTUP_VALIDATION",
            },
        },
        "evaluation_outcome_access": False,
        "startup_validation_contract": {
            "research_progress_claim_allowed": False,
            "completion_claim_allowed": False,
            "pre_registration_claim_allowed": False,
            "outcome_access_allowed": False,
            "science_trial_appends": 0,
            "target_kind": "RUNTIME_CANARY_EVENT",
        },
    }
    _write_json(pin_path, pin)
    _write_text(
        input_path,
        "# SCIENCE_STARTUP_VALIDATION\n\n"
        "Read-only runtime audit. Verify that the reusable worker/tool chain executes "
        "under XINAO_SCIENCE_PROTOCOL_ACTIVE. Do not create a scientific hypothesis, "
        "inspect evaluation outcomes, modify files, or claim research progress.\n",
    )
    return {
        "episode_id": episode_id,
        "protocol_pin_path": pin_path,
        "protocol_pin_sha256": _sha256(pin_path),
        "world_path": world_path,
        "exposure_path": exposure_path,
        "ledger_path": ledger_path,
        "input_path": input_path,
        "output_root": science_episode_world_root(episode_id, _sha256(pin_path)),
    }


def _science_initial(
    materials: dict[str, Any],
    *,
    code_git_sha: str,
    model: str,
) -> dict[str, Any]:
    return {
        "episode_id": materials["episode_id"],
        "protocol_pin_ref": _host_to_container(materials["protocol_pin_path"]),
        "protocol_pin_sha256": materials["protocol_pin_sha256"],
        "mode": "SCIENCE_STARTUP_VALIDATION",
        "start_paused": True,
        "code_git_sha": code_git_sha,
        "model": model,
    }


async def _active_known_workflows(client: Client) -> list[dict[str, str]]:
    active: list[dict[str, str]] = []
    async for execution in client.list_workflows('ExecutionStatus = "Running"'):
        if (
            execution.status == WorkflowExecutionStatus.RUNNING
            and execution.task_queue in KNOWN_QUEUES
        ):
            active.append(
                {
                    "workflow_id": execution.id,
                    "run_id": execution.run_id,
                    "workflow_type": execution.workflow_type,
                    "task_queue": execution.task_queue,
                }
            )
    return sorted(active, key=lambda item: (item["workflow_id"], item["run_id"]))


async def _mainline_queue_snapshot(client: Client) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, queue_type in (
        ("workflow", TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
        ("activity", TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY),
    ):
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=client.namespace,
                task_queue=TaskQueue(name=TASK_QUEUE),
                task_queue_type=queue_type,
                report_stats=True,
                report_pollers=True,
            )
        )
        result[name] = {
            "poller_identities": [poller.identity for poller in response.pollers],
            "backlog": (
                int(response.task_queue_status.backlog_count_hint or 0)
                if response.HasField("task_queue_status")
                else 0
            ),
        }
    return result


async def _wait_phase(handle: Any, phase: str, timeout: float = 90.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    last: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        try:
            last = await handle.query(XinaoScienceEpisodeWorkflowV1.state)
        except Exception:
            await asyncio.sleep(0.25)
            continue
        if last.get("phase") == phase:
            return last
        await asyncio.sleep(0.25)
    raise TimeoutError(f"workflow did not reach phase {phase}: {last}")


def _event_names(history: Any) -> list[str]:
    return [EventType.Name(event.event_type) for event in history.events]


def _activity_types(history: Any) -> list[str]:
    names: list[str] = []
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            names.append(event.activity_task_scheduled_event_attributes.activity_type.name)
    return names


async def _wait_container_healthy(
    container: str,
    *,
    expected_static_identity: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    last: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        last = docker_identity(container)
        if _static_identity(last) != expected_static_identity:
            raise RuntimeError("worker identity or mount topology drifted while waiting for health")
        if last.get("status") == "running" and last.get("health") == "healthy":
            return last
        await asyncio.sleep(2)
    raise TimeoutError(f"worker did not become healthy before timeout: {last}")


async def _cancel_and_verify_terminal(
    handle: Any,
    workflow_id: str,
    *,
    rpc_timeout: float = RPC_TIMEOUT_SECONDS,
) -> Any:
    """Bound every cleanup RPC and prove the exact workflow is terminal."""

    description = await asyncio.wait_for(handle.describe(), timeout=rpc_timeout)
    if description.status == WorkflowExecutionStatus.RUNNING:
        await asyncio.wait_for(handle.cancel(), timeout=rpc_timeout)
        try:
            await asyncio.wait_for(handle.result(), timeout=rpc_timeout)
        except Exception:
            pass
    terminal = await asyncio.wait_for(handle.describe(), timeout=rpc_timeout)
    if terminal.status == WorkflowExecutionStatus.RUNNING:
        raise RuntimeError(f"workflow did not reach terminal state: {workflow_id}")
    return terminal


def _failure_chain(
    exc: BaseException,
    *,
    max_depth: int = 16,
) -> dict[str, Any]:
    """Expose bounded Temporal failure causes and their structured identities."""

    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    entries: list[dict[str, Any]] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    cycle_detected = False
    depth_limited = False
    for depth in range(max_depth):
        if current is None:
            break
        if id(current) in seen:
            cycle_detected = True
            break
        seen.add(id(current))
        entry: dict[str, Any] = {
            "depth": depth,
            "exception_type": type(current).__name__,
            "message": str(current),
        }
        if isinstance(current, ApplicationError):
            entry["application_error_type"] = current.type
            entry["non_retryable"] = current.non_retryable
        if isinstance(current, ActivityError):
            entry["activity_type"] = current.activity_type
            entry["activity_id"] = current.activity_id
            entry["retry_state"] = str(current.retry_state)
        entries.append(entry)
        nested = getattr(current, "cause", None)
        if not isinstance(nested, BaseException):
            nested = current.__cause__
        current = nested if isinstance(nested, BaseException) else None
    else:
        depth_limited = current is not None
    messages = [str(entry["message"]) for entry in entries if entry["message"]]
    return {
        "entries": entries,
        "message_text": " | caused by: ".join(messages),
        "cycle_detected": cycle_detected,
        "depth_limited": depth_limited,
    }


async def _expected_failure(
    client: Client,
    *,
    workflow: Any,
    initial: dict[str, Any],
    workflow_id: str,
    expected_text: str,
    forbidden_activity_types: tuple[str, ...] = (),
    timeout: float = 90,
) -> dict[str, Any]:
    _ACTIVE_WORKFLOW_IDS.add(workflow_id)
    handle = None
    error = ""
    failure_chain: dict[str, Any] = {}
    try:
        handle = await client.start_workflow(
            workflow,
            initial,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
        try:
            await asyncio.wait_for(handle.result(), timeout=timeout)
        except WorkflowFailureError as exc:
            failure_chain = _failure_chain(exc)
            error = str(failure_chain["message_text"])
        else:
            raise AssertionError(f"negative scenario unexpectedly succeeded: {workflow_id}")
    finally:
        try:
            if handle is not None:
                await _cancel_and_verify_terminal(handle, workflow_id)
        finally:
            _ACTIVE_WORKFLOW_IDS.discard(workflow_id)
    if handle is None:
        raise AssertionError(f"negative workflow was not started: {workflow_id}")
    history = await asyncio.wait_for(
        handle.fetch_history(),
        timeout=RPC_TIMEOUT_SECONDS,
    )
    names = _event_names(history)
    activity_types = _activity_types(history)
    expected_root_cause_found = expected_text in error
    child_absent = "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in names
    forbidden_activities_absent = all(
        name not in activity_types for name in forbidden_activity_types
    )
    if not expected_root_cause_found:
        raise AssertionError(
            "negative scenario did not expose its expected root cause: "
            f"{workflow_id}: expected={expected_text!r}; error={error}"
        )
    if not child_absent or not forbidden_activities_absent:
        raise AssertionError(
            "negative scenario crossed its denied execution boundary: "
            f"{workflow_id}: error={error}; activities={activity_types}"
        )
    return {
        "workflow_id": workflow_id,
        "error": error[:1000],
        "event_count": len(names),
        "activity_types": activity_types,
        "failure_chain": failure_chain,
        "expected_root_cause_found": expected_root_cause_found,
        "child_scheduled": not child_absent,
        "forbidden_activities_absent": forbidden_activities_absent,
        "ok": True,
    }


def _verify_runtime_artifact(
    value: str,
    expected_sha256: str,
    *,
    expected_root: Path,
) -> dict[str, str]:
    path = _container_to_host(value)
    resolved = path.resolve()
    try:
        resolved.relative_to(expected_root.resolve())
    except ValueError as exc:
        raise AssertionError(f"runtime artifact escaped the validation root: {value}") from exc
    if not resolved.is_file():
        raise AssertionError(f"runtime artifact is missing: {resolved}")
    observed = _sha256(resolved)
    if observed != expected_sha256:
        raise AssertionError(f"runtime artifact hash mismatch: {resolved}")
    return {"ref": str(resolved), "sha256": observed}


def _verify_positive_worker_receipt(
    result: dict[str, Any],
    *,
    materials: dict[str, Any],
    expected_model: str,
) -> dict[str, Any]:
    worker = dict(result.get("science_startup_worker_receipt") or {})
    usage = dict(worker.get("usage") or {})
    expected_root = Path(materials["output_root"]).resolve()
    run_root = _container_to_host(str(worker.get("run_root") or "")).resolve()
    if run_root != expected_root:
        raise AssertionError("startup worker receipt is not bound to the canonical world root")
    usage_ok = (
        int(usage.get("invocation_count") or 0) >= 1
        and int(usage.get("total_tokens") or 0) > 0
        and int(usage.get("accepted_tokens") or 0) > 0
        and int(usage.get("total_tokens") or 0)
        == sum(
            int(usage.get(name) or 0)
            for name in ("accepted_tokens", "cancelled_tokens", "failed_tokens")
        )
    )
    checks = dict(worker.get("worker_checks") or {})
    required_checks = {
        "fanin_ok",
        "provider_exact",
        "model_identity_ok",
        "provider_invoked",
        "model_invoked",
        "one_accepted_invocation",
        "terminal_completed",
        "cross_seam_receipt",
        "sandboxed_no_tools",
        "capabilities_disabled",
        "bound_output",
        "non_grok_invocations_zero",
    }
    identity_ok = (
        worker.get("status") == "WORKER_TERMINAL_ACCEPTED"
        and worker.get("selected_provider") == PROVIDER_ID
        and worker.get("requested_model") == expected_model
        and worker.get("observed_model") == expected_docker_grok_backend_models(expected_model)[0]
        and worker.get("model_identity_ok") is True
        and worker.get("sandbox_profile") == READ_ONLY_SANDBOX_PROFILE
        and worker.get("permission_mode") == READ_ONLY_PERMISSION_MODE
        and worker.get("security_cli_args")
        == [
            "--sandbox",
            READ_ONLY_SANDBOX_PROFILE,
            "--permission-mode",
            READ_ONLY_PERMISSION_MODE,
            "--tools",
            "",
        ]
        and worker.get("terminal_state") == "completed"
        and str(worker.get("stop_reason") or "").casefold() == "endturn"
        and required_checks.issubset(checks)
        and all(checks[name] is True for name in required_checks)
        and usage_ok
    )
    science_boundary_ok = (
        int(worker.get("science_trial_appends") or 0) == 0
        and worker.get("outcome_accessed") is False
        and worker.get("research_progress_claim_allowed") is False
        and worker.get("completion_claim_allowed") is False
        and worker.get("legacy_parent_scope_consumed") is False
    )
    if not identity_ok or not science_boundary_ok:
        raise AssertionError("startup worker identity, usage, or science boundary is incomplete")
    artifacts = {
        name: _verify_runtime_artifact(
            str(worker.get(ref_name) or ""),
            str(worker.get(hash_name) or ""),
            expected_root=expected_root,
        )
        for name, ref_name, hash_name in (
            ("receipt", "receipt_ref", "receipt_sha256"),
            ("checkpoint", "checkpoint_ref", "checkpoint_sha256"),
            ("output", "output_ref", "output_sha256"),
            ("logical_contract", "logical_contract_ref", "logical_contract_sha256"),
            ("attempt_receipt", "attempt_receipt_ref", "attempt_receipt_sha256"),
            ("fanin_manifest", "fanin_manifest_ref", "fanin_manifest_sha256"),
        )
    }
    return {
        "identity_ok": True,
        "usage_ok": True,
        "science_boundary_ok": True,
        "usage": usage,
        "artifacts": artifacts,
    }


def _offline_legacy_synthetic_contract_replay() -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        (
            "tests/test_xinao_research_campaign_admission.py::"
            "test_pre_cutover_history_replays_without_admission_activity"
        ),
        (
            "tests/test_xinao_research_campaign_admission.py::"
            "test_pre_retirement_domain_admission_history_still_replays"
        ),
    ]
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        cwd=REPO,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=180,
        creationflags=WINDOWLESS,
    )
    return {
        "ok": completed.returncode == 0,
        "evidence_kind": "synthetic_contract_replay",
        "production_history_claim_allowed": False,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


async def _freeze_retained_legacy_histories(
    client: Client,
    *,
    exclude_workflow_prefix: str,
    started_before: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    async def collect() -> list[Any]:
        return [
            execution
            async for execution in client.list_workflows(
                'WorkflowType = "XinaoResearchCampaignWorkflow"'
            )
        ]

    executions = await asyncio.wait_for(collect(), timeout=RPC_TIMEOUT_SECONDS)
    retained: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for execution in executions:
        if execution.id.startswith(exclude_workflow_prefix):
            rejected.append({"workflow_id": execution.id, "reason": "current_validation_prefix"})
            continue
        handle = client.get_workflow_handle(execution.id, run_id=execution.run_id)
        history = await asyncio.wait_for(
            handle.fetch_history(),
            timeout=RPC_TIMEOUT_SECONDS,
        )
        if not history.events:
            rejected.append({"workflow_id": execution.id, "reason": "empty_history"})
            continue
        started_at = history.events[0].event_time.ToDatetime(tzinfo=UTC)
        names = _event_names(history)
        activity_types = _activity_types(history)
        legacy_shape = (
            "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" in names
            or "xinao_verify_domain_research_admission" in activity_types
        )
        if started_at >= started_before:
            rejected.append({"workflow_id": execution.id, "reason": "not_pre_cutover"})
            continue
        if not legacy_shape:
            rejected.append({"workflow_id": execution.id, "reason": "not_legacy_execution_shape"})
            continue
        retained.append(
            {
                "workflow_id": execution.id,
                "run_id": execution.run_id,
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "event_count": len(history.events),
                "history_sha256": hashlib.sha256(history.to_json().encode("utf-8")).hexdigest(),
                "event_names": sorted(names),
                "activity_types": activity_types,
                "_history": history,
            }
        )
    inventory = {
        "status": "FROZEN_BEFORE_CURRENT_VALIDATION",
        "frozen_at": _now(),
        "started_before": started_before.isoformat().replace("+00:00", "Z"),
        "queried_execution_count": len(executions),
        "retained_history_count": len(retained),
        "retained": [
            {key: value for key, value in item.items() if key != "_history"} for item in retained
        ],
        "rejected": rejected,
    }
    return retained, inventory


async def _retained_legacy_history_replay(
    retained: list[dict[str, Any]],
) -> dict[str, Any]:
    replayed: list[dict[str, Any]] = []
    for record in retained:
        replay = await asyncio.wait_for(
            Replayer(workflows=[XinaoResearchCampaignWorkflow]).replay_workflow(
                record["_history"],
                raise_on_replay_failure=False,
            ),
            timeout=120,
        )
        replayed.append(
            {
                "workflow_id": record["workflow_id"],
                "run_id": record["run_id"],
                "ok": replay.replay_failure is None,
                "failure": (None if replay.replay_failure is None else repr(replay.replay_failure)),
                "event_count": record["event_count"],
                "history_sha256": record["history_sha256"],
            }
        )
    has_retained_history = bool(replayed)
    return {
        "ok": all(item["ok"] for item in replayed),
        "status": (
            "VERIFIED"
            if replayed and all(item["ok"] for item in replayed)
            else "FAILED"
            if replayed
            else "NOT_APPLICABLE_NO_RETAINED_PRE_CUTOVER_HISTORY"
        ),
        "retained_history_count": len(replayed),
        "not_applicable": not has_retained_history,
        "production_history_claim_allowed": has_retained_history
        and all(item["ok"] for item in replayed),
        "histories": replayed,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    args.run_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output or args.run_dir / "science_startup_validation.report.json"
    parent = load_science_active_parent()
    active_parent_sha256 = str(parent["active_parent"]["sha256"])
    code_git_sha = str(args.code_git_sha or "").lower()
    if not _COMMIT_RE.fullmatch(code_git_sha):
        raise RuntimeError("--code-git-sha must be one exact 40-character commit")
    source_release = _expected_source_release(
        release_dir=args.release_dir,
        manifest_path=args.release_manifest,
        git_repo=args.git_repo,
        code_git_sha=code_git_sha,
    )
    materials = _materialize_validation_episode(
        args.run_dir,
        active_parent_sha256=active_parent_sha256,
        background_contract_sha256=str(parent["background_contract"]["sha256"]),
    )
    workflow_id = f"xinao-{materials['episode_id']}"
    _ACTIVE_WORKFLOW_IDS.add(workflow_id)
    initial = _science_initial(
        materials,
        code_git_sha=code_git_sha,
        model=args.model,
    )
    client = await Client.connect(args.address, namespace=args.namespace)
    pre_active = await _active_known_workflows(client)
    if pre_active:
        raise RuntimeError(
            "bounded restart denied because another canonical workflow is running: "
            + json.dumps(pre_active, ensure_ascii=False)
        )
    pre_container = docker_identity(args.container)
    if pre_container.get("status") != "running" or pre_container.get("health") != "healthy":
        raise RuntimeError("canonical worker is not running and healthy before validation")
    release_mounts_before = _verify_container_release_mounts(
        pre_container,
        release_dir=args.release_dir,
    )
    container_created_at = datetime.fromisoformat(
        str(pre_container.get("created") or "").replace("Z", "+00:00")
    ).astimezone(UTC)
    retained_histories, retained_history_inventory = await _freeze_retained_legacy_histories(
        client,
        exclude_workflow_prefix=workflow_id,
        started_before=container_created_at,
    )
    daemon_before_path = RUNTIME / "state" / "integrated_bus_worker_daemon" / "latest.json"
    daemon_before = json.loads(daemon_before_path.read_text(encoding="utf-8"))
    daemon_release_before = _verify_daemon_source_release(
        daemon_before,
        expected=source_release,
    )
    handle = await client.start_workflow(
        XinaoScienceEpisodeWorkflowV1.run,
        initial,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    description = await asyncio.wait_for(
        handle.describe(),
        timeout=RPC_TIMEOUT_SECONDS,
    )
    run_id = description.run_id
    paused_before = await _wait_phase(handle, "PAUSED_AFTER_ADMISSION")
    active_during = await _active_known_workflows(client)
    if {(item["workflow_id"], item["run_id"]) for item in active_during} != {(workflow_id, run_id)}:
        raise RuntimeError("canonical restart blast radius changed after episode start")

    restart_started = datetime.now(UTC)
    restart = _docker_restart(str(pre_container["id"]))
    if restart["exit_code"] != 0:
        current = None
        try:
            current = docker_identity(args.container)
        except Exception:
            pass
        rollback = _rollback_start_if_exact_stopped(
            pre=pre_container,
            current=current,
        )
        raise RuntimeError(f"bounded worker restart failed: {restart}; rollback={rollback}")
    post_container = docker_identity(args.container)
    if _static_identity(post_container) != _static_identity(pre_container):
        raise RuntimeError("worker identity or mount topology drifted across restart")
    if (
        post_container.get("status") != "running"
        or post_container.get("pid") == pre_container.get("pid")
        or post_container.get("started_at") == pre_container.get("started_at")
    ):
        raise RuntimeError("worker did not establish a running new process generation")
    daemon_after, integrated_queues = await _wait_daemon_and_queues(
        client,
        previous_run_id=str(daemon_before.get("run_id") or ""),
        started_after=restart_started,
        timeout=120,
    )
    post_container = await _wait_container_healthy(
        args.container,
        expected_static_identity=_static_identity(pre_container),
        timeout=180,
    )
    restart_completed = datetime.now(UTC)
    release_mounts_after = _verify_container_release_mounts(
        post_container,
        release_dir=args.release_dir,
    )
    daemon_release_after = _verify_daemon_source_release(
        daemon_after,
        expected=source_release,
    )
    if (
        daemon_after.get("workflow_roles", {}).get(SCIENCE_EPISODE_WORKFLOW_NAME)
        != "CURRENT_SCIENCE_ENTRY"
        or daemon_after.get("workflow_roles", {}).get("XinaoResearchCampaignWorkflow")
        != "LEGACY_REPLAY"
    ):
        raise RuntimeError("restarted worker did not register current/legacy workflow roles")
    mainline_queue = await _mainline_queue_snapshot(client)
    if any(not mainline_queue[kind]["poller_identities"] for kind in ("workflow", "activity")):
        raise RuntimeError("restarted worker is not polling the science task queue")
    paused_after = await _wait_phase(handle, "PAUSED_AFTER_ADMISSION", timeout=120)
    await handle.signal(XinaoScienceEpisodeWorkflowV1.control, "RESUME")
    result = await asyncio.wait_for(handle.result(), timeout=args.timeout)
    _ACTIVE_WORKFLOW_IDS.discard(workflow_id)
    history = await asyncio.wait_for(
        handle.fetch_history(),
        timeout=RPC_TIMEOUT_SECONDS,
    )
    names = _event_names(history)
    activity_types = _activity_types(history)
    expected_events = {
        "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED",
        "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
        "EVENT_TYPE_ACTIVITY_TASK_COMPLETED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    }
    expected_activities = {
        "xinao_verify_science_episode_admission_v1",
        "xinao_verify_science_instruments_v1",
        "xinao_run_science_startup_worker_v1",
    }
    positive_ok = (
        result.get("status") == "STARTUP_VALIDATED"
        and result.get("child_scheduled") is False
        and result.get("worker_activity_scheduled") is True
        and result.get("outcome_accessed") is False
        and result.get("research_progress_claim_allowed") is False
        and result.get("completion_claim_allowed") is False
        and result.get("pre_registration_claim_allowed") is False
        and int(result.get("science_trial_appends") or 0) == 0
        and result.get("old_g6_consumed") is False
        and result.get("science_instrument_validation", {}).get("ok") is True
        and expected_events.issubset(names)
        and expected_activities.issubset(activity_types)
        and "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in names
    )
    if not positive_ok:
        raise AssertionError("positive science startup validation result is incomplete")
    worker_acceptance = _verify_positive_worker_receipt(
        result,
        materials=materials,
        expected_model=args.model,
    )
    replay = await Replayer(workflows=[XinaoScienceEpisodeWorkflowV1]).replay_workflow(
        history, raise_on_replay_failure=False
    )
    current_replay = {
        "ok": replay.replay_failure is None,
        "failure": None if replay.replay_failure is None else repr(replay.replay_failure),
        "event_count": len(history.events),
        "history_sha256": hashlib.sha256(history.to_json().encode("utf-8")).hexdigest(),
    }
    if not current_replay["ok"]:
        raise AssertionError("current science workflow history replay failed")

    bad_world_payload = deepcopy(json.loads(materials["world_path"].read_text(encoding="utf-8")))
    bad_world_payload["bindings"]["dataset"]["sha256"] = "0" * 64
    bad_world_path = materials["world_path"].with_name("world_measurement_bundle.bad-binding.json")
    _write_json(bad_world_path, bad_world_payload)
    bad_pin = deepcopy(json.loads(materials["protocol_pin_path"].read_text(encoding="utf-8")))
    bad_pin["world_measurement_bundle"] = {
        "ref": str(bad_world_path),
        "sha256": _sha256(bad_world_path),
    }
    bad_pin_path = materials["protocol_pin_path"].with_name("protocol_pin.bad-world-binding.json")
    _write_json(bad_pin_path, bad_pin)
    bad_initial = deepcopy(initial)
    bad_initial["start_paused"] = False
    bad_initial["protocol_pin_ref"] = _host_to_container(bad_pin_path)
    bad_initial["protocol_pin_sha256"] = _sha256(bad_pin_path)
    bad_world = await _expected_failure(
        client,
        workflow=XinaoScienceEpisodeWorkflowV1.run,
        initial=bad_initial,
        workflow_id=f"{workflow_id}-bad-world",
        expected_text="WorldMeasurementBundle dataset binding drifted",
        forbidden_activity_types=(
            "xinao_verify_science_instruments_v1",
            "xinao_run_science_startup_worker_v1",
        ),
    )
    wrong_mode = deepcopy(initial)
    wrong_mode["start_paused"] = False
    wrong_mode["mode"] = "RESEARCH"
    wrong_mode_case = await _expected_failure(
        client,
        workflow=XinaoScienceEpisodeWorkflowV1.run,
        initial=wrong_mode,
        workflow_id=f"{workflow_id}-startup-as-research",
        expected_text="research mode rejects startup-only claim intent",
        forbidden_activity_types=(
            "xinao_verify_science_instruments_v1",
            "xinao_run_science_startup_worker_v1",
        ),
    )
    forged_authority = deepcopy(initial)
    forged_authority["start_paused"] = False
    forged_authority["active_parent_projection_ref"] = "/evidence/forged/active_parent.current.json"
    forged_authority_case = await _expected_failure(
        client,
        workflow=XinaoScienceEpisodeWorkflowV1.run,
        initial=forged_authority,
        workflow_id=f"{workflow_id}-forged-authority",
        expected_text="science authority and episode output roots are derived",
        forbidden_activity_types=(
            "xinao_verify_science_episode_admission_v1",
            "xinao_verify_science_instruments_v1",
            "xinao_run_science_startup_worker_v1",
        ),
    )
    legacy_case = await _expected_failure(
        client,
        workflow=XinaoResearchCampaignWorkflow.run,
        initial={
            "campaign_id": f"{materials['episode_id']}-legacy",
            "bus_state": {"input_path": _host_to_container(materials["input_path"])},
        },
        workflow_id=f"{workflow_id}-legacy-fresh",
        expected_text="retired for fresh starts",
        forbidden_activity_types=(
            "xinao_verify_science_episode_admission_v1",
            "xinao_verify_science_instruments_v1",
            "xinao_run_science_startup_worker_v1",
        ),
    )
    retained_legacy_replay = await _retained_legacy_history_replay(retained_histories)
    if not retained_legacy_replay["ok"]:
        raise AssertionError("a retained legacy Temporal history no longer replays")
    legacy_synthetic_replay = _offline_legacy_synthetic_contract_replay()
    if not legacy_synthetic_replay["ok"]:
        raise AssertionError("legacy synthetic compatibility contracts no longer replay")
    post_active = await _active_known_workflows(client)
    if post_active:
        raise AssertionError(f"validation left running workflows: {post_active}")
    source_release_after = _expected_source_release(
        release_dir=args.release_dir,
        manifest_path=args.release_manifest,
        git_repo=args.git_repo,
        code_git_sha=code_git_sha,
    )
    if source_release_after != source_release:
        raise AssertionError("source release identity drifted during startup validation")

    report = {
        "schema_version": "xinao.science_startup_validation.v1",
        "status": "VERIFIED",
        "generated_at": _now(),
        "validation_only": True,
        "research_progress_claim_allowed": False,
        "completion_claim_allowed": False,
        "pre_registration_claim_allowed": False,
        "science_trial_appends": 0,
        "evaluation_outcome_accessed": False,
        "active_parent_sha256": active_parent_sha256,
        "code_git_sha": code_git_sha,
        "source_release": {
            **source_release,
            "container_mounts_before": release_mounts_before,
            "container_mounts_after": release_mounts_after,
            "daemon_before": daemon_release_before,
            "daemon_after": daemon_release_after,
            "host_verification_after": source_release_after,
        },
        "runtime_canary_event": {
            "target_kind": "RUNTIME_CANARY_EVENT",
            "pre_registration_claim_allowed": False,
            "restart_started_at": restart_started.isoformat().replace("+00:00", "Z"),
            "restart_completed_at": restart_completed.isoformat().replace("+00:00", "Z"),
        },
        "workflow": {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "type": SCIENCE_EPISODE_WORKFLOW_NAME,
            "paused_before_restart": paused_before,
            "paused_after_restart": paused_after,
            "result": result,
            "history_event_count": len(names),
            "activity_types": activity_types,
            "worker_acceptance": worker_acceptance,
        },
        "worker_restart": {
            "pre": {
                "id": pre_container["id"],
                "pid": pre_container["pid"],
                "started_at": pre_container["started_at"],
                "health": pre_container["health"],
            },
            "action": restart,
            "post": {
                "id": post_container["id"],
                "pid": post_container["pid"],
                "started_at": post_container["started_at"],
                "health": post_container["health"],
            },
            "static_identity_preserved": True,
            "daemon_run_before": daemon_before.get("run_id"),
            "daemon_run_after": daemon_after.get("run_id"),
            "integrated_queues": integrated_queues,
            "science_queue": mainline_queue,
        },
        "replay": {
            "current_science_history": current_replay,
            "retained_legacy_history_inventory": retained_history_inventory,
            "retained_legacy_temporal_histories": retained_legacy_replay,
            "legacy_synthetic_contract_replay": legacy_synthetic_replay,
        },
        "negative_cases": {
            "world_binding_hash_drift": bad_world,
            "startup_pin_as_research": wrong_mode_case,
            "caller_forged_authority": forged_authority_case,
            "legacy_campaign_fresh_start": legacy_case,
        },
        "cleanup": {
            "running_known_workflows_after": post_active,
            "temporary_episode_is_research_progress": False,
            "evidence_retained_for_migration_acceptance": True,
        },
    }
    _write_json(report_path, report)
    report["report_ref"] = str(report_path)
    report["report_sha256"] = _sha256(report_path)
    _ACTIVE_WORKFLOW_IDS.clear()
    return report


async def _cancel_exact_if_running(
    address: str,
    namespace: str,
    workflow_ids: set[str],
) -> None:
    if not workflow_ids:
        return
    client = await asyncio.wait_for(
        Client.connect(address, namespace=namespace),
        timeout=RPC_TIMEOUT_SECONDS,
    )
    errors: list[str] = []
    for workflow_id in sorted(workflow_ids):
        try:
            handle = client.get_workflow_handle(workflow_id)
            await _cancel_and_verify_terminal(handle, workflow_id)
        except Exception as exc:
            errors.append(f"{workflow_id}: {type(exc).__name__}: {exc}")
        finally:
            _ACTIVE_WORKFLOW_IDS.discard(workflow_id)
    if errors:
        raise RuntimeError("bounded workflow cleanup failed: " + "; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--container", default=CONTAINER_NAME)
    parser.add_argument("--model", default="grok-4.5")
    parser.add_argument("--code-git-sha", required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--git-repo", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        try:
            asyncio.run(
                _cancel_exact_if_running(
                    args.address,
                    args.namespace,
                    set(_ACTIVE_WORKFLOW_IDS),
                )
            )
        except Exception:
            pass
        print(
            json.dumps(
                {
                    "schema_version": "xinao.science_startup_validation.v1",
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "completion_claim_allowed": False,
                    "research_progress_claim_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
