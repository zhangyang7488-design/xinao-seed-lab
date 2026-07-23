"""Typed orthogonal conditions for the G4/G5 boundary and G6 admission.

Final claims are observations, not construction commands.  This module keeps
those meanings separate and derives compatibility booleans, action directives,
and a Chinese operator summary from one exact condition set.  It deliberately
has no authority to schedule work, pause the parent, or declare completion.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

PHASE_CONTROL_SCHEMA_VERSION = "xinao.phase_control_conditions.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PhaseConditionError(ValueError):
    """A phase-control condition set is malformed or contradictory."""


class ConditionStatus(StrEnum):
    TRUE = "True"
    FALSE = "False"
    UNKNOWN = "Unknown"


class PhaseConditionType(StrEnum):
    G4_ENGINEERING_ALLOWED = "g4_engineering_allowed"
    G4_BATCH_EXECUTION_ALLOWED = "g4_batch_execution_allowed"
    G4_FULL_EVIDENCE_COMPLETE = "g4_full_evidence_complete"
    G5_DESIGN_ALLOWED = "g5_design_allowed"
    G5_PREREGISTRATION_ALLOWED = "g5_preregistration_allowed"
    G5_FINAL_ADJUDICATION_COMPLETE = "g5_final_adjudication_complete"
    G6_FORMAL_RESEARCH_ALLOWED = "g6_formal_research_allowed"


CONDITION_ORDER = tuple(PhaseConditionType)
ACTION_CONDITIONS = (
    PhaseConditionType.G4_ENGINEERING_ALLOWED,
    PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED,
    PhaseConditionType.G5_DESIGN_ALLOWED,
    PhaseConditionType.G5_PREREGISTRATION_ALLOWED,
)
FINAL_CLAIM_CONDITIONS = (
    PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE,
    PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE,
)
_SCOPES = {
    PhaseConditionType.G4_ENGINEERING_ALLOWED: "g4_engineering",
    PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED: "g4_batch",
    PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE: "g4_final_claim",
    PhaseConditionType.G5_DESIGN_ALLOWED: "g5_design",
    PhaseConditionType.G5_PREREGISTRATION_ALLOWED: "g5_preregistration",
    PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE: "g5_final_claim",
    PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED: "g6_formal_research",
}

_REASONS: dict[PhaseConditionType, dict[ConditionStatus, str]] = {
    PhaseConditionType.G4_ENGINEERING_ALLOWED: {
        ConditionStatus.TRUE: "G4_ENGINEERING_ACTIONABLE",
        ConditionStatus.FALSE: "G4_ENGINEERING_LOCAL_PREREQUISITE_OPEN",
        ConditionStatus.UNKNOWN: "G4_ENGINEERING_ELIGIBILITY_NOT_OBSERVED",
    },
    PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED: {
        ConditionStatus.TRUE: "BOUNDED_G4_BATCH_EXECUTION_ADMITTED",
        ConditionStatus.FALSE: "G4_BATCH_LOCAL_PREREQUISITE_OPEN",
        ConditionStatus.UNKNOWN: "G4_BATCH_EXECUTION_NOT_OBSERVED",
    },
    PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE: {
        ConditionStatus.TRUE: "ALL_REQUIRED_G4_EVIDENCE_COMPLETE",
        ConditionStatus.FALSE: "REQUIRED_G4_EXPERIMENT_DEBT_REMAINS",
        ConditionStatus.UNKNOWN: "G4_FULL_EVIDENCE_NOT_OBSERVED",
    },
    PhaseConditionType.G5_DESIGN_ALLOWED: {
        ConditionStatus.TRUE: "G5_PRE_OUTCOME_DESIGN_ACTIONABLE",
        ConditionStatus.FALSE: "G5_DESIGN_LOCAL_PREREQUISITE_OPEN",
        ConditionStatus.UNKNOWN: "G5_DESIGN_ELIGIBILITY_NOT_OBSERVED",
    },
    PhaseConditionType.G5_PREREGISTRATION_ALLOWED: {
        ConditionStatus.TRUE: "G5_PREREGISTRATION_ACTIONABLE",
        ConditionStatus.FALSE: "G5_PREREGISTRATION_LOCAL_PREREQUISITE_OPEN",
        ConditionStatus.UNKNOWN: "G5_PREREGISTRATION_ELIGIBILITY_NOT_OBSERVED",
    },
    PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE: {
        ConditionStatus.TRUE: "ALL_REQUIRED_G5_EVIDENCE_ADJUDICATED",
        ConditionStatus.FALSE: "G5_FINAL_EVIDENCE_ADJUDICATION_OPEN",
        ConditionStatus.UNKNOWN: "G5_FINAL_ADJUDICATION_NOT_OBSERVED",
    },
    PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED: {
        ConditionStatus.TRUE: "FOUNDATION_AND_G0_G5_FINAL_GATE_SATISFIED",
        ConditionStatus.FALSE: "FOUNDATION_OR_G0_G5_FINAL_GATE_OPEN",
        ConditionStatus.UNKNOWN: "G6_FORMAL_ADMISSION_NOT_OBSERVED",
    },
}

_MESSAGES: dict[PhaseConditionType, dict[ConditionStatus, str]] = {
    PhaseConditionType.G4_ENGINEERING_ALLOWED: {
        ConditionStatus.TRUE: "G4 工程可继续施工。",
        ConditionStatus.FALSE: "只修复 G4 工程的本地前置, 不扩大冻结范围。",
        ConditionStatus.UNKNOWN: "尚未取得 G4 工程施工资格事实。",
    },
    PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED: {
        ConditionStatus.TRUE: "G4 当前有界批次可按批次合同执行。",
        ConditionStatus.FALSE: "只暂停当前批次并修复其本地前置, 不冻结 G4 工程或 G5。",
        ConditionStatus.UNKNOWN: "尚未取得 G4 当前批次执行资格事实。",
    },
    PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE: {
        ConditionStatus.TRUE: "G4 所有必需证据已完整。",
        ConditionStatus.FALSE: "G4_FULL 仍为 false, 尚有实验债务。",
        ConditionStatus.UNKNOWN: "尚未观察 G4 全证据完整性。",
    },
    PhaseConditionType.G5_DESIGN_ALLOWED: {
        ConditionStatus.TRUE: "G5 设计与分析计划可在 G4_FULL 前继续。",
        ConditionStatus.FALSE: "只修复 G5 设计的本地前置。",
        ConditionStatus.UNKNOWN: "尚未取得 G5 设计施工资格事实。",
    },
    PhaseConditionType.G5_PREREGISTRATION_ALLOWED: {
        ConditionStatus.TRUE: "G5 预登记与统计方案冻结可继续。",
        ConditionStatus.FALSE: "只修复 G5 预登记的本地前置。",
        ConditionStatus.UNKNOWN: "尚未取得 G5 预登记资格事实。",
    },
    PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE: {
        ConditionStatus.TRUE: "G5 最终统计证据裁决已完成。",
        ConditionStatus.FALSE: "G5 最终裁决未完成; 这不等于冻结全部 G5 工作。",
        ConditionStatus.UNKNOWN: "尚未观察 G5 最终裁决完整性。",
    },
    PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED: {
        ConditionStatus.TRUE: "G6 正式研究可以启动。",
        ConditionStatus.FALSE: "Foundation 与 G0-G5 未全闭合, G6 正式研究仍禁止。",
        ConditionStatus.UNKNOWN: "尚未观察 G6 正式准入事实。",
    },
}


def _status(value: bool | None) -> ConditionStatus:
    if value is True:
        return ConditionStatus.TRUE
    if value is False:
        return ConditionStatus.FALSE
    if value is None:
        return ConditionStatus.UNKNOWN
    raise PhaseConditionError("condition values must be bool or None")


def _require_generation(value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PhaseConditionError("observed_generation must be 64 lowercase hex")
    return value


def _record(
    condition_type: PhaseConditionType,
    value: bool | None,
    observed_generation: str,
) -> dict[str, str]:
    status = _status(value)
    return {
        "type": condition_type.value,
        "status": status.value,
        "reason": _REASONS[condition_type][status],
        "message": _MESSAGES[condition_type][status],
        "scope": _SCOPES[condition_type],
        "observed_generation": observed_generation,
    }


def build_phase_control_state(
    *,
    observed_generation: str,
    g4_engineering_allowed: bool | None,
    g4_batch_execution_allowed: bool | None,
    g4_full_evidence_complete: bool | None,
    g5_design_allowed: bool | None,
    g5_preregistration_allowed: bool | None,
    g5_final_adjudication_complete: bool | None,
    g6_formal_research_allowed: bool | None,
) -> dict[str, Any]:
    """Build one exact condition set without inferring commands from final claims."""

    generation = _require_generation(observed_generation)
    values = {
        PhaseConditionType.G4_ENGINEERING_ALLOWED: g4_engineering_allowed,
        PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED: g4_batch_execution_allowed,
        PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE: g4_full_evidence_complete,
        PhaseConditionType.G5_DESIGN_ALLOWED: g5_design_allowed,
        PhaseConditionType.G5_PREREGISTRATION_ALLOWED: g5_preregistration_allowed,
        PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE: (g5_final_adjudication_complete),
        PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED: g6_formal_research_allowed,
    }
    if g5_final_adjudication_complete is True and g4_full_evidence_complete is not True:
        raise PhaseConditionError("final G5 adjudication requires complete G4 evidence")
    if g6_formal_research_allowed is True and (
        g4_full_evidence_complete is not True or g5_final_adjudication_complete is not True
    ):
        raise PhaseConditionError("formal G6 admission requires complete G4 and G5 claims")

    return {
        "schema_version": PHASE_CONTROL_SCHEMA_VERSION,
        "observed_generation": generation,
        "conditions": [
            _record(condition_type, values[condition_type], generation)
            for condition_type in CONDITION_ORDER
        ],
        "actionable_frontier": [
            condition_type.value
            for condition_type in ACTION_CONDITIONS
            if values[condition_type] is True
        ],
        "open_final_claims": [
            condition_type.value
            for condition_type in FINAL_CLAIM_CONDITIONS
            if values[condition_type] is not True
        ],
        "global_wait_authority": False,
        "authority": False,
        "completion_claim_allowed": False,
        "parent_wait_claim_allowed": False,
    }


def _parsed_values(raw: Mapping[str, Any]) -> dict[PhaseConditionType, bool | None]:
    if raw.get("schema_version") != PHASE_CONTROL_SCHEMA_VERSION:
        raise PhaseConditionError("unexpected phase-control schema_version")
    generation = _require_generation(raw.get("observed_generation"))
    conditions = raw.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != len(CONDITION_ORDER):
        raise PhaseConditionError("conditions must contain the exact typed condition set")

    parsed: dict[PhaseConditionType, bool | None] = {}
    status_values = {
        ConditionStatus.TRUE: True,
        ConditionStatus.FALSE: False,
        ConditionStatus.UNKNOWN: None,
    }
    for index, item in enumerate(conditions):
        if not isinstance(item, Mapping):
            raise PhaseConditionError(f"conditions[{index}] must be an object")
        try:
            condition_type = PhaseConditionType(str(item.get("type") or ""))
            status = ConditionStatus(str(item.get("status") or ""))
        except ValueError as exc:
            raise PhaseConditionError(f"conditions[{index}] has an invalid type or status") from exc
        if condition_type in parsed:
            raise PhaseConditionError("condition types must be unique")
        if item.get("observed_generation") != generation:
            raise PhaseConditionError("condition observed_generation mismatch")
        if item.get("reason") != _REASONS[condition_type][status]:
            raise PhaseConditionError("condition reason is not canonical")
        if item.get("message") != _MESSAGES[condition_type][status]:
            raise PhaseConditionError("condition message is not canonical")
        if item.get("scope") != _SCOPES[condition_type]:
            raise PhaseConditionError("condition scope is not canonical")
        parsed[condition_type] = status_values[status]
    if set(parsed) != set(CONDITION_ORDER):
        raise PhaseConditionError("condition set is incomplete")
    return parsed


def validate_phase_control_state(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all conditions and every derived projection."""

    generation = _require_generation(raw.get("observed_generation"))
    parsed = _parsed_values(raw)
    rebuilt = build_phase_control_state(
        observed_generation=generation,
        g4_engineering_allowed=parsed[PhaseConditionType.G4_ENGINEERING_ALLOWED],
        g4_batch_execution_allowed=parsed[PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED],
        g4_full_evidence_complete=parsed[PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE],
        g5_design_allowed=parsed[PhaseConditionType.G5_DESIGN_ALLOWED],
        g5_preregistration_allowed=parsed[PhaseConditionType.G5_PREREGISTRATION_ALLOWED],
        g5_final_adjudication_complete=parsed[PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE],
        g6_formal_research_allowed=parsed[PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED],
    )
    if dict(raw) != rebuilt:
        raise PhaseConditionError("phase-control projections are not canonical")
    return rebuilt


def condition_value(
    raw: Mapping[str, Any],
    condition_type: PhaseConditionType,
) -> bool | None:
    """Return one typed condition after validating the complete state."""

    return _parsed_values(validate_phase_control_state(raw))[condition_type]


def legacy_claim_projection(raw: Mapping[str, Any]) -> dict[str, bool]:
    """Project old final-claim booleans from typed conditions, never in reverse."""

    parsed = _parsed_values(validate_phase_control_state(raw))
    g4_full = parsed[PhaseConditionType.G4_FULL_EVIDENCE_COMPLETE] is True
    g5_closed = parsed[PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE] is True
    return {
        "g4_full": g4_full,
        "g4_closed": g4_full,
        "g5_closed": g5_closed,
        "formal_research_allowed": (parsed[PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED] is True),
    }


def _action(value: bool | None) -> str:
    if value is True:
        return "EXECUTE"
    if value is False:
        return "HOLD_LOCAL_PREREQUISITE"
    return "UNKNOWN"


def execution_directives(raw: Mapping[str, Any]) -> dict[str, str | bool]:
    """Derive local actions only from their own eligibility conditions."""

    parsed = _parsed_values(validate_phase_control_state(raw))
    return {
        "g4_engineering": _action(parsed[PhaseConditionType.G4_ENGINEERING_ALLOWED]),
        "g4_batch_runner": _action(parsed[PhaseConditionType.G4_BATCH_EXECUTION_ALLOWED]),
        "g5_design": _action(parsed[PhaseConditionType.G5_DESIGN_ALLOWED]),
        "g5_preregistration": _action(parsed[PhaseConditionType.G5_PREREGISTRATION_ALLOWED]),
        "g5_final_claim": (
            "COMPLETE"
            if parsed[PhaseConditionType.G5_FINAL_ADJUDICATION_COMPLETE] is True
            else "OPEN"
        ),
        "g6_formal_research": (
            "ALLOW" if parsed[PhaseConditionType.G6_FORMAL_RESEARCH_ALLOWED] is True else "DENY"
        ),
        "parent_global_wait_allowed": False,
    }


def human_summary_cn(raw: Mapping[str, Any]) -> str:
    """Render the operator decision surface without losing technical truth."""

    state = validate_phase_control_state(raw)
    projection = legacy_claim_projection(state)
    directives = execution_directives(state)
    action_cn = {
        "EXECUTE": "执行",
        "HOLD_LOCAL_PREREQUISITE": "仅局部前置未满足",
        "UNKNOWN": "未知",
    }
    return (
        f"G4 工程={action_cn[str(directives['g4_engineering'])]}; "
        f"G4 当前批次={action_cn[str(directives['g4_batch_runner'])]}; "
        f"G4_FULL={'已完成' if projection['g4_full'] else '未完成'}; "
        f"G5 设计={action_cn[str(directives['g5_design'])]}; "
        f"G5 预登记={action_cn[str(directives['g5_preregistration'])]}; "
        f"G5 最终裁决={'已完成' if projection['g5_closed'] else '未完成'}; "
        f"G6 正式研究={'允许' if projection['formal_research_allowed'] else '禁止'}。"
        "最终 claim 未完成不产生整阶段冻结, 也不授权父级全局等待。"
    )


__all__ = [
    "PHASE_CONTROL_SCHEMA_VERSION",
    "ConditionStatus",
    "PhaseConditionError",
    "PhaseConditionType",
    "build_phase_control_state",
    "condition_value",
    "execution_directives",
    "human_summary_cn",
    "legacy_claim_projection",
    "validate_phase_control_state",
]
