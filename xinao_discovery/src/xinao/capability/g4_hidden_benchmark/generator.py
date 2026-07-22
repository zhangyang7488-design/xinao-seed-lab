"""Deterministic full-family hidden-benchmark generator (pure producer port).

Side-effect constraints for generation:
- no filesystem writes
- no environment variable inspection
- no network
- no subprocess
- no provider/model calls
- does not import the event422 synthetic seam package

Artifact identity may read package source modules for content addressing only.
"""

from __future__ import annotations

import json
from typing import Any

from xinao.canonical import canonical_sha256

from .artifact import build_generator_artifact
from .constants import (
    FAMILY_IDS,
    MIN_SECRET_BYTES,
    NON_CLAIMS,
    SPLIT_HELDOUT,
    SPLIT_TRAINING,
)
from .families import build_family_world, registered_family_ids
from .public_safety import (
    contains_secret_material,
    scan_family_identity_leak,
    scan_forbidden_public_keys,
    scan_h03_public_hints,
    scan_h04_public_hints,
)
from .stream import DeterministicStream, opaque_case_id
from .types import (
    FullFamilyGeneratorResult,
    GeneratorProfile,
    NonCollisionAttestation,
    PrivateBundle,
    PrivateCaseRecord,
    PublicManifest,
    SuiteIdentity,
    freeze_mapping,
    non_collision_material,
    private_bundle_material,
    public_manifest_material,
    recompute_commitment,
    suite_identity_material,
    suite_label_for,
)


def _require_secret(secret: bytes, *, name: str) -> bytes:
    if not isinstance(secret, (bytes, bytearray)):
        raise TypeError(f"{name} must be bytes")
    secret_b = bytes(secret)
    if len(secret_b) < MIN_SECRET_BYTES:
        raise ValueError(f"{name} must be at least {MIN_SECRET_BYTES} bytes")
    return secret_b


def _build_case(
    *,
    secret: bytes,
    split: str,
    family_id: str,
    case_index: int,
    suite_label: str,
    ordinal: int,
) -> PrivateCaseRecord:
    label = f"{split}:{family_id}:{case_index:04d}"
    stream = DeterministicStream(secret, label=label)
    world = build_family_world(family_id, stream, split=split, case_index=case_index)

    # Provisional id material without final public_case_id; then bind opaque id.
    provisional = {
        "family_id": family_id,
        "split": split,
        "case_index": case_index,
        "public_instructions": world["public_instructions"],
        "task_input": world["task_input"],
        "hidden_parameters": world["hidden_parameters"],
        "truth": world["truth"],
        "expected_disposition": world["expected_disposition"],
        "scoring_policy_id": world["scoring_policy_id"],
    }
    material_digest = canonical_sha256(provisional)
    public_case_id = opaque_case_id(
        commitment_material_digest=material_digest,
        suite_label=suite_label,
        ordinal=ordinal,
    )

    record = PrivateCaseRecord(
        public_case_id=public_case_id,
        family_id=family_id,
        split=split,
        case_index=case_index,
        public_instructions=world["public_instructions"],
        task_input=freeze_mapping(world["task_input"]),
        hidden_parameters=freeze_mapping(world["hidden_parameters"]),
        truth=freeze_mapping(world["truth"]),
        expected_disposition=world["expected_disposition"],
        scoring_policy_id=world["scoring_policy_id"],
        commitment_sha256="",  # filled below
    )
    commitment = recompute_commitment(record)
    # dataclasses.replace would need commitment field set at construction
    return PrivateCaseRecord(
        public_case_id=record.public_case_id,
        family_id=record.family_id,
        split=record.split,
        case_index=record.case_index,
        public_instructions=record.public_instructions,
        task_input=record.task_input,
        hidden_parameters=record.hidden_parameters,
        truth=record.truth,
        expected_disposition=record.expected_disposition,
        scoring_policy_id=record.scoring_policy_id,
        commitment_sha256=commitment,
    )


def _require_public_boundary(
    manifest: PublicManifest,
    records: list[PrivateCaseRecord],
    *,
    secret: bytes,
    split: str,
) -> None:
    payload = manifest.as_public_dict()
    problems: list[str] = []
    problems.extend(f"forbidden_key:{path}" for path in scan_forbidden_public_keys(payload))
    problems.extend(f"family_hint:{hint}" for hint in scan_family_identity_leak(payload))
    problems.extend(f"secret_material:{hit}" for hit in contains_secret_material(payload, secret))
    if split.lower() in json.dumps(payload, sort_keys=True).lower():
        problems.append("split_role_disclosed")
    for record in records:
        public_case = record.public_view().as_public_dict()
        if record.family_id == "H03":
            problems.extend(f"h03_hint:{hint}" for hint in scan_h03_public_hints(public_case))
        if record.family_id == "H04":
            problems.extend(f"h04_hint:{hint}" for hint in scan_h04_public_hints(public_case))
    if problems:
        raise RuntimeError("public_boundary_violation:" + ",".join(sorted(set(problems))))


def generate_split_suite(
    *,
    secret: bytes,
    split: str,
    profile: GeneratorProfile,
    generator_artifact_sha256: str,
) -> tuple[PublicManifest, PrivateBundle, SuiteIdentity]:
    if split not in (SPLIT_TRAINING, SPLIT_HELDOUT):
        raise ValueError(f"unknown split: {split}")
    secret_b = _require_secret(secret, name="secret")
    if profile.cases_per_family < 1:
        raise ValueError("cases_per_family must be >= 1")

    suite_label = suite_label_for(
        split=split,
        profile=profile.as_dict(),
        generator_artifact_sha256=generator_artifact_sha256,
    )
    records: list[PrivateCaseRecord] = []
    ordinal = 0
    for family_id in FAMILY_IDS:
        for case_index in range(profile.cases_per_family):
            rec = _build_case(
                secret=secret_b,
                split=split,
                family_id=family_id,
                case_index=case_index,
                suite_label=suite_label,
                ordinal=ordinal,
            )
            records.append(rec)
            ordinal += 1

    public_cases = tuple(r.public_view() for r in records)
    profile_map = freeze_mapping(profile.as_dict())
    public_body = public_manifest_material(
        suite_label=suite_label,
        cases=public_cases,
        generator_artifact_sha256=generator_artifact_sha256,
        profile=profile_map,
    )
    public_manifest_sha256 = canonical_sha256(public_body)
    public_manifest = PublicManifest(
        suite_label=suite_label,
        split=split,
        case_count=len(public_cases),
        cases=public_cases,
        public_manifest_sha256=public_manifest_sha256,
        generator_artifact_sha256=generator_artifact_sha256,
        profile=profile_map,
    )
    _require_public_boundary(public_manifest, records, secret=secret_b, split=split)

    private_body = private_bundle_material(
        suite_label=suite_label,
        split=split,
        records=records,
        family_schedule=FAMILY_IDS,
        generator_artifact_sha256=generator_artifact_sha256,
    )
    private_bundle_sha256 = canonical_sha256(private_body)
    private_bundle = PrivateBundle(
        suite_label=suite_label,
        split=split,
        records=tuple(records),
        private_bundle_sha256=private_bundle_sha256,
        family_schedule=FAMILY_IDS,
        generator_artifact_sha256=generator_artifact_sha256,
    )

    profile_sha = canonical_sha256(profile.as_dict())
    identity_body = suite_identity_material(
        split=split,
        suite_label=suite_label,
        public_manifest_sha256=public_manifest_sha256,
        private_bundle_sha256=private_bundle_sha256,
        generator_artifact_sha256=generator_artifact_sha256,
        profile_sha256=profile_sha,
        family_inventory=FAMILY_IDS,
    )
    identity = SuiteIdentity(
        split=split,
        identity_sha256=canonical_sha256(identity_body),
        suite_label=suite_label,
        public_manifest_sha256=public_manifest_sha256,
        private_bundle_sha256=private_bundle_sha256,
        generator_artifact_sha256=generator_artifact_sha256,
        profile_sha256=profile_sha,
        family_inventory=FAMILY_IDS,
    )
    return public_manifest, private_bundle, identity


def generate_full_family_suites(
    *,
    training_secret: bytes,
    heldout_secret: bytes,
    profile: GeneratorProfile | None = None,
) -> FullFamilyGeneratorResult:
    """Generate training + heldout full-family suites in memory.

    ``training_secret`` and ``heldout_secret`` must each be >= 32 bytes and must differ.
    Secrets are never returned, logged, or embedded in public/private serializable
    fields of the result objects.
    """
    train = _require_secret(training_secret, name="training_secret")
    hold = _require_secret(heldout_secret, name="heldout_secret")
    if train == hold:
        raise ValueError("training_secret and heldout_secret must be distinct")

    prof = profile if profile is not None else GeneratorProfile()
    artifact = build_generator_artifact()

    train_pub, train_priv, train_id = generate_split_suite(
        secret=train,
        split=SPLIT_TRAINING,
        profile=prof,
        generator_artifact_sha256=artifact.artifact_sha256,
    )
    hold_pub, hold_priv, hold_id = generate_split_suite(
        secret=hold,
        split=SPLIT_HELDOUT,
        profile=prof,
        generator_artifact_sha256=artifact.artifact_sha256,
    )

    if train_id.identity_sha256 == hold_id.identity_sha256:
        raise RuntimeError("training and heldout identities collided unexpectedly")

    attestation_body = non_collision_material(
        training_identity_sha256=train_id.identity_sha256,
        heldout_identity_sha256=hold_id.identity_sha256,
    )
    attestation = NonCollisionAttestation(
        training_identity_sha256=train_id.identity_sha256,
        heldout_identity_sha256=hold_id.identity_sha256,
        attestation_sha256=canonical_sha256(attestation_body),
        distinct=True,
    )

    return FullFamilyGeneratorResult(
        generator_artifact=artifact,
        profile=prof,
        training_public_manifest=train_pub,
        training_private_bundle=train_priv,
        heldout_public_manifest=hold_pub,
        heldout_private_bundle=hold_priv,
        training_identity=train_id,
        heldout_identity=hold_id,
        non_collision_attestation=attestation,
        non_claims=freeze_mapping(NON_CLAIMS),
    )


def family_inventory() -> tuple[str, ...]:
    return registered_family_ids()


def result_canonical_hash(result: FullFamilyGeneratorResult) -> str:
    """Stable hash over identity-bearing summary (excludes raw secret material)."""
    return canonical_sha256(result.as_summary_dict())


def public_export(manifest: PublicManifest) -> dict[str, Any]:
    """Export exactly one opaque suite manifest for a subject-facing boundary."""
    return manifest.as_public_dict()
