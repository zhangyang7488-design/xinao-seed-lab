"""Thin horizontal system-awareness consumers over existing facts.

The task-run event chain, runtime APIs, domain ledgers, and evidence artifacts
remain authoritative.  This module derives completion, cost, problem, identity,
recovery, and temporary-object decisions without creating another scheduler,
database, router, or completion authority.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import exceptions as jsonschema_exceptions
from jsonschema import validators as jsonschema_validators

from services.agent_runtime.execution_contract import artifact_json_bytes

REPORT_VERSION = "xinao.system_awareness.report.v1"
COMPLETION_CARD_VERSION = "xinao.work_key_completion_card.v1"
EPISODE_OUTCOME_VERSION = "xinao.episode_outcome_projection.v1"
PROBLEM_PROJECTION_VERSION = "xinao.problem_projection.v1"
IDENTITY_VERSION = "xinao.identity_reconciliation.v1"
PREFLIGHT_VERSION = "xinao.supervisor_capability_preflight.v1"
TEMPORAL_VERSION = "xinao.temporal_identity_reconciliation.v1"
RECOVERY_VERSION = "xinao.recovery_truth.v1"
TEMP_OBJECT_VERSION = "xinao.temporary_object_lifecycle.v1"
TRAJECTORY_VERSION = "xinao.trajectory_sample_evaluation.v1"
PROMOTION_VERSION = "xinao.system_awareness.promotion_evidence.v1"
WAKEABLE_WAIT_VERSION = "xinao.wakeable_wait_decision.v1"
TASK_RUN_VERSION = "codex.verified-task-run.v1"

EXECUTION_PHASES = frozenset({"EXPLORE", "CONSTRUCT", "VERIFY", "LAND"})
FAILURE_PHASE_RE = re.compile(r"(?:reject|fail|error|blocked|invalid|unverified)", re.I)
FAMILY_NORMALIZE_RE = re.compile(r"(?:retry|attempt|wave|event|v)[-_ ]?\d+", re.I)


class SystemAwarenessError(ValueError):
    """A source fact is malformed or a requested decision cannot be trusted."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SystemAwarenessError("INPUT_INVALID", f"{field} must be an object")
    return dict(value)


def _require_text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SystemAwarenessError("INPUT_INVALID", f"{field} must be a string")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemAwarenessError("INPUT_INVALID", f"{field} must be an integer >= 0")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, field: str = "input") -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        value = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemAwarenessError("UTF8_OR_JSON_INVALID", f"cannot read {field}: {path}") from exc
    if "\ufffd" in text:
        raise SystemAwarenessError("UTF8_REPLACEMENT_CHARACTER", f"{field} contains U+FFFD")
    return _require_mapping(value, field), raw


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = artifact_json_bytes(value)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256_bytes(raw)


def _bool_predicates(raw: object, field: str) -> dict[str, bool]:
    values = _require_mapping(raw, field)
    normalized: dict[str, bool] = {}
    for key, value in values.items():
        if not isinstance(value, bool):
            raise SystemAwarenessError("INPUT_INVALID", f"{field}.{key} must be boolean")
        normalized[str(key)] = value
    if not normalized:
        raise SystemAwarenessError("INPUT_INVALID", f"{field} must not be empty")
    return normalized


def evaluate_completion_card(raw: Mapping[str, object]) -> dict[str, Any]:
    """Separate local boundary verification from parent completion authority."""

    data = _require_mapping(raw, "completion_card")
    work_key = _require_text(data.get("work_key"), "work_key")
    role = str(data.get("role") or "boundary_consumer")
    authority_scope = str(data.get("authority_scope") or "non_parent_owner")
    boundary = _bool_predicates(data.get("boundary_predicates"), "boundary_predicates")
    parent_raw = data.get("parent_predicates")
    parent = _bool_predicates(parent_raw, "parent_predicates") if parent_raw is not None else {}
    missing_boundary = sorted(key for key, passed in boundary.items() if not passed)
    missing_parent = sorted(key for key, passed in parent.items() if not passed)
    reasons: list[str] = []

    if role == "internal_execution_child":
        status = "internal_child_bound_to_parent"
        parent_state = "owned_by_parent_consumer"
        reasons.append("INTERNAL_CHILD_NOT_INDEPENDENT_CONSUMER")
        gap_discovery_eligible = False
    elif missing_boundary:
        status = "partial" if any(boundary.values()) else "open"
        parent_state = "open" if authority_scope == "parent_owner" else "not_owned"
        reasons.append("WORK_KEY_INCOMPLETE_PREDICATES")
        if "LEDGER_MOVE" in missing_boundary:
            reasons.append("LEDGER_MOVE_MISSING")
        gap_discovery_eligible = True
    elif authority_scope != "parent_owner":
        status = "verified_within_boundary_non_parent_owner"
        parent_state = "not_owned"
        reasons.append("BOUNDARY_VERIFIED_NO_PARENT_AUTHORITY")
        gap_discovery_eligible = True
    elif parent and not missing_parent:
        status = "verified"
        parent_state = "verified"
        reasons.append("WORK_KEY_AND_PARENT_VERIFIED")
        gap_discovery_eligible = True
    else:
        status = "boundary_verified_parent_open"
        parent_state = "open"
        reasons.append("BOUNDARY_VERIFIED_PARENT_OPEN")
        gap_discovery_eligible = True

    return {
        "schema_version": COMPLETION_CARD_VERSION,
        "work_key": work_key,
        "status": status,
        "role": role,
        "authority_scope": authority_scope,
        "boundary_verified": not missing_boundary,
        "parent_state": parent_state,
        "parent_completion_claim_allowed": status == "verified"
        and authority_scope == "parent_owner",
        "gap_discovery_eligible": gap_discovery_eligible,
        "missing_predicates": {
            "boundary": missing_boundary,
            "parent": missing_parent,
        },
        "reason_codes": reasons,
    }


def _attempt_bucket(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "accepted":
        return "accepted"
    if normalized == "cancelled":
        return "cancelled"
    if normalized in {"failed", "rejected", "timeout"}:
        return "failed"
    return "incomplete"


def project_episode_outcome(raw: Mapping[str, object]) -> dict[str, Any]:
    """Preserve all attempt cost while keeping outcome credit separate."""

    data = _require_mapping(raw, "episode")
    attempts_raw = data.get("attempts")
    if not isinstance(attempts_raw, list):
        raise SystemAwarenessError("INPUT_INVALID", "attempts must be an array")
    by_bucket = {key: 0 for key in ("accepted", "failed", "cancelled", "incomplete")}
    normalized: list[dict[str, object]] = []
    unknown_attempts: list[str] = []
    conversion_links: list[dict[str, object]] = []
    reasons: list[str] = []

    for index, raw_attempt in enumerate(attempts_raw):
        attempt = _require_mapping(raw_attempt, f"attempts[{index}]")
        attempt_id = str(attempt.get("attempt_id") or f"attempt-{index}")
        status = _require_text(attempt.get("status"), f"attempts[{index}].status")
        usage = attempt.get("usage")
        usage_map = _require_mapping(usage, f"attempts[{index}].usage") if usage is not None else {}
        total_raw = usage_map.get("total_tokens")
        if total_raw is None:
            total_tokens: int | None = None
            unknown_attempts.append(attempt_id)
        else:
            total_tokens = _nonnegative_int(total_raw, f"attempts[{index}].usage.total_tokens")
            by_bucket[_attempt_bucket(status)] += total_tokens

        links_raw = attempt.get("outcome_links") or []
        if not isinstance(links_raw, list):
            raise SystemAwarenessError("INPUT_INVALID", "outcome_links must be an array")
        links = [dict(link) for link in links_raw if isinstance(link, Mapping)]
        conversion_links.extend({"attempt_id": attempt_id, **link} for link in links)
        owner_recovered = any(str(link.get("kind")) == "owner_recovered_artifact" for link in links)
        if _attempt_bucket(status) == "failed" and owner_recovered:
            reasons.append("REJECTED_ATTEMPT_COST_RETAINED")
            reasons.append("ARTIFACT_OWNER_RECOVERED_SEPARATELY")
        normalized.append(
            {
                "attempt_id": attempt_id,
                "declared_status": status,
                "cost_bucket": _attempt_bucket(status),
                "total_tokens": total_tokens if total_tokens is not None else "unknown",
                "outcome_links": links,
                "attempt_acceptance_unchanged": True,
            }
        )

    known_total = sum(by_bucket.values())
    native_total_raw = data.get("native_total_tokens")
    native_total = (
        _nonnegative_int(native_total_raw, "native_total_tokens")
        if native_total_raw is not None
        else known_total
    )
    conservation = (
        "unknown"
        if unknown_attempts
        else ("balanced" if known_total == native_total else "mismatch")
    )
    if conservation == "balanced":
        reasons.append("TOKEN_ACCOUNTING_BALANCED")
    elif conservation == "mismatch":
        reasons.append("TOKEN_ACCOUNTING_MISMATCH")

    meaningful_kinds = {
        "verified_outcome",
        "ledger_move",
        "new_effective_evidence",
        "owner_recovered_artifact",
    }
    converted = any(str(link.get("kind")) in meaningful_kinds for link in conversion_links)
    threshold_raw = data.get("high_burn_threshold")
    threshold = (
        _nonnegative_int(threshold_raw, "high_burn_threshold")
        if threshold_raw is not None
        else None
    )
    high_burn_no_conversion = bool(
        threshold is not None
        and known_total >= threshold
        and not converted
        and not unknown_attempts
    )
    if high_burn_no_conversion:
        reasons.append("HIGH_BURN_NO_CONVERSION")

    return {
        "schema_version": EPISODE_OUTCOME_VERSION,
        "episode_id": str(data.get("episode_id") or "unknown"),
        "attempts": normalized,
        "tokens": {
            "native_total": native_total,
            "known_total": known_total,
            "by_outcome": by_bucket,
            "unknown_attempts": unknown_attempts,
            "conservation": conservation,
        },
        "conversion": {
            "converted": converted,
            "links": conversion_links,
            "high_burn_threshold": threshold,
            "high_burn_no_conversion": high_burn_no_conversion,
        },
        "reason_codes": list(dict.fromkeys(reasons)),
        "completion_claim_allowed": False,
    }


def _family_signature(event: Mapping[str, object]) -> str:
    raw = str(
        event.get("family_signature")
        or event.get("root_cause_signature")
        or event.get("reason_code")
        or event.get("phase")
        or "unknown"
    ).strip()
    return FAMILY_NORMALIZE_RE.sub("#", raw).lower()


def _problem_ref(signature: str, cause: str) -> str:
    digest = hashlib.sha256(f"{signature}\n{cause}".encode("utf-8")).hexdigest()[:12].upper()
    return f"PRB-{digest}"


def _classify_problem(
    events: Sequence[Mapping[str, object]], previous: Mapping[str, object] | None
) -> str:
    work_keys = {str(row.get("work_key") or "") for row in events if row.get("work_key")}
    components = {str(row.get("component") or "") for row in events if row.get("component")}
    systemic_flags = {
        "capability_gap",
        "missing_consumer",
        "governing_assumption",
        "cross_entrypoint",
        "control_boundary",
    }
    if any(any(row.get(flag) is True for flag in systemic_flags) for row in events):
        return "systemic_capability_gap"
    if len(work_keys) > 1 or len(components) > 1:
        return "systemic_capability_gap"
    if previous and str(previous.get("recurrence_state")) == "recurred":
        return "systemic_capability_gap"
    return "local_defect" if events else "undetermined"


def _escalate_repair(level: str) -> str:
    order = ["local_patch", "structural_chain_repair", "governing_boundary_repair"]
    try:
        return order[min(order.index(level) + 1, len(order) - 1)]
    except ValueError:
        return "structural_chain_repair"


def _repair_decision(
    events: Sequence[Mapping[str, object]], classification: str, repair_level: str
) -> tuple[str, list[str]]:
    """Choose small repair, structural repair, or an explicit no-build decision."""

    explicit_no_build = any(
        str(row.get("repair_decision") or row.get("build_decision") or "").lower()
        in {"no_build", "do_not_build"}
        for row in events
    )
    irrelevant = bool(events) and all(row.get("relevant_to_parent") is False for row in events)
    nonpositive = bool(events) and all(
        row.get("expected_net_benefit_positive") is False for row in events
    )
    if explicit_no_build or irrelevant or nonpositive:
        return "no_build", ["NO_BUILD_SELECTED"]
    if classification == "local_defect" and repair_level == "local_patch":
        return "small_repair", ["LOCAL_REPAIR_SELECTED"]
    return "structural_repair", ["SYSTEMIC_REPAIR_SELECTED"]


def reconcile_problem_lifecycle(raw: Mapping[str, object]) -> dict[str, Any]:
    """Project merge/split, repair choice, effectiveness, and recurrence over events."""

    data = _require_mapping(raw, "problem_projection")
    events_raw = data.get("events")
    if not isinstance(events_raw, list):
        raise SystemAwarenessError("INPUT_INVALID", "events must be an array")
    events = [_require_mapping(row, f"events[{index}]") for index, row in enumerate(events_raw)]
    previous_raw = data.get("previous") or []
    if isinstance(previous_raw, Mapping):
        previous_rows = [dict(previous_raw)]
    elif isinstance(previous_raw, list):
        previous_rows = [dict(row) for row in previous_raw if isinstance(row, Mapping)]
    else:
        raise SystemAwarenessError("INPUT_INVALID", "previous must be an object or array")
    previous_by_identity = {
        (str(row.get("family_signature") or ""), str(row.get("governing_cause") or "")): row
        for row in previous_rows
    }
    evidence_raw = data.get("effectiveness_evidence") or []
    if not isinstance(evidence_raw, list):
        raise SystemAwarenessError("INPUT_INVALID", "effectiveness_evidence must be an array")
    effectiveness = [dict(row) for row in evidence_raw if isinstance(row, Mapping)]
    close_requested = data.get("close_requested") is True
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    causes_by_family: dict[str, set[str]] = defaultdict(set)
    for event in events:
        signature = _family_signature(event)
        cause = str(event.get("governing_cause") or signature)
        grouped[(signature, cause)].append(event)
        causes_by_family[signature].add(cause)

    problems: list[dict[str, Any]] = []
    receipts: list[dict[str, object]] = []
    for identity in previous_by_identity:
        grouped.setdefault(identity, [])

    group_count = len(grouped)
    for (signature, cause), rows in sorted(grouped.items()):
        previous = previous_by_identity.get((signature, cause))
        event_problem_refs = {
            str(row.get("problem_ref")) for row in rows if str(row.get("problem_ref") or "")
        }
        problem_ref = (
            str(previous.get("problem_ref"))
            if previous
            else next(iter(event_problem_refs))
            if len(event_problem_refs) == 1
            else _problem_ref(signature, cause)
        )
        source_event_refs = list(
            dict.fromkeys(
                str(row.get("event_id") or f"event-{index}") for index, row in enumerate(rows)
            )
        )
        classification = (
            _classify_problem(rows, previous)
            if rows
            else str(previous.get("problem_class") or "undetermined")
        )
        default_level = (
            "structural_chain_repair"
            if classification == "systemic_capability_gap"
            else "local_patch"
        )
        repair_level = (
            str(previous.get("repair_level") or default_level) if previous else default_level
        )
        previous_effective = bool(previous and previous.get("status") == "effective")
        previous_events = (
            set(str(value) for value in (previous.get("source_event_refs") or []))
            if previous
            else set()
        )
        new_event_refs = [value for value in source_event_refs if value not in previous_events]
        recurred = previous_effective and bool(new_event_refs)
        reasons: list[str] = []
        if len(rows) > 1:
            reasons.append("PROBLEM_FAMILY_MERGED")
        if len(causes_by_family[signature]) > 1:
            reasons.append("PROBLEM_FAMILY_SPLIT")
            receipts.append(
                {
                    "reason_code": "PROBLEM_FAMILY_SPLIT",
                    "family_signature": signature,
                    "problem_ref": problem_ref,
                    "lineage": sorted(causes_by_family[signature]),
                }
            )

        current_effectiveness = [
            row
            for row in effectiveness
            if str(row.get("problem_ref") or "") == problem_ref
            or str(row.get("family_signature") or "") == signature
            or (group_count == 1 and not row.get("problem_ref") and not row.get("family_signature"))
        ]
        prior_effectiveness = (
            [
                dict(row)
                for row in (previous.get("effectiveness_evidence") or [])
                if isinstance(row, Mapping)
            ]
            if previous
            else []
        )
        scoped_effectiveness: list[dict[str, object]] = []
        for row in [*prior_effectiveness, *current_effectiveness]:
            if row not in scoped_effectiveness:
                scoped_effectiveness.append(row)
        real_consumer_ok = any(
            row.get("passed") is True and str(row.get("kind")) in {"real_consumer", "live_canary"}
            for row in scoped_effectiveness
        )
        window_ok = any(
            row.get("passed") is True
            and row.get("window_completed") is True
            and str(row.get("kind"))
            in {"monitoring_window", "effectiveness_window", "observation_window"}
            for row in scoped_effectiveness
        )
        effectiveness_ok = real_consumer_ok and window_ok
        repair_decision, decision_reasons = _repair_decision(rows, classification, repair_level)
        reasons.extend(decision_reasons)
        if repair_decision == "no_build":
            status = "retired"
            recurrence_state = "retired"
        elif recurred:
            status = "open"
            recurrence_state = "recurred"
            repair_level = _escalate_repair(repair_level)
            repair_decision = "structural_repair"
            reasons.append("PROBLEM_RECURRENCE_DETECTED")
        elif previous and not new_event_refs and not close_requested:
            previous_status = str(previous.get("status") or "open")
            if previous_status == "effective" and not effectiveness_ok:
                status = "monitoring"
                recurrence_state = "monitoring"
                reasons.append("EFFECTIVENESS_EVIDENCE_MISSING")
            else:
                status = previous_status
                recurrence_state = str(previous.get("recurrence_state") or previous_status)
                reasons.append("PROBLEM_STATE_RETAINED_NO_NEW_EVENT")
        elif close_requested and effectiveness_ok:
            status = "effective"
            recurrence_state = "effective"
            reasons.append("PROBLEM_EFFECTIVENESS_VERIFIED")
        elif close_requested:
            status = "monitoring"
            recurrence_state = "monitoring"
            reasons.append("EFFECTIVENESS_EVIDENCE_MISSING")
        elif not rows and previous:
            status = str(previous.get("status") or "open")
            recurrence_state = str(previous.get("recurrence_state") or "open")
        else:
            status = "open"
            recurrence_state = "open"

        problems.append(
            {
                "problem_ref": problem_ref,
                "family_signature": signature,
                "governing_cause": cause,
                "problem_class": classification,
                "repair_level": repair_level,
                "repair_decision": repair_decision,
                "status": status,
                "recurrence_state": recurrence_state,
                "source_event_refs": sorted(previous_events | set(source_event_refs)),
                "new_event_refs": new_event_refs,
                "effectiveness_evidence": [dict(row) for row in scoped_effectiveness],
                "reason_codes": list(dict.fromkeys(reasons)),
                "completion_claim_allowed": status == "effective" and effectiveness_ok,
            }
        )

    return {
        "schema_version": PROBLEM_PROJECTION_VERSION,
        "authority": False,
        "truth_sources": "existing_task_run_events_and_evidence",
        "problems": problems,
        "receipts": receipts,
        "problem_count": len(problems),
    }


def reconcile_identity(raw: Mapping[str, object]) -> dict[str, Any]:
    data = _require_mapping(raw, "identity")
    declared = str(data.get("declared") or "")
    selected = str(data.get("selected") or "")
    observed = str(data.get("observed") or "")
    allowed_raw = data.get("allowed_observed") or ([selected] if selected else [])
    if not isinstance(allowed_raw, list):
        raise SystemAwarenessError("INPUT_INVALID", "allowed_observed must be an array")
    allowed = sorted(str(value) for value in allowed_raw if str(value))
    reasons: list[str] = []
    if not observed:
        reasons.append("OBSERVED_IDENTITY_MISSING")
    if declared and selected and declared != selected:
        reasons.append("MODEL_IDENTITY_MISMATCH")
    if observed and observed not in allowed:
        reasons.append("MODEL_IDENTITY_MISMATCH")
    verified = not reasons
    return {
        "schema_version": IDENTITY_VERSION,
        "matrix": {
            "declared": declared or None,
            "selected": selected or None,
            "observed": observed or None,
            "allowed_observed": allowed,
        },
        "status": "verified" if verified else "unverified",
        "reason_codes": list(dict.fromkeys(reasons or ["DECLARED_SELECTED_OBSERVED_MATCH"])),
        "completion_claim_allowed": verified,
    }


def _schema_type_matches(value: object, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return expected in checks and checks[expected](value)


def validate_strict_json_result(
    text: str, schema: Mapping[str, object] | None = None
) -> dict[str, Any]:
    """Reject narration prefixes; validate the whole text as the result object."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "reason_code": "RESULT_JSON_PREFIX_INVALID",
            "attempt_status": "rejected",
        }
    if not isinstance(value, Mapping):
        return {"ok": False, "reason_code": "RESULT_JSON_NOT_OBJECT", "attempt_status": "rejected"}
    obj = dict(value)
    if schema is not None:
        schema_obj = _require_mapping(schema, "schema")
        if schema_obj.get("type") not in (None, "object"):
            return {
                "ok": False,
                "reason_code": "RESULT_SCHEMA_INVALID",
                "attempt_status": "rejected",
            }
        try:
            validator_class = jsonschema_validators.validator_for(schema_obj)
            validator_class.check_schema(schema_obj)
            validator_class(schema_obj).validate(obj)
        except jsonschema_exceptions.SchemaError:
            return {
                "ok": False,
                "reason_code": "RESULT_SCHEMA_INVALID",
                "attempt_status": "rejected",
            }
        except jsonschema_exceptions.ValidationError as exc:
            return {
                "ok": False,
                "reason_code": "RESULT_JSON_SCHEMA_MISMATCH",
                "attempt_status": "rejected",
                "json_path": list(exc.absolute_path),
            }
    return {
        "ok": True,
        "reason_code": "RESULT_JSON_VALID",
        "attempt_status": "accepted",
        "value": obj,
    }


def preflight_supervisor_root(
    supervisor_root: Path,
    *,
    phase: str,
    json_schema_path: Path | None = None,
    require_json_object: bool = False,
) -> dict[str, Any]:
    root = Path(supervisor_root).resolve()
    reasons: list[str] = []
    selector = root / "services" / "agent_runtime" / "routing_policy_reader.py"
    preparer = root / "scripts" / "prepare_direct_worker_pool_common_contract.py"
    python_candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / "projects" / "dual-brain-coordination" / ".venv" / "Scripts" / "python.exe",
    ]
    selector_interface = False
    if selector.is_file():
        try:
            tree = ast.parse(selector.read_text(encoding="utf-8"), filename=str(selector))
            selector_interface = any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "resolve_supervisor_worker_decision"
                for node in ast.walk(tree)
            )
        except (OSError, UnicodeDecodeError, SyntaxError):
            selector_interface = False
    if not selector_interface:
        reasons.append("SUPERVISOR_SELECTOR_MISSING")
    if not preparer.is_file():
        reasons.append("COMMON_CONTRACT_PREPARER_MISSING")
    runtime = next((path for path in python_candidates if path.is_file()), None)
    if runtime is None:
        reasons.append("SUPERVISOR_RUNTIME_MISSING")
    if phase not in EXECUTION_PHASES:
        reasons.append("SUPERVISOR_PHASE_INVALID")
    schema_sha256 = ""
    if require_json_object and json_schema_path is None:
        reasons.append("RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT")
    if json_schema_path is not None:
        try:
            schema, raw = _read_json(Path(json_schema_path), "json_schema")
            if schema.get("type") not in (None, "object"):
                raise SystemAwarenessError(
                    "RESULT_SCHEMA_INVALID", "result schema must describe an object"
                )
            validator_class = jsonschema_validators.validator_for(schema)
            validator_class.check_schema(schema)
            schema_sha256 = _sha256_bytes(raw)
        except jsonschema_exceptions.SchemaError:
            reasons.append("RESULT_SCHEMA_BOUND_OR_PREMODEL_REJECT")
        except SystemAwarenessError as exc:
            reasons.append(exc.reason_code)
    ok = not reasons
    return {
        "schema_version": PREFLIGHT_VERSION,
        "supervisor_root": str(root),
        "phase": phase,
        "allowed_phases": sorted(EXECUTION_PHASES),
        "selector_path": str(selector),
        "selector_interface": selector_interface,
        "common_contract_preparer": preparer.is_file(),
        "python_executable": str(runtime) if runtime else None,
        "json_schema_sha256": schema_sha256 or None,
        "ok": ok,
        "reason_codes": reasons or ["SUPERVISOR_CAPABILITY_PREFLIGHT_OK"],
        "model_tokens": 0,
        "model_call_allowed": ok,
    }


def reconcile_temporal_identity(
    repo_manifest: Mapping[str, object], live_snapshot: Mapping[str, object]
) -> dict[str, Any]:
    repo = _require_mapping(repo_manifest, "repo_manifest")
    live = _require_mapping(live_snapshot, "live_snapshot")
    repo_build = str(repo.get("build_id") or repo.get("current_build_id") or "")
    live_build = str(live.get("current_build_id") or live.get("build_id") or "")
    reasons: list[str] = []
    if not live_build:
        reasons.append("OBSERVED_IDENTITY_MISSING")
    elif repo_build != live_build:
        reasons.extend(["TEMPORAL_BUILD_PIN_DRIFT", "DEPLOYMENT_BUILD_DRIFT"])
    workflow_versioning = str(live.get("workflow_versioning") or "").upper()
    activity_versioning = str(live.get("activity_versioning") or "").upper()
    pollers = live.get("pollers")
    if workflow_versioning == "UNVERSIONED" or activity_versioning == "UNVERSIONED":
        reasons.append("TEMPORAL_QUEUE_UNVERSIONED")
    if pollers in (None, [], {}):
        reasons.append("TEMPORAL_POLLER_IDENTITY_MISSING")
    verified = not reasons
    return {
        "schema_version": TEMPORAL_VERSION,
        "authority": False,
        "mutation_performed": False,
        "repo": {
            "deployment_name": repo.get("deployment_name"),
            "build_id": repo_build or None,
        },
        "live": {
            "deployment_name": live.get("deployment_name"),
            "current_build_id": live_build or None,
            "task_queue": live.get("task_queue"),
            "workflow_versioning": workflow_versioning or None,
            "activity_versioning": activity_versioning or None,
            "pollers": pollers,
        },
        "status": "verified" if verified else "partial",
        "reason_codes": reasons or ["TEMPORAL_IDENTITY_RECONCILED"],
        "completion_claim_allowed": False,
    }


def evaluate_recovery_truth(raw: Mapping[str, object]) -> dict[str, Any]:
    data = _require_mapping(raw, "recovery")
    declared = _require_mapping(data.get("declared") or {}, "declared")
    live = _require_mapping(data.get("live") or {}, "live")
    restore = _require_mapping(data.get("isolated_restore") or {}, "isolated_restore")
    canary = _require_mapping(data.get("downstream_canary") or {}, "downstream_canary")
    restore_ok = restore.get("authorized") is True and restore.get("passed") is True
    identity_ok = restore.get("data_identity_match") is True
    canary_ok = canary.get("passed") is True and canary.get("real_consumer") is True
    verified = restore_ok and identity_ok and canary_ok
    reasons: list[str] = []
    declared_archive_mode = str(declared.get("archive_mode") or "").lower()
    live_archive_mode = str(live.get("archive_mode") or "").lower()
    if declared_archive_mode and live_archive_mode and declared_archive_mode != live_archive_mode:
        reasons.append("RECOVERY_DECLARATION_DRIFT")
    if str(live.get("data_checksums") or "").lower() == "off":
        reasons.append("DATA_CHECKSUMS_DISABLED")
    if not verified:
        reasons.append("RESTORE_CANARY_MISSING")
    else:
        reasons.append("RECOVERY_VERIFIED")
    return {
        "schema_version": RECOVERY_VERSION,
        "declared": declared,
        "live": live,
        "isolated_restore": restore,
        "downstream_canary": canary,
        "status": "verified" if verified else "partial",
        "reason_codes": reasons,
        "backup_presence_is_restore_proof": False,
        "mutation_performed": False,
        "completion_claim_allowed": verified,
    }


def _parse_time(value: object, field: str) -> datetime:
    text = _require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise SystemAwarenessError("INPUT_INVALID", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_temporary_object(
    raw: Mapping[str, object], *, now: datetime | None = None
) -> dict[str, Any]:
    data = _require_mapping(raw, "temporary_object")
    object_id = str(data.get("object_id") or "unknown")
    owner = str(data.get("owner") or "")
    expiry = data.get("expiry")
    next_consumer = str(data.get("next_consumer") or "")
    declared_pin = str(data.get("pin") or "")
    current_pin = str(data.get("current_pin") or declared_pin)
    classified = bool(owner and expiry and next_consumer)
    reasons: list[str] = []
    if not classified:
        decision = "quarantine_unclassified"
        reasons.append("TEMP_OBJECT_UNCLASSIFIED_NO_DELETE")
    else:
        expired = _parse_time(expiry, "expiry") <= (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        )
        pin_drift = not declared_pin or declared_pin != current_pin
        if expired or pin_drift:
            if data.get("rehash_ok") is True and data.get("canary_ok") is True:
                decision = "reuse_admitted_after_revalidation"
                reasons.append("TEMP_OBJECT_REUSE_ADMITTED")
            elif data.get("rehash_ok") is False or data.get("canary_ok") is False:
                decision = "retire_pending"
                reasons.append("TEMP_OBJECT_REVALIDATION_FAILED_RETIRE")
            else:
                decision = "revalidation_required"
                reasons.append("TEMP_OBJECT_REVALIDATION_REQUIRED")
        elif data.get("manifest_ok") is True and data.get("canary_ok") is True:
            decision = "reuse_admitted"
            reasons.append("TEMP_OBJECT_REUSE_ADMITTED")
        else:
            decision = "revalidation_required"
            reasons.append("TEMP_OBJECT_REVALIDATION_REQUIRED")
    return {
        "schema_version": TEMP_OBJECT_VERSION,
        "object_id": object_id,
        "owner": owner or None,
        "expiry": expiry,
        "next_consumer": next_consumer or None,
        "decision": decision,
        "reason_codes": reasons,
        "delete_performed": False,
        "automatic_delete_allowed": False,
        "completion_claim_allowed": decision.startswith("reuse_admitted"),
    }


def evaluate_trajectory_sample(
    trajectories: Sequence[Mapping[str, object]], *, sample_size: int, seed: str
) -> dict[str, Any]:
    if sample_size < 1:
        raise SystemAwarenessError("INPUT_INVALID", "sample_size must be positive")
    ranked = sorted(
        (dict(row) for row in trajectories),
        key=lambda row: hashlib.sha256(
            f"{seed}\n{row.get('event_id') or row.get('trajectory_id') or ''}".encode("utf-8")
        ).hexdigest(),
    )[:sample_size]
    reports: list[dict[str, object]] = []
    required = ("envelope", "pin", "manifest", "authority", "result_contract")
    for index, row in enumerate(ranked):
        defects = [f"{field.upper()}_MISSING" for field in required if not row.get(field)]
        authority = str(row.get("authority") or "")
        if row.get("parent_complete_claim") is True and authority != "parent_owner":
            defects.append("UNAUTHORIZED_PARENT_COMPLETION_CLAIM")
        reports.append(
            {
                "trajectory_id": str(row.get("trajectory_id") or row.get("event_id") or index),
                "source_event_ref": row.get("event_id") or row.get("source_event_ref"),
                "defect_codes": defects,
                "ok": not defects,
            }
        )
    return {
        "schema_version": TRAJECTORY_VERSION,
        "sample_seed": seed,
        "sample_size": len(reports),
        "reports": reports,
        "reason_code": "TRAJECTORY_SAMPLE_EVALUATED",
    }


def evaluate_promotion_evidence(raw: Mapping[str, object]) -> dict[str, Any]:
    """Do not let a static eval replace a live consumer canary."""

    data = _require_mapping(raw, "promotion_evidence")
    eval_passed = data.get("eval_passed") is True
    live_verified = data.get("live_consumer_verified") is True
    verified = eval_passed and live_verified
    reasons: list[str] = []
    if not eval_passed:
        reasons.append("BEHAVIOR_EVAL_NOT_VERIFIED")
    if not live_verified:
        reasons.append("LIVE_CONSUMER_NOT_VERIFIED")
    return {
        "schema_version": PROMOTION_VERSION,
        "status": "verified" if verified else "partial",
        "promotion_allowed": verified,
        "reason_codes": reasons or ["EVAL_AND_LIVE_CONSUMER_VERIFIED"],
    }


def evaluate_wakeable_wait(raw: Mapping[str, object]) -> dict[str, Any]:
    """Prove a no-positive-action wait without claiming completion or blockage."""

    data = _require_mapping(raw, "wakeable_wait")
    positive_actions = data.get("positive_actions") or []
    wake_conditions = data.get("wake_conditions") or []
    if not isinstance(positive_actions, list) or not isinstance(wake_conditions, list):
        raise SystemAwarenessError(
            "INPUT_INVALID", "positive_actions and wake_conditions must be arrays"
        )
    reconciled = all(
        data.get(field) is True
        for field in ("frontier_reconciled", "alternative_paths_checked", "prerequisites_checked")
    )
    durable = data.get("durable_surface_verified") is True
    wait_allowed = reconciled and not positive_actions and bool(wake_conditions) and durable
    reasons: list[str] = []
    if not reconciled:
        reasons.append("FRONTIER_RECONCILIATION_INCOMPLETE")
    if positive_actions:
        reasons.append("POSITIVE_ACTION_AVAILABLE")
    if not wake_conditions:
        reasons.append("WAKE_CONDITION_MISSING")
    if not durable:
        reasons.append("WAKEABLE_SURFACE_UNVERIFIED")
    return {
        "schema_version": WAKEABLE_WAIT_VERSION,
        "status": "wakeable_wait" if wait_allowed else "active_or_partial",
        "wait_allowed": wait_allowed,
        "wake_conditions": [str(value) for value in wake_conditions],
        "reason_codes": reasons or ["WAKEABLE_WAIT_NO_POSITIVE_ACTION"],
        "mutation_performed": False,
        "completion_claim_allowed": False,
        "blocked_claim_allowed": False,
    }


def _load_task_run(
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    task, task_raw = _read_json(run_dir / "task.json", "task")
    state, state_raw = _read_json(run_dir / "state.json", "state")
    if (
        task.get("schema_version") != TASK_RUN_VERSION
        or state.get("schema_version") != TASK_RUN_VERSION
    ):
        raise SystemAwarenessError("TASK_RUN_SCHEMA_DRIFT", "task-run schema drifted")
    run_id = str(task.get("run_id") or "")
    if not run_id or state.get("run_id") != run_id or run_dir.name != run_id:
        raise SystemAwarenessError("TASK_RUN_IDENTITY_DRIFT", "task-run identity disagrees")
    try:
        events_raw = (run_dir / "events.jsonl").read_bytes()
        events_text = events_raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemAwarenessError("UTF8_EVENT_INVALID", "events.jsonl is not valid UTF-8") from exc
    if "\ufffd" in events_text:
        raise SystemAwarenessError("UTF8_REPLACEMENT_CHARACTER", "events contain U+FFFD")
    if events_raw and not events_raw.endswith(b"\n"):
        raise SystemAwarenessError("EVENT_TAIL_INCOMPLETE", "events.jsonl has an incomplete tail")
    events: list[dict[str, Any]] = []
    for index, line in enumerate(events_text.splitlines(), start=1):
        try:
            event = _require_mapping(json.loads(line), f"event[{index}]")
        except json.JSONDecodeError as exc:
            raise SystemAwarenessError(
                "EVENT_JSON_INVALID", f"event line {index} is invalid"
            ) from exc
        if event.get("run_id") != run_id or event.get("schema_version") != TASK_RUN_VERSION:
            raise SystemAwarenessError(
                "TASK_RUN_IDENTITY_DRIFT", f"event line {index} identity drifted"
            )
        event["ordinal"] = index
        events.append(event)
    if state.get("events_count") != len(events):
        raise SystemAwarenessError("EVENT_HEAD_DRIFT", "state.events_count disagrees with events")
    hashes = {
        "task_sha256": _sha256_bytes(task_raw),
        "state_sha256": _sha256_bytes(state_raw),
        "events_sha256": _sha256_bytes(events_raw),
    }
    return task, state, events, hashes


def _problem_candidates(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for event in events:
        exit_code = event.get("exit_code")
        retry_class = str(event.get("retry_class") or "none")
        phase = str(event.get("phase") or "")
        if (
            (isinstance(exit_code, int) and exit_code != 0)
            or retry_class != "none"
            or FAILURE_PHASE_RE.search(phase)
        ):
            candidates.append(
                {
                    "event_id": event.get("event_id"),
                    "phase": phase,
                    "family_signature": FAMILY_NORMALIZE_RE.sub("#", phase),
                    "governing_cause": str(event.get("problem_ref") or retry_class or phase),
                    "work_key": event.get("target"),
                    "component": event.get("actor"),
                    "reason_code": "TASK_RUN_FAILURE_EVENT",
                }
            )
    return candidates


def _attempts_from_evidence(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    attempts: list[dict[str, object]] = []
    seen: set[str] = set()
    for event in events:
        refs = event.get("evidence_refs") or []
        if not isinstance(refs, list):
            continue
        event_links: list[dict[str, object]] = []
        if event.get("kind") == "result" and event.get("exit_code") == 0:
            phase = str(event.get("phase") or "").lower()
            if "ledger" in phase and any(token in phase for token in ("commit", "cas", "move")):
                link_kind = "ledger_move"
            elif any(token in phase for token in ("verified", "postland", "postcas")):
                link_kind = "verified_outcome"
            else:
                link_kind = "new_effective_evidence"
            event_links.append(
                {
                    "kind": link_kind,
                    "event_id": event.get("event_id"),
                    "target": event.get("target"),
                }
            )
        for raw_ref in refs:
            path = Path(str(raw_ref).split("#", 1)[0])
            key = os.path.normcase(str(path.resolve()))
            if key in seen or not path.is_file() or path.suffix.lower() != ".json":
                continue
            seen.add(key)
            try:
                payload, _ = _read_json(path, "usage_evidence")
            except SystemAwarenessError:
                continue
            results = payload.get("results")
            if isinstance(results, Mapping) and isinstance(results.get("results"), list):
                for index, raw_result in enumerate(results["results"]):
                    if not isinstance(raw_result, Mapping):
                        continue
                    response = raw_result.get("response")
                    response_map = dict(response) if isinstance(response, Mapping) else {}
                    usage = response_map.get("tokenUsage") or raw_result.get("tokenUsage")
                    if not isinstance(usage, Mapping):
                        continue
                    vars_raw = raw_result.get("vars")
                    vars_map = dict(vars_raw) if isinstance(vars_raw, Mapping) else {}
                    test_case = raw_result.get("testCase")
                    test_map = dict(test_case) if isinstance(test_case, Mapping) else {}
                    test_vars = test_map.get("vars")
                    test_vars_map = dict(test_vars) if isinstance(test_vars, Mapping) else {}
                    case_id = str(
                        vars_map.get("case_id")
                        or test_vars_map.get("case_id")
                        or raw_result.get("id")
                        or index
                    )
                    attempts.append(
                        {
                            "attempt_id": f"promptfoo:{case_id}",
                            "status": "accepted"
                            if raw_result.get("success") is True
                            else "rejected",
                            "usage": {"total_tokens": int(usage.get("total") or 0)},
                            "outcome_links": [dict(link) for link in event_links],
                            "evidence_ref": str(path),
                        }
                    )
            elif isinstance(results, list) and results:
                for index, raw_result in enumerate(results):
                    if not isinstance(raw_result, Mapping) or not isinstance(
                        raw_result.get("usage"), Mapping
                    ):
                        continue
                    attempts.append(
                        {
                            "attempt_id": f"{payload.get('pool_id') or path.stem}:{index}",
                            "status": str(
                                raw_result.get("status")
                                or raw_result.get("outcome")
                                or "incomplete"
                            ),
                            "usage": {
                                "total_tokens": int(raw_result["usage"].get("total_tokens") or 0)
                            },
                            "outcome_links": [dict(link) for link in event_links],
                            "evidence_ref": str(path),
                        }
                    )
            elif isinstance(payload.get("usage"), Mapping) and payload.get("status"):
                attempts.append(
                    {
                        "attempt_id": str(payload.get("run_id") or path.stem),
                        "status": str(payload.get("status")),
                        "usage": {"total_tokens": int(payload["usage"].get("total_tokens") or 0)},
                        "outcome_links": [dict(link) for link in event_links],
                        "evidence_ref": str(path),
                    }
                )
    return attempts


def _previous_problem_rows(raw: Mapping[str, object] | None) -> list[dict[str, Any]]:
    if raw is None:
        return []
    candidate: object = raw
    if isinstance(candidate, Mapping) and isinstance(candidate.get("problem_projection"), Mapping):
        candidate = candidate["problem_projection"]
    if isinstance(candidate, Mapping):
        candidate = candidate.get("problems") or []
    if not isinstance(candidate, list):
        raise SystemAwarenessError(
            "INPUT_INVALID", "previous problem projection must contain problems[]"
        )
    return [dict(row) for row in candidate if isinstance(row, Mapping)]


def scan_task_run(
    run_dir: Path,
    *,
    high_burn_threshold: int | None = None,
    previous_problem_projection: Mapping[str, object] | None = None,
    effectiveness_evidence: Sequence[Mapping[str, object]] | None = None,
    close_requested: bool = False,
) -> dict[str, Any]:
    """Real read-only consumer: turn a task-run into problem and token projections."""

    resolved = Path(run_dir).resolve()
    task, state, events, hashes = _load_task_run(resolved)
    candidates = _problem_candidates(events)
    problems = reconcile_problem_lifecycle(
        {
            "events": candidates,
            "previous": _previous_problem_rows(previous_problem_projection),
            "effectiveness_evidence": [dict(row) for row in (effectiveness_evidence or [])],
            "close_requested": close_requested,
        }
    )
    attempts = _attempts_from_evidence(events)
    episode_input: dict[str, object] = {
        "episode_id": task["run_id"],
        "attempts": attempts,
        "native_total_tokens": sum(
            int(_require_mapping(row.get("usage"), "attempt.usage").get("total_tokens") or 0)
            for row in attempts
        ),
    }
    if high_burn_threshold is not None:
        episode_input["high_burn_threshold"] = high_burn_threshold
    episode = project_episode_outcome(episode_input)
    searchable_text = "\n".join(
        f"{event.get('summary') or ''}\n"
        + "\n".join(str(ref) for ref in (event.get("evidence_refs") or []))
        for event in events
    )
    return {
        "schema_version": REPORT_VERSION,
        "consumer_id": "system_awareness_task_run_scanner",
        "authority": False,
        "completion_claim_allowed": False,
        "source": {
            "task_run_dir": str(resolved),
            "run_id": task["run_id"],
            "status": state.get("status"),
            "event_count": len(events),
            **hashes,
        },
        "problem_projection": problems,
        "episode_outcome": episode,
        "utf8": {
            "roundtrip_ok": "\ufffd" not in searchable_text,
            "searchable_sha256": _sha256_bytes(searchable_text.encode("utf-8")),
            "reason_codes": ["UTF8_PATH_ROUNDTRIP_OK", "UTF8_EVENT_SEARCHABLE"],
        },
        "reason_codes": ["SYSTEM_AWARENESS_SCAN_COMPLETED"],
    }


def _load_input(path: Path) -> dict[str, Any]:
    value, _ = _read_json(path)
    return value


def _emit(value: Mapping[str, object], output: Path | None) -> None:
    if output is not None:
        _write_json_atomic(output, value)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in (
        "completion-card",
        "episode-outcome",
        "problem",
        "identity",
        "recovery",
        "temporary-object",
        "promotion",
        "wakeable-wait",
    ):
        command = sub.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--output", type=Path)

    scan = sub.add_parser("scan-task-run")
    scan.add_argument("--task-run-dir", type=Path, required=True)
    scan.add_argument("--high-burn-threshold", type=int)
    scan.add_argument("--previous-problems", type=Path)
    scan.add_argument("--effectiveness-evidence", type=Path)
    scan.add_argument("--close-requested", action="store_true")
    scan.add_argument("--output", type=Path)

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--supervisor-root", type=Path, required=True)
    preflight.add_argument("--phase", required=True)
    preflight.add_argument("--json-schema", type=Path)
    preflight.add_argument("--require-json-object", action="store_true")
    preflight.add_argument("--output", type=Path)

    temporal = sub.add_parser("temporal")
    temporal.add_argument("--repo-manifest", type=Path, required=True)
    temporal.add_argument("--live-snapshot", type=Path, required=True)
    temporal.add_argument("--output", type=Path)

    strict = sub.add_parser("strict-json")
    strict.add_argument("--result", type=Path, required=True)
    strict.add_argument("--schema", type=Path)
    strict.add_argument("--output", type=Path)

    trajectory = sub.add_parser("trajectory")
    trajectory.add_argument("--input", type=Path, required=True)
    trajectory.add_argument("--sample-size", type=int, required=True)
    trajectory.add_argument("--seed", required=True)
    trajectory.add_argument("--output", type=Path)

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "scan-task-run":
            effectiveness_payload = (
                _load_input(args.effectiveness_evidence) if args.effectiveness_evidence else {}
            )
            effectiveness_rows = effectiveness_payload.get("effectiveness_evidence") or []
            if not isinstance(effectiveness_rows, list):
                raise SystemAwarenessError(
                    "INPUT_INVALID", "effectiveness_evidence must be an array"
                )
            value = scan_task_run(
                args.task_run_dir,
                high_burn_threshold=args.high_burn_threshold,
                previous_problem_projection=(
                    _load_input(args.previous_problems) if args.previous_problems else None
                ),
                effectiveness_evidence=[
                    dict(row) for row in effectiveness_rows if isinstance(row, Mapping)
                ],
                close_requested=args.close_requested,
            )
        elif args.command == "preflight":
            value = preflight_supervisor_root(
                args.supervisor_root,
                phase=args.phase,
                json_schema_path=args.json_schema,
                require_json_object=args.require_json_object,
            )
        elif args.command == "temporal":
            value = reconcile_temporal_identity(
                _load_input(args.repo_manifest), _load_input(args.live_snapshot)
            )
        elif args.command == "strict-json":
            try:
                text = args.result.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise SystemAwarenessError("UTF8_OR_JSON_INVALID", "result is not UTF-8") from exc
            schema = _load_input(args.schema) if args.schema else None
            value = validate_strict_json_result(text, schema)
        elif args.command == "trajectory":
            payload = _load_input(args.input)
            trajectories = payload.get("trajectories") or []
            if not isinstance(trajectories, list):
                raise SystemAwarenessError("INPUT_INVALID", "trajectories must be an array")
            value = evaluate_trajectory_sample(
                [dict(row) for row in trajectories if isinstance(row, Mapping)],
                sample_size=args.sample_size,
                seed=args.seed,
            )
        else:
            payload = _load_input(args.input)
            handlers = {
                "completion-card": evaluate_completion_card,
                "episode-outcome": project_episode_outcome,
                "problem": reconcile_problem_lifecycle,
                "identity": reconcile_identity,
                "recovery": evaluate_recovery_truth,
                "temporary-object": evaluate_temporary_object,
                "promotion": evaluate_promotion_evidence,
                "wakeable-wait": evaluate_wakeable_wait,
            }
            value = handlers[args.command](payload)
        _emit(value, args.output)
        return 0 if value.get("ok", True) is not False else 2
    except SystemAwarenessError as exc:
        print(
            json.dumps(
                {
                    "schema_version": REPORT_VERSION,
                    "ok": False,
                    "reason_code": exc.reason_code,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SystemAwarenessError",
    "evaluate_completion_card",
    "project_episode_outcome",
    "reconcile_problem_lifecycle",
    "reconcile_identity",
    "validate_strict_json_result",
    "preflight_supervisor_root",
    "reconcile_temporal_identity",
    "evaluate_recovery_truth",
    "evaluate_temporary_object",
    "evaluate_trajectory_sample",
    "evaluate_promotion_evidence",
    "evaluate_wakeable_wait",
    "scan_task_run",
    "main",
]
