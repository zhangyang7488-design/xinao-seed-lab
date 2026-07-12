"""Submit one existing 333 integrated-bus workflow with a container-visible input ref."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.client import Client


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


async def _run(args: argparse.Namespace) -> int:
    workflow_id = args.workflow_id or f"xinao-integrated-bus-recovery-{uuid.uuid4().hex[:12]}"
    initial = {
        "input_path": args.input_ref,
        "params_path": args.params_ref,
        "repo_root": args.repo_root,
        "runtime_root": args.runtime_root,
        "workflow_id": workflow_id,
        "episode_phase": args.episode_phase,
        "episode_max_phase": args.episode_max_phase,
        "react_loop_count": 0,
        "heal_retry_count": 0,
        "heal_failed_checks": [],
    }
    evidence = {
        "schema_version": "xinao.333.temporal_recovery_canary.v1",
        "workflow_id": workflow_id,
        "task_queue": args.task_queue,
        "address": args.address,
        "input_ref": args.input_ref,
        "params_ref": args.params_ref,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "starting",
    }
    evidence_path = Path(args.evidence)
    _write_json(evidence_path, evidence)

    client = await Client.connect(args.address, namespace=args.namespace)
    handle = await client.start_workflow(
        "XinaoIntegratedBusWorkflow",
        initial,
        id=workflow_id,
        task_queue=args.task_queue,
    )
    evidence.update({"status": "running", "run_id": handle.first_execution_run_id})
    _write_json(evidence_path, evidence)
    print(json.dumps({"status": "running", "workflow_id": workflow_id}, ensure_ascii=False), flush=True)

    try:
        result = await asyncio.wait_for(handle.result(), timeout=args.timeout_seconds)
    except TimeoutError:
        description = await handle.describe()
        evidence.update(
            {
                "status": "timeout",
                "temporal_status": str(description.status),
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_json(evidence_path, evidence)
        print(json.dumps({"status": "timeout", "workflow_id": workflow_id}, ensure_ascii=False))
        return 2
    except Exception as exc:
        evidence.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_json(evidence_path, evidence)
        print(
            json.dumps(
                {"status": "failed", "workflow_id": workflow_id, "error_type": type(exc).__name__},
                ensure_ascii=False,
            )
        )
        return 1

    result_dict = dict(result) if isinstance(result, dict) else {"value_type": type(result).__name__}
    evidence.update(
        {
            "status": "completed",
            "finished_at": datetime.now(UTC).isoformat(),
            "result_keys": sorted(result_dict),
            "parallel_width_n": int(result_dict.get("parallel_width_n") or 0),
            "parallel_succeeded": int(result_dict.get("parallel_succeeded") or 0),
            "parallel_semantic": str(result_dict.get("parallel_semantic") or ""),
            "fanin_ok": result_dict.get("fanin_ok") is True,
            "promotion_gate_passed": result_dict.get("promotion_gate_passed") is True,
        }
    )
    _write_json(evidence_path, evidence)
    print(
        json.dumps(
            {
                "status": "completed",
                "workflow_id": workflow_id,
                "parallel_width_n": evidence["parallel_width_n"],
                "parallel_succeeded": evidence["parallel_succeeded"],
                "parallel_semantic": evidence["parallel_semantic"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="naijiu-shiwu:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--task-queue", default="xinao-integrated-langgraph-plugin-queue")
    parser.add_argument("--workflow-id", default="")
    parser.add_argument(
        "--input-ref",
        default="/evidence/specs/p0_backend_autonomous_construction_blueprint_full_20260708.txt",
    )
    parser.add_argument(
        "--params-ref",
        default="/app/materials/authority_glue/seams/integrated_bus_params.v1.json",
    )
    parser.add_argument("--repo-root", default="/app")
    parser.add_argument("--runtime-root", default="/evidence")
    parser.add_argument("--episode-phase", type=int, default=3)
    parser.add_argument("--episode-max-phase", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--evidence", required=True)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
