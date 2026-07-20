#!/usr/bin/env python3
"""Resolve one immutable quota snapshot for a bounded dispatch epoch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.quota_dispatch_epoch import (  # noqa: E402
    QuotaDispatchEpochError,
    get_or_refresh_dispatch_epoch,
    record_dispatch_epoch_usage,
)


def _collector(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"quota collector exit={completed.returncode}: {completed.stderr.strip()}"
        )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise TypeError("quota collector output must be an object")
    return value


def _write_json_atomic(path: Path, value: object) -> None:
    path = path.resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--epoch-id", required=True)
    parser.add_argument("--collector-command-json", required=True)
    parser.add_argument("--invalidate-reason")
    parser.add_argument("--record-usage", action="store_true")
    parser.add_argument("--work-key")
    parser.add_argument("--provider-id")
    parser.add_argument("--input-tokens", type=int, default=0)
    parser.add_argument("--output-tokens", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.record_usage:
            result = record_dispatch_epoch_usage(
                runtime_root=args.runtime_root,
                epoch_id=args.epoch_id,
                work_key=args.work_key or "",
                provider_id=args.provider_id or "",
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
            )
        else:
            collector_command = json.loads(args.collector_command_json)
            if (
                not isinstance(collector_command, list)
                or not collector_command
                or not all(isinstance(value, str) and value for value in collector_command)
            ):
                raise ValueError("collector command JSON must be a non-empty string array")
            collector_identity = (
                "command-sha256:"
                + hashlib.sha256(
                    json.dumps(collector_command, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
            )
            result = get_or_refresh_dispatch_epoch(
                runtime_root=args.runtime_root,
                epoch_id=args.epoch_id,
                source_identity=collector_identity,
                collector=lambda: _collector(collector_command),
                invalidate_reason=args.invalidate_reason,
            )
        if args.output is not None:
            _write_json_atomic(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, ValueError, QuotaDispatchEpochError) as exc:
        print(f"QUOTA_DISPATCH_EPOCH_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 20


if __name__ == "__main__":
    raise SystemExit(main())
