"""Idempotent outcome observation and deterministic shadow settlement."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import canonical_sha256
from xinao.decision import FrozenDecision
from xinao.ledger.accounting import JournalGroup, settlement_group

from .special_number import SettlementResult, settle_special_number


class OutcomeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome_ref: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    actual_special_number: int = Field(ge=1, le=49)
    observed_at: datetime
    verified: bool
    supersedes_outcome_ref: str | None = None
    result_hash: str | None = None

    def with_hash(self) -> OutcomeObservation:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("outcome timestamp must be timezone-aware")
        basis = {
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "actual_special_number": self.actual_special_number,
        }
        return self.model_copy(update={"result_hash": canonical_sha256(basis)})


class OutcomeAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ACCEPTED", "DUPLICATE", "CONFLICT", "QUARANTINED"]
    outcome_ref: str
    conflicting_outcome_refs: tuple[str, ...] = ()


class SettlementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_ref: str = Field(min_length=1)
    frozen_decision_ref: str
    frozen_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_ref: str
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_ref: str
    result: SettlementResult
    journal_group_ref: str
    settlement_hash: str | None = None

    def with_hash(self) -> SettlementRecord:
        basis = self.model_dump(mode="json", exclude={"settlement_hash"})
        return self.model_copy(update={"settlement_hash": canonical_sha256(basis)})


class SettlementBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: SettlementRecord
    journal_group: JournalGroup


def admit_outcome(
    existing: tuple[OutcomeObservation, ...], candidate: OutcomeObservation
) -> OutcomeAdmission:
    if candidate.result_hash is None:
        raise ValueError("outcome must be hash sealed")
    if not candidate.verified:
        return OutcomeAdmission(status="QUARANTINED", outcome_ref=candidate.outcome_ref)
    same_target = tuple(
        outcome
        for outcome in existing
        if outcome.source_ref == candidate.source_ref and outcome.target_ref == candidate.target_ref
    )
    for outcome in same_target:
        if outcome.result_hash == candidate.result_hash:
            return OutcomeAdmission(status="DUPLICATE", outcome_ref=outcome.outcome_ref)
    if same_target:
        return OutcomeAdmission(
            status="CONFLICT",
            outcome_ref=candidate.outcome_ref,
            conflicting_outcome_refs=tuple(outcome.outcome_ref for outcome in same_target),
        )
    return OutcomeAdmission(status="ACCEPTED", outcome_ref=candidate.outcome_ref)


def settle_frozen_decision(
    *,
    frozen: FrozenDecision,
    outcome: OutcomeObservation,
    settlement_ref: str,
    journal_group_ref: str,
    portfolio_ref: str,
    occurred_at: datetime,
) -> SettlementBundle:
    if frozen.decision_hash is None or outcome.result_hash is None:
        raise ValueError("freeze and outcome must be hash sealed")
    if frozen.decision_type != "ACTION":
        raise ValueError("NO_ACTION freeze cannot produce a settlement")
    if not outcome.verified:
        raise ValueError("unverified outcome cannot produce a settlement")
    if outcome.target_ref != frozen.target_ref:
        raise ValueError("outcome target and frozen decision disagree")
    result = settle_special_number(
        selected_number=frozen.selected_number,
        actual_special_number=outcome.actual_special_number,
        panel=frozen.panel,
        stake=frozen.stake,
    )
    journal = settlement_group(
        group_ref=journal_group_ref,
        portfolio_ref=portfolio_ref,
        settlement_ref=settlement_ref,
        occurred_at=occurred_at,
        result=result,
    )
    record = SettlementRecord(
        settlement_ref=settlement_ref,
        frozen_decision_ref=frozen.decision_ref,
        frozen_decision_hash=frozen.decision_hash,
        outcome_ref=outcome.outcome_ref,
        outcome_hash=outcome.result_hash,
        rule_ref=frozen.rule_ref,
        result=result,
        journal_group_ref=journal.group_ref,
    ).with_hash()
    return SettlementBundle(record=record, journal_group=journal)


def admit_settlement(
    existing: tuple[SettlementRecord, ...], candidate: SettlementRecord
) -> Literal["ACCEPTED", "DUPLICATE"]:
    if candidate.settlement_hash is None:
        raise ValueError("settlement must be hash sealed")
    for record in existing:
        if record.frozen_decision_ref != candidate.frozen_decision_ref:
            continue
        if record.settlement_hash == candidate.settlement_hash:
            return "DUPLICATE"
        raise ValueError("settlement conflict must pause automatic posting")
    return "ACCEPTED"
