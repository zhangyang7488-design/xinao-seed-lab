"""Typed human and agent handoff messages from the construction contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from xinao.canonical.identifiers import UUID7_PATTERN, require_uuid7
from xinao.canonical.time_profile import format_utc


class PayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntentPayload(PayloadBase):
    kind: Literal["Intent"] = "Intent"
    summary: str = Field(min_length=1)
    desired_outcome: str = Field(min_length=1)


class QuestionPayload(PayloadBase):
    kind: Literal["Question"] = "Question"
    question: str = Field(min_length=1)
    blocking: bool


class DecisionPayload(PayloadBase):
    kind: Literal["Decision"] = "Decision"
    decision: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class TaskPayload(PayloadBase):
    kind: Literal["Task"] = "Task"
    objective: str = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(min_length=1)


class ClaimPayload(PayloadBase):
    kind: Literal["Claim"] = "Claim"
    statement: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]


class EvidencePayload(PayloadBase):
    kind: Literal["Evidence"] = "Evidence"
    claim_refs: tuple[str, ...] = Field(min_length=1)
    verdict: Literal["supports", "contradicts", "inconclusive"]


class ArtifactPayload(PayloadBase):
    kind: Literal["Artifact"] = "Artifact"
    name: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewPayload(PayloadBase):
    kind: Literal["Review"] = "Review"
    subject_ref: str = Field(min_length=1)
    verdict: Literal["approved", "changes_requested", "rejected"]
    comments: tuple[str, ...] = ()


class BlockerPayload(PayloadBase):
    kind: Literal["Blocker"] = "Blocker"
    reason: str = Field(min_length=1)
    required_input: str = Field(min_length=1)


class StopPayload(PayloadBase):
    kind: Literal["Stop"] = "Stop"
    reason: str = Field(min_length=1)
    cancel_scope: tuple[str, ...] = Field(min_length=1)


class ResumePayload(PayloadBase):
    kind: Literal["Resume"] = "Resume"
    checkpoint_ref: str = Field(min_length=1)
    resume_from: str = Field(min_length=1)


class ResearchQuestionPayload(PayloadBase):
    kind: Literal["ResearchQuestion"] = "ResearchQuestion"
    question: str = Field(min_length=1)
    expected_information_gain: str = Field(min_length=1)
    budget: str = Field(min_length=1)


class EvidenceBundlePayload(PayloadBase):
    kind: Literal["EvidenceBundle"] = "EvidenceBundle"
    claims: tuple[str, ...] = Field(min_length=1)
    contradictions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class CandidateProposalPayload(PayloadBase):
    kind: Literal["CandidateProposal"] = "CandidateProposal"
    hypothesis: str = Field(min_length=1)
    parent_refs: tuple[str, ...] = ()
    risk: str = Field(min_length=1)


class CritiquePayload(PayloadBase):
    kind: Literal["Critique"] = "Critique"
    target_ref: str = Field(min_length=1)
    findings: tuple[str, ...] = Field(min_length=1)


class VerificationResultPayload(PayloadBase):
    kind: Literal["VerificationResult"] = "VerificationResult"
    criteria: tuple[str, ...] = Field(min_length=1)
    verdict: Literal["verified", "partial", "blocked", "unverified"]


HandoffPayload = Annotated[
    IntentPayload
    | QuestionPayload
    | DecisionPayload
    | TaskPayload
    | ClaimPayload
    | EvidencePayload
    | ArtifactPayload
    | ReviewPayload
    | BlockerPayload
    | StopPayload
    | ResumePayload
    | ResearchQuestionPayload
    | EvidenceBundlePayload
    | CandidateProposalPayload
    | CritiquePayload
    | VerificationResultPayload,
    Field(discriminator="kind"),
]


class HandoffMessage(BaseModel):
    """Minimum typed message envelope for all human/agent handoffs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: Annotated[str, Field(pattern=UUID7_PATTERN)]
    schema_version: Literal["xinao.agent_handoff.v1"] = "xinao.agent_handoff.v1"
    session_id: str = Field(min_length=1)
    workflow_id: str | None = None
    run_id: str | None = None
    correlation_id: Annotated[str, Field(pattern=UUID7_PATTERN)]
    handoff_id: Annotated[str, Field(pattern=UUID7_PATTERN)]
    thread_id: Annotated[str, Field(pattern=UUID7_PATTERN)]
    parent_id: Annotated[str, Field(pattern=UUID7_PATTERN)] | None = None
    causation_id: Annotated[str, Field(pattern=UUID7_PATTERN)] | None = None
    actor: str = Field(min_length=1)
    target_object: str = Field(min_length=1)
    authority_scope: tuple[str, ...] = Field(min_length=1)
    scope: tuple[str, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    status: Literal[
        "proposed",
        "accepted",
        "running",
        "completed",
        "rejected",
        "blocked",
        "cancel_requested",
        "paused",
    ]
    expiry: datetime | None = None
    idempotency_key: str = Field(min_length=1)
    created_at: datetime
    payload: HandoffPayload

    @field_validator(
        "message_id", "correlation_id", "handoff_id", "thread_id", "parent_id", "causation_id"
    )
    @classmethod
    def validate_uuid7_fields(cls, value: str | None) -> str | None:
        return None if value is None else require_uuid7(value)

    @field_validator("created_at", "expiry")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            format_utc(value)
        return value

    @field_serializer("created_at", "expiry")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc(value)

    @model_validator(mode="after")
    def validate_execution_and_expiry(self) -> Self:
        if (self.workflow_id is None) != (self.run_id is None):
            raise ValueError("workflow_id and run_id must be supplied together")
        if self.expiry is not None and self.expiry <= self.created_at:
            raise ValueError("expiry must be later than created_at")
        return self
