#!/usr/bin/env python3
"""Independently verify an F4 zero-model negative-companion evidence pack.

The verifier never calls the negative runner and never trusts its ``checks``,
``replay_ok``, or zero-count booleans.  It verifies the exact manifest bytes,
decodes the retained Temporal histories, replays them with the bound workflow
code, and derives the three negative-case assertions from recorded events.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import hashlib
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
XINAO_SRC = REPO_ROOT / "xinao_discovery" / "src"
for source_root in (REPO_ROOT, XINAO_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from xinao.foundation.f4_snapshot_runtime import (
    file_sha256 as snapshot_file_sha256,
)
from xinao.foundation.f4_snapshot_runtime import (
    input_path,
    inside,
    load_object,
    readable_path,
    retained_path,
    same_path,
)

DEFAULT_PACK = Path(
    r"D:\XINAO_RESEARCH_RUNTIME\projects\xinao_discovery\evidence"
    r"\xinao-f4-negative-companion-20260714T160917Z"
)
SCHEMA_VERSION = "xinao.f4_negative_pack_independent_verification.v1"
ASSERTION_SCHEMA_VERSION = "xinao.content_addressed_assertion.v1"
PREFIX = "xinao-f4-negative-companion"
SOURCE_INDEX_RELATIVE = "source_cas/index.json"
EXPECTED_SOURCE_LOGICAL_PATHS = {
    "input_helper": "scripts/run_foundation_v2_f4_live_canary.py",
    "runner": "scripts/run_foundation_v2_f4_negative_companion.py",
    "v1_workflow": "services/agent_runtime/foundation_continuous_workflow.py",
    "v2_workflow": "services/agent_runtime/foundation_continuous_workflow_v2.py",
}

EXPECTED_CASE_HISTORIES = {
    "AVAILABLE_SLOTS_ZERO_BACKPRESSURE": ["backpressure-parent"],
    "EXACT_EXTERNAL_FAILURE_DOWNSHIFT_RECOVERY": [
        "partial-parent",
        "partial-failed-child",
        "partial-recovery-child",
    ],
    "EXACT_CHILD_EXTERNAL_CANCEL_AND_FRESH_RECOVERY": [
        "cancel-parent",
        "cancel-callback-child",
        "cancel-exact-hold",
        "cancel-recovery-parent",
        "cancel-recovery-child",
    ],
}
EXPECTED_HISTORY_TYPES = {
    "backpressure-parent": "FoundationContinuousWorkflowV2",
    "partial-parent": "FoundationContinuousWorkflowV2",
    "partial-failed-child": "FoundationWaveChildWorkflowV1",
    "partial-recovery-child": "FoundationWaveChildWorkflowV1",
    "cancel-parent": "FoundationContinuousWorkflowV2",
    "cancel-callback-child": "FoundationWaveChildWorkflowV1",
    "cancel-exact-hold": "FoundationWaveChildWorkflowV1",
    "cancel-recovery-parent": "FoundationContinuousWorkflowV2",
    "cancel-recovery-child": "FoundationWaveChildWorkflowV1",
}
EXPECTED_TERMINALS = {
    "backpressure-parent": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    "partial-parent": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    "partial-failed-child": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    "partial-recovery-child": "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
    "cancel-parent": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    "cancel-callback-child": "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
    "cancel-exact-hold": "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
    "cancel-recovery-parent": "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
    "cancel-recovery-child": "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
}
ALLOWED_ACTIVITY_TYPES = {
    "xinao.foundation.persist_state",
    "xinao.foundation.v2.reconcile",
    "xinao.foundation.v2.verify_roll_forward",
}


class VerificationError(ValueError):
    """Raised when retained evidence is missing, mutable, or contradictory."""


@dataclass(frozen=True)
class ParsedHistory:
    name: str
    path: Path
    meta: Mapping[str, Any]
    raw: Mapping[str, Any]
    events: tuple[Mapping[str, Any], ...]
    workflow_id: str
    run_id: str
    workflow_type: str
    task_queue: str


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return snapshot_file_sha256(path)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = load_object(path)
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"JSON evidence is not an object: {path}")
    return value


def _inside(path: Path, root: Path, *, label: str) -> Path:
    try:
        resolved = readable_path(path)
    except (OSError, RuntimeError) as exc:
        raise VerificationError(f"{label} is not a readable pack-local file: {path}") from exc
    if not inside(path, root):
        raise VerificationError(f"{label} escaped source pack: {resolved}")
    return resolved


def _same_path(left: object, right: object) -> bool:
    return same_path(left, right)


def _evidence_ref(path: Path) -> dict[str, Any]:
    resolved = readable_path(path, expect="file")
    return {
        "path": retained_path(path),
        "sha256": file_sha256(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _assertion(
    assertion_id: str,
    evidence_paths: Iterable[Path],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    by_path = {retained_path(path): _evidence_ref(path) for path in evidence_paths}
    refs = [by_path[key] for key in sorted(by_path)]
    body = {
        "schema_version": ASSERTION_SCHEMA_VERSION,
        "assertion_id": assertion_id,
        "status": "PASS",
        "evidence_refs": refs,
        "evidence_set_sha256": canonical_sha256(refs),
        "observed": dict(observed),
    }
    return {**body, "assertion_sha256": canonical_sha256(body)}


def _verify_manifest(
    pack: Path,
) -> tuple[dict[str, Any], Path, dict[str, Path], str]:
    pack = input_path(pack, expect="directory")
    manifest_path = pack / "artifact_manifest.json"
    manifest = _load_object(manifest_path)
    _require(
        manifest.get("schema_version") == "xinao.f4_negative_companion_artifact_manifest.v1",
        "unexpected negative-pack manifest schema",
    )
    _require(
        _same_path(manifest.get("pack_ref"), pack),
        "manifest pack_ref does not identify the source pack",
    )
    entries = manifest.get("artifacts")
    _require(isinstance(entries, list) and entries, "artifact list is empty")
    _require(
        int(manifest.get("artifact_count") or -1) == len(entries),
        "artifact_count does not equal manifest entries",
    )

    paths: dict[str, Path] = {}
    identities: list[dict[str, Any]] = []
    for raw in entries:
        _require(isinstance(raw, dict), "manifest artifact entry is not an object")
        relative = str(raw.get("relative_path") or "")
        candidate = _inside(pack / relative, pack, label="manifest artifact")
        _require(
            relative == candidate.relative_to(pack).as_posix(),
            f"manifest path is not canonical: {relative}",
        )
        _require(relative not in paths, f"duplicate manifest path: {relative}")
        _require(candidate.is_file(), f"manifest artifact is missing: {candidate}")
        expected_hash = str(raw.get("sha256") or "").lower()
        expected_size = int(raw.get("size_bytes") or -1)
        _require(
            len(expected_hash) == 64 and file_sha256(candidate) == expected_hash,
            f"manifest artifact hash drifted: {relative}",
        )
        _require(
            candidate.stat().st_size == expected_size,
            f"manifest artifact size drifted: {relative}",
        )
        paths[relative] = candidate
        identities.append(
            {
                "relative_path": relative,
                "sha256": expected_hash,
                "size_bytes": expected_size,
            }
        )

    actual = {
        path.resolve().relative_to(pack).as_posix()
        for path in pack.rglob("*")
        if path.is_file() and path.resolve() != manifest_path.resolve()
    }
    _require(actual == set(paths), "manifest does not equal the exact source file set")

    report_path = pack / "negative_companion_report.json"
    _require(
        "negative_companion_report.json" in paths,
        "negative report is absent from artifact manifest",
    )
    _require(
        _same_path(manifest.get("report_ref"), report_path),
        "manifest report_ref drifted",
    )
    _require(
        str(manifest.get("report_sha256") or "").lower()
        == file_sha256(report_path)
        == str(
            next(
                item["sha256"]
                for item in identities
                if item["relative_path"] == "negative_companion_report.json"
            )
        ),
        "negative report is not byte-bound by the manifest",
    )
    artifact_set_hash = canonical_sha256(sorted(identities, key=lambda item: item["relative_path"]))
    return manifest, manifest_path, paths, artifact_set_hash


def _decode_payload_object(payload_container: object, *, label: str) -> dict[str, Any]:
    _require(isinstance(payload_container, dict), f"{label} payload container missing")
    payloads = payload_container.get("payloads")
    _require(
        isinstance(payloads, list) and len(payloads) == 1,
        f"{label} must contain exactly one payload",
    )
    payload = payloads[0]
    _require(isinstance(payload, dict), f"{label} payload is invalid")
    metadata = payload.get("metadata")
    _require(isinstance(metadata, dict), f"{label} encoding metadata missing")
    try:
        encoding = base64.b64decode(str(metadata.get("encoding") or "")).decode()
        raw = base64.b64decode(str(payload.get("data") or "")).decode("utf-8")
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{label} payload is not valid JSON/plain") from exc
    _require(encoding == "json/plain", f"{label} payload encoding drifted")
    _require(isinstance(value, dict), f"{label} payload is not a JSON object")
    return value


def _events(
    history: ParsedHistory,
    event_type: str,
) -> list[Mapping[str, Any]]:
    return [event for event in history.events if event.get("eventType") == event_type]


def _terminal_state(history: ParsedHistory) -> dict[str, Any]:
    completed = _events(history, "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED")
    _require(len(completed) == 1, f"{history.name} has no single completed result")
    attributes = completed[0].get("workflowExecutionCompletedEventAttributes")
    _require(isinstance(attributes, dict), f"{history.name} terminal attributes missing")
    return _decode_payload_object(attributes.get("result"), label=f"{history.name} result")


def _signals(history: ParsedHistory, signal_name: str) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for event in _events(history, "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED"):
        attributes = event.get("workflowExecutionSignaledEventAttributes")
        if isinstance(attributes, dict) and attributes.get("signalName") == signal_name:
            decoded.append(
                _decode_payload_object(
                    attributes.get("input"),
                    label=f"{history.name} {signal_name}",
                )
            )
    return decoded


def _activity_results(history: ParsedHistory, activity_type: str) -> list[dict[str, Any]]:
    scheduled: dict[str, str] = {}
    for event in _events(history, "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"):
        attributes = event.get("activityTaskScheduledEventAttributes")
        if not isinstance(attributes, dict):
            continue
        activity = attributes.get("activityType")
        if isinstance(activity, dict):
            scheduled[str(event.get("eventId") or "")] = str(activity.get("name") or "")
    results: list[dict[str, Any]] = []
    for event in _events(history, "EVENT_TYPE_ACTIVITY_TASK_COMPLETED"):
        attributes = event.get("activityTaskCompletedEventAttributes")
        if not isinstance(attributes, dict):
            continue
        scheduled_id = str(attributes.get("scheduledEventId") or "")
        if scheduled.get(scheduled_id) == activity_type:
            results.append(
                _decode_payload_object(
                    attributes.get("result"),
                    label=f"{history.name} {activity_type} result",
                )
            )
    return results


def _child_starts(history: ParsedHistory) -> list[dict[str, Any]]:
    initiated: dict[str, Mapping[str, Any]] = {}
    for event in _events(
        history,
        "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED",
    ):
        attributes = event.get("startChildWorkflowExecutionInitiatedEventAttributes")
        _require(isinstance(attributes, dict), "child initiation attributes missing")
        initiated[str(event.get("eventId") or "")] = attributes
    starts: list[dict[str, Any]] = []
    for event in _events(history, "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED"):
        attributes = event.get("childWorkflowExecutionStartedEventAttributes")
        _require(isinstance(attributes, dict), "child start attributes missing")
        initiated_id = str(attributes.get("initiatedEventId") or "")
        request = initiated.get(initiated_id)
        _require(request is not None, "child start has no initiated event")
        execution = attributes.get("workflowExecution")
        workflow_type = attributes.get("workflowType")
        task_queue = request.get("taskQueue")
        _require(
            isinstance(execution, dict)
            and isinstance(workflow_type, dict)
            and isinstance(task_queue, dict),
            "child start identity is incomplete",
        )
        starts.append(
            {
                "workflow_id": str(execution.get("workflowId") or ""),
                "run_id": str(execution.get("runId") or ""),
                "workflow_type": str(workflow_type.get("name") or ""),
                "task_queue": str(task_queue.get("name") or ""),
                "input": _decode_payload_object(
                    request.get("input"),
                    label=f"{history.name} child input",
                ),
            }
        )
    return starts


def _terminal_child_identities(history: ParsedHistory, event_type: str) -> set[tuple[str, str]]:
    field_by_type = {
        "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED": (
            "childWorkflowExecutionCompletedEventAttributes"
        ),
        "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED": (
            "childWorkflowExecutionCanceledEventAttributes"
        ),
    }
    field = field_by_type[event_type]
    identities: set[tuple[str, str]] = set()
    for event in _events(history, event_type):
        attributes = event.get(field)
        _require(isinstance(attributes, dict), "child terminal attributes missing")
        execution = attributes.get("workflowExecution")
        _require(isinstance(execution, dict), "child terminal identity missing")
        identities.add(
            (
                str(execution.get("workflowId") or ""),
                str(execution.get("runId") or ""),
            )
        )
    return identities


def _report_history_metadata(
    report: Mapping[str, Any],
    pack: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    _require(
        report.get("schema_version") == "xinao.f4_negative_companion_report.v1",
        "unexpected negative report schema",
    )
    _require(report.get("scope") == "F4_ZERO_MODEL_NEGATIVE_COMPANION", "scope drifted")
    cases = report.get("cases")
    _require(isinstance(cases, list) and len(cases) == 3, "exactly three cases required")
    by_case: dict[str, Mapping[str, Any]] = {}
    histories: dict[str, Mapping[str, Any]] = {}
    history_case: dict[str, str] = {}
    for raw_case in cases:
        _require(isinstance(raw_case, dict), "case entry is invalid")
        case_id = str(raw_case.get("case") or "")
        _require(case_id not in by_case, f"duplicate case: {case_id}")
        by_case[case_id] = raw_case
        raw_histories = raw_case.get("histories")
        _require(isinstance(raw_histories, list), f"{case_id} histories missing")
        expected = EXPECTED_CASE_HISTORIES.get(case_id)
        _require(expected is not None, f"unexpected negative case: {case_id}")
        actual_names: list[str] = []
        for meta in raw_histories:
            _require(isinstance(meta, dict), f"{case_id} history metadata invalid")
            path = _inside(Path(str(meta.get("history_ref") or "")), pack, label="history")
            _require(path.parent == pack / "histories", "history is outside histories directory")
            name = path.stem
            _require(name not in histories, f"duplicate history metadata: {name}")
            histories[name] = meta
            history_case[name] = case_id
            actual_names.append(name)
        _require(actual_names == expected, f"{case_id} history ordering/set drifted")
    _require(set(by_case) == set(EXPECTED_CASE_HISTORIES), "negative case set drifted")
    _require(set(histories) == set(EXPECTED_HISTORY_TYPES), "history set drifted")
    return histories, history_case


def _parse_histories(
    report: Mapping[str, Any],
    pack: Path,
) -> tuple[dict[str, ParsedHistory], dict[str, str]]:
    metadata, history_case = _report_history_metadata(report, pack)
    parsed: dict[str, ParsedHistory] = {}
    identities: set[tuple[str, str]] = set()
    for name, meta in metadata.items():
        path = _inside(Path(str(meta.get("history_ref") or "")), pack, label="history")
        _require(path.is_file(), f"history missing: {path}")
        _require(
            file_sha256(path) == str(meta.get("history_sha256") or "").lower(),
            f"history hash drifted: {name}",
        )
        raw = _load_object(path)
        raw_events = raw.get("events")
        _require(isinstance(raw_events, list) and raw_events, f"empty history: {name}")
        _require(all(isinstance(item, dict) for item in raw_events), f"invalid history: {name}")
        events = tuple(raw_events)
        event_ids = [int(str(item.get("eventId") or "0")) for item in events]
        _require(event_ids == list(range(1, len(events) + 1)), f"event IDs drifted: {name}")
        _require(
            int(meta.get("history_event_count") or -1) == len(events),
            f"history event count metadata drifted: {name}",
        )
        actual_types = sorted({str(item.get("eventType") or "") for item in events})
        _require(
            actual_types == sorted(meta.get("event_types") or []), f"event type set drifted: {name}"
        )
        _require(
            events[0].get("eventType") == "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
            f"history does not start with workflow start: {name}",
        )
        _require(
            events[-1].get("eventType") == EXPECTED_TERMINALS[name],
            f"terminal event drifted: {name}",
        )
        start = events[0].get("workflowExecutionStartedEventAttributes")
        _require(isinstance(start, dict), f"workflow start attributes missing: {name}")
        workflow_type = start.get("workflowType")
        task_queue = start.get("taskQueue")
        _require(
            isinstance(workflow_type, dict) and isinstance(task_queue, dict),
            f"workflow start identity incomplete: {name}",
        )
        workflow_id = str(meta.get("workflow_id") or "")
        run_id = str(meta.get("run_id") or "")
        actual_workflow_type = str(workflow_type.get("name") or "")
        actual_task_queue = str(task_queue.get("name") or "")
        _require(workflow_id.startswith(PREFIX), f"workflow identity escaped prefix: {name}")
        _require(actual_task_queue.startswith(PREFIX), f"task queue escaped prefix: {name}")
        _require(
            actual_workflow_type
            == EXPECTED_HISTORY_TYPES[name]
            == str(meta.get("workflow_type") or ""),
            f"workflow type drifted: {name}",
        )
        _require(
            run_id
            and run_id
            == str(start.get("originalExecutionRunId") or "")
            == str(start.get("firstExecutionRunId") or ""),
            f"run identity drifted: {name}",
        )
        _require(
            actual_task_queue == str(meta.get("task_queue") or ""),
            f"task queue metadata drifted: {name}",
        )
        identity = (workflow_id, run_id)
        _require(identity not in identities, f"duplicate workflow execution: {identity}")
        identities.add(identity)
        parsed[name] = ParsedHistory(
            name=name,
            path=path,
            meta=meta,
            raw=raw,
            events=events,
            workflow_id=workflow_id,
            run_id=run_id,
            workflow_type=actual_workflow_type,
            task_queue=actual_task_queue,
        )
    return parsed, history_case


def _verify_source_bindings(
    report: Mapping[str, Any],
    pack: Path,
    artifact_paths: Mapping[str, Path],
) -> tuple[dict[str, Path], dict[str, Any]]:
    raw = report.get("source_bindings")
    _require(isinstance(raw, dict), "source bindings missing")
    _require(
        set(raw) == set(EXPECTED_SOURCE_LOGICAL_PATHS),
        "source binding roles drifted",
    )
    index_binding = report.get("source_index")
    _require(isinstance(index_binding, dict), "source index binding missing")
    _require(
        str(index_binding.get("ref") or "") == SOURCE_INDEX_RELATIVE,
        "source index ref drifted",
    )
    index_path = artifact_paths.get(SOURCE_INDEX_RELATIVE)
    _require(index_path is not None, "source index is absent from artifact manifest")
    _require(
        file_sha256(index_path) == str(index_binding.get("sha256") or "").lower(),
        "source index hash drifted",
    )
    _require(
        index_path.stat().st_size == int(index_binding.get("size_bytes") or -1),
        "source index size drifted",
    )
    index = _load_object(index_path)
    _require(
        index.get("schema_version") == "xinao.f4_negative_source_cas.v1",
        "source index schema drifted",
    )
    index_core = dict(index)
    recorded_content_hash = str(index_core.pop("content_sha256", "")).lower()
    _require(
        len(recorded_content_hash) == 64 and recorded_content_hash == canonical_sha256(index_core),
        "source index content hash drifted",
    )
    indexed_sources = index.get("sources")
    _require(isinstance(indexed_sources, dict), "source index entries missing")
    _require(indexed_sources == raw, "report source bindings drifted from source index")
    _require(
        int(index.get("source_count") or -1) == len(EXPECTED_SOURCE_LOGICAL_PATHS),
        "source index source_count drifted",
    )
    paths: dict[str, Path] = {}
    observed: dict[str, Any] = {}
    expected_cas_refs: set[str] = set()
    for key, logical_path in EXPECTED_SOURCE_LOGICAL_PATHS.items():
        binding = raw.get(key)
        _require(isinstance(binding, dict), f"source binding missing: {key}")
        expected_hash = str(binding.get("sha256") or "").lower()
        expected_size = int(binding.get("size_bytes") or -1)
        expected_ref = f"source_cas/sha256/{expected_hash[:2]}/{expected_hash}.py"
        _require(
            binding.get("logical_path") == logical_path,
            f"source logical path drifted: {key}",
        )
        _require(binding.get("cas_ref") == expected_ref, f"source CAS ref drifted: {key}")
        path = artifact_paths.get(expected_ref)
        _require(path is not None, f"source CAS object absent from manifest: {key}")
        path = _inside(path, pack, label=f"source CAS object {key}")
        _require(not path.is_symlink(), f"source CAS object is a symlink: {key}")
        _require(
            len(expected_hash) == 64 and path.is_file() and file_sha256(path) == expected_hash,
            f"source hash drifted: {key}",
        )
        _require(path.stat().st_size == expected_size, f"source size drifted: {key}")
        paths[key] = path
        observed[key] = {
            "logical_path": logical_path,
            "cas_ref": expected_ref,
            "sha256": expected_hash,
            "size_bytes": expected_size,
        }
        expected_cas_refs.add(expected_ref)
    actual_cas_refs = {
        relative for relative in artifact_paths if relative.startswith("source_cas/sha256/")
    }
    _require(actual_cas_refs == expected_cas_refs, "source CAS exact inventory drifted")
    _require(
        int(index.get("cas_object_count") or -1) == len(expected_cas_refs),
        "source index cas_object_count drifted",
    )
    return paths, observed


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _verify_input_helper_reachability(helper: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(helper.read_text(encoding="utf-8"), filename=str(helper))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise VerificationError("bound negative input helper is not parseable Python") from exc
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    reachable = {"prepare_inputs"}
    frontier = ["prepare_inputs"]
    while frontier:
        name = frontier.pop()
        function = functions.get(name)
        _require(function is not None, f"bound helper function is missing: {name}")
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            called = _dotted_name(node.func)
            if called in functions and called not in reachable:
                reachable.add(called)
                frontier.append(called)
    expected = {
        "build_method",
        "file_sha256",
        "prepare_inputs",
        "versioned_source_graph",
        "write_json",
    }
    _require(reachable == expected, "negative input helper reachable function set drifted")
    forbidden_prefixes = (
        "Client.connect",
        "asyncio.create_subprocess_",
        "os.system",
        "subprocess.",
    )
    reachable_calls = sorted(
        {
            _dotted_name(node.func)
            for name in reachable
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call)
        }
    )
    _require(
        not any(
            call == prefix or call.startswith(prefix)
            for call in reachable_calls
            for prefix in forbidden_prefixes
        ),
        "negative input helper reaches a live/process transport",
    )
    top_level_calls = sorted(
        {
            _dotted_name(node.func)
            for statement in tree.body
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
        }
    )
    _require(
        not any(
            call == prefix or call.startswith(prefix)
            for call in top_level_calls
            for prefix in forbidden_prefixes
        ),
        "negative input helper has a prohibited import-time side effect",
    )
    return {
        "reachable_function_names": sorted(reachable),
        "reachable_function_count": len(reachable),
        "reachable_live_client_connect_calls": 0,
        "reachable_process_launch_calls": 0,
        "import_time_prohibited_calls": 0,
    }


def _verify_runner_isolation(runner: Path, input_helper: Path) -> dict[str, Any]:
    try:
        tree = ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise VerificationError("bound negative runner is not parseable Python") from exc
    imported_modules: set[str] = set()
    calls: list[str] = []
    started_workflow_classes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_modules.add(str(node.module or ""))
        elif isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            calls.append(name)
            if name.endswith(".start_workflow") and node.args:
                started_workflow_classes.append(_dotted_name(node.args[0]))
    helper_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "scripts.run_foundation_v2_f4_live_canary"
        for alias in node.names
    }
    _require(
        helper_imports == {"RUNTIME", "file_sha256", "prepare_inputs", "write_json"},
        "negative runner helper import surface drifted",
    )
    forbidden_modules = {
        "docker",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "temporalio.client.Client",
        "urllib",
    }
    forbidden_calls = {
        "Client.connect",
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.run",
    }
    _require(not (imported_modules & forbidden_modules), "runner imports a live/process transport")
    _require(not (set(calls) & forbidden_calls), "runner calls a live/process transport")
    _require(
        calls.count("WorkflowEnvironment.start_time_skipping") == 1,
        "runner is not bound to one ephemeral time-skipping environment",
    )
    _require(
        set(started_workflow_classes)
        <= {"FoundationContinuousWorkflowV2.run", "FoundationWaveChildWorkflowV1.run"},
        "runner starts an unexpected workflow type",
    )
    _require(
        "FoundationContinuousWorkflowV1.run" not in started_workflow_classes,
        "runner starts canonical/predecessor V1",
    )
    _require(len(started_workflow_classes) == 5, "runner start_workflow call topology drifted")

    run_function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
        ),
        None,
    )
    _require(run_function is not None, "runner run() function missing")
    case_clients: list[str] = []
    for node in ast.walk(run_function):
        if not isinstance(node, ast.Call):
            continue
        if _dotted_name(node.func) not in {
            "run_backpressure_case",
            "run_partial_case",
            "run_cancel_case",
        }:
            continue
        client_keyword = next((item for item in node.keywords if item.arg == "client"), None)
        client_node = (
            client_keyword.value
            if client_keyword is not None
            else (node.args[0] if node.args else None)
        )
        _require(client_node is not None, "negative case has no explicit client binding")
        case_clients.append(_dotted_name(client_node))
    _require(
        case_clients == ["environment.client"] * 3,
        "negative cases do not use only ephemeral client",
    )
    helper_observed = _verify_input_helper_reachability(input_helper)
    return {
        "ephemeral_environment_calls": 1,
        "live_client_connect_calls": 0,
        "process_launch_calls": 0,
        "started_workflow_classes": started_workflow_classes,
        "case_client_bindings": case_clients,
        "input_helper": helper_observed,
    }


async def _replay_histories(
    histories: Mapping[str, ParsedHistory],
    source_paths: Mapping[str, Path],
) -> list[dict[str, Any]]:
    for path in (REPO_ROOT, XINAO_SRC):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        import services.agent_runtime  # noqa: F401
        from temporalio.client import WorkflowHistory
        from temporalio.worker import Replayer, UnsandboxedWorkflowRunner
    except ImportError as exc:
        raise VerificationError("Temporal replay dependencies are unavailable") from exc

    module_names = [
        "services.agent_runtime.foundation_continuous_workflow",
        "services.agent_runtime.foundation_continuous_workflow_v2",
    ]
    previous = {name: sys.modules.get(name) for name in module_names}

    def load_bound_module(name: str, path: Path) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.__package__ = name.rpartition(".")[0]
        sys.modules[name] = module
        try:
            source = path.read_bytes()
            exec(compile(source, str(path), "exec"), module.__dict__)
        except Exception as exc:
            raise VerificationError(f"bound workflow source cannot load: {name}") from exc
        return module

    try:
        v1_module = load_bound_module(module_names[0], source_paths["v1_workflow"])
        v2_module = load_bound_module(module_names[1], source_paths["v2_workflow"])
        child_workflow = getattr(v1_module, "FoundationWaveChildWorkflowV1")
        parent_workflow = getattr(v2_module, "FoundationContinuousWorkflowV2")
        replayer = Replayer(
            workflows=[parent_workflow, child_workflow],
            workflow_runner=UnsandboxedWorkflowRunner(),
        )
        observed: list[dict[str, Any]] = []
        for name in EXPECTED_HISTORY_TYPES:
            item = histories[name]
            history = WorkflowHistory.from_json(item.workflow_id, dict(item.raw))
            result = await replayer.replay_workflow(
                history,
                raise_on_replay_failure=False,
            )
            _require(result.replay_failure is None, f"Temporal SDK replay failed: {name}")
            observed.append(
                {
                    "name": name,
                    "workflow_id": item.workflow_id,
                    "run_id": item.run_id,
                    "workflow_type": item.workflow_type,
                    "event_count": len(item.events),
                    "history_sha256": file_sha256(item.path),
                }
            )
        return observed
    finally:
        for name in reversed(module_names):
            prior = previous[name]
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _verify_backpressure(history: ParsedHistory) -> dict[str, Any]:
    state = _terminal_state(history)
    reconciles = _activity_results(history, "xinao.foundation.v2.reconcile")
    _require(len(reconciles) == 1, "backpressure must contain one reconcile result")
    decision = reconciles[0]
    capacity = decision.get("capacity_decision")
    last_decision = state.get("last_decision")
    _require(
        isinstance(capacity, dict) and isinstance(last_decision, dict),
        "backpressure decision missing",
    )
    observation = capacity.get("observation")
    _require(isinstance(observation, dict), "backpressure observation missing")
    _require(
        state.get("status") == "STOPPED"
        and state.get("wave_sequence") == 0
        and state.get("waves_completed") == 0
        and state.get("waves_failed") == 0
        and state.get("current_wave") is None,
        "backpressure terminal state dispatched work",
    )
    _require(
        decision.get("action") == "WAIT"
        and decision.get("reason") == "CAPACITY_BACKPRESSURE"
        and capacity.get("dispatch_width") == 0
        and capacity.get("reason") == "HOST_NOT_READY"
        and capacity.get("backpressure") is True
        and observation.get("available_slots") == 0,
        "backpressure reconcile semantics drifted",
    )
    _require(
        last_decision.get("reason") == "CAPACITY_BACKPRESSURE"
        and last_decision.get("capacity_decision") == capacity,
        "backpressure terminal state is not bound to reconcile result",
    )
    _require(not _child_starts(history), "backpressure history started a child workflow")
    return {
        "available_slots": 0,
        "dispatch_width": 0,
        "capacity_reason": "HOST_NOT_READY",
        "wait_reason": "CAPACITY_BACKPRESSURE",
        "child_workflows_started": 0,
        "terminal_status": "STOPPED",
    }


def _verify_partial(
    parent: ParsedHistory,
    failed_child: ParsedHistory,
    recovery_child: ParsedHistory,
) -> dict[str, Any]:
    state = _terminal_state(parent)
    failed_state = _terminal_state(failed_child)
    reconciles = _activity_results(parent, "xinao.foundation.v2.reconcile")
    _require(len(reconciles) == 2, "partial case must contain two reconcile decisions")
    capacities = [item.get("capacity_decision") for item in reconciles]
    _require(all(isinstance(item, dict) for item in capacities), "partial capacity missing")
    first, second = capacities
    _require(
        first.get("dispatch_width") == 2 and first.get("reason") == "INITIAL_VERIFIED_CAPACITY",
        "partial first dispatch is not width two",
    )
    second_observation = second.get("observation")
    _require(isinstance(second_observation, dict), "partial recovery observation missing")
    _require(
        second.get("dispatch_width") == 1
        and second.get("reason") == "DOWNSHIFT_AFTER_PARTIAL_OR_FAILURE"
        and second_observation.get("partial") is True
        and second_observation.get("failed") == 2,
        "partial recovery is not a 2-to-1 downshift",
    )
    failure_signals = _signals(failed_child, "external_failed")
    _require(len(failure_signals) == 1, "failed child lacks one exact failure signal")
    failure = failure_signals[0]
    _require(
        failure.get("error_type") == "INJECTED_ZERO_MODEL_FAILURE",
        "failed child error type drifted",
    )
    _require(
        failed_state.get("status") == "EXTERNAL_FAILED"
        and failed_state.get("external_failed") == failure,
        "failed child terminal state is not bound to failure signal",
    )
    last_wave = state.get("last_wave_result")
    _require(isinstance(last_wave, dict), "partial parent last wave result missing")
    _require(
        state.get("status") == "STOPPED"
        and state.get("wave_sequence") == 2
        and state.get("waves_failed") == 1
        and state.get("previous_partial") is True
        and state.get("previous_failed") == 2
        and state.get("current_wave") is None
        and last_wave.get("status") == "EXTERNAL_FAILED"
        and last_wave.get("external_failed") == failure,
        "partial parent did not record exact failure and recovery",
    )

    starts = _child_starts(parent)
    _require(len(starts) == 2, "partial parent did not start exactly two child waves")
    expected = [
        (failed_child.workflow_id, failed_child.run_id),
        (recovery_child.workflow_id, recovery_child.run_id),
    ]
    _require(
        [(item["workflow_id"], item["run_id"]) for item in starts] == expected,
        "partial child identities/order drifted",
    )
    _require(
        _terminal_child_identities(
            parent,
            "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED",
        )
        == {expected[0]},
        "failed child did not complete into parent history",
    )
    _require(
        _terminal_child_identities(
            parent,
            "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED",
        )
        == {expected[1]},
        "recovery child was not canceled by bounded stop",
    )
    return {
        "first_dispatch_width": 2,
        "failure_type": "INJECTED_ZERO_MODEL_FAILURE",
        "partial_recorded": True,
        "failed_work_count": 2,
        "recovery_dispatch_width": 1,
        "recovery_reason": "DOWNSHIFT_AFTER_PARTIAL_OR_FAILURE",
        "child_wave_count": 2,
        "terminal_status": "STOPPED",
    }


def _execution_identity(attributes: object, *, label: str) -> tuple[str, str]:
    _require(isinstance(attributes, dict), f"{label} attributes missing")
    execution = attributes.get("workflowExecution")
    _require(isinstance(execution, dict), f"{label} workflow identity missing")
    return (
        str(execution.get("workflowId") or ""),
        str(execution.get("runId") or ""),
    )


def _verify_cancel_and_recovery(
    parent: ParsedHistory,
    callback_child: ParsedHistory,
    hold: ParsedHistory,
    recovery_parent: ParsedHistory,
    recovery_child: ParsedHistory,
) -> dict[str, Any]:
    parent_state = _terminal_state(parent)
    recovery_state = _terminal_state(recovery_parent)
    _require(
        parent_state.get("status") == "STOPPED" and parent_state.get("wave_sequence") == 1,
        "cancel parent terminal state drifted",
    )
    starts = _child_starts(parent)
    _require(len(starts) == 1, "cancel parent must start one callback child")
    callback_identity = (callback_child.workflow_id, callback_child.run_id)
    _require(
        (starts[0]["workflow_id"], starts[0]["run_id"]) == callback_identity,
        "cancel callback child identity drifted",
    )
    _require(
        _terminal_child_identities(
            parent,
            "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED",
        )
        == {callback_identity},
        "cancel parent did not observe callback-child cancellation",
    )

    started_signals = _signals(callback_child, "external_started")
    _require(len(started_signals) == 1, "callback child lacks one external_started signal")
    started = started_signals[0]
    hold_identity = (hold.workflow_id, hold.run_id)
    _require(
        (started.get("workflow_id"), started.get("run_id")) == hold_identity
        and started.get("task_queue") == hold.task_queue,
        "external_started signal is not bound to exact hold workflow",
    )

    initiated = _events(
        callback_child,
        "EVENT_TYPE_REQUEST_CANCEL_EXTERNAL_WORKFLOW_EXECUTION_INITIATED",
    )
    requested = _events(
        callback_child,
        "EVENT_TYPE_EXTERNAL_WORKFLOW_EXECUTION_CANCEL_REQUESTED",
    )
    _require(len(initiated) == len(requested) == 1, "exact external cancel event pair missing")
    initiated_identity = _execution_identity(
        initiated[0].get("requestCancelExternalWorkflowExecutionInitiatedEventAttributes"),
        label="initiated external cancel",
    )
    requested_identity = _execution_identity(
        requested[0].get("externalWorkflowExecutionCancelRequestedEventAttributes"),
        label="requested external cancel",
    )
    _require(
        initiated_identity == requested_identity == hold_identity,
        "external cancellation target is not the exact hold identity",
    )
    _require(
        callback_child.events[-1].get("eventType")
        == hold.events[-1].get("eventType")
        == "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
        "callback child or exact hold did not reach canceled terminal state",
    )

    recovery_starts = _child_starts(recovery_parent)
    _require(len(recovery_starts) == 1, "fresh recovery parent must start one child")
    recovery_identity = (recovery_child.workflow_id, recovery_child.run_id)
    _require(
        (recovery_starts[0]["workflow_id"], recovery_starts[0]["run_id"]) == recovery_identity,
        "fresh recovery child identity drifted",
    )
    _require(
        recovery_state.get("status") == "STOPPED"
        and recovery_state.get("wave_sequence") == 1
        and recovery_state.get("last_decision", {})
        .get("capacity_decision", {})
        .get("dispatch_width")
        == 1,
        "fresh recovery was not dispatched before bounded stop",
    )
    _require(
        _terminal_child_identities(
            recovery_parent,
            "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED",
        )
        == {recovery_identity},
        "fresh recovery child was not canceled by bounded stop",
    )
    all_ids = {
        parent.workflow_id,
        callback_child.workflow_id,
        hold.workflow_id,
        recovery_parent.workflow_id,
        recovery_child.workflow_id,
    }
    _require(
        len(all_ids) == 5 and all(item.startswith(PREFIX) for item in all_ids),
        "cancel/recovery identities are not isolated",
    )
    return {
        "callback_child": {
            "workflow_id": callback_child.workflow_id,
            "run_id": callback_child.run_id,
        },
        "exact_canceled_external": {
            "workflow_id": hold.workflow_id,
            "run_id": hold.run_id,
            "task_queue": hold.task_queue,
        },
        "fresh_recovery_parent": recovery_parent.workflow_id,
        "fresh_recovery_child": recovery_child.workflow_id,
        "fresh_recovery_dispatch_width": 1,
        "isolated_workflow_id_count": 5,
    }


def _verify_zero_model_history_surface(
    histories: Mapping[str, ParsedHistory],
    runner_observed: Mapping[str, Any],
) -> dict[str, Any]:
    activity_types: set[str] = set()
    workflow_types = {item.workflow_type for item in histories.values()}
    task_queues = {item.task_queue for item in histories.values()}
    for item in histories.values():
        for event in _events(item, "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"):
            attributes = event.get("activityTaskScheduledEventAttributes")
            _require(isinstance(attributes, dict), "scheduled activity attributes missing")
            activity_type = attributes.get("activityType")
            _require(isinstance(activity_type, dict), "scheduled activity type missing")
            activity_types.add(str(activity_type.get("name") or ""))
    _require(
        activity_types <= ALLOWED_ACTIVITY_TYPES, "history scheduled a model/external activity"
    )
    _require(
        workflow_types == {"FoundationContinuousWorkflowV2", "FoundationWaveChildWorkflowV1"},
        "history executed an unexpected workflow type",
    )
    _require(
        all(queue.startswith(PREFIX) for queue in task_queues),
        "history used a non-isolated task queue",
    )
    _require(
        runner_observed.get("live_client_connect_calls") == 0, "runner can connect to live Temporal"
    )
    _require(runner_observed.get("process_launch_calls") == 0, "runner can launch a model process")
    return {
        "model_workflow_executions": 0,
        "model_activity_schedules": 0,
        "canonical_v1_workflow_executions": 0,
        "live_client_connect_calls_in_bound_runner": 0,
        "process_launch_calls_in_bound_runner": 0,
        "ephemeral_environment_calls_in_bound_runner": 1,
        "captured_workflow_types": sorted(workflow_types),
        "scheduled_activity_types": sorted(activity_types),
        "isolated_task_queue_count": len(task_queues),
        "isolation_scope": ("bound runner code path plus all nine retained Temporal histories"),
    }


async def verify_negative_pack(pack: Path) -> dict[str, Any]:
    pack = input_path(pack, expect="directory")
    _require(pack.is_dir(), f"negative pack does not exist: {pack}")
    manifest, manifest_path, artifact_paths, artifact_set_hash = _verify_manifest(pack)
    report_path = pack / "negative_companion_report.json"
    report = _load_object(report_path)
    source_paths, source_observed = _verify_source_bindings(
        report,
        pack,
        artifact_paths,
    )
    runner_observed = _verify_runner_isolation(
        source_paths["runner"],
        source_paths["input_helper"],
    )
    histories, history_case = _parse_histories(report, pack)

    assertions: dict[str, dict[str, Any]] = {}
    assertions["artifact_manifest_exact_and_byte_bound"] = _assertion(
        "artifact_manifest_exact_and_byte_bound",
        [manifest_path, *artifact_paths.values()],
        {
            "artifact_count": len(artifact_paths),
            "artifact_set_sha256": artifact_set_hash,
            "manifest_sha256": file_sha256(manifest_path),
            "report_sha256": file_sha256(report_path),
        },
    )

    replayed = await _replay_histories(histories, source_paths)
    event_count = sum(len(item.events) for item in histories.values())
    assertions["three_cases_nine_histories_sdk_replay"] = _assertion(
        "three_cases_nine_histories_sdk_replay",
        [item.path for item in histories.values()]
        + [source_paths["v1_workflow"], source_paths["v2_workflow"]],
        {
            "case_count": len(EXPECTED_CASE_HISTORIES),
            "history_count": len(histories),
            "event_count": event_count,
            "history_case_map": history_case,
            "histories": replayed,
            "source_bindings": source_observed,
        },
    )

    backpressure = _verify_backpressure(histories["backpressure-parent"])
    assertions["available_slots_zero_backpressure"] = _assertion(
        "available_slots_zero_backpressure",
        [histories["backpressure-parent"].path, report_path],
        backpressure,
    )

    partial = _verify_partial(
        histories["partial-parent"],
        histories["partial-failed-child"],
        histories["partial-recovery-child"],
    )
    assertions["external_failure_partial_downshift_recovery"] = _assertion(
        "external_failure_partial_downshift_recovery",
        [
            histories["partial-parent"].path,
            histories["partial-failed-child"].path,
            histories["partial-recovery-child"].path,
        ],
        partial,
    )

    cancel = _verify_cancel_and_recovery(
        histories["cancel-parent"],
        histories["cancel-callback-child"],
        histories["cancel-exact-hold"],
        histories["cancel-recovery-parent"],
        histories["cancel-recovery-child"],
    )
    assertions["exact_cancel_and_fresh_recovery"] = _assertion(
        "exact_cancel_and_fresh_recovery",
        [
            histories["cancel-parent"].path,
            histories["cancel-callback-child"].path,
            histories["cancel-exact-hold"].path,
            histories["cancel-recovery-parent"].path,
            histories["cancel-recovery-child"].path,
        ],
        cancel,
    )

    isolation = _verify_zero_model_history_surface(histories, runner_observed)
    assertions["ephemeral_zero_model_no_canonical_v1_execution"] = _assertion(
        "ephemeral_zero_model_no_canonical_v1_execution",
        [
            source_paths["runner"],
            source_paths["input_helper"],
            *[item.path for item in histories.values()],
        ],
        {**runner_observed, **isolation},
    )
    _require(all(item.get("status") == "PASS" for item in assertions.values()), "assertion failure")
    core = {
        "schema_version": SCHEMA_VERSION,
        "status": "VERIFIED",
        "source_pack_ref": retained_path(pack),
        "source_pack_manifest_sha256": file_sha256(manifest_path),
        "source_report_sha256": file_sha256(report_path),
        "assertion_count": len(assertions),
        "assertions": assertions,
        "ignored_self_asserted_report_fields": [
            "cases[*].checks",
            "cases[*].histories[*].replay_ok",
            "canonical_grok_runner_processes_started",
            "canonical_v1_live_mutations",
            "live_namespace_connections",
            "model_invocations",
            "positive_nine_lane_pack_reruns",
        ],
        "unclosed_items": [],
        "verification_scope": (
            "exact retained pack, bound runner code path, and nine replayed histories; "
            "does not claim knowledge of unrelated concurrent machine processes"
        ),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def write_verification(report: Mapping[str, Any], output_dir: Path) -> Path:
    content_hash = str(report.get("content_sha256") or "")
    _require(len(content_hash) == 64, "verification content hash missing")
    body = dict(report)
    recorded = str(body.pop("content_sha256") or "")
    _require(recorded == canonical_sha256(body), "verification content hash drifted")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{content_hash}.json"
    path.write_text(
        json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(verify_negative_pack(args.pack))
    output_dir = args.output_dir or args.pack.parent / (
        f"{args.pack.name}-independent-verification"
    )
    path = write_verification(report, output_dir)
    result = {
        "ok": True,
        "status": report["status"],
        "verification_ref": retained_path(path),
        "verification_file_sha256": file_sha256(path),
        "content_sha256": report["content_sha256"],
        "assertion_count": report["assertion_count"],
        "case_count": 3,
        "history_count": 9,
        "event_count": report["assertions"]["three_cases_nine_histories_sdk_replay"]["observed"][
            "event_count"
        ],
        "unclosed_items": report["unclosed_items"],
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
