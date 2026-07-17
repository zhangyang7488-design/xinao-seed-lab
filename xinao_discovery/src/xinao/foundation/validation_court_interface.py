"""Generic, domain-neutral validation-court contracts sealed by F4.

F4 owns only this request/admission/result boundary and its temporal and
content-binding invariants.  Concrete datasets, split dates, statistical
protocols, candidate reports, and candidate identities are P5 instances.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from xinao.canonical import canonical_sha256
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
    FROZEN_ROUTE_QUOTE_BASELINE_IDS,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"

COURT_ADMISSION_INVARIANTS = (
    "ACTIVE_SETTLEMENT_REFS_CANONICAL_AND_FROZEN_EXCLUDED",
    "ERROR_BUDGET_ADMITTED",
    "FEATURE_TIMESTAMP_LT_TARGET_OPEN_TIME",
    "FIXED_SPLIT_AND_PARTITION_IDENTITY_HASH_BOUND",
    "METHOD_REGISTRATION_AND_ADMISSION_HASH_BOUND",
    "NEGATIVE_CONTROLS_DECLARED",
    "PURGE_EMBARGO_COVERS_INFORMATION_HORIZON",
    "RESULT_AND_EVIDENCE_SCHEMAS_HASH_BOUND",
    "WALK_FORWARD_TRAIN_PRECEDES_TEST_WITH_PURGE",
)


class CourtArtifactBinding(BaseModel):
    """One immutable artifact identity used by the generic court boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)


class CourtFeatureObservation(BaseModel):
    """One feature/target time relation checked before court admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_ref: str = Field(min_length=1)
    feature_timestamp: datetime
    target_open_time: datetime

    @model_validator(mode="after")
    def reject_future_information(self) -> Self:
        if self.feature_timestamp.utcoffset() is None or self.target_open_time.utcoffset() is None:
            raise ValueError("court timestamps must be timezone-aware")
        if self.feature_timestamp >= self.target_open_time:
            raise ValueError("future leakage detected at validation-court boundary")
        return self


class CourtWalkForwardFold(BaseModel):
    """Generic ordered-row fold; concrete dates and row counts belong to P5."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fold_id: str = Field(min_length=1)
    train_start_index: int = Field(ge=0)
    train_end_index: int = Field(ge=0)
    test_start_index: int = Field(ge=0)
    test_end_index: int = Field(ge=0)

    @model_validator(mode="after")
    def order_train_and_test(self) -> Self:
        if self.train_start_index > self.train_end_index:
            raise ValueError("walk-forward train range is reversed")
        if self.test_start_index > self.test_end_index:
            raise ValueError("walk-forward test range is reversed")
        if self.train_end_index >= self.test_start_index:
            raise ValueError("walk-forward train must precede test")
        return self


class CourtNegativeControlEvidence(BaseModel):
    """Evidence that one requested negative control was actually exercised."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    control_kind: str = Field(min_length=1)
    evidence: CourtArtifactBinding
    passed: bool


class ValidationCourtRequest(BaseModel):
    """Domain-neutral request binding one candidate to a fixed court instance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.validation_court_request.v1"] = (
        "xinao.validation_court_request.v1"
    )
    request_ref: str = Field(min_length=1)
    work_key: str = Field(pattern=_SHA256_PATTERN)
    active_settlement_refs: tuple[str, ...] = Field(min_length=1)
    candidate_artifact: CourtArtifactBinding
    method_id: str = Field(min_length=1)
    method_registration_sha256: str = Field(pattern=_SHA256_PATTERN)
    method_admission_sha256: str = Field(pattern=_SHA256_PATTERN)
    protocol_artifact: CourtArtifactBinding
    split_manifest: CourtArtifactBinding
    evaluation_partition_ref: str = Field(min_length=1)
    evaluation_partition_sha256: str = Field(pattern=_SHA256_PATTERN)
    feature_lookback_rows: int = Field(ge=0)
    decision_horizon_rows: int = Field(ge=1)
    purge_embargo_rows: int = Field(ge=1)
    feature_observations: tuple[CourtFeatureObservation, ...] = ()
    walk_forward_folds: tuple[CourtWalkForwardFold, ...] = Field(min_length=1)
    negative_control_kinds: tuple[str, ...] = Field(min_length=1)
    error_budget_policy_ref: str = Field(min_length=1)
    error_budget_policy_sha256: str = Field(pattern=_SHA256_PATTERN)
    hypotheses_in_family: int = Field(ge=0)
    confirmation_queries_used: int = Field(ge=0)
    input_snapshot_hashes: tuple[str, ...] = Field(min_length=1)
    result_schema: CourtArtifactBinding
    evidence_schema: CourtArtifactBinding

    @model_validator(mode="after")
    def enforce_generic_court_invariants(self) -> Self:
        active_refs = tuple(sorted(set(self.active_settlement_refs)))
        if active_refs != self.active_settlement_refs:
            raise ValueError("active settlement refs must be unique and canonically ordered")
        if set(active_refs) & FROZEN_ROUTE_QUOTE_BASELINE_IDS:
            raise ValueError("frozen route quote cannot enter validation court")
        if not set(active_refs) <= ACTIVE_SETTLEMENT_BASELINE_IDS:
            raise ValueError("validation court requires canonical ACTIVE settlement refs")

        horizon = max(self.feature_lookback_rows, self.decision_horizon_rows)
        if self.purge_embargo_rows < horizon:
            raise ValueError("purge/embargo must cover the maximum information horizon")

        observations = tuple(
            sorted(
                self.feature_observations,
                key=lambda item: (
                    item.target_open_time,
                    item.feature_ref,
                    item.feature_timestamp,
                ),
            )
        )
        observation_keys = {
            (item.feature_ref, item.feature_timestamp, item.target_open_time)
            for item in observations
        }
        if observations != self.feature_observations or len(observation_keys) != len(observations):
            raise ValueError("feature observations must be unique and canonically ordered")

        folds = tuple(
            sorted(
                self.walk_forward_folds,
                key=lambda item: (item.test_start_index, item.fold_id),
            )
        )
        if folds != self.walk_forward_folds or len({item.fold_id for item in folds}) != len(folds):
            raise ValueError("walk-forward folds must be unique and canonically ordered")
        previous_test_end = -1
        for fold in folds:
            gap_rows = fold.test_start_index - fold.train_end_index - 1
            if gap_rows < self.purge_embargo_rows:
                raise ValueError("walk-forward fold does not preserve purge/embargo")
            if fold.test_start_index <= previous_test_end:
                raise ValueError("walk-forward test ranges must not overlap")
            previous_test_end = fold.test_end_index

        controls = tuple(sorted(set(self.negative_control_kinds)))
        if controls != self.negative_control_kinds or not all(controls):
            raise ValueError("negative controls must be unique canonical non-empty names")
        inputs = tuple(sorted(set(self.input_snapshot_hashes)))
        if inputs != self.input_snapshot_hashes or not all(
            len(value) == 64 and all(character in "0123456789abcdef" for character in value)
            for value in inputs
        ):
            raise ValueError("input snapshot hashes must be unique canonical SHA-256 values")
        return self

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class ValidationCourtAdmission(BaseModel):
    """Positive admission after method, policy, and request bindings are checked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.validation_court_admission.v1"] = (
        "xinao.validation_court_admission.v1"
    )
    admitted: Literal[True] = True
    request_sha256: str = Field(pattern=_SHA256_PATTERN)
    work_key: str = Field(pattern=_SHA256_PATTERN)
    active_settlement_refs: tuple[str, ...] = Field(min_length=1)
    method_id: str = Field(min_length=1)
    method_registration_sha256: str = Field(pattern=_SHA256_PATTERN)
    method_admission_sha256: str = Field(pattern=_SHA256_PATTERN)
    error_budget_decision_sha256: str = Field(pattern=_SHA256_PATTERN)
    checked_invariants: tuple[str, ...] = COURT_ADMISSION_INVARIANTS

    @model_validator(mode="after")
    def exact_invariant_inventory(self) -> Self:
        if self.checked_invariants != COURT_ADMISSION_INVARIANTS:
            raise ValueError("validation-court admission invariant inventory drifted")
        active_refs = tuple(sorted(set(self.active_settlement_refs)))
        if active_refs != self.active_settlement_refs:
            raise ValueError("admitted ACTIVE refs must be unique and canonically ordered")
        if (
            set(active_refs) & FROZEN_ROUTE_QUOTE_BASELINE_IDS
            or not set(active_refs) <= ACTIVE_SETTLEMENT_BASELINE_IDS
        ):
            raise ValueError("validation-court admission contains a non-ACTIVE ref")
        return self

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class ValidationCourtResult(BaseModel):
    """Generic terminal court output; scientific result fields live in its artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["xinao.validation_court_result.v1"] = "xinao.validation_court_result.v1"
    result_ref: str = Field(min_length=1)
    request_sha256: str = Field(pattern=_SHA256_PATTERN)
    admission_sha256: str = Field(pattern=_SHA256_PATTERN)
    work_key: str = Field(pattern=_SHA256_PATTERN)
    active_settlement_refs: tuple[str, ...] = Field(min_length=1)
    verdict: Literal["VERIFIED", "FALSIFIED", "NO_ACTION"]
    negative_controls: tuple[CourtNegativeControlEvidence, ...] = Field(min_length=1)
    result_artifact: CourtArtifactBinding
    evidence: tuple[CourtArtifactBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_evidence_inventory(self) -> Self:
        active_refs = tuple(sorted(set(self.active_settlement_refs)))
        if active_refs != self.active_settlement_refs:
            raise ValueError("result ACTIVE refs must be unique and canonically ordered")
        if (
            set(active_refs) & FROZEN_ROUTE_QUOTE_BASELINE_IDS
            or not set(active_refs) <= ACTIVE_SETTLEMENT_BASELINE_IDS
        ):
            raise ValueError("validation-court result contains a non-ACTIVE ref")
        controls = tuple(sorted(self.negative_controls, key=lambda item: item.control_kind))
        unique_control_count = len({item.control_kind for item in controls})
        if controls != self.negative_controls or unique_control_count != len(controls):
            raise ValueError("negative-control evidence must be unique and canonically ordered")
        evidence = tuple(sorted(self.evidence, key=lambda item: item.ref))
        if evidence != self.evidence or len({item.ref for item in evidence}) != len(evidence):
            raise ValueError("court evidence must be unique and canonically ordered")
        return self

    @property
    def content_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def verify_validation_court_result(
    request: ValidationCourtRequest,
    admission: ValidationCourtAdmission,
    result: ValidationCourtResult,
) -> dict[str, object]:
    """Verify exact cross-object binding without interpreting domain statistics."""

    if admission.request_sha256 != request.content_hash:
        raise ValueError("validation-court admission is not bound to request")
    if (
        admission.work_key != request.work_key
        or admission.active_settlement_refs != request.active_settlement_refs
        or admission.method_id != request.method_id
        or admission.method_registration_sha256 != request.method_registration_sha256
        or admission.method_admission_sha256 != request.method_admission_sha256
    ):
        raise ValueError("validation-court admission identity drifted")
    if (
        result.request_sha256 != request.content_hash
        or result.admission_sha256 != admission.content_hash
        or result.work_key != request.work_key
        or result.active_settlement_refs != request.active_settlement_refs
    ):
        raise ValueError("validation-court result is not bound to request and admission")
    controls = tuple(item.control_kind for item in result.negative_controls)
    if controls != request.negative_control_kinds or not all(
        item.passed for item in result.negative_controls
    ):
        raise ValueError("validation-court negative controls are incomplete or failed")
    core: dict[str, object] = {
        "schema_version": "xinao.validation_court_result_verification.v1",
        "verified": True,
        "request_sha256": request.content_hash,
        "admission_sha256": admission.content_hash,
        "result_sha256": result.content_hash,
        "work_key": request.work_key,
        "active_settlement_refs": list(request.active_settlement_refs),
        "verdict": result.verdict,
        "negative_control_count": len(controls),
    }
    return {**core, "content_sha256": canonical_sha256(core)}


__all__ = [
    "COURT_ADMISSION_INVARIANTS",
    "CourtArtifactBinding",
    "CourtFeatureObservation",
    "CourtNegativeControlEvidence",
    "CourtWalkForwardFold",
    "ValidationCourtAdmission",
    "ValidationCourtRequest",
    "ValidationCourtResult",
    "verify_validation_court_result",
]
