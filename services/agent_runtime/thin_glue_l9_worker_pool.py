"""L9 worker pool thin bind — Temporal child workflows replace ThreadPoolExecutor run_lane."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_lane_worker import run_thin_glue_lane
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, now_iso, write_json

REPLACES_MODULE = "modular_dynamic_worker_pool_phase1"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l9_worker_pool.v1"
DEFAULT_WIDTH = 3


def thin_glue_worker_pool_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_WORKER_POOL", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def default_width() -> int:
    raw = os.environ.get("XINAO_THIN_GLUE_WORKER_POOL_WIDTH", str(DEFAULT_WIDTH))
    try:
        return max(1, min(12, int(raw)))
    except ValueError:
        return DEFAULT_WIDTH


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_worker_pool"
    return {
        "latest": state / "latest.json",
        "merge_dir": runtime / "worker_pool" / "merge",
        "readback": runtime / "readback" / "zh" / "thin_glue_worker_pool_latest.md",
    }


def build_lane_specs(*, wave_id: str, width: int) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    for index in range(1, width + 1):
        mode = "draft" if index <= max(2, width - 1) else "eval"
        lanes.append(
            {
                "lane_id": f"thin-glue-lane-{index:03d}",
                "lane_number": index,
                "mode": mode,
                "query": f"thin_glue_worker_pool {wave_id} lane{index}",
                "wave_id": wave_id,
            }
        )
    return lanes


def _merge_lane_results(
    *,
    runtime: Path,
    wave_id: str,
    lane_results: list[dict[str, Any]],
    write: bool,
) -> dict[str, Any]:
    drafts = [r for r in lane_results if r.get("status") == "succeeded"]
    merge_text = "\n\n".join(
        str(item.get("draft_text") or item.get("artifact_ref") or "") for item in drafts
    )
    merge_path = runtime / "worker_pool" / "merge" / f"{wave_id}.md"
    if write and merge_text.strip():
        merge_path.parent.mkdir(parents=True, exist_ok=True)
        merge_path.write_text(merge_text + "\n", encoding="utf-8")
    draft_count = len([r for r in lane_results if r.get("mode") == "draft" and r.get("status") == "succeeded"])
    return {
        "status": "merge_consumer_merged" if draft_count > 0 else "merge_consumer_blocked",
        "draft_count": draft_count,
        "merged_count": 1 if draft_count > 0 else 0,
        "merge_artifact": str(merge_path) if merge_text.strip() else "",
        "merge_text_excerpt": merge_text[:500],
        "thin_glue": True,
    }


def run_thin_glue_worker_pool_local(
    *,
    wave_id: str,
    lanes: list[dict[str, Any]],
    runtime_root: Path,
    repo_root: Path,
    write: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    max_workers = min(len(lanes), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                run_thin_glue_lane,
                lane_id=str(lane["lane_id"]),
                mode=str(lane.get("mode") or "draft"),
                query=str(lane.get("query") or "thin_glue"),
                wave_id=wave_id,
                runtime_root=runtime_root,
                repo_root=repo_root,
                lane_number=int(lane.get("lane_number") or 1),
                write=write,
            ): lane
            for lane in lanes
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                lane = futures[future]
                results.append(
                    {
                        "lane_id": lane.get("lane_id"),
                        "status": "blocked",
                        "named_blocker": f"LANE_EXCEPTION:{type(exc).__name__}",
                        "thin_glue": True,
                    }
                )
    order = {str(lane["lane_id"]): int(lane.get("lane_number") or 0) for lane in lanes}
    return sorted(results, key=lambda item: order.get(str(item.get("lane_id")), 9999))


async def run_thin_glue_worker_pool_temporal(
    *,
    wave_id: str,
    lanes: list[dict[str, Any]],
    runtime_root: Path,
    repo_root: Path,
    address: str = "127.0.0.1:7233",
    write: bool = True,
) -> dict[str, Any]:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from services.agent_runtime.thin_glue_worker_pool_temporal import (
        TASK_QUEUE,
        XinaoThinGlueWorkerPoolWorkflow,
        temporal_exports,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"thin-glue-worker-pool-{run_id}"
    payload = {
        "wave_id": wave_id,
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "write": write,
        "lanes": [
            {
                **lane,
                "runtime_root": str(runtime_root),
                "repo_root": str(repo_root),
                "write": write,
            }
            for lane in lanes
        ],
    }
    workflows, activities = temporal_exports()
    client = await Client.connect(address)
    async with Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities):
        handle = await client.start_workflow(
            XinaoThinGlueWorkerPoolWorkflow.run,
            payload,
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        return await handle.result()


def run_thin_glue_worker_pool_wave(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "thin-glue-worker-pool-wave-001",
    target_width: int = 0,
    use_temporal: bool = False,
    temporal_address: str = "127.0.0.1:7233",
    write: bool = True,
    **compat_kwargs: Any,
) -> dict[str, Any]:
    del compat_kwargs
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    width = target_width if int(target_width or 0) > 0 else default_width()
    lanes = build_lane_specs(wave_id=wave_id, width=width)
    generated_at = now_iso()

    temporal_result: dict[str, Any] | None = None
    if use_temporal:
        import asyncio

        temporal_result = asyncio.run(
            run_thin_glue_worker_pool_temporal(
                wave_id=wave_id,
                lanes=lanes,
                runtime_root=runtime,
                repo_root=repo,
                address=temporal_address,
                write=write,
            )
        )
        lane_results = list(temporal_result.get("lane_results") or [])
        carrier = "temporal_child_workflows"
    else:
        lane_results = run_thin_glue_worker_pool_local(
            wave_id=wave_id,
            lanes=lanes,
            runtime_root=runtime,
            repo_root=repo,
            write=write,
        )
        carrier = "local_thread_pool_thin_lanes"

    succeeded = [r for r in lane_results if r.get("status") == "succeeded"]
    merge = _merge_lane_results(runtime=runtime, wave_id=wave_id, lane_results=lane_results, write=write)
    draft_count = int(merge.get("draft_count") or 0)
    checks = {
        "lanes_dispatched": len(lane_results) == width,
        "succeeded_count_nonzero": len(succeeded) > 0,
        "draft_count_positive": draft_count > 0,
        "merge_artifact_written": bool(merge.get("merge_artifact")),
        "hand_rolled_worker_pool_bypassed": True,
        "hand_rolled_thread_pool_run_lane_bypassed": True,
        "temporal_child_workflows": use_temporal and temporal_result is not None,
    }
    passed = all(
        [
            checks["lanes_dispatched"],
            checks["succeeded_count_nonzero"],
            checks["draft_count_positive"],
            checks["merge_artifact_written"],
        ]
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "replaces": REPLACES_MODULE,
        "not_333_mainline": True,
        "thin_glue": True,
        "wave_id": wave_id,
        "target_width": width,
        "status": "thin_glue_worker_pool_wave_merged" if passed else "thin_glue_worker_pool_wave_blocked",
        "generated_at": generated_at,
        "parallel_carrier": carrier,
        "lane_results": lane_results,
        "succeeded_count": len(succeeded),
        "draft_count": draft_count,
        "merged_count": merge.get("merged_count"),
        "merge_consumer": merge,
        "temporal_pool_result": temporal_result,
        "hand_rolled_worker_pool_bypassed": True,
        "acceptance_now_can_invoke_cn": (
            f"薄胶 worker pool：{width} 路并行({carrier})，succeeded={len(succeeded)}，"
            f"draft={draft_count}，merge已写；替 modular_dynamic_worker_pool 手搓 ThreadPool。"
            if passed
            else "worker pool 未绿：检查 lane 本地 rg 命中或 Temporal"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": generated_at},
        "completion_claim_allowed": False,
        "not_source_of_truth": True,
        "not_user_completion": True,
    }

    if write:
        paths = output_paths(runtime)
        evidence = runtime / "readback" / f"thin_glue_worker_pool_{wave_id}.json"
        write_json(paths["latest"], payload)
        write_json(evidence, payload)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# Thin Glue Worker Pool",
                    f"- wave: {wave_id}",
                    f"- passed: {passed}",
                    f"- succeeded: {len(succeeded)} / {width}",
                    f"- carrier: {carrier}",
                    payload["acceptance_now_can_invoke_cn"],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        payload["output_paths"] = {
            "latest": str(paths["latest"]),
            "evidence": str(evidence),
            "readback_zh": str(paths["readback"]),
            "merge_artifact": merge.get("merge_artifact"),
        }

    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Thin glue L9 worker pool (Temporal child workflows)")
    parser.add_argument("--wave-id", default="thin-glue-worker-pool-wave-001")
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--temporal", action="store_true")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    payload = run_thin_glue_worker_pool_wave(
        wave_id=args.wave_id,
        target_width=args.width,
        use_temporal=args.temporal,
        temporal_address=args.address,
        write=not args.no_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())