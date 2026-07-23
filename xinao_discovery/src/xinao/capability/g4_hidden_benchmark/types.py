"""Immutable in-memory object shapes for the hidden-benchmark generator."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from xinao.canonical import canonical_sha256

from .constants import (
    GENERATOR_ID,
    GENERATOR_PROFILE_ID,
    HASH_PROFILE,
    NON_CLAIMS,
    SCHEMA_VERSION,
)


def freeze_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Deep-freeze a JSON-like mapping tree into MappingProxyType / tuples."""

    def _freeze(value: Any) -> Any:
        if isinstance(value, Mapping):
            return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
        if isinstance(value, list):
            return tuple(_freeze(v) for v in value)
        if isinstance(value, tuple):
            return tuple(_freeze(v) for v in value)
        return value

    return MappingProxyType({str(k): _freeze(v) for k, v in data.items()})


def unfreeze(value: Any) -> Any:
    """Return a plain JSON-like structure for hashing/serialization helpers."""
    if isinstance(value, Mapping):
        return {k: unfreeze(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [unfreeze(v) for v in value]
    if isinstance(value, list):
        return [unfreeze(v) for v in value]
    return value


@dataclass(frozen=True, slots=True)
class PublicCaseView:
    public_case_id: str
    public_instructions: str
    task_input: Mapping[str, Any]
    commitment_sha256: str

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "public_case_id": self.public_case_id,
            "public_instructions": self.public_instructions,
            "task_input": unfreeze(self.task_input),
            "commitment_sha256": self.commitment_sha256,
        }


@dataclass(frozen=True, slots=True)
class PrivateCaseRecord:
    public_case_id: str
    family_id: str
    split: str
    case_index: int
    public_instructions: str
    task_input: Mapping[str, Any]
    hidden_parameters: Mapping[str, Any]
    truth: Mapping[str, Any]
    expected_disposition: str
    scoring_policy_id: str
    commitment_sha256: str

    def commitment_material(self) -> dict[str, Any]:
        return {
            "public_case_id": self.public_case_id,
            "public_instructions": self.public_instructions,
            "task_input": unfreeze(self.task_input),
            "family_id": self.family_id,
            "split": self.split,
            "case_index": self.case_index,
            "hidden_parameters": unfreeze(self.hidden_parameters),
            "truth": unfreeze(self.truth),
            "expected_disposition": self.expected_disposition,
            "scoring_policy_id": self.scoring_policy_id,
            "hash_profile": HASH_PROFILE,
        }

    def as_private_dict(self) -> dict[str, Any]:
        return {
            "public_case_id": self.public_case_id,
            "family_id": self.family_id,
            "split": self.split,
            "case_index": self.case_index,
            "public_instructions": self.public_instructions,
            "task_input": unfreeze(self.task_input),
            "hidden_parameters": unfreeze(self.hidden_parameters),
            "truth": unfreeze(self.truth),
            "expected_disposition": self.expected_disposition,
            "scoring_policy_id": self.scoring_policy_id,
            "commitment_sha256": self.commitment_sha256,
        }

    def public_view(self) -> PublicCaseView:
        return PublicCaseView(
            public_case_id=self.public_case_id,
            public_instructions=self.public_instructions,
            task_input=self.task_input,
            commitment_sha256=self.commitment_sha256,
        )


def recompute_commitment(record: PrivateCaseRecord) -> str:
    return canonical_sha256(record.commitment_material())


def verify_commitment(record: PrivateCaseRecord) -> bool:
    return recompute_commitment(record) == record.commitment_sha256


def public_manifest_material(
    *,
    suite_label: str,
    cases: Sequence[PublicCaseView],
    generator_artifact_sha256: str,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "suite_label": suite_label,
        "case_count": len(cases),
        "cases": [case.as_public_dict() for case in cases],
        "generator_artifact_sha256": generator_artifact_sha256,
        "profile": unfreeze(profile),
        "schema_version": SCHEMA_VERSION,
    }


def suite_label_for(
    *, split: str, profile: Mapping[str, Any], generator_artifact_sha256: str
) -> str:
    """Derive the opaque suite label from its fixed public configuration."""
    digest = canonical_sha256(
        {
            "split": split,
            "profile": unfreeze(profile),
            "generator_artifact_sha256": generator_artifact_sha256,
            "schema_version": SCHEMA_VERSION,
        }
    )
    return f"suite_{digest[:32]}"


def private_bundle_material(
    *,
    suite_label: str,
    split: str,
    records: Sequence[PrivateCaseRecord],
    family_schedule: Sequence[str],
    generator_artifact_sha256: str,
) -> dict[str, Any]:
    return {
        "suite_label": suite_label,
        "split": split,
        "records": [record.as_private_dict() for record in records],
        "family_schedule": list(family_schedule),
        "generator_artifact_sha256": generator_artifact_sha256,
        "schema_version": SCHEMA_VERSION,
    }


def suite_identity_material(
    *,
    split: str,
    suite_label: str,
    public_manifest_sha256: str,
    private_bundle_sha256: str,
    generator_artifact_sha256: str,
    profile_sha256: str,
    family_inventory: Sequence[str],
) -> dict[str, Any]:
    return {
        "split": split,
        "suite_label": suite_label,
        "public_manifest_sha256": public_manifest_sha256,
        "private_bundle_sha256": private_bundle_sha256,
        "generator_artifact_sha256": generator_artifact_sha256,
        "profile_sha256": profile_sha256,
        "family_inventory": list(family_inventory),
        "schema_version": SCHEMA_VERSION,
    }


def non_collision_material(
    *, training_identity_sha256: str, heldout_identity_sha256: str
) -> dict[str, Any]:
    return {
        "training_identity_sha256": training_identity_sha256,
        "heldout_identity_sha256": heldout_identity_sha256,
        "distinct": training_identity_sha256 != heldout_identity_sha256,
        "schema_version": "xinao.g4.hidden_benchmark.non_collision.v1",
    }


@dataclass(frozen=True, slots=True)
class GeneratorProfile:
    profile_id: str = GENERATOR_PROFILE_ID
    cases_per_family: int = 1
    suite_version: str = "1"
    generator_id: str = GENERATOR_ID

    def __post_init__(self) -> None:
        if self.profile_id != GENERATOR_PROFILE_ID:
            raise ValueError("profile_id must equal the frozen generator profile")
        if self.generator_id != GENERATOR_ID:
            raise ValueError("generator_id must equal the executable generator identity")
        if not 1 <= self.cases_per_family <= 256:
            raise ValueError("cases_per_family must be between 1 and 256")
        if re.fullmatch(r"[1-9][0-9]{0,5}", self.suite_version) is None:
            raise ValueError("suite_version must be a positive decimal version")

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "cases_per_family": self.cases_per_family,
            "suite_version": self.suite_version,
            "generator_id": self.generator_id,
        }


@dataclass(frozen=True, slots=True)
class PublicManifest:
    suite_label: str
    split: str
    case_count: int
    cases: tuple[PublicCaseView, ...]
    public_manifest_sha256: str
    generator_artifact_sha256: str
    profile: Mapping[str, Any]

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "suite_label": self.suite_label,
            "case_count": self.case_count,
            "cases": [c.as_public_dict() for c in self.cases],
            "public_manifest_sha256": self.public_manifest_sha256,
            "generator_artifact_sha256": self.generator_artifact_sha256,
            "profile": unfreeze(self.profile),
            # split is intentionally omitted from public export surface
            "schema_version": SCHEMA_VERSION,
            **dict(NON_CLAIMS),
        }


@dataclass(frozen=True, slots=True)
class PrivateBundle:
    suite_label: str
    split: str
    records: tuple[PrivateCaseRecord, ...]
    private_bundle_sha256: str
    family_schedule: tuple[str, ...]
    generator_artifact_sha256: str

    def as_private_dict(self) -> dict[str, Any]:
        return {
            "suite_label": self.suite_label,
            "split": self.split,
            "records": [r.as_private_dict() for r in self.records],
            "private_bundle_sha256": self.private_bundle_sha256,
            "family_schedule": list(self.family_schedule),
            "generator_artifact_sha256": self.generator_artifact_sha256,
            "schema_version": SCHEMA_VERSION,
            **dict(NON_CLAIMS),
        }


@dataclass(frozen=True, slots=True)
class SuiteIdentity:
    split: str
    identity_sha256: str
    suite_label: str
    public_manifest_sha256: str
    private_bundle_sha256: str
    generator_artifact_sha256: str
    profile_sha256: str
    family_inventory: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "identity_sha256": self.identity_sha256,
            "suite_label": self.suite_label,
            "public_manifest_sha256": self.public_manifest_sha256,
            "private_bundle_sha256": self.private_bundle_sha256,
            "generator_artifact_sha256": self.generator_artifact_sha256,
            "profile_sha256": self.profile_sha256,
            "family_inventory": list(self.family_inventory),
        }


@dataclass(frozen=True, slots=True)
class NonCollisionAttestation:
    training_identity_sha256: str
    heldout_identity_sha256: str
    attestation_sha256: str
    distinct: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "training_identity_sha256": self.training_identity_sha256,
            "heldout_identity_sha256": self.heldout_identity_sha256,
            "attestation_sha256": self.attestation_sha256,
            "distinct": self.distinct,
            "schema_version": "xinao.g4.hidden_benchmark.non_collision.v1",
        }


@dataclass(frozen=True, slots=True)
class GeneratorArtifact:
    generator_id: str
    artifact_sha256: str
    source_files_sha256: str
    family_registry_sha256: str
    specification_sha256: str
    module_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "generator_id": self.generator_id,
            "artifact_sha256": self.artifact_sha256,
            "source_files_sha256": self.source_files_sha256,
            "family_registry_sha256": self.family_registry_sha256,
            "specification_sha256": self.specification_sha256,
            "module_count": self.module_count,
            "schema_version": "xinao.g4.hidden_benchmark.generator_artifact.v1",
            **dict(NON_CLAIMS),
        }


@dataclass(frozen=True, slots=True)
class FullFamilyGeneratorResult:
    """Top-level pure in-memory result for training + heldout full-family suites."""

    generator_artifact: GeneratorArtifact
    profile: GeneratorProfile
    training_public_manifest: PublicManifest
    training_private_bundle: PrivateBundle
    heldout_public_manifest: PublicManifest
    heldout_private_bundle: PrivateBundle
    training_identity: SuiteIdentity
    heldout_identity: SuiteIdentity
    non_collision_attestation: NonCollisionAttestation
    non_claims: Mapping[str, bool] = field(default_factory=lambda: freeze_mapping(NON_CLAIMS))

    def as_summary_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "generator_artifact": self.generator_artifact.as_dict(),
            "profile": self.profile.as_dict(),
            "training_identity": self.training_identity.as_dict(),
            "heldout_identity": self.heldout_identity.as_dict(),
            "non_collision_attestation": self.non_collision_attestation.as_dict(),
            "training_public_manifest_sha256": self.training_public_manifest.public_manifest_sha256,
            "heldout_public_manifest_sha256": self.heldout_public_manifest.public_manifest_sha256,
            "training_private_bundle_sha256": self.training_private_bundle.private_bundle_sha256,
            "heldout_private_bundle_sha256": self.heldout_private_bundle.private_bundle_sha256,
            "family_inventory": list(self.training_identity.family_inventory),
            **dict(NON_CLAIMS),
        }
