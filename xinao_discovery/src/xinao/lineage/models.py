"""Hash-sealed links from a settlement back to every formal upstream identity."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xinao.canonical import canonical_sha256


class LineageIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.lineage_intent.v1"] = "xinao.lineage_intent.v1"
    lineage_ref: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    code_git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    code_dirty: bool
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dvc_lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_contract_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    dataset_ref: str = Field(min_length=1)
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_ref: str = Field(min_length=1)
    baseline_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_version: str = Field(min_length=1)
    experiment_ref: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    validation_ref: str = Field(min_length=1)
    validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_decision_ref: str = Field(min_length=1)
    frozen_decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_ref: str = Field(min_length=1)
    settlement_ref: str = Field(min_length=1)
    settlement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_snapshot_hashes: tuple[str, ...]
    output_hashes: tuple[str, ...]
    openlineage_run_id: str = Field(min_length=1)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    intent_hash: str | None = None

    def with_hash(self) -> LineageIntent:
        basis = self.model_dump(mode="json", exclude={"intent_hash"})
        return self.model_copy(update={"intent_hash": canonical_sha256(basis)})


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.evidence_manifest.v1"] = "xinao.evidence_manifest.v1"
    intent: LineageIntent
    mlflow_run_id: str = Field(min_length=1)
    openlineage_run_id: str = Field(min_length=1)
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    result_status: Literal["VERIFIED", "PARTIAL", "BLOCKED", "UNVERIFIED"]
    verifier: str = Field(min_length=1)
    created_at: datetime
    delivery_status: Literal["DELIVERED", "PENDING_RETRY"]
    manifest_hash: str | None = None

    def with_hash(self) -> EvidenceManifest:
        if self.intent.intent_hash is None:
            raise ValueError("lineage intent must be hash sealed")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("manifest created_at must be timezone-aware")
        if self.openlineage_run_id != self.intent.openlineage_run_id:
            raise ValueError("OpenLineage run identity drifted from formal intent")
        if self.trace_id != self.intent.trace_id:
            raise ValueError("OTel trace identity drifted from formal intent")
        basis = self.model_dump(mode="json", exclude={"manifest_hash"})
        return self.model_copy(update={"manifest_hash": canonical_sha256(basis)})


def build_lineage_intent(**values: object) -> LineageIntent:
    intent = LineageIntent.model_validate(values).with_hash()
    if len(set(intent.input_snapshot_hashes)) != len(intent.input_snapshot_hashes):
        raise ValueError("lineage input hashes must be unique")
    if len(set(intent.output_hashes)) != len(intent.output_hashes):
        raise ValueError("lineage output hashes must be unique")
    return intent
