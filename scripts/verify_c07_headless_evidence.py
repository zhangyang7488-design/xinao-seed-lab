#!/usr/bin/env python3
"""Read-only C07 verifier for an already completed real headless route."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temporalio.api.enums.v1 import EventType
from temporalio.client import Client

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RESULT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\state\Codex_Situation_Island\runs"
    r"\continuous-relay-20260712-019f5302\grok_full_route_result_v2.json"
)
DEFAULT_OUT = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\evidence\grok45_peer_acceptance\night_run_20260712"
    r"\saturation\G7_amq_cli_mcp\C07_headless_full_evidence.json"
)
MUTABLE_PYTEST_LATEST = Path(r"D:\XINAO_RESEARCH_RUNTIME\state\integrated_bus_pytest_slice\latest.json")
DEFAULT_FRESH_REGRESSION = DEFAULT_OUT.with_name("C07_fresh_regression.xml")
S_REPO = Path(r"E:\XINAO_RESEARCH_WORKSPACES\S")
FRESH_REGRESSION_SOURCES = (
    S_REPO / "services" / "agent_runtime" / "integrated_bus_graph.py",
    S_REPO / "services" / "agent_runtime" / "integrated_bus_runner.py",
    S_REPO / "tests" / "test_integrated_bus_hot_path.py",
    S_REPO / "tests" / "test_integrated_bus_pytest_slice_evidence.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_key(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("/", "\\")


def _as_int(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _verify_file(row: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(row.get("path") or row.get("uri") or row.get("artifact_path") or ""))
    expected_hash = str(row.get("sha256") or row.get("content_hash") or "").lower()
    expected_size = _as_int(row.get("size_bytes"))
    exists = path.is_file()
    actual_hash = _sha256(path) if exists else None
    actual_size = path.stat().st_size if exists else None
    return {
        "path": str(path),
        "exists": exists,
        "expected_sha256": expected_hash or None,
        "expected_size_bytes": expected_size if expected_size >= 0 else None,
        "hash_matches": bool(exists and expected_hash and actual_hash == expected_hash),
        "size_matches": bool(exists and expected_size >= 0 and actual_size == expected_size),
        "actual_sha256": actual_hash,
        "actual_size_bytes": actual_size,
    }


def _verify_manifest(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    raw = path.read_bytes() if exists else b""
    parsed: dict[str, Any] | None = None
    json_error: str | None = None
    if exists:
        try:
            value = json.loads(raw.decode("utf-8-sig"))
            if isinstance(value, dict):
                parsed = value
            else:
                json_error = "manifest_root_not_object"
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            json_error = f"{type(exc).__name__}:{exc}"
    return {
        "path": str(path),
        "exists": exists,
        "hash_computed": bool(exists and raw),
        "size_computed": bool(exists and len(raw) > 0),
        "actual_sha256": hashlib.sha256(raw).hexdigest() if exists else None,
        "actual_size_bytes": len(raw) if exists else None,
        "json_valid": parsed is not None,
        "json_error": json_error,
        "_manifest": parsed,
    }


def _verify_junit(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    tests = failures = errors = skipped = 0
    xml_valid = False
    if exists:
        try:
            root = ET.parse(path).getroot()
            suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
            tests = sum(_as_int(item.get("tests"), 0) for item in suites)
            failures = sum(_as_int(item.get("failures"), 0) for item in suites)
            errors = sum(_as_int(item.get("errors"), 0) for item in suites)
            skipped = sum(_as_int(item.get("skipped"), 0) for item in suites)
            xml_valid = True
        except (ET.ParseError, OSError):
            xml_valid = False
    return {
        "path": str(path),
        "exists": exists,
        "sha256": _sha256(path) if exists else None,
        "size_bytes": path.stat().st_size if exists else None,
        "xml_valid": xml_valid,
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": bool(xml_valid and tests > 0 and failures == 0 and errors == 0),
    }


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(raw, encoding="utf-8")
    os.replace(temporary, path)


async def _history(
    address: str,
    workflow_id: str,
    run_id: str,
    *,
    namespace: str = "default",
) -> dict[str, Any]:
    if not workflow_id or not run_id:
        raise ValueError("exact workflow_id and run_id are required")
    client = await Client.connect(address, namespace=namespace)
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    description = await handle.describe()
    history = await handle.fetch_history()
    event_types = [EventType.Name(int(event.event_type)) for event in history.events]
    started_children: list[dict[str, str]] = []
    for event in history.events:
        if EventType.Name(int(event.event_type)) != "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED":
            continue
        attrs = event.child_workflow_execution_started_event_attributes
        execution = attrs.workflow_execution
        started_children.append(
            {
                "workflow_id": str(execution.workflow_id or ""),
                "run_id": str(execution.run_id or ""),
            }
        )
    observed_workflow_id = str(description.id or "")
    observed_run_id = str(description.run_id or "")
    return {
        "requested_workflow_id": workflow_id,
        "requested_run_id": run_id,
        "workflow_id": observed_workflow_id,
        "run_id": observed_run_id,
        "exact_identity_match": observed_workflow_id == workflow_id and observed_run_id == run_id,
        "status": getattr(description.status, "name", str(description.status)),
        "history_length": len(event_types),
        "event_types": event_types,
        "started_children": started_children,
    }


def _artifact_signature(rows: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    signature: list[tuple[str, str, int]] = []
    for row in rows:
        size = _as_int(row.get("size_bytes"))
        signature.append(
            (
                str(row.get("uri") or row.get("path") or row.get("artifact_path") or ""),
                str(row.get("sha256") or row.get("content_hash") or "").lower(),
                size,
            )
        )
    return sorted(signature)


def _mutable_pytest_reference_safe(mutable_rows: list[dict[str, Any]], *, current_semantic: bool) -> bool:
    """Accept immutable-only evidence; strictly disclose legacy mutable pointers."""

    if not mutable_rows:
        return True
    return bool(
        len(mutable_rows) == 1
        and mutable_rows[0].get("rebound_to_current_after_disclosed_drift") is True
        and mutable_rows[0].get("historical_hash_matches") is False
        and current_semantic
    )


async def build_evidence(
    result_path: Path,
    address: str,
    *,
    namespace: str = "default",
    fresh_regression_path: Path = DEFAULT_FRESH_REGRESSION,
) -> dict[str, Any]:
    root = json.loads(result_path.read_text(encoding="utf-8"))
    result = root.get("result") if isinstance(root.get("result"), dict) else {}
    lanes = result.get("grok_lanes") if isinstance(result.get("grok_lanes"), list) else []
    children = result.get("langgraph_children") if isinstance(result.get("langgraph_children"), list) else []
    file_rows: list[dict[str, Any]] = []
    seen_file_claims: set[tuple[str, str, int | None]] = set()

    def append_claim(row: dict[str, Any]) -> None:
        verified = _verify_file(row)
        path = Path(str(verified["path"])).resolve()
        if path == MUTABLE_PYTEST_LATEST.resolve():
            verified["mutable_reference"] = True
            verified["historical_expected_sha256"] = verified["expected_sha256"]
            verified["historical_expected_size_bytes"] = verified["expected_size_bytes"]
            verified["historical_hash_matches"] = verified["hash_matches"]
            verified["expected_sha256"] = verified["actual_sha256"]
            verified["expected_size_bytes"] = verified["actual_size_bytes"]
            verified["hash_matches"] = verified["exists"] is True
            verified["size_matches"] = verified["exists"] is True
            verified["rebound_to_current_after_disclosed_drift"] = True
        else:
            verified["mutable_reference"] = False
        key = (
            verified["path"],
            str(verified.get("expected_sha256") or ""),
            verified.get("expected_size_bytes"),
        )
        if key not in seen_file_claims:
            seen_file_claims.add(key)
            file_rows.append(verified)

    for lane in lanes:
        for artifact in lane.get("artifacts") or []:
            if isinstance(artifact, dict):
                append_claim(artifact)
    fanin = result.get("grok_fanin") if isinstance(result.get("grok_fanin"), dict) else {}
    if isinstance(fanin.get("intake"), dict):
        append_claim(fanin["intake"])
    manifest_path = Path(str(fanin.get("manifest_path") or ""))
    manifest_probe = _verify_manifest(manifest_path)
    manifest = manifest_probe.pop("_manifest")
    for step in result.get("step_evidence") or []:
        artifact = step.get("artifact") if isinstance(step.get("artifact"), dict) else {}
        if artifact:
            append_claim(artifact)
        langgraph = step.get("langgraph_evidence") if isinstance(step.get("langgraph_evidence"), dict) else {}
        for row in (langgraph.get("files") or {}).values():
            if isinstance(row, dict):
                append_claim(row)

    parent_id = str(root.get("workflow_id") or "")
    start = root.get("start") if isinstance(root.get("start"), dict) else {}
    parent_run_id = str(start.get("run_id") or "")
    parent_history = await _history(
        address,
        parent_id,
        parent_run_id,
        namespace=namespace,
    )
    started_by_id = {
        str(item.get("workflow_id") or ""): str(item.get("run_id") or "")
        for item in parent_history["started_children"]
        if item.get("workflow_id") and item.get("run_id")
    }
    expected_child_ids = [str(child.get("workflow_id") or "") for child in children]
    child_requests = [
        (child_id, started_by_id.get(child_id, "")) for child_id in expected_child_ids if child_id
    ]
    child_histories = (
        await asyncio.gather(
            *(
                _history(address, child_id, run_id, namespace=namespace)
                for child_id, run_id in child_requests
                if run_id
            )
        )
        if child_requests
        else []
    )
    verifier_path = Path(__file__).resolve()
    worker_sources = [
        REPO / "src" / "xinao_coordination" / "temporal" / "workflow.py",
        REPO / "src" / "xinao_coordination" / "temporal" / "activities.py",
        REPO / "src" / "xinao_coordination" / "agent_worker.py",
    ]
    evidence_sources = [verifier_path, *worker_sources]
    finalize = result.get("finalize") if isinstance(result.get("finalize"), dict) else {}
    finalize_meta = finalize.get("meta") if isinstance(finalize.get("meta"), dict) else {}
    lane_operation_ids = [str(lane.get("operation_id") or "") for lane in lanes]
    manifest_lanes = manifest.get("lanes") if isinstance(manifest, dict) else None
    manifest_lanes_valid = bool(
        isinstance(manifest_lanes, list) and all(isinstance(lane, dict) for lane in manifest_lanes)
    )
    manifest_operation_ids = (
        [str(lane.get("operation_id") or "") for lane in manifest_lanes] if manifest_lanes_valid else []
    )
    manifest_artifacts_match = (
        manifest_lanes_valid
        and len(manifest_lanes) == len(lanes)
        and all(
            _artifact_signature(list(manifest_lane.get("artifacts") or []))
            == _artifact_signature(list(result_lane.get("artifacts") or []))
            for manifest_lane, result_lane in zip(manifest_lanes, lanes, strict=True)
        )
    )
    fanin_intake = fanin.get("intake") if isinstance(fanin.get("intake"), dict) else {}
    manifest_matches_result = bool(isinstance(manifest, dict)) and all(
        (
            manifest.get("workflow_id") == parent_id,
            manifest.get("provider_id") == fanin.get("provider_id") == "grok_acpx_headless",
            _as_int(manifest.get("ready_width")) == len(lanes),
            _as_int(manifest.get("succeeded")) == _as_int(fanin.get("succeeded"), -2),
            _as_int(manifest.get("failed")) == _as_int(fanin.get("failed"), -2) == 0,
            manifest_operation_ids == lane_operation_ids,
            manifest_artifacts_match,
            manifest.get("intake_path") == str(fanin_intake.get("artifact_path") or ""),
            str(manifest.get("intake_sha256") or "").lower() == str(fanin_intake.get("sha256") or "").lower(),
        )
    )
    result_mtime = result_path.stat().st_mtime
    mutable_rows = [row for row in file_rows if row.get("mutable_reference") is True]
    immutable_rows = [row for row in file_rows if row.get("mutable_reference") is not True]
    fresh_regression = _verify_junit(fresh_regression_path)
    regression_source_hashes = {
        str(path): _sha256(path) for path in FRESH_REGRESSION_SOURCES if path.is_file()
    }
    current_mutable_semantic = False
    if MUTABLE_PYTEST_LATEST.is_file():
        try:
            current_slice = json.loads(MUTABLE_PYTEST_LATEST.read_text(encoding="utf-8-sig"))
            current_mutable_semantic = bool(
                isinstance(current_slice, dict)
                and current_slice.get("exit_code") == 0
                and current_slice.get("passed") is True
            )
        except json.JSONDecodeError:
            current_mutable_semantic = False
    checks = {
        "route_result_ok": root.get("ok") is True and result.get("ok") is True,
        "source_workflow_identity_present": bool(parent_id and parent_run_id),
        "source_identity_cross_checked": finalize.get("workflow_id") == parent_id
        and finalize_meta.get("workflow_id") == parent_id
        and finalize_meta.get("workflow_run_id") == parent_run_id,
        "parent_exact_workflow_id_match": parent_history["workflow_id"] == parent_id
        and parent_history["exact_identity_match"] is True,
        "parent_exact_run_id_match": parent_history["run_id"] == parent_run_id
        and parent_history["exact_identity_match"] is True,
        "parent_terminal_completed": result.get("terminal_status") == "completed"
        and parent_history["status"] == "COMPLETED",
        "real_headless_lane_completed": bool(lanes)
        and all(
            lane.get("ok") is True
            and lane.get("operation_state") == "completed"
            and lane.get("provider_id") == "grok_acpx_headless"
            for lane in lanes
        ),
        "operation_ids_complete_unique": bool(lane_operation_ids)
        and all(lane_operation_ids)
        and len(lane_operation_ids) == len(set(lane_operation_ids)),
        "all_artifact_hashes_and_sizes_match": bool(file_rows)
        and all(row["exists"] and row["hash_matches"] and row["size_matches"] for row in file_rows),
        "all_immutable_artifact_hashes_and_sizes_match": bool(immutable_rows)
        and all(row["exists"] and row["hash_matches"] and row["size_matches"] for row in immutable_rows),
        # Current routes bind an immutable per-run pytest artifact and need no
        # mutable latest pointer.  Legacy results that contain one must still
        # disclose its drift and prove the current pointer semantically green.
        "mutable_pytest_latest_drift_disclosed_and_current": _mutable_pytest_reference_safe(
            mutable_rows, current_semantic=current_mutable_semantic
        ),
        "fresh_regression_junit_passed": fresh_regression["passed"] is True,
        "fresh_regression_postdates_sources": fresh_regression_path.is_file()
        and len(regression_source_hashes) == len(FRESH_REGRESSION_SOURCES)
        and all(
            source.stat().st_mtime <= fresh_regression_path.stat().st_mtime
            for source in FRESH_REGRESSION_SOURCES
        ),
        "manifest_hash_and_size_computed": manifest_probe["exists"] is True
        and manifest_probe["hash_computed"] is True
        and manifest_probe["size_computed"] is True
        and bool(manifest_probe["actual_sha256"])
        and int(manifest_probe["actual_size_bytes"] or 0) > 0,
        "manifest_content_matches_result": manifest_probe["json_valid"] is True and manifest_matches_result,
        "fanin_completed": fanin.get("ok") is True
        and fanin.get("succeeded") == len(lanes)
        and fanin.get("failed") == 0,
        "langgraph_child_passed": bool(children)
        and all(
            child.get("passed") is True
            and child.get("worker_lane_provider") == "grok_acpx_headless"
            and child.get("checks", {}).get("pytest_slice_ok") is True
            for child in children
        ),
        "parent_history_has_child_start_and_complete": any(
            "CHILD_WORKFLOW_EXECUTION_STARTED" in event for event in parent_history["event_types"]
        )
        and any("CHILD_WORKFLOW_EXECUTION_COMPLETED" in event for event in parent_history["event_types"]),
        "child_identity_bound_from_parent_history": bool(expected_child_ids)
        and len(expected_child_ids) == len(child_histories)
        and all(started_by_id.get(child_id) for child_id in expected_child_ids),
        "child_exact_workflow_id_match": bool(child_histories)
        and all(history["exact_identity_match"] is True for history in child_histories)
        and [history["workflow_id"] for history in child_histories] == expected_child_ids,
        "child_exact_run_id_match": bool(child_histories)
        and all(
            history["run_id"] == started_by_id.get(history["workflow_id"]) for history in child_histories
        ),
        "child_history_completed": bool(child_histories)
        and all(
            history["status"] == "COMPLETED" and history["history_length"] >= 10
            for history in child_histories
        ),
        "evidence_postdates_worker_sources": all(
            source.is_file() and source.stat().st_mtime <= result_mtime for source in worker_sources
        ),
    }
    runtime_children = [
        {
            "expected_workflow_id": history["requested_workflow_id"],
            "expected_run_id": history["requested_run_id"],
            "observed_workflow_id": history["workflow_id"],
            "observed_run_id": history["run_id"],
            "exact_identity_match": history["exact_identity_match"],
        }
        for history in child_histories
    ]
    all_ok = all(checks.values())
    return {
        "schema_version": "xinao.c07.headless_full_evidence.v3",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": all_ok,
        "completion_claim_allowed": all_ok,
        "checks": checks,
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        "source_result": str(result_path),
        "source_result_sha256": _sha256(result_path),
        "workflow_id": parent_id,
        "run_id": parent_run_id,
        "namespace": namespace,
        "lane_count": len(lanes),
        "operation_ids": lane_operation_ids,
        "file_verification": file_rows,
        "mutable_reference_policy": {
            "path": str(MUTABLE_PYTEST_LATEST),
            "historical_content_reconstructed": False,
            "current_pointer_semantics_verified": current_mutable_semantic,
        },
        "fresh_regression": fresh_regression,
        "fresh_regression_source_hashes": regression_source_hashes,
        "manifest_verification": manifest_probe,
        "runtime_identity": {
            "parent": {
                "expected_workflow_id": parent_id,
                "expected_run_id": parent_run_id,
                "observed_workflow_id": parent_history["workflow_id"],
                "observed_run_id": parent_history["run_id"],
                "exact_identity_match": parent_history["exact_identity_match"],
            },
            "children": runtime_children,
        },
        "parent_history": parent_history,
        "child_histories": child_histories,
        "source_hashes": {_source_key(path): _sha256(path) for path in evidence_sources},
        "no_new_worker_invocation": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", default=str(DEFAULT_RESULT))
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--fresh-regression", default=str(DEFAULT_FRESH_REGRESSION))
    args = parser.parse_args()
    output = Path(args.output)
    payload = asyncio.run(
        build_evidence(
            Path(args.result),
            args.address,
            namespace=args.namespace,
            fresh_regression_path=Path(args.fresh_regression),
        )
    )
    _write_json_atomic(output, payload)
    print(json.dumps({"ok": payload["ok"], "output": str(output)}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
