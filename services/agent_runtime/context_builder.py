from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_context_snapshot(
    *,
    runtime: str | Path,
    repo: str | Path,
    max_bundle_bytes: int = 196608,
    max_file_bytes: int = 32768,
) -> dict[str, Any]:
    runtime = Path(runtime)
    repo = Path(repo)
    text = f"repo={repo}\nruntime={runtime}\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    snapshot_id = f"context-{digest[:16]}"
    bundle_path = runtime / "agent_runtime" / "context_snapshots" / f"{snapshot_id}.txt"
    manifest_path = runtime / "agent_runtime" / "context_snapshots" / f"{snapshot_id}.json"
    latest_path = runtime / "agent_runtime" / "context_snapshots" / "latest.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(text[:max_bundle_bytes], encoding="utf-8")
    manifest = {
        "schema_version": "xinao.context_snapshot.v1",
        "snapshot_id": snapshot_id,
        "status": "ready",
        "repo": str(repo),
        "runtime": str(runtime),
        "bundle_path": str(bundle_path),
        "snapshot_hash": digest,
        "max_bundle_bytes": max_bundle_bytes,
        "max_file_bytes": max_file_bytes,
        "named_blocker": "",
    }
    _write_json(manifest_path, manifest)
    _write_json(latest_path, manifest)
    return manifest


def load_context_snapshot(runtime: str | Path, snapshot_id: str) -> tuple[dict[str, Any], str]:
    runtime = Path(runtime)
    manifest_path = runtime / "agent_runtime" / "context_snapshots" / f"{snapshot_id}.json"
    bundle_path = runtime / "agent_runtime" / "context_snapshots" / f"{snapshot_id}.txt"
    if not manifest_path.is_file():
        return {"status": "missing", "snapshot_id": snapshot_id, "snapshot_hash": ""}, ""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text = bundle_path.read_text(encoding="utf-8") if bundle_path.is_file() else ""
    return manifest, text
