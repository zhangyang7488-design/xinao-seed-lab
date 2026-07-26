#!/usr/bin/env python3
"""Atomically promote an append-only science revision chain into the live projection.

The current science text remains the human authority. This tool only updates the
non-authoritative active-parent projection after every immutable revision evidence
file and its task-run event already exist and pass the strict consumer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from xinao.science.active_parent import (
    SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    load_science_active_parent,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _revision_entry(evidence_path: Path, event_ref: str) -> dict[str, str]:
    evidence = _load_json(evidence_path)
    if (
        evidence.get("schema_version") != "xinao.science_revision.v1"
        or evidence.get("status") != "APPLIED"
        or not isinstance(evidence.get("run_id"), str)
        or not evidence["run_id"].strip()
    ):
        raise ValueError(f"unsupported or incomplete science revision evidence: {evidence_path}")
    return {
        "status": "APPLIED",
        "run_id": evidence["run_id"],
        "event_ref": event_ref,
        "revision_evidence_ref": str(evidence_path),
        "revision_evidence_sha256": _sha256(evidence_path),
    }


def promote_revision_chain(
    *,
    projection_path: Path,
    evidence_paths: list[Path],
    event_refs: list[str],
    rollback_copy: Path,
) -> dict[str, Any]:
    if len(evidence_paths) != len(event_refs) or not evidence_paths:
        raise ValueError("revision evidence and event refs must be paired and non-empty")
    if rollback_copy.exists():
        raise FileExistsError(f"rollback copy already exists: {rollback_copy}")

    projection = _load_json(projection_path)
    if projection.get("science_revision_chain") not in (None, []):
        raise ValueError("live projection already contains a science revision chain")
    projection["science_revision_chain"] = [
        _revision_entry(evidence_path.resolve(), event_ref)
        for evidence_path, event_ref in zip(evidence_paths, event_refs, strict=True)
    ]

    projection_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{projection_path.name}.", suffix=".candidate", dir=projection_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        temporary_path.write_text(
            json.dumps(projection, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        resolution = load_science_active_parent(temporary_path)
        rollback_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(projection_path, rollback_copy)
        os.replace(temporary_path, projection_path)
        try:
            live_resolution = load_science_active_parent(projection_path)
        except Exception:
            shutil.copy2(rollback_copy, temporary_path)
            os.replace(temporary_path, projection_path)
            raise
    finally:
        temporary_path.unlink(missing_ok=True)

    return {
        "schema_version": "xinao.science_revision_promotion.v1",
        "status": "VERIFIED",
        "projection_path": str(projection_path),
        "projection_sha256": _sha256(projection_path),
        "rollback_copy": str(rollback_copy),
        "rollback_copy_sha256": _sha256(rollback_copy),
        "revision_count": len(projection["science_revision_chain"]),
        "candidate_resolution_status": resolution["status"],
        "live_resolution_status": live_resolution["status"],
        "active_parent_sha256": live_resolution["active_parent"]["sha256"],
        "completion_claim_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--projection",
        type=Path,
        default=SCIENCE_ACTIVE_PARENT_PROJECTION_PATH,
    )
    parser.add_argument("--revision-evidence", type=Path, action="append", required=True)
    parser.add_argument("--event-ref", action="append", required=True)
    parser.add_argument("--rollback-copy", type=Path, required=True)
    args = parser.parse_args()
    result = promote_revision_chain(
        projection_path=args.projection.resolve(),
        evidence_paths=args.revision_evidence,
        event_refs=args.event_ref,
        rollback_copy=args.rollback_copy.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
