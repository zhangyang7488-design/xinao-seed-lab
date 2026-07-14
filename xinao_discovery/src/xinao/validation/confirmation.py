"""Application-side gate in front of the limited confirmation-vault API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from xinao.canonical import canonical_sha256

from .court import CandidateReport


class CandidateVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str
    semantic_config: dict[str, Any]

    @property
    def semantic_hash(self) -> str:
        return canonical_sha256(self.semantic_config)


class ConfirmationBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str
    candidate_semantic_hash: str
    validation_output_hash: str
    admitted_query_kinds: tuple[str, ...] = ("AGGREGATE_EFFECT", "FINAL_GATE")


def bind_confirmation(candidate: CandidateVersion, report: CandidateReport) -> ConfirmationBinding:
    if report.output_hash is None:
        raise ValueError("validation report must be hash sealed")
    if candidate.candidate_ref != report.candidate_ref:
        raise ValueError("candidate and validation report identities disagree")
    if report.verdict != "ACTION":
        raise ValueError("NO_ACTION candidate cannot consume confirmation budget")
    return ConfirmationBinding(
        candidate_ref=candidate.candidate_ref,
        candidate_semantic_hash=candidate.semantic_hash,
        validation_output_hash=report.output_hash,
    )


def require_new_candidate_id(
    prior: ConfirmationBinding, candidate: CandidateVersion
) -> CandidateVersion:
    if (
        candidate.semantic_hash != prior.candidate_semantic_hash
        and candidate.candidate_ref == prior.candidate_ref
    ):
        raise ValueError("semantic change after confirmation requires a new CandidateVersion ID")
    return candidate
