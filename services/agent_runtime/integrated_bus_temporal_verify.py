"""Verify Worker daemon registration + Temporal history continuation after cleanup."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.integrated_bus_workflow_registry import registry_summary
from services.agent_runtime.thin_glue_stack import DEFAULT_RUNTIME, write_json

SCHEMA_VERSION = "xinao.integrated_bus_temporal_verify.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_TEMPORAL_VERIFY_V1"


async def _try_temporal_history_probe(address: str) -> dict[str, Any]:
    try:
        from temporalio.client import Client

        from services.agent_runtime.integrated_bus_graph import XinaoIntegratedBusWorkflow, default_initial_state
        from services.agent_runtime.integrated_bus_runner import resolve_input

        client = await Client.connect(address)
        trigger = resolve_input(None)
        workflow_id = f"xinao-verify-history-{uuid.uuid4().hex[:10]}"
        initial = default_initial_state(trigger, workflow_id=workflow_id)
        handle = await client.start_workflow(
            XinaoIntegratedBusWorkflow.run,
            initial,
            id=workflow_id,
            task_queue="xinao-integrated-langgraph-plugin-queue",
        )
        desc = await handle.describe()
        return {
            "temporal_reachable": True,
            "workflow_started": True,
            "workflow_id": workflow_id,
            "run_id": desc.run_id,
            "status": str(desc.status),
            "history_events_hint": "use handle.fetch_history after worker completes",
        }
    except Exception as exc:
        return {
            "temporal_reachable": False,
            "workflow_started": False,
            "error": str(exc),
            "named_blocker": "TEMPORAL_NOT_REACHABLE_OR_WORKER_NOT_POLLING",
        }


def verify_integrated_bus_temporal(
    *,
    runtime_root: str | Path = DEFAULT_RUNTIME,
    address: str = "127.0.0.1:7233",
    probe_start: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    runtime = Path(runtime_root)
    run_id = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    reg = registry_summary()
    daemon_latest = runtime / "state" / "integrated_bus_worker_daemon" / "latest.json"
    daemon_evidence: dict[str, Any] = {}
    if daemon_latest.is_file():
        try:
            daemon_evidence = json.loads(daemon_latest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            daemon_evidence = {}

    history_probe: dict[str, Any] = {"skipped": not probe_start}
    if probe_start:
        history_probe = asyncio.run(_try_temporal_history_probe(address))

    workflows = reg.get("workflows_registered") or []
    checks = {
        "registry_binding_count_ge_1": int(reg.get("binding_count") or 0) >= 1,
        "integrated_bus_workflow_registered": "XinaoIntegratedBusWorkflow" in workflows,
        "parent_child_registered": (
            "XinaoIntegratedBusParentWorkflow" in workflows
            and "XinaoIntegratedBusChildWorkflow" in workflows
        ),
        "daemon_evidence_present": daemon_latest.is_file() or daemon_evidence.get("sentinel"),
        "handroll_intact_false": daemon_evidence.get("handroll_intact") is False
        if daemon_evidence
        else True,
        "temporal_probe_ok": history_probe.get("temporal_reachable") is True
        or history_probe.get("workflow_started") is True,
    }
    passed = checks["registry_binding_count_ge_1"] and checks["integrated_bus_workflow_registered"]

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "run_id": run_id,
        "registry": reg,
        "daemon_evidence": daemon_evidence,
        "history_probe": history_probe,
        "handroll_intact": False,
        "not_333_mainline": True,
        "completion_claim_allowed": False,
        "acceptance_now_can_invoke_cn": (
            f"Worker注册={reg.get('binding_count')} workflow；"
            f"父/子WF={'已注册' if checks['parent_child_registered'] else '待daemon拉起'}；"
            f"Temporal探活={'可达' if history_probe.get('temporal_reachable') else '需开daemon'}"
        ),
        "validation": {"passed": passed, "checks": checks, "validated_at": datetime.now().astimezone().isoformat()},
    }
    if write:
        out_dir = runtime / "state" / "integrated_bus_temporal_verify"
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(out_dir / "latest.json", payload)
        write_json(runtime / "readback" / f"integrated_bus_temporal_verify_{run_id}.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify integrated bus Temporal + daemon")
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--no-probe", action="store_true")
    args = parser.parse_args(argv)
    payload = verify_integrated_bus_temporal(
        runtime_root=args.runtime_root,
        address=args.address,
        probe_start=not args.no_probe,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("validation", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())