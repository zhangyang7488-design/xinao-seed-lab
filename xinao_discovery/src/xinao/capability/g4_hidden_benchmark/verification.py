"""Fail-closed consumers for content-addressed hidden-benchmark objects."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from xinao.canonical import canonical_sha256

from .artifact import build_generator_artifact
from .constants import FAMILY_IDS, NON_CLAIMS, SPLIT_HELDOUT, SPLIT_TRAINING
from .public_safety import (
    scan_family_identity_leak,
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)
from .types import (
    FullFamilyGeneratorResult,
    PrivateBundle,
    PublicManifest,
    SuiteIdentity,
    non_collision_material,
    private_bundle_material,
    public_manifest_material,
    suite_identity_material,
    suite_label_for,
    unfreeze,
    verify_commitment,
)


def _expected_record_families(cases_per_family: int) -> list[str]:
    return [family for family in FAMILY_IDS for _ in range(cases_per_family)]


def _verify_public_manifest(
    manifest: PublicManifest,
    private: PrivateBundle,
    *,
    cases_per_family: int,
    expected_artifact_sha256: str,
    expected_profile: dict[str, Any],
    expected_suite_label: str,
) -> list[str]:
    reasons: list[str] = []
    expected_hash = canonical_sha256(
        public_manifest_material(
            suite_label=manifest.suite_label,
            cases=manifest.cases,
            generator_artifact_sha256=manifest.generator_artifact_sha256,
            profile=manifest.profile,
        )
    )
    if manifest.public_manifest_sha256 != expected_hash:
        reasons.append(f"{private.split}:public_manifest_hash_mismatch")
    if manifest.case_count != len(manifest.cases):
        reasons.append(f"{private.split}:public_case_count_mismatch")
    if manifest.case_count != len(FAMILY_IDS) * cases_per_family:
        reasons.append(f"{private.split}:public_family_cardinality_mismatch")
    public_ids = [case.public_case_id for case in manifest.cases]
    private_ids = [record.public_case_id for record in private.records]
    if len(set(public_ids)) != len(public_ids):
        reasons.append(f"{private.split}:duplicate_public_case_id")
    if public_ids != private_ids:
        reasons.append(f"{private.split}:public_private_case_coverage_mismatch")
    if unfreeze(manifest.profile) != expected_profile:
        reasons.append(f"{private.split}:public_profile_mismatch")
    if manifest.generator_artifact_sha256 != expected_artifact_sha256:
        reasons.append(f"{private.split}:generator_artifact_mismatch:public")
    if manifest.suite_label != expected_suite_label:
        reasons.append(f"{private.split}:suite_label_mismatch:public")
    public_payload = manifest.as_public_dict()
    if scan_forbidden_public_keys(public_payload):
        reasons.append(f"{private.split}:forbidden_public_key")
    if scan_family_identity_leak(public_payload):
        reasons.append(f"{private.split}:family_identity_public_leak")
    if private.split.lower() in str(public_payload).lower():
        reasons.append(f"{private.split}:split_role_public_leak")
    by_id = {record.public_case_id: record for record in private.records}
    if len(by_id) != len(private.records):
        reasons.append(f"{private.split}:duplicate_private_case_id")
    for case in manifest.cases:
        record = by_id.get(case.public_case_id)
        if record is None or case.as_public_dict() != record.public_view().as_public_dict():
            reasons.append(f"{private.split}:public_private_case_binding_mismatch")
            break
        if record.family_id == "H03" and scan_h03_public_hints(case.as_public_dict()):
            reasons.append(f"{private.split}:h03_public_hint")
        if record.family_id == "H04" and scan_h04_public_hints(case.as_public_dict()):
            reasons.append(f"{private.split}:h04_public_hint")
    return reasons


def _verify_private_bundle(
    bundle: PrivateBundle,
    *,
    cases_per_family: int,
    expected_artifact_sha256: str,
    expected_suite_label: str,
) -> list[str]:
    reasons: list[str] = []
    expected_hash = canonical_sha256(
        private_bundle_material(
            suite_label=bundle.suite_label,
            split=bundle.split,
            records=bundle.records,
            family_schedule=bundle.family_schedule,
            generator_artifact_sha256=bundle.generator_artifact_sha256,
        )
    )
    if bundle.private_bundle_sha256 != expected_hash:
        reasons.append(f"{bundle.split}:private_bundle_hash_mismatch")
    if bundle.family_schedule != FAMILY_IDS:
        reasons.append(f"{bundle.split}:family_schedule_mismatch")
    if bundle.generator_artifact_sha256 != expected_artifact_sha256:
        reasons.append(f"{bundle.split}:generator_artifact_mismatch:private")
    if bundle.suite_label != expected_suite_label:
        reasons.append(f"{bundle.split}:suite_label_mismatch:private")
    observed = [record.family_id for record in bundle.records]
    if observed != _expected_record_families(cases_per_family):
        reasons.append(f"{bundle.split}:record_family_inventory_mismatch")
    if any(record.split != bundle.split for record in bundle.records):
        reasons.append(f"{bundle.split}:record_split_mismatch")
    if any(not verify_commitment(record) for record in bundle.records):
        reasons.append(f"{bundle.split}:case_commitment_mismatch")
    return reasons


def _verify_suite_identity(
    identity: SuiteIdentity,
    public: PublicManifest,
    private: PrivateBundle,
    *,
    profile_sha256: str,
    expected_artifact_sha256: str,
    expected_suite_label: str,
) -> list[str]:
    reasons: list[str] = []
    expected_hash = canonical_sha256(
        suite_identity_material(
            split=identity.split,
            suite_label=identity.suite_label,
            public_manifest_sha256=identity.public_manifest_sha256,
            private_bundle_sha256=identity.private_bundle_sha256,
            generator_artifact_sha256=identity.generator_artifact_sha256,
            profile_sha256=identity.profile_sha256,
            family_inventory=identity.family_inventory,
        )
    )
    if identity.identity_sha256 != expected_hash:
        reasons.append(f"{identity.split}:suite_identity_hash_mismatch")
    if identity.generator_artifact_sha256 != expected_artifact_sha256:
        reasons.append(f"{identity.split}:generator_artifact_mismatch:identity")
    if identity.suite_label != expected_suite_label:
        reasons.append(f"{identity.split}:suite_label_mismatch:identity")
    expected_fields: Sequence[tuple[str, Any, Any]] = (
        ("suite_label", identity.suite_label, public.suite_label),
        ("suite_label_private", identity.suite_label, private.suite_label),
        ("public_manifest", identity.public_manifest_sha256, public.public_manifest_sha256),
        ("private_bundle", identity.private_bundle_sha256, private.private_bundle_sha256),
        ("generator_public", identity.generator_artifact_sha256, public.generator_artifact_sha256),
        (
            "generator_private",
            identity.generator_artifact_sha256,
            private.generator_artifact_sha256,
        ),
        ("profile", identity.profile_sha256, profile_sha256),
        ("split_private", identity.split, private.split),
        ("family_inventory", identity.family_inventory, FAMILY_IDS),
    )
    for field, observed, expected in expected_fields:
        if observed != expected:
            reasons.append(f"{identity.split}:suite_binding_mismatch:{field}")
    return reasons


def verify_full_family_result(result: FullFamilyGeneratorResult) -> dict[str, Any]:
    """Recompute every identity and cross-object binding before READY is possible."""
    reasons: list[str] = []
    current_artifact = build_generator_artifact()
    if result.generator_artifact != current_artifact:
        reasons.append("generator_artifact_not_current")
    if unfreeze(result.non_claims) != NON_CLAIMS:
        reasons.append("top_level_non_claims_mismatch")
    profile_sha256 = canonical_sha256(result.profile.as_dict())
    pairs = (
        (
            SPLIT_TRAINING,
            result.training_public_manifest,
            result.training_private_bundle,
            result.training_identity,
        ),
        (
            SPLIT_HELDOUT,
            result.heldout_public_manifest,
            result.heldout_private_bundle,
            result.heldout_identity,
        ),
    )
    for split, public, private, identity in pairs:
        expected_suite_label = suite_label_for(
            split=split,
            profile=result.profile.as_dict(),
            generator_artifact_sha256=current_artifact.artifact_sha256,
        )
        if (public.split, private.split, identity.split) != (split, split, split):
            reasons.append(f"{split}:top_level_split_binding_mismatch")
        reasons.extend(
            _verify_public_manifest(
                public,
                private,
                cases_per_family=result.profile.cases_per_family,
                expected_artifact_sha256=current_artifact.artifact_sha256,
                expected_profile=result.profile.as_dict(),
                expected_suite_label=expected_suite_label,
            )
        )
        reasons.extend(
            _verify_private_bundle(
                private,
                cases_per_family=result.profile.cases_per_family,
                expected_artifact_sha256=current_artifact.artifact_sha256,
                expected_suite_label=expected_suite_label,
            )
        )
        reasons.extend(
            _verify_suite_identity(
                identity,
                public,
                private,
                profile_sha256=profile_sha256,
                expected_artifact_sha256=current_artifact.artifact_sha256,
                expected_suite_label=expected_suite_label,
            )
        )
    attestation_material = non_collision_material(
        training_identity_sha256=result.training_identity.identity_sha256,
        heldout_identity_sha256=result.heldout_identity.identity_sha256,
    )
    attestation = result.non_collision_attestation
    if attestation.attestation_sha256 != canonical_sha256(attestation_material):
        reasons.append("non_collision_attestation_hash_mismatch")
    if (
        attestation.training_identity_sha256 != result.training_identity.identity_sha256
        or attestation.heldout_identity_sha256 != result.heldout_identity.identity_sha256
    ):
        reasons.append("non_collision_attestation_binding_mismatch")
    if attestation.distinct is not True or attestation_material["distinct"] is not True:
        reasons.append("training_heldout_identity_collision")
    return {
        "ok": not reasons,
        "reasons": sorted(set(reasons)),
        "verified_family_count": len(FAMILY_IDS) if not reasons else 0,
        "authority": False,
        "completion_claim_allowed": False,
    }


__all__ = ["verify_full_family_result"]
