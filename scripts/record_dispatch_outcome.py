#!/usr/bin/env python3
"""Write a typed dispatch outcome and append its hash to an existing task-run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.dispatch_economics import (  # noqa: E402
    DispatchEconomicsError,
    build_dispatch_outcome_event,
)

WINDOWLESS_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _runtime_path_resolver(runtime_root: Path) -> Callable[[str], Path]:
    """Map the container's immutable /evidence carrier to the exact host runtime."""

    root = runtime_root.resolve(strict=True)

    def resolve(logical: str) -> Path:
        text = str(logical or "").strip()
        normalized = text.replace("\\", "/")
        if normalized == "/evidence" or normalized.startswith("/evidence/"):
            relative = normalized.removeprefix("/evidence").lstrip("/")
            parts = tuple(part for part in relative.split("/") if part)
            if any(part in {".", ".."} for part in parts):
                raise ValueError("container evidence path cannot traverse runtime root")
            candidate = (root.joinpath(*parts)).resolve(strict=False)
            candidate.relative_to(root)
            return candidate
        return Path(text)

    return resolve


def _atomic_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if path.exists():
        observed = path.read_bytes()
        if observed != raw:
            raise FileExistsError(f"dispatch outcome already exists with different bytes: {path}")
        return hashlib.sha256(observed).hexdigest()
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-run-cli", type=Path, required=True)
    parser.add_argument("--task-run-root", type=Path, required=True)
    parser.add_argument("--task-run-id", required=True)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--actor", default="codex-owner")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        if not isinstance(request, dict):
            raise TypeError("request must be an object")
        path_resolver = (
            _runtime_path_resolver(args.runtime_root) if args.runtime_root is not None else None
        )
        event = build_dispatch_outcome_event(**request, path_resolver=path_resolver)
        event_sha = _atomic_json(args.output, event)
        phase = str(event["event_type"])
        parent_work_key = str(event["parent_work_key"])
        target = str(event["work_key"])
        package_id = str(event["package_id"])
        work_identity_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "parent_work_key": parent_work_key,
                    "work_key": target,
                    "package_id": package_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        command = [
            sys.executable,
            str(args.task_run_cli.resolve(strict=True)),
            "--root",
            str(args.task_run_root.resolve(strict=False)),
            "event",
            "--run-id",
            args.task_run_id,
            "--event-id",
            f"evt-dispatch-{event_sha[:32]}",
            "--actor",
            args.actor,
            "--kind",
            "result",
            "--phase",
            phase,
            "--summary",
            f"{phase} work-unit {parent_work_key}/{target}/{package_id}",
            "--evidence-ref",
            f"{args.output.resolve(strict=True)}#sha256={event_sha}",
            "--target",
            target,
            "--exit-code",
            "0",
            "--retry-class",
            "none",
            "--side-effect-id",
            f"se:{phase}:{args.task_run_id}:{work_identity_sha256[:16]}:{event_sha[:16]}",
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=WINDOWLESS_CREATIONFLAGS,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"task-run append failed exit={completed.returncode}: {completed.stderr.strip()}"
            )
        print(
            json.dumps(
                {
                    "event_ref": str(args.output.resolve(strict=True)),
                    "event_sha256": event_sha,
                    "task_run_id": args.task_run_id,
                    "phase": phase,
                    "parent_work_key": parent_work_key,
                    "work_key": target,
                    "package_id": package_id,
                    "work_identity_sha256": work_identity_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        DispatchEconomicsError,
    ) as exc:
        print(f"DISPATCH_OUTCOME_RECORD_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
