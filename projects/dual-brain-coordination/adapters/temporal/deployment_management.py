"""Small host-side helpers for official Temporal Worker Deployment routing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def load_verified_deployment(project_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Load a deployment manifest only when every pinned Worker source matches."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("use_worker_versioning") is not True:
        raise RuntimeError("worker deployment manifest does not enable versioning")
    source_hashes = manifest.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise RuntimeError("worker deployment manifest has no source hashes")
    for relative, expected in source_hashes.items():
        path = project_root / str(relative)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(expected):
            raise RuntimeError(f"worker deployment source drift: {relative}")
    return manifest


def temporal_cli(address: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["temporal", *args, "--address", address],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def deployment_is_current(address: str, deployment_name: str, build_id: str) -> bool:
    described = temporal_cli(
        address,
        "worker",
        "deployment",
        "describe",
        "--name",
        deployment_name,
        "--output",
        "json",
    )
    if described.returncode != 0:
        return False
    payload = json.loads(described.stdout)
    routing = payload.get("routingConfig") if isinstance(payload, dict) else None
    return isinstance(routing, dict) and routing.get("currentVersionBuildID") == build_id


async def ensure_deployment_current(
    address: str,
    deployment_name: str,
    build_id: str,
    *,
    attempts: int = 30,
) -> None:
    """Register/rout one verified Worker Deployment version with bounded retries."""
    last_error = "deployment version not ready"
    for _ in range(attempts):
        if await asyncio.to_thread(
            deployment_is_current,
            address,
            deployment_name,
            build_id,
        ):
            return
        promoted = await asyncio.to_thread(
            temporal_cli,
            address,
            "worker",
            "deployment",
            "set-current-version",
            "--deployment-name",
            deployment_name,
            "--build-id",
            build_id,
            "--yes",
        )
        if promoted.returncode == 0:
            return
        last_error = (promoted.stderr or promoted.stdout or last_error).strip()[-500:]
        await asyncio.sleep(1)
    raise RuntimeError(f"worker deployment did not become current: {last_error}")


__all__ = [
    "deployment_is_current",
    "ensure_deployment_current",
    "load_verified_deployment",
    "temporal_cli",
]
