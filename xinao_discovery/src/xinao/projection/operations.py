"""Credential-free read projection for the native Temporal operator surface."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ENV_ALLOWLIST = {
    "COMSPEC",
    "NO_COLOR",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
}


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected a JSON object: {path}")
    return value


def _readonly_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    current = os.environ if source is None else source
    environment = {key: value for key, value in current.items() if key.upper() in _ENV_ALLOWLIST}
    environment["NO_COLOR"] = "1"
    if os.name == "nt" and environment.get("TEMP"):
        # Go's os.UserConfigDir requires APPDATA on Windows. Point it at the
        # existing temporary root instead of exposing the user's config tree.
        environment["APPDATA"] = environment["TEMP"]
    return environment


def describe_temporal_workflow(
    *,
    workflow_id: str,
    run_id: str = "",
    address: str = "127.0.0.1:7233",
    namespace: str = "default",
) -> dict[str, Any]:
    """Read one execution through the official Temporal CLI without domain credentials."""
    executable = shutil.which("temporal")
    if not executable:
        raise RuntimeError("Temporal CLI is required for workflow status projection")
    command = [
        executable,
        "workflow",
        "describe",
        "--workflow-id",
        workflow_id,
        "--address",
        address,
        "--namespace",
        namespace,
        "--output",
        "json",
    ]
    if run_id:
        command.extend(("--run-id", run_id))
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_readonly_environment(),
        timeout=30,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise TypeError("Temporal CLI describe output must be a JSON object")
    return value


def _host_evidence_path(ref: str, runtime_root: Path) -> Path:
    normalized = ref.replace("\\", "/")
    if not normalized.startswith("/evidence/"):
        raise ValueError("evidence reference must be rooted at /evidence/")
    relative = normalized.removeprefix("/evidence/")
    path = (runtime_root / Path(relative)).resolve()
    root = runtime_root.resolve()
    if path != root and root not in path.parents:
        raise ValueError("evidence reference escaped the runtime root")
    return path


def verify_evidence_report(report_path: Path, *, runtime_root: Path) -> dict[str, Any]:
    """Verify the P8 report, replay receipts, and its final content-addressed snapshot."""
    report = _load_object(report_path)
    expected_report_hash = _canonical_hash({**report, "report_hash": ""})
    mainline = dict(report.get("mainline_result") or {})
    artifact_ref = str(mainline.get("last_evidence_ref") or "")
    artifact_path = _host_evidence_path(artifact_ref, runtime_root)
    artifact = _load_object(artifact_path)
    snapshot = dict(artifact.get("snapshot") or {})
    snapshot_hash = _canonical_hash(snapshot)
    history = dict(report.get("history") or {})
    mainline_replay = dict(history.get("mainline") or {})
    campaign_replay = dict(history.get("campaign") or {})
    checks = dict(report.get("checks") or {})
    verification = {
        "report_status_verified": report.get("status") == "verified",
        "report_hash_matches": report.get("report_hash") == expected_report_hash,
        "all_report_checks_pass": bool(checks) and all(value is True for value in checks.values()),
        "mainline_replay_passed": mainline_replay.get("replay_failure") is None,
        "campaign_replay_passed": campaign_replay.get("replay_failure") is None,
        "snapshot_exists": artifact_path.is_file(),
        "snapshot_hash_matches": artifact.get("snapshot_hash") == snapshot_hash
        and artifact_path.stem == snapshot_hash,
        "snapshot_workflow_matches": artifact.get("workflow_id")
        == report.get("prepared", {}).get("workflow_id"),
    }
    return {
        "schema_version": "xinao.evidence_verification.v1",
        "ok": all(verification.values()),
        "read_only": True,
        "report_path": str(report_path.resolve()),
        "report_hash": expected_report_hash,
        "artifact_path": str(artifact_path),
        "checks": verification,
    }


def build_workflow_projection(
    report_path: Path,
    *,
    temporal_description: dict[str, Any],
    runtime_root: Path,
) -> dict[str, Any]:
    """Compose a stable operator projection without a domain database connection."""
    report = _load_object(report_path)
    prepared = dict(report.get("prepared") or {})
    info = dict(temporal_description.get("workflowExecutionInfo") or {})
    execution = dict(info.get("execution") or {})
    result = dict(temporal_description.get("result") or report.get("mainline_result") or {})
    control = [dict(item) for item in result.get("control_audit", [])]
    evidence = verify_evidence_report(report_path, runtime_root=runtime_root)
    return {
        "schema_version": "xinao.workflow_projection.v1",
        "read_only": True,
        "domain_write_credentials": False,
        "workflow": {
            "workflow_id": execution.get("workflowId") or prepared.get("workflow_id"),
            "run_id": execution.get("runId") or prepared.get("run_id"),
            "type": dict(info.get("type") or {}).get("name"),
            "task_queue": info.get("taskQueue"),
            "status": info.get("status"),
            "history_length": info.get("historyLength"),
        },
        "state": {
            "operation_id": result.get("operation_id"),
            "complete": result.get("complete"),
            "paused": result.get("paused"),
            "stop_requested": result.get("stop_requested"),
            "fact_count": result.get("fact_count"),
            "duplicate_signals": result.get("duplicate_signals"),
        },
        "controls": control,
        "pause_visible": any(item.get("action") == "PAUSE" for item in control),
        "resume_visible": any(item.get("action") == "RESUME" for item in control),
        "evidence": evidence,
    }


def render_tui(projection: dict[str, Any]) -> str:
    """Render a dependency-free read-only terminal projection."""
    workflow = dict(projection["workflow"])
    state = dict(projection["state"])
    controls = list(projection.get("controls") or [])
    lines = [
        "Xinao workflow projection [READ ONLY]",
        f"workflow : {workflow.get('workflow_id')}",
        f"run      : {workflow.get('run_id')}",
        f"status   : {workflow.get('status')}",
        f"facts    : {state.get('fact_count')} (duplicates={state.get('duplicate_signals')})",
        f"evidence : {'VERIFIED' if projection['evidence']['ok'] else 'FAILED'}",
        "controls : "
        + (" -> ".join(str(item.get("action")) for item in controls) if controls else "none"),
    ]
    return "\n".join(lines)
