"""Two-phase P8 live probe around one bounded houtai-gongren restart."""

# ruff: noqa: E402 -- standalone entrypoint adds the repository root before local imports.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.agent_runtime.xinao_mainline_canary import (
    TASK_QUEUE,
    XinaoMainlineCanaryWorkflow,
    XinaoResearchCampaignWorkflow,
)
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import Replayer


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def event_names(history) -> list[str]:
    return [EventType.Name(event.event_type) for event in history.events]


def host_to_evidence(path: Path) -> str:
    normalized = str(path.resolve()).replace("\\", "/")
    marker = "/XINAO_RESEARCH_RUNTIME/"
    position = normalized.upper().find(marker)
    if position < 0:
        raise ValueError(f"path is not inside XINAO_RESEARCH_RUNTIME: {path}")
    return "/evidence/" + normalized[position + len(marker) :]


def fact(*, fact_id: str, kind: str, ref: str, fact_hash: str) -> dict[str, str]:
    return {"fact_id": fact_id, "kind": kind, "ref": ref, "fact_hash": fact_hash}


async def prepare(args: argparse.Namespace) -> dict[str, Any]:
    client = await Client.connect(args.address, namespace=args.namespace)
    manifest = json.loads(args.p7_manifest.read_text(encoding="utf-8"))
    report = json.loads(args.p7_report.read_text(encoding="utf-8"))
    operation_id = str(manifest["intent"]["session_id"])
    mainline_id = args.workflow_id
    campaign_id = f"{args.workflow_id}-campaign"
    settlement = fact(
        fact_id="settlement",
        kind="SettlementRecord",
        ref=str(manifest["intent"]["settlement_ref"]),
        fact_hash=str(manifest["intent"]["settlement_hash"]),
    )
    lineage = fact(
        fact_id="lineage",
        kind="EvidenceManifest",
        ref=str(report["lineage_ref"]),
        fact_hash=str(report["manifest_hash"]),
    )
    mainline = await client.start_workflow(
        XinaoMainlineCanaryWorkflow.run,
        {
            "operation_id": operation_id,
            "expected_fact_ids": ["settlement", "lineage"],
            "seed_facts": [settlement],
        },
        id=mainline_id,
        task_queue=TASK_QUEUE,
    )
    source_workflow_id = args.source_grok_workflow_id
    campaign = await client.start_workflow(
        XinaoResearchCampaignWorkflow.run,
        {
            "campaign_id": campaign_id,
            "bus_state": {
                "input_path": host_to_evidence(args.grok_fanin_input),
                "params_path": "/app/materials/authority_glue/seams/integrated_bus_params.v1.json",
                "repo_root": "/app",
                "runtime_root": "/evidence",
                "workflow_id": f"{source_workflow_id}-langgraph-s0",
                "episode_phase": 3,
                "episode_max_phase": 3,
            },
        },
        id=campaign_id,
        task_queue=TASK_QUEUE,
    )
    initial_state = await mainline.query("state")
    mainline_desc = await mainline.describe()
    campaign_desc = await campaign.describe()
    prepared = {
        "schema_version": "xinao.p8_prepare.v1",
        "status": "waiting_for_bounded_worker_restart",
        "prepared_at": datetime.now(UTC).isoformat(),
        "address": args.address,
        "namespace": args.namespace,
        "task_queue": TASK_QUEUE,
        "operation_id": operation_id,
        "workflow_id": mainline_id,
        "run_id": mainline_desc.run_id,
        "campaign_workflow_id": campaign_id,
        "campaign_run_id": campaign_desc.run_id,
        "settlement_fact": settlement,
        "lineage_fact": lineage,
        "initial_state": initial_state,
        "source_grok_workflow_id": source_workflow_id,
        "grok_fanin_input": str(args.grok_fanin_input),
    }
    write_json_atomic(args.output, prepared)
    return prepared


async def replay(history, workflows: list[type]) -> dict[str, Any]:
    result = await Replayer(workflows=workflows).replay_workflow(
        history, raise_on_replay_failure=False
    )
    return {
        "event_count": len(history.events),
        "history_sha256": hashlib.sha256(history.to_json().encode("utf-8")).hexdigest(),
        "replay_failure": None if result.replay_failure is None else repr(result.replay_failure),
    }


async def stable_history(handle, *, attempts: int = 20, interval: float = 0.25):
    previous = await handle.fetch_history()
    for _ in range(attempts):
        await asyncio.sleep(interval)
        current = await handle.fetch_history()
        if len(current.events) == len(previous.events):
            return current
        previous = current
    raise AssertionError("workflow history did not stabilize inside the bounded observation window")


async def terminal_audit_workflow(
    client: Client,
    *,
    base_id: str,
    operation_id: str,
    action: str,
) -> dict[str, Any]:
    workflow_id = f"{base_id}-{action.lower()}"
    handle = await client.start_workflow(
        XinaoMainlineCanaryWorkflow.run,
        {"operation_id": operation_id, "expected_fact_ids": ["never"], "seed_facts": []},
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    await handle.query("state")
    result_status = action
    validator_rejected = None
    accepted_before = None
    accepted_after = None
    if action == "STOP":
        accepted_before = event_names(await handle.fetch_history()).count(
            "EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED"
        )
        validator_rejected = False
        try:
            await handle.execute_update(
                "control",
                {
                    "operation_id": f"{workflow_id}-invalid",
                    "action": "DROP_ALL",
                    "reason": "P8 negative validator audit",
                },
            )
        except Exception:
            validator_rejected = True
        accepted_after = event_names(await handle.fetch_history()).count(
            "EVENT_TYPE_WORKFLOW_EXECUTION_UPDATE_ACCEPTED"
        )
        if not validator_rejected or accepted_after != accepted_before:
            raise AssertionError("Update validator did not reject before history acceptance")
        await handle.execute_update(
            "control",
            {"operation_id": f"{workflow_id}-op", "action": "STOP", "reason": "P8 audit"},
        )
        result = await handle.result()
        result_status = str(result["status"])
    elif action == "CANCEL":
        await handle.cancel()
        try:
            await handle.result()
        except Exception:
            # Cancellation is the expected terminal result for this audit workflow.
            pass
    elif action == "TERMINATE":
        await handle.terminate("P8 bounded terminate audit")
    history = await handle.fetch_history()
    names = event_names(history)
    expected_event = {
        "STOP": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
        "CANCEL": "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
        "TERMINATE": "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED",
    }[action]
    if expected_event not in names:
        raise AssertionError(f"{action} terminal history event missing")
    return {
        "workflow_id": workflow_id,
        "action": action,
        "result_status": result_status,
        "terminal_event": expected_event,
        "event_count": len(names),
        "validator_rejected_before_acceptance": validator_rejected,
        "accepted_updates_before_invalid": accepted_before,
        "accepted_updates_after_invalid": accepted_after,
    }


async def finish(args: argparse.Namespace) -> dict[str, Any]:
    prepared = json.loads(args.prepare_report.read_text(encoding="utf-8"))
    restart = json.loads(args.restart_report.read_text(encoding="utf-8"))
    client = await Client.connect(args.address, namespace=args.namespace)
    mainline = client.get_workflow_handle(prepared["workflow_id"], run_id=prepared["run_id"])
    campaign = client.get_workflow_handle(
        prepared["campaign_workflow_id"], run_id=prepared["campaign_run_id"]
    )
    mainline_description = await mainline.describe()
    already_completed = mainline_description.status == WorkflowExecutionStatus.COMPLETED
    resumed_state = await mainline.query("state")
    history_before_queries = await stable_history(mainline)
    first_query = await mainline.query("state")
    second_query = await mainline.query("state")
    history_after_queries = await stable_history(mainline)
    query_is_read_only = first_query == second_query and len(history_before_queries.events) == len(
        history_after_queries.events
    )
    if already_completed:
        mainline_result = await mainline.result()
        duplicate_state = dict(mainline_result)
        paused_complete = {
            **mainline_result,
            "projection_note": "recovered from the completed durable run; PAUSE/RESUME are in control_audit",
        }
    else:
        for _ in range(max(0, 2 - int(resumed_state.get("duplicate_signals") or 0))):
            await mainline.signal("submit_fact", prepared["settlement_fact"])
        duplicate_state = await mainline.query("state")
        if not any(item["action"] == "PAUSE" for item in duplicate_state["control_audit"]):
            await mainline.execute_update(
                "control",
                {"operation_id": "p8-pause", "action": "PAUSE", "reason": "restart audit gate"},
            )
        current = await mainline.query("state")
        if not any(item["fact_id"] == "lineage" for item in current["facts"]):
            await mainline.signal("submit_fact", prepared["lineage_fact"])
        paused_complete = await mainline.query("state")
        if paused_complete["status"] != "PAUSED" or paused_complete["complete"] is not True:
            raise AssertionError("paused workflow did not retain a visible complete projection")
        if paused_complete["paused"]:
            await mainline.execute_update(
                "control",
                {"operation_id": "p8-resume", "action": "RESUME", "reason": "continue canary"},
            )
        mainline_result = await mainline.result()
    campaign_result = await campaign.result()
    mainline_history = await mainline.fetch_history()
    campaign_history = await campaign.fetch_history()
    mainline_replay = await replay(mainline_history, [XinaoMainlineCanaryWorkflow])
    campaign_replay = await replay(campaign_history, [XinaoResearchCampaignWorkflow])
    if mainline_replay["replay_failure"] or campaign_replay["replay_failure"]:
        raise AssertionError("Temporal history replay failed")

    terminal = []
    for action in ("STOP", "CANCEL", "TERMINATE"):
        terminal.append(
            await terminal_audit_workflow(
                client,
                base_id=prepared["workflow_id"],
                operation_id=prepared["operation_id"],
                action=action,
            )
        )
    checks = {
        "same_workflow_id_after_restart": mainline_result["operation_id"]
        == prepared["operation_id"],
        "same_run_id_after_restart": (await mainline.describe()).run_id == prepared["run_id"],
        "duplicate_signal_no_duplicate_fact": mainline_result["fact_count"] == 2
        and mainline_result["duplicate_signals"] == 2,
        "query_is_read_only": query_is_read_only,
        "update_validator_rejected": terminal[0]["validator_rejected_before_acceptance"] is True
        and terminal[0]["accepted_updates_after_invalid"]
        == terminal[0]["accepted_updates_before_invalid"],
        "pause_resume_audited": [item["action"] for item in mainline_result["control_audit"]]
        == ["PAUSE", "RESUME"],
        "history_replay": mainline_replay["replay_failure"] is None
        and campaign_replay["replay_failure"] is None,
        "research_campaign_gates": all(campaign_result["checks"].values()),
        "terminal_audit": len(terminal) == 3,
        "bounded_restart_verified": restart.get("status") == "verified",
    }
    if not all(checks.values()):
        raise AssertionError(
            "P8 checks failed: " + ",".join(key for key, value in checks.items() if not value)
        )
    report = {
        "schema_version": "xinao.p8_temporal_live_probe.v1",
        "status": "verified",
        "verified_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "restart": restart,
        "prepared": prepared,
        "resumed_state": resumed_state,
        "duplicate_state": duplicate_state,
        "paused_complete_state": paused_complete,
        "mainline_result": mainline_result,
        "campaign_result": campaign_result,
        "history": {
            "mainline": mainline_replay,
            "campaign": campaign_replay,
            "mainline_terminal_event": event_names(mainline_history)[-1],
            "campaign_terminal_event": event_names(campaign_history)[-1],
        },
        "terminal_audit": terminal,
        "report_hash": "",
    }
    report["report_hash"] = canonical_hash({**report, "report_hash": ""})
    write_json_atomic(args.output, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "finish"))
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--workflow-id", default="xinao-mainline-p8-canary-20260714")
    parser.add_argument("--p7-manifest", type=Path)
    parser.add_argument("--p7-report", type=Path)
    parser.add_argument("--grok-fanin-input", type=Path)
    parser.add_argument("--source-grok-workflow-id")
    parser.add_argument("--prepare-report", type=Path)
    parser.add_argument("--restart-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.phase == "prepare":
        required = (
            args.p7_manifest,
            args.p7_report,
            args.grok_fanin_input,
            args.source_grok_workflow_id,
        )
    else:
        required = (args.prepare_report, args.restart_report)
    if any(value is None or value == "" for value in required):
        raise SystemExit(f"missing required arguments for phase {args.phase}")
    result = asyncio.run(prepare(args) if args.phase == "prepare" else finish(args))
    print(json.dumps({"status": result.get("status"), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
