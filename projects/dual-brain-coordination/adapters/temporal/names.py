"""Single source of truth for Temporal workflow / activity / query / signal names.

Prevents string drift (e.g. query \"status\" vs registered \"get_status\") between
starter scripts, canaries, and the worker registration surface.

Does not touch Admin client.py.
"""

from __future__ import annotations

from typing import Any

# Must match @workflow.defn(name=...) / WORKFLOW_TYPE in package workflow.py
WORKFLOW_TYPE = "XinaoPromotedTaskWorkflowV1"
DEFAULT_TASK_QUEUE = "xinao-dualbrain-promoted-v1"

# Must match @activity.defn(name=...) on package activities
ACTIVITY_VALIDATE_ENVELOPE = "xinao.promoted.validate_envelope"
ACTIVITY_RECORD_STARTED = "xinao.promoted.record_started"
ACTIVITY_EXECUTE_STEP = "xinao.promoted.execute_step"
ACTIVITY_FINALIZE = "xinao.promoted.finalize"
ACTIVITY_GROK_EXECUTE_ACPX_LANE = "xinao.grok.execute_acpx_lane"
ACTIVITY_GROK_MATERIALIZE_ACPX_FANIN = "xinao.grok.materialize_acpx_fanin"

PROMOTED_ACTIVITY_NAMES: tuple[str, ...] = (
    ACTIVITY_VALIDATE_ENVELOPE,
    ACTIVITY_RECORD_STARTED,
    ACTIVITY_EXECUTE_STEP,
    ACTIVITY_FINALIZE,
    ACTIVITY_GROK_EXECUTE_ACPX_LANE,
    ACTIVITY_GROK_MATERIALIZE_ACPX_FANIN,
)

# Query method names (Temporal registers def name unless name= override)
QUERY_GET_STATUS = "get_status"
QUERY_GET_PROGRESS = "get_progress"
# Historical wrong name that failed canaries — do not use
QUERY_STATUS_ALIAS_FORBIDDEN = "status"

SIGNAL_REQUEST_CANCEL = "request_cancel"
SIGNAL_PAUSE = "pause"
SIGNAL_RESUME = "resume"
SIGNAL_SET_NOTE = "set_note"

PROMOTED_QUERY_NAMES: tuple[str, ...] = (QUERY_GET_STATUS, QUERY_GET_PROGRESS)
PROMOTED_SIGNAL_NAMES: tuple[str, ...] = (
    SIGNAL_REQUEST_CANCEL,
    SIGNAL_PAUSE,
    SIGNAL_RESUME,
    SIGNAL_SET_NOTE,
)


def verify_registered_names() -> dict[str, Any]:
    """Cross-check package workflow/activity registrations against this SSOT.

    Returns a report dict; raises AssertionError only if *strict* callers want —
    selftest uses ``ok`` field.
    """
    from temporalio.activity import _Definition as ActivityDefinition
    from temporalio.workflow import _Definition as WorkflowDefinition

    from xinao_coordination.temporal.activities import PROMOTED_ACTIVITIES
    from xinao_coordination.temporal.workflow import (
        WORKFLOW_TYPE as PKG_WORKFLOW_TYPE,
    )
    from xinao_coordination.temporal.workflow import (
        XinaoPromotedTaskWorkflowV1,
    )

    errors: list[str] = []
    if PKG_WORKFLOW_TYPE != WORKFLOW_TYPE:
        errors.append(f"workflow type mismatch: package={PKG_WORKFLOW_TYPE!r} ssot={WORKFLOW_TYPE!r}")

    wdef = WorkflowDefinition.from_class(XinaoPromotedTaskWorkflowV1)
    if wdef.name != WORKFLOW_TYPE:
        errors.append(f"@workflow.defn name={wdef.name!r} != ssot {WORKFLOW_TYPE!r}")

    reg_queries = sorted(wdef.queries.keys())
    expected_queries = sorted(PROMOTED_QUERY_NAMES)
    if reg_queries != expected_queries:
        errors.append(f"queries mismatch: reg={reg_queries} ssot={expected_queries}")
    if QUERY_STATUS_ALIAS_FORBIDDEN in reg_queries:
        errors.append(f"forbidden query name registered: {QUERY_STATUS_ALIAS_FORBIDDEN!r}")

    reg_signals = sorted(wdef.signals.keys())
    expected_signals = sorted(PROMOTED_SIGNAL_NAMES)
    if reg_signals != expected_signals:
        errors.append(f"signals mismatch: reg={reg_signals} ssot={expected_signals}")

    reg_activity_names: list[str] = []
    for act in PROMOTED_ACTIVITIES:
        defn = ActivityDefinition.from_callable(act)
        reg_activity_names.append(defn.name)
    reg_activity_names_sorted = sorted(reg_activity_names)
    expected_acts = sorted(PROMOTED_ACTIVITY_NAMES)
    if reg_activity_names_sorted != expected_acts:
        errors.append(f"activities mismatch: reg={reg_activity_names_sorted} ssot={expected_acts}")

    return {
        "ok": not errors,
        "workflow_type": WORKFLOW_TYPE,
        "activity_names": list(PROMOTED_ACTIVITY_NAMES),
        "query_names": list(PROMOTED_QUERY_NAMES),
        "signal_names": list(PROMOTED_SIGNAL_NAMES),
        "registered_activity_names": reg_activity_names,
        "registered_queries": reg_queries,
        "registered_signals": reg_signals,
        "errors": errors,
    }


__all__ = [
    "ACTIVITY_EXECUTE_STEP",
    "ACTIVITY_FINALIZE",
    "ACTIVITY_GROK_EXECUTE_ACPX_LANE",
    "ACTIVITY_GROK_MATERIALIZE_ACPX_FANIN",
    "ACTIVITY_RECORD_STARTED",
    "ACTIVITY_VALIDATE_ENVELOPE",
    "DEFAULT_TASK_QUEUE",
    "PROMOTED_ACTIVITY_NAMES",
    "PROMOTED_QUERY_NAMES",
    "PROMOTED_SIGNAL_NAMES",
    "QUERY_GET_PROGRESS",
    "QUERY_GET_STATUS",
    "QUERY_STATUS_ALIAS_FORBIDDEN",
    "SIGNAL_PAUSE",
    "SIGNAL_REQUEST_CANCEL",
    "SIGNAL_RESUME",
    "SIGNAL_SET_NOTE",
    "WORKFLOW_TYPE",
    "verify_registered_names",
]
