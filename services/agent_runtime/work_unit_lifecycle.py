"""Shared pure projection for typed work-unit lifecycle events.

The task-run event chain remains authoritative.  This module only gives every
consumer one deterministic interpretation of a work key, including monotonic
pause/resume and terminal semantics.  It performs no writes and grants no
authority.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

WORK_UNIT_LIFECYCLE_VERSION = "xinao.work_unit_lifecycle_projection.v1"

WORK_UNIT_TRANSITION_RULES: dict[str, tuple[str, frozenset[str]]] = {
    "work_unit_planned": ("planned", frozenset({"planned"})),
    "work_unit_active": ("active", frozenset({"planned", "active"})),
    "work_unit_paused": ("paused", frozenset({"active"})),
    "work_unit_interrupted": ("interrupted", frozenset({"active"})),
    "work_unit_resume_reconciled": ("active", frozenset({"paused", "interrupted"})),
    "work_unit_verifying": ("verifying", frozenset({"active"})),
    "work_unit_boundary_verified": ("verifying", frozenset({"verifying"})),
    "work_unit_land_requested": ("land_requested", frozenset({"verifying"})),
    "work_unit_land_verified": ("landed", frozenset({"land_requested"})),
    "work_unit_effect_verified": ("effect_verified", frozenset({"landed"})),
    "work_unit_effect_not_required": ("effect_not_required", frozenset({"landed"})),
    "work_unit_blocked": (
        "blocked",
        frozenset(
            {"planned", "active", "paused", "interrupted", "verifying", "land_requested", "landed"}
        ),
    ),
    "work_unit_failed": (
        "failed",
        frozenset(
            {"planned", "active", "paused", "interrupted", "verifying", "land_requested", "landed"}
        ),
    ),
    "work_unit_cancelled": (
        "cancelled",
        frozenset(
            {"planned", "active", "paused", "interrupted", "verifying", "land_requested", "landed"}
        ),
    ),
}

WORK_UNIT_TERMINAL_STATES = frozenset(
    {"effect_verified", "effect_not_required", "blocked", "failed", "cancelled", "stopped"}
)
WORK_UNIT_FROZEN_STATES = frozenset({"paused", "interrupted", *WORK_UNIT_TERMINAL_STATES})
WORK_UNIT_NEXT_CONSUMERS = {
    "planned": "execution_owner",
    "active": "boundary_verifier",
    "paused": "action_resume_preaction_guard",
    "interrupted": "action_resume_preaction_guard",
    "verifying": "land_owner",
    "land_requested": "git_pr_land_observer",
    "landed": "real_effect_consumer",
    "effect_verified": "parent_completion_owner",
    "effect_not_required": "parent_completion_owner",
    "blocked": "owner_reconciliation",
    "failed": "owner_reconciliation",
    "cancelled": "parent_completion_owner",
    "stopped": "owner_reconciliation",
    "unbound": "work_unit_identity_owner",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _verified_hash_bound_evidence(refs: object) -> bool:
    if not isinstance(refs, list):
        return False
    for raw_ref in refs:
        reference = str(raw_ref or "")
        if "#sha256=" not in reference:
            continue
        path_text, expected = reference.rsplit("#sha256=", 1)
        if not _SHA256_RE.fullmatch(expected):
            continue
        try:
            observed = hashlib.sha256(Path(path_text).read_bytes()).hexdigest()
        except OSError:
            continue
        if observed == expected:
            return True
    return False


def discover_work_unit_keys(events: Sequence[Mapping[str, object]]) -> set[str]:
    """Return only identities introduced by typed lifecycle or targeted-stop facts."""

    keys: set[str] = set()
    for event in events:
        target = str(event.get("target") or "").strip()
        if not target:
            continue
        phase = str(event.get("phase") or "").lower()
        kind = str(event.get("kind") or "").lower()
        if phase.startswith("work_unit_") or kind == "stop" or phase.endswith("_stopped"):
            keys.add(target)
    return keys


def project_work_unit_state(
    events: Sequence[Mapping[str, object]], work_key: str
) -> dict[str, Any]:
    """Project one exact work key with fail-closed invalid-transition evidence.

    ``event_id`` is the immutable identity for control-state facts.  A
    ``side_effect_id`` is retained when present but is not required for the
    non-authoritative control projection; completion finalizers independently
    require their stronger typed side-effect and readback evidence.
    """

    relevant = [dict(event) for event in events if str(event.get("target") or "") == work_key]
    state = "planned"
    bound = False
    matched_event: Mapping[str, object] | None = None
    invalid_transitions: list[dict[str, object]] = []
    pending_invalid_transitions: list[dict[str, object]] = []

    for event in relevant:
        phase = str(event.get("phase") or "").lower()
        kind = str(event.get("kind") or "").lower()
        event_id = str(event.get("event_id") or "").strip()

        if kind == "stop" or phase.endswith("_stopped"):
            bound = True
            if state in WORK_UNIT_TERMINAL_STATES:
                invalid = {
                    "event_id": event.get("event_id"),
                    "phase": phase,
                    "from_state": state,
                    "reason_code": "WORK_UNIT_TERMINAL_ABSORBING",
                }
                invalid_transitions.append(invalid)
                pending_invalid_transitions.append(invalid)
                continue
            state = "stopped"
            matched_event = event
            pending_invalid_transitions.clear()
            continue

        if not phase.startswith("work_unit_"):
            continue
        bound = True
        rule = WORK_UNIT_TRANSITION_RULES.get(phase)
        if rule is None:
            invalid = {
                "event_id": event.get("event_id"),
                "phase": phase,
                "from_state": state,
                "reason_code": "WORK_UNIT_PHASE_UNKNOWN",
            }
            invalid_transitions.append(invalid)
            pending_invalid_transitions.append(invalid)
            continue

        candidate, allowed_predecessors = rule
        terminal_failure = phase in {"work_unit_blocked", "work_unit_failed"}
        outcome_valid = (
            bool(event_id)
            and kind == "result"
            and (
                (
                    terminal_failure
                    and isinstance(event.get("exit_code"), int)
                    and event.get("exit_code") != 0
                )
                or (not terminal_failure and event.get("exit_code") == 0)
            )
        )
        if not outcome_valid or state not in allowed_predecessors:
            invalid = {
                "event_id": event.get("event_id"),
                "phase": phase,
                "from_state": state,
                "reason_code": "WORK_UNIT_TRANSITION_INVALID",
            }
            invalid_transitions.append(invalid)
            pending_invalid_transitions.append(invalid)
            continue
        if phase == "work_unit_resume_reconciled" and not _verified_hash_bound_evidence(
            event.get("evidence_refs")
        ):
            invalid = {
                "event_id": event.get("event_id"),
                "phase": phase,
                "from_state": state,
                "reason_code": "WORK_UNIT_RESUME_READBACK_MISSING",
            }
            invalid_transitions.append(invalid)
            pending_invalid_transitions.append(invalid)
            continue

        state = candidate
        matched_event = event
        pending_invalid_transitions.clear()

    projected_state = state if bound else "unbound"
    return {
        "work_key": work_key,
        "bound": bound,
        "state": projected_state,
        "next_consumer": WORK_UNIT_NEXT_CONSUMERS[projected_state],
        "event_count": len(relevant),
        "event_id": matched_event.get("event_id") if matched_event else None,
        "phase": matched_event.get("phase") if matched_event else None,
        "actor": matched_event.get("actor") if matched_event else None,
        "side_effect_id": matched_event.get("side_effect_id") if matched_event else None,
        "invalid_transitions": invalid_transitions,
        "pending_invalid_transitions": pending_invalid_transitions,
        "authority": False,
        "completion_claim_allowed": False,
    }


__all__ = [
    "WORK_UNIT_FROZEN_STATES",
    "WORK_UNIT_LIFECYCLE_VERSION",
    "WORK_UNIT_NEXT_CONSUMERS",
    "WORK_UNIT_TERMINAL_STATES",
    "WORK_UNIT_TRANSITION_RULES",
    "discover_work_unit_keys",
    "project_work_unit_state",
]
