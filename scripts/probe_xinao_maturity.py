"""One-shot, read-only maturity probe for the canonical Xinao agent route.

Temporal CLI and Docker Engine remain authoritative.  This file only composes
their bounded JSON reads, static contract hashes, and a native Windows window
negative into one atomic evidence artifact.  It never starts a workflow,
creates a sandbox, cleans a residual, or installs a monitor.
"""

from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import tomllib
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import docker

REPO_ROOT = Path(__file__).resolve().parents[1]


def _configured_path(name: str, default: str) -> Path:
    """Resolve an operator-owned path without making a host layout a test fixture."""
    return Path(os.environ.get(name, default)).expanduser()


DUAL_ROOT = _configured_path(
    "XINAO_DUAL_ROOT", r"E:\XINAO_RESEARCH_WORKSPACES\dual-brain-coordination"
)
ISLAND_ROOT = _configured_path(
    "XINAO_ISLAND_ROOT", r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island"
)
SOURCE_CLOSURE = _configured_path(
    "XINAO_SOURCE_CLOSURE",
    r"D:\XINAO_RESEARCH_RUNTIME\state\xinao-market-lab\source-provenance"
    r"\source_provenance_closure_20260712T1153+0800.json",
)
CANARY_ROOT = ISLAND_ROOT / "runs" / "continuous-mature-closure-20260713-001"
DEPLOYMENT_MANIFEST = DUAL_ROOT / "adapters" / "temporal" / "worker_deployment.v1.json"
TOOL_SURFACE_TOML = DUAL_ROOT / "provisioning" / "grok-background-tool-surface.v1.toml"
GROK_PARALLEL = DUAL_ROOT / "src" / "xinao_coordination" / "temporal" / "grok_parallel.py"
GROK_ACP_ADAPTER = DUAL_ROOT / "adapters" / "grok" / "Invoke-XinaoGrokAcp.ps1"
DEFAULT_OUTPUT = ISLAND_ROOT / "state" / "maturity_probe" / "latest.json"
OPENHANDS_CONTAINER_ENDPOINT = "openhands-execution-v1"
OPENHANDS_NETWORK_ENDPOINT = "openhands-execution-network-v1"
SHARED_CONTROL_NETWORK = "xinao_sandbox_control_v1"
EXPECTED_TOOLS = {
    "grep",
    "list_dir",
    "read_file",
    "search_tool",
    "use_tool",
    "web_fetch",
    "web_search",
}
EXPECTED_SHELL_DENY = {"run_terminal_cmd", "run_terminal_command"}
CONSOLE_EXECUTABLES = {
    "cmd.exe",
    "conhost.exe",
    "docker.exe",
    "docker-sandbox.exe",
    "openconsole.exe",
    "powershell.exe",
    "pwsh.exe",
    "python.exe",
    "pythonw.exe",
    "temporal.exe",
    "windowsterminal.exe",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(raw, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _run_text(args: list[str], *, timeout: int = 30) -> str:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        args,
        cwd=DUAL_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "command failed").strip()[:2000]
        raise RuntimeError(f"{Path(args[0]).name} exit={result.returncode}: {message}")
    return result.stdout.strip()


def _run_json(args: list[str], *, timeout: int = 30) -> Any:
    output = _run_text(args, timeout=timeout)
    return json.loads(output) if output else None


def _temporal_args(temporal: str, *parts: str) -> list[str]:
    return [
        temporal,
        *parts,
        "--address",
        "127.0.0.1:7233",
        "--namespace",
        "default",
        "--output",
        "json",
    ]


def _poller_summary(value: dict[str, Any], *, now_epoch: float) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in value.get("pollers") or []:
        stamp = item.get("last_access_time") or {}
        seconds = float(stamp.get("seconds") or 0)
        nanos = float(stamp.get("nanos") or 0)
        observed = seconds + nanos / 1_000_000_000
        age = max(0.0, now_epoch - observed) if observed else float("inf")
        deployment = item.get("deployment_options") or {}
        version = item.get("worker_version_capabilities") or {}
        rows.append(
            {
                "identity": str(item.get("identity") or ""),
                "last_access_epoch": observed,
                "age_seconds": round(age, 3),
                "fresh_within_60_seconds": age <= 60,
                "deployment_name": str(deployment.get("deployment_name") or ""),
                "build_id": str(deployment.get("build_id") or version.get("build_id") or ""),
            }
        )
    return {
        "poller_count": len(rows),
        "all_fresh_within_60_seconds": bool(rows)
        and all(item["fresh_within_60_seconds"] for item in rows),
        "pollers": rows,
    }


def _background_allowed_tools(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "BACKGROUND_ALLOWED_TOOLS"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Call) or not node.value.args:
            break
        value = ast.literal_eval(node.value.args[0])
        return sorted(str(item) for item in value)
    raise RuntimeError("BACKGROUND_ALLOWED_TOOLS was not found as a literal set")


def _tool_surface() -> dict[str, Any]:
    config = tomllib.loads(TOOL_SURFACE_TOML.read_text(encoding="utf-8"))
    servers = config.get("mcp_servers") or {}
    server_state = {
        str(name): bool((entry or {}).get("enabled")) for name, entry in servers.items()
    }
    allowed = _background_allowed_tools(GROK_PARALLEL)
    adapter_text = GROK_ACP_ADAPTER.read_text(encoding="utf-8")
    match = re.search(r"requiredShellDenyCsv\s*=\s*'([^']+)'", adapter_text)
    deny = sorted(
        item.strip() for item in (match.group(1) if match else "").split(",") if item.strip()
    )
    return {
        "allowed_tools": allowed,
        "allowed_tools_exact": set(allowed) == EXPECTED_TOOLS,
        "mcp_servers": server_state,
        "filesystem_disabled": server_state.get("filesystem") is False,
        "commander_disabled": server_state.get("commander") is False,
        "xinao_sandbox_enabled": server_state.get("xinao-sandbox") is True,
        "shell_capability_deny": deny,
        "shell_capability_deny_exact": set(deny) == EXPECTED_SHELL_DENY,
        "source_hashes": {
            str(TOOL_SURFACE_TOML): _sha256(TOOL_SURFACE_TOML),
            str(GROK_PARALLEL): _sha256(GROK_PARALLEL),
            str(GROK_ACP_ADAPTER): _sha256(GROK_ACP_ADAPTER),
        },
    }


def _safe_xinao_labels(labels: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in labels.items()
        if str(key).startswith("xinao.") or str(key) == "com.docker.compose.service"
    }


def _container_summary(container: Any) -> dict[str, Any]:
    container.reload()
    value = container.attrs
    state = value.get("State") or {}
    health = state.get("Health") or {}
    return {
        "id": str(container.id),
        "name": str(value.get("Name") or "").lstrip("/"),
        "status": str(state.get("Status") or container.status or ""),
        "health": str(health.get("Status") or "not_configured"),
        "labels": _safe_xinao_labels((value.get("Config") or {}).get("Labels") or {}),
        "networks": sorted(((value.get("NetworkSettings") or {}).get("Networks") or {}).keys()),
        "mount_destinations": sorted(
            str(item.get("Destination") or "") for item in value.get("Mounts") or []
        ),
    }


def _docker_state() -> dict[str, Any]:
    client = docker.from_env()
    try:
        client.ping()
        houtai = _container_summary(client.containers.get("houtai-gongren"))
        broker = _container_summary(client.containers.get("mowei-zhixing"))
        residual_containers = [
            _container_summary(item)
            for item in client.containers.list(
                all=True,
                filters={"label": f"xinao.endpoint={OPENHANDS_CONTAINER_ENDPOINT}"},
            )
        ]
        residual_networks: list[dict[str, Any]] = []
        for network in client.networks.list(
            filters={"label": f"xinao.endpoint={OPENHANDS_NETWORK_ENDPOINT}"}
        ):
            network.reload()
            value = network.attrs
            residual_networks.append(
                {
                    "id": str(network.id),
                    "name": str(value.get("Name") or ""),
                    "driver": str(value.get("Driver") or ""),
                    "internal": value.get("Internal") is True,
                    "member_container_ids": sorted((value.get("Containers") or {}).keys()),
                    "labels": _safe_xinao_labels(value.get("Labels") or {}),
                }
            )
        control = client.networks.get(SHARED_CONTROL_NETWORK)
        control.reload()
        control_members = control.attrs.get("Containers") or {}
        return {
            "engine_ping": True,
            "houtai_gongren": houtai,
            "mowei_zhixing": broker,
            "residual_containers": residual_containers,
            "residual_networks": residual_networks,
            "shared_control_network": {
                "name": SHARED_CONTROL_NETWORK,
                "driver": str(control.attrs.get("Driver") or ""),
                "internal": control.attrs.get("Internal") is True,
                "member_container_ids": sorted(control_members.keys()),
                "member_names": sorted(
                    str(item.get("Name") or "") for item in control_members.values()
                ),
            },
        }
    finally:
        client.close()


class _VisibleWindowSampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline: set[str] = set()
        self._observed: dict[str, dict[str, Any]] = {}
        self.supported = os.name == "nt"

    @staticmethod
    def _process_name(pid: int) -> str:
        if os.name != "nt":
            return ""
        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name.lower()
            return ""
        finally:
            kernel32.CloseHandle(process)

    @classmethod
    def _snapshot(cls) -> list[dict[str, Any]]:
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        rows: list[dict[str, Any]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = cls._process_name(int(pid.value))
            if name not in CONSOLE_EXECUTABLES:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            rows.append(
                {
                    "handle": int(hwnd),
                    "pid": int(pid.value),
                    "process": name,
                    "title": title.value,
                }
            )
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return rows

    def start(self) -> None:
        if not self.supported:
            return
        baseline = self._snapshot()
        self._baseline = {f"{item['handle']}|{item['pid']}" for item in baseline}
        self._thread = threading.Thread(target=self._run, name="xinao-window-probe", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        while not self._stop.wait(0.05):
            foreground = int(user32.GetForegroundWindow())
            for item in self._snapshot():
                key = f"{item['handle']}|{item['pid']}"
                if key in self._baseline or key in self._observed:
                    continue
                item["foreground_when_seen"] = item["handle"] == foreground
                item["observed_at"] = datetime.now(UTC).isoformat()
                self._observed[key] = item

    def stop(self) -> dict[str, Any]:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=2)
        rows = list(self._observed.values())
        return {
            "supported": self.supported,
            "baseline_count": len(self._baseline),
            "new_console_window_count": len(rows),
            "foreground_regression_count": sum(
                1 for item in rows if item.get("foreground_when_seen") is True
            ),
            "observed": rows,
        }


def _rollback_state() -> dict[str, Any]:
    plan_path = CANARY_ROOT / "per_request_network_canary_plan_20260713T0038+0800.json"
    plan = _read_json(plan_path)
    backup_root = Path(plan["rollback"]["backup_root"])
    expected = plan["baseline_control"]["source_hashes"]
    rows: dict[str, Any] = {}
    for name, expected_hash in expected.items():
        backup = backup_root / name
        actual = _sha256(backup) if backup.is_file() else ""
        rows[name] = {
            "path": str(backup),
            "expected_sha256": expected_hash,
            "actual_sha256": actual,
            "match": actual == expected_hash,
        }
    return {
        "canary_plan": str(plan_path),
        "canary_plan_sha256": _sha256(plan_path),
        "backup_files": rows,
        "all_backup_hashes_match": all(item["match"] for item in rows.values()),
    }


def _source_gate() -> dict[str, Any]:
    closure = _read_json(SOURCE_CLOSURE)
    decision = closure.get("decision") or {}
    local = closure.get("local_input") or {}
    history = local.get("history_jsonl") or {}
    return {
        "closure_path": str(SOURCE_CLOSURE),
        "closure_sha256": _sha256(SOURCE_CLOSURE),
        "frontier_status": closure.get("frontier_status"),
        "row_count": history.get("row_count"),
        "verify_false_count": history.get("verify_false_count"),
        "verify_true_count": history.get("verify_true_count"),
        "official_product_identity_verified": decision.get("official_product_identity_verified"),
        "authoritative_history_feed_found": decision.get("authoritative_history_feed_found"),
        "source_verified": decision.get("source_verified"),
        "source_truth_external_blocker": decision.get("source_truth_external_blocker"),
        "promote_l1": decision.get("promote_l1"),
    }


def _queue_backlogs(version: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for item in version.get("taskQueuesInfos") or []:
        kind = str(item.get("type") or "unknown")
        stats = item.get("stats") or {}
        rows[kind] = {
            "task_queue": str(item.get("name") or ""),
            "approximate_backlog_count": int(stats.get("approximateBacklogCount") or 0),
            "approximate_backlog_age": float(stats.get("approximateBacklogAge") or 0),
            "backlog_increase_rate": float(stats.get("backlogIncreaseRate") or 0),
        }
    return rows


def _history_summary(history: Any) -> dict[str, Any]:
    raw = json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(history, dict):
        events = history.get("events") or history.get("history", {}).get("events") or []
    elif isinstance(history, list):
        events = history
    else:
        events = []
    return {
        "event_count": len(events),
        "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest().upper(),
        "embedded": False,
    }


def build_probe(*, workflow_id: str = "", run_id: str = "") -> dict[str, Any]:
    temporal = shutil.which("temporal")
    if not temporal:
        raise RuntimeError("Temporal CLI is not discoverable")
    manifest = _read_json(DEPLOYMENT_MANIFEST)
    deployment_name = str(manifest["deployment_name"])
    build_id = str(manifest["build_id"])
    task_queue = str(manifest["task_queue"])
    version_text = _run_text([temporal, "--version"])
    deployment = _run_json(
        _temporal_args(temporal, "worker", "deployment", "describe", "--name", deployment_name)
    )
    deployment_version = _run_json(
        _temporal_args(
            temporal,
            "worker",
            "deployment",
            "describe-version",
            "--deployment-name",
            deployment_name,
            "--build-id",
            build_id,
            "--report-task-queue-stats",
        )
    )
    now_epoch = time.time()
    workflow_pollers = _poller_summary(
        _run_json(
            _temporal_args(
                temporal,
                "task-queue",
                "describe",
                "--task-queue",
                task_queue,
                "--legacy-mode",
                "--task-queue-type-legacy",
                "workflow",
            )
        ),
        now_epoch=now_epoch,
    )
    activity_pollers = _poller_summary(
        _run_json(
            _temporal_args(
                temporal,
                "task-queue",
                "describe",
                "--task-queue",
                task_queue,
                "--legacy-mode",
                "--task-queue-type-legacy",
                "activity",
            )
        ),
        now_epoch=now_epoch,
    )
    workflow: dict[str, Any] | None = None
    if workflow_id:
        describe_args = ["workflow", "describe", "--workflow-id", workflow_id]
        history_args = ["workflow", "show", "--workflow-id", workflow_id]
        if run_id:
            describe_args.extend(["--run-id", run_id])
            history_args.extend(["--run-id", run_id])
        description = _run_json(_temporal_args(temporal, *describe_args), timeout=60)
        history = _run_json(_temporal_args(temporal, *history_args), timeout=60)
        workflow = {
            "workflow_id": workflow_id,
            "run_id": run_id
            or str(
                ((description.get("workflowExecutionInfo") or {}).get("execution") or {}).get(
                    "runId"
                )
                or ""
            ),
            "description": description,
            "history": _history_summary(history),
        }
    docker_state = _docker_state()
    tools = _tool_surface()
    source = _source_gate()
    rollback = _rollback_state()
    routing = deployment.get("routingConfig") or {}
    backlogs = _queue_backlogs(deployment_version)
    checks = {
        "deployment_current_matches_manifest": (
            routing.get("currentVersionDeploymentName") == deployment_name
            and routing.get("currentVersionBuildID") == build_id
        ),
        "deployment_ramp_empty": (
            not routing.get("rampingVersionDeploymentName")
            and not routing.get("rampingVersionBuildID")
            and float(routing.get("rampingVersionPercentage") or 0) == 0
        ),
        "workflow_poller_fresh": workflow_pollers["all_fresh_within_60_seconds"],
        "activity_poller_fresh": activity_pollers["all_fresh_within_60_seconds"],
        "workflow_backlog_zero": (
            backlogs.get("workflow", {}).get("approximate_backlog_count") == 0
        ),
        "activity_backlog_zero": (
            backlogs.get("activity", {}).get("approximate_backlog_count") == 0
        ),
        "houtai_gongren_healthy": (
            docker_state["houtai_gongren"]["status"] == "running"
            and docker_state["houtai_gongren"]["health"] == "healthy"
        ),
        "mowei_zhixing_healthy": (
            docker_state["mowei_zhixing"]["status"] == "running"
            and docker_state["mowei_zhixing"]["health"] == "healthy"
        ),
        "docker_control_split": (
            "/var/run/docker.sock" not in docker_state["houtai_gongren"]["mount_destinations"]
            and "/var/run/docker.sock" in docker_state["mowei_zhixing"]["mount_destinations"]
        ),
        "openhands_residual_containers_zero": not docker_state["residual_containers"],
        "openhands_residual_networks_zero": not docker_state["residual_networks"],
        "shared_control_network_internal": docker_state["shared_control_network"]["internal"],
        "shared_control_network_only_broker": docker_state["shared_control_network"]["member_names"]
        == ["mowei-zhixing"],
        "grok_tool_surface_exact": (
            tools["allowed_tools_exact"]
            and tools["filesystem_disabled"]
            and tools["commander_disabled"]
            and tools["xinao_sandbox_enabled"]
            and tools["shell_capability_deny_exact"]
        ),
        "rollback_backups_match": rollback["all_backup_hashes_match"],
        "source_gate_quarantined": (
            source["frontier_status"] == "verified"
            and source["source_verified"] is False
            and source["source_truth_external_blocker"] is True
            and source["promote_l1"] is False
            and source["verify_true_count"] == 0
        ),
        "selected_workflow_history_observed": (
            workflow is None or workflow["history"]["event_count"] > 0
        ),
    }
    return {
        "schema_version": "xinao.maturity_probe.v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "one_shot_read_only",
        "authorities": {
            "temporal": "Temporal CLI and Server APIs",
            "docker": "Docker Engine API via docker-py 7.1.0",
            "tool_surface": "canonical Grok source and managed TOML",
            "source_gate": "hash-pinned source provenance closure",
        },
        "temporal": {
            "cli_version": version_text,
            "manifest": {
                "path": str(DEPLOYMENT_MANIFEST),
                "sha256": _sha256(DEPLOYMENT_MANIFEST),
                "deployment_name": deployment_name,
                "build_id": build_id,
                "task_queue": task_queue,
            },
            "deployment": deployment,
            "deployment_version": deployment_version,
            "backlogs": backlogs,
            "workflow_pollers": workflow_pollers,
            "activity_pollers": activity_pollers,
            "selected_workflow": workflow,
        },
        "docker": docker_state,
        "tool_surface": tools,
        "rollback": rollback,
        "source_gate": source,
        "checks": checks,
        "honest_boundaries": [
            "single-user local endpoint; hostile multi-tenant kernel or VM isolation is not claimed",
            "source provenance remains verify=false and L1 remains closed",
            "OpenTelemetry console-span capability is not treated as production Temporal tracing",
            "the probe performs no cleanup, workflow start, timer, daemon, or persistent monitoring",
        ],
        "probe_source": {
            "path": str(Path(__file__).resolve()),
            "sha256": _sha256(Path(__file__).resolve()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    windows = _VisibleWindowSampler()
    windows.start()
    exit_code = 2
    try:
        result = build_probe(workflow_id=args.workflow_id, run_id=args.run_id)
        exit_code = 0
    except Exception as exc:
        result = {
            "schema_version": "xinao.maturity_probe.v1",
            "generated_at": datetime.now().astimezone().isoformat(),
            "mode": "one_shot_read_only",
            "status": "unverified",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:2000],
            "checks": {},
            "completion_claim_allowed": False,
        }
    window_result = windows.stop()
    result["visible_windows"] = window_result
    result.setdefault("checks", {})["no_visible_console_or_focus_regression"] = (
        window_result["new_console_window_count"] == 0
        and window_result["foreground_regression_count"] == 0
    )
    checks = result.get("checks") or {}
    if exit_code == 0:
        passed = bool(checks) and all(value is True for value in checks.values())
        result["status"] = "verified" if passed else "partial"
        result["completion_claim_allowed"] = passed
        exit_code = 0 if passed else 1
    _write_json_atomic(args.output.resolve(), result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(args.output.resolve()),
                "checks_passed": sum(value is True for value in checks.values()),
                "checks_total": len(checks),
            },
            ensure_ascii=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
