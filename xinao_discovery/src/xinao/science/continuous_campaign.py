"""Fixed-cutoff continuous campaign over historical replay and future tickets.

The campaign keeps candidate information frozen at the formal dataset boundary.
Post-cutoff outcomes may settle and evaluate tickets, but never enter candidate
features, selection, tuning, or policy hashes.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256
from xinao.catalog.compiler import sha256_file
from xinao.science.day1_portfolio import (
    DAY1_POLICY_REFS,
    Day1PolicyCompilation,
    PolicyHashBinding,
    SpecialNumberObservation,
    build_day1_policy_compilation,
    observations_from_draws,
    parse_macaujc_history_response,
)
from xinao.science.multipolicy_episode import (
    SOURCE_CONTRACT_REF,
    _fetch_live_source,
    _millisecond_now,
    build_episode_package,
    verify_episode_package,
)
from xinao.science.portfolio import PolicyRole, ScoreRow, SettlementSet
from xinao.settlement import OutcomeObservation
from xinao.world.builder import load_draws

CAMPAIGN_MANIFEST_NAME = "continuous_campaign_manifest.v1.json"
ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKLY_CLOSE_POLICY_REF = "weekly-close.asia-shanghai.monday-1500.v1"
HOMOGENEITY_AUDIT_MIN_TARGETS = 7
_MONEY_QUANTUM = Decimal("0.0001")
_BASELINE_POLICY_REF = "policy.day1.baseline-rolling-marginal-w90.v1"
_SUBSTANTIVE_POLICY_REF = "policy.day1.substantive-multiscale-overlap-7-14-28.v1"


class CampaignCadence(StrEnum):
    """Current campaign cadence selected by the parent ProtocolPin."""

    FROZEN_INCUMBENT = "FROZEN_INCUMBENT"


class CampaignTemporalIdentity(StrEnum):
    """Whether a target was truly frozen live or reconstructed after outcome."""

    SIMULATED_HISTORICAL_REPLAY = "SIMULATED_HISTORICAL_REPLAY"
    LIVE_PRE_OUTCOME = "LIVE_PRE_OUTCOME"


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _model_hash(bindings: Sequence[PolicyHashBinding]) -> str:
    return canonical_sha256([item.model_dump(mode="json") for item in bindings])


class ProspectiveTarget(BaseModel):
    """Earliest target whose real freeze deadline is still open."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_ref: str = Field(pattern=r"^macaujc2/expect/\d{7}$")
    target_open_time: datetime
    freeze_deadline: datetime
    skipped_missed_deadline_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_times(self) -> Self:
        _require_aware(self.target_open_time, "prospective target open time")
        _require_aware(self.freeze_deadline, "prospective freeze deadline")
        if self.freeze_deadline >= self.target_open_time:
            raise ValueError("prospective freeze deadline must precede target open")
        return self


class ContinuousCampaignPin(BaseModel):
    """One policy seal spanning replay targets and the next live ticket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.continuous_campaign_pin.v1"] = "xinao.continuous_campaign_pin.v1"
    campaign_id: str = Field(min_length=1)
    campaign_ref: str = Field(min_length=1)
    pinned_at: datetime
    cadence: Literal[CampaignCadence.FROZEN_INCUMBENT] = CampaignCadence.FROZEN_INCUMBENT
    policy_dataset_ref: str = Field(min_length=1)
    policy_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_observation_count: int = Field(ge=180)
    candidate_information_latest_expect: str = Field(pattern=r"^\d{7}$")
    candidate_information_cutoff: datetime
    candidate_information_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_bindings: tuple[PolicyHashBinding, ...] = Field(min_length=4, max_length=4)
    post_cutoff_outcome_use: Literal["SETTLEMENT_AND_EVALUATION_ONLY"] = (
        "SETTLEMENT_AND_EVALUATION_ONLY"
    )
    validation_source_ref: str = Field(min_length=1)
    validation_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_source_captured_at: datetime
    historical_target_refs: tuple[str, ...] = Field(min_length=1)
    historical_temporal_identity: Literal[CampaignTemporalIdentity.SIMULATED_HISTORICAL_REPLAY] = (
        CampaignTemporalIdentity.SIMULATED_HISTORICAL_REPLAY
    )
    historical_claim_ceiling: Literal["E2"] = "E2"
    prospective_target_ref: str = Field(pattern=r"^macaujc2/expect/\d{7}$")
    prospective_target_open_time: datetime
    prospective_freeze_deadline: datetime
    real_money_authorized: Literal[False] = False
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_pin(self) -> Self:
        for label, value in (
            ("pinned_at", self.pinned_at),
            ("candidate_information_cutoff", self.candidate_information_cutoff),
            ("validation_source_captured_at", self.validation_source_captured_at),
            ("prospective_target_open_time", self.prospective_target_open_time),
            ("prospective_freeze_deadline", self.prospective_freeze_deadline),
        ):
            _require_aware(value, label)
        if self.validation_source_captured_at > self.pinned_at:
            raise ValueError("campaign was pinned before its validation source capture")
        if not (
            self.candidate_information_cutoff
            <= self.pinned_at
            <= self.prospective_freeze_deadline
            < self.prospective_target_open_time
        ):
            raise ValueError("continuous campaign temporal boundaries are invalid")
        if tuple(binding.policy_ref for binding in self.policy_bindings) != DAY1_POLICY_REFS:
            raise ValueError("continuous campaign policy bindings drifted")
        if len({binding.content_hash for binding in self.policy_bindings}) != 4:
            raise ValueError("continuous campaign policy hashes must be unique")
        if self.policy_set_hash != _model_hash(self.policy_bindings):
            raise ValueError("continuous campaign policy_set_hash differs from its bindings")
        if tuple(sorted(set(self.historical_target_refs))) != self.historical_target_refs:
            raise ValueError("historical target refs must be sorted and unique")
        if self.prospective_target_ref in self.historical_target_refs:
            raise ValueError("prospective target is already present in historical outcomes")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("continuous campaign pin content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ContinuousCampaignPin:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class CampaignTargetRecord(BaseModel):
    """One immutable campaign child target and its exact child-package pin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence_index: int = Field(ge=1)
    target_ref: str = Field(pattern=r"^macaujc2/expect/\d{7}$")
    target_open_time: datetime
    temporal_identity: CampaignTemporalIdentity
    episode_dir: str = Field(min_length=1)
    episode_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_bindings: tuple[PolicyHashBinding, ...] = Field(min_length=4, max_length=4)
    candidate_information_cutoff: datetime
    candidate_information_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_information_role: Literal["SETTLEMENT_ONLY", "TARGET_SCHEDULING_ONLY"]
    state: Literal["HISTORICAL_REPLAY_SETTLED", "FROZEN_AWAITING_VERIFIED_OUTCOME"]
    eligible_frozen_count: Literal[4] = 4
    settled_exactly_once_count: int = Field(ge=0, le=4)
    claim_grade: Literal[
        "E2_MAX_HISTORICAL_SIMULATED_REPLAY",
        "E2_CEILING_AWAITING_PROSPECTIVE_OUTCOME",
    ]
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        _require_aware(self.target_open_time, "campaign target open time")
        _require_aware(self.candidate_information_cutoff, "campaign target information cutoff")
        historical = self.temporal_identity == CampaignTemporalIdentity.SIMULATED_HISTORICAL_REPLAY
        if historical != (self.state == "HISTORICAL_REPLAY_SETTLED"):
            raise ValueError("campaign target temporal identity and state disagree")
        if historical:
            if (
                self.outcome_information_role != "SETTLEMENT_ONLY"
                or self.settled_exactly_once_count != 4
                or self.claim_grade != "E2_MAX_HISTORICAL_SIMULATED_REPLAY"
            ):
                raise ValueError("historical campaign target settlement semantics are invalid")
        elif (
            self.outcome_information_role != "TARGET_SCHEDULING_ONLY"
            or self.settled_exactly_once_count != 0
            or self.claim_grade != "E2_CEILING_AWAITING_PROSPECTIVE_OUTCOME"
        ):
            raise ValueError("prospective campaign target semantics are invalid")
        if self.policy_set_hash != _model_hash(self.policy_bindings):
            raise ValueError("campaign target policy bindings differ from policy_set_hash")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("campaign target content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> CampaignTargetRecord:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class PolicyCampaignScore(BaseModel):
    """Deterministic aggregate of one policy's immutable ScoreRows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: str = Field(min_length=1)
    policy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: PolicyRole
    target_count: int = Field(ge=1)
    action_count: int = Field(ge=0)
    no_action_count: int = Field(ge=0)
    void_count: int = Field(ge=0)
    hit_count: int = Field(ge=0)
    unique_selected_numbers: tuple[int, ...]
    behavior_trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_stake: str
    total_gross_return: str
    total_realized_gain: str
    total_realized_loss: str
    net_result: str
    advantage_status: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_score(self) -> Self:
        if self.action_count + self.no_action_count + self.void_count != self.target_count:
            raise ValueError("policy aggregate dispositions do not conserve targets")
        if self.hit_count > self.action_count:
            raise ValueError("policy aggregate hit count exceeds action count")
        if tuple(sorted(set(self.unique_selected_numbers))) != self.unique_selected_numbers:
            raise ValueError("policy aggregate selected numbers must be sorted and unique")
        for amount in (
            self.total_stake,
            self.total_gross_return,
            self.total_realized_gain,
            self.total_realized_loss,
            self.net_result,
        ):
            Decimal(amount)
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("policy campaign score content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> PolicyCampaignScore:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class CampaignWeeklyPeriod(BaseModel):
    """One Asia/Shanghai Monday-15:00 half-open accounting projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    period_ref: str = Field(min_length=1)
    weekly_close_policy_ref: Literal["weekly-close.asia-shanghai.monday-1500.v1"] = (
        WEEKLY_CLOSE_POLICY_REF
    )
    period_start: datetime
    period_end: datetime
    target_refs: tuple[str, ...] = Field(min_length=1)
    target_count: int = Field(ge=1, le=7)
    expected_target_count: Literal[7] = 7
    settled_ticket_count: int = Field(ge=4, le=28)
    closure_state: Literal["CLOSED", "PARTIAL_VALIDATION_WINDOW"]
    policy_scores: tuple[PolicyCampaignScore, ...] = Field(min_length=4, max_length=4)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        _require_aware(self.period_start, "weekly period start")
        _require_aware(self.period_end, "weekly period end")
        if self.period_end - self.period_start != timedelta(days=7):
            raise ValueError("weekly period must span exactly seven days")
        if self.target_count != len(self.target_refs):
            raise ValueError("weekly period target count differs from target refs")
        if self.settled_ticket_count != self.target_count * 4:
            raise ValueError("weekly period does not contain four settled tickets per target")
        if tuple(score.policy_ref for score in self.policy_scores) != DAY1_POLICY_REFS:
            raise ValueError("weekly period policy score order drifted")
        if any(score.target_count != self.target_count for score in self.policy_scores):
            raise ValueError("weekly policy score coverage differs from period coverage")
        expected_state = "CLOSED" if self.target_count == 7 else "PARTIAL_VALIDATION_WINDOW"
        if self.closure_state != expected_state:
            raise ValueError("weekly period closure state differs from its coverage")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("weekly period content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> CampaignWeeklyPeriod:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class BehaviorEquivalenceCluster(BaseModel):
    """Observed cross-role action equivalence over the replay target stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_ref: str = Field(min_length=1)
    behavior_trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_refs: tuple[str, ...] = Field(min_length=2)
    roles: tuple[PolicyRole, ...] = Field(min_length=2)
    target_count: int = Field(ge=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_cluster(self) -> Self:
        if tuple(sorted(set(self.policy_refs))) != self.policy_refs:
            raise ValueError("equivalence cluster policy refs must be sorted and unique")
        if tuple(sorted(set(self.roles), key=str)) != self.roles:
            raise ValueError("equivalence cluster roles must be sorted and unique")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("equivalence cluster content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> BehaviorEquivalenceCluster:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class CampaignNextQuestionSet(BaseModel):
    """Bounded successor question; it cannot silently mutate the frozen campaign."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_type: Literal["NextQuestionSet"] = "NextQuestionSet"
    next_question_set_ref: str = Field(min_length=1)
    campaign_ref: str = Field(min_length=1)
    campaign_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trigger_reasons: tuple[str, ...] = Field(min_length=1)
    question: str = Field(min_length=1)
    challenger_cadences: tuple[
        Literal["PER_TARGET_UPDATE", "RETRAIN_EVERY_7_TARGETS", "FIXED_7_TARGET_BATCH"],
        ...,
    ] = Field(min_length=3, max_length=3)
    requires_new_protocol_version: Literal[True] = True
    past_outcomes_role: Literal["DESIGN_AND_E2_ONLY"] = "DESIGN_AND_E2_ONLY"
    prospective_evidence_inherited: Literal[False] = False
    earliest_eligible_target_ref: str = Field(pattern=r"^macaujc2/expect/\d{7}$")
    eligibility_condition: Literal[
        "NEW_POLICIES_MUST_BE_PINNED_BEFORE_THEIR_TARGET_FREEZE_DEADLINE"
    ] = "NEW_POLICIES_MUST_BE_PINNED_BEFORE_THEIR_TARGET_FREEZE_DEADLINE"
    parent_idle: Literal[False] = False
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_next_question(self) -> Self:
        if len(set(self.trigger_reasons)) != len(self.trigger_reasons):
            raise ValueError("next-question trigger reasons must be unique")
        if len(set(self.challenger_cadences)) != 3:
            raise ValueError("next-question challenger cadences must be unique")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("next-question set content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> CampaignNextQuestionSet:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class ContinuousCampaignEvaluation(BaseModel):
    """Weekly and campaign-level E2 result, audit, and successor question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.continuous_campaign_evaluation.v1"] = (
        "xinao.continuous_campaign_evaluation.v1"
    )
    evaluation_ref: str = Field(min_length=1)
    campaign_ref: str = Field(min_length=1)
    campaign_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    weekly_close_policy_ref: Literal["weekly-close.asia-shanghai.monday-1500.v1"] = (
        WEEKLY_CLOSE_POLICY_REF
    )
    historical_target_count: int = Field(ge=1)
    global_policy_scores: tuple[PolicyCampaignScore, ...] = Field(min_length=4, max_length=4)
    weekly_periods: tuple[CampaignWeeklyPeriod, ...] = Field(min_length=1)
    complete_weekly_period_count: int = Field(ge=0)
    partial_weekly_period_count: int = Field(ge=0)
    behavior_equivalence_clusters: tuple[BehaviorEquivalenceCluster, ...]
    homogeneity_audit_min_targets: Literal[7] = HOMOGENEITY_AUDIT_MIN_TARGETS
    portfolio_health: Literal[
        "DEGRADED_HOMOGENEITY",
        "NO_CROSS_ROLE_CO_COLLAPSE_OBSERVED",
        "UNDERPOWERED_HOMOGENEITY_AUDIT",
    ]
    evaluation_conclusion: Literal["NO_PREDICTIVE_ADVANTAGE_ESTABLISHED"] = (
        "NO_PREDICTIVE_ADVANTAGE_ESTABLISHED"
    )
    historical_claim_ceiling: Literal["E2"] = "E2"
    prospective_evidence_inherited: Literal[False] = False
    next_question_set: CampaignNextQuestionSet
    parent_idle: Literal[False] = False
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        if tuple(score.policy_ref for score in self.global_policy_scores) != DAY1_POLICY_REFS:
            raise ValueError("campaign evaluation policy score order drifted")
        if any(
            score.target_count != self.historical_target_count
            for score in self.global_policy_scores
        ):
            raise ValueError("campaign evaluation policy coverage differs")
        complete = sum(period.closure_state == "CLOSED" for period in self.weekly_periods)
        partial = sum(
            period.closure_state == "PARTIAL_VALIDATION_WINDOW" for period in self.weekly_periods
        )
        if (complete, partial) != (
            self.complete_weekly_period_count,
            self.partial_weekly_period_count,
        ):
            raise ValueError("campaign evaluation weekly counts differ")
        collapsed_pair = {_BASELINE_POLICY_REF, _SUBSTANTIVE_POLICY_REF}
        degraded = self.historical_target_count >= HOMOGENEITY_AUDIT_MIN_TARGETS and any(
            collapsed_pair.issubset(cluster.policy_refs)
            for cluster in self.behavior_equivalence_clusters
        )
        expected_health = (
            "UNDERPOWERED_HOMOGENEITY_AUDIT"
            if self.historical_target_count < HOMOGENEITY_AUDIT_MIN_TARGETS
            else ("DEGRADED_HOMOGENEITY" if degraded else "NO_CROSS_ROLE_CO_COLLAPSE_OBSERVED")
        )
        if self.portfolio_health != expected_health:
            raise ValueError("campaign portfolio health differs from homogeneity evidence")
        if self.next_question_set.content_hash is None:
            raise ValueError("campaign evaluation next-question set is not sealed")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("campaign evaluation content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ContinuousCampaignEvaluation:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class ContinuousCampaignLedger(BaseModel):
    """Append-free sealed projection of one replay plus its next live frontier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.continuous_campaign_ledger.v1"] = (
        "xinao.continuous_campaign_ledger.v1"
    )
    campaign_ref: str = Field(min_length=1)
    campaign_pin_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: tuple[CampaignTargetRecord, ...] = Field(min_length=2)
    historical_settled_target_count: int = Field(ge=1)
    historical_settled_ticket_count: int = Field(ge=4)
    prospective_pending_target_count: Literal[1] = 1
    post_cutoff_candidate_observation_count: Literal[0] = 0
    skipped_missed_deadline_refs: tuple[str, ...] = ()
    waiting_scope: Literal["TARGET_ONLY"] = "TARGET_ONLY"
    parent_idle: Literal[False] = False
    real_money_authorized: Literal[False] = False
    parent_complete: Literal[False] = False
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ledger(self) -> Self:
        if tuple(item.sequence_index for item in self.targets) != tuple(
            range(1, len(self.targets) + 1)
        ):
            raise ValueError("campaign target sequence is not contiguous")
        if len({item.target_ref for item in self.targets}) != len(self.targets):
            raise ValueError("campaign ledger contains duplicate targets")
        historical = tuple(
            item for item in self.targets if item.state == "HISTORICAL_REPLAY_SETTLED"
        )
        prospective = tuple(
            item for item in self.targets if item.state == "FROZEN_AWAITING_VERIFIED_OUTCOME"
        )
        if len(historical) != self.historical_settled_target_count:
            raise ValueError("campaign historical target count differs")
        if sum(item.settled_exactly_once_count for item in historical) != (
            self.historical_settled_ticket_count
        ):
            raise ValueError("campaign historical ticket count differs")
        if len(prospective) != 1 or prospective[0] != self.targets[-1]:
            raise ValueError("campaign must end in exactly one prospective target")
        if len({item.policy_set_hash for item in self.targets}) != 1:
            raise ValueError("campaign minted target-specific policy identities")
        if len({item.candidate_information_set_hash for item in self.targets}) != 1:
            raise ValueError("campaign target information sets drifted")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("continuous campaign ledger content_hash does not match")
        return self

    def canonical_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ContinuousCampaignLedger:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


def split_fixed_cutoff_stream(
    policy_observations: Sequence[SpecialNumberObservation],
    observed_source: Sequence[SpecialNumberObservation],
) -> tuple[tuple[SpecialNumberObservation, ...], tuple[SpecialNumberObservation, ...]]:
    """Verify the source overlap and isolate outcomes strictly after the fixed cutoff."""

    fixed = tuple(policy_observations)
    source = tuple(observed_source)
    if len(fixed) < 180 or not source:
        raise ValueError("fixed campaign requires policy history and an observed source")
    fixed_latest = fixed[-1]
    fixed_by_expect = {item.expect: item for item in fixed}
    if len(fixed_by_expect) != len(fixed):
        raise ValueError("fixed policy observations contain duplicate identities")
    overlap = tuple(item for item in source if item.open_time <= fixed_latest.open_time)
    if not overlap or overlap[-1].expect != fixed_latest.expect:
        raise ValueError("observed source does not reach the formal prefix boundary")
    for item in overlap:
        expected = fixed_by_expect.get(item.expect)
        if expected is None or (
            expected.open_time != item.open_time or expected.special_number != item.special_number
        ):
            raise ValueError("observed source differs from the formal prefix")
    validation = tuple(item for item in source if item.open_time > fixed_latest.open_time)
    if not validation:
        raise ValueError("post-cutoff validation window is empty")
    previous_expect = int(fixed_latest.expect)
    previous_time = fixed_latest.open_time
    for item in validation:
        if int(item.expect) != previous_expect + 1 or item.open_time <= previous_time:
            raise ValueError("post-cutoff validation stream is not sequential")
        previous_expect = int(item.expect)
        previous_time = item.open_time
    return fixed, validation


def select_next_legal_target(
    latest: SpecialNumberObservation,
    *,
    now: datetime,
    freeze_lead: timedelta = timedelta(hours=1),
    max_lookahead: int = 7,
) -> ProspectiveTarget:
    """Select the first future target whose deadline has not already been missed."""

    _require_aware(now, "campaign selection time")
    _require_aware(latest.open_time, "latest outcome open time")
    skipped: list[str] = []
    for offset in range(1, max_lookahead + 1):
        expect = str(int(latest.expect) + offset)
        target_ref = f"macaujc2/expect/{expect}"
        target_open_time = latest.open_time + timedelta(days=offset)
        freeze_deadline = target_open_time - freeze_lead
        if now <= freeze_deadline:
            return ProspectiveTarget(
                target_ref=target_ref,
                target_open_time=target_open_time,
                freeze_deadline=freeze_deadline,
                skipped_missed_deadline_refs=tuple(skipped),
            )
        skipped.append(target_ref)
    raise ValueError("no legal prospective target remains inside the bounded lookahead")


def _write_new_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _write_model(path: Path, model: BaseModel) -> None:
    _write_new_json(path, model.model_dump(mode="json"))


def _campaign_manifest(root: Path) -> dict[str, Any]:
    artifacts = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == CAMPAIGN_MANIFEST_NAME:
            continue
        artifacts.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": "xinao.continuous_campaign_manifest.v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "content_hash": canonical_sha256(artifacts),
    }


def _policy_bindings(compilation: Day1PolicyCompilation) -> tuple[PolicyHashBinding, ...]:
    return tuple(
        PolicyHashBinding(
            policy_ref=policy.policy_ref,
            content_hash=str(policy.content_hash),
            role=policy.role,
        )
        for policy in compilation.policies
    )


def _money_text(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM), "f")


def _summarize_policy_rows(
    rows: Sequence[tuple[str, ScoreRow]],
) -> tuple[PolicyCampaignScore, ...]:
    by_policy: dict[str, list[tuple[str, ScoreRow]]] = defaultdict(list)
    for target_ref, row in rows:
        by_policy[row.policy_ref].append((target_ref, row))
    if tuple(sorted(by_policy)) != DAY1_POLICY_REFS:
        raise ValueError("campaign score rows do not cover the fixed policy set")

    summaries: list[PolicyCampaignScore] = []
    for policy_ref in DAY1_POLICY_REFS:
        policy_rows = by_policy[policy_ref]
        first = policy_rows[0][1]
        if any(
            row.policy_content_hash != first.policy_content_hash or row.role != first.role
            for _, row in policy_rows
        ):
            raise ValueError("campaign score row policy identity drifted")
        behavior_trace = [
            {
                "target_ref": target_ref,
                "decision_kind": row.decision_kind.value,
                "selected_number": (
                    None if row.decision_kind.value == "NO_ACTION" else row.selected_number
                ),
            }
            for target_ref, row in policy_rows
        ]
        stake = sum((Decimal(row.stake) for _, row in policy_rows), Decimal(0))
        gross = sum((Decimal(row.gross_return) for _, row in policy_rows), Decimal(0))
        gain = sum((Decimal(row.realized_gain) for _, row in policy_rows), Decimal(0))
        loss = sum((Decimal(row.realized_loss) for _, row in policy_rows), Decimal(0))
        summaries.append(
            PolicyCampaignScore(
                policy_ref=policy_ref,
                policy_content_hash=first.policy_content_hash,
                role=first.role,
                target_count=len(policy_rows),
                action_count=sum(row.disposition == "SETTLED" for _, row in policy_rows),
                no_action_count=sum(
                    row.disposition == "NO_ACTION_SETTLED" for _, row in policy_rows
                ),
                void_count=sum(row.disposition == "VOID" for _, row in policy_rows),
                hit_count=sum(row.hit is True for _, row in policy_rows),
                unique_selected_numbers=tuple(
                    sorted(
                        {
                            row.selected_number
                            for _, row in policy_rows
                            if row.decision_kind.value != "NO_ACTION"
                        }
                    )
                ),
                behavior_trace_hash=canonical_sha256(behavior_trace),
                total_stake=_money_text(stake),
                total_gross_return=_money_text(gross),
                total_realized_gain=_money_text(gain),
                total_realized_loss=_money_text(loss),
                net_result=_money_text(gain - loss),
            ).with_content_hash()
        )
    return tuple(summaries)


def _weekly_period_start(value: datetime) -> datetime:
    local = value.astimezone(ASIA_SHANGHAI)
    monday = local.date() - timedelta(days=local.weekday())
    boundary = datetime.combine(monday, time(hour=15), ASIA_SHANGHAI)
    return boundary if local >= boundary else boundary - timedelta(days=7)


def build_campaign_evaluation(
    *,
    pin: ContinuousCampaignPin,
    historical_records: Sequence[CampaignTargetRecord],
    settlement_sets: Sequence[SettlementSet],
) -> ContinuousCampaignEvaluation:
    """Recompute weekly ledgers, behavior clusters, claim cap, and successor question."""

    records = tuple(historical_records)
    settlements = tuple(settlement_sets)
    if not records or len(records) != len(settlements):
        raise ValueError("campaign evaluation requires one settlement set per historical target")
    period_members: dict[datetime, list[tuple[CampaignTargetRecord, SettlementSet]]] = defaultdict(
        list
    )
    all_rows: list[tuple[str, ScoreRow]] = []
    for record, settlement in zip(records, settlements, strict=True):
        if (
            record.state != "HISTORICAL_REPLAY_SETTLED"
            or settlement.target_ref != record.target_ref
            or settlement.settled_exactly_once_count != 4
            or not settlement.closed
        ):
            raise ValueError("campaign evaluation received an unsettled or mismatched target")
        period_members[_weekly_period_start(record.target_open_time)].append((record, settlement))
        all_rows.extend((record.target_ref, row) for row in settlement.score_rows)

    weekly_periods: list[CampaignWeeklyPeriod] = []
    for period_start in sorted(period_members):
        members = period_members[period_start]
        target_refs = tuple(record.target_ref for record, _ in members)
        expected_refs = tuple(sorted(target_refs, key=lambda item: int(item.rsplit("/", 1)[-1])))
        if target_refs != expected_refs or len(set(target_refs)) != len(target_refs):
            raise ValueError("weekly period target order or identity drifted")
        period_rows = [
            (record.target_ref, row)
            for record, settlement in members
            for row in settlement.score_rows
        ]
        target_count = len(members)
        period_end = period_start + timedelta(days=7)
        weekly_periods.append(
            CampaignWeeklyPeriod(
                period_ref=(
                    f"accounting-period/{period_start.strftime('%Y%m%dT%H%M%z')}"
                    f"--{period_end.strftime('%Y%m%dT%H%M%z')}"
                ),
                period_start=period_start,
                period_end=period_end,
                target_refs=target_refs,
                target_count=target_count,
                settled_ticket_count=len(period_rows),
                closure_state=("CLOSED" if target_count == 7 else "PARTIAL_VALIDATION_WINDOW"),
                policy_scores=_summarize_policy_rows(period_rows),
            ).with_content_hash()
        )

    global_scores = _summarize_policy_rows(all_rows)
    by_trace: dict[str, list[PolicyCampaignScore]] = defaultdict(list)
    for score in global_scores:
        by_trace[score.behavior_trace_hash].append(score)
    clusters: list[BehaviorEquivalenceCluster] = []
    for trace_hash, scores in sorted(by_trace.items()):
        roles = tuple(sorted({score.role for score in scores}, key=str))
        if len(scores) < 2 or len(roles) < 2:
            continue
        clusters.append(
            BehaviorEquivalenceCluster(
                cluster_ref=f"behavior-equivalence/{pin.campaign_id}/{trace_hash}",
                behavior_trace_hash=trace_hash,
                policy_refs=tuple(sorted(score.policy_ref for score in scores)),
                roles=roles,
                target_count=len(records),
            ).with_content_hash()
        )

    collapsed_pair = {_BASELINE_POLICY_REF, _SUBSTANTIVE_POLICY_REF}
    degraded = len(records) >= HOMOGENEITY_AUDIT_MIN_TARGETS and any(
        collapsed_pair.issubset(cluster.policy_refs) for cluster in clusters
    )
    portfolio_health = (
        "UNDERPOWERED_HOMOGENEITY_AUDIT"
        if len(records) < HOMOGENEITY_AUDIT_MIN_TARGETS
        else ("DEGRADED_HOMOGENEITY" if degraded else "NO_CROSS_ROLE_CO_COLLAPSE_OBSERVED")
    )
    trigger_reasons = [
        "HISTORICAL_REPLAY_CLAIM_CEILING_E2",
        "NO_PREDICTIVE_ADVANTAGE_ESTABLISHED",
    ]
    if degraded:
        trigger_reasons.append("BASELINE_SUBSTANTIVE_BEHAVIORAL_CO_COLLAPSE")
    next_question = CampaignNextQuestionSet(
        next_question_set_ref=f"next-question-set/{pin.campaign_id}/cadence-challengers-v1",
        campaign_ref=pin.campaign_ref,
        campaign_pin_sha256=str(pin.content_hash),
        trigger_reasons=tuple(trigger_reasons),
        question=(
            "Do predeclared per-target, seven-target retraining, and fixed seven-target "
            "batch policies generate behaviorally non-equivalent predictions and improve "
            "time-out performance over the frozen incumbent and null controls?"
        ),
        challenger_cadences=(
            "PER_TARGET_UPDATE",
            "RETRAIN_EVERY_7_TARGETS",
            "FIXED_7_TARGET_BATCH",
        ),
        earliest_eligible_target_ref=pin.prospective_target_ref,
    ).with_content_hash()
    return ContinuousCampaignEvaluation(
        evaluation_ref=f"continuous-campaign-evaluation/{pin.campaign_id}",
        campaign_ref=pin.campaign_ref,
        campaign_pin_sha256=str(pin.content_hash),
        historical_target_count=len(records),
        global_policy_scores=global_scores,
        weekly_periods=tuple(weekly_periods),
        complete_weekly_period_count=sum(
            period.closure_state == "CLOSED" for period in weekly_periods
        ),
        partial_weekly_period_count=sum(
            period.closure_state == "PARTIAL_VALIDATION_WINDOW" for period in weekly_periods
        ),
        behavior_equivalence_clusters=tuple(clusters),
        portfolio_health=portfolio_health,
        next_question_set=next_question,
    ).with_content_hash()


def _snapshot_payload(
    *,
    pin: ContinuousCampaignPin,
    target: SpecialNumberObservation | ProspectiveTarget,
    temporal_identity: CampaignTemporalIdentity,
    outcome_role: str,
    validation_source_ref: str,
    validation_source_sha256: str,
    skipped_missed_deadline_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "xinao.fixed_cutoff_target_information.v1",
        "campaign_ref": pin.campaign_ref,
        "campaign_pin_sha256": pin.content_hash,
        "temporal_identity": temporal_identity,
        "policy_dataset_ref": pin.policy_dataset_ref,
        "policy_dataset_sha256": pin.policy_dataset_sha256,
        "policy_information_set_hash": pin.candidate_information_set_hash,
        "candidate_information_cutoff": pin.candidate_information_cutoff.isoformat(),
        "candidate_information_latest_expect": pin.candidate_information_latest_expect,
        "post_cutoff_candidate_outcome_access": False,
        "post_cutoff_outcome_use": pin.post_cutoff_outcome_use,
        "validation_source_ref": validation_source_ref,
        "validation_source_sha256": validation_source_sha256,
        "outcome_information_role": outcome_role,
        "target_ref": (
            f"macaujc2/expect/{target.expect}"
            if isinstance(target, SpecialNumberObservation)
            else target.target_ref
        ),
        "target_open_time": target.open_time.isoformat()
        if isinstance(target, SpecialNumberObservation)
        else target.target_open_time.isoformat(),
        "skipped_missed_deadline_refs": list(skipped_missed_deadline_refs),
    }
    payload["content_hash"] = canonical_sha256(payload)
    return payload


def build_continuous_campaign_package(
    *,
    output_dir: Path,
    campaign_id: str,
    policy_observations: Sequence[SpecialNumberObservation],
    observed_source: Sequence[SpecialNumberObservation],
    policy_dataset_ref: str,
    policy_dataset_sha256: str,
    validation_source_ref: str,
    validation_source_sha256: str,
    validation_source_captured_at: datetime,
    active_parent_ref: str,
    active_parent_sha256: str,
    source_contract_ref: str,
    source_contract_sha256: str,
    pinned_at: datetime,
    allow_precreated_output: bool = False,
) -> dict[str, Any]:
    """Build and settle all known replay targets, then freeze the next legal target."""

    _require_aware(validation_source_captured_at, "validation source captured_at")
    _require_aware(pinned_at, "campaign pinned_at")
    if allow_precreated_output:
        root = output_dir.resolve()
        if not root.is_dir() or (root / CAMPAIGN_MANIFEST_NAME).exists():
            raise ValueError("precreated campaign output is missing or already sealed")
    else:
        output_dir.mkdir(parents=True, exist_ok=False)
        root = output_dir.resolve()
    fixed, validation = split_fixed_cutoff_stream(policy_observations, observed_source)
    if validation_source_captured_at < validation[-1].open_time or pinned_at < (
        validation_source_captured_at
    ):
        raise ValueError("campaign capture/pin time precedes a validation outcome")
    candidate_cutoff = fixed[-1].open_time + timedelta(seconds=1)
    prospective = select_next_legal_target(validation[-1], now=pinned_at)
    first_horizon = int(validation[0].expect) - int(fixed[-1].expect)
    seed = build_day1_policy_compilation(
        fixed,
        target_ref=f"macaujc2/expect/{validation[0].expect}",
        knowledge_cutoff=candidate_cutoff,
        horizon_draws=first_horizon,
    )
    bindings = _policy_bindings(seed)
    policy_set_hash = _model_hash(bindings)
    information_set_hash = canonical_sha256(
        {
            "policy_dataset_sha256": policy_dataset_sha256,
            "history_identity_hash": seed.history_identity_hash,
            "candidate_information_cutoff": candidate_cutoff.isoformat(),
            "post_cutoff_candidate_outcome_access": False,
        }
    )
    pin = ContinuousCampaignPin(
        campaign_id=campaign_id,
        campaign_ref=f"continuous-campaign/{campaign_id}",
        pinned_at=pinned_at,
        policy_dataset_ref=policy_dataset_ref,
        policy_dataset_sha256=policy_dataset_sha256,
        policy_observation_count=len(fixed),
        candidate_information_latest_expect=fixed[-1].expect,
        candidate_information_cutoff=candidate_cutoff,
        candidate_information_set_hash=information_set_hash,
        policy_set_hash=policy_set_hash,
        policy_bindings=bindings,
        validation_source_ref=validation_source_ref,
        validation_source_sha256=validation_source_sha256,
        validation_source_captured_at=validation_source_captured_at,
        historical_target_refs=tuple(f"macaujc2/expect/{item.expect}" for item in validation),
        prospective_target_ref=prospective.target_ref,
        prospective_target_open_time=prospective.target_open_time,
        prospective_freeze_deadline=prospective.freeze_deadline,
    ).with_content_hash()
    _write_model(root / "continuous_campaign_pin.v1.json", pin)

    target_records: list[CampaignTargetRecord] = []
    historical_settlements: list[SettlementSet] = []
    for index, outcome_observation in enumerate(validation, start=1):
        target_ref = f"macaujc2/expect/{outcome_observation.expect}"
        target_dir = root / "targets" / outcome_observation.expect
        target_dir.mkdir(parents=True)
        snapshot = _snapshot_payload(
            pin=pin,
            target=outcome_observation,
            temporal_identity=CampaignTemporalIdentity.SIMULATED_HISTORICAL_REPLAY,
            outcome_role="SETTLEMENT_ONLY",
            validation_source_ref=validation_source_ref,
            validation_source_sha256=validation_source_sha256,
        )
        snapshot_path = target_dir / "policy_information_snapshot.v1.json"
        _write_new_json(snapshot_path, snapshot)
        outcome = OutcomeObservation(
            outcome_ref=f"verified-outcome/{campaign_id}/{outcome_observation.expect}",
            source_ref=f"{validation_source_ref}#sha256={validation_source_sha256}",
            target_ref=target_ref,
            actual_special_number=outcome_observation.special_number,
            observed_at=outcome_observation.open_time + timedelta(seconds=1),
            verified=True,
        ).with_hash()
        result = build_episode_package(
            output_dir=target_dir,
            episode_id=f"{campaign_id}.historical.{outcome_observation.expect}",
            evidence_class="HISTORICAL_TIME_OUT_REPLAY",
            observations=fixed,
            source_snapshot_ref=snapshot_path.name,
            source_snapshot_sha256=sha256_file(snapshot_path),
            source_captured_at=candidate_cutoff,
            active_parent_ref=active_parent_ref,
            active_parent_sha256=active_parent_sha256,
            source_contract_ref=source_contract_ref,
            source_contract_sha256=source_contract_sha256,
            target_ref=target_ref,
            target_open_time=outcome_observation.open_time,
            knowledge_cutoff=candidate_cutoff,
            freeze_deadline=outcome_observation.open_time - timedelta(hours=1),
            horizon_draws=int(outcome_observation.expect) - int(fixed[-1].expect),
            frozen_at=outcome_observation.open_time - timedelta(hours=2),
            verified_outcome=outcome,
            policy_information_set_hash=information_set_hash,
        )
        compiled = Day1PolicyCompilation.model_validate_json(
            (target_dir / "day1_policy_compilation.v1.json").read_text(encoding="utf-8")
        )
        target_bindings = _policy_bindings(compiled)
        if target_bindings != bindings:
            raise ValueError("historical target minted target-specific policy identities")
        historical_settlements.append(
            SettlementSet.model_validate_json(
                (target_dir / "settlement_set.v1.json").read_text(encoding="utf-8")
            )
        )
        target_records.append(
            CampaignTargetRecord(
                sequence_index=index,
                target_ref=target_ref,
                target_open_time=outcome_observation.open_time,
                temporal_identity=CampaignTemporalIdentity.SIMULATED_HISTORICAL_REPLAY,
                episode_dir=target_dir.relative_to(root).as_posix(),
                episode_manifest_sha256=result["manifest_sha256"],
                policy_set_hash=policy_set_hash,
                policy_bindings=target_bindings,
                candidate_information_cutoff=candidate_cutoff,
                candidate_information_set_hash=information_set_hash,
                outcome_information_role="SETTLEMENT_ONLY",
                state="HISTORICAL_REPLAY_SETTLED",
                settled_exactly_once_count=4,
                claim_grade="E2_MAX_HISTORICAL_SIMULATED_REPLAY",
            ).with_content_hash()
        )

    prospective_expect = prospective.target_ref.rsplit("/", 1)[-1]
    prospective_dir = root / "targets" / prospective_expect
    prospective_dir.mkdir(parents=True)
    prospective_snapshot = _snapshot_payload(
        pin=pin,
        target=prospective,
        temporal_identity=CampaignTemporalIdentity.LIVE_PRE_OUTCOME,
        outcome_role="TARGET_SCHEDULING_ONLY",
        validation_source_ref=validation_source_ref,
        validation_source_sha256=validation_source_sha256,
        skipped_missed_deadline_refs=prospective.skipped_missed_deadline_refs,
    )
    prospective_snapshot_path = prospective_dir / "policy_information_snapshot.v1.json"
    _write_new_json(prospective_snapshot_path, prospective_snapshot)
    prospective_result = build_episode_package(
        output_dir=prospective_dir,
        episode_id=f"{campaign_id}.prospective.{prospective_expect}",
        evidence_class="PROSPECTIVE_EXPERIMENTAL",
        observations=fixed,
        source_snapshot_ref=prospective_snapshot_path.name,
        source_snapshot_sha256=sha256_file(prospective_snapshot_path),
        source_captured_at=candidate_cutoff,
        active_parent_ref=active_parent_ref,
        active_parent_sha256=active_parent_sha256,
        source_contract_ref=source_contract_ref,
        source_contract_sha256=source_contract_sha256,
        target_ref=prospective.target_ref,
        target_open_time=prospective.target_open_time,
        knowledge_cutoff=candidate_cutoff,
        freeze_deadline=prospective.freeze_deadline,
        horizon_draws=int(prospective_expect) - int(fixed[-1].expect),
        frozen_at=pinned_at,
        policy_information_set_hash=information_set_hash,
    )
    prospective_compiled = Day1PolicyCompilation.model_validate_json(
        (prospective_dir / "day1_policy_compilation.v1.json").read_text(encoding="utf-8")
    )
    prospective_bindings = _policy_bindings(prospective_compiled)
    if prospective_bindings != bindings:
        raise ValueError("prospective target minted target-specific policy identities")
    target_records.append(
        CampaignTargetRecord(
            sequence_index=len(target_records) + 1,
            target_ref=prospective.target_ref,
            target_open_time=prospective.target_open_time,
            temporal_identity=CampaignTemporalIdentity.LIVE_PRE_OUTCOME,
            episode_dir=prospective_dir.relative_to(root).as_posix(),
            episode_manifest_sha256=prospective_result["manifest_sha256"],
            policy_set_hash=policy_set_hash,
            policy_bindings=prospective_bindings,
            candidate_information_cutoff=candidate_cutoff,
            candidate_information_set_hash=information_set_hash,
            outcome_information_role="TARGET_SCHEDULING_ONLY",
            state="FROZEN_AWAITING_VERIFIED_OUTCOME",
            settled_exactly_once_count=0,
            claim_grade="E2_CEILING_AWAITING_PROSPECTIVE_OUTCOME",
        ).with_content_hash()
    )
    evaluation = build_campaign_evaluation(
        pin=pin,
        historical_records=tuple(target_records[:-1]),
        settlement_sets=tuple(historical_settlements),
    )
    _write_model(root / "continuous_campaign_evaluation.v1.json", evaluation)
    ledger = ContinuousCampaignLedger(
        campaign_ref=pin.campaign_ref,
        campaign_pin_sha256=str(pin.content_hash),
        evaluation_sha256=str(evaluation.content_hash),
        targets=tuple(target_records),
        historical_settled_target_count=len(validation),
        historical_settled_ticket_count=len(validation) * 4,
        skipped_missed_deadline_refs=prospective.skipped_missed_deadline_refs,
    ).with_content_hash()
    _write_model(root / "continuous_campaign_ledger.v1.json", ledger)
    receipt = {
        "schema_version": "xinao.continuous_campaign_consumer_receipt.v1",
        "state": "HISTORICAL_REPLAY_SETTLED_AND_PROSPECTIVE_FROZEN",
        "campaign_ref": pin.campaign_ref,
        "campaign_pin_sha256": pin.content_hash,
        "ledger_sha256": ledger.content_hash,
        "evaluation_sha256": evaluation.content_hash,
        "evaluation_conclusion": evaluation.evaluation_conclusion,
        "portfolio_health": evaluation.portfolio_health,
        "complete_weekly_period_count": evaluation.complete_weekly_period_count,
        "partial_weekly_period_count": evaluation.partial_weekly_period_count,
        "next_question_set_ref": evaluation.next_question_set.next_question_set_ref,
        "next_question_set_sha256": evaluation.next_question_set.content_hash,
        "candidate_information_latest_expect": pin.candidate_information_latest_expect,
        "candidate_information_set_hash": pin.candidate_information_set_hash,
        "post_cutoff_candidate_observation_count": 0,
        "historical_settled_target_count": ledger.historical_settled_target_count,
        "historical_settled_ticket_count": ledger.historical_settled_ticket_count,
        "prospective_pending_target_count": 1,
        "prospective_target_ref": prospective.target_ref,
        "waiting_scope": "TARGET_ONLY",
        "parent_idle": False,
        "real_money_authorized": False,
        "parent_complete": False,
    }
    receipt["content_hash"] = canonical_sha256(receipt)
    _write_new_json(root / "continuous_campaign_consumer_receipt.v1.json", receipt)
    manifest = _campaign_manifest(root)
    _write_new_json(root / CAMPAIGN_MANIFEST_NAME, manifest)
    return {
        "ok": True,
        "package_dir": str(root),
        "state": receipt["state"],
        "manifest_sha256": sha256_file(root / CAMPAIGN_MANIFEST_NAME),
        "campaign_pin_sha256": pin.content_hash,
        "ledger_sha256": ledger.content_hash,
        "evaluation_sha256": evaluation.content_hash,
        "portfolio_health": evaluation.portfolio_health,
        "historical_settled_target_count": len(validation),
        "prospective_target_ref": prospective.target_ref,
        "parent_complete": False,
    }


def verify_continuous_campaign_package(
    package_dir: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Fresh readback of campaign identity, child packages, and wait scope."""

    root = package_dir.resolve()
    manifest_path = root / CAMPAIGN_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = sha256_file(manifest_path)
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ValueError("continuous campaign manifest differs from its external pin")
    if manifest != _campaign_manifest(root):
        raise ValueError("continuous campaign manifest inventory drifted")
    pin = ContinuousCampaignPin.model_validate_json(
        (root / "continuous_campaign_pin.v1.json").read_text(encoding="utf-8")
    )
    ledger = ContinuousCampaignLedger.model_validate_json(
        (root / "continuous_campaign_ledger.v1.json").read_text(encoding="utf-8")
    )
    evaluation = ContinuousCampaignEvaluation.model_validate_json(
        (root / "continuous_campaign_evaluation.v1.json").read_text(encoding="utf-8")
    )
    if pin.content_hash is None or ledger.content_hash is None or evaluation.content_hash is None:
        raise ValueError("continuous campaign contains an unsealed root object")
    if (
        ledger.campaign_ref != pin.campaign_ref
        or ledger.campaign_pin_sha256 != pin.content_hash
        or ledger.evaluation_sha256 != evaluation.content_hash
    ):
        raise ValueError("continuous campaign ledger differs from its pin")
    historical_refs: list[str] = []
    historical_records: list[CampaignTargetRecord] = []
    historical_settlements: list[SettlementSet] = []
    historical_tickets = 0
    for record in ledger.targets:
        target_dir = (root / record.episode_dir).resolve()
        try:
            target_dir.relative_to(root)
        except ValueError as exc:
            raise ValueError("campaign target directory escapes package root") from exc
        child = verify_episode_package(
            target_dir,
            expected_manifest_sha256=record.episode_manifest_sha256,
        )
        compiled = Day1PolicyCompilation.model_validate_json(
            (target_dir / "day1_policy_compilation.v1.json").read_text(encoding="utf-8")
        )
        child_bindings = _policy_bindings(compiled)
        if (
            child_bindings != pin.policy_bindings
            or record.policy_bindings != pin.policy_bindings
            or record.policy_set_hash != pin.policy_set_hash
            or compiled.knowledge_cutoff != pin.candidate_information_cutoff
            or any(
                policy.knowledge_cutoff != pin.candidate_information_cutoff
                for policy in compiled.policies
            )
        ):
            raise ValueError("campaign child policy identity or cutoff drifted")
        freeze_set_payload = json.loads(
            (target_dir / "frozen_decision_set.v1.json").read_text(encoding="utf-8")
        )
        tickets = freeze_set_payload.get("tickets", [])
        if len(tickets) != 4 or any(
            item.get("frozen_decision", {}).get("information_set_hash")
            != pin.candidate_information_set_hash
            for item in tickets
        ):
            raise ValueError("campaign child ticket information set drifted")
        if child["state"] != record.state or child["eligible_frozen_count"] != 4:
            raise ValueError("campaign child readback differs from ledger state")
        if record.state == "HISTORICAL_REPLAY_SETTLED":
            historical_refs.append(record.target_ref)
            historical_records.append(record)
            historical_settlements.append(
                SettlementSet.model_validate_json(
                    (target_dir / "settlement_set.v1.json").read_text(encoding="utf-8")
                )
            )
            historical_tickets += record.settled_exactly_once_count
        elif record.target_ref != pin.prospective_target_ref:
            raise ValueError("campaign pending target differs from its prospective pin")
    if tuple(historical_refs) != pin.historical_target_refs:
        raise ValueError("campaign historical target coverage differs from its pin")
    expected_evaluation = build_campaign_evaluation(
        pin=pin,
        historical_records=tuple(historical_records),
        settlement_sets=tuple(historical_settlements),
    )
    if evaluation != expected_evaluation:
        raise ValueError("continuous campaign evaluation differs from fresh recomputation")
    receipt = json.loads(
        (root / "continuous_campaign_consumer_receipt.v1.json").read_text(encoding="utf-8")
    )
    receipt_hash = receipt.pop("content_hash", None)
    if receipt_hash != canonical_sha256(receipt):
        raise ValueError("continuous campaign consumer receipt hash differs")
    expected_receipt = {
        "state": "HISTORICAL_REPLAY_SETTLED_AND_PROSPECTIVE_FROZEN",
        "campaign_ref": pin.campaign_ref,
        "campaign_pin_sha256": pin.content_hash,
        "ledger_sha256": ledger.content_hash,
        "evaluation_sha256": evaluation.content_hash,
        "evaluation_conclusion": evaluation.evaluation_conclusion,
        "portfolio_health": evaluation.portfolio_health,
        "complete_weekly_period_count": evaluation.complete_weekly_period_count,
        "partial_weekly_period_count": evaluation.partial_weekly_period_count,
        "next_question_set_ref": evaluation.next_question_set.next_question_set_ref,
        "next_question_set_sha256": evaluation.next_question_set.content_hash,
        "candidate_information_latest_expect": pin.candidate_information_latest_expect,
        "candidate_information_set_hash": pin.candidate_information_set_hash,
        "post_cutoff_candidate_observation_count": 0,
        "historical_settled_target_count": ledger.historical_settled_target_count,
        "historical_settled_ticket_count": ledger.historical_settled_ticket_count,
        "prospective_pending_target_count": 1,
        "prospective_target_ref": pin.prospective_target_ref,
        "waiting_scope": "TARGET_ONLY",
        "parent_idle": False,
        "real_money_authorized": False,
        "parent_complete": False,
    }
    if any(receipt.get(key) != value for key, value in expected_receipt.items()):
        raise ValueError("continuous campaign consumer receipt differs from sealed objects")
    return {
        "ok": True,
        "schema_version": "xinao.continuous_campaign_readback.v1",
        "manifest_sha256": manifest_sha256,
        "external_manifest_pin_matched": expected_manifest_sha256 is not None,
        "state": expected_receipt["state"],
        "cadence": pin.cadence,
        "candidate_information_latest_expect": pin.candidate_information_latest_expect,
        "candidate_information_set_hash": pin.candidate_information_set_hash,
        "historical_settled_target_count": len(historical_refs),
        "historical_settled_ticket_count": historical_tickets,
        "prospective_pending_target_count": 1,
        "prospective_target_ref": pin.prospective_target_ref,
        "post_cutoff_candidate_observation_count": 0,
        "historical_claim_ceiling": pin.historical_claim_ceiling,
        "evaluation_sha256": evaluation.content_hash,
        "evaluation_conclusion": evaluation.evaluation_conclusion,
        "portfolio_health": evaluation.portfolio_health,
        "complete_weekly_period_count": evaluation.complete_weekly_period_count,
        "partial_weekly_period_count": evaluation.partial_weekly_period_count,
        "next_question_set_ref": evaluation.next_question_set.next_question_set_ref,
        "waiting_scope": ledger.waiting_scope,
        "parent_idle": ledger.parent_idle,
        "real_money_authorized": ledger.real_money_authorized,
        "parent_complete": ledger.parent_complete,
    }


def _verify_input(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ValueError(f"{label} SHA-256 differs from its frozen binding")


def run_fixed_cutoff_continuous_campaign(
    *,
    output_dir: Path,
    campaign_id: str,
    dataset_path: Path,
    dataset_sha256: str,
    active_parent_path: Path,
    active_parent_sha256: str,
    source_contract_path: Path,
    source_contract_sha256: str,
) -> dict[str, Any]:
    """Capture the result stream, replay its fixed-cutoff window, and freeze next target."""

    _verify_input(dataset_path, dataset_sha256, "formal dataset")
    _verify_input(active_parent_path, active_parent_sha256, "active parent")
    _verify_input(source_contract_path, source_contract_sha256, "source contract")
    output_dir.mkdir(parents=True, exist_ok=False)
    root = output_dir.resolve()
    raw, captured_at, raw_path = _fetch_live_source(root)
    observed_source = parse_macaujc_history_response(
        raw,
        knowledge_cutoff=captured_at + timedelta(milliseconds=1),
    )
    fixed = observations_from_draws(load_draws(dataset_path))
    if (
        fixed[-1].expect != "2026182"
        or fixed[-1].open_time.isoformat() != "2026-07-01T21:32:32+08:00"
    ):
        raise ValueError("formal policy-information boundary is not 2026-07-01/2026182")
    return build_continuous_campaign_package(
        output_dir=root,
        campaign_id=campaign_id,
        policy_observations=fixed,
        observed_source=observed_source,
        policy_dataset_ref=str(dataset_path.resolve()),
        policy_dataset_sha256=dataset_sha256,
        validation_source_ref=str(raw_path.resolve()),
        validation_source_sha256=sha256_file(raw_path),
        validation_source_captured_at=captured_at,
        active_parent_ref=str(active_parent_path.resolve()),
        active_parent_sha256=active_parent_sha256,
        source_contract_ref=SOURCE_CONTRACT_REF,
        source_contract_sha256=source_contract_sha256,
        pinned_at=_millisecond_now(),
        allow_precreated_output=True,
    )


__all__ = [
    "CAMPAIGN_MANIFEST_NAME",
    "HOMOGENEITY_AUDIT_MIN_TARGETS",
    "WEEKLY_CLOSE_POLICY_REF",
    "BehaviorEquivalenceCluster",
    "CampaignCadence",
    "CampaignNextQuestionSet",
    "CampaignTargetRecord",
    "CampaignTemporalIdentity",
    "CampaignWeeklyPeriod",
    "ContinuousCampaignEvaluation",
    "ContinuousCampaignLedger",
    "ContinuousCampaignPin",
    "PolicyCampaignScore",
    "ProspectiveTarget",
    "build_campaign_evaluation",
    "build_continuous_campaign_package",
    "run_fixed_cutoff_continuous_campaign",
    "select_next_legal_target",
    "split_fixed_cutoff_stream",
    "verify_continuous_campaign_package",
]
