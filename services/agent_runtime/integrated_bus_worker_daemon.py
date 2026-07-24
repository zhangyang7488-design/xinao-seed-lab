"""Long-lived Temporal worker daemon for the canonical integrated-bus queues."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_graph import (
    GRAPH_ID,
    integrated_temporal_graphs,
    make_integrated_graph,
)
from services.agent_runtime.integrated_bus_workflow_registry import (
    collect_worker_bindings,
    registry_summary,
)
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json
from services.agent_runtime.thin_glue_sunset_registry import summarize_sunset_registry

SCHEMA_VERSION = "xinao.integrated_bus_worker_daemon.v2"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_WORKER_DAEMON_READY"
DEFAULT_POLLING_START_TIMEOUT_SECONDS = 30.0
SOURCE_RELEASE_SCHEMA_VERSION = "xinao.s_runtime_source_release.v1"
SOURCE_RELEASE_CRITICAL_FILES = (
    "services/agent_runtime/integrated_bus_worker_daemon.py",
    "services/agent_runtime/integrated_bus_workflow_registry.py",
    "services/agent_runtime/xinao_science_episode_workflow.py",
    "services/agent_runtime/grok_build_docker_worker.py",
    "xinao_discovery/src/xinao/science/episode_admission.py",
    "xinao_discovery/src/xinao/world/builder.py",
    "scripts/verify_science_startup_validation.py",
    "pyproject.toml",
    "uv.lock",
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _load_params() -> dict[str, Any]:
    from services.agent_runtime.integrated_bus_graph import DEFAULT_PARAMS

    if not DEFAULT_PARAMS.is_file():
        return {}
    return json.loads(DEFAULT_PARAMS.read_text(encoding="utf-8"))


def _process_start_ticks(process_id: int) -> str:
    """Return Linux's immutable start generation for one process."""

    raw = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
    command_end = raw.rfind(")")
    fields_after_command = raw[command_end + 2 :].split() if command_end >= 0 else []
    if len(fields_after_command) <= 19:
        raise RuntimeError(f"cannot read process start generation for pid={process_id}")
    # /proc/<pid>/stat field 22; fields_after_command starts at field 3.
    return fields_after_command[19]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_release_identity(
    *,
    runtime_root: Path,
    app_root: Path,
) -> dict[str, Any]:
    """Verify the mounted worker bytes against one content-addressed release."""

    commit = os.environ.get("XINAO_S_RUNTIME_RELEASE_COMMIT", "").strip().lower()
    expected_manifest_sha256 = (
        os.environ.get("XINAO_S_RUNTIME_RELEASE_MANIFEST_SHA256", "").strip().lower()
    )
    if not _COMMIT_RE.fullmatch(commit):
        raise RuntimeError("XINAO_S_RUNTIME_RELEASE_COMMIT is missing or invalid")
    if not _HASH_RE.fullmatch(expected_manifest_sha256):
        raise RuntimeError("XINAO_S_RUNTIME_RELEASE_MANIFEST_SHA256 is missing or invalid")
    manifest_path = (
        runtime_root / "state" / "s_runtime_releases" / f"{commit}.release-manifest.json"
    )
    if not manifest_path.is_file():
        raise RuntimeError(f"S runtime release manifest is missing: {manifest_path}")
    observed_manifest_sha256 = _sha256(manifest_path)
    if observed_manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError("S runtime release manifest hash drifted")
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != SOURCE_RELEASE_SCHEMA_VERSION
        or manifest.get("commit") != commit
    ):
        raise RuntimeError("S runtime release manifest identity is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise RuntimeError("S runtime release manifest has no file identities")
    critical_files: dict[str, str] = {}
    for relative in SOURCE_RELEASE_CRITICAL_FILES:
        binding = files.get(relative)
        if not isinstance(binding, dict):
            raise RuntimeError(f"S runtime release omitted critical file: {relative}")
        expected_sha256 = str(binding.get("sha256") or "").lower()
        if not _HASH_RE.fullmatch(expected_sha256):
            raise RuntimeError(f"S runtime critical file hash is invalid: {relative}")
        mounted_path = app_root.joinpath(*relative.split("/"))
        if not mounted_path.is_file() or _sha256(mounted_path) != expected_sha256:
            raise RuntimeError(f"mounted S runtime critical file drifted: {relative}")
        critical_files[relative] = expected_sha256
    return {
        "status": "VERIFIED",
        "commit": commit,
        "manifest_ref": str(manifest_path),
        "manifest_sha256": observed_manifest_sha256,
        "critical_files": critical_files,
    }


def readiness_marker_issues(
    evidence: dict[str, Any],
    *,
    expected_container_id: str,
    expected_process_id: int,
    expected_process_start_ticks: str,
    expected_source_release: dict[str, Any] | None = None,
) -> list[str]:
    """Validate that a polling marker belongs to the current daemon process."""

    issues: list[str] = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        issues.append("schema_version_mismatch")
    if evidence.get("sentinel") != SENTINEL:
        issues.append("sentinel_mismatch")
    if evidence.get("status") != "polling":
        issues.append("status_not_polling")
    if evidence.get("readiness_confirmed") is not True:
        issues.append("readiness_not_confirmed")
    if evidence.get("container_id") != expected_container_id:
        issues.append("container_generation_mismatch")
    if evidence.get("process_id") != expected_process_id:
        issues.append("process_id_mismatch")
    if evidence.get("process_start_ticks") != expected_process_start_ticks:
        issues.append("process_generation_mismatch")
    binding_count = evidence.get("binding_count")
    worker_context_count = evidence.get("worker_context_count")
    if not isinstance(binding_count, int) or binding_count <= 0:
        issues.append("binding_count_invalid")
    if worker_context_count != binding_count:
        issues.append("worker_context_count_mismatch")
    if evidence.get("all_workers_running") is not True:
        issues.append("workers_not_running")
    roles = evidence.get("workflow_roles")
    if not isinstance(roles, dict):
        issues.append("workflow_roles_missing")
    elif roles.get("XinaoScienceEpisodeWorkflowV1") != "CURRENT_SCIENCE_ENTRY":
        issues.append("current_science_workflow_role_missing")
    elif roles.get("XinaoResearchCampaignWorkflow") != "LEGACY_REPLAY":
        issues.append("legacy_campaign_workflow_role_missing")
    if (
        expected_source_release is not None
        and evidence.get("source_release") != expected_source_release
    ):
        issues.append("source_release_identity_mismatch")
    return issues


def check_readiness(
    *,
    runtime_root: Path,
    expected_process_id: int = 1,
) -> dict[str, Any]:
    """Fail closed on stale files, prior container generations, and pre-poll markers."""

    marker_path = runtime_root / "state" / "integrated_bus_worker_daemon" / "latest.json"
    evidence = _read_json(marker_path)
    issues: list[str] = []
    try:
        release = source_release_identity(
            runtime_root=runtime_root,
            app_root=Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT") or "/app"),
        )
    except (OSError, UnicodeError, RuntimeError) as exc:
        release = None
        issues.append(f"source_release_unavailable:{type(exc).__name__}")
    try:
        process_start_ticks = _process_start_ticks(expected_process_id)
    except (OSError, UnicodeError, RuntimeError) as exc:
        issues.append(f"process_generation_unavailable:{type(exc).__name__}")
    else:
        issues.extend(
            readiness_marker_issues(
                evidence,
                expected_container_id=socket.gethostname(),
                expected_process_id=expected_process_id,
                expected_process_start_ticks=process_start_ticks,
                expected_source_release=release,
            )
        )
    return {
        "schema_version": "xinao.integrated_bus_worker_readiness_check.v1",
        "ok": not issues,
        "issues": issues,
        "marker_path": str(marker_path),
        "completion_claim_allowed": False,
    }


async def _wait_for_workers_polling(
    workers: list[Any],
    *,
    timeout_seconds: float = DEFAULT_POLLING_START_TIMEOUT_SECONDS,
) -> None:
    """Wait until Temporal has started every configured worker poll loop."""

    if not workers:
        raise RuntimeError("no Temporal worker bindings were configured")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while not all(worker.is_running for worker in workers):
        if loop.time() >= deadline:
            raise TimeoutError("Temporal workers did not enter polling state before timeout")
        await asyncio.sleep(0.05)


async def run_integrated_bus_worker_daemon(
    *,
    address: str = "127.0.0.1:7233",
    runtime_root: Path = DEFAULT_RUNTIME,
) -> None:
    from temporalio.client import Client
    from temporalio.contrib.langgraph import LangGraphPlugin
    from temporalio.worker import Worker

    from services.agent_runtime.integrated_bus_runner import integrated_bus_workflow_runner

    bindings = collect_worker_bindings()
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S_%f")
    sunset = summarize_sunset_registry()
    reg = registry_summary()
    process_id = os.getpid()
    process_start_ticks = _process_start_ticks(process_id)
    release = source_release_identity(
        runtime_root=runtime_root,
        app_root=Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT") or "/app"),
    )
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "status": "starting",
        "run_id": run_id,
        "address": address,
        "container_id": socket.gethostname(),
        "process_id": process_id,
        "process_start_ticks": process_start_ticks,
        "graph_id": GRAPH_ID,
        "binding_count": len(bindings),
        "worker_context_count": 0,
        "all_workers_running": False,
        "readiness_confirmed": False,
        "task_queues": reg.get("task_queues", []),
        "workflows_registered": reg.get("workflows_registered", []),
        "workflow_roles": reg.get("workflow_roles", {}),
        "source_release": release,
        "activity_count": reg.get("activity_count", 0),
        "handroll_intact": False,
        "facade_hard_redirect": True,
        "sunset_registry_handroll_intact": sunset.get("handroll_intact") is False,
        "not_333_mainline": False,
        "completion_claim_allowed": False,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    state_dir = runtime_root / "state" / "integrated_bus_worker_daemon"
    state_dir.mkdir(parents=True, exist_ok=True)
    write_json(state_dir / "latest.json", evidence)
    client = await Client.connect(address)

    async with AsyncExitStack() as stack:
        workers: list[Any] = []
        for binding in bindings:
            plugins = []
            if binding.langgraph_plugin and binding.graph_id:
                graphs = (
                    integrated_temporal_graphs()
                    if binding.graph_id == GRAPH_ID
                    else {binding.graph_id: make_integrated_graph()}
                )
                plugins.append(LangGraphPlugin(graphs=graphs))
            worker = Worker(
                client,
                task_queue=binding.task_queue,
                workflows=binding.workflows,
                activities=binding.activities,
                plugins=plugins,
                activity_executor=ThreadPoolExecutor(max(4, len(binding.activities) or 1)),
                workflow_runner=integrated_bus_workflow_runner(),
            )
            await stack.enter_async_context(worker)
            workers.append(worker)
        await _wait_for_workers_polling(workers)
        evidence.update(
            {
                "status": "polling",
                "worker_context_count": len(workers),
                "all_workers_running": all(worker.is_running for worker in workers),
                "readiness_confirmed": True,
                "polling_started_at": datetime.now().astimezone().isoformat(),
                "generated_at": datetime.now().astimezone().isoformat(),
            }
        )
        write_json(state_dir / "latest.json", evidence)
        write_json(
            runtime_root / "readback" / f"integrated_bus_worker_daemon_{run_id}.json",
            evidence,
        )
        await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Integrated bus Temporal worker daemon (canonical queues only)"
    )
    # Prefer compose TEMPORAL_ADDRESS (pinyin stack: naijiu-shiwu:7233); host rescue falls back to localhost.
    default_address = (
        os.environ.get("TEMPORAL_ADDRESS") or os.environ.get("TEMPORAL_HOST") or "127.0.0.1:7233"
    )
    parser.add_argument("--address", default=default_address)
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument(
        "--check-readiness",
        action="store_true",
        help="validate that latest.json belongs to the current polling PID 1",
    )
    args = parser.parse_args(argv)
    if args.check_readiness:
        report = check_readiness(runtime_root=Path(args.runtime_root))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["ok"] else 1
    try:
        asyncio.run(
            run_integrated_bus_worker_daemon(
                address=args.address,
                runtime_root=Path(args.runtime_root),
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
