"""Long-lived Temporal worker daemon for the canonical integrated-bus queues."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
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

SCHEMA_VERSION = "xinao.integrated_bus_worker_daemon.v5"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_WORKER_DAEMON_READY"
DEFAULT_POLLING_START_TIMEOUT_SECONDS = 30.0
SOURCE_RELEASE_SCHEMA_VERSION = "xinao.s_runtime_source_release.v1"
GROK_EXPECTED_CAPABILITY_MASK = "00000000000000c0"
GROK_EXPECTED_NO_NEW_PRIVS = "1"
SOURCE_RELEASE_CRITICAL_FILES = (
    "services/agent_runtime/integrated_bus_worker_daemon.py",
    "services/agent_runtime/integrated_bus_workflow_registry.py",
    "services/agent_runtime/integrated_bus_graph.py",
    "services/agent_runtime/integrated_bus_parent_workflow.py",
    "services/agent_runtime/grok_build_docker_worker.py",
    "pyproject.toml",
    "uv.lock",
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _docker_native_grok_enabled() -> bool:
    return os.environ.get("XINAO_GROK_DOCKER_NATIVE", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _controlling_tty_available(path: str = "/dev/tty") -> bool:
    """Return whether this daemon process owns an openable controlling TTY."""

    flags = os.O_RDWR | getattr(os, "O_NOCTTY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    os.close(descriptor)
    return True


def _grok_session_store_state(sessions_root: Path) -> dict[str, Any]:
    """Prove that Grok's declared session store resolves and accepts a new directory."""

    try:
        resolved = sessions_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Grok session store is unavailable") from exc
    if not resolved.is_dir():
        raise RuntimeError("Grok session store is unavailable")
    try:
        with tempfile.TemporaryDirectory(prefix=".xinao-readiness-", dir=resolved):
            pass
    except OSError as exc:
        raise RuntimeError("Grok session store is not writable") from exc
    return {
        "ok": True,
        "declared_root": str(sessions_root),
        "resolved_root": str(resolved),
        "writable": True,
    }


def _parse_proc_status(raw: str) -> dict[str, str]:
    """Parse Linux proc status fields without depending on field ordering."""

    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def _grok_outer_privilege_state(path: Path = Path("/proc/self/status")) -> dict[str, Any]:
    """Verify the exact outer capability state required by the bwrap wrapper."""

    fields = _parse_proc_status(path.read_text(encoding="utf-8"))
    required_fields = ("CapEff", "CapPrm", "CapBnd", "NoNewPrivs", "Seccomp")
    missing = [field for field in required_fields if not fields.get(field)]
    if missing:
        raise RuntimeError(f"process privilege status omitted fields: {','.join(missing)}")
    observed = {
        "cap_eff": fields["CapEff"].split()[0].lower(),
        "cap_prm": fields["CapPrm"].split()[0].lower(),
        "cap_bnd": fields["CapBnd"].split()[0].lower(),
        "no_new_privs": fields["NoNewPrivs"].split()[0],
        "seccomp": fields["Seccomp"].split()[0],
    }
    return {
        "expected_capability_mask": GROK_EXPECTED_CAPABILITY_MASK,
        "expected_no_new_privs": GROK_EXPECTED_NO_NEW_PRIVS,
        **observed,
        "ok": (
            observed["cap_eff"] == GROK_EXPECTED_CAPABILITY_MASK
            and observed["cap_prm"] == GROK_EXPECTED_CAPABILITY_MASK
            and observed["cap_bnd"] == GROK_EXPECTED_CAPABILITY_MASK
            and observed["no_new_privs"] == GROK_EXPECTED_NO_NEW_PRIVS
        ),
    }


def _grok_bwrap_bootstrap_available(executable: str = "/usr/bin/bwrap") -> bool:
    """Probe the nested user/PID/network namespace boundary without Grok or network I/O."""

    try:
        completed = subprocess.run(
            [
                executable,
                "--unshare-user",
                "--unshare-pid",
                "--unshare-net",
                "--die-with-parent",
                "--ro-bind",
                "/",
                "/",
                "/bin/true",
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


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
    expected_grok_sandbox_tty_required: bool = False,
    expected_grok_outer_privilege_required: bool = False,
    expected_grok_outer_privilege_state: dict[str, Any] | None = None,
    expected_grok_bwrap_bootstrap_required: bool = False,
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
    if evidence.get("grok_sandbox_tty_required") is not expected_grok_sandbox_tty_required:
        issues.append("grok_sandbox_tty_requirement_mismatch")
    if (
        expected_grok_sandbox_tty_required
        and evidence.get("grok_sandbox_tty_available") is not True
    ):
        issues.append("grok_sandbox_tty_unavailable")
    if evidence.get("grok_outer_privilege_required") is not expected_grok_outer_privilege_required:
        issues.append("grok_outer_privilege_requirement_mismatch")
    outer_privilege = evidence.get("grok_outer_privilege")
    if expected_grok_outer_privilege_required:
        if not isinstance(outer_privilege, dict):
            issues.append("grok_outer_privilege_state_missing")
        elif (
            outer_privilege.get("ok") is not True
            or outer_privilege.get("expected_capability_mask") != GROK_EXPECTED_CAPABILITY_MASK
            or outer_privilege.get("expected_no_new_privs") != GROK_EXPECTED_NO_NEW_PRIVS
            or outer_privilege.get("cap_eff") != GROK_EXPECTED_CAPABILITY_MASK
            or outer_privilege.get("cap_prm") != GROK_EXPECTED_CAPABILITY_MASK
            or outer_privilege.get("cap_bnd") != GROK_EXPECTED_CAPABILITY_MASK
            or outer_privilege.get("no_new_privs") != GROK_EXPECTED_NO_NEW_PRIVS
            or not str(outer_privilege.get("seccomp") or "").isdigit()
        ):
            issues.append("grok_outer_privilege_state_invalid")
        if (
            expected_grok_outer_privilege_state is not None
            and outer_privilege != expected_grok_outer_privilege_state
        ):
            issues.append("grok_outer_privilege_state_mismatch")
    if evidence.get("grok_bwrap_bootstrap_required") is not expected_grok_bwrap_bootstrap_required:
        issues.append("grok_bwrap_bootstrap_requirement_mismatch")
    if (
        expected_grok_bwrap_bootstrap_required
        and evidence.get("grok_bwrap_bootstrap_available") is not True
    ):
        issues.append("grok_bwrap_bootstrap_unavailable")
    roles = evidence.get("workflow_roles")
    required_roles = {
        "XinaoIntegratedBusWorkflow": "REUSABLE_INSTRUMENT",
        "XinaoIntegratedBusParentWorkflow": "REUSABLE_INSTRUMENT_ORCHESTRATOR",
        "XinaoIntegratedBusChildWorkflow": "REUSABLE_INSTRUMENT_CHILD",
    }
    if not isinstance(roles, dict):
        issues.append("workflow_roles_missing")
    elif roles != required_roles:
        issues.append("workflow_roles_not_exact_generic_set")
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
    grok_sandbox_tty_required = _docker_native_grok_enabled()
    grok_outer_privilege_required = grok_sandbox_tty_required
    grok_bwrap_bootstrap_required = grok_sandbox_tty_required
    grok_session_store = None
    if grok_sandbox_tty_required:
        try:
            grok_session_store = _grok_session_store_state(
                Path(os.environ.get("GROK_HOME") or "/grok-home/.grok") / "sessions"
            )
        except RuntimeError as exc:
            issues.append(f"grok_session_store_unavailable:{type(exc).__name__}")
    try:
        release = source_release_identity(
            runtime_root=runtime_root,
            app_root=Path(os.environ.get("XINAO_CODEX_S_REPO_ROOT") or "/app"),
        )
    except (OSError, UnicodeError, RuntimeError) as exc:
        release = None
        issues.append(f"source_release_unavailable:{type(exc).__name__}")
    try:
        outer_privilege = _grok_outer_privilege_state(Path(f"/proc/{expected_process_id}/status"))
    except (OSError, UnicodeError, RuntimeError) as exc:
        outer_privilege = None
        if grok_outer_privilege_required:
            issues.append(f"grok_outer_privilege_unavailable:{type(exc).__name__}")
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
                expected_grok_sandbox_tty_required=grok_sandbox_tty_required,
                expected_grok_outer_privilege_required=grok_outer_privilege_required,
                expected_grok_outer_privilege_state=outer_privilege,
                expected_grok_bwrap_bootstrap_required=grok_bwrap_bootstrap_required,
            )
        )
    return {
        "schema_version": "xinao.integrated_bus_worker_readiness_check.v1",
        "ok": not issues,
        "issues": issues,
        "marker_path": str(marker_path),
        "grok_sandbox_tty_required": grok_sandbox_tty_required,
        "grok_sandbox_tty_available": evidence.get("grok_sandbox_tty_available") is True,
        "grok_outer_privilege_required": grok_outer_privilege_required,
        "grok_outer_privilege": outer_privilege,
        "grok_bwrap_bootstrap_required": grok_bwrap_bootstrap_required,
        "grok_bwrap_bootstrap_available": (evidence.get("grok_bwrap_bootstrap_available") is True),
        "grok_session_store": grok_session_store,
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
    reg = registry_summary()
    process_id = os.getpid()
    process_start_ticks = _process_start_ticks(process_id)
    grok_sandbox_tty_required = _docker_native_grok_enabled()
    grok_sandbox_tty_available = _controlling_tty_available()
    if grok_sandbox_tty_required and not grok_sandbox_tty_available:
        raise RuntimeError(
            "Docker-native Grok requires an allocated container TTY for its Landlock sandbox"
        )
    grok_session_store = None
    if grok_sandbox_tty_required:
        grok_session_store = _grok_session_store_state(
            Path(os.environ.get("GROK_HOME") or "/grok-home/.grok") / "sessions"
        )
    grok_outer_privilege_required = grok_sandbox_tty_required
    grok_outer_privilege = _grok_outer_privilege_state()
    if grok_outer_privilege_required and grok_outer_privilege.get("ok") is not True:
        raise RuntimeError(
            "Docker-native Grok requires the exact fail-closed outer capability state"
        )
    grok_bwrap_bootstrap_required = grok_sandbox_tty_required
    grok_bwrap_bootstrap_available = _grok_bwrap_bootstrap_available()
    if grok_bwrap_bootstrap_required and not grok_bwrap_bootstrap_available:
        raise RuntimeError(
            "Docker-native Grok requires a working nested bubblewrap namespace boundary"
        )
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
        "grok_sandbox_tty_required": grok_sandbox_tty_required,
        "grok_sandbox_tty_available": grok_sandbox_tty_available,
        "grok_outer_privilege_required": grok_outer_privilege_required,
        "grok_outer_privilege": grok_outer_privilege,
        "grok_bwrap_bootstrap_required": grok_bwrap_bootstrap_required,
        "grok_bwrap_bootstrap_available": grok_bwrap_bootstrap_available,
        "grok_session_store": grok_session_store,
        "task_queues": reg.get("task_queues", []),
        "workflows_registered": reg.get("workflows_registered", []),
        "workflow_roles": reg.get("workflow_roles", {}),
        "source_release": release,
        "activity_count": reg.get("activity_count", 0),
        "handroll_intact": False,
        "facade_hard_redirect": True,
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
