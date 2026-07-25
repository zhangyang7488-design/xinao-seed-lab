"""Fail-closed DecisionPlan/NO_ACTION compiler and immutable freeze boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal


class NoActionReason(StrEnum):
    NO_ACTION_SELECTED = "NO_ACTION_SELECTED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    BASELINE_INACTIVE = "BASELINE_INACTIVE"
    RULE_INACTIVE = "RULE_INACTIVE"
    UNCERTAINTY_NOT_POSITIVE_AFTER_COST = "UNCERTAINTY_NOT_POSITIVE_AFTER_COST"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    INVALID_TEMPORAL_BOUNDARY = "INVALID_TEMPORAL_BOUNDARY"
    FREEZE_DEADLINE_MISSED = "FREEZE_DEADLINE_MISSED"


class DecisionKind(StrEnum):
    FROZEN_EXPERIMENTAL_SHADOW = "FROZEN_EXPERIMENTAL_SHADOW"
    FROZEN_ELIGIBLE_ACTION = "FROZEN_ELIGIBLE_ACTION"
    NO_ACTION = "NO_ACTION"


class CandidateQualification(StrEnum):
    SHADOW_EXPERIMENTAL = "SHADOW_EXPERIMENTAL"
    SHADOW_CLAIM_ELIGIBLE = "SHADOW_CLAIM_ELIGIBLE"


def _expected_qualification(kind: DecisionKind) -> CandidateQualification | None:
    if kind == DecisionKind.FROZEN_EXPERIMENTAL_SHADOW:
        return CandidateQualification.SHADOW_EXPERIMENTAL
    if kind == DecisionKind.FROZEN_ELIGIBLE_ACTION:
        return CandidateQualification.SHADOW_CLAIM_ELIGIBLE
    return None


def _legacy_decision_type(kind: DecisionKind) -> Literal["ACTION", "NO_ACTION"]:
    return "NO_ACTION" if kind == DecisionKind.NO_ACTION else "ACTION"


def _claim_scope(
    kind: DecisionKind,
) -> Literal["EXPERIMENTAL_ONLY", "CLAIM_ELIGIBLE", "NO_ACTION"]:
    if kind == DecisionKind.FROZEN_EXPERIMENTAL_SHADOW:
        return "EXPERIMENTAL_ONLY"
    if kind == DecisionKind.FROZEN_ELIGIBLE_ACTION:
        return "CLAIM_ELIGIBLE"
    return "NO_ACTION"


def _validate_science_axes(
    *,
    decision_kind: DecisionKind,
    candidate_qualification: CandidateQualification | None,
    decision_type: Literal["ACTION", "NO_ACTION"],
    claim_scope: Literal["EXPERIMENTAL_ONLY", "CLAIM_ELIGIBLE", "NO_ACTION"],
) -> None:
    if candidate_qualification != _expected_qualification(decision_kind):
        raise ValueError("decision kind and candidate qualification disagree")
    if decision_type != _legacy_decision_type(decision_kind):
        raise ValueError("decision kind and legacy decision type disagree")
    if claim_scope != _claim_scope(decision_kind):
        raise ValueError("decision kind and claim scope disagree")


class DecisionGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str = Field(min_length=1)
    requested_decision_kind: DecisionKind
    candidate_qualification: CandidateQualification | None
    adjudicated_decision_kinds: tuple[DecisionKind, ...] = Field(min_length=1)
    court_verdict_bundle_ref: str = Field(min_length=1)
    court_verdict_bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_pin_ref: str = Field(min_length=1)
    protocol_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    information_set_ref: str = Field(min_length=1)
    information_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_report_ref: str = Field(min_length=1)
    validation_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_verdict: Literal["ACTION", "NO_ACTION"]
    baseline_ref: str = Field(min_length=1)
    baseline_active: bool
    rule_ref: str = Field(min_length=1)
    rule_active: bool
    odds_version_ref: str = Field(min_length=1)
    cost_version_ref: str = Field(min_length=1)
    friction_version_ref: str = Field(min_length=1)
    exposure_policy_ref: str = Field(min_length=1)
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
    def validate_science_gate(self) -> Self:
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
        if len(set(self.adjudicated_decision_kinds)) != len(self.adjudicated_decision_kinds):
            raise ValueError("adjudicated decision kinds must be unique")
        if self.requested_decision_kind not in self.adjudicated_decision_kinds:
            raise ValueError("requested decision kind is not permitted by the court bundle")
        expected = _expected_qualification(self.requested_decision_kind)
        if self.candidate_qualification != expected:
            raise ValueError("requested decision kind and candidate qualification disagree")
        return self


class DecisionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_ref: str = Field(min_length=1)
    candidate_ref: str
    decision_kind: DecisionKind
    candidate_qualification: CandidateQualification | None
    adjudicated_decision_kinds: tuple[DecisionKind, ...]
    court_verdict_bundle_ref: str
    court_verdict_bundle_content_hash: str
    protocol_pin_ref: str
    protocol_pin_sha256: str
    information_set_ref: str
    information_set_hash: str
    validation_report_ref: str
    validation_output_hash: str
    baseline_ref: str
    rule_ref: str
    odds_version_ref: str
    cost_version_ref: str
    friction_version_ref: str
    exposure_policy_ref: str
    target_ref: str
    target_window_start: datetime
    target_window_end: datetime
    target_open_time: datetime
    freeze_deadline: datetime
    knowledge_cutoff: datetime
    compiled_at: datetime
    decision_type: Literal["ACTION", "NO_ACTION"]
    claim_scope: Literal["EXPERIMENTAL_ONLY", "CLAIM_ELIGIBLE", "NO_ACTION"]
    panel: Literal["A", "B"]
    selected_number: int = Field(ge=1, le=49)
    stake: str
    lower_expected_net: str
    estimated_cost: str
    risk_limit: str
    no_action_reasons: tuple[NoActionReason, ...]
    plan_hash: str | None = None

    @model_validator(mode="after")
    def validate_science_axes(self) -> Self:
        _validate_science_axes(
            decision_kind=self.decision_kind,
            candidate_qualification=self.candidate_qualification,
            decision_type=self.decision_type,
            claim_scope=self.claim_scope,
        )
        if (self.decision_kind == DecisionKind.NO_ACTION) != bool(self.no_action_reasons):
            raise ValueError("NO_ACTION kind and refusal reasons disagree")
        if len(set(self.adjudicated_decision_kinds)) != len(self.adjudicated_decision_kinds):
            raise ValueError("adjudicated decision kinds must be unique")
        if self.decision_kind not in self.adjudicated_decision_kinds:
            raise ValueError("decision kind is not permitted by the court bundle")
        return self

    def with_hash(self) -> DecisionPlan:
        basis = self.model_dump(mode="json", exclude={"plan_hash"})
        return self.model_copy(update={"plan_hash": canonical_sha256(basis)})


class FrozenDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_ref: str = Field(min_length=1)
    decision_plan_ref: str
    decision_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_kind: DecisionKind
    candidate_qualification: CandidateQualification | None
    adjudicated_decision_kinds: tuple[DecisionKind, ...]
    decision_type: Literal["ACTION", "NO_ACTION"]
    claim_scope: Literal["EXPERIMENTAL_ONLY", "CLAIM_ELIGIBLE", "NO_ACTION"]
    candidate_refs: tuple[str, ...]
    candidate_refs_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    court_verdict_bundle_ref: str
    court_verdict_bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_pin_ref: str
    protocol_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    information_set_ref: str
    information_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_ref: str
    target_window_start: datetime
    target_window_end: datetime
    target_open_time: datetime
    freeze_deadline: datetime
    knowledge_cutoff: datetime
    frozen_at: datetime
    baseline_ref: str
    rule_ref: str
    odds_version_ref: str
    cost_version_ref: str
    friction_version_ref: str
    exposure_policy_ref: str
    panel: Literal["A", "B"]
    selected_number: int = Field(ge=1, le=49)
    stake: str
    no_action_reasons: tuple[NoActionReason, ...]
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_science_axes_and_hash(self) -> Self:
        _validate_science_axes(
            decision_kind=self.decision_kind,
            candidate_qualification=self.candidate_qualification,
            decision_type=self.decision_type,
            claim_scope=self.claim_scope,
        )
        if (self.decision_kind == DecisionKind.NO_ACTION) != bool(self.no_action_reasons):
            raise ValueError("NO_ACTION kind and refusal reasons disagree")
        if not self.candidate_refs:
            raise ValueError("frozen decision requires at least one candidate reference")
        if self.candidate_refs_hash != canonical_sha256(self.candidate_refs):
            raise ValueError("candidate_refs_hash does not bind candidate_refs")
        if len(set(self.adjudicated_decision_kinds)) != len(self.adjudicated_decision_kinds):
            raise ValueError("adjudicated decision kinds must be unique")
        if self.decision_kind not in self.adjudicated_decision_kinds:
            raise ValueError("decision kind is not permitted by the court bundle")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical frozen decision")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> FrozenDecision:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


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
    if gate.requested_decision_kind == DecisionKind.NO_ACTION:
        reasons.append(NoActionReason.NO_ACTION_SELECTED)

    unique_reasons = tuple(dict.fromkeys(reasons))
    decision_kind = DecisionKind.NO_ACTION if unique_reasons else gate.requested_decision_kind
    if decision_kind not in gate.adjudicated_decision_kinds:
        raise ValueError("compiled decision kind is not permitted by the court bundle")
    qualification = _expected_qualification(decision_kind)
    decision_type = _legacy_decision_type(decision_kind)
    exposure = "0.0000" if unique_reasons else format_decimal(stake, ACCOUNTING_DECIMAL)
    return DecisionPlan(
        plan_ref=plan_ref,
        candidate_ref=gate.candidate_ref,
        decision_kind=decision_kind,
        candidate_qualification=qualification,
        adjudicated_decision_kinds=gate.adjudicated_decision_kinds,
        court_verdict_bundle_ref=gate.court_verdict_bundle_ref,
        court_verdict_bundle_content_hash=gate.court_verdict_bundle_content_hash,
        protocol_pin_ref=gate.protocol_pin_ref,
        protocol_pin_sha256=gate.protocol_pin_sha256,
        information_set_ref=gate.information_set_ref,
        information_set_hash=gate.information_set_hash,
        validation_report_ref=gate.validation_report_ref,
        validation_output_hash=gate.validation_output_hash,
        baseline_ref=gate.baseline_ref,
        rule_ref=gate.rule_ref,
        odds_version_ref=gate.odds_version_ref,
        cost_version_ref=gate.cost_version_ref,
        friction_version_ref=gate.friction_version_ref,
        exposure_policy_ref=gate.exposure_policy_ref,
        target_ref=gate.target_ref,
        target_window_start=gate.target_window_start,
        target_window_end=gate.target_window_end,
        target_open_time=gate.target_open_time,
        freeze_deadline=gate.freeze_deadline,
        knowledge_cutoff=gate.knowledge_cutoff,
        compiled_at=gate.compiled_at,
        decision_type=decision_type,
        claim_scope=_claim_scope(decision_kind),
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
    _validate_science_axes(
        decision_kind=plan.decision_kind,
        candidate_qualification=plan.candidate_qualification,
        decision_type=plan.decision_type,
        claim_scope=plan.claim_scope,
    )
    if (plan.decision_kind == DecisionKind.NO_ACTION) != bool(plan.no_action_reasons):
        raise ValueError("NO_ACTION kind and refusal reasons disagree")
    if plan.decision_kind not in plan.adjudicated_decision_kinds:
        raise ValueError("decision kind is not permitted by the court bundle")
    return FrozenDecision(
        decision_ref=decision_ref,
        decision_plan_ref=plan.plan_ref,
        decision_plan_hash=plan.plan_hash,
        decision_kind=plan.decision_kind,
        candidate_qualification=plan.candidate_qualification,
        adjudicated_decision_kinds=plan.adjudicated_decision_kinds,
        decision_type=plan.decision_type,
        claim_scope=plan.claim_scope,
        candidate_refs=(plan.candidate_ref,),
        candidate_refs_hash=canonical_sha256((plan.candidate_ref,)),
        court_verdict_bundle_ref=plan.court_verdict_bundle_ref,
        court_verdict_bundle_content_hash=plan.court_verdict_bundle_content_hash,
        protocol_pin_ref=plan.protocol_pin_ref,
        protocol_pin_sha256=plan.protocol_pin_sha256,
        information_set_ref=plan.information_set_ref,
        information_set_hash=plan.information_set_hash,
        target_ref=plan.target_ref,
        target_window_start=plan.target_window_start,
        target_window_end=plan.target_window_end,
        target_open_time=plan.target_open_time,
        freeze_deadline=plan.freeze_deadline,
        knowledge_cutoff=plan.knowledge_cutoff,
        frozen_at=frozen_at,
        baseline_ref=plan.baseline_ref,
        rule_ref=plan.rule_ref,
        odds_version_ref=plan.odds_version_ref,
        cost_version_ref=plan.cost_version_ref,
        friction_version_ref=plan.friction_version_ref,
        exposure_policy_ref=plan.exposure_policy_ref,
        panel=plan.panel,
        selected_number=plan.selected_number,
        stake=plan.stake,
        no_action_reasons=plan.no_action_reasons,
    ).with_content_hash()
