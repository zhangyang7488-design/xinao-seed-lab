"""Thin horizontal system-awareness consumers over existing facts.

The task-run event chain, runtime APIs, domain ledgers, and evidence artifacts
remain authoritative.  This module derives completion, cost, problem, identity,
recovery, work-unit, and temporary-carrier decisions without creating another
scheduler, database, router, deletion authority, or completion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import exceptions as jsonschema_exceptions
from jsonschema import validators as jsonschema_validators

from services.agent_runtime.execution_contract import artifact_json_bytes
from services.agent_runtime.work_unit_lifecycle import (
    WORK_UNIT_LIFECYCLE_VERSION,
    discover_work_unit_keys,
    project_work_unit_state,
)

REPORT_VERSION = "xinao.system_awareness.report.v1"
COMPLETION_CARD_VERSION = "xinao.work_key_completion_card.v1"
EPISODE_OUTCOME_VERSION = "xinao.episode_outcome_projection.v1"
PROBLEM_PROJECTION_VERSION = "xinao.problem_projection.v1"
FRONTIER_RECONCILIATION_VERSION = "xinao.global_frontier_reconciliation.v1"
IDENTITY_VERSION = "xinao.identity_reconciliation.v1"
PREFLIGHT_VERSION = "xinao.supervisor_capability_preflight.v1"
TEMPORAL_VERSION = "xinao.temporal_identity_reconciliation.v1"
RECOVERY_VERSION = "xinao.recovery_truth.v1"
TEMP_OBJECT_VERSION = "xinao.temporary_object_lifecycle.v1"
WORKTREE_LIFECYCLE_VERSION = "xinao.worktree_lifecycle_report.v1"
WORKTREE_RECORDS_VERSION = "xinao.worktree_lifecycle_records.v1"
WORKTREE_ARCHIVE_VERSION = "xinao.worktree_archive_manifest.v1"
WORKTREE_RESTORE_VERSION = "xinao.worktree_archive_restore_receipt.v1"
WORK_UNIT_EVIDENCE_VERSION = "xinao.work_unit_finalizer_evidence.v1"
TRAJECTORY_VERSION = "xinao.trajectory_sample_evaluation.v1"
PROMOTION_VERSION = "xinao.system_awareness.promotion_evidence.v1"
WAKEABLE_WAIT_VERSION = "xinao.wakeable_wait_decision.v1"
TASK_RUN_VERSION = "codex.verified-task-run.v1"
DISPATCH_OUTCOME_PHASES = frozenset(
    {
        "worker_terminal",
        "owner_verdict",
        "owner_adopted",
        "authority_applied",
        "effect_verified",
    }
)

EXECUTION_PHASES = frozenset({"EXPLORE", "CONSTRUCT", "VERIFY", "LAND"})
FAILURE_PHASE_RE = re.compile(r"(?:reject|fail|error|blocked|invalid|unverified)", re.I)
FAMILY_NORMALIZE_RE = re.compile(r"(?:retry|attempt|wave|event|v)[-_ ]?\d+", re.I)
WORKTREE_DECLARED_STATES = frozenset(
    {
        "active",
        "paused",
        "superseded",
        "archive_required",
        "retire_requested",
        "retired",
    }
)
MAX_WORKTREE_RECORD_TTL_SECONDS = 86400
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_ENVIRONMENT_OVERRIDES = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_NAMESPACE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_WORK_TREE",
    }
)


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
    if normalized in {"accepted", "success", "succeeded", "completed", "returned"}:
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
                "invocation_status": attempt.get("invocation_status") or status,
                "evaluation_verdict": attempt.get("evaluation_verdict"),
                "cost_bucket": _attempt_bucket(status),
                "total_tokens": total_tokens if total_tokens is not None else "unknown",
                "outcome_links": links,
                "outcome_conversion": bool(links),
                "attempt_acceptance_unchanged": True,
            }
        )

    known_total = sum(by_bucket.values())
    native_total_raw = data.get("native_total_tokens")
    native_total = (
        _nonnegative_int(native_total_raw, "native_total_tokens")
        if native_total_raw is not None
        else None
    )
    conservation = (
        "unknown"
        if unknown_attempts or native_total is None
        else ("balanced" if known_total == native_total else "mismatch")
    )
    if conservation == "balanced":
        reasons.append("TOKEN_ACCOUNTING_BALANCED")
    elif conservation == "mismatch":
        reasons.append("TOKEN_ACCOUNTING_MISMATCH")
    else:
        reasons.append("TOKEN_NATIVE_TOTAL_UNOBSERVED")

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
                "problem_effectiveness_boundary_verified": status == "effective"
                and effectiveness_ok,
                "completion_claim_allowed": False,
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


def reconcile_global_frontier(raw: Mapping[str, object]) -> dict[str, Any]:
    """Validate the proof boundary for a parent-wide frontier decision.

    This is a read-only consumer over task-run facts.  A local wait or a
    transport failure can describe only its affected cone; it cannot become a
    parent-wide wait without a complete, hash-bound coverage record.
    """

    data = _require_mapping(raw, "global_frontier_reconciliation")
    parent_mainline_id = str(data.get("parent_mainline_id") or "").strip()
    event_head = str(data.get("event_head") or "").strip()
    scan_generation = str(data.get("scan_generation") or "").strip()
    if not parent_mainline_id or not event_head or not scan_generation:
        raise SystemAwarenessError(
            "INPUT_INVALID",
            "parent_mainline_id, event_head, and scan_generation are required",
        )
    raw_transactions = data.get("transactions")
    if not isinstance(raw_transactions, list):
        raise SystemAwarenessError("INPUT_INVALID", "transactions must be an array")
    transactions: list[dict[str, Any]] = []
    transaction_ids: set[str] = set()
    scope_violations: list[str] = []
    for index, raw_transaction in enumerate(raw_transactions):
        transaction = _require_mapping(raw_transaction, f"transactions[{index}]")
        transaction_id = str(
            transaction.get("transaction_id") or transaction.get("work_key") or ""
        ).strip()
        if not transaction_id or transaction_id in transaction_ids:
            scope_violations.append("DUPLICATE_OR_MISSING_TRANSACTION_ID")
        transaction_ids.add(transaction_id)
        scope = str(transaction.get("scope") or "").strip()
        if scope not in {"package", "batch", "parent"}:
            scope_violations.append("TRANSACTION_SCOPE_INVALID")
        batch_id = str(transaction.get("batch_id") or "").strip()
        package_id = str(transaction.get("package_id") or "").strip()
        work_key = str(transaction.get("work_key") or transaction_id).strip()
        if scope == "package" and (
            work_key == parent_mainline_id or (batch_id and batch_id == parent_mainline_id)
        ):
            scope_violations.append("PACKAGE_PARENT_SCOPE_COLLISION")
        if scope == "batch" and batch_id == parent_mainline_id:
            scope_violations.append("BATCH_PARENT_SCOPE_COLLISION")
        if scope == "parent" and transaction_id != parent_mainline_id:
            scope_violations.append("PARENT_SCOPE_ID_MISMATCH")
        transactions.append(
            {
                "transaction_id": transaction_id,
                "scope": scope,
                "work_key": work_key,
                "batch_id": batch_id,
                "package_id": package_id,
                "state": str(transaction.get("state") or "open"),
                "affected_cone": str(transaction.get("affected_cone") or transaction_id),
                "consumer": str(transaction.get("consumer") or ""),
            }
        )

    covered_raw = data.get("covered_transaction_ids")
    if not isinstance(covered_raw, list):
        raise SystemAwarenessError("INPUT_INVALID", "covered_transaction_ids must be an array")
    covered = {str(value).strip() for value in covered_raw if str(value).strip()}
    unknown_covered = sorted(covered - transaction_ids)
    uncovered = sorted(transaction_ids - covered)
    disposition = str(data.get("frontier_disposition") or "").strip()
    global_exhaustion_requested = disposition in {
        "durable_wait",
        "no_positive_global_candidate",
    }
    local_wait_only = disposition in {"local_wait", "blocked_cone"}
    reasons: list[str] = []
    fatal_reasons: list[str] = []
    if scope_violations:
        fatal_reasons.extend(sorted(set(scope_violations)))
        reasons.extend(sorted(set(scope_violations)))
    if unknown_covered:
        fatal_reasons.append("UNKNOWN_COVERED_TRANSACTION")
        reasons.append("UNKNOWN_COVERED_TRANSACTION")
    if uncovered:
        fatal_reasons.append("GLOBAL_COVERAGE_INCOMPLETE")
        reasons.append("GLOBAL_COVERAGE_INCOMPLETE")
    if local_wait_only:
        reasons.append("LOCAL_WAIT_SCOPE_PRESERVED")
    if global_exhaustion_requested and not covered == transaction_ids:
        fatal_reasons.append("GLOBAL_EXHAUSTION_REQUIRES_COMPLETE_COVERAGE")
        reasons.append("GLOBAL_EXHAUSTION_REQUIRES_COMPLETE_COVERAGE")
    if global_exhaustion_requested and not transactions:
        fatal_reasons.append("GLOBAL_EXHAUSTION_REQUIRES_TRANSACTION_SET")
        reasons.append("GLOBAL_EXHAUSTION_REQUIRES_TRANSACTION_SET")
    valid = not fatal_reasons and disposition in {
        "execute",
        "advance_mainline",
        "local_wait",
        "blocked_cone",
        "durable_wait",
        "no_positive_global_candidate",
    }
    parent_state = (
        "open"
        if local_wait_only or not valid
        else "waiting"
        if global_exhaustion_requested
        else "open"
    )
    receipt_core = {
        "schema_version": FRONTIER_RECONCILIATION_VERSION,
        "parent_mainline_id": parent_mainline_id,
        "event_head": event_head,
        "scan_generation": scan_generation,
        "frontier_disposition": disposition,
        "covered_transaction_ids": sorted(covered),
        "transactions": transactions,
    }
    return {
        **receipt_core,
        "receipt_sha256": hashlib.sha256(artifact_json_bytes(receipt_core)).hexdigest(),
        "status": "valid" if valid else "invalid",
        "parent_state": parent_state,
        "global_frontier_reconciled": valid and global_exhaustion_requested,
        "parent_wait_claim_allowed": valid and global_exhaustion_requested,
        "scope_violations": sorted(set(scope_violations)),
        "uncovered_transaction_ids": uncovered,
        "unknown_covered_transaction_ids": unknown_covered,
        "reason_codes": list(dict.fromkeys(reasons or ["GLOBAL_FRONTIER_RECONCILED"])),
        "authority": False,
        "completion_claim_allowed": False,
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
        "identity_boundary_verified": verified,
        "completion_claim_allowed": False,
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
        root / ".venv" / "bin" / "python",
        root / "projects" / "dual-brain-coordination" / ".venv" / "Scripts" / "python.exe",
        root / "projects" / "dual-brain-coordination" / ".venv" / "bin" / "python",
    ]
    selector_interface = False
    selector_probe: dict[str, object] = {"executed": False, "returncode": None}
    preparer_contract = False
    preparer_probe: dict[str, object] = {"executed": False, "returncode": None}
    if not selector.is_file():
        reasons.append("SUPERVISOR_SELECTOR_MISSING")
    if not preparer.is_file():
        reasons.append("COMMON_CONTRACT_PREPARER_MISSING")
    runtime = next((path for path in python_candidates if path.is_file()), None)
    if runtime is None:
        reasons.append("SUPERVISOR_RUNTIME_MISSING")
    else:
        if selector.is_file():
            selector_code = (
                "import inspect,json,sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "from services.agent_runtime.routing_policy_reader import "
                "resolve_supervisor_worker_decision as fn\n"
                "sig=inspect.signature(fn)\n"
                "ok='request' in sig.parameters and 'runtime_root' in sig.parameters\n"
                "try:\n"
                "    fn(None)\n"
                "except TypeError as exc:\n"
                "    ok=ok and 'request must be an object' in str(exc)\n"
                "else:\n"
                "    ok=False\n"
                "print(json.dumps({'ok':ok,'signature':str(sig)}))\n"
                "raise SystemExit(0 if ok else 3)\n"
            )
            try:
                completed = subprocess.run(
                    [str(runtime), "-c", selector_code, str(root)],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                )
            except (OSError, subprocess.TimeoutExpired):
                completed = None
            selector_probe = {
                "executed": completed is not None,
                "returncode": completed.returncode if completed else None,
                "stdout_sha256": _sha256_bytes(completed.stdout.encode("utf-8"))
                if completed
                else None,
            }
            selector_interface = completed is not None and completed.returncode == 0
            if not selector_interface:
                reasons.append("SUPERVISOR_SELECTOR_PROBE_FAILED")
        if preparer.is_file():
            try:
                completed = subprocess.run(
                    [str(runtime), str(preparer), "--help"],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                )
            except (OSError, subprocess.TimeoutExpired):
                completed = None
            required_help = ("--selection-receipt", "--work-key", "--output")
            preparer_contract = bool(
                completed
                and completed.returncode == 0
                and all(token in completed.stdout for token in required_help)
            )
            preparer_probe = {
                "executed": completed is not None,
                "returncode": completed.returncode if completed else None,
                "help_contract": preparer_contract,
            }
            if not preparer_contract:
                reasons.append("COMMON_CONTRACT_PREPARER_PROBE_FAILED")
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
        "selector_probe": selector_probe,
        "common_contract_preparer": preparer_contract,
        "preparer_probe": preparer_probe,
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
    repo_deployment = str(repo.get("deployment_name") or "")
    live_deployment = str(live.get("deployment_name") or "")
    repo_queue = str(repo.get("task_queue") or "")
    live_queue = str(live.get("task_queue") or "")
    repo_work_key = str(repo.get("work_key") or "")
    live_work_key = str(live.get("work_key") or "")
    repo_workflow_id = str(repo.get("workflow_id") or "")
    live_workflow_id = str(live.get("workflow_id") or "")
    live_run_id = str(live.get("run_id") or live.get("workflow_run_id") or "")
    if live.get("worker_deployment_version_supported") is False:
        reasons.append("TEMPORAL_DEPLOYMENT_VERSION_UNSUPPORTED")
    if not repo_deployment or not live_deployment:
        reasons.append("TEMPORAL_DEPLOYMENT_IDENTITY_MISSING")
    elif repo_deployment != live_deployment:
        reasons.append("TEMPORAL_DEPLOYMENT_NAME_DRIFT")
    if not repo_queue or not live_queue:
        reasons.append("TEMPORAL_TASK_QUEUE_IDENTITY_MISSING")
    elif repo_queue != live_queue:
        reasons.append("TEMPORAL_TASK_QUEUE_DRIFT")
    if not repo_work_key or not live_work_key or repo_work_key != live_work_key:
        reasons.append("TEMPORAL_WORK_KEY_IDENTITY_DRIFT")
    if (
        not repo_workflow_id
        or not live_workflow_id
        or repo_workflow_id != live_workflow_id
        or not live_run_id
    ):
        reasons.append("TEMPORAL_WORKFLOW_RUN_IDENTITY_MISSING_OR_DRIFTED")
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
            "deployment_name": repo_deployment or None,
            "build_id": repo_build or None,
            "task_queue": repo_queue or None,
            "work_key": repo_work_key or None,
            "workflow_id": repo_workflow_id or None,
        },
        "live": {
            "deployment_name": live_deployment or None,
            "current_build_id": live_build or None,
            "task_queue": live_queue or None,
            "work_key": live_work_key or None,
            "workflow_id": live_workflow_id or None,
            "run_id": live_run_id or None,
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
    restore_refs = [
        restore.get("manifest_ref"),
        restore.get("receipt_ref"),
        restore.get("authorization_ref"),
    ]
    restore_evidence_ok = all(
        _verified_hash_bound_evidence([reference]) for reference in restore_refs
    )
    restore_ok = restore.get("passed") is True and restore_evidence_ok
    source_identity = str(restore.get("source_identity") or "")
    target_identity = str(restore.get("target_identity") or "")
    identity_ok = (
        restore.get("data_identity_match") is True
        and bool(source_identity)
        and bool(target_identity)
    )
    canary_evidence_ok = bool(_verified_hash_bound_evidence([canary.get("evidence_ref")]))
    canary_ok = (
        canary.get("passed") is True
        and canary.get("real_consumer") is True
        and bool(str(canary.get("source_event_id") or ""))
        and canary_evidence_ok
    )
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
        "recovery_boundary_verified": verified,
        "completion_claim_allowed": False,
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
        "reuse_boundary_admitted": decision.startswith("reuse_admitted"),
        "completion_claim_allowed": False,
    }


def _git_bytes(root: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> tuple[bytes, int]:
    environment = os.environ.copy()
    for name in _GIT_ENVIRONMENT_OVERRIDES:
        environment.pop(name, None)
    environment.update(
        {
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        completed = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
    except OSError as exc:
        raise SystemAwarenessError("GIT_FACTS_UNAVAILABLE", f"cannot execute git: {exc}") from exc
    if completed.returncode not in allowed:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SystemAwarenessError(
            "GIT_FACTS_UNAVAILABLE",
            f"git {' '.join(arguments)} failed with {completed.returncode}: {detail[:500]}",
        )
    return completed.stdout, completed.returncode


def _git_text(root: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> tuple[str, int]:
    raw, returncode = _git_bytes(root, *arguments, allowed=allowed)
    return raw.decode("utf-8", errors="surrogateescape").strip(), returncode


def _path_identity(path: object) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).replace("\\", "/")


def _worktree_path_id(path: object) -> str:
    digest = _sha256_bytes(_path_identity(path).encode("utf-8", errors="surrogateescape"))
    return f"wt-path:{digest[:20]}"


def _path_within(path: Path, parent: Path) -> bool:
    try:
        resolved_path = os.path.normcase(str(path.resolve()))
        resolved_parent = os.path.normcase(str(parent.resolve()))
        return os.path.commonpath((resolved_path, resolved_parent)) == resolved_parent
    except ValueError:
        return False


def _protected_base_branch_ref(base_ref: str) -> str | None:
    if base_ref.startswith("refs/heads/"):
        return base_ref
    if base_ref.startswith("refs/remotes/origin/"):
        return f"refs/heads/{base_ref.removeprefix('refs/remotes/origin/')}"
    if base_ref.startswith("origin/"):
        return f"refs/heads/{base_ref.removeprefix('origin/')}"
    if base_ref.startswith("refs/") or _SHA256_RE.fullmatch(base_ref):
        return None
    return f"refs/heads/{base_ref}"


def _parse_worktree_porcelain(raw: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for item in raw.split(b"\0"):
        if not item:
            if current:
                records.append(current)
                current = {}
            continue
        label_raw, separator, value_raw = item.partition(b" ")
        label = label_raw.decode("ascii", errors="strict")
        value = value_raw.decode("utf-8", errors="surrogateescape") if separator else True
        current[label] = value
    if current:
        records.append(current)
    return records


def _hash_parts(parts: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def _dirty_facts(worktree: Path) -> dict[str, Any]:
    status_raw, _ = _git_bytes(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    parts = status_raw.split(b"\0")
    entries: list[dict[str, object]] = []
    skip_rename_source = False
    for item in parts:
        if not item:
            continue
        if skip_rename_source:
            skip_rename_source = False
            continue
        if len(item) < 3:
            raise SystemAwarenessError("GIT_STATUS_INVALID", "porcelain status entry is truncated")
        code = item[:2].decode("ascii", errors="replace")
        path = item[3:].decode("utf-8", errors="surrogateescape")
        entries.append({"code": code, "path": path})
        if code[0] in {"R", "C"} or code[1] in {"R", "C"}:
            skip_rename_source = True

    untracked_raw, _ = _git_bytes(worktree, "ls-files", "--others", "--exclude-standard", "-z")
    untracked_parts: list[bytes] = []
    for raw_path in untracked_raw.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", errors="surrogateescape")
        full = worktree / relative
        try:
            file_hash = _sha256_file(full)
            size = full.stat().st_size
            fact = f"{relative}\0{size}\0{file_hash}".encode("utf-8", errors="surrogateescape")
        except OSError:
            fact = f"{relative}\0MISSING".encode("utf-8", errors="surrogateescape")
        untracked_parts.append(fact)

    ignored_raw, _ = _git_bytes(
        worktree,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
        "--no-empty-directory",
        "-z",
    )
    ignored_parts: list[bytes] = []
    ignored_sample: list[str] = []
    for raw_path in ignored_raw.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8", errors="surrogateescape")
        if len(ignored_sample) < 20:
            ignored_sample.append(relative)
        full = worktree / relative.rstrip("/")
        try:
            stat = full.stat()
            fact = f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}".encode(
                "utf-8", errors="surrogateescape"
            )
        except OSError:
            fact = f"{relative}\0MISSING".encode("utf-8", errors="surrogateescape")
        ignored_parts.append(fact)

    working_diff, _ = _git_bytes(worktree, "diff", "--binary", "--no-ext-diff", "HEAD", "--")
    index_diff, _ = _git_bytes(
        worktree, "diff", "--cached", "--binary", "--no-ext-diff", "HEAD", "--"
    )
    fingerprint = _hash_parts([status_raw, working_diff, index_diff, *sorted(untracked_parts)])
    ignored_fingerprint = _hash_parts([ignored_raw, *sorted(ignored_parts)])
    staged = sum(1 for row in entries if row["code"] != "??" and str(row["code"])[0] != " ")
    unstaged = sum(1 for row in entries if row["code"] != "??" and str(row["code"])[1] != " ")
    untracked = sum(1 for row in entries if row["code"] == "??")
    conflicted = sum(
        1 for row in entries if row["code"] in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    )
    return {
        "facts_available": True,
        "dirty": bool(entries),
        "dirty_total": len(entries),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "ignored": len(ignored_parts),
        "ignored_material_present": bool(ignored_parts),
        "ignored_fingerprint": ignored_fingerprint,
        "ignored_sample": ignored_sample,
        "conflicted": conflicted,
        "dirty_fingerprint": fingerprint,
        "status_sample": entries[:20],
    }


def _unavailable_dirty_facts(worktree: Path) -> dict[str, Any]:
    return {
        "facts_available": False,
        "dirty": True,
        "dirty_total": 0,
        "staged": 0,
        "unstaged": 0,
        "untracked": 0,
        "ignored": 0,
        "ignored_material_present": True,
        "ignored_fingerprint": _sha256_bytes(
            f"IGNORED_FACTS_UNAVAILABLE\n{_path_identity(worktree)}".encode("utf-8")
        ),
        "ignored_sample": [],
        "conflicted": 0,
        "dirty_fingerprint": _sha256_bytes(
            f"WORKTREE_FACTS_UNAVAILABLE\n{_path_identity(worktree)}".encode("utf-8")
        ),
        "status_sample": [],
    }


def _observation_sha256(observed: Mapping[str, object]) -> str:
    identity = {
        key: observed.get(key)
        for key in (
            "path_id",
            "worktree_path",
            "head",
            "branch",
            "detached",
            "base_ref",
            "base_commit",
            "locked",
            "lock_reason",
            "prunable",
            "primary_worktree",
            "protected_base_branch",
            "facts_available",
            "facts_stable",
            "dirty_total",
            "staged",
            "unstaged",
            "untracked",
            "ignored",
            "ignored_material_present",
            "ignored_fingerprint",
            "conflicted",
            "dirty_fingerprint",
            "ahead_base",
            "behind_base",
            "head_is_ancestor_of_base",
            "head_tree_reachable_from_base",
            "cherry_unique_patch_count",
            "cherry_equivalent_patch_count",
            "commits_absorbed",
        )
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return _sha256_bytes(raw)


def _event_reference(reference: object) -> tuple[Path, str]:
    raw = str(reference or "")
    if "#" not in raw:
        raise SystemAwarenessError("WORKTREE_TASK_EVENT_REF_INVALID", "event ref needs #event-id")
    path_text, event_id = raw.rsplit("#", 1)
    event_path = Path(path_text)
    if event_path.is_dir():
        event_path /= "events.jsonl"
    if event_path.name != "events.jsonl" or not event_id:
        raise SystemAwarenessError("WORKTREE_TASK_EVENT_REF_INVALID", "invalid events.jsonl ref")
    return event_path.resolve(), event_id


def _event_prefix_sha256(event_path: Path, ordinal: int) -> str:
    try:
        lines = event_path.read_bytes().splitlines(keepends=True)
    except OSError as exc:
        raise SystemAwarenessError("WORKTREE_TASK_RUN_INVALID", "cannot read event prefix") from exc
    if ordinal < 1 or ordinal > len(lines) or not all(line.endswith(b"\n") for line in lines):
        raise SystemAwarenessError("WORKTREE_TASK_RUN_INVALID", "event prefix is incomplete")
    return _sha256_bytes(b"".join(lines[:ordinal]))


def _verified_hash_bound_evidence(refs: object) -> list[str]:
    if not isinstance(refs, list):
        return []
    verified: list[str] = []
    for raw_ref in refs:
        reference_text = str(raw_ref or "")
        if "#sha256=" not in reference_text:
            continue
        path_text, expected_sha = reference_text.rsplit("#sha256=", 1)
        if not _SHA256_RE.fullmatch(expected_sha):
            continue
        try:
            if _sha256_file(Path(path_text)) == expected_sha:
                verified.append(reference_text)
        except OSError:
            continue
    return verified


def _event_binding(
    record: Mapping[str, object],
    reference: object,
    *,
    expected_phase: str,
    require_owner: bool,
    expected_evidence: Sequence[str] = (),
    require_hash_bound_artifact: bool = False,
) -> dict[str, object]:
    try:
        event_path, event_id = _event_reference(reference)
        _, _, events, hashes = _load_task_run(event_path.parent)
    except SystemAwarenessError as exc:
        return {
            "ok": False,
            "reason_code": "WORKTREE_TASK_RUN_INVALID"
            if exc.reason_code != "WORKTREE_TASK_EVENT_REF_INVALID"
            else exc.reason_code,
            "task_run_reason_code": exc.reason_code,
        }
    event = next((row for row in events if str(row.get("event_id") or "") == event_id), None)
    if event is None:
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_NOT_FOUND"}
    if str(event.get("target") or "") != str(record.get("work_key") or ""):
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_TARGET_MISMATCH"}
    if require_owner and str(event.get("actor") or "") != str(record.get("owner") or ""):
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_OWNER_MISMATCH"}
    if (
        event.get("kind") != "result"
        or event.get("exit_code") != 0
        or str(event.get("phase") or "").lower() != expected_phase
    ):
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_OUTCOME_INVALID"}
    side_effect_id = str(event.get("side_effect_id") or "")
    if not side_effect_id:
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_SIDE_EFFECT_MISSING"}
    if require_owner and side_effect_id != str(record.get("side_effect_id") or ""):
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_SIDE_EFFECT_MISMATCH"}
    refs = event.get("evidence_refs")
    if not isinstance(refs, list) or any(token not in refs for token in expected_evidence):
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_EVIDENCE_MISMATCH"}
    if require_hash_bound_artifact:
        if not _verified_hash_bound_evidence(refs):
            return {
                "ok": False,
                "reason_code": "WORKTREE_TASK_EVENT_ARTIFACT_UNVERIFIED",
            }
    try:
        event_time = _parse_time(event.get("timestamp"), "event.timestamp")
        recorded_at = _parse_time(record.get("recorded_at"), "recorded_at")
        expires_at = _parse_time(record.get("expires_at"), "expires_at")
        prefix_sha = _event_prefix_sha256(event_path, int(event["ordinal"]))
    except SystemAwarenessError:
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_TIME_INVALID"}
    if not recorded_at <= event_time <= expires_at:
        return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_TIME_MISMATCH"}
    head = record.get("event_head")
    if require_owner:
        if not isinstance(head, Mapping):
            return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_HEAD_MISSING"}
        if (
            head.get("event_count") != event.get("ordinal")
            or head.get("event_id") != event_id
            or head.get("prefix_sha256") != prefix_sha
        ):
            return {"ok": False, "reason_code": "WORKTREE_TASK_EVENT_HEAD_MISMATCH"}
    event_for_hash = {key: value for key, value in event.items() if key != "ordinal"}
    canonical = json.dumps(
        event_for_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "ok": True,
        "event_id": event_id,
        "event_ordinal": event.get("ordinal"),
        "event_sha256": _sha256_bytes(canonical),
        "event_prefix_sha256": prefix_sha,
        "event_path": str(event_path),
        "run_id": event.get("run_id"),
        "side_effect_id": side_effect_id,
        **hashes,
    }


def _task_event_binding(
    record: Mapping[str, object], observed: Mapping[str, object]
) -> dict[str, object]:
    carrier_id = str(record.get("carrier_id") or "")
    generation = record.get("carrier_generation")
    observation = str(observed.get("observation_sha256") or "")
    evidence = (
        f"xinao-worktree-carrier:{carrier_id}:{generation}",
        f"xinao-worktree-observation-sha256:{observation}",
    )
    return _event_binding(
        record,
        record.get("task_run_event_ref"),
        expected_phase=f"worktree_lifecycle_{str(record.get('declared_state') or '').lower()}",
        require_owner=True,
        expected_evidence=evidence,
    )


def _typed_finalizer_event_binding(
    record: Mapping[str, object],
    reference: object,
    *,
    phase: str,
    allowed_kinds: frozenset[str],
) -> dict[str, object]:
    binding = _event_binding(
        record,
        reference,
        expected_phase=phase,
        require_owner=False,
        require_hash_bound_artifact=True,
    )
    if binding.get("ok") is not True:
        return binding
    try:
        event_path, event_id = _event_reference(reference)
        _, _, events, _ = _load_task_run(event_path.parent)
    except SystemAwarenessError:
        return {"ok": False, "reason_code": "WORKTREE_FINALIZER_READBACK_INVALID"}
    event = next((row for row in events if row.get("event_id") == event_id), None)
    typed = (
        _typed_work_unit_evidence(
            event.get("evidence_refs"),
            work_key=str(record.get("work_key") or ""),
            allowed_kinds=allowed_kinds,
        )
        if event
        else []
    )
    if not typed:
        return {"ok": False, "reason_code": "WORKTREE_FINALIZER_READBACK_INVALID"}
    return {**binding, "typed_readbacks": typed}


def _finalizer_bindings(record: Mapping[str, object]) -> dict[str, object]:
    raw = record.get("finalizer_event_refs")
    refs = dict(raw) if isinstance(raw, Mapping) else {}
    bindings = {
        "boundary_verified": _typed_finalizer_event_binding(
            record,
            refs.get("boundary_verified"),
            phase="work_unit_boundary_verified",
            allowed_kinds=frozenset({"boundary_verification"}),
        ),
        "land_verified": _typed_finalizer_event_binding(
            record,
            refs.get("land_verified"),
            phase="work_unit_land_verified",
            allowed_kinds=frozenset({"git_remote_ref", "pull_request"}),
        ),
    }
    effect_key = "effect_verified" if refs.get("effect_verified") else "effect_not_required"
    bindings[effect_key] = _typed_finalizer_event_binding(
        record,
        refs.get(effect_key),
        phase=f"work_unit_{effect_key}",
        allowed_kinds=frozenset(
            {"runtime_consumer" if effect_key == "effect_verified" else "effect_not_required"}
        ),
    )
    bindings["all_satisfied"] = all(
        binding.get("ok") is True for binding in bindings.values() if isinstance(binding, Mapping)
    )
    return bindings


def _archive_binding(
    record: Mapping[str, object], observed: Mapping[str, object]
) -> dict[str, object]:
    archive_raw = record.get("archive")
    if not isinstance(archive_raw, Mapping):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_MISSING"}
    archive = dict(archive_raw)
    required_text = ("manifest_path", "manifest_sha256")
    if any(not str(archive.get(field) or "") for field in required_text):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_INCOMPLETE"}
    manifest_path = Path(str(archive["manifest_path"]))
    worktree_path = Path(str(observed["worktree_path"]))
    if not manifest_path.is_absolute() or _path_within(manifest_path, worktree_path):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_LOCATION_UNSAFE"}
    try:
        manifest_raw = manifest_path.read_bytes()
        current_hash = _sha256_bytes(manifest_raw)
        manifest_text = manifest_raw.decode("utf-8-sig")
        manifest = _require_mapping(json.loads(manifest_text), "worktree_archive_manifest")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemAwarenessError):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_MISSING"}
    if current_hash.lower() != str(archive["manifest_sha256"]).lower():
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_HASH_DRIFT"}
    if "\ufffd" in manifest_text:
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_MANIFEST_INVALID"}
    if (
        manifest.get("schema_version") != WORKTREE_ARCHIVE_VERSION
        or manifest.get("authority") is not False
    ):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_MANIFEST_INVALID"}
    if manifest.get("coverage_complete") is not True:
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_COVERAGE_INCOMPLETE"}
    source = manifest.get("source")
    if not isinstance(source, Mapping):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_SOURCE_DRIFT"}
    exact_source_fields = (
        "path_id",
        "head",
        "observation_sha256",
        "dirty_fingerprint",
        "ignored_fingerprint",
    )
    if any(
        str(source.get(field) or "") != str(observed.get(field) or "")
        for field in exact_source_fields
    ) or _path_identity(source.get("worktree_path") or "") != _path_identity(
        observed["worktree_path"]
    ):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_SOURCE_DRIFT"}
    restore = manifest.get("restore_verification")
    if not isinstance(restore, Mapping):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_VERIFICATION_MISSING"}
    evidence_ref = str(restore.get("evidence_ref") or "")
    if (
        restore.get("schema_version") != WORKTREE_RESTORE_VERSION
        or restore.get("authority") is not False
        or restore.get("isolated_restore") is not True
        or restore.get("content_match") is not True
        or restore.get("source_observation_sha256") != observed.get("observation_sha256")
        or "#sha256=" not in evidence_ref
    ):
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_RESTORE_UNVERIFIED"}
    evidence_text, expected_evidence_hash = evidence_ref.rsplit("#sha256=", 1)
    evidence_path = Path(evidence_text)
    if not evidence_path.is_absolute():
        evidence_path = manifest_path.parent / evidence_path
    try:
        evidence_hash = _sha256_file(evidence_path)
    except OSError:
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_VERIFICATION_MISSING"}
    if evidence_hash != expected_evidence_hash:
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_VERIFICATION_HASH_DRIFT"}
    artifacts_raw = manifest.get("artifacts")
    if not isinstance(artifacts_raw, list) or not artifacts_raw:
        return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_ARTIFACT_MISSING"}
    artifacts: list[dict[str, object]] = []
    for index, raw_artifact in enumerate(artifacts_raw):
        if not isinstance(raw_artifact, Mapping):
            return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_ARTIFACT_INVALID"}
        artifact_path = Path(str(raw_artifact.get("path") or ""))
        if not artifact_path.is_absolute():
            artifact_path = manifest_path.parent / artifact_path
        expected_hash = str(raw_artifact.get("sha256") or "")
        if (
            not expected_hash
            or artifact_path.resolve() == manifest_path.resolve()
            or _path_within(artifact_path, worktree_path)
        ):
            return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_ARTIFACT_INVALID"}
        try:
            artifact_hash = _sha256_file(artifact_path)
        except OSError:
            return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_ARTIFACT_MISSING"}
        if artifact_hash.lower() != expected_hash.lower():
            return {"valid": False, "reason_code": "WORKTREE_ARCHIVE_ARTIFACT_HASH_DRIFT"}
        artifacts.append(
            {
                "index": index,
                "path": str(artifact_path.resolve()),
                "sha256": artifact_hash,
            }
        )
    return {
        "valid": True,
        "reason_code": "WORKTREE_ARCHIVE_VERIFIED",
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": current_hash,
        "verification_evidence_ref": str(evidence_path.resolve()),
        "verification_evidence_sha256": evidence_hash,
        "independent_restore_verified": True,
        "artifacts": artifacts,
    }


def _record_template(observed: Mapping[str, object]) -> dict[str, object]:
    return {
        "path_id": observed["path_id"],
        "carrier_id": "",
        "carrier_generation": 1,
        "worktree_path": observed["worktree_path"],
        "purpose": "",
        "owner": "",
        "declared_state": "active",
        "recorded_at": "",
        "expires_at": "",
        "work_key": "",
        "side_effect_id": "",
        "task_run_event_ref": "",
        "event_head": {
            "event_count": 0,
            "event_id": "",
            "prefix_sha256": "",
        },
        "finalizer_event_refs": {
            "boundary_verified": "",
            "land_verified": "",
            "effect_verified": "",
        },
        "base_ref": observed["base_ref"],
        "expected": {
            "head": observed["head"],
            "branch": observed["branch"],
            "dirty_fingerprint": observed["dirty_fingerprint"],
            "ignored_fingerprint": observed["ignored_fingerprint"],
            "observation_sha256": observed["observation_sha256"],
        },
    }


def evaluate_worktree_lifecycle(
    observed_raw: Mapping[str, object],
    record_raw: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive a fail-closed lifecycle decision; never remove or mutate a worktree."""

    observed = _require_mapping(observed_raw, "observed_worktree")
    reasons: list[str] = []
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    archive_status: dict[str, object] = {
        "valid": False,
        "reason_code": "WORKTREE_ARCHIVE_NOT_EVALUATED",
    }
    event_binding: dict[str, object] = {
        "ok": False,
        "reason_code": "WORKTREE_TASK_EVENT_NOT_EVALUATED",
    }
    declared_state: str | None = None
    purpose: str | None = None
    owner: str | None = None

    if record_raw is None:
        decision = "unclassified"
        reasons.append("WORKTREE_LIFECYCLE_RECORD_MISSING")
    else:
        record = _require_mapping(record_raw, "worktree_lifecycle_record")
        required = (
            "path_id",
            "carrier_id",
            "carrier_generation",
            "worktree_path",
            "purpose",
            "owner",
            "declared_state",
            "recorded_at",
            "expires_at",
            "work_key",
            "side_effect_id",
            "task_run_event_ref",
            "event_head",
            "base_ref",
            "expected",
        )
        missing = [
            field
            for field in required
            if record.get(field) is None
            or (isinstance(record.get(field), str) and not str(record.get(field)).strip())
            or (field in {"expected", "event_head"} and not record.get(field))
        ]
        if missing:
            decision = "unclassified"
            reasons.append("WORKTREE_LIFECYCLE_RECORD_INCOMPLETE")
        else:
            declared_state = str(record["declared_state"])
            purpose = str(record["purpose"])
            owner = str(record["owner"])
            expected = _require_mapping(record["expected"], "expected")
            generation = record.get("carrier_generation")
            if (
                declared_state not in WORKTREE_DECLARED_STATES
                or isinstance(generation, bool)
                or not isinstance(generation, int)
                or generation < 1
            ):
                decision = "unclassified"
                reasons.append("WORKTREE_LIFECYCLE_STATE_INVALID")
            elif str(record["path_id"]) != str(observed["path_id"]) or _path_identity(
                record["worktree_path"]
            ) != _path_identity(observed["worktree_path"]):
                decision = "record_stale"
                reasons.append("WORKTREE_LIFECYCLE_IDENTITY_DRIFT")
            elif str(record["base_ref"]) != str(observed["base_ref"]) or any(
                str(expected.get(field) or "") != str(observed.get(field) or "")
                for field in (
                    "head",
                    "branch",
                    "dirty_fingerprint",
                    "ignored_fingerprint",
                    "observation_sha256",
                )
            ):
                decision = "record_stale"
                reasons.append("WORKTREE_LIFECYCLE_FACT_DRIFT")
            else:
                try:
                    recorded_at = _parse_time(record["recorded_at"], "recorded_at")
                    expires_at = _parse_time(record["expires_at"], "expires_at")
                except SystemAwarenessError:
                    decision = "record_stale"
                    reasons.append("WORKTREE_LIFECYCLE_TIME_INVALID")
                else:
                    if (
                        recorded_at > current_time
                        or expires_at <= current_time
                        or expires_at <= recorded_at
                        or (expires_at - recorded_at).total_seconds()
                        > MAX_WORKTREE_RECORD_TTL_SECONDS
                    ):
                        decision = "record_stale"
                        reasons.append("WORKTREE_LIFECYCLE_RECORD_EXPIRED")
                    else:
                        event_binding = _task_event_binding(record, observed)
                        if event_binding.get("ok") is not True:
                            decision = "record_stale"
                            reasons.append(str(event_binding["reason_code"]))
                        elif declared_state == "retired":
                            decision = "record_stale"
                            reasons.append("WORKTREE_RETIRED_CARRIER_REAPPEARED")
                        elif declared_state == "active":
                            decision = "active"
                            reasons.append("WORKTREE_ACTIVE_PROTECTED")
                        elif declared_state == "paused":
                            decision = "paused"
                            reasons.append("WORKTREE_PAUSED_PROTECTED")
                        elif declared_state == "superseded":
                            decision = "superseded_review"
                            reasons.append("WORKTREE_SUPERSEDED_REQUIRES_RETIRE_REQUEST")
                        else:
                            archive_status = _archive_binding(record, observed)
                            needs_archive = (
                                bool(observed.get("dirty"))
                                or bool(observed.get("ignored_material_present"))
                                or not bool(observed.get("commits_absorbed"))
                            )
                            if declared_state == "archive_required":
                                if archive_status.get("valid") is True:
                                    decision = "archive_preserved_review"
                                    reasons.extend(
                                        [
                                            "WORKTREE_ARCHIVE_RESTORE_VERIFIED",
                                            "WORKTREE_ARCHIVE_NEVER_GRANTS_REMOVAL",
                                        ]
                                    )
                                else:
                                    decision = "archive_required"
                                    reasons.append(str(archive_status["reason_code"]))
                            elif (
                                observed.get("primary_worktree") is True
                                or observed.get("protected_base_branch") is True
                            ):
                                decision = "retire_blocked"
                                reasons.append("WORKTREE_PROTECTED_IDENTITY")
                            elif observed.get("locked") is True:
                                decision = "retire_blocked"
                                reasons.append("WORKTREE_LOCKED_PROTECTED")
                            elif observed.get("prunable") is True:
                                decision = "retire_blocked"
                                reasons.append("WORKTREE_PRUNABLE_STATE_REQUIRES_REPAIR")
                            elif observed.get("facts_available") is not True:
                                decision = "retire_blocked"
                                reasons.append("WORKTREE_FACTS_UNAVAILABLE")
                            elif observed.get("facts_stable") is not True:
                                decision = "retire_blocked"
                                reasons.append("WORKTREE_CONCURRENT_FACT_DRIFT")
                            elif needs_archive:
                                decision = "archive_required"
                                reasons.append("WORKTREE_ARCHIVE_REQUIRED_BEFORE_OWNER_REVIEW")
                            else:
                                finalizers = _finalizer_bindings(record)
                                if finalizers.get("all_satisfied") is not True:
                                    decision = "retire_blocked"
                                    reasons.append("WORKTREE_FINALIZERS_INCOMPLETE")
                                else:
                                    decision = "retire_candidate"
                                    reasons.append(
                                        "WORKTREE_REMOVAL_CANDIDATE_CURRENT_AUTHORITY_REQUIRED"
                                    )
                                    archive_status = {
                                        **archive_status,
                                        "finalizers": finalizers,
                                    }

    if observed.get("locked") is True and "WORKTREE_LOCKED_PROTECTED" not in reasons:
        reasons.append("WORKTREE_LOCKED_PROTECTED")
    if observed.get("facts_available") is not True:
        reasons.append("WORKTREE_FACTS_UNAVAILABLE")
    if observed.get("facts_stable") is not True:
        reasons.append("WORKTREE_CONCURRENT_FACT_DRIFT")
    if observed.get("dirty") is True:
        reasons.append("WORKTREE_DIRTY_FACTS_PRESENT")
    if observed.get("ignored_material_present") is True:
        reasons.append("WORKTREE_IGNORED_MATERIAL_PRESENT")
    if observed.get("commits_absorbed") is True:
        reasons.append("WORKTREE_COMMITTED_HISTORY_ABSORBED")
    else:
        reasons.append("WORKTREE_UNABSORBED_HISTORY_PRESENT")
        if (
            int(observed.get("cherry_unique_patch_count") or 0) == 0
            and int(observed.get("cherry_equivalent_patch_count") or 0) > 0
        ):
            reasons.append("WORKTREE_PATCH_EQUIVALENCE_INSUFFICIENT")

    return {
        "schema_version": WORKTREE_LIFECYCLE_VERSION,
        "path_id": observed["path_id"],
        "carrier_id": record_raw.get("carrier_id") if isinstance(record_raw, Mapping) else None,
        "carrier_generation": (
            record_raw.get("carrier_generation") if isinstance(record_raw, Mapping) else None
        ),
        "work_key": record_raw.get("work_key") if isinstance(record_raw, Mapping) else None,
        "worktree_path": observed["worktree_path"],
        "purpose": purpose,
        "owner": owner,
        "declared_state": declared_state,
        "decision": decision,
        "retire_ready": decision == "retire_candidate",
        "retire_ready_scope": "carrier_removal_candidate_only",
        "reason_codes": list(dict.fromkeys(reasons)),
        "observed": observed,
        "task_run_event": event_binding,
        "archive": archive_status,
        "record_template": _record_template(observed),
        "authority": False,
        "delete_authority": False,
        "delete_performed": False,
        "automatic_delete_allowed": False,
        "cleanup_action": "none",
        "current_removal_authority_required": True,
        "completion_claim_allowed": False,
    }


def _normalize_lifecycle_records(
    records_raw: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
) -> list[dict[str, object]]:
    if records_raw is None:
        return []
    if not isinstance(records_raw, Mapping):
        raise SystemAwarenessError("INPUT_INVALID", "records must be a versioned object")
    data = dict(records_raw)
    if data.get("schema_version") != WORKTREE_RECORDS_VERSION:
        raise SystemAwarenessError(
            "INPUT_INVALID", f"records schema_version must be {WORKTREE_RECORDS_VERSION}"
        )
    if data.get("authority") is not False:
        raise SystemAwarenessError("INPUT_INVALID", "worktree records must set authority=false")
    if data.get("delete_authority") is not False:
        raise SystemAwarenessError(
            "INPUT_INVALID", "worktree records must set delete_authority=false"
        )
    rows = data.get("records")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise SystemAwarenessError("INPUT_INVALID", "records must be an array")
    return [_require_mapping(row, f"records[{index}]") for index, row in enumerate(rows)]


def _retired_record_binding(record: Mapping[str, object]) -> dict[str, object]:
    if record.get("declared_state") != "retired":
        return {"ok": False, "reason_code": "WORKTREE_LIFECYCLE_ORPHAN_RECORD"}
    path_id = str(record.get("path_id") or "")
    carrier_id = str(record.get("carrier_id") or "")
    generation = record.get("carrier_generation")
    worktree_path = Path(str(record.get("worktree_path") or ""))
    if (
        not path_id
        or not carrier_id
        or not isinstance(generation, int)
        or generation < 1
        or not str(record.get("worktree_path") or "").strip()
        or path_id != _worktree_path_id(worktree_path)
    ):
        return {"ok": False, "reason_code": "WORKTREE_RETIRED_TOMBSTONE_INCOMPLETE"}
    if worktree_path.exists():
        return {
            "ok": False,
            "reason_code": "WORKTREE_RETIRED_PATH_STILL_PRESENT",
        }
    binding = _event_binding(
        record,
        record.get("task_run_event_ref"),
        expected_phase="worktree_lifecycle_retired",
        require_owner=True,
        expected_evidence=(
            f"xinao-worktree-carrier:{carrier_id}:{generation}",
            f"xinao-worktree-absence-path-id:{path_id}",
        ),
        require_hash_bound_artifact=True,
    )
    if binding.get("ok") is not True:
        return {
            "ok": False,
            "reason_code": "WORKTREE_RETIRED_TOMBSTONE_INVALID",
            "event": binding,
        }
    return {
        "ok": True,
        "reason_code": "WORKTREE_RETIRED_TOMBSTONE_VERIFIED",
        "path_id": path_id,
        "carrier_id": carrier_id,
        "carrier_generation": generation,
        "work_key": record.get("work_key"),
        "worktree_path": record.get("worktree_path"),
        "event": binding,
        "authority": False,
        "delete_authority": False,
        "completion_claim_allowed": False,
    }


def scan_worktree_lifecycle(
    repo_root: Path,
    *,
    base_ref: str = "origin/main",
    records: Mapping[str, object] | Sequence[Mapping[str, object]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect every linked worktree from stable Git porcelain and project lifecycle receipts."""

    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise SystemAwarenessError("GIT_FACTS_UNAVAILABLE", f"repo root missing: {root}")
    base_commit, _ = _git_text(root, "rev-parse", "--verify", base_ref)
    base_tree_rows, _ = _git_text(root, "log", "--format=%T", base_commit)
    base_trees = {row for row in base_tree_rows.splitlines() if row}
    porcelain, _ = _git_bytes(root, "worktree", "list", "--porcelain", "-z")
    inventory_sha256 = _sha256_bytes(porcelain)
    worktree_rows = _parse_worktree_porcelain(porcelain)
    lifecycle_records = _normalize_lifecycle_records(records)
    by_path: dict[str, dict[str, object]] = {}
    duplicate_paths: set[str] = set()
    carrier_instances: set[tuple[str, object]] = set()
    duplicate_carriers: set[tuple[str, object]] = set()
    for record in lifecycle_records:
        if not str(record.get("worktree_path") or "").strip():
            raise SystemAwarenessError(
                "INPUT_INVALID", "every worktree record requires worktree_path"
            )
        key = _path_identity(record.get("worktree_path") or "")
        if key in by_path:
            duplicate_paths.add(key)
        by_path[key] = record
        carrier_instance = (
            str(record.get("carrier_id") or ""),
            record.get("carrier_generation"),
        )
        if carrier_instance in carrier_instances:
            duplicate_carriers.add(carrier_instance)
        carrier_instances.add(carrier_instance)

    reports: list[dict[str, Any]] = []
    observed_paths: set[str] = set()
    protected_base_ref = _protected_base_branch_ref(base_ref)
    for index, row in enumerate(worktree_rows):
        worktree_text = str(row.get("worktree") or "")
        if not worktree_text:
            raise SystemAwarenessError(
                "GIT_FACTS_UNAVAILABLE", "worktree inventory path is missing"
            )
        worktree_path = Path(worktree_text).resolve()
        path_key = _path_identity(worktree_path)
        observed_paths.add(path_key)
        branch = str(row.get("branch") or "")
        detached = row.get("detached") is True
        head = str(row.get("HEAD") or "")
        if not head:
            raise SystemAwarenessError("GIT_FACTS_UNAVAILABLE", "worktree HEAD is missing")
        if worktree_path.is_dir():
            try:
                dirty_before = _dirty_facts(worktree_path)
            except SystemAwarenessError:
                dirty_before = _unavailable_dirty_facts(worktree_path)
        else:
            dirty_before = _unavailable_dirty_facts(worktree_path)
        ahead_text, _ = _git_text(root, "rev-list", "--count", f"{base_commit}..{head}")
        behind_text, _ = _git_text(root, "rev-list", "--count", f"{head}..{base_commit}")
        _, ancestor_code = _git_bytes(
            root, "merge-base", "--is-ancestor", head, base_commit, allowed=(0, 1)
        )
        head_tree, _ = _git_text(root, "rev-parse", f"{head}^{{tree}}")
        try:
            cherry_text, _ = _git_text(root, "cherry", base_commit, head)
        except SystemAwarenessError:
            cherry_rows: list[str] = []
            cherry_facts_available = False
        else:
            cherry_rows = [line for line in cherry_text.splitlines() if line]
            cherry_facts_available = True
        cherry_unique = sum(1 for line in cherry_rows if line.startswith("+"))
        cherry_equivalent = sum(1 for line in cherry_rows if line.startswith("-"))
        head_is_ancestor = ancestor_code == 0
        tree_reachable = head_tree in base_trees
        commits_absorbed = head_is_ancestor
        if dirty_before.get("facts_available") is True and worktree_path.is_dir():
            try:
                dirty_after = _dirty_facts(worktree_path)
            except SystemAwarenessError:
                dirty_after = _unavailable_dirty_facts(worktree_path)
        else:
            dirty_after = dirty_before
        facts_stable = (
            dirty_before.get("facts_available") is True
            and dirty_after.get("facts_available") is True
            and dirty_before.get("dirty_fingerprint") == dirty_after.get("dirty_fingerprint")
            and dirty_before.get("ignored_fingerprint") == dirty_after.get("ignored_fingerprint")
        )
        dirty = dict(dirty_after)
        dirty["facts_stable"] = facts_stable
        if not facts_stable:
            dirty["dirty"] = True
        lock_value = row.get("locked")
        prunable_value = row.get("prunable")
        observed: dict[str, object] = {
            "path_id": _worktree_path_id(worktree_path),
            "worktree_path": str(worktree_path),
            "head": head,
            "branch": branch or None,
            "detached": detached,
            "base_ref": base_ref,
            "base_commit": base_commit,
            "locked": lock_value is not None,
            "lock_reason": lock_value if isinstance(lock_value, str) else None,
            "prunable": prunable_value is not None,
            "prunable_reason": (prunable_value if isinstance(prunable_value, str) else None),
            "primary_worktree": index == 0,
            "protected_base_branch": bool(protected_base_ref and branch == protected_base_ref),
            **dirty,
            "ahead_base": int(ahead_text),
            "behind_base": int(behind_text),
            "head_is_ancestor_of_base": head_is_ancestor,
            "head_tree_reachable_from_base": tree_reachable,
            "cherry_unique_patch_count": cherry_unique,
            "cherry_equivalent_patch_count": cherry_equivalent,
            "cherry_facts_available": cherry_facts_available,
            "commits_absorbed": commits_absorbed,
        }
        observed["observation_sha256"] = _observation_sha256(observed)
        record = by_path.get(path_key)
        record_instance = (
            (str(record.get("carrier_id") or ""), record.get("carrier_generation"))
            if record
            else None
        )
        if path_key in duplicate_paths or record_instance in duplicate_carriers:
            record = None
            report = evaluate_worktree_lifecycle(observed, record, now=now)
            report["reason_codes"].insert(0, "WORKTREE_LIFECYCLE_RECORD_DUPLICATE")
        else:
            report = evaluate_worktree_lifecycle(observed, record, now=now)
        reports.append(report)

    final_porcelain, _ = _git_bytes(root, "worktree", "list", "--porcelain", "-z")
    final_base_commit, _ = _git_text(root, "rev-parse", "--verify", base_ref)
    scan_snapshot_stable = (
        _sha256_bytes(final_porcelain) == inventory_sha256 and final_base_commit == base_commit
    )
    if not scan_snapshot_stable:
        for report in reports:
            if report["decision"] == "retire_candidate":
                report["decision"] = "retire_blocked"
                report["retire_ready"] = False
            report["reason_codes"] = list(
                dict.fromkeys(["WORKTREE_SCAN_SNAPSHOT_DRIFT", *report["reason_codes"]])
            )

    orphan_records: list[dict[str, object]] = []
    retired_carriers: list[dict[str, object]] = []
    for row in lifecycle_records:
        if _path_identity(row.get("worktree_path") or "") in observed_paths:
            continue
        retired = _retired_record_binding(row)
        if retired.get("ok") is True:
            retired_carriers.append(retired)
        else:
            orphan_records.append(
                {
                    "path_id": row.get("path_id"),
                    "carrier_id": row.get("carrier_id"),
                    "carrier_generation": row.get("carrier_generation"),
                    "worktree_path": row.get("worktree_path"),
                    "reason_code": retired.get("reason_code", "WORKTREE_LIFECYCLE_ORPHAN_RECORD"),
                }
            )
    counts: dict[str, int] = defaultdict(int)
    for report in reports:
        counts[str(report["decision"])] += 1
    git_version, _ = _git_text(root, "--version")
    attention_decisions = {
        "unclassified",
        "record_stale",
        "superseded_review",
        "archive_required",
        "retire_blocked",
        "retire_candidate",
    }
    attention_count = sum(counts.get(decision, 0) for decision in attention_decisions) + len(
        orphan_records
    )
    return {
        "schema_version": WORKTREE_LIFECYCLE_VERSION,
        "consumer_id": "worktree_lifecycle_scanner",
        "authority": False,
        "delete_authority": False,
        "delete_performed": False,
        "automatic_delete_allowed": False,
        "completion_claim_allowed": False,
        "source": {
            "repo_root": str(root),
            "base_ref": base_ref,
            "base_commit": base_commit,
            "git_version": git_version,
            "inventory_command": "git worktree list --porcelain -z",
            "inventory_sha256": inventory_sha256,
            "scan_snapshot_stable": scan_snapshot_stable,
            "git_optional_locks": False,
            "inherited_git_environment_sanitized": True,
        },
        "worktrees": reports,
        "orphan_records": orphan_records,
        "retired_carriers": retired_carriers,
        "summary": {
            "worktree_count": len(reports),
            "record_count": len(lifecycle_records),
            "decision_counts": dict(sorted(counts.items())),
            "retire_ready_count": counts.get("retire_candidate", 0),
            "retired_count": len(retired_carriers),
            "unclassified_count": counts.get("unclassified", 0),
            "archive_required_count": counts.get("archive_required", 0),
            "attention_count": attention_count,
            "forest_status": "attention_required" if attention_count else "declared",
            "logical_main_count": sum(
                1 for report in reports if report["observed"].get("primary_worktree") is True
            ),
        },
        "reason_codes": ["WORKTREE_LIFECYCLE_SCAN_COMPLETED"],
    }


def _iso_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def publish_worktree_lifecycle_record(
    repo_root: Path,
    records_path: Path,
    *,
    worktree_path: Path,
    task_run_event_ref: str,
    carrier_id: str,
    carrier_generation: int,
    purpose: str,
    owner: str,
    declared_state: str,
    work_key: str,
    side_effect_id: str,
    base_ref: str = "origin/main",
    ttl_seconds: int = 3600,
    finalizer_event_refs: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Publish one hashable carrier record from an already appended task-run event."""

    if declared_state not in WORKTREE_DECLARED_STATES:
        raise SystemAwarenessError("INPUT_INVALID", "unsupported declared worktree state")
    if not 60 <= ttl_seconds <= MAX_WORKTREE_RECORD_TTL_SECONDS:
        raise SystemAwarenessError("INPUT_INVALID", "record TTL is outside the bounded range")
    if carrier_generation < 1:
        raise SystemAwarenessError("INPUT_INVALID", "carrier_generation must be positive")
    required_text = {
        "carrier_id": carrier_id,
        "purpose": purpose,
        "owner": owner,
        "work_key": work_key,
        "side_effect_id": side_effect_id,
        "task_run_event_ref": task_run_event_ref,
    }
    if any(not str(value).strip() for value in required_text.values()):
        raise SystemAwarenessError("INPUT_INVALID", "record identity fields must be non-empty")

    target_path = Path(worktree_path).resolve()
    output = Path(records_path).resolve()
    if output.exists():
        existing_payload, _ = _read_json(output, "worktree_lifecycle_records")
        existing_records = _normalize_lifecycle_records(existing_payload)
        raw_floors = existing_payload.get("generation_floors")
        generation_floors = (
            {str(key): int(value) for key, value in raw_floors.items()}
            if isinstance(raw_floors, Mapping)
            else {}
        )
    else:
        existing_records = []
        generation_floors = {}
    same_path = next(
        (
            row
            for row in existing_records
            if _path_identity(row.get("worktree_path") or "") == _path_identity(target_path)
        ),
        None,
    )
    same_instance = same_path and (
        same_path.get("carrier_id") == carrier_id
        and same_path.get("carrier_generation") == carrier_generation
    )
    prior_floor = max(
        [
            generation_floors.get(carrier_id, 0),
            *[
                int(row.get("carrier_generation") or 0)
                for row in existing_records
                if row.get("carrier_id") == carrier_id
            ],
        ]
    )
    if not same_instance and carrier_generation <= prior_floor:
        raise SystemAwarenessError(
            "WORKTREE_CARRIER_GENERATION_REUSED",
            "a recreated carrier must advance its generation",
        )
    if any(
        row is not same_path
        and row.get("carrier_id") == carrier_id
        and row.get("carrier_generation") == carrier_generation
        for row in existing_records
    ):
        raise SystemAwarenessError(
            "WORKTREE_CARRIER_GENERATION_REUSED", "carrier generation already exists"
        )

    event_path, event_id = _event_reference(task_run_event_ref)
    _, _, task_events, _ = _load_task_run(event_path.parent)
    event = next((row for row in task_events if row.get("event_id") == event_id), None)
    if event is None:
        raise SystemAwarenessError("WORKTREE_TASK_EVENT_NOT_FOUND", "event does not exist")
    event_time = _parse_time(event.get("timestamp"), "event.timestamp")
    event_head = {
        "event_count": event.get("ordinal"),
        "event_id": event_id,
        "prefix_sha256": _event_prefix_sha256(event_path, int(event.get("ordinal") or 0)),
    }

    if declared_state == "retired":
        if same_path is None:
            raise SystemAwarenessError(
                "WORKTREE_RETIRED_TOMBSTONE_INCOMPLETE",
                "retirement requires the prior carrier record",
            )
        record = dict(same_path)
    else:
        scan = scan_worktree_lifecycle(repo_root, base_ref=base_ref)
        report = next(
            (
                row
                for row in scan["worktrees"]
                if _path_identity(row.get("worktree_path") or "") == _path_identity(target_path)
            ),
            None,
        )
        if report is None:
            raise SystemAwarenessError(
                "GIT_FACTS_UNAVAILABLE", "worktree is not present in the Git inventory"
            )
        record = dict(report["record_template"])
    record.update(
        {
            "carrier_id": carrier_id,
            "carrier_generation": carrier_generation,
            "worktree_path": str(target_path),
            "purpose": purpose,
            "owner": owner,
            "declared_state": declared_state,
            "recorded_at": _iso_time(event_time),
            "expires_at": _iso_time(event_time + timedelta(seconds=ttl_seconds)),
            "work_key": work_key,
            "side_effect_id": side_effect_id,
            "task_run_event_ref": task_run_event_ref,
            "event_head": event_head,
            "finalizer_event_refs": dict(
                finalizer_event_refs or record.get("finalizer_event_refs") or {}
            ),
        }
    )
    if declared_state == "retired":
        retired = _retired_record_binding(record)
        if retired.get("ok") is not True:
            raise SystemAwarenessError(
                str(retired.get("reason_code") or "WORKTREE_RETIRED_TOMBSTONE_INVALID"),
                "retired carrier did not pass physical absence and event readback",
            )
    else:
        current_scan = scan_worktree_lifecycle(repo_root, base_ref=base_ref)
        current_report = next(
            row
            for row in current_scan["worktrees"]
            if _path_identity(row.get("worktree_path") or "") == _path_identity(target_path)
        )
        binding = _task_event_binding(record, current_report["observed"])
        if binding.get("ok") is not True:
            raise SystemAwarenessError(
                str(binding.get("reason_code") or "WORKTREE_TASK_RUN_INVALID"),
                "record event does not bind the current carrier observation",
            )

    rows = [row for row in existing_records if row is not same_path]
    rows.append(record)
    rows.sort(key=lambda row: _path_identity(row.get("worktree_path") or ""))
    payload = {
        "schema_version": WORKTREE_RECORDS_VERSION,
        "authority": False,
        "delete_authority": False,
        "generation_floors": {
            **generation_floors,
            carrier_id: max(prior_floor, carrier_generation),
        },
        "records": rows,
    }
    output_sha = _write_json_atomic(output, payload)
    return {
        "schema_version": WORKTREE_RECORDS_VERSION,
        "status": "record_published",
        "records_path": str(output),
        "records_sha256": output_sha,
        "record": record,
        "next_required_event": {
            "phase": "worktree_lifecycle_records_published",
            "target": work_key,
            "evidence_ref": f"{output}#sha256={output_sha}",
        },
        "mutation_performed": True,
        "git_mutation_performed": False,
        "authority": False,
        "delete_authority": False,
        "completion_claim_allowed": False,
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
    event_ids = [str(event.get("event_id") or "") for event in events]
    if not all(event_ids) or len(set(event_ids)) != len(event_ids):
        raise SystemAwarenessError("EVENT_ID_INVALID", "event IDs are missing or duplicated")
    if events and state.get("current_phase") != events[-1].get("phase"):
        raise SystemAwarenessError(
            "EVENT_HEAD_DRIFT", "state.current_phase disagrees with event head"
        )
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
        retry_class = str(event.get("retry_class") or "none").lower()
        phase = str(event.get("phase") or "")
        if (
            (isinstance(exit_code, int) and exit_code != 0)
            or retry_class != "none"
            or FAILURE_PHASE_RE.search(phase)
        ):
            candidate = {
                "event_id": event.get("event_id"),
                "phase": phase,
                "family_signature": FAMILY_NORMALIZE_RE.sub("#", phase),
                "governing_cause": str(
                    event.get("problem_ref")
                    or event.get("reason_code")
                    or (retry_class if retry_class != "none" else phase)
                ),
                "work_key": event.get("target"),
                "component": event.get("actor"),
                "reason_code": str(event.get("reason_code") or "TASK_RUN_FAILURE_EVENT"),
            }
            for flag in (
                "capability_gap",
                "missing_consumer",
                "governing_assumption",
                "cross_entrypoint",
                "control_boundary",
                "relevant_to_parent",
                "expected_net_benefit_positive",
            ):
                if flag in event:
                    candidate[flag] = event.get(flag)
            candidates.append(candidate)
    return candidates


def _attempts_from_evidence(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    attempts: list[dict[str, object]] = []
    links_by_path: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in events:
        refs = event.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or event.get("kind") != "result"
            or event.get("exit_code") != 0
        ):
            continue
        phase = str(event.get("phase") or "").lower()
        link_kind = ""
        if "ledger" in phase and any(token in phase for token in ("commit", "cas", "move")):
            link_kind = "ledger_move"
        elif phase in {
            "work_unit_effect_verified",
            "problem_effectiveness_observed",
            "postland_effect_verified",
            "postcas_verified",
        }:
            link_kind = "verified_outcome"
        if not link_kind:
            continue
        link = {
            "kind": link_kind,
            "event_id": event.get("event_id"),
            "target": event.get("target"),
        }
        for raw_ref in refs:
            path = Path(str(raw_ref).split("#", 1)[0])
            key = os.path.normcase(str(path.resolve()))
            if link not in links_by_path[key]:
                links_by_path[key].append(dict(link))

    seen: set[str] = set()
    for event in events:
        refs = event.get("evidence_refs") or []
        if not isinstance(refs, list):
            continue
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
            event_links = links_by_path.get(key, [])
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
                            "status": "accepted",
                            "invocation_status": "returned",
                            "evaluation_verdict": "passed"
                            if raw_result.get("success") is True
                            else "failed",
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


def _native_usage_total_from_events(
    events: Sequence[Mapping[str, object]],
) -> tuple[int | None, dict[str, object] | None]:
    for event in reversed(events):
        if (
            event.get("kind") != "result"
            or event.get("exit_code") != 0
            or str(event.get("phase") or "").lower() != "native_usage_total_observed"
        ):
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for raw_ref in refs:
            reference = str(raw_ref or "")
            if "#sha256=" not in reference:
                continue
            path_text, expected_sha = reference.rsplit("#sha256=", 1)
            if not _SHA256_RE.fullmatch(expected_sha):
                continue
            try:
                raw = Path(path_text).read_bytes()
                payload = _require_mapping(json.loads(raw.decode("utf-8-sig")), "native_usage")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemAwarenessError):
                continue
            total = payload.get("native_total_tokens")
            if (
                _sha256_bytes(raw) != expected_sha
                or isinstance(total, bool)
                or not isinstance(total, int)
                or total < 0
            ):
                continue
            return total, {
                "path": str(Path(path_text).resolve()),
                "sha256": expected_sha,
                "event_id": event.get("event_id"),
                "event_ordinal": event.get("ordinal"),
            }
    return None, None


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


def _latest_problem_projection_binding(
    events: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    for event in reversed(events):
        refs = event.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for raw_ref in reversed(refs):
            reference = str(raw_ref or "")
            if "#sha256=" not in reference:
                continue
            path_text, expected_sha = reference.rsplit("#sha256=", 1)
            if not _SHA256_RE.fullmatch(expected_sha):
                continue
            path = Path(path_text)
            try:
                raw = path.read_bytes()
                payload = _require_mapping(
                    json.loads(raw.decode("utf-8-sig")), "problem_projection_artifact"
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemAwarenessError):
                continue
            if _sha256_bytes(raw) != expected_sha:
                continue
            candidate = (
                payload.get("problem_projection")
                if isinstance(payload.get("problem_projection"), Mapping)
                else payload
            )
            if (
                not isinstance(candidate, Mapping)
                or candidate.get("schema_version") != PROBLEM_PROJECTION_VERSION
                or candidate.get("authority") is not False
                or not isinstance(candidate.get("problems"), list)
            ):
                continue
            return dict(candidate), {
                "path": str(path.resolve()),
                "sha256": expected_sha,
                "event_id": event.get("event_id"),
                "event_ordinal": event.get("ordinal"),
                "authority": False,
            }
    return None, None


def _effectiveness_evidence_from_events(
    events: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    allowed_kinds = {
        "real_consumer",
        "live_canary",
        "monitoring_window",
        "effectiveness_window",
        "observation_window",
    }
    for event in events:
        if (
            event.get("kind") != "result"
            or event.get("exit_code") != 0
            or str(event.get("phase") or "").lower() != "problem_effectiveness_observed"
        ):
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for raw_ref in refs:
            reference = str(raw_ref or "")
            if "#sha256=" not in reference:
                continue
            path_text, expected_sha = reference.rsplit("#sha256=", 1)
            if not _SHA256_RE.fullmatch(expected_sha):
                continue
            try:
                raw = Path(path_text).read_bytes()
                payload = _require_mapping(
                    json.loads(raw.decode("utf-8-sig")), "effectiveness_evidence"
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemAwarenessError):
                continue
            if _sha256_bytes(raw) != expected_sha:
                continue
            candidates = payload.get("effectiveness_evidence")
            candidates = candidates if isinstance(candidates, list) else [payload]
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                kind = str(candidate.get("kind") or "")
                if kind not in allowed_kinds or candidate.get("passed") is not True:
                    continue
                row = dict(candidate)
                row["source_event_id"] = event.get("event_id")
                row["evidence_ref"] = reference
                if row not in rows:
                    rows.append(row)
    return rows


def _latest_worktree_records_binding(
    events: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    for event in reversed(events):
        refs = event.get("evidence_refs")
        if not isinstance(refs, list):
            continue
        for raw_ref in reversed(refs):
            reference = str(raw_ref or "")
            if "#sha256=" not in reference:
                continue
            path_text, expected_sha = reference.rsplit("#sha256=", 1)
            if not _SHA256_RE.fullmatch(expected_sha):
                continue
            path = Path(path_text)
            try:
                raw = path.read_bytes()
                if _sha256_bytes(raw) != expected_sha:
                    continue
                payload = _require_mapping(
                    json.loads(raw.decode("utf-8-sig")), "worktree_lifecycle_records"
                )
                _normalize_lifecycle_records(payload)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemAwarenessError):
                continue
            return payload, {
                "path": str(path.resolve()),
                "sha256": expected_sha,
                "event_id": event.get("event_id"),
                "event_ordinal": event.get("ordinal"),
                "authority": False,
            }
    return None, None


def _typed_work_unit_evidence(
    refs: object,
    *,
    work_key: str,
    allowed_kinds: frozenset[str],
) -> list[dict[str, object]]:
    if not isinstance(refs, list):
        return []
    verified: list[dict[str, object]] = []
    for raw_ref in refs:
        reference = str(raw_ref or "")
        if "#sha256=" not in reference:
            continue
        path_text, expected_sha = reference.rsplit("#sha256=", 1)
        if not _SHA256_RE.fullmatch(expected_sha):
            continue
        path = Path(path_text)
        try:
            raw = path.read_bytes()
            payload = _require_mapping(
                json.loads(raw.decode("utf-8-sig")), "work_unit_finalizer_evidence"
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, SystemAwarenessError):
            continue
        kind = str(payload.get("kind") or "")
        if (
            _sha256_bytes(raw) != expected_sha
            or payload.get("schema_version") != WORK_UNIT_EVIDENCE_VERSION
            or payload.get("authority") is not False
            or payload.get("completion_claim_allowed") is not False
            or payload.get("work_key") != work_key
            or kind not in allowed_kinds
            or not str(payload.get("subject") or "").strip()
            or not str(payload.get("observed_value") or "").strip()
            or payload.get("readback_verified") is not True
        ):
            continue
        verified.append(
            {
                "reference": reference,
                "kind": kind,
                "subject": payload.get("subject"),
                "observed_value": payload.get("observed_value"),
            }
        )
    return verified


def _work_unit_finalizer(
    events: Sequence[Mapping[str, object]], phase: str, work_key: str
) -> dict[str, object]:
    allowed_by_phase = {
        "work_unit_boundary_verified": frozenset({"boundary_verification"}),
        "work_unit_land_verified": frozenset({"git_remote_ref", "pull_request"}),
        "work_unit_effect_verified": frozenset({"runtime_consumer"}),
        "work_unit_effect_not_required": frozenset({"effect_not_required"}),
    }
    allowed_kinds = allowed_by_phase[phase]
    candidates = [
        (event, evidence)
        for event in events
        for evidence in [
            _typed_work_unit_evidence(
                event.get("evidence_refs"),
                work_key=work_key,
                allowed_kinds=allowed_kinds,
            )
        ]
        if str(event.get("phase") or "").lower() == phase
        and event.get("kind") == "result"
        and event.get("exit_code") == 0
        and str(event.get("side_effect_id") or "")
        and bool(evidence)
    ]
    if not candidates:
        return {"status": "pending", "event_ref": None, "evidence_refs": []}
    event, typed_evidence = candidates[-1]
    return {
        "status": "evidence_bound",
        "event_ref": event.get("event_id"),
        "event_ordinal": event.get("ordinal"),
        "side_effect_id": event.get("side_effect_id"),
        "evidence_refs": list(event.get("evidence_refs") or []),
        "typed_readbacks": typed_evidence,
    }


def _dispatch_outcome_projection_if_present(
    run_dir: Path,
    events: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Lazily consume the canonical v2 projection only when its event seam is present."""

    candidate_present = any(
        str(event.get("phase") or "").lower() in DISPATCH_OUTCOME_PHASES
        and isinstance(event.get("evidence_refs"), list)
        and any(
            isinstance(reference, str) and "#sha256=" in reference
            for reference in event.get("evidence_refs") or []
        )
        for event in events
    )
    if not candidate_present:
        return None

    from services.agent_runtime.dispatch_economics import (
        OUTCOME_PROJECTION_SCHEMA,
        DispatchEconomicsError,
        project_dispatch_outcomes,
    )

    try:
        projection = project_dispatch_outcomes(run_dir)
    except DispatchEconomicsError as exc:
        raise SystemAwarenessError(
            "DISPATCH_OUTCOME_PROJECTION_INVALID",
            f"dispatch outcome v2 projection failed: {exc}",
        ) from exc
    if int(projection.get("event_count") or 0) == 0:
        return None
    if (
        projection.get("schema_version") != OUTCOME_PROJECTION_SCHEMA
        or projection.get("authority") is not False
        or projection.get("completion_claim_allowed") is not False
    ):
        raise SystemAwarenessError(
            "DISPATCH_OUTCOME_PROJECTION_INVALID",
            "dispatch outcome projection crossed its non-authoritative boundary",
        )
    return dict(projection)


def _frontier_reconciliation_from_events(
    events: Sequence[Mapping[str, object]],
) -> dict[str, Any] | None:
    """Consume the newest explicit parent-frontier receipt, if one exists."""

    candidates: list[Mapping[str, object]] = []
    for event in events:
        embedded = event.get("global_frontier_reconciliation")
        if isinstance(embedded, Mapping):
            candidates.append(embedded)
        elif str(event.get("kind") or event.get("phase") or "") in {
            "global_frontier_reconciliation",
            "frontier_reconciliation",
        }:
            candidates.append(event)
    if not candidates:
        return None
    try:
        return reconcile_global_frontier(candidates[-1])
    except SystemAwarenessError as exc:
        return {
            "schema_version": FRONTIER_RECONCILIATION_VERSION,
            "status": "invalid",
            "parent_state": "open",
            "global_frontier_reconciled": False,
            "parent_wait_claim_allowed": False,
            "reason_codes": [exc.code, "GLOBAL_FRONTIER_RECEIPT_INVALID"],
            "authority": False,
            "completion_claim_allowed": False,
        }


def project_work_unit_lifecycle(
    task: Mapping[str, object],
    state: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Project one logical work identity across direct, Temporal, Git and runtime carriers."""

    records_payload, records_binding = _latest_worktree_records_binding(events)
    # A task-run target is free text (paths, refs and component names are common),
    # so only typed work-unit events or hash-bound carrier records may introduce
    # a logical work identity.  Prefix guessing would manufacture false units.
    work_keys = discover_work_unit_keys(events)
    if records_payload:
        work_keys.update(
            str(record.get("work_key"))
            for record in records_payload.get("records") or []
            if isinstance(record, Mapping) and str(record.get("work_key") or "").strip()
        )
    ordered_work_keys = sorted(work_keys) or [f"wk:task-run:{task.get('run_id')}"]
    projections: list[dict[str, object]] = []
    for work_key in ordered_work_keys:
        relevant = [dict(event) for event in events if str(event.get("target") or "") == work_key]
        lifecycle = project_work_unit_state(events, work_key)
        current_state = str(lifecycle["state"])
        if current_state == "unbound":
            current_state = "planned"
        invalid_transitions = list(lifecycle["invalid_transitions"])
        boundary = _work_unit_finalizer(relevant, "work_unit_boundary_verified", work_key)
        land = _work_unit_finalizer(relevant, "work_unit_land_verified", work_key)
        effect = _work_unit_finalizer(relevant, "work_unit_effect_verified", work_key)
        effect_not_required = _work_unit_finalizer(
            relevant, "work_unit_effect_not_required", work_key
        )
        effect_satisfied = (
            effect.get("status") == "evidence_bound"
            or effect_not_required.get("status") == "evidence_bound"
        )
        all_parent_predicates_observed = (
            boundary.get("status") == "evidence_bound"
            and land.get("status") == "evidence_bound"
            and effect_satisfied
            and current_state in {"effect_verified", "effect_not_required"}
            and not invalid_transitions
        )
        bindings: list[dict[str, object]] = []
        for event in relevant:
            binding = {
                key: event.get(key)
                for key in (
                    "event_id",
                    "ordinal",
                    "actor",
                    "side_effect_id",
                    "pool_id",
                    "workflow_id",
                    "workflow_run_id",
                    "lane",
                )
                if event.get(key) is not None
            }
            if any(key in binding for key in ("pool_id", "workflow_id", "lane")):
                bindings.append(binding)
        latest = relevant[-1] if relevant else None
        projections.append(
            {
                "work_key": work_key,
                "state": current_state,
                "next_consumer": lifecycle["next_consumer"],
                "event_count": len(relevant),
                "event_head": {
                    "event_id": latest.get("event_id") if latest else None,
                    "event_ordinal": latest.get("ordinal") if latest else None,
                    "phase": latest.get("phase") if latest else None,
                },
                "finalizers": {
                    "boundary_verified": boundary,
                    "land_verified": land,
                    "effect_verified": effect,
                    "effect_not_required": effect_not_required,
                    "all_parent_predicates_observed": all_parent_predicates_observed,
                },
                "execution_bindings": bindings,
                "invalid_transitions": invalid_transitions,
                "pending_invalid_transitions": list(lifecycle["pending_invalid_transitions"]),
                "carrier_records_binding": records_binding,
                "resume_requires_live_fact_reconciliation": current_state
                in {"paused", "interrupted", "blocked"},
                "authority": False,
                "completion_claim_allowed": False,
                "completion_authority": "parent_owner_only",
            }
        )
    return {
        "schema_version": WORK_UNIT_LIFECYCLE_VERSION,
        "consumer_id": "work_unit_lifecycle_projector",
        "source_run_id": task.get("run_id"),
        "source_status": state.get("status"),
        "work_units": projections,
        "latest_carrier_records": records_binding,
        "latest_carrier_record_count": len(records_payload.get("records") or [])
        if records_payload
        else 0,
        "authority": False,
        "delete_authority": False,
        "automatic_delete_allowed": False,
        "completion_claim_allowed": False,
        "reason_codes": ["WORK_UNIT_LIFECYCLE_PROJECTED_FROM_EXISTING_FACTS"],
    }


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
    dispatch_outcome_projection = _dispatch_outcome_projection_if_present(resolved, events)
    frontier_reconciliation = _frontier_reconciliation_from_events(events)
    candidates = _problem_candidates(events)
    recovered_problem_projection, problem_history_binding = _latest_problem_projection_binding(
        events
    )
    effective_previous = previous_problem_projection or recovered_problem_projection
    typed_close_requested = any(
        event.get("kind") == "result"
        and event.get("exit_code") == 0
        and str(event.get("phase") or "").lower() == "problem_close_requested"
        for event in events
    )
    recovered_effectiveness = _effectiveness_evidence_from_events(events)
    combined_effectiveness = [
        *recovered_effectiveness,
        *[dict(row) for row in (effectiveness_evidence or [])],
    ]
    problems = reconcile_problem_lifecycle(
        {
            "events": candidates,
            "previous": _previous_problem_rows(effective_previous),
            "effectiveness_evidence": combined_effectiveness,
            "close_requested": close_requested or typed_close_requested,
        }
    )
    attempts = _attempts_from_evidence(events)
    native_total, native_usage_binding = _native_usage_total_from_events(events)
    episode_input: dict[str, object] = {
        "episode_id": task["run_id"],
        "attempts": attempts,
    }
    if native_total is not None:
        episode_input["native_total_tokens"] = native_total
    if high_burn_threshold is not None:
        episode_input["high_burn_threshold"] = high_burn_threshold
    episode = project_episode_outcome(episode_input)
    searchable_text = "\n".join(
        f"{event.get('summary') or ''}\n"
        + "\n".join(str(ref) for ref in (event.get("evidence_refs") or []))
        for event in events
    )
    report: dict[str, Any] = {
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
        "problem_history_binding": problem_history_binding,
        "episode_outcome": episode,
        "native_usage_binding": native_usage_binding,
        "work_unit_lifecycle": project_work_unit_lifecycle(task, state, events),
        "utf8": {
            "roundtrip_ok": "\ufffd" not in searchable_text,
            "searchable_sha256": _sha256_bytes(searchable_text.encode("utf-8")),
            "reason_codes": ["UTF8_PATH_ROUNDTRIP_OK", "UTF8_EVENT_SEARCHABLE"],
        },
        "reason_codes": ["SYSTEM_AWARENESS_SCAN_COMPLETED"],
    }
    if dispatch_outcome_projection is not None:
        report["dispatch_outcome_projection"] = dispatch_outcome_projection
        report["reason_codes"].append("DISPATCH_OUTCOME_V2_PROJECTED")
    if frontier_reconciliation is not None:
        report["global_frontier_reconciliation"] = frontier_reconciliation
        report["reason_codes"].append("GLOBAL_FRONTIER_RECONCILIATION_PROJECTED")
    return report


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

    worktrees = sub.add_parser("scan-worktrees")
    worktrees.add_argument("--repo-root", type=Path, required=True)
    worktrees.add_argument("--base-ref", default="origin/main")
    worktrees.add_argument("--records", type=Path)
    worktrees.add_argument("--task-run-dir", type=Path)
    worktrees.add_argument("--now")
    worktrees.add_argument("--output", type=Path)

    publish_record = sub.add_parser("publish-worktree-record")
    publish_record.add_argument("--repo-root", type=Path, required=True)
    publish_record.add_argument("--records", type=Path, required=True)
    publish_record.add_argument("--worktree", type=Path, required=True)
    publish_record.add_argument("--task-run-event-ref", required=True)
    publish_record.add_argument("--carrier-id", required=True)
    publish_record.add_argument("--carrier-generation", type=int, required=True)
    publish_record.add_argument("--purpose", required=True)
    publish_record.add_argument("--owner", required=True)
    publish_record.add_argument(
        "--declared-state", choices=sorted(WORKTREE_DECLARED_STATES), required=True
    )
    publish_record.add_argument("--work-key", required=True)
    publish_record.add_argument("--side-effect-id", required=True)
    publish_record.add_argument("--base-ref", default="origin/main")
    publish_record.add_argument("--ttl-seconds", type=int, default=3600)
    publish_record.add_argument("--finalizers", type=Path)
    publish_record.add_argument("--output", type=Path)

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
        if args.command == "publish-worktree-record":
            finalizers_payload = _load_input(args.finalizers) if args.finalizers else {}
            value = publish_worktree_lifecycle_record(
                args.repo_root,
                args.records,
                worktree_path=args.worktree,
                task_run_event_ref=args.task_run_event_ref,
                carrier_id=args.carrier_id,
                carrier_generation=args.carrier_generation,
                purpose=args.purpose,
                owner=args.owner,
                declared_state=args.declared_state,
                work_key=args.work_key,
                side_effect_id=args.side_effect_id,
                base_ref=args.base_ref,
                ttl_seconds=args.ttl_seconds,
                finalizer_event_refs=finalizers_payload,
            )
        elif args.command == "scan-task-run":
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
        elif args.command == "scan-worktrees":
            records_payload = _load_input(args.records) if args.records else None
            if records_payload is None and args.task_run_dir:
                _, _, task_events, _ = _load_task_run(args.task_run_dir.resolve())
                records_payload, _ = _latest_worktree_records_binding(task_events)
            value = scan_worktree_lifecycle(
                args.repo_root,
                base_ref=args.base_ref,
                records=records_payload,
                now=_parse_time(args.now, "now") if args.now else None,
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
    "evaluate_worktree_lifecycle",
    "scan_worktree_lifecycle",
    "publish_worktree_lifecycle_record",
    "project_work_unit_lifecycle",
    "evaluate_trajectory_sample",
    "evaluate_promotion_evidence",
    "evaluate_wakeable_wait",
    "scan_task_run",
    "main",
]
