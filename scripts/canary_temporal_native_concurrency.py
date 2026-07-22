"""Live canary for Temporal-native queue concurrency and stable ID semantics."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

SCHEMA_VERSION = "xinao.temporal_native_concurrency_canary.v1"
SENTINEL = "SENTINEL:XINAO_TEMPORAL_NATIVE_CONCURRENCY_CANARY_V1"
ACTIVITY_NAME = "xinao_temporal_native_concurrency_canary_activity"
WINDOWLESS_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@workflow.defn(name="XinaoTemporalNativeConcurrencyCanaryWorkflow")
class TemporalNativeConcurrencyCanaryWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, str]) -> dict[str, Any]:
        return await workflow.execute_activity(
            ACTIVITY_NAME,
            payload,
            start_to_close_timeout=timedelta(seconds=15),
        )


class _CanaryActivities:
    def __init__(self, *, worker_label: str) -> None:
        self.worker_label = worker_label

    @activity.defn(name=ACTIVITY_NAME)
    async def run(self, payload: dict[str, str]) -> dict[str, Any]:
        mode = str(payload.get("mode") or "")
        if mode not in {"overlap", "duplicate"}:
            raise ValueError(f"unsupported canary mode: {mode}")
        started_at = time.time()
        await asyncio.sleep(0.4)
        return {
            "activity_id": activity.info().activity_id,
            "label": str(payload.get("label") or ""),
            "mode": mode,
            "worker_label": self.worker_label,
            "started_unix": started_at,
            "finished_unix": time.time(),
        }


async def _run_worker(
    *,
    address: str,
    task_queue: str,
    worker_label: str,
    ready_file: Path,
    stop_file: Path,
) -> None:
    client = await Client.connect(address)
    canary_activities = _CanaryActivities(worker_label=worker_label)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[TemporalNativeConcurrencyCanaryWorkflow],
        activities=[canary_activities.run],
        identity=worker_label,
        max_concurrent_activities=1,
    )
    async with worker:
        ready_file.write_text(
            json.dumps({"worker_label": worker_label, "task_queue": task_queue}) + "\n",
            encoding="utf-8",
        )
        while not stop_file.exists():
            await asyncio.sleep(0.05)


async def _wait_for_worker_readiness(
    processes: list[subprocess.Popen[bytes]],
    ready_files: list[Path],
    log_files: list[Path],
    *,
    timeout_seconds: float = 15,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while not all(path.is_file() for path in ready_files):
        exited = [process.poll() for process in processes]
        if any(code is not None for code in exited):
            logs = [
                path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
                for path in log_files
            ]
            raise RuntimeError(f"canary worker exited before readiness: {exited}; logs={logs}")
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("canary workers did not enter polling state")
        await asyncio.sleep(0.05)


def _start_worker_processes(
    *,
    address: str,
    task_queue: str,
    state_dir: Path,
) -> tuple[
    list[subprocess.Popen[bytes]],
    list[Path],
    list[Path],
    list[Any],
]:
    script_path = Path(__file__).resolve()
    processes: list[subprocess.Popen[bytes]] = []
    ready_files: list[Path] = []
    stop_files: list[Path] = []
    log_paths: list[Path] = []
    log_handles: list[Any] = []
    for index in range(2):
        worker_label = f"worker-{index + 1}"
        ready_file = state_dir / f"{worker_label}.ready.json"
        stop_file = state_dir / f"{worker_label}.stop"
        log_path = state_dir / f"{worker_label}.log"
        log_handle = log_path.open("wb")
        command = [
            sys.executable,
            str(script_path),
            "--worker",
            "--address",
            address,
            "--task-queue",
            task_queue,
            "--worker-label",
            worker_label,
            "--ready-file",
            str(ready_file),
            "--stop-file",
            str(stop_file),
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=WINDOWLESS_CREATIONFLAGS,
        )
        processes.append(process)
        ready_files.append(ready_file)
        stop_files.append(stop_file)
        log_paths.append(log_path)
        log_handles.append(log_handle)
    return processes, ready_files, stop_files, log_paths, log_handles


def _stop_worker_processes(
    processes: list[subprocess.Popen[bytes]],
    stop_files: list[Path],
    log_handles: list[Any],
) -> None:
    for path in stop_files:
        path.touch()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
    for handle in log_handles:
        handle.close()


async def _exercise_temporal(
    *,
    client: Client,
    task_queue: str,
    canary_generation: str,
) -> dict[str, Any]:
    overlap_ids = [f"xinao-temporal-overlap-{canary_generation}-{index}" for index in range(2)]
    overlap_handles = await asyncio.gather(
        *(
            client.start_workflow(
                TemporalNativeConcurrencyCanaryWorkflow.run,
                {"mode": "overlap", "label": workflow_id},
                id=workflow_id,
                task_queue=task_queue,
                id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            for workflow_id in overlap_ids
        )
    )
    overlap_results = await asyncio.gather(*(handle.result() for handle in overlap_handles))
    overlap_descriptions = await asyncio.gather(*(handle.describe() for handle in overlap_handles))

    stable_id = f"xinao-temporal-stable-{canary_generation}"
    duplicate_payload = {"mode": "duplicate", "label": stable_id}
    first_handle = await client.start_workflow(
        TemporalNativeConcurrencyCanaryWorkflow.run,
        duplicate_payload,
        id=stable_id,
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    joined_handle = await client.start_workflow(
        TemporalNativeConcurrencyCanaryWorkflow.run,
        duplicate_payload,
        id=stable_id,
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    first_result, joined_result = await asyncio.gather(
        first_handle.result(),
        joined_handle.result(),
    )
    first_description, joined_description = await asyncio.gather(
        first_handle.describe(),
        joined_handle.describe(),
    )

    closed_duplicate_rejected = False
    closed_duplicate_run_id = ""
    closed_duplicate_result: dict[str, Any] = {}
    try:
        await client.start_workflow(
            TemporalNativeConcurrencyCanaryWorkflow.run,
            duplicate_payload,
            id=stable_id,
            task_queue=task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError as exc:
        closed_duplicate_rejected = True
        closed_duplicate_run_id = str(exc.run_id or "")
        prior_handle = client.get_workflow_handle(stable_id, run_id=exc.run_id or None)
        closed_duplicate_result = dict(await prior_handle.result())

    overlap_intervals = [
        (float(item["started_unix"]), float(item["finished_unix"])) for item in overlap_results
    ]
    intervals_overlap = max(start for start, _ in overlap_intervals) < min(
        end for _, end in overlap_intervals
    )
    distinct_workers = len({str(item["worker_label"]) for item in overlap_results}) == 2
    stable_run_same = first_description.run_id == joined_description.run_id
    stable_result_same = first_result == joined_result == closed_duplicate_result
    checks = {
        "two_worker_processes_consumed_distinct_work": distinct_workers,
        "two_distinct_workflows_overlapped": intervals_overlap,
        "stable_open_duplicate_joined_one_run": stable_run_same,
        "stable_duplicate_executed_once": first_result == joined_result,
        "closed_duplicate_rejected": closed_duplicate_rejected,
        "closed_duplicate_prior_result_readable": stable_result_same,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "task_queue": task_queue,
        "overlap": {
            "workflow_ids": overlap_ids,
            "run_ids": [description.run_id for description in overlap_descriptions],
            "activity_results": overlap_results,
            "intervals_overlap": intervals_overlap,
            "distinct_worker_processes": distinct_workers,
        },
        "stable_identity": {
            "workflow_id": stable_id,
            "first_run_id": first_description.run_id,
            "joined_run_id": joined_description.run_id,
            "closed_duplicate_run_id": closed_duplicate_run_id,
            "activity_id": str(first_result.get("activity_id") or ""),
            "closed_duplicate_rejected": closed_duplicate_rejected,
        },
        "validation": {"passed": all(checks.values()), "checks": checks},
    }


async def _run_canary(*, address: str, state_root: Path) -> dict[str, Any]:
    client = await Client.connect(address)
    canary_generation = uuid.uuid4().hex[:12]
    task_queue = f"xinao-temporal-native-canary-{canary_generation}"
    state_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{canary_generation}-",
        dir=state_root,
    ) as raw_state_dir:
        state_dir = Path(raw_state_dir)
        (
            processes,
            ready_files,
            stop_files,
            log_paths,
            log_handles,
        ) = _start_worker_processes(
            address=address,
            task_queue=task_queue,
            state_dir=state_dir,
        )
        try:
            await _wait_for_worker_readiness(processes, ready_files, log_paths)
            payload = await _exercise_temporal(
                client=client,
                task_queue=task_queue,
                canary_generation=canary_generation,
            )
        finally:
            _stop_worker_processes(processes, stop_files, log_handles)
    payload["address"] = address
    payload["worker_process_exit_codes"] = [process.returncode for process in processes]
    payload["validation"]["checks"]["worker_processes_exited_cleanly"] = all(
        process.returncode == 0 for process in processes
    )
    payload["validation"]["passed"] = all(payload["validation"]["checks"].values())
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded live Temporal concurrency and Workflow ID canary"
    )
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument(
        "--state-root",
        default=r"D:\XINAO_RESEARCH_RUNTIME\state\temporal_native_concurrency_canary",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--task-queue", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-label", default="", help=argparse.SUPPRESS)
    parser.add_argument("--ready-file", default="", help=argparse.SUPPRESS)
    parser.add_argument("--stop-file", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        asyncio.run(
            _run_worker(
                address=args.address,
                task_queue=args.task_queue,
                worker_label=args.worker_label,
                ready_file=Path(args.ready_file),
                stop_file=Path(args.stop_file),
            )
        )
        return 0
    payload = asyncio.run(_run_canary(address=args.address, state_root=Path(args.state_root)))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
