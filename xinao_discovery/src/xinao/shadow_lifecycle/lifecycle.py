"""Minimal leg-A shadow lifecycle: dual-branch freeze, settle, statement, replay.

Separates scientific decisions from account decisions. Does not claim real-world
shadow-practice milestones from synthetic fixtures alone.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import ACCOUNTING_DECIMAL, canonical_sha256, format_decimal
from xinao.decision import DecisionKind, FrozenDecision
from xinao.ledger.accounting import (
    Account,
    JournalGroup,
    frozen_position_group,
    opening_group,
    replay_balances,
)
from xinao.settlement.shadow import (
    OutcomeAdmission,
    OutcomeObservation,
    SettlementBundle,
    SettlementRecord,
    admit_outcome,
    admit_settlement,
    settle_frozen_decision,
)
from xinao.settlement.special_number import SPECIAL_NUMBER_RULE

DEFAULT_OPENING_BALANCE = "10000.0000"
ZERO_AMOUNT = "0.0000"
# Mechanical settlement in this vertical only implements special-number-rule.v1.
MECHANICAL_SETTLEMENT_RULE_REF = SPECIAL_NUMBER_RULE.rule_ref

_ACTION_DECISION_KINDS = frozenset(
    {
        DecisionKind.FROZEN_EXPERIMENTAL_SHADOW,
        DecisionKind.FROZEN_ELIGIBLE_ACTION,
    }
)


class ScienceDecisionIdentity(StrEnum):
    SCIENCE_CANDIDATE = "SCIENCE_CANDIDATE"
    POLICY_NO_ACTION = "POLICY_NO_ACTION"


class AccountDecisionIdentity(StrEnum):
    ACTION = "ACTION"
    RESEARCHER_ACCOUNT_NO_ACTION = "RESEARCHER_ACCOUNT_NO_ACTION"


class EvidenceState(StrEnum):
    """Honest lifecycle evidence labels. Fixtures must not auto-promote milestones."""

    IMPLEMENTATION_READY = "IMPLEMENTATION_READY"
    UNIT_FIXTURE_ONLY = "UNIT_FIXTURE_ONLY"
    READY_FOR_SHADOW_PRACTICE = "READY_FOR_SHADOW_PRACTICE"
    SHADOW_PRACTICE_STARTED = "SHADOW_PRACTICE_STARTED"
    FIRST_EPISODE_VERIFIED = "FIRST_EPISODE_VERIFIED"
    WALK_FORWARD_REPLAY = "WALK_FORWARD_REPLAY"


class AnomalyStatus(StrEnum):
    NONE = "NONE"
    HASH_MISMATCH = "HASH_MISMATCH"
    SEAT_MISMATCH = "SEAT_MISMATCH"
    PORTFOLIO_MISMATCH = "PORTFOLIO_MISMATCH"
    TARGET_MISMATCH = "TARGET_MISMATCH"
    TEMPORAL_VIOLATION = "TEMPORAL_VIOLATION"
    DOUBLE_SETTLEMENT = "DOUBLE_SETTLEMENT"
    HALF_TRANSACTION = "HALF_TRANSACTION"
    MUTATED_SEAL = "MUTATED_SEAL"
    MISSING_OUTCOME = "MISSING_OUTCOME"


class StatementResultKind(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    NO_EXPOSURE = "NO_EXPOSURE"


def _require_aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _amount(value: str) -> Decimal:
    return Decimal(format_decimal(value, ACCOUNTING_DECIMAL))


def _fmt_amount(value: Decimal | str) -> str:
    return format_decimal(value, ACCOUNTING_DECIMAL)


def _cash_balance(balances: dict[str, str]) -> str:
    return balances[Account.SHADOW_CASH.value]


def _require_content_seal(obj: object, *, label: str) -> None:
    """Reject missing or stale content hashes (model_copy can retain an old seal)."""

    sealed = getattr(obj, "content_hash", None)
    if sealed is None:
        raise ValueError(f"{label} must be hash sealed")
    compute = getattr(obj, "compute_content_hash", None)
    if compute is None:
        raise ValueError(f"{label} cannot recompute content seal")
    if compute() != sealed:
        raise ValueError(f"mutated sealed {label} rejected")


def _require_outcome_seal(outcome: OutcomeObservation) -> None:
    outcome.require_valid_result_hash()


def _require_mechanical_rule_ref(rule_ref: str, *, boundary: str) -> None:
    if rule_ref != MECHANICAL_SETTLEMENT_RULE_REF:
        raise ValueError(
            f"{boundary} rejects unsupported rule_ref={rule_ref!r}; "
            f"mechanical settlement only implements {MECHANICAL_SETTLEMENT_RULE_REF}"
        )


def _expected_opening_journal(
    *,
    group_ref: str,
    portfolio_ref: str,
    frozen_at: datetime,
    pre_freeze_balance: str,
) -> JournalGroup:
    return opening_group(
        group_ref=group_ref,
        portfolio_ref=portfolio_ref,
        occurred_at=frozen_at,
        amount=pre_freeze_balance,
    )


def _expected_position_journal(
    *,
    group_ref: str,
    portfolio_ref: str,
    decision_ref: str,
    frozen_at: datetime,
    stake: str,
) -> JournalGroup:
    return frozen_position_group(
        group_ref=group_ref,
        portfolio_ref=portfolio_ref,
        decision_ref=decision_ref,
        occurred_at=frozen_at,
        stake=stake,
    )


class ShadowSeat(BaseModel):
    """Researcher seat with an isolated shadow portfolio and opening capital."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seat_id: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    opening_balance: str = DEFAULT_OPENING_BALANCE
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_seat(self) -> Self:
        if self.seat_id == self.portfolio_ref:
            raise ValueError("seat_id and portfolio_ref must be distinct")
        if self.opening_balance != _fmt_amount(self.opening_balance):
            raise ValueError("opening_balance must use accounting scale")
        if _amount(self.opening_balance) <= 0:
            raise ValueError("opening_balance must be positive")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical seat")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ShadowSeat:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class ScienceBranchDecision(BaseModel):
    """Scientific branch only: candidate or policy no-action. Not an account ticket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    science_decision_ref: str = Field(min_length=1)
    identity: ScienceDecisionIdentity
    candidate_ref: str | None = None
    knowledge_cutoff: datetime
    rationale_ref: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_science(self) -> Self:
        _require_aware(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if self.identity == ScienceDecisionIdentity.SCIENCE_CANDIDATE:
            if not self.candidate_ref:
                raise ValueError("SCIENCE_CANDIDATE requires candidate_ref")
        elif self.candidate_ref is not None:
            raise ValueError("POLICY_NO_ACTION must not carry a candidate_ref")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical science decision")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ScienceBranchDecision:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class AccountBranchDecision(BaseModel):
    """Account branch only: ACTION risk ticket or explicit zero-risk no-action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_decision_ref: str = Field(min_length=1)
    identity: AccountDecisionIdentity
    frozen_decision_ref: str | None = None
    frozen_decision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    stake: str
    rule_ref: str = Field(min_length=1)
    odds_version_ref: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_account(self) -> Self:
        stake = _amount(self.stake)
        if self.stake != _fmt_amount(stake):
            raise ValueError("stake must use accounting scale")
        if self.identity == AccountDecisionIdentity.ACTION:
            if stake <= 0:
                raise ValueError("ACTION requires positive stake")
            if not self.frozen_decision_ref or not self.frozen_decision_hash:
                raise ValueError("ACTION must bind a sealed FrozenDecision identity")
        else:
            if stake != 0:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must be zero-risk")
            if self.frozen_decision_ref is not None or self.frozen_decision_hash is not None:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must not bind a FrozenDecision")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical account decision")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> AccountBranchDecision:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class FrozenShadowEpisode(BaseModel):
    """Pre-outcome freeze binding seat, dual branch decisions, balances, and rule ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_ref: str = Field(min_length=1)
    seat_id: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    target_open_time: datetime
    freeze_deadline: datetime
    frozen_at: datetime
    science_decision: ScienceBranchDecision
    account_decision: AccountBranchDecision
    opening_balance: str
    pre_freeze_balance: str
    rule_ref: str = Field(min_length=1)
    odds_version_ref: str = Field(min_length=1)
    bound_frozen_decision: FrozenDecision | None = None
    opening_journal_group: JournalGroup | None = None
    position_journal_group: JournalGroup | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_episode(self) -> Self:
        for name, value in (
            ("target_open_time", self.target_open_time),
            ("freeze_deadline", self.freeze_deadline),
            ("frozen_at", self.frozen_at),
        ):
            _require_aware(value, field_name=name)
        if self.seat_id == self.portfolio_ref:
            raise ValueError("seat_id and portfolio_ref must be distinct")
        if not (self.frozen_at <= self.freeze_deadline < self.target_open_time):
            raise ValueError("frozen_at <= freeze_deadline < target_open_time is required")
        if self.science_decision.content_hash is None:
            raise ValueError("science decision must be hash sealed")
        if self.science_decision.compute_content_hash() != self.science_decision.content_hash:
            raise ValueError("mutated sealed science decision rejected")
        if self.account_decision.content_hash is None:
            raise ValueError("account decision must be hash sealed")
        if self.account_decision.compute_content_hash() != self.account_decision.content_hash:
            raise ValueError("mutated sealed account decision rejected")
        if self.account_decision.rule_ref != self.rule_ref:
            raise ValueError("account decision rule_ref must match episode rule_ref")
        if self.account_decision.odds_version_ref != self.odds_version_ref:
            raise ValueError("account decision odds_version_ref must match episode")
        if self.opening_balance != _fmt_amount(self.opening_balance):
            raise ValueError("opening_balance must use accounting scale")
        if self.pre_freeze_balance != _fmt_amount(self.pre_freeze_balance):
            raise ValueError("pre_freeze_balance must use accounting scale")

        if self.account_decision.identity == AccountDecisionIdentity.ACTION:
            if self.bound_frozen_decision is None:
                raise ValueError("ACTION episode requires bound_frozen_decision")
            frozen = self.bound_frozen_decision
            if frozen.content_hash is None:
                raise ValueError("bound FrozenDecision must be hash sealed")
            if frozen.compute_content_hash() != frozen.content_hash:
                raise ValueError("mutated sealed bound FrozenDecision rejected")
            if frozen.decision_ref != self.account_decision.frozen_decision_ref:
                raise ValueError("account decision frozen_decision_ref mismatch")
            if frozen.content_hash != self.account_decision.frozen_decision_hash:
                raise ValueError("account decision frozen_decision_hash mismatch")
            if frozen.decision_kind not in _ACTION_DECISION_KINDS:
                raise ValueError("ACTION requires an exact frozen shadow decision kind")
            if frozen.target_ref != self.target_ref:
                raise ValueError("bound FrozenDecision target_ref mismatch")
            if frozen.rule_ref != self.rule_ref:
                raise ValueError("bound FrozenDecision rule_ref mismatch")
            if frozen.odds_version_ref != self.odds_version_ref:
                raise ValueError("bound FrozenDecision odds_version_ref mismatch")
            if frozen.stake != self.account_decision.stake:
                raise ValueError("account stake must equal bound FrozenDecision stake")
            if frozen.frozen_at > self.frozen_at:
                raise ValueError(
                    "bound FrozenDecision frozen_at must not be after episode frozen_at"
                )
            _require_mechanical_rule_ref(self.rule_ref, boundary="ACTION episode")
            _require_mechanical_rule_ref(frozen.rule_ref, boundary="bound FrozenDecision")
            if self.opening_balance != self.pre_freeze_balance:
                raise ValueError(
                    "first-period pre_freeze_balance must equal sealed seat opening_balance; "
                    "multi-period carry-forward from prior sealed closing is out of scope"
                )
            if (
                self.science_decision.identity == ScienceDecisionIdentity.SCIENCE_CANDIDATE
                and self.science_decision.candidate_ref not in frozen.candidate_refs
            ):
                raise ValueError(
                    "SCIENCE_CANDIDATE candidate_ref must exist in bound "
                    "FrozenDecision.candidate_refs"
                )
            if self.opening_journal_group is None or self.position_journal_group is None:
                raise ValueError("ACTION requires opening and frozen-position journal groups")
            expected_opening = _expected_opening_journal(
                group_ref=self.opening_journal_group.group_ref,
                portfolio_ref=self.portfolio_ref,
                frozen_at=self.frozen_at,
                pre_freeze_balance=self.pre_freeze_balance,
            )
            if self.opening_journal_group != expected_opening:
                raise ValueError(
                    "opening_journal_group must equal reconstructed opening_group "
                    "(frozen_at, pre_freeze_balance, group_ref, portfolio)"
                )
            expected_position = _expected_position_journal(
                group_ref=self.position_journal_group.group_ref,
                portfolio_ref=self.portfolio_ref,
                decision_ref=frozen.decision_ref,
                frozen_at=self.frozen_at,
                stake=self.account_decision.stake,
            )
            if self.position_journal_group != expected_position:
                raise ValueError(
                    "position_journal_group must equal reconstructed frozen_position_group "
                    "(frozen_at, decision_ref, stake, group_ref, portfolio)"
                )
        else:
            if self.bound_frozen_decision is not None:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must not bind FrozenDecision")
            if self.opening_journal_group is not None or self.position_journal_group is not None:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must create no position journals")

        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical frozen episode")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> FrozenShadowEpisode:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})

    def is_account_pre_outcome_freeze(self) -> bool:
        """True when an account-side ticket was frozen before outcome."""

        return self.account_decision.identity in {
            AccountDecisionIdentity.ACTION,
            AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION,
        }


class AccountStatement(BaseModel):
    """Immutable human-readable account statement for one closed episode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_ref: str = Field(min_length=1)
    episode_ref: str = Field(min_length=1)
    seat_id: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    outcome_ref: str = Field(min_length=1)
    actual_special_number: int = Field(ge=1, le=49)
    observed_at: datetime
    opening_balance: str
    account_decision: AccountDecisionIdentity
    risk_stake: str
    rule_ref: str
    odds_version_ref: str
    # Trade semantics from settlement result on ACTION; explicit nulls on NO_EXPOSURE.
    selected_number: int | None = Field(default=None, ge=1, le=49)
    panel: Literal["A", "B"] | None = None
    baseline_ref: str | None = None
    odds: str | None = None
    result: StatementResultKind
    pnl: str
    closing_balance: str
    anomaly_status: AnomalyStatus = AnomalyStatus.NONE
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_statement(self) -> Self:
        _require_aware(self.observed_at, field_name="observed_at")
        for field in (
            "opening_balance",
            "risk_stake",
            "pnl",
            "closing_balance",
        ):
            value = getattr(self, field)
            if value != _fmt_amount(value):
                raise ValueError(f"{field} must use accounting scale")
        trade_fields = (self.selected_number, self.panel, self.baseline_ref, self.odds)
        if self.account_decision == AccountDecisionIdentity.ACTION:
            if self.result == StatementResultKind.NO_EXPOSURE:
                raise ValueError("ACTION statement cannot be NO_EXPOSURE")
            if any(value is None for value in trade_fields):
                raise ValueError(
                    "ACTION statement requires selected_number, panel, baseline_ref, and odds "
                    "from settlement result"
                )
            if not self.baseline_ref or not self.odds:
                raise ValueError("ACTION statement baseline_ref and odds must be non-empty")
        else:
            if self.result != StatementResultKind.NO_EXPOSURE:
                raise ValueError("account no-action statement must be NO_EXPOSURE")
            if any(value is not None for value in trade_fields):
                raise ValueError(
                    "NO_EXPOSURE statement must use nullable trade fields; forged odds rejected"
                )
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical statement")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> AccountStatement:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class SettledShadowEpisode(BaseModel):
    """Mechanical settlement of a frozen episode plus statement (caller-supplied priors)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_ref: str = Field(min_length=1)
    frozen_episode_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seat_id: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    outcome: OutcomeObservation
    settlement_bundle: SettlementBundle | None = None
    journal_groups: tuple[JournalGroup, ...] = ()
    statement: AccountStatement
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_settled(self) -> Self:
        self.outcome.require_valid_result_hash()
        if not self.outcome.verified:
            raise ValueError("settled episode requires verified outcome")
        if self.statement.episode_ref != self.episode_ref:
            raise ValueError("statement episode_ref mismatch")
        if (
            self.statement.seat_id != self.seat_id
            or self.statement.portfolio_ref != self.portfolio_ref
        ):
            raise ValueError("statement seat/portfolio mismatch")
        if self.statement.target_ref != self.outcome.target_ref:
            raise ValueError("statement target_ref mismatch")
        if self.statement.outcome_ref != self.outcome.outcome_ref:
            raise ValueError("statement outcome_ref mismatch")
        if self.statement.actual_special_number != self.outcome.actual_special_number:
            raise ValueError("statement actual_special_number mismatch")
        if self.statement.observed_at != self.outcome.observed_at:
            raise ValueError("statement observed_at mismatch")
        if self.statement.content_hash is None:
            raise ValueError("statement must be hash sealed")
        if self.statement.compute_content_hash() != self.statement.content_hash:
            raise ValueError("mutated sealed statement rejected")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical settled episode")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> SettledShadowEpisode:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class EvidenceAssessment(BaseModel):
    """Honest evidence labeling. Fixtures/library cannot construct real FIRST milestone."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: EvidenceState
    prospective_freeze_attested: bool = False
    independent_outcome_attested: bool = False
    first_episode_verified: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def validate_honesty(self) -> Self:
        # This PR has no trusted external attestation carrier: keep the milestone noun,
        # but refuse any library-side construction of a real FIRST_EPISODE_VERIFIED claim.
        if self.first_episode_verified or self.state == EvidenceState.FIRST_EPISODE_VERIFIED:
            raise ValueError(
                "FIRST_EPISODE_VERIFIED cannot be constructed by library booleans; "
                "no trusted external attestation carrier on this surface"
            )
        if (
            self.state == EvidenceState.SHADOW_PRACTICE_STARTED
            and not self.prospective_freeze_attested
        ):
            raise ValueError(
                "SHADOW_PRACTICE_STARTED requires prospective account freeze attestation"
            )
        return self


def create_seat(
    *,
    seat_id: str,
    portfolio_ref: str,
    opening_balance: str = DEFAULT_OPENING_BALANCE,
) -> ShadowSeat:
    return ShadowSeat(
        seat_id=seat_id,
        portfolio_ref=portfolio_ref,
        opening_balance=_fmt_amount(opening_balance),
    ).with_content_hash()


def build_science_decision(
    *,
    science_decision_ref: str,
    identity: ScienceDecisionIdentity,
    knowledge_cutoff: datetime,
    rationale_ref: str,
    candidate_ref: str | None = None,
) -> ScienceBranchDecision:
    return ScienceBranchDecision(
        science_decision_ref=science_decision_ref,
        identity=identity,
        candidate_ref=candidate_ref,
        knowledge_cutoff=knowledge_cutoff,
        rationale_ref=rationale_ref,
    ).with_content_hash()


def build_account_action(
    *,
    account_decision_ref: str,
    frozen_decision: FrozenDecision,
) -> AccountBranchDecision:
    _require_content_seal(frozen_decision, label="FrozenDecision")
    if frozen_decision.decision_kind not in _ACTION_DECISION_KINDS:
        raise ValueError("ACTION requires an exact frozen shadow decision kind")
    _require_mechanical_rule_ref(frozen_decision.rule_ref, boundary="ACTION build")
    stake = _amount(frozen_decision.stake)
    if stake <= 0:
        raise ValueError("ACTION requires positive stake on FrozenDecision")
    return AccountBranchDecision(
        account_decision_ref=account_decision_ref,
        identity=AccountDecisionIdentity.ACTION,
        frozen_decision_ref=frozen_decision.decision_ref,
        frozen_decision_hash=frozen_decision.content_hash,
        stake=_fmt_amount(stake),
        rule_ref=frozen_decision.rule_ref,
        odds_version_ref=frozen_decision.odds_version_ref,
    ).with_content_hash()


def build_account_no_action(
    *,
    account_decision_ref: str,
    rule_ref: str,
    odds_version_ref: str,
) -> AccountBranchDecision:
    return AccountBranchDecision(
        account_decision_ref=account_decision_ref,
        identity=AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION,
        frozen_decision_ref=None,
        frozen_decision_hash=None,
        stake=ZERO_AMOUNT,
        rule_ref=rule_ref,
        odds_version_ref=odds_version_ref,
    ).with_content_hash()


def freeze_shadow_episode(
    *,
    episode_ref: str,
    seat: ShadowSeat,
    science_decision: ScienceBranchDecision,
    account_decision: AccountBranchDecision,
    target_ref: str,
    target_open_time: datetime,
    freeze_deadline: datetime,
    frozen_at: datetime,
    pre_freeze_balance: str | None = None,
    bound_frozen_decision: FrozenDecision | None = None,
    opening_journal_group_ref: str | None = None,
    position_journal_group_ref: str | None = None,
    outcome_present: bool = False,
) -> FrozenShadowEpisode:
    """Freeze an episode only while the outcome is absent and time bounds hold.

    First period only: pre_freeze_balance must equal the sealed seat opening_balance.
    Multi-period carry from a prior sealed closing is out of scope for this surface.
    """

    _require_content_seal(seat, label="seat")
    _require_content_seal(science_decision, label="science decision")
    _require_content_seal(account_decision, label="account decision")
    if outcome_present:
        raise ValueError("cannot freeze after outcome is present")
    _require_aware(target_open_time, field_name="target_open_time")
    _require_aware(freeze_deadline, field_name="freeze_deadline")
    _require_aware(frozen_at, field_name="frozen_at")
    if not (frozen_at <= freeze_deadline < target_open_time):
        raise ValueError(
            "late or backdated freeze rejected: "
            "require frozen_at <= freeze_deadline < target_open_time"
        )
    if science_decision.knowledge_cutoff >= target_open_time:
        raise ValueError("science knowledge_cutoff must be before target_open_time")
    if science_decision.knowledge_cutoff > frozen_at:
        raise ValueError(
            "science knowledge_cutoff must be at or before frozen_at "
            "(future knowledge cannot enter an earlier freeze)"
        )

    # Single-seat first period: reject bare "续期余额" inflation away from seat opening.
    seat_opening = _fmt_amount(seat.opening_balance)
    if pre_freeze_balance is not None:
        balance = _fmt_amount(pre_freeze_balance)
        if balance != seat_opening:
            raise ValueError(
                "pre_freeze_balance must equal sealed seat opening_balance "
                f"({seat_opening}); bare roll-forward / inflated balances rejected "
                "(multi-period prior sealed closing is out of scope for this PR)"
            )
    else:
        balance = seat_opening
    if _amount(balance) < 0:
        raise ValueError("pre_freeze_balance must be non-negative")

    opening_journal: JournalGroup | None = None
    position_journal: JournalGroup | None = None

    if account_decision.identity == AccountDecisionIdentity.ACTION:
        if bound_frozen_decision is None:
            raise ValueError("ACTION freeze requires bound_frozen_decision")
        _require_content_seal(bound_frozen_decision, label="bound FrozenDecision")
        _require_mechanical_rule_ref(account_decision.rule_ref, boundary="ACTION freeze")
        _require_mechanical_rule_ref(bound_frozen_decision.rule_ref, boundary="ACTION freeze")
        if bound_frozen_decision.decision_ref != account_decision.frozen_decision_ref:
            raise ValueError("bound FrozenDecision ref mismatch")
        if bound_frozen_decision.content_hash != account_decision.frozen_decision_hash:
            raise ValueError("bound FrozenDecision hash mismatch")
        if bound_frozen_decision.target_ref != target_ref:
            raise ValueError("bound FrozenDecision target mismatch")
        if bound_frozen_decision.target_open_time != target_open_time:
            raise ValueError("bound FrozenDecision target_open_time mismatch")
        if bound_frozen_decision.freeze_deadline != freeze_deadline:
            raise ValueError("bound FrozenDecision freeze_deadline mismatch")
        if bound_frozen_decision.stake != account_decision.stake:
            raise ValueError("stake mismatch between account decision and FrozenDecision")
        if bound_frozen_decision.frozen_at > frozen_at:
            raise ValueError("bound FrozenDecision frozen_at must not be after episode frozen_at")
        if (
            science_decision.identity == ScienceDecisionIdentity.SCIENCE_CANDIDATE
            and science_decision.candidate_ref not in bound_frozen_decision.candidate_refs
        ):
            raise ValueError(
                "SCIENCE_CANDIDATE candidate_ref must exist in bound FrozenDecision.candidate_refs"
            )
        if _amount(account_decision.stake) > _amount(balance):
            raise ValueError("stake exceeds pre-freeze balance")
        if not opening_journal_group_ref or not position_journal_group_ref:
            raise ValueError("ACTION freeze requires journal group refs")
        opening_journal = _expected_opening_journal(
            group_ref=opening_journal_group_ref,
            portfolio_ref=seat.portfolio_ref,
            frozen_at=frozen_at,
            pre_freeze_balance=balance,
        )
        position_journal = _expected_position_journal(
            group_ref=position_journal_group_ref,
            portfolio_ref=seat.portfolio_ref,
            decision_ref=bound_frozen_decision.decision_ref,
            frozen_at=frozen_at,
            stake=account_decision.stake,
        )
    else:
        if bound_frozen_decision is not None:
            raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must not bind FrozenDecision")
        if opening_journal_group_ref is not None or position_journal_group_ref is not None:
            raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION creates no position journals")

    return FrozenShadowEpisode(
        episode_ref=episode_ref,
        seat_id=seat.seat_id,
        portfolio_ref=seat.portfolio_ref,
        target_ref=target_ref,
        target_open_time=target_open_time,
        freeze_deadline=freeze_deadline,
        frozen_at=frozen_at,
        science_decision=science_decision,
        account_decision=account_decision,
        opening_balance=seat_opening,
        pre_freeze_balance=balance,
        rule_ref=account_decision.rule_ref,
        odds_version_ref=account_decision.odds_version_ref,
        bound_frozen_decision=bound_frozen_decision,
        opening_journal_group=opening_journal,
        position_journal_group=position_journal,
    ).with_content_hash()


def reject_policy_as_account_ticket(science_decision: ScienceBranchDecision) -> None:
    """Scientific POLICY_NO_ACTION is not an account-side ticket."""

    if science_decision.identity == ScienceDecisionIdentity.POLICY_NO_ACTION:
        raise ValueError(
            "POLICY_NO_ACTION is a science-branch identity and cannot substitute "
            "for RESEARCHER_ACCOUNT_NO_ACTION or ACTION account tickets"
        )


def admit_episode_outcome(
    *,
    episode: FrozenShadowEpisode,
    candidate: OutcomeObservation,
    existing: tuple[OutcomeObservation, ...] = (),
) -> OutcomeAdmission:
    """Admit a verified, target-matching outcome only at/after target open."""

    _require_content_seal(episode, label="episode")
    _require_outcome_seal(candidate)
    _require_aware(candidate.observed_at, field_name="observed_at")
    if candidate.observed_at < episode.target_open_time:
        raise ValueError("pre-open outcome rejected")
    if candidate.observed_at < episode.frozen_at:
        raise ValueError("outcome-before-freeze rejected")
    if candidate.target_ref != episode.target_ref:
        raise ValueError("outcome target and frozen episode disagree")
    if not candidate.verified:
        return OutcomeAdmission(status="QUARANTINED", outcome_ref=candidate.outcome_ref)
    return admit_outcome(existing, candidate)


def settle_shadow_episode(
    *,
    episode: FrozenShadowEpisode,
    outcome: OutcomeObservation,
    settlement_ref: str | None = None,
    settlement_journal_group_ref: str | None = None,
    statement_ref: str,
    existing_settlements: tuple[SettlementRecord, ...],
    occurred_at: datetime | None = None,
) -> SettledShadowEpisode:
    """Pure-function mechanical settlement; not naturally once-only without storage.

    Callers must pass ``existing_settlements`` explicitly (use ``()`` on the first
    call). When priors exist for the same frozen decision, conflicts still pause
    via ``admit_settlement``. This surface does not add platform storage.
    ACTION reuses settlement/ledger primitives; account no-action is zero P&L.
    """

    _require_content_seal(episode, label="episode")
    _require_outcome_seal(outcome)
    admission = admit_episode_outcome(episode=episode, candidate=outcome)
    if admission.status != "ACCEPTED":
        raise ValueError(f"outcome not admitted for settlement: {admission.status}")
    settled_at = occurred_at if occurred_at is not None else outcome.observed_at
    _require_aware(settled_at, field_name="occurred_at")
    if settled_at < episode.target_open_time:
        raise ValueError("settlement before target open rejected")
    if settled_at < outcome.observed_at:
        raise ValueError("settlement occurred_at must be at or after outcome.observed_at")

    if episode.account_decision.identity == AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION:
        if settlement_ref is not None or settlement_journal_group_ref is not None:
            raise ValueError("account no-action must not produce settlement journals")
        statement = AccountStatement(
            statement_ref=statement_ref,
            episode_ref=episode.episode_ref,
            seat_id=episode.seat_id,
            portfolio_ref=episode.portfolio_ref,
            target_ref=episode.target_ref,
            outcome_ref=outcome.outcome_ref,
            actual_special_number=outcome.actual_special_number,
            observed_at=outcome.observed_at,
            opening_balance=episode.pre_freeze_balance,
            account_decision=AccountDecisionIdentity.RESEARCHER_ACCOUNT_NO_ACTION,
            risk_stake=ZERO_AMOUNT,
            rule_ref=episode.rule_ref,
            odds_version_ref=episode.odds_version_ref,
            selected_number=None,
            panel=None,
            baseline_ref=None,
            odds=None,
            result=StatementResultKind.NO_EXPOSURE,
            pnl=ZERO_AMOUNT,
            closing_balance=episode.pre_freeze_balance,
            anomaly_status=AnomalyStatus.NONE,
        ).with_content_hash()
        return SettledShadowEpisode(
            episode_ref=episode.episode_ref,
            frozen_episode_hash=episode.content_hash,
            seat_id=episode.seat_id,
            portfolio_ref=episode.portfolio_ref,
            outcome=outcome,
            settlement_bundle=None,
            journal_groups=(),
            statement=statement,
        ).with_content_hash()

    # ACTION path
    if episode.bound_frozen_decision is None:
        raise ValueError("ACTION settle requires bound FrozenDecision")
    _require_content_seal(episode.bound_frozen_decision, label="bound FrozenDecision")
    _require_mechanical_rule_ref(episode.rule_ref, boundary="ACTION settle")
    _require_mechanical_rule_ref(episode.bound_frozen_decision.rule_ref, boundary="ACTION settle")
    if episode.opening_journal_group is None or episode.position_journal_group is None:
        raise ValueError("ACTION settle requires complete freeze journals (half transaction)")
    if not settlement_ref or not settlement_journal_group_ref:
        raise ValueError("ACTION settle requires settlement refs")

    bundle = settle_frozen_decision(
        frozen=episode.bound_frozen_decision,
        outcome=outcome,
        settlement_ref=settlement_ref,
        journal_group_ref=settlement_journal_group_ref,
        portfolio_ref=episode.portfolio_ref,
        occurred_at=settled_at,
    )
    if bundle.journal_group.portfolio_ref != episode.portfolio_ref:
        raise ValueError("settlement journal portfolio mismatch")
    if bundle.record.rule_ref != episode.rule_ref:
        raise ValueError("settlement record rule_ref must match episode rule_ref")
    if bundle.record.result.rule_ref != episode.bound_frozen_decision.rule_ref:
        raise ValueError("SettlementResult.rule_ref must match frozen rule_ref")
    admission_status = admit_settlement(existing_settlements, bundle.record)
    if admission_status == "DUPLICATE":
        raise ValueError("double or conflicting settlement rejected")

    journals = (
        episode.opening_journal_group,
        episode.position_journal_group,
        bundle.journal_group,
    )
    balances = replay_balances(journals)
    closing = _cash_balance(balances)
    pnl = _fmt_amount(_amount(closing) - _amount(episode.pre_freeze_balance))
    result_kind = StatementResultKind.HIT if bundle.record.result.hit else StatementResultKind.MISS
    settlement_result = bundle.record.result

    statement = AccountStatement(
        statement_ref=statement_ref,
        episode_ref=episode.episode_ref,
        seat_id=episode.seat_id,
        portfolio_ref=episode.portfolio_ref,
        target_ref=episode.target_ref,
        outcome_ref=outcome.outcome_ref,
        actual_special_number=outcome.actual_special_number,
        observed_at=outcome.observed_at,
        opening_balance=episode.pre_freeze_balance,
        account_decision=AccountDecisionIdentity.ACTION,
        risk_stake=episode.account_decision.stake,
        rule_ref=episode.rule_ref,
        odds_version_ref=episode.odds_version_ref,
        selected_number=settlement_result.selected_number,
        panel=settlement_result.panel,
        baseline_ref=settlement_result.baseline_ref,
        odds=settlement_result.odds,
        result=result_kind,
        pnl=pnl,
        closing_balance=closing,
        anomaly_status=AnomalyStatus.NONE,
    ).with_content_hash()

    return SettledShadowEpisode(
        episode_ref=episode.episode_ref,
        frozen_episode_hash=episode.content_hash,
        seat_id=episode.seat_id,
        portfolio_ref=episode.portfolio_ref,
        outcome=outcome,
        settlement_bundle=bundle,
        journal_groups=journals,
        statement=statement,
    ).with_content_hash()


def replay_settled_episode(
    *,
    episode: FrozenShadowEpisode,
    outcome: OutcomeObservation,
    settled: SettledShadowEpisode,
    seat: ShadowSeat | None = None,
    portfolio_ref: str | None = None,
) -> SettledShadowEpisode:
    """Fresh replay from sealed inputs; fail closed on mutation or mismatch."""

    _require_content_seal(episode, label="episode")
    _require_content_seal(settled, label="settled episode")
    if settled.frozen_episode_hash != episode.content_hash:
        raise ValueError("settled episode does not bind frozen episode hash")
    if settled.episode_ref != episode.episode_ref:
        raise ValueError("episode_ref mismatch on replay")
    if settled.seat_id != episode.seat_id:
        raise ValueError("cross-seat mismatch rejected")
    if settled.portfolio_ref != episode.portfolio_ref:
        raise ValueError("cross-portfolio mismatch rejected")
    if seat is not None:
        _require_content_seal(seat, label="seat")
        if seat.seat_id != episode.seat_id:
            raise ValueError("cross-seat mismatch rejected")
        if seat.portfolio_ref != episode.portfolio_ref:
            raise ValueError("cross-portfolio mismatch rejected")
    if portfolio_ref is not None and portfolio_ref != episode.portfolio_ref:
        raise ValueError("cross-portfolio mismatch rejected")
    _require_outcome_seal(outcome)
    if outcome.target_ref != episode.target_ref:
        raise ValueError("target mismatch rejected")
    if settled.statement.target_ref != episode.target_ref:
        raise ValueError("statement target_ref mismatch on replay")
    if settled.statement.outcome_ref != outcome.outcome_ref:
        raise ValueError("statement outcome_ref mismatch on replay")
    if settled.statement.actual_special_number != outcome.actual_special_number:
        raise ValueError("statement actual_special_number mismatch on replay")
    if settled.statement.observed_at != outcome.observed_at:
        raise ValueError("statement observed_at mismatch on replay")
    if episode.account_decision.identity == AccountDecisionIdentity.ACTION:
        for field in ("selected_number", "panel", "baseline_ref", "odds"):
            if getattr(settled.statement, field) is None:
                raise ValueError(f"ACTION statement {field} missing on replay")
    else:
        for field in ("selected_number", "panel", "baseline_ref", "odds"):
            if getattr(settled.statement, field) is not None:
                raise ValueError(f"NO_EXPOSURE statement forged {field} on replay")

    # Half-transaction: ACTION must carry full journal chain
    if episode.account_decision.identity == AccountDecisionIdentity.ACTION:
        if episode.opening_journal_group is None or episode.position_journal_group is None:
            raise ValueError("half transaction rejected")
        if settled.settlement_bundle is None:
            raise ValueError("half transaction rejected: missing settlement")
        if len(settled.journal_groups) != 3:
            raise ValueError("half transaction rejected: incomplete journals")
        for group in settled.journal_groups:
            if group.group_hash is None or group.with_hash().group_hash != group.group_hash:
                raise ValueError("journal group hash mismatch")
            if group.portfolio_ref != episode.portfolio_ref:
                raise ValueError("cross-portfolio mismatch rejected")
        replay_balances(settled.journal_groups)
    else:
        if settled.settlement_bundle is not None:
            raise ValueError("account no-action must not carry settlement bundle")
        if settled.journal_groups:
            raise ValueError("account no-action must not carry settlement journals")
        if settled.statement.result != StatementResultKind.NO_EXPOSURE:
            raise ValueError("account no-action statement result mismatch")
        if settled.statement.pnl != ZERO_AMOUNT:
            raise ValueError("account no-action pnl must be zero")

    # Re-settle deterministically and compare sealed identity
    if episode.account_decision.identity == AccountDecisionIdentity.ACTION:
        assert settled.settlement_bundle is not None
        fresh = settle_shadow_episode(
            episode=episode,
            outcome=outcome,
            settlement_ref=settled.settlement_bundle.record.settlement_ref,
            settlement_journal_group_ref=settled.settlement_bundle.journal_group.group_ref,
            statement_ref=settled.statement.statement_ref,
            occurred_at=settled.settlement_bundle.journal_group.occurred_at,
            existing_settlements=(),
        )
    else:
        fresh = settle_shadow_episode(
            episode=episode,
            outcome=outcome,
            statement_ref=settled.statement.statement_ref,
            occurred_at=outcome.observed_at,
            existing_settlements=(),
        )

    if fresh.content_hash != settled.content_hash:
        raise ValueError("fresh replay hash mismatch")
    if fresh.statement.content_hash != settled.statement.content_hash:
        raise ValueError("statement replay hash mismatch")
    if fresh.statement.closing_balance != settled.statement.closing_balance:
        raise ValueError("balance replay mismatch")
    return fresh


def reject_conflicting_settlement(
    *,
    existing: SettledShadowEpisode,
    candidate: SettledShadowEpisode,
) -> None:
    if existing.episode_ref != candidate.episode_ref:
        return
    if existing.content_hash == candidate.content_hash:
        raise ValueError("double settlement rejected")
    raise ValueError("conflicting settlement rejected")


def assess_fixture_evidence(
    *,
    implementation_ready: bool,
    synthetic_or_historical: bool = True,
    science_only_policy_no_action: bool = False,
    account_ticket_frozen: bool = False,
) -> EvidenceAssessment:
    """Unit/synthetic fixtures may prove readiness, never real first-episode verification."""

    if science_only_policy_no_action and not account_ticket_frozen:
        return EvidenceAssessment(
            state=EvidenceState.IMPLEMENTATION_READY
            if implementation_ready
            else EvidenceState.UNIT_FIXTURE_ONLY,
            prospective_freeze_attested=False,
            independent_outcome_attested=False,
            first_episode_verified=False,
            notes=(
                "POLICY_NO_ACTION alone never counts as SHADOW_PRACTICE_STARTED; "
                "no account ticket freeze."
            ),
        )

    if synthetic_or_historical:
        state = (
            EvidenceState.IMPLEMENTATION_READY
            if implementation_ready
            else EvidenceState.UNIT_FIXTURE_ONLY
        )
        return EvidenceAssessment(
            state=state,
            prospective_freeze_attested=False,
            independent_outcome_attested=False,
            first_episode_verified=False,
            notes=(
                "Synthetic/historical fixtures cannot claim FIRST_EPISODE_VERIFIED; "
                "that milestone requires a real prospective freeze and later independent outcome."
            ),
        )

    # No trusted external attestation carrier on this surface: refuse non-synthetic promotion.
    raise ValueError(
        "non-synthetic claims require trusted external attestation; "
        "this library cannot construct FIRST_EPISODE_VERIFIED"
    )
