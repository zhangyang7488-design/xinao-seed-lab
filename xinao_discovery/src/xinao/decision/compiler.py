"""Fail-closed DecisionPlan/NO_ACTION compiler and immutable freeze boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal


class NoActionReason(StrEnum):
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    BASELINE_INACTIVE = "BASELINE_INACTIVE"
    RULE_INACTIVE = "RULE_INACTIVE"
    UNCERTAINTY_NOT_POSITIVE_AFTER_COST = "UNCERTAINTY_NOT_POSITIVE_AFTER_COST"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    INVALID_TEMPORAL_BOUNDARY = "INVALID_TEMPORAL_BOUNDARY"
    FREEZE_DEADLINE_MISSED = "FREEZE_DEADLINE_MISSED"


class DecisionGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str = Field(min_length=1)
    validation_report_ref: str = Field(min_length=1)
    validation_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_verdict: Literal["ACTION", "NO_ACTION"]
    baseline_ref: str = Field(min_length=1)
    baseline_active: bool
    rule_ref: str = Field(min_length=1)
    rule_active: bool
    target_ref: str = Field(min_length=1)
    target_window_start: datetime
    target_window_end: datetime
    target_open_time: datetime
    freeze_deadline: datetime
    knowledge_cutoff: datetime
    compiled_at: datetime
    panel: Literal["A", "B"]
    selected_number: int = Field(ge=1, le=49)
    stake: str
    lower_expected_net: str
    estimated_cost: str
    risk_limit: str

    @model_validator(mode="after")
    def validate_aware_datetimes(self) -> DecisionGateInput:
        values = (
            self.target_window_start,
            self.target_window_end,
            self.target_open_time,
            self.freeze_deadline,
            self.knowledge_cutoff,
            self.compiled_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in values):
            raise ValueError("decision times must be timezone-aware")
        return self


class DecisionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_ref: str = Field(min_length=1)
    candidate_ref: str
    validation_report_ref: str
    validation_output_hash: str
    baseline_ref: str
    rule_ref: str
    target_ref: str
    target_window_start: datetime
    target_window_end: datetime
    target_open_time: datetime
    freeze_deadline: datetime
    knowledge_cutoff: datetime
    compiled_at: datetime
    decision_type: Literal["ACTION", "NO_ACTION"]
    panel: Literal["A", "B"]
    selected_number: int = Field(ge=1, le=49)
    stake: str
    lower_expected_net: str
    estimated_cost: str
    risk_limit: str
    no_action_reasons: tuple[NoActionReason, ...]
    plan_hash: str | None = None

    def with_hash(self) -> DecisionPlan:
        basis = self.model_dump(mode="json", exclude={"plan_hash"})
        return self.model_copy(update={"plan_hash": canonical_sha256(basis)})


class FrozenDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_ref: str = Field(min_length=1)
    decision_plan_ref: str
    decision_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_type: Literal["ACTION", "NO_ACTION"]
    candidate_refs: tuple[str, ...]
    target_ref: str
    target_window_start: datetime
    target_window_end: datetime
    target_open_time: datetime
    freeze_deadline: datetime
    knowledge_cutoff: datetime
    frozen_at: datetime
    baseline_ref: str
    rule_ref: str
    panel: Literal["A", "B"]
    selected_number: int = Field(ge=1, le=49)
    stake: str
    no_action_reasons: tuple[NoActionReason, ...]
    decision_hash: str | None = None

    def with_hash(self) -> FrozenDecision:
        basis = self.model_dump(mode="json", exclude={"decision_hash"})
        return self.model_copy(update={"decision_hash": canonical_sha256(basis)})


def _amount(value: str) -> Decimal:
    return Decimal(format_decimal(value, ACCOUNTING_DECIMAL))


def compile_decision_plan(gate: DecisionGateInput, *, plan_ref: str) -> DecisionPlan:
    stake = _amount(gate.stake)
    lower = _amount(gate.lower_expected_net)
    cost = _amount(gate.estimated_cost)
    risk_limit = _amount(gate.risk_limit)
    if stake <= 0 or cost < 0 or risk_limit < 0:
        raise ValueError("stake must be positive and cost/risk limit must be non-negative")

    reasons: list[NoActionReason] = []
    if gate.validation_verdict != "ACTION":
        reasons.append(NoActionReason.VALIDATION_REJECTED)
    if not gate.baseline_active:
        reasons.append(NoActionReason.BASELINE_INACTIVE)
    if not gate.rule_active:
        reasons.append(NoActionReason.RULE_INACTIVE)
    if lower - cost <= 0:
        reasons.append(NoActionReason.UNCERTAINTY_NOT_POSITIVE_AFTER_COST)
    if stake > risk_limit:
        reasons.append(NoActionReason.RISK_LIMIT_EXCEEDED)
    if not (
        gate.target_window_start <= gate.target_window_end
        and gate.freeze_deadline < gate.target_open_time
        and gate.knowledge_cutoff < gate.target_open_time
    ):
        reasons.append(NoActionReason.INVALID_TEMPORAL_BOUNDARY)
    if gate.compiled_at > gate.freeze_deadline:
        reasons.append(NoActionReason.FREEZE_DEADLINE_MISSED)

    unique_reasons = tuple(dict.fromkeys(reasons))
    decision_type: Literal["ACTION", "NO_ACTION"] = "NO_ACTION" if unique_reasons else "ACTION"
    exposure = "0.0000" if unique_reasons else format_decimal(stake, ACCOUNTING_DECIMAL)
    return DecisionPlan(
        plan_ref=plan_ref,
        candidate_ref=gate.candidate_ref,
        validation_report_ref=gate.validation_report_ref,
        validation_output_hash=gate.validation_output_hash,
        baseline_ref=gate.baseline_ref,
        rule_ref=gate.rule_ref,
        target_ref=gate.target_ref,
        target_window_start=gate.target_window_start,
        target_window_end=gate.target_window_end,
        target_open_time=gate.target_open_time,
        freeze_deadline=gate.freeze_deadline,
        knowledge_cutoff=gate.knowledge_cutoff,
        compiled_at=gate.compiled_at,
        decision_type=decision_type,
        panel=gate.panel,
        selected_number=gate.selected_number,
        stake=exposure,
        lower_expected_net=format_decimal(lower, ACCOUNTING_DECIMAL),
        estimated_cost=format_decimal(cost, ACCOUNTING_DECIMAL),
        risk_limit=format_decimal(risk_limit, ACCOUNTING_DECIMAL),
        no_action_reasons=unique_reasons,
    ).with_hash()


def freeze_decision(
    plan: DecisionPlan, *, decision_ref: str, frozen_at: datetime
) -> FrozenDecision:
    if plan.plan_hash is None:
        raise ValueError("decision plan must be hash sealed before freeze")
    if frozen_at.tzinfo is None or frozen_at.utcoffset() is None:
        raise ValueError("frozen_at must be timezone-aware")
    if frozen_at > plan.freeze_deadline:
        raise ValueError("decision freeze is late")
    if (
        plan.freeze_deadline >= plan.target_open_time
        or plan.knowledge_cutoff >= plan.target_open_time
    ):
        raise ValueError("decision freeze temporal boundary is invalid")
    if (plan.decision_type == "ACTION") != (not plan.no_action_reasons):
        raise ValueError("decision type and refusal reasons disagree")
    return FrozenDecision(
        decision_ref=decision_ref,
        decision_plan_ref=plan.plan_ref,
        decision_plan_hash=plan.plan_hash,
        decision_type=plan.decision_type,
        candidate_refs=(plan.candidate_ref,),
        target_ref=plan.target_ref,
        target_window_start=plan.target_window_start,
        target_window_end=plan.target_window_end,
        target_open_time=plan.target_open_time,
        freeze_deadline=plan.freeze_deadline,
        knowledge_cutoff=plan.knowledge_cutoff,
        frozen_at=frozen_at,
        baseline_ref=plan.baseline_ref,
        rule_ref=plan.rule_ref,
        panel=plan.panel,
        selected_number=plan.selected_number,
        stake=plan.stake,
        no_action_reasons=plan.no_action_reasons,
    ).with_hash()
