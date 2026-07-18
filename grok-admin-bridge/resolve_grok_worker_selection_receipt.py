"""Thin CLI adapter for the canonical S supervisor-worker selector.

This module owns no routing policy.  It binds one exact, already-observed
direct Grok candidate to the existing selector and atomically writes the
resulting decision receipt for the lower fail-closed worker-pool layers.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervisor-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"selection receipt already exists: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    args = _parse_args()
    supervisor_root = args.supervisor_root.resolve(strict=True)
    selector_source = (
        supervisor_root / "services" / "agent_runtime" / "routing_policy_reader.py"
    )
    if not selector_source.is_file():
        raise FileNotFoundError(f"canonical selector missing: {selector_source}")
    sys.path.insert(0, str(supervisor_root))

    from services.agent_runtime.routing_policy_reader import (  # noqa: PLC0415
        resolve_supervisor_worker_decision,
    )

    model = args.model.strip()
    if not model:
        raise ValueError("model must be non-empty")
    identity = {
        "provider_id": "grok_acpx_headless",
        "profile_ref": "grok.com.cached_profile",
        "model_id": model,
        "transport_id": "direct-grok-worker-pool",
    }
    request = {
        "candidates": [
            {
                **identity,
                "declared_active": True,
                "healthy": True,
                "positive_benefit": True,
                "context_capable": False,
            }
        ],
        "task_separable": True,
        "supervisor_choice": identity,
        "context_inheritance_required": False,
    }
    receipt = resolve_supervisor_worker_decision(
        request,
        runtime_root=args.runtime_root.resolve(strict=True),
    )
    selected = receipt.get("selected_candidate")
    if receipt.get("decision") != "selected" or not isinstance(selected, dict):
        raise RuntimeError(
            "canonical selector did not select the exact direct Grok candidate: "
            + str(receipt.get("decision_reason") or receipt.get("decision"))
        )
    observed_identity = {
        key: str(selected.get(key) or "")
        for key in ("provider_id", "profile_ref", "model_id", "transport_id")
    }
    if observed_identity != identity:
        raise RuntimeError(
            f"canonical selector identity mismatch: selected={observed_identity} requested={identity}"
        )

    output = args.output.resolve(strict=False)
    _atomic_write_json(output, receipt)
    print(
        json.dumps(
            {
                "selection_path": str(output),
                "decision_sha256": str(receipt.get("decision_sha256") or ""),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
