"""Export and replay every retained promoted-workflow history.

This is an admission/upgrade gate for the official Temporal Worker Deployment
route.  It deliberately reads histories through the Temporal SDK and replays
them with the exact workflow classes imported by the candidate worker.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.worker import Replayer

from xinao_coordination.temporal.workflow import PROMOTED_WORKFLOWS, WORKFLOW_TYPE

SCHEMA_VERSION = "xinao.temporal.promoted_history_replay.v1"


def canonical_json_bytes(value: object) -> bytes:
    """Return the stable JSON representation used by every evidence hash."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def history_set_sha256(entries: list[dict[str, Any]]) -> str:
    """Hash only immutable history identities and exported content hashes."""

    identity_set = [
        {
            "history_sha256": entry["history_sha256"],
            "run_id": entry["run_id"],
            "workflow_id": entry["workflow_id"],
        }
        for entry in sorted(entries, key=lambda item: (item["workflow_id"], item["run_id"]))
    ]
    return hashlib.sha256(canonical_json_bytes(identity_set)).hexdigest().upper()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


async def replay_all(args: argparse.Namespace) -> dict[str, Any]:
    client = await Client.connect(args.address, namespace=args.namespace)
    query = args.query or f'WorkflowType="{WORKFLOW_TYPE}"'
    executions = [
        execution
        async for execution in client.list_workflows(
            query,
            limit=args.limit,
            page_size=args.page_size,
        )
    ]
    executions.sort(key=lambda item: (item.start_time, item.id, item.run_id))
    if args.require_count is not None and len(executions) != args.require_count:
        raise RuntimeError(
            "XINAO_TEMPORAL_REPLAY_COUNT_MISMATCH: "
            f"expected={args.require_count} actual={len(executions)}"
        )

    output_dir = Path(args.output_dir).resolve()
    history_dir = output_dir / "histories"
    replayer = Replayer(workflows=list(PROMOTED_WORKFLOWS))
    entries: list[dict[str, Any]] = []

    for execution in executions:
        history = await client.get_workflow_handle(
            execution.id,
            run_id=execution.run_id,
        ).fetch_history()
        history_payload = canonical_json_bytes(json.loads(history.to_json())) + b"\n"
        history_hash = hashlib.sha256(history_payload).hexdigest().upper()
        history_path = history_dir / f"{execution.run_id}.json"
        _write_atomic(history_path, history_payload)

        replay = await replayer.replay_workflow(history, raise_on_replay_failure=False)
        failure = None if replay.replay_failure is None else repr(replay.replay_failure)
        entries.append(
            {
                "event_count": len(history.events),
                "history_path": str(history_path),
                "history_sha256": history_hash,
                "replay_failure": failure,
                "run_id": execution.run_id,
                "start_time": execution.start_time.isoformat(),
                "status": execution.status.name,
                "workflow_id": execution.id,
            }
        )

    failed = [entry for entry in entries if entry["replay_failure"] is not None]
    report = {
        "schema_version": SCHEMA_VERSION,
        "verified_at": datetime.now(UTC).isoformat(),
        "address": args.address,
        "namespace": args.namespace,
        "query": query,
        "workflow_type": WORKFLOW_TYPE,
        "history_count": len(entries),
        "passed": len(entries) - len(failed),
        "failed": len(failed),
        "ok": not failed and bool(entries),
        "history_set_sha256": history_set_sha256(entries),
        "entries": entries,
    }
    report_payload = canonical_json_bytes(report) + b"\n"
    _write_atomic(output_dir / "replay_report.json", report_payload)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--query")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--require-count", type=int)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    report = asyncio.run(replay_all(parse_args()))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
