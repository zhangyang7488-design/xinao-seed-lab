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
    settlement_group,
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
from xinao.settlement.special_number import (
    SPECIAL_NUMBER_FUNCTION,
    SPECIAL_NUMBER_RULE,
    SettlementResult,
    settle_special_number,
)

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


class AccountingBasis(StrEnum):
    """How one episode reconstructs its opening cash without changing funding identity."""

    LEGACY_OPENING_JOURNAL = "LEGACY_OPENING_JOURNAL"
    CARRIED_BALANCE_SNAPSHOT = "CARRIED_BALANCE_SNAPSHOT"


class FeedbackKind(StrEnum):
    TYPED_FEEDBACK = "TYPED_FEEDBACK"
    NO_CHANGE_WITH_REASON = "NO_CHANGE_WITH_REASON"


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


def _period_snapshot_balances(pre_freeze_balance: str) -> dict[str, str]:
    """Balanced period-start snapshot; it is not a second funding transaction."""

    amount = _fmt_amount(pre_freeze_balance)
    values = {account.value: ZERO_AMOUNT for account in Account}
    values[Account.SHADOW_CASH.value] = amount
    values[Account.OPENING_CAPITAL_EQUITY.value] = _fmt_amount(-_amount(amount))
    return values


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


class AccountRiskTicket(BaseModel):
    """Sealed account-scope ACTION ticket with no scientific adoption fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticket_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    target_open_time: datetime
    freeze_deadline: datetime
    knowledge_cutoff: datetime
    frozen_at: datetime
    panel: Literal["A", "B"]
    selected_number: int = Field(ge=1, le=49)
    stake: str
    rule_ref: str = Field(min_length=1)
    odds_version_ref: str = Field(min_length=1)
    baseline_ref: str = Field(min_length=1)
    risk_policy_ref: str = Field(min_length=1)
    information_set_ref: str = Field(min_length=1)
    information_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_ticket(self) -> Self:
        for name, value in (
            ("target_open_time", self.target_open_time),
            ("freeze_deadline", self.freeze_deadline),
            ("knowledge_cutoff", self.knowledge_cutoff),
            ("frozen_at", self.frozen_at),
        ):
            _require_aware(value, field_name=name)
        if not (self.frozen_at <= self.freeze_deadline < self.target_open_time):
            raise ValueError(
                "ACCOUNT_TICKET_TEMPORAL_VIOLATION: require "
                "frozen_at <= freeze_deadline < target_open_time"
            )
        if self.knowledge_cutoff > self.frozen_at:
            raise ValueError(
                "ACCOUNT_TICKET_TEMPORAL_VIOLATION: knowledge_cutoff must be at or before frozen_at"
            )
        stake = _amount(self.stake)
        if self.stake != _fmt_amount(stake) or stake <= 0:
            raise ValueError(
                "ACCOUNT_TICKET_STAKE_INVALID: stake must be positive at accounting scale"
            )
        _require_mechanical_rule_ref(self.rule_ref, boundary="AccountRiskTicket")
        expected_baseline = (
            SPECIAL_NUMBER_FUNCTION.a_baseline_ref
            if self.panel == "A"
            else SPECIAL_NUMBER_FUNCTION.b_baseline_ref
        )
        if self.baseline_ref != expected_baseline:
            raise ValueError("ACCOUNT_TICKET_BASELINE_INVALID: baseline_ref must match the panel")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical account risk ticket")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> AccountRiskTicket:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class PeriodOpenBinding(BaseModel):
    """Binds period N to the exact settled close of period N-1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    period_index: int = Field(ge=2)
    prior_period_index: int = Field(ge=1)
    prior_episode_ref: str = Field(min_length=1)
    prior_settled_episode_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_statement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_closing_balance: str
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.prior_period_index != self.period_index - 1:
            raise ValueError("HISTORY_GAP: prior period must be exactly period_index - 1")
        if self.prior_closing_balance != _fmt_amount(self.prior_closing_balance):
            raise ValueError("prior_closing_balance must use accounting scale")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical period-open binding")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> PeriodOpenBinding:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class ShadowPortfolio(BaseModel):
    """Immutable continuity-root identity; the live head is derived from sealed periods."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.shadow_lifecycle.portfolio.v1"] = (
        "xinao.shadow_lifecycle.portfolio.v1"
    )
    seat_id: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    seat_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    genesis_opening_balance: str
    min_consumer_version: Literal["0.3.0"] = "0.3.0"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_portfolio(self) -> Self:
        if self.seat_id == self.portfolio_ref:
            raise ValueError("seat_id and portfolio_ref must be distinct")
        if self.genesis_opening_balance != _fmt_amount(self.genesis_opening_balance):
            raise ValueError("genesis_opening_balance must use accounting scale")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical shadow portfolio")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> ShadowPortfolio:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class AccountFeedback(BaseModel):
    """Sealed post-settlement account feedback that cannot promote science."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feedback_ref: str = Field(min_length=1)
    kind: FeedbackKind
    period_index: int = Field(ge=1)
    episode_ref: str = Field(min_length=1)
    settled_episode_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    statement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_pnl_echo: str
    reason_code: str | None = None
    notes: str = ""
    scientific_promotion: Literal[False] = False
    claim_grade_delta: Literal[None] = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_feedback(self) -> Self:
        if self.account_pnl_echo != _fmt_amount(self.account_pnl_echo):
            raise ValueError("account_pnl_echo must use accounting scale")
        if self.kind == FeedbackKind.NO_CHANGE_WITH_REASON and not self.reason_code:
            raise ValueError("NO_CHANGE_WITH_REASON requires reason_code")
        if self.scientific_promotion is not False or self.claim_grade_delta is not None:
            raise ValueError("SCIENCE_ACCOUNT_CROSS_GREEN")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match canonical account feedback")
        return self

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"content_hash"})

    def compute_content_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_content_hash(self) -> AccountFeedback:
        return self.model_copy(update={"content_hash": self.compute_content_hash()})


class AccountTicketSettlementRecord(BaseModel):
    """Mechanical settlement identity for an account-scoped risk ticket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_ref: str = Field(min_length=1)
    account_ticket_ref: str = Field(min_length=1)
    account_ticket_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_ref: str = Field(min_length=1)
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_ref: str = Field(min_length=1)
    result: SettlementResult
    journal_group_ref: str = Field(min_length=1)
    settlement_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def canonical_content(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"settlement_hash"})

    def compute_settlement_hash(self) -> str:
        return canonical_sha256(self.canonical_content())

    def with_hash(self) -> AccountTicketSettlementRecord:
        return self.model_copy(update={"settlement_hash": self.compute_settlement_hash()})


class AccountTicketSettlementBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: AccountTicketSettlementRecord
    journal_group: JournalGroup


class AccountBranchDecision(BaseModel):
    """Account branch only: ACTION risk ticket or explicit zero-risk no-action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_decision_ref: str = Field(min_length=1)
    identity: AccountDecisionIdentity
    frozen_decision_ref: str | None = None
    frozen_decision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    account_ticket_ref: str | None = None
    account_ticket_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
            frozen_pair = (self.frozen_decision_ref, self.frozen_decision_hash)
            ticket_pair = (self.account_ticket_ref, self.account_ticket_hash)
            if any(frozen_pair) and not all(frozen_pair):
                raise ValueError("ACTION FrozenDecision identity pair is incomplete")
            if any(ticket_pair) and not all(ticket_pair):
                raise ValueError("ACTION AccountRiskTicket identity pair is incomplete")
            if bool(all(frozen_pair)) == bool(all(ticket_pair)):
                raise ValueError(
                    "ACTION must bind exactly one sealed FrozenDecision or AccountRiskTicket"
                )
        else:
            if stake != 0:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must be zero-risk")
            if any(
                value is not None
                for value in (
                    self.frozen_decision_ref,
                    self.frozen_decision_hash,
                    self.account_ticket_ref,
                    self.account_ticket_hash,
                )
            ):
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must not bind an ACTION ticket")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical account decision")
        return self

    def canonical_content(self) -> dict[str, object]:
        body = self.model_dump(mode="json", exclude={"content_hash"})
        # These fields did not exist in the 0.2.0 schema. Omitting their null defaults
        # keeps every already sealed legacy decision byte-for-byte hash readable.
        if self.account_ticket_ref is None:
            body.pop("account_ticket_ref")
        if self.account_ticket_hash is None:
            body.pop("account_ticket_hash")
        return body

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
    bound_account_ticket: AccountRiskTicket | None = None
    period_index: int = Field(default=1, ge=1)
    prior_close_binding: PeriodOpenBinding | None = None
    accounting_basis: AccountingBasis = AccountingBasis.LEGACY_OPENING_JOURNAL
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
        if _amount(self.pre_freeze_balance) < 0:
            raise ValueError("pre_freeze_balance must be non-negative")

        if self.period_index == 1:
            if self.prior_close_binding is not None:
                raise ValueError("period 1 must not bind a prior close")
            if self.pre_freeze_balance != self.opening_balance:
                raise ValueError("period 1 pre_freeze_balance must equal seat opening_balance")
        else:
            if self.accounting_basis != AccountingBasis.CARRIED_BALANCE_SNAPSHOT:
                raise ValueError("period 2+ requires CARRIED_BALANCE_SNAPSHOT")
            if self.prior_close_binding is None:
                raise ValueError("period 2+ requires a sealed prior close binding")
            _require_content_seal(self.prior_close_binding, label="prior close binding")
            if self.prior_close_binding.period_index != self.period_index:
                raise ValueError("HISTORY_GAP: prior close binding period mismatch")
            if self.pre_freeze_balance != self.prior_close_binding.prior_closing_balance:
                raise ValueError(
                    "PRIOR_CLOSE_MISMATCH: pre-freeze balance differs from prior close"
                )

        if self.account_decision.identity == AccountDecisionIdentity.ACTION:
            has_frozen = self.bound_frozen_decision is not None
            has_ticket = self.bound_account_ticket is not None
            if has_frozen == has_ticket:
                raise ValueError("ACTION episode requires exactly one bound action ticket")
            _require_mechanical_rule_ref(self.rule_ref, boundary="ACTION episode")
            if _amount(self.account_decision.stake) > _amount(self.pre_freeze_balance):
                raise ValueError("stake exceeds pre-freeze balance")

            source_ref: str
            if has_frozen:
                assert self.bound_frozen_decision is not None
                frozen = self.bound_frozen_decision
                _require_content_seal(frozen, label="bound FrozenDecision")
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
                _require_mechanical_rule_ref(frozen.rule_ref, boundary="bound FrozenDecision")
                if (
                    self.science_decision.identity == ScienceDecisionIdentity.SCIENCE_CANDIDATE
                    and self.science_decision.candidate_ref not in frozen.candidate_refs
                ):
                    raise ValueError(
                        "SCIENCE_CANDIDATE candidate_ref must exist in bound "
                        "FrozenDecision.candidate_refs"
                    )
                source_ref = frozen.decision_ref
            else:
                assert self.bound_account_ticket is not None
                ticket = self.bound_account_ticket
                _require_content_seal(ticket, label="bound AccountRiskTicket")
                if ticket.ticket_ref != self.account_decision.account_ticket_ref:
                    raise ValueError("account decision account_ticket_ref mismatch")
                if ticket.content_hash != self.account_decision.account_ticket_hash:
                    raise ValueError("account decision account_ticket_hash mismatch")
                if ticket.target_ref != self.target_ref:
                    raise ValueError("bound AccountRiskTicket target_ref mismatch")
                if ticket.target_open_time != self.target_open_time:
                    raise ValueError("bound AccountRiskTicket target_open_time mismatch")
                if ticket.freeze_deadline != self.freeze_deadline:
                    raise ValueError("bound AccountRiskTicket freeze_deadline mismatch")
                if ticket.rule_ref != self.rule_ref:
                    raise ValueError("bound AccountRiskTicket rule_ref mismatch")
                if ticket.odds_version_ref != self.odds_version_ref:
                    raise ValueError("bound AccountRiskTicket odds_version_ref mismatch")
                if ticket.stake != self.account_decision.stake:
                    raise ValueError("account stake must equal AccountRiskTicket stake")
                if ticket.frozen_at > self.frozen_at:
                    raise ValueError("AccountRiskTicket frozen_at must not follow episode freeze")
                source_ref = ticket.ticket_ref

            if self.position_journal_group is None:
                raise ValueError("ACTION requires a frozen-position journal group")
            if self.accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
                if self.opening_journal_group is None:
                    raise ValueError("legacy ACTION requires an opening journal group")
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
            elif self.opening_journal_group is not None:
                raise ValueError("carried-balance ACTION must not post a new OPENING journal")
            expected_position = _expected_position_journal(
                group_ref=self.position_journal_group.group_ref,
                portfolio_ref=self.portfolio_ref,
                decision_ref=source_ref,
                frozen_at=self.frozen_at,
                stake=self.account_decision.stake,
            )
            if self.position_journal_group != expected_position:
                raise ValueError(
                    "position_journal_group must equal reconstructed frozen_position_group "
                    "(frozen_at, decision_ref, stake, group_ref, portfolio)"
                )
        else:
            if self.bound_frozen_decision is not None or self.bound_account_ticket is not None:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must not bind an ACTION ticket")
            if self.opening_journal_group is not None or self.position_journal_group is not None:
                raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must create no position journals")

        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical frozen episode")
        return self

    def canonical_content(self) -> dict[str, object]:
        body = self.model_dump(mode="json", exclude={"content_hash"})
        # Additive 0.3.0 fields are absent from legacy 0.2.0 hash projections.
        if self.bound_account_ticket is None:
            body.pop("bound_account_ticket")
        if self.period_index == 1:
            body.pop("period_index")
        if self.prior_close_binding is None:
            body.pop("prior_close_binding")
        if self.accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
            body.pop("accounting_basis")
        account_body = body.get("account_decision")
        if isinstance(account_body, dict):
            if self.account_decision.account_ticket_ref is None:
                account_body.pop("account_ticket_ref", None)
            if self.account_decision.account_ticket_hash is None:
                account_body.pop("account_ticket_hash", None)
        return body

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
    period_index: int = Field(default=1, ge=1)
    seat_id: str = Field(min_length=1)
    portfolio_ref: str = Field(min_length=1)
    outcome: OutcomeObservation
    settlement_bundle: SettlementBundle | AccountTicketSettlementBundle | None = None
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
        if self.settlement_bundle is not None:
            record = self.settlement_bundle.record
            if (
                record.settlement_hash is None
                or record.with_hash().settlement_hash != record.settlement_hash
            ):
                raise ValueError("settlement record content seal invalid")
            group = self.settlement_bundle.journal_group
            if group.group_hash is None or group.with_hash().group_hash != group.group_hash:
                raise ValueError("settlement journal content seal invalid")
        if self.content_hash is not None and self.content_hash != self.compute_content_hash():
            raise ValueError("content_hash does not match the canonical settled episode")
        return self

    def canonical_content(self) -> dict[str, object]:
        body = self.model_dump(mode="json", exclude={"content_hash"})
        # Preserve 0.2.0 settled hashes while sealing period identity for period 2+.
        if self.period_index == 1:
            body.pop("period_index")
        return body

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


def create_portfolio(*, seat: ShadowSeat) -> ShadowPortfolio:
    """Seal the immutable continuity-root identity around an existing seat."""

    _require_content_seal(seat, label="seat")
    assert seat.content_hash is not None
    return ShadowPortfolio(
        seat_id=seat.seat_id,
        portfolio_ref=seat.portfolio_ref,
        seat_content_hash=seat.content_hash,
        genesis_opening_balance=seat.opening_balance,
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


def build_account_action_from_ticket(
    *,
    account_decision_ref: str,
    account_ticket: AccountRiskTicket,
) -> AccountBranchDecision:
    """Build ACTION without importing scientific adoption or claim-grade gates."""

    _require_content_seal(account_ticket, label="AccountRiskTicket")
    _require_mechanical_rule_ref(account_ticket.rule_ref, boundary="account ticket build")
    assert account_ticket.content_hash is not None
    return AccountBranchDecision(
        account_decision_ref=account_decision_ref,
        identity=AccountDecisionIdentity.ACTION,
        account_ticket_ref=account_ticket.ticket_ref,
        account_ticket_hash=account_ticket.content_hash,
        stake=account_ticket.stake,
        rule_ref=account_ticket.rule_ref,
        odds_version_ref=account_ticket.odds_version_ref,
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
    bound_account_ticket: AccountRiskTicket | None = None,
    period_index: int = 1,
    prior_settled: SettledShadowEpisode | None = None,
    accounting_basis: AccountingBasis = AccountingBasis.LEGACY_OPENING_JOURNAL,
    opening_journal_group_ref: str | None = None,
    position_journal_group_ref: str | None = None,
    outcome_present: bool = False,
) -> FrozenShadowEpisode:
    """Freeze one prospective period with exact genesis or predecessor balance binding."""

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

    seat_opening = _fmt_amount(seat.opening_balance)
    prior_binding: PeriodOpenBinding | None = None
    if period_index < 1:
        raise ValueError("period_index must be positive")
    if period_index == 1:
        if prior_settled is not None:
            raise ValueError("period 1 must not supply a prior settled episode")
        balance = seat_opening
        if pre_freeze_balance is not None and _fmt_amount(pre_freeze_balance) != balance:
            raise ValueError(
                "pre_freeze_balance must equal sealed seat opening_balance "
                f"({seat_opening}); bare roll-forward / inflated balances rejected"
            )
    else:
        if accounting_basis != AccountingBasis.CARRIED_BALANCE_SNAPSHOT:
            raise ValueError("period 2+ requires CARRIED_BALANCE_SNAPSHOT")
        if prior_settled is None:
            raise ValueError("period 2+ requires the exact prior settled episode")
        _require_content_seal(prior_settled, label="prior settled episode")
        _require_content_seal(prior_settled.statement, label="prior statement")
        if prior_settled.period_index != period_index - 1:
            raise ValueError("HISTORY_GAP: prior settled period must be exactly period_index - 1")
        if (
            prior_settled.seat_id != seat.seat_id
            or prior_settled.portfolio_ref != seat.portfolio_ref
        ):
            raise ValueError("FOREIGN_PORTFOLIO: prior settled seat/portfolio mismatch")
        assert prior_settled.content_hash is not None
        assert prior_settled.statement.content_hash is not None
        balance = prior_settled.statement.closing_balance
        if pre_freeze_balance is not None and _fmt_amount(pre_freeze_balance) != balance:
            raise ValueError("PRIOR_CLOSE_MISMATCH: supplied balance differs from prior close")
        prior_binding = PeriodOpenBinding(
            period_index=period_index,
            prior_period_index=period_index - 1,
            prior_episode_ref=prior_settled.episode_ref,
            prior_settled_episode_hash=prior_settled.content_hash,
            prior_statement_hash=prior_settled.statement.content_hash,
            prior_closing_balance=balance,
        ).with_content_hash()
    if _amount(balance) < 0:
        raise ValueError("pre_freeze_balance must be non-negative")

    opening_journal: JournalGroup | None = None
    position_journal: JournalGroup | None = None

    if account_decision.identity == AccountDecisionIdentity.ACTION:
        if (bound_frozen_decision is None) == (bound_account_ticket is None):
            raise ValueError(
                "ACTION freeze requires exactly one bound_frozen_decision or bound_account_ticket"
            )
        _require_mechanical_rule_ref(account_decision.rule_ref, boundary="ACTION freeze")
        source_ref: str
        if bound_frozen_decision is not None:
            _require_content_seal(bound_frozen_decision, label="bound FrozenDecision")
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
                raise ValueError(
                    "bound FrozenDecision frozen_at must not be after episode frozen_at"
                )
            if (
                science_decision.identity == ScienceDecisionIdentity.SCIENCE_CANDIDATE
                and science_decision.candidate_ref not in bound_frozen_decision.candidate_refs
            ):
                raise ValueError(
                    "SCIENCE_CANDIDATE candidate_ref must exist in bound "
                    "FrozenDecision.candidate_refs"
                )
            source_ref = bound_frozen_decision.decision_ref
        else:
            assert bound_account_ticket is not None
            _require_content_seal(bound_account_ticket, label="bound AccountRiskTicket")
            if bound_account_ticket.ticket_ref != account_decision.account_ticket_ref:
                raise ValueError("bound AccountRiskTicket ref mismatch")
            if bound_account_ticket.content_hash != account_decision.account_ticket_hash:
                raise ValueError("bound AccountRiskTicket hash mismatch")
            if bound_account_ticket.target_ref != target_ref:
                raise ValueError("bound AccountRiskTicket target mismatch")
            if bound_account_ticket.target_open_time != target_open_time:
                raise ValueError("bound AccountRiskTicket target_open_time mismatch")
            if bound_account_ticket.freeze_deadline != freeze_deadline:
                raise ValueError("bound AccountRiskTicket freeze_deadline mismatch")
            if bound_account_ticket.frozen_at > frozen_at:
                raise ValueError("bound AccountRiskTicket frozen_at follows episode freeze")
            if bound_account_ticket.stake != account_decision.stake:
                raise ValueError("stake mismatch between account decision and AccountRiskTicket")
            source_ref = bound_account_ticket.ticket_ref
        if _amount(account_decision.stake) > _amount(balance):
            raise ValueError("stake exceeds pre-freeze balance")
        if not position_journal_group_ref:
            raise ValueError("ACTION freeze requires position_journal_group_ref")
        if accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
            if not opening_journal_group_ref:
                raise ValueError("legacy ACTION freeze requires opening_journal_group_ref")
            opening_journal = _expected_opening_journal(
                group_ref=opening_journal_group_ref,
                portfolio_ref=seat.portfolio_ref,
                frozen_at=frozen_at,
                pre_freeze_balance=balance,
            )
        elif opening_journal_group_ref is not None:
            raise ValueError("carried-balance freeze must not request an OPENING journal")
        position_journal = _expected_position_journal(
            group_ref=position_journal_group_ref,
            portfolio_ref=seat.portfolio_ref,
            decision_ref=source_ref,
            frozen_at=frozen_at,
            stake=account_decision.stake,
        )
    else:
        if bound_frozen_decision is not None or bound_account_ticket is not None:
            raise ValueError("RESEARCHER_ACCOUNT_NO_ACTION must not bind an ACTION ticket")
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
        bound_account_ticket=bound_account_ticket,
        period_index=period_index,
        prior_close_binding=prior_binding,
        accounting_basis=accounting_basis,
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


def _settle_account_ticket(
    *,
    ticket: AccountRiskTicket,
    outcome: OutcomeObservation,
    settlement_ref: str,
    journal_group_ref: str,
    portfolio_ref: str,
    occurred_at: datetime,
) -> AccountTicketSettlementBundle:
    """Settle an account ticket through the same mechanical rule and ledger."""

    _require_content_seal(ticket, label="AccountRiskTicket")
    _require_outcome_seal(outcome)
    if not outcome.verified:
        raise ValueError("unverified outcome cannot produce a settlement")
    if outcome.target_ref != ticket.target_ref:
        raise ValueError("outcome target and AccountRiskTicket disagree")
    _require_mechanical_rule_ref(ticket.rule_ref, boundary="account ticket settlement")
    result = settle_special_number(
        selected_number=ticket.selected_number,
        actual_special_number=outcome.actual_special_number,
        panel=ticket.panel,
        stake=ticket.stake,
    )
    if result.rule_ref != ticket.rule_ref:
        raise ValueError("SettlementResult.rule_ref must match AccountRiskTicket rule_ref")
    if result.baseline_ref != ticket.baseline_ref:
        raise ValueError("AccountRiskTicket baseline_ref disagrees with mechanical settlement")
    journal = settlement_group(
        group_ref=journal_group_ref,
        portfolio_ref=portfolio_ref,
        settlement_ref=settlement_ref,
        occurred_at=occurred_at,
        result=result,
    )
    assert ticket.content_hash is not None
    assert outcome.result_hash is not None
    record = AccountTicketSettlementRecord(
        settlement_ref=settlement_ref,
        account_ticket_ref=ticket.ticket_ref,
        account_ticket_hash=ticket.content_hash,
        outcome_ref=outcome.outcome_ref,
        outcome_hash=outcome.result_hash,
        rule_ref=ticket.rule_ref,
        result=result,
        journal_group_ref=journal.group_ref,
    ).with_hash()
    return AccountTicketSettlementBundle(record=record, journal_group=journal)


def _admit_account_ticket_settlement(
    existing: tuple[SettlementRecord | AccountTicketSettlementRecord, ...],
    candidate: AccountTicketSettlementRecord,
) -> Literal["ACCEPTED", "DUPLICATE"]:
    if candidate.settlement_hash is None:
        raise ValueError("settlement must be hash sealed")
    for record in existing:
        if not isinstance(record, AccountTicketSettlementRecord):
            raise ValueError("settlement history source identity mismatch")
        if record.account_ticket_ref != candidate.account_ticket_ref:
            continue
        if record.settlement_hash == candidate.settlement_hash:
            return "DUPLICATE"
        raise ValueError("settlement conflict must pause automatic posting")
    return "ACCEPTED"


def settle_shadow_episode(
    *,
    episode: FrozenShadowEpisode,
    outcome: OutcomeObservation,
    settlement_ref: str | None = None,
    settlement_journal_group_ref: str | None = None,
    statement_ref: str,
    existing_settlements: tuple[SettlementRecord | AccountTicketSettlementRecord, ...],
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
            period_index=episode.period_index,
            seat_id=episode.seat_id,
            portfolio_ref=episode.portfolio_ref,
            outcome=outcome,
            settlement_bundle=None,
            journal_groups=(),
            statement=statement,
        ).with_content_hash()

    # ACTION path: the account ticket and legacy FrozenDecision are parallel
    # admission identities. Both settle through the same mechanical rule.
    if (episode.bound_frozen_decision is None) == (episode.bound_account_ticket is None):
        raise ValueError("ACTION settle requires exactly one bound action ticket")
    _require_mechanical_rule_ref(episode.rule_ref, boundary="ACTION settle")
    if episode.position_journal_group is None:
        raise ValueError("ACTION settle requires complete freeze journals (half transaction)")
    if episode.accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
        if episode.opening_journal_group is None:
            raise ValueError("legacy ACTION settle requires opening journal")
    elif episode.opening_journal_group is not None:
        raise ValueError("carried-balance ACTION must not carry an OPENING journal")
    if not settlement_ref or not settlement_journal_group_ref:
        raise ValueError("ACTION settle requires settlement refs")

    bundle: SettlementBundle | AccountTicketSettlementBundle
    if episode.bound_frozen_decision is not None:
        _require_content_seal(episode.bound_frozen_decision, label="bound FrozenDecision")
        _require_mechanical_rule_ref(
            episode.bound_frozen_decision.rule_ref, boundary="ACTION settle"
        )
        if any(not isinstance(item, SettlementRecord) for item in existing_settlements):
            raise ValueError("settlement history source identity mismatch")
        bundle = settle_frozen_decision(
            frozen=episode.bound_frozen_decision,
            outcome=outcome,
            settlement_ref=settlement_ref,
            journal_group_ref=settlement_journal_group_ref,
            portfolio_ref=episode.portfolio_ref,
            occurred_at=settled_at,
        )
        admission_status = admit_settlement(
            tuple(item for item in existing_settlements if isinstance(item, SettlementRecord)),
            bundle.record,
        )
    else:
        assert episode.bound_account_ticket is not None
        bundle = _settle_account_ticket(
            ticket=episode.bound_account_ticket,
            outcome=outcome,
            settlement_ref=settlement_ref,
            journal_group_ref=settlement_journal_group_ref,
            portfolio_ref=episode.portfolio_ref,
            occurred_at=settled_at,
        )
        admission_status = _admit_account_ticket_settlement(existing_settlements, bundle.record)
    if bundle.journal_group.portfolio_ref != episode.portfolio_ref:
        raise ValueError("settlement journal portfolio mismatch")
    if bundle.record.rule_ref != episode.rule_ref:
        raise ValueError("settlement record rule_ref must match episode rule_ref")
    if bundle.record.result.rule_ref != episode.rule_ref:
        raise ValueError("SettlementResult.rule_ref must match episode rule_ref")
    if admission_status == "DUPLICATE":
        raise ValueError("double or conflicting settlement rejected")

    if episode.accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
        assert episode.opening_journal_group is not None
        journals = (
            episode.opening_journal_group,
            episode.position_journal_group,
            bundle.journal_group,
        )
        balances = replay_balances(journals)
    else:
        journals = (episode.position_journal_group, bundle.journal_group)
        balances = replay_balances(
            journals,
            starting_balances=_period_snapshot_balances(episode.pre_freeze_balance),
        )
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
        period_index=episode.period_index,
        seat_id=episode.seat_id,
        portfolio_ref=episode.portfolio_ref,
        outcome=outcome,
        settlement_bundle=bundle,
        journal_groups=journals,
        statement=statement,
    ).with_content_hash()


def seal_account_feedback(
    *,
    feedback_ref: str,
    kind: FeedbackKind,
    period_index: int,
    settled: SettledShadowEpisode,
    outcome: OutcomeObservation,
    reason_code: str | None = None,
    notes: str = "",
) -> AccountFeedback:
    """Seal period feedback without granting scientific adoption or completion."""

    _require_content_seal(settled, label="settled episode")
    _require_content_seal(settled.statement, label="statement")
    _require_outcome_seal(outcome)
    if settled.outcome != outcome:
        raise ValueError("feedback outcome differs from settled episode outcome")
    if settled.period_index != period_index:
        raise ValueError("feedback period_index differs from settled episode")
    assert settled.content_hash is not None
    assert settled.statement.content_hash is not None
    assert outcome.result_hash is not None
    return AccountFeedback(
        feedback_ref=feedback_ref,
        kind=kind,
        period_index=period_index,
        episode_ref=settled.episode_ref,
        settled_episode_hash=settled.content_hash,
        statement_hash=settled.statement.content_hash,
        outcome_result_hash=outcome.result_hash,
        account_pnl_echo=settled.statement.pnl,
        reason_code=reason_code,
        notes=notes,
        scientific_promotion=False,
        claim_grade_delta=None,
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
        if episode.position_journal_group is None:
            raise ValueError("half transaction rejected")
        if settled.settlement_bundle is None:
            raise ValueError("half transaction rejected: missing settlement")
        if episode.bound_frozen_decision is not None:
            if not isinstance(settled.settlement_bundle, SettlementBundle):
                raise ValueError("settlement bundle source identity mismatch")
        elif episode.bound_account_ticket is not None:
            if not isinstance(settled.settlement_bundle, AccountTicketSettlementBundle):
                raise ValueError("settlement bundle source identity mismatch")
        else:
            raise ValueError("ACTION episode has no bound action ticket")
        if episode.accounting_basis == AccountingBasis.LEGACY_OPENING_JOURNAL:
            if episode.opening_journal_group is None or len(settled.journal_groups) != 3:
                raise ValueError("half transaction rejected: incomplete legacy journals")
            starting_balances = None
        else:
            if episode.opening_journal_group is not None or len(settled.journal_groups) != 2:
                raise ValueError("half transaction rejected: incomplete carried journals")
            starting_balances = _period_snapshot_balances(episode.pre_freeze_balance)
        for group in settled.journal_groups:
            if group.group_hash is None or group.with_hash().group_hash != group.group_hash:
                raise ValueError("journal group hash mismatch")
            if group.portfolio_ref != episode.portfolio_ref:
                raise ValueError("cross-portfolio mismatch rejected")
        replay_balances(settled.journal_groups, starting_balances=starting_balances)
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
