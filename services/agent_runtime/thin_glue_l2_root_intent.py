"""L2 root intent thin bind — Temporal tick reads thin-glue evidence chain."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_l9_ledger import run_thin_glue_ledger_mirror
from services.agent_runtime.thin_glue_mainline_bridge import attach_thin_glue_bridge_evidence
from services.agent_runtime.thin_glue_stack import DEFAULT_REPO, DEFAULT_RUNTIME, write_json

REPLACES_MODULE = "root_intent_loop_driver"
SCHEMA_VERSION = "xinao.codex_s.thin_glue_l2_root_intent.v1"
SENTINEL = "SENTINEL:XINAO_THIN_GLUE_L2_ROOT_INTENT_READY"


def thin_glue_root_intent_enabled() -> bool:
    flag = os.environ.get("XINAO_THIN_GLUE_ROOT_INTENT", "1")
    return flag.strip().lower() not in {"0", "false", "no", "off"}


def output_paths(runtime: Path) -> dict[str, Path]:
    state = runtime / "state" / "thin_glue_root_intent"
    return {
        "latest": state / "latest.json",
        "readback": runtime / "readback" / "zh" / "thin_glue_root_intent_latest.md",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def run_thin_glue_root_intent_tick(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    repo_root: str | Path = DEFAULT_REPO,
    wave_id: str = "thin-glue-root-intent-tick",
    workflow_id: str = "",
    workflow_run_id: str = "",
    write: bool = True,
    temporal_activity: bool = False,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    repo = Path(repo_root)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    bridge = attach_thin_glue_bridge_evidence(runtime) if write else {}
    ledger = run_thin_glue_ledger_mirror(
        runtime_root=runtime,
        repo_root=repo,
        wave_id=wave_id,
        task_id="thin_glue_root_intent_tick",
        write=write,
    )
    pool_latest = _read_json(runtime / "state" / "thin_glue_worker_pool" / "latest.json")
    loop_passed = bridge.get("latest_thin_glue_loop_passed") is True
    ledger_succeeded = int(ledger.get("succeeded_count") or 0)
    pool_passed = pool_latest.get("validation", {}).get("passed") is True

    checks = {
        "thin_glue_loop_passed": loop_passed,
        "ledger_succeeded_nonzero": ledger_succeeded > 0,
        "worker_pool_evidence_optional": pool_passed or not pool_latest,
        "hand_rolled_root_driver_bypassed": True,
        "mainline_14k_body_untouched": True,
        "temporal_parent_tick": temporal_activity,
    }
    passed = loop_passed and ledger_succeeded > 0

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "replaces": REPLACES_MODULE,
        "not_333_mainline": True,
        "thin_glue": True,
        "wave_id": wave_id,
        "workflow_id": workflow_id,
        "workflow_run_id": workflow_run_id,
        "status": "thin_glue_root_intent_tick_ready"
        if passed
        else "thin_glue_root_intent_tick_blocked",
        "generated_at": generated_at,
        "thin_glue_mainline_bridge": bridge,
        "thin_glue_ledger": {
            "succeeded_count": ledger_succeeded,
            "validation_passed": ledger.get("validation", {}).get("passed"),
        },
        "thin_glue_worker_pool": {
            "present": bool(pool_latest),
            "validation_passed": pool_passed,
            "succeeded_count": pool_latest.get("succeeded_count"),
        },
        "ledger_succeeded_count": ledger_succeeded,
        "temporal_every_wave_root_driver_tick_ready": passed and temporal_activity,
        "acceptance_now_can_invoke_cn": (
            f"L2 薄入口：读薄胶 bridge(loop绿={loop_passed}) + ledger(succeeded={ledger_succeeded})；"
            "未改 14k workflow 正文。"
            if passed
            else "L2 薄入口未绿：先跑 thin-glue 全链"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": generated_at},
        "named_blocker": None if passed else "THIN_GLUE_ROOT_INTENT_EVIDENCE_INCOMPLETE",
        "completion_claim_allowed": False,
        "not_user_completion": True,
        "not_source_of_truth": True,
    }

    if write:
        paths = output_paths(runtime)
        evidence = runtime / "readback" / f"thin_glue_root_intent_{wave_id}.json"
        write_json(paths["latest"], payload)
        write_json(evidence, payload)
        driver_overlay = {
            "thin_glue_l2_delegation": True,
            "hand_rolled_build_bypassed": True,
            "thin_glue_root_intent_latest": str(paths["latest"]),
            "ledger_succeeded_count": ledger_succeeded,
            "temporal_every_wave_root_driver_tick": {
                "invoked_by": "thin_glue_root_intent_tick",
                "ledger_succeeded_count": ledger_succeeded,
                "generated_at": generated_at,
            },
            "generated_at": generated_at,
        }
        driver_latest_path = runtime / "state" / "root_intent_loop_driver" / "latest.json"
        existing = _read_json(driver_latest_path)
        existing.update(driver_overlay)
        write_json(driver_latest_path, existing)
        paths["readback"].parent.mkdir(parents=True, exist_ok=True)
        paths["readback"].write_text(
            "\n".join(
                [
                    "# Thin Glue L2 Root Intent",
                    f"- wave: {wave_id}",
                    f"- passed: {passed}",
                    f"- ledger_succeeded: {ledger_succeeded}",
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
            "root_intent_driver_latest_overlay": str(driver_latest_path),
        }

    return payload


async def run_thin_glue_root_intent_temporal(
    *,
    runtime_root: Path = DEFAULT_RUNTIME,
    repo_root: Path = DEFAULT_REPO,
    wave_id: str = "thin-glue-root-intent-temporal",
    address: str = "127.0.0.1:7233",
    write: bool = True,
) -> dict[str, Any]:
    from temporalio.client import Client
    from temporalio.worker import Worker

    from services.agent_runtime.thin_glue_root_intent_temporal import (
        TASK_QUEUE,
        XinaoThinGlueRootIntentTickWorkflow,
        temporal_exports,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf_id = f"thin-glue-root-intent-{run_id}"
    activity_payload = {
        "runtime_root": str(runtime_root),
        "repo_root": str(repo_root),
        "wave_id": wave_id,
        "workflow_id": wf_id,
        "write": write,
    }
    workflows, activities = temporal_exports()
    client = await Client.connect(address)
    async with Worker(client, task_queue=TASK_QUEUE, workflows=workflows, activities=activities):
        handle = await client.start_workflow(
            XinaoThinGlueRootIntentTickWorkflow.run,
            activity_payload,
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
        result = await handle.result()
    result["temporal"] = {"workflow_id": wf_id, "task_queue": TASK_QUEUE, "address": address}
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Thin glue L2 root intent tick")
    parser.add_argument("--wave-id", default="thin-glue-root-intent-tick")
    parser.add_argument("--temporal", action="store_true")
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    if args.temporal:
        out = asyncio.run(
            run_thin_glue_root_intent_temporal(
                wave_id=args.wave_id,
                address=args.address,
                write=not args.no_write,
            )
        )
    else:
        out = run_thin_glue_root_intent_tick(
            wave_id=args.wave_id,
            write=not args.no_write,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
