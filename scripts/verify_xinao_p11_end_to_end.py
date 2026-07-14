"""Run the P11 end-to-end canary and emit one content-addressed evidence pack."""

# ruff: noqa: E402 -- standalone entrypoint bootstraps both repository roots.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_ROOT = REPO_ROOT / "xinao_discovery"
for candidate in (str(REPO_ROOT), str(XINAO_ROOT / "src")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from services.agent_runtime.xinao_mainline_canary import (
    TASK_QUEUE,
    XinaoMainlineCanaryWorkflow,
)
from temporalio.client import Client
from temporalio.worker import Replayer


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_text(command: list[str], *, check: bool = True, timeout: int = 600) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed with {completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def postgres_read(database: str, sql: str) -> str:
    return run_text(
        [
            "docker",
            "exec",
            "shiwu-ku",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "temporal",
            "-d",
            database,
            "-Atc",
            sql,
        ]
    )[1]


async def replay(history) -> dict[str, Any]:
    result = await Replayer(workflows=[XinaoMainlineCanaryWorkflow]).replay_workflow(
        history, raise_on_replay_failure=False
    )
    return {
        "event_count": len(history.events),
        "history_sha256": hashlib.sha256(history.to_json().encode()).hexdigest(),
        "replay_failure": None if result.replay_failure is None else repr(result.replay_failure),
    }


async def workflow_checks(client: Client, prepared: dict[str, Any]) -> dict[str, Any]:
    positive_id = "xinao-mainline-p11-positive-20260714"
    positive = await client.start_workflow(
        XinaoMainlineCanaryWorkflow.run,
        {
            "operation_id": "xinao-mainline-20260714T014700-p11-positive",
            "expected_fact_ids": ["settlement", "lineage"],
            "seed_facts": [prepared["settlement_fact"]],
        },
        id=positive_id,
        task_queue=TASK_QUEUE,
    )
    await positive.signal("submit_fact", prepared["lineage_fact"])
    positive_result = await positive.result()
    positive_history = await positive.fetch_history()
    positive_replay = await replay(positive_history)

    conflict_id = "xinao-mainline-p11-conflict-20260714"
    conflict = await client.start_workflow(
        XinaoMainlineCanaryWorkflow.run,
        {
            "operation_id": "xinao-mainline-20260714T014700-p11-conflict",
            "expected_fact_ids": ["never"],
            "seed_facts": [prepared["settlement_fact"]],
        },
        id=conflict_id,
        task_queue=TASK_QUEUE,
    )
    await conflict.signal("submit_fact", prepared["settlement_fact"])
    conflicting = {**prepared["settlement_fact"], "fact_hash": "0" * 64}
    await conflict.signal("submit_fact", conflicting)
    conflict_result = await conflict.result()
    conflict_history = await conflict.fetch_history()
    conflict_replay = await replay(conflict_history)
    return {
        "positive": {
            "workflow_id": positive_id,
            "run_id": (await positive.describe()).run_id,
            "result": positive_result,
            "replay": positive_replay,
        },
        "duplicate_conflict": {
            "workflow_id": conflict_id,
            "run_id": (await conflict.describe()).run_id,
            "result": conflict_result,
            "replay": conflict_replay,
        },
    }


async def run_workflow_checks(prepared: dict[str, Any]) -> dict[str, Any]:
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    return await workflow_checks(client, prepared)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--p10-grok-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    paths = {
        "formal": root / "p3_p5_formal_registration" / "formal_vertical_registration.json",
        "p5_candidate": root / "p5_validation_court" / "candidate_validation_report.json",
        "p7_lineage": root / "p7_lineage_dvc" / "lineage_delivery_probe_report.json",
        "p8_prepare": root / "p8_temporal" / "prepare_report.json",
        "p8_live": root / "p8_temporal" / "live_probe_report.json",
        "p9_projection": root / "p9_cli_eval" / "operator_projection_probe_report.json",
        "p9_promptfoo": root / "p9_cli_eval" / "agent_admission_promptfoo_after_grok_fix.json",
        "p10_backup": root / "p10_backup_restore" / "backup_manifest.json",
        "p10_restore": root / "p10_backup_restore" / "isolated_restore_report.json",
        "p10_grok": args.p10_grok_result.resolve(),
    }
    loaded = {key: load_object(path) for key, path in paths.items()}
    domain_output = args.output.parent / "p11_domain_checks.json"
    run_text(
        [
            "uv",
            "run",
            "--project",
            str(XINAO_ROOT),
            "--frozen",
            "python",
            str(XINAO_ROOT / "scripts" / "probe" / "p11_domain_checks.py"),
            "--expected-report",
            str(paths["p5_candidate"]),
            "--output",
            str(domain_output),
        ],
        timeout=1200,
    )
    domain = load_object(domain_output)

    unauthorized_code, _, unauthorized_error = run_text(
        [
            "docker",
            "exec",
            "shiwu-ku",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "VERBOSITY=verbose",
            "-U",
            "temporal",
            "-d",
            "xinao_discovery_domain_canary_20260714",
            "-c",
            "set role xinao_discovery_projection_reader; insert into domain_event default values;",
        ],
        check=False,
    )
    formal_rows = postgres_read(
        "xinao_discovery_domain_canary_20260714",
        "select event_id::text || '|' || event_hash || '|' || correlation_id || '|' || "
        "workflow_id || '|' || run_id from domain_event order by aggregate_type, aggregate_id, "
        "aggregate_version;",
    )
    formal_reverse_hash = hashlib.sha256(formal_rows.encode()).hexdigest()
    formal_count = int(
        postgres_read(
            "xinao_discovery_domain_canary_20260714", "select count(*) from domain_event;"
        )
    )
    outbox_count = int(
        postgres_read(
            "xinao_discovery_domain_canary_20260714",
            "select count(*) from transactional_outbox;",
        )
    )

    workflows = asyncio.run(run_workflow_checks(loaded["p8_prepare"]))
    positive = workflows["positive"]
    conflict = workflows["duplicate_conflict"]
    reverse_links = dict(loaded["p7_lineage"].get("reverse_links") or {})
    p10_lane = loaded["p10_grok"]["result"]["grok_lanes"][0]
    p10_child = loaded["p10_grok"]["result"]["langgraph_children"][0]
    restored_hash = loaded["p10_restore"]["restore"]["formal_event_hash"]
    checks = {
        "positive_vertical_registered": loaded["formal"].get("status") == "verified"
        and formal_count == loaded["formal"].get("registered_count") == 11
        and outbox_count == 11,
        "fresh_positive_temporal_completed": positive["result"]["status"] == "COMPLETED"
        and positive["result"]["fact_count"] == 2
        and positive["replay"]["replay_failure"] is None,
        "fresh_no_action_reproduced": domain["checks"]["no_action"] is True
        and domain["checks"]["no_action_hash_matches_p5"] is True,
        "unauthorized_write_rejected": unauthorized_code != 0 and "42501" in unauthorized_error,
        "future_leakage_rejected": domain["checks"]["future_leakage_rejected"] is True,
        "duplicate_and_conflict_audited": conflict["result"]["status"] == "CONFLICTED"
        and conflict["result"]["fact_count"] == 1
        and conflict["result"]["duplicate_signals"] == 1
        and len(conflict["result"]["fact_conflicts"]) == 1
        and conflict["replay"]["replay_failure"] is None,
        "worker_restart_recovery_verified": loaded["p8_live"].get("status") == "verified"
        and loaded["p8_live"]["checks"]["bounded_restart_verified"] is True,
        "pitr_recovery_hash_matches": loaded["p10_restore"].get("status") == "verified"
        and restored_hash == loaded["p10_restore"]["source"]["formal_event_hash"],
        "reverse_lookup_complete": formal_count == 11
        and len(reverse_links) >= 12
        and bool(reverse_links.get("workflow_id"))
        and bool(reverse_links.get("settlement_ref")),
        "readonly_projection_verified": loaded["p9_projection"].get("status") == "verified",
        "p10_temporal_grok_langgraph_verified": loaded["p10_grok"].get("ok") is True
        and p10_lane.get("model") == "grok-4.5"
        and p10_lane.get("provider_id") == "grok_acpx_headless"
        and restored_hash in p10_lane.get("result_text", "")
        and p10_child.get("passed") is True,
    }
    artifacts = {key: {"path": str(path), "sha256": file_hash(path)} for key, path in paths.items()}
    artifacts["p11_domain"] = {"path": str(domain_output), "sha256": file_hash(domain_output)}
    pack = {
        "schema_version": "xinao.p11_end_to_end_evidence_pack.v1",
        "status": "verified" if all(checks.values()) else "partial",
        "generated_at": datetime.now(UTC).isoformat(),
        "operation_id": "xinao-mainline-20260714T014700",
        "checks": checks,
        "workflows": workflows,
        "domain": domain,
        "unauthorized_write": {
            "rejected": unauthorized_code != 0,
            "sqlstate": "42501" if "42501" in unauthorized_error else "unknown",
        },
        "reverse_lookup": {
            "formal_event_count": formal_count,
            "outbox_count": outbox_count,
            "formal_rows_sha256": formal_reverse_hash,
            "lineage_reverse_links": reverse_links,
        },
        "recovery": {
            "p8_report_hash": loaded["p8_live"].get("report_hash"),
            "p10_formal_event_hash": restored_hash,
            "p10_rto_seconds": loaded["p10_restore"]["restore"]["rto_seconds"],
            "p10_grok_workflow_id": loaded["p10_grok"].get("workflow_id"),
        },
        "artifacts": artifacts,
        "pack_hash": "",
    }
    pack["pack_hash"] = canonical_hash({**pack, "pack_hash": ""})
    write_json_atomic(args.output, pack)
    readback = load_object(args.output)
    if canonical_hash({**readback, "pack_hash": ""}) != readback["pack_hash"]:
        raise AssertionError("P11 evidence pack readback hash mismatch")
    print(json.dumps({"status": pack["status"], "output": str(args.output)}))
    return 0 if pack["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
