"""Non-vacuous policy sets and exact freeze-all/settle-all consumers.

This module is a thin collection layer over the existing single-decision
compiler and shadow settlement service.  It does not choose research topics,
schedule work, or authorize real-money action.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal
from xinao.decision import (
    DecisionGateInput,
    DecisionKind,
    FrozenDecision,
    compile_decision_plan,
    freeze_decision,
)
from xinao.settlement import (
    OutcomeObservation,
    SettlementBundle,
    settle_frozen_decision,
)
from xinao.shadow_lifecycle.store import (
    FEEDBACK_NAME,
    derive_portfolio_head,
    load_feedback,
    load_frozen,
    load_portfolio,
    load_settled,
    period_directory,
    resolve_root,
)

PORTFOLIO_FEEDBACK_STATE_SCHEMA = "xinao.settled_portfolio_feedback_state.v1"
PORTFOLIO_FEEDBACK_STATE_MARKER = "XINAO_SETTLED_PORTFOLIO_FEEDBACK_STATE_V1"
COST_ACCOUNTING_UNPROVEN = "UNPROVEN_NOT_RECORDED"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PortfolioFeedbackStateError(ValueError):
    """A settled Portfolio cannot be compiled into a truthful feedback state."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _account_amount(value: Decimal | str | int) -> str:
    return format_decimal(value, ACCOUNTING_DECIMAL)


def _drawdown_fraction(*, high_water: Decimal, closing: Decimal) -> str:
    if high_water <= 0:
        return "0.000000"
    value = max(Decimal("0"), high_water - closing) / high_water
    return format(value.quantize(Decimal("0.000001")), "f")


def settled_portfolio_feedback_state_cas_path(
    *,
    portfolio_root: Path,
    content_hash: str,
) -> Path:
    if _HEX_SHA256.fullmatch(content_hash) is None:
        raise PortfolioFeedbackStateError(
            "PORTFOLIO_FEEDBACK_STATE_HASH_INVALID",
            content_hash,
        )
    base = resolve_root(portfolio_root)
    return (
        base
        / "objects"
        / "settled_portfolio_feedback_state"
        / "sha256"
        / content_hash[:2]
        / f"{content_hash}.json"
    )


def compile_settled_portfolio_feedback_state(
    *,
    portfolio_root: Path,
    through_period_index: int | None = None,
) -> dict[str, Any]:
    """Recompute cross-period account facts from the sealed Portfolio store.

    This is a read-only projection.  It never fills absent fees with zero and
    never lets account performance promote a scientific claim.
    """

    base = resolve_root(portfolio_root)
    portfolio = load_portfolio(base)
    head = derive_portfolio_head(base)
    through = head.period_index if through_period_index is None else through_period_index
    if type(through) is not int or through < 1:
        raise PortfolioFeedbackStateError(
            "PORTFOLIO_FEEDBACK_REQUIRES_SETTLED_PERIOD",
            str(through),
        )
    if through > head.period_index:
        raise PortfolioFeedbackStateError(
            "PORTFOLIO_FEEDBACK_PERIOD_BEYOND_HEAD",
            f"through={through} head={head.period_index}",
        )

    genesis = Decimal(portfolio.genesis_opening_balance)
    high_water = genesis
    max_drawdown = Decimal("0")
    max_drawdown_fraction = Decimal("0")
    total_pnl = Decimal("0")
    total_stake = Decimal("0")
    action_count = 0
    no_action_count = 0
    science_candidate_count = 0
    science_no_action_count = 0
    missing_cost_periods: list[int] = []
    periods: list[dict[str, Any]] = []
    prior_close = genesis

    for index in range(1, through + 1):
        period_root = period_directory(base, index)
        try:
            frozen = load_frozen(period_root)
            settled = load_settled(period_root)
        except Exception as exc:
            raise PortfolioFeedbackStateError(
                "PORTFOLIO_FEEDBACK_PERIOD_NOT_SETTLED",
                f"period={index}: {exc}",
            ) from exc
        if frozen.content_hash is None or settled.content_hash is None:
            raise PortfolioFeedbackStateError(
                "PORTFOLIO_FEEDBACK_PERIOD_SEAL_MISSING",
                f"period={index}",
            )
        if settled.frozen_episode_hash != frozen.content_hash:
            raise PortfolioFeedbackStateError(
                "PORTFOLIO_FEEDBACK_FROZEN_SETTLED_MISMATCH",
                f"period={index}",
            )
        statement = settled.statement
        if statement.content_hash is None:
            raise PortfolioFeedbackStateError(
                "PORTFOLIO_FEEDBACK_STATEMENT_SEAL_MISSING",
                f"period={index}",
            )
        opening = Decimal(statement.opening_balance)
        closing = Decimal(statement.closing_balance)
        pnl = Decimal(statement.pnl)
        stake = Decimal(statement.risk_stake)
        if opening != prior_close:
            raise PortfolioFeedbackStateError(
                "PORTFOLIO_FEEDBACK_BALANCE_DISCONTINUITY",
                f"period={index} opening={opening} prior_close={prior_close}",
            )

        high_water = max(high_water, closing)
        drawdown = max(Decimal("0"), high_water - closing)
        drawdown_fraction_text = _drawdown_fraction(high_water=high_water, closing=closing)
        max_drawdown = max(max_drawdown, drawdown)
        max_drawdown_fraction = max(max_drawdown_fraction, Decimal(drawdown_fraction_text))
        total_pnl += pnl
        total_stake += stake
        prior_close = closing

        account_identity = frozen.account_decision.identity.value
        if account_identity == "ACTION":
            action_count += 1
        else:
            no_action_count += 1
        science_identity = frozen.science_decision.identity.value
        if science_identity == "SCIENCE_CANDIDATE":
            science_candidate_count += 1
        else:
            science_no_action_count += 1

        legacy_ticket = frozen.bound_frozen_decision
        account_ticket = frozen.bound_account_ticket
        cost_version_ref = (
            getattr(legacy_ticket, "cost_version_ref", None) if legacy_ticket is not None else None
        )
        friction_version_ref = (
            getattr(legacy_ticket, "friction_version_ref", None)
            if legacy_ticket is not None
            else None
        )
        # Neither production AccountRiskTicket nor AccountStatement records an
        # actual fee amount.  A version ref, when present on a legacy ticket,
        # is not evidence that a cost was posted.
        missing_cost_periods.append(index)
        feedback_hash: str | None = None
        if (period_root / FEEDBACK_NAME).is_file():
            feedback = load_feedback(period_root)
            feedback_hash = feedback.content_hash

        period_body: dict[str, Any] = {
            "period_index": index,
            "episode_ref": frozen.episode_ref,
            "target_ref": frozen.target_ref,
            "frozen_episode_hash": frozen.content_hash,
            "settled_episode_hash": settled.content_hash,
            "statement_hash": statement.content_hash,
            "account_feedback_hash": feedback_hash,
            "account_axis": {
                "identity": account_identity,
                "opening_balance": statement.opening_balance,
                "risk_stake": statement.risk_stake,
                "risk_policy_ref": (
                    account_ticket.risk_policy_ref if account_ticket is not None else None
                ),
                "rule_ref": statement.rule_ref,
                "odds_version_ref": statement.odds_version_ref,
                "odds": statement.odds,
                "result": statement.result.value,
                "recorded_pnl": statement.pnl,
                "closing_balance": statement.closing_balance,
                "high_water_balance": _account_amount(high_water),
                "drawdown_amount": _account_amount(drawdown),
                "drawdown_fraction": drawdown_fraction_text,
                "cost_version_ref": cost_version_ref,
                "friction_version_ref": friction_version_ref,
                "recorded_cost_amount": None,
                "cost_accounting_status": COST_ACCOUNTING_UNPROVEN,
                "after_cost_profit_claim_allowed": False,
            },
            "science_axis": {
                "identity": science_identity,
                "candidate_ref": frozen.science_decision.candidate_ref,
                "science_decision_ref": frozen.science_decision.science_decision_ref,
                "science_decision_hash": frozen.science_decision.content_hash,
                "scientific_promotion": False,
            },
        }
        periods.append({**period_body, "content_hash": canonical_sha256(period_body)})

    state_body: dict[str, Any] = {
        "schema_version": PORTFOLIO_FEEDBACK_STATE_SCHEMA,
        "state_marker": PORTFOLIO_FEEDBACK_STATE_MARKER,
        "portfolio_ref": portfolio.portfolio_ref,
        "portfolio_content_hash": portfolio.content_hash,
        "seat_id": portfolio.seat_id,
        "genesis_opening_balance": portfolio.genesis_opening_balance,
        "through_period_index": through,
        "periods": periods,
        "account_axis": {
            "current_balance": _account_amount(prior_close),
            "recorded_pnl": _account_amount(total_pnl),
            "total_risk_stake": _account_amount(total_stake),
            "high_water_balance": _account_amount(high_water),
            "max_drawdown_amount": _account_amount(max_drawdown),
            "max_drawdown_fraction": format(
                max_drawdown_fraction.quantize(Decimal("0.000001")),
                "f",
            ),
            "action_count": action_count,
            "no_action_count": no_action_count,
            "cost_accounting_status": COST_ACCOUNTING_UNPROVEN,
            "periods_missing_recorded_cost_amount": missing_cost_periods,
            "recorded_cost_total": None,
            "after_cost_profit_claim_allowed": False,
        },
        "science_axis": {
            "science_candidate_count": science_candidate_count,
            "science_no_action_count": science_no_action_count,
            "scientific_promotion": False,
            "account_performance_is_scientific_proof": False,
        },
        "future_outcome_access": False,
        "auto_start_next_research": False,
        "auto_next_period_freeze": False,
        "completion_claim_allowed": False,
    }
    return {**state_body, "content_hash": canonical_sha256(state_body)}


class PolicyRole(StrEnum):
    """Scientific role occupied by one immutable policy version."""

    NO_ACTION = "NO_ACTION"
    NEG_CONTROL = "NEG_CONTROL"
    BASELINE = "BASELINE"
    SUBSTANTIVE = "SUBSTANTIVE"


REQUIRED_RESEARCH_ROLES = frozenset(
    {PolicyRole.NEG_CONTROL, PolicyRole.BASELINE, PolicyRole.SUBSTANTIVE}
)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


class DecisionSignature(BaseModel):
    """Observable behavior signature used to reject renamed duplicates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism: str = Field(min_length=1)
    feature_visibility: tuple[str, ...] = Field(min_length=1)
    time_scale: str = Field(min_length=1)
    update_policy: str = Field(min_length=1)
    abstention_rule: str = Field(min_length=1)
    action_support: str = Field(min_length=1)
    decision_map_ref: str = Field(min_length=1)
    probe_target_count: int = Field(ge=1)
    probe_action_count: int = Field(ge=0)
    probe_trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_probe_counts(self) -> Self:
        if self.probe_action_count > self.probe_target_count:
            raise ValueError("probe action count exceeds probe target count")
        if len(set(self.feature_visibility)) != len(self.feature_visibility):
            raise ValueError("feature visibility entries must be unique")
        return self

    @property
    def signature_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class PolicyCandidateVersion(BaseModel):
    """One immutable Policy/CandidateVersion semantic seal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["PolicyCandidateVersion"] = "PolicyCandidateVersion"
    policy_ref: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    role: PolicyRole
    knowledge_cutoff: datetime
    decision_signature: DecisionSignature
    semantic_config: dict[str, Any]
    exposure_class: Literal["EXPLORATORY"] = "EXPLORATORY"
    claim_ceiling: Literal["E2"] = "E2"
    outcome_access: Literal[False] = False
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_semantics_and_hash(self) -> Self:
        _require_aware(self.knowledge_cutoff, "policy knowledge_cutoff")
        if self.role == PolicyRole.NO_ACTION:
            if self.decision_signature.probe_action_count != 0:
                raise ValueError("NO_ACTION policy probe must always abstain")
        elif self.decision_signature.probe_action_count == 0:
            raise ValueError("research-role policy probe is vacuous")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("policy content_hash does not match its semantic seal")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> PolicyCandidateVersion:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class RoleCoverage(BaseModel):
    """Frozen role-to-policy coverage snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: PolicyRole
    policy_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_refs(self) -> Self:
        if len(set(self.policy_refs)) != len(self.policy_refs):
            raise ValueError("role coverage policy references must be unique")
        if tuple(sorted(self.policy_refs)) != self.policy_refs:
            raise ValueError("role coverage policy references must be sorted")
        return self


class ActiveSet(BaseModel):
    """A non-vacuous ActiveSet under one ProtocolPin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["ActiveSet"] = "ActiveSet"
    active_set_ref: str = Field(min_length=1)
    protocol_pin_ref: str = Field(min_length=1)
    protocol_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admitted_at: datetime
    policies: tuple[PolicyCandidateVersion, ...] = Field(min_length=4)
    residual_axes: tuple[str, ...] = Field(min_length=1)
    role_coverage: tuple[RoleCoverage, ...] = Field(min_length=4)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_non_vacuous(self) -> Self:
        _require_aware(self.admitted_at, "ActiveSet admitted_at")
        if tuple(sorted(self.policies, key=lambda item: item.policy_ref)) != self.policies:
            raise ValueError("ActiveSet policies must be sorted by policy_ref")
        policy_refs = tuple(policy.policy_ref for policy in self.policies)
        if len(set(policy_refs)) != len(policy_refs):
            raise ValueError("ActiveSet policy references must be unique")
        if any(policy.content_hash is None for policy in self.policies):
            raise ValueError("ActiveSet policies must be hash sealed")
        content_hashes = tuple(str(policy.content_hash) for policy in self.policies)
        if len(set(content_hashes)) != len(content_hashes):
            raise ValueError("ActiveSet policy content hashes must be unique")
        signature_hashes = tuple(
            policy.decision_signature.signature_hash for policy in self.policies
        )
        if len(set(signature_hashes)) != len(signature_hashes):
            raise ValueError("ActiveSet contains behaviorally equivalent decision signatures")
        trace_hashes = tuple(policy.decision_signature.probe_trace_hash for policy in self.policies)
        if len(set(trace_hashes)) != len(trace_hashes):
            raise ValueError("ActiveSet probe traces do not demonstrate behavioral diversity")

        roles = {policy.role for policy in self.policies}
        if PolicyRole.NO_ACTION not in roles or not REQUIRED_RESEARCH_ROLES.issubset(roles):
            raise ValueError("ActiveSet lacks NO_ACTION or a required research role")
        if len(set(self.residual_axes)) != len(self.residual_axes):
            raise ValueError("ActiveSet residual axes must be unique")

        coverage = {item.role: item.policy_refs for item in self.role_coverage}
        if len(coverage) != len(self.role_coverage):
            raise ValueError("ActiveSet role coverage contains duplicate roles")
        if set(coverage) != roles:
            raise ValueError("ActiveSet role coverage does not match admitted policy roles")
        by_role: dict[PolicyRole, tuple[str, ...]] = {}
        for role in roles:
            by_role[role] = tuple(
                sorted(policy.policy_ref for policy in self.policies if policy.role == role)
            )
        if coverage != by_role:
            raise ValueError("ActiveSet role coverage references disagree with policies")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("ActiveSet content_hash does not match its contents")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ActiveSet:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class EligibleSet(BaseModel):
    """Policy subset obligated to freeze for one unopened target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["EligibleSet"] = "EligibleSet"
    eligible_set_ref: str = Field(min_length=1)
    active_set_ref: str = Field(min_length=1)
    active_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_ref: str = Field(min_length=1)
    target_open_time: datetime
    created_at: datetime
    eligible_policy_refs: tuple[str, ...] = Field(min_length=4)
    role_coverage: tuple[RoleCoverage, ...] = Field(min_length=4)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_eligibility(self) -> Self:
        _require_aware(self.target_open_time, "EligibleSet target_open_time")
        _require_aware(self.created_at, "EligibleSet created_at")
        if self.created_at >= self.target_open_time:
            raise ValueError("EligibleSet must be created before target open")
        if tuple(sorted(self.eligible_policy_refs)) != self.eligible_policy_refs:
            raise ValueError("EligibleSet policy references must be sorted")
        if len(set(self.eligible_policy_refs)) != len(self.eligible_policy_refs):
            raise ValueError("EligibleSet policy references must be unique")
        coverage_refs = tuple(
            sorted(policy_ref for item in self.role_coverage for policy_ref in item.policy_refs)
        )
        if len({item.role for item in self.role_coverage}) != len(self.role_coverage):
            raise ValueError("EligibleSet role coverage contains duplicate roles")
        if coverage_refs != self.eligible_policy_refs:
            raise ValueError("EligibleSet role coverage does not cover its exact policy set")
        roles = {item.role for item in self.role_coverage}
        if PolicyRole.NO_ACTION not in roles or not REQUIRED_RESEARCH_ROLES.issubset(roles):
            raise ValueError("EligibleSet does not cover the required roles")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("EligibleSet content_hash does not match its contents")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> EligibleSet:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class FrozenPolicyTicket(BaseModel):
    """One policy identity bound to one existing FrozenDecision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["FrozenPolicyTicket"] = "FrozenPolicyTicket"
    policy_ref: str = Field(min_length=1)
    policy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: PolicyRole
    active_set_ref: str = Field(min_length=1)
    active_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_set_ref: str = Field(min_length=1)
    eligible_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_decision: FrozenDecision
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ticket(self) -> Self:
        if self.frozen_decision.content_hash is None:
            raise ValueError("FrozenPolicyTicket decision must be hash sealed")
        if self.frozen_decision.candidate_refs != (self.policy_ref,):
            raise ValueError("FrozenPolicyTicket policy identity and decision candidate disagree")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("FrozenPolicyTicket content_hash does not match its contents")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> FrozenPolicyTicket:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class FrozenDecisionSet(BaseModel):
    """Exact pre-outcome ticket set for one EligibleSet and target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["FrozenDecisionSet"] = "FrozenDecisionSet"
    freeze_set_ref: str = Field(min_length=1)
    active_set_ref: str = Field(min_length=1)
    active_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_set_ref: str = Field(min_length=1)
    eligible_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_ref: str = Field(min_length=1)
    target_open_time: datetime
    frozen_at: datetime
    tickets: tuple[FrozenPolicyTicket, ...] = Field(min_length=4)
    role_coverage: tuple[RoleCoverage, ...] = Field(min_length=4)
    eligible_frozen_count: int = Field(ge=1)
    freeze_coverage: Literal["1.0000"] = "1.0000"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_freeze_set(self) -> Self:
        _require_aware(self.target_open_time, "FrozenDecisionSet target_open_time")
        _require_aware(self.frozen_at, "FrozenDecisionSet frozen_at")
        if self.frozen_at >= self.target_open_time:
            raise ValueError("FrozenDecisionSet must precede target open")
        if tuple(sorted(self.tickets, key=lambda item: item.policy_ref)) != self.tickets:
            raise ValueError("FrozenDecisionSet tickets must be sorted by policy_ref")
        policy_refs = tuple(ticket.policy_ref for ticket in self.tickets)
        if len(set(policy_refs)) != len(policy_refs):
            raise ValueError("FrozenDecisionSet contains duplicate policy tickets")
        if self.eligible_frozen_count != len(self.tickets):
            raise ValueError("eligible_frozen_count does not equal the ticket count")
        if any(ticket.frozen_decision.target_ref != self.target_ref for ticket in self.tickets):
            raise ValueError("FrozenDecisionSet contains a target-mismatched decision")
        if any(
            ticket.frozen_decision.target_open_time != self.target_open_time
            for ticket in self.tickets
        ):
            raise ValueError("FrozenDecisionSet contains an open-time-mismatched decision")
        if any(
            ticket.active_set_ref != self.active_set_ref
            or ticket.active_set_hash != self.active_set_hash
            or ticket.eligible_set_ref != self.eligible_set_ref
            or ticket.eligible_set_hash != self.eligible_set_hash
            for ticket in self.tickets
        ):
            raise ValueError("FrozenDecisionSet ticket collection bindings disagree")
        coverage = {item.role: item.policy_refs for item in self.role_coverage}
        if len(coverage) != len(self.role_coverage):
            raise ValueError("FrozenDecisionSet role coverage contains duplicate roles")
        by_role: dict[PolicyRole, tuple[str, ...]] = {}
        for role in {ticket.role for ticket in self.tickets}:
            by_role[role] = tuple(
                sorted(ticket.policy_ref for ticket in self.tickets if ticket.role == role)
            )
        if coverage != by_role:
            raise ValueError("FrozenDecisionSet role coverage disagrees with tickets")
        if PolicyRole.NO_ACTION not in coverage or not REQUIRED_RESEARCH_ROLES.issubset(coverage):
            raise ValueError("FrozenDecisionSet does not cover the required roles")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("FrozenDecisionSet content_hash does not match its contents")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> FrozenDecisionSet:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class ScoreRow(BaseModel):
    """One append-only settlement row, including explicit NO_ACTION settlement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["ScoreRow"] = "ScoreRow"
    score_row_ref: str = Field(min_length=1)
    ticket_ref: str = Field(min_length=1)
    ticket_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_ref: str = Field(min_length=1)
    policy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: PolicyRole
    decision_kind: DecisionKind
    outcome_ref: str = Field(min_length=1)
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_pin_ref: str = Field(min_length=1)
    protocol_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scoring_rule_ref: str = Field(min_length=1)
    odds_version_ref: str = Field(min_length=1)
    cost_version_ref: str = Field(min_length=1)
    friction_version_ref: str = Field(min_length=1)
    disposition: Literal["SETTLED", "NO_ACTION_SETTLED", "VOID"]
    selected_number: int = Field(ge=1, le=49)
    actual_special_number: int = Field(ge=1, le=49)
    hit: bool | None
    stake: str
    gross_return: str
    realized_gain: str
    realized_loss: str
    settlement_ref: str | None = None
    settlement_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    void_reason_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_disposition_and_hash(self) -> Self:
        zero_amounts = (
            self.stake,
            self.gross_return,
            self.realized_gain,
            self.realized_loss,
        ) == ("0.0000", "0.0000", "0.0000", "0.0000")
        if self.disposition == "SETTLED":
            if self.decision_kind == DecisionKind.NO_ACTION:
                raise ValueError("NO_ACTION cannot use ACTION settlement disposition")
            if self.settlement_ref is None or self.settlement_hash is None or self.hit is None:
                raise ValueError("ACTION settlement row lacks its settlement identity")
            if self.void_reason_hash is not None:
                raise ValueError("settled row cannot carry a void reason")
        elif self.disposition == "NO_ACTION_SETTLED":
            if self.decision_kind != DecisionKind.NO_ACTION:
                raise ValueError("NO_ACTION settlement disposition requires a NO_ACTION ticket")
            if not zero_amounts or self.hit is not None:
                raise ValueError("NO_ACTION settlement must have zero amounts and no hit value")
            if self.settlement_ref is not None or self.settlement_hash is not None:
                raise ValueError("NO_ACTION settlement must not invent an ACTION settlement record")
            if self.void_reason_hash is not None:
                raise ValueError("NO_ACTION settlement is not a VOID")
        else:
            if self.void_reason_hash is None:
                raise ValueError("VOID row requires an immutable reason hash")
            if not zero_amounts or self.hit is not None:
                raise ValueError("VOID row must have zero amounts and no hit value")
            if self.settlement_ref is not None or self.settlement_hash is not None:
                raise ValueError("VOID row must not carry an ACTION settlement record")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("ScoreRow content_hash does not match its contents")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ScoreRow:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class RoleSettlementCoverage(BaseModel):
    """Per-role freeze and settlement coverage for one target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: PolicyRole
    frozen_count: int = Field(ge=1)
    settled_or_void_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.settled_or_void_count != self.frozen_count:
            raise ValueError("role settlement coverage is incomplete")
        return self


class SettlementSet(BaseModel):
    """Closed settle-all result for exactly one FrozenDecisionSet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["SettlementSet"] = "SettlementSet"
    settlement_set_ref: str = Field(min_length=1)
    freeze_set_ref: str = Field(min_length=1)
    freeze_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_ref: str = Field(min_length=1)
    outcome_ref: str = Field(min_length=1)
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    score_rows: tuple[ScoreRow, ...] = Field(min_length=4)
    role_coverage: tuple[RoleSettlementCoverage, ...] = Field(min_length=4)
    eligible_frozen_count: int = Field(ge=1)
    settled_exactly_once_count: int = Field(ge=0)
    void_with_reason_count: int = Field(ge=0)
    missing_or_duplicate_count: Literal[0] = 0
    closed: Literal[True] = True
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_settle_all(self) -> Self:
        if tuple(sorted(self.score_rows, key=lambda item: item.ticket_ref)) != self.score_rows:
            raise ValueError("SettlementSet score rows must be sorted by ticket_ref")
        ticket_refs = tuple(row.ticket_ref for row in self.score_rows)
        if len(set(ticket_refs)) != len(ticket_refs):
            raise ValueError("SettlementSet contains duplicate ticket rows")
        if any(row.content_hash is None for row in self.score_rows):
            raise ValueError("SettlementSet score rows must be hash sealed")
        if self.eligible_frozen_count != len(self.score_rows):
            raise ValueError("SettlementSet row count differs from eligible frozen count")
        settled = sum(row.disposition != "VOID" for row in self.score_rows)
        voided = sum(row.disposition == "VOID" for row in self.score_rows)
        if self.settled_exactly_once_count != settled or self.void_with_reason_count != voided:
            raise ValueError("SettlementSet aggregate counts disagree with score rows")
        if settled + voided != self.eligible_frozen_count:
            raise ValueError("SettlementSet does not conserve all frozen tickets")
        role_counts = Counter(row.role for row in self.score_rows)
        coverage = {item.role: item for item in self.role_coverage}
        if len(coverage) != len(self.role_coverage):
            raise ValueError("SettlementSet role coverage contains duplicate roles")
        if set(coverage) != set(role_counts):
            raise ValueError("SettlementSet role coverage differs from score rows")
        for role, count in role_counts.items():
            if coverage[role].frozen_count != count:
                raise ValueError("SettlementSet role coverage count is incorrect")
        if PolicyRole.NO_ACTION not in coverage or not REQUIRED_RESEARCH_ROLES.issubset(coverage):
            raise ValueError("SettlementSet does not retain required role coverage")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("SettlementSet content_hash does not match its contents")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> SettlementSet:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class SettleAllResult(BaseModel):
    """SettlementSet plus existing per-action accounting bundles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_set: SettlementSet
    action_bundles: tuple[SettlementBundle, ...]


def _role_coverage(policies: tuple[PolicyCandidateVersion, ...]) -> tuple[RoleCoverage, ...]:
    roles = sorted({policy.role for policy in policies}, key=str)
    return tuple(
        RoleCoverage(
            role=role,
            policy_refs=tuple(
                sorted(policy.policy_ref for policy in policies if policy.role == role)
            ),
        )
        for role in roles
    )


def admit_active_set(
    *,
    active_set_ref: str,
    protocol_pin_ref: str,
    protocol_pin_sha256: str,
    admitted_at: datetime,
    policies: tuple[PolicyCandidateVersion, ...],
    residual_axes: tuple[str, ...],
) -> ActiveSet:
    """Admit and hash-seal one demonstrably non-vacuous ActiveSet."""

    ordered = tuple(sorted(policies, key=lambda item: item.policy_ref))
    return ActiveSet(
        active_set_ref=active_set_ref,
        protocol_pin_ref=protocol_pin_ref,
        protocol_pin_sha256=protocol_pin_sha256,
        admitted_at=admitted_at,
        policies=ordered,
        residual_axes=residual_axes,
        role_coverage=_role_coverage(ordered),
    ).with_content_hash()


def admit_eligible_set(
    *,
    active_set: ActiveSet,
    eligible_set_ref: str,
    target_ref: str,
    target_open_time: datetime,
    created_at: datetime,
    eligible_policy_refs: tuple[str, ...] | None = None,
) -> EligibleSet:
    """Resolve exact Eligible policies and reject role-shrinking theater."""

    if active_set.content_hash is None:
        raise ValueError("ActiveSet must be hash sealed before eligibility admission")
    by_ref = {policy.policy_ref: policy for policy in active_set.policies}
    selected_refs = tuple(sorted(eligible_policy_refs or tuple(by_ref)))
    if set(selected_refs) - set(by_ref):
        raise ValueError("EligibleSet references a policy outside ActiveSet")
    selected = tuple(by_ref[policy_ref] for policy_ref in selected_refs)
    roles = {policy.role for policy in selected}
    if PolicyRole.NO_ACTION not in roles or not REQUIRED_RESEARCH_ROLES.issubset(roles):
        raise ValueError("EligibleSet role coverage is incomplete")
    required_traces = {
        policy.decision_signature.probe_trace_hash
        for policy in selected
        if policy.role in REQUIRED_RESEARCH_ROLES
    }
    required_policies = sum(policy.role in REQUIRED_RESEARCH_ROLES for policy in selected)
    if len(required_traces) != required_policies:
        raise ValueError("EligibleSet required-role representatives are behaviorally equivalent")
    return EligibleSet(
        eligible_set_ref=eligible_set_ref,
        active_set_ref=active_set.active_set_ref,
        active_set_hash=active_set.content_hash,
        target_ref=target_ref,
        target_open_time=target_open_time,
        created_at=created_at,
        eligible_policy_refs=selected_refs,
        role_coverage=_role_coverage(selected),
    ).with_content_hash()


def freeze_all(
    *,
    active_set: ActiveSet,
    eligible_set: EligibleSet,
    gates: Mapping[str, DecisionGateInput],
    freeze_set_ref: str,
    frozen_at: datetime,
) -> FrozenDecisionSet:
    """Freeze one exact ACTION/NO_ACTION ticket for every Eligible policy."""

    if active_set.content_hash is None or eligible_set.content_hash is None:
        raise ValueError("ActiveSet and EligibleSet must be hash sealed before freeze-all")
    if (
        eligible_set.active_set_ref != active_set.active_set_ref
        or eligible_set.active_set_hash != active_set.content_hash
    ):
        raise ValueError("EligibleSet is not bound to the supplied ActiveSet")
    expected_refs = set(eligible_set.eligible_policy_refs)
    if set(gates) != expected_refs:
        missing = sorted(expected_refs - set(gates))
        extra = sorted(set(gates) - expected_refs)
        raise ValueError(f"freeze-all gate coverage differs: missing={missing}, extra={extra}")
    policies = {policy.policy_ref: policy for policy in active_set.policies}
    tickets: list[FrozenPolicyTicket] = []
    for policy_ref in sorted(expected_refs):
        policy = policies[policy_ref]
        gate = gates[policy_ref]
        if gate.candidate_ref != policy_ref:
            raise ValueError("freeze-all gate candidate identity differs from policy")
        if gate.protocol_pin_ref != active_set.protocol_pin_ref or (
            gate.protocol_pin_sha256 != active_set.protocol_pin_sha256
        ):
            raise ValueError("freeze-all gate ProtocolPin differs from ActiveSet")
        if gate.target_ref != eligible_set.target_ref:
            raise ValueError("freeze-all gate target differs from EligibleSet")
        if gate.target_open_time != eligible_set.target_open_time:
            raise ValueError("freeze-all gate open time differs from EligibleSet")
        plan = compile_decision_plan(
            gate,
            plan_ref=f"{freeze_set_ref}/decision-plan/{policy_ref}",
        )
        decision = freeze_decision(
            plan,
            decision_ref=f"{freeze_set_ref}/ticket/{policy_ref}",
            frozen_at=frozen_at,
        )
        tickets.append(
            FrozenPolicyTicket(
                policy_ref=policy_ref,
                policy_content_hash=str(policy.content_hash),
                role=policy.role,
                active_set_ref=active_set.active_set_ref,
                active_set_hash=active_set.content_hash,
                eligible_set_ref=eligible_set.eligible_set_ref,
                eligible_set_hash=eligible_set.content_hash,
                frozen_decision=decision,
            ).with_content_hash()
        )
    ordered = tuple(tickets)
    return FrozenDecisionSet(
        freeze_set_ref=freeze_set_ref,
        active_set_ref=active_set.active_set_ref,
        active_set_hash=active_set.content_hash,
        eligible_set_ref=eligible_set.eligible_set_ref,
        eligible_set_hash=eligible_set.content_hash,
        target_ref=eligible_set.target_ref,
        target_open_time=eligible_set.target_open_time,
        frozen_at=frozen_at,
        tickets=ordered,
        role_coverage=tuple(
            RoleCoverage(
                role=role,
                policy_refs=tuple(
                    sorted(ticket.policy_ref for ticket in ordered if ticket.role == role)
                ),
            )
            for role in sorted({ticket.role for ticket in ordered}, key=str)
        ),
        eligible_frozen_count=len(ordered),
    ).with_content_hash()


def settle_all(
    *,
    freeze_set: FrozenDecisionSet,
    outcome: OutcomeObservation,
    settlement_set_ref: str,
    portfolio_ref: str,
    occurred_at: datetime,
    void_reason_hashes: Mapping[str, str] | None = None,
) -> SettleAllResult:
    """Settle or explicitly VOID every frozen ticket exactly once."""

    if freeze_set.content_hash is None or outcome.result_hash is None:
        raise ValueError("FrozenDecisionSet and outcome must be hash sealed")
    if not outcome.verified:
        raise ValueError("settle-all requires a verified outcome")
    if outcome.target_ref != freeze_set.target_ref:
        raise ValueError("settle-all outcome target differs from FrozenDecisionSet")
    _require_aware(outcome.observed_at, "outcome observed_at")
    _require_aware(occurred_at, "settlement occurred_at")
    if outcome.observed_at < freeze_set.target_open_time:
        raise ValueError("settle-all outcome was observed before target open")
    if occurred_at < outcome.observed_at:
        raise ValueError("settlement occurred before outcome observation")

    voids = dict(void_reason_hashes or {})
    known_ticket_refs = {ticket.frozen_decision.decision_ref for ticket in freeze_set.tickets}
    if set(voids) - known_ticket_refs:
        raise ValueError("settle-all contains a VOID reason for an unknown ticket")

    score_rows: list[ScoreRow] = []
    bundles: list[SettlementBundle] = []
    zero = "0.0000"
    for ticket in freeze_set.tickets:
        decision = ticket.frozen_decision
        ticket_ref = decision.decision_ref
        common: dict[str, Any] = {
            "score_row_ref": f"{settlement_set_ref}/score-row/{ticket.policy_ref}",
            "ticket_ref": ticket_ref,
            "ticket_hash": str(ticket.content_hash),
            "frozen_decision_hash": str(decision.content_hash),
            "policy_ref": ticket.policy_ref,
            "policy_content_hash": ticket.policy_content_hash,
            "role": ticket.role,
            "decision_kind": decision.decision_kind,
            "outcome_ref": outcome.outcome_ref,
            "outcome_hash": outcome.result_hash,
            "protocol_pin_ref": decision.protocol_pin_ref,
            "protocol_pin_sha256": decision.protocol_pin_sha256,
            "scoring_rule_ref": decision.rule_ref,
            "odds_version_ref": decision.odds_version_ref,
            "cost_version_ref": decision.cost_version_ref,
            "friction_version_ref": decision.friction_version_ref,
            "selected_number": decision.selected_number,
            "actual_special_number": outcome.actual_special_number,
        }
        if ticket_ref in voids:
            row = ScoreRow(
                **common,
                disposition="VOID",
                hit=None,
                stake=zero,
                gross_return=zero,
                realized_gain=zero,
                realized_loss=zero,
                void_reason_hash=voids[ticket_ref],
            ).with_content_hash()
        elif decision.decision_kind == DecisionKind.NO_ACTION:
            row = ScoreRow(
                **common,
                disposition="NO_ACTION_SETTLED",
                hit=None,
                stake=zero,
                gross_return=zero,
                realized_gain=zero,
                realized_loss=zero,
            ).with_content_hash()
        else:
            settlement_ref = f"{settlement_set_ref}/settlement/{ticket.policy_ref}"
            bundle = settle_frozen_decision(
                frozen=decision,
                outcome=outcome,
                settlement_ref=settlement_ref,
                journal_group_ref=f"{settlement_set_ref}/journal/{ticket.policy_ref}",
                portfolio_ref=portfolio_ref,
                occurred_at=occurred_at,
            )
            bundles.append(bundle)
            result = bundle.record.result
            row = ScoreRow(
                **common,
                disposition="SETTLED",
                hit=result.hit,
                stake=result.stake,
                gross_return=result.gross_return,
                realized_gain=result.realized_gain,
                realized_loss=result.realized_loss,
                settlement_ref=bundle.record.settlement_ref,
                settlement_hash=bundle.record.settlement_hash,
            ).with_content_hash()
        score_rows.append(row)

    ordered_rows = tuple(sorted(score_rows, key=lambda item: item.ticket_ref))
    role_counts = Counter(row.role for row in ordered_rows)
    settlement_set = SettlementSet(
        settlement_set_ref=settlement_set_ref,
        freeze_set_ref=freeze_set.freeze_set_ref,
        freeze_set_hash=freeze_set.content_hash,
        target_ref=freeze_set.target_ref,
        outcome_ref=outcome.outcome_ref,
        outcome_hash=outcome.result_hash,
        score_rows=ordered_rows,
        role_coverage=tuple(
            RoleSettlementCoverage(
                role=role,
                frozen_count=count,
                settled_or_void_count=count,
            )
            for role, count in sorted(role_counts.items(), key=lambda item: str(item[0]))
        ),
        eligible_frozen_count=len(freeze_set.tickets),
        settled_exactly_once_count=sum(row.disposition != "VOID" for row in ordered_rows),
        void_with_reason_count=sum(row.disposition == "VOID" for row in ordered_rows),
    ).with_content_hash()
    return SettleAllResult(settlement_set=settlement_set, action_bundles=tuple(bundles))


__all__ = [
    "COST_ACCOUNTING_UNPROVEN",
    "PORTFOLIO_FEEDBACK_STATE_MARKER",
    "PORTFOLIO_FEEDBACK_STATE_SCHEMA",
    "REQUIRED_RESEARCH_ROLES",
    "ActiveSet",
    "DecisionSignature",
    "EligibleSet",
    "FrozenDecisionSet",
    "FrozenPolicyTicket",
    "PolicyCandidateVersion",
    "PolicyRole",
    "PortfolioFeedbackStateError",
    "RoleCoverage",
    "RoleSettlementCoverage",
    "ScoreRow",
    "SettleAllResult",
    "SettlementSet",
    "admit_active_set",
    "admit_eligible_set",
    "compile_settled_portfolio_feedback_state",
    "freeze_all",
    "settle_all",
    "settled_portfolio_feedback_state_cas_path",
]
