"""Builders and validators for the fourteen required seam objects."""

from __future__ import annotations

from typing import Any

from . import SYNTHETIC_LABEL
from .canonical import canonical_json_sha256, identity_from_fields
from .security_model import scan_forbidden_public_payload

REQUIRED_OBJECTS = (
    "HiddenSuiteIdentityEnvelope",
    "GeneratorArtifactDescriptor",
    "SealedParameterCommitment",
    "SubjectPublicManifest",
    "SealedTruthVault",
    "EvaluatorBundle",
    "SubjectExecutionRouteDescriptor",
    "PromptfooSubjectAdapter",
    "ImmutableRunEnvelope",
    "RunIdempotencyRegistry",
    "ExposureLedger",
    "RotationRevocationRegistry",
    "HeldoutNonCollisionAttestation",
    "CalibrationContract",
)

H_SLOTS = [f"H{i:02d}" for i in range(1, 15)]
C_SLOTS = [f"C{i}" for i in range(0, 7)]

SUITE_HASH_PROFILE = "canonical-json-v1+sha256"
SUITE_HASH_PROFILES = [SUITE_HASH_PROFILE, "raw-bytes-sha256-v1"]
SUITE_NON_AUTHORITY_CONSTRAINTS = {
    "not_real_hidden_identity": True,
    "not_admission": True,
    "not_discovery": True,
    "not_rejection_evidence": True,
    "authority": False,
    "g4_closed": False,
    "g5_active": False,
}
SUITE_NON_AUTHORITY_FLAGS = {
    "not_real_hidden_identity": True,
    "not_admission": True,
    "not_discovery": True,
    "not_rejection_evidence": True,
    "authority": False,
    "g4_closed": False,
    "g5_active": False,
}

RUN_ENVELOPE_IDENTITY_FIELDS = (
    "run_id",
    "attempt_id",
    "suite_identity_sha256",
    "route_identity_sha256",
    "manifest_identity_sha256",
    "raw_outputs",
    "telemetry",
    "terminal_status",
    "scoring_enabled",
    "hidden_cases_consumed",
    "promoted_to_pass",
    "immutable",
    "synthetic_only",
    "label",
    "not_admission",
    "not_capability_result",
    "authority",
    "g4_closed",
    "g5_active",
)

# Every identity-bearing field bound into suite_identity_sha256 (excludes suite_identity itself)
SUITE_IDENTITY_FIELDS = (
    "suite_version",
    "public_suite_label",
    "schedule_slots",
    "synthetic_salt",
    "generator_descriptor_identity_sha256",
    "generator_artifact_bytes_sha256",
    "evaluator_bundle_identity_sha256",
    "evaluator_code_hash",
    "scoring_calibration_contract_identity_sha256",
    "public_manifest_blueprint_commitment",
    "heldout_identity_sha256",
    "training_identity_sha256",
    "non_collision_attestation_identity_sha256",
    "exposure_ledger_initial_head_contract",
    "exposure_subject_identity_sha256",
    "lifecycle_status",
    "creator_identity",
    "created_at_source",
    "rotation_registry_identity_sha256",
    "rotation_registry_head_sha256",
    "revocation_status",
    "parent_suite_identity_sha256",
    "subject_route_identity_sha256",
    "run_envelope_identity_schema_version",
    "hash_profiles",
    "synthetic_only",
    "non_authority_constraints",
    "rotated_from",
    "canonical_suite_commitment",
    "realized_manifest_binding",
    "exposure_ledger_sealed_head_contract",
    "hash_profile",
    "label",
    "not_real_hidden_identity",
    "not_admission",
    "not_discovery",
    "not_rejection_evidence",
    "authority",
    "g4_closed",
    "g5_active",
)

# Every declared identity field must change suite_identity_sha256 when mutated.
SUITE_IDENTITY_MUTATION_FIELDS = SUITE_IDENTITY_FIELDS

# Fields that form the acyclic canonical_suite_commitment body (no suite_identity, no sealed-head post-facts that cycle)
SUITE_CANONICAL_COMMITMENT_FIELDS = (
    "suite_version",
    "public_suite_label",
    "schedule_slots",
    "synthetic_salt",
    "generator_descriptor_identity_sha256",
    "generator_artifact_bytes_sha256",
    "evaluator_bundle_identity_sha256",
    "evaluator_code_hash",
    "scoring_calibration_contract_identity_sha256",
    "public_manifest_blueprint_commitment",
    "heldout_identity_sha256",
    "training_identity_sha256",
    "non_collision_attestation_identity_sha256",
    "exposure_ledger_initial_head_contract",
    "lifecycle_status",
    "creator_identity",
    "created_at_source",
    "rotation_registry_identity_sha256",
    "rotation_registry_head_sha256",
    "revocation_status",
    "parent_suite_identity_sha256",
    "subject_route_identity_sha256",
    "run_envelope_identity_schema_version",
    "hash_profiles",
    "synthetic_only",
    "non_authority_constraints",
    "rotated_from",
)


def recompute_canonical_suite_commitment(envelope: dict[str, Any]) -> str:
    body = {k: envelope.get(k) for k in SUITE_CANONICAL_COMMITMENT_FIELDS}
    return canonical_json_sha256(body)


def build_hidden_suite_canonical_fields(
    *,
    public_suite_label: str,
    schedule_slots: list[str],
    synthetic_salt: str,
    suite_version: str = "1",
    generator_descriptor_identity_sha256: str = "",
    generator_artifact_bytes_sha256: str = "",
    evaluator_bundle_identity_sha256: str = "",
    evaluator_code_hash: str = "",
    scoring_calibration_contract_identity_sha256: str = "",
    public_manifest_blueprint_commitment: str = "",
    heldout_identity_sha256: str = "",
    training_identity_sha256: str = "",
    non_collision_attestation_identity_sha256: str = "",
    exposure_ledger_initial_head_contract: str = "0" * 64,
    lifecycle_status: str = "active",
    creator_identity: str = "syn_seam_author_v1",
    created_at_source: str = "synthetic_deterministic_clock_v1",
    rotation_registry_identity_sha256: str = "",
    rotation_registry_head_sha256: str = "0" * 64,
    revocation_status: str = "not_revoked",
    parent_suite_identity_sha256: str | None = None,
    subject_route_identity_sha256: str = "",
    run_envelope_identity_schema_version: str = "xinao.g4.hidden_capability_seam.immutable_run_envelope.v1",
    hash_profiles: list[str] | None = None,
    rotated_from: str | None = None,
) -> dict[str, Any]:
    """Return the acyclic suite core used before exposure-ledger sealing."""
    profiles = list(SUITE_HASH_PROFILES if hash_profiles is None else hash_profiles)
    return {
        "suite_version": suite_version,
        "public_suite_label": public_suite_label,
        "schedule_slots": list(schedule_slots),
        "synthetic_salt": synthetic_salt,
        "generator_descriptor_identity_sha256": generator_descriptor_identity_sha256,
        "generator_artifact_bytes_sha256": generator_artifact_bytes_sha256,
        "evaluator_bundle_identity_sha256": evaluator_bundle_identity_sha256,
        "evaluator_code_hash": evaluator_code_hash,
        "scoring_calibration_contract_identity_sha256": scoring_calibration_contract_identity_sha256,
        "public_manifest_blueprint_commitment": public_manifest_blueprint_commitment,
        "heldout_identity_sha256": heldout_identity_sha256,
        "training_identity_sha256": training_identity_sha256,
        "non_collision_attestation_identity_sha256": non_collision_attestation_identity_sha256,
        "exposure_ledger_initial_head_contract": exposure_ledger_initial_head_contract,
        "lifecycle_status": lifecycle_status,
        "creator_identity": creator_identity,
        "created_at_source": created_at_source,
        "rotation_registry_identity_sha256": rotation_registry_identity_sha256,
        "rotation_registry_head_sha256": rotation_registry_head_sha256,
        "revocation_status": revocation_status,
        "parent_suite_identity_sha256": parent_suite_identity_sha256,
        "subject_route_identity_sha256": subject_route_identity_sha256,
        "run_envelope_identity_schema_version": run_envelope_identity_schema_version,
        "hash_profiles": profiles,
        "synthetic_only": True,
        "non_authority_constraints": dict(SUITE_NON_AUTHORITY_CONSTRAINTS),
        "rotated_from": rotated_from,
    }


def derive_exposure_subject_identity_sha256(
    *, canonical_suite_commitment: str, realized_manifest_binding: str
) -> str:
    """Acyclic key used by exposure records before the final suite identity exists."""
    return identity_from_fields(
        "HiddenSuiteExposureSubjectIdentity",
        {
            "canonical_suite_commitment": canonical_suite_commitment,
            "realized_manifest_binding": realized_manifest_binding,
            "synthetic_only": True,
            "authority": False,
        },
    )["identity_sha256"]


def hidden_suite_registration_commitment_inputs(envelope: dict[str, Any]) -> dict[str, Any]:
    """Only admitted registration metadata for a full hidden-suite envelope."""
    return {
        "canonical_suite_commitment": envelope.get("canonical_suite_commitment"),
        "suite_version": envelope.get("suite_version"),
    }


def recompute_suite_identity_sha256(envelope: dict[str, Any]) -> str:
    fields = {k: envelope.get(k) for k in SUITE_IDENTITY_FIELDS}
    return identity_from_fields("HiddenSuiteIdentityEnvelope", fields)["identity_sha256"]


def expected_public_case_ids() -> list[str]:
    """Synthetic schedule public case IDs for H01-H14 and C0-C6."""
    return [f"syn-{slot}-001" for slot in (H_SLOTS + C_SLOTS)]


def expected_case_set_identity_sha256() -> str:
    return identity_from_fields(
        "ExpectedPublicCaseSet",
        {
            "public_case_ids": expected_public_case_ids(),
            "schedule_slots": H_SLOTS + C_SLOTS,
            "count": 21,
            "synthetic_only": True,
        },
    )["identity_sha256"]


def _snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


SCHEMA_VERSIONS = {
    name: f"xinao.g4.hidden_capability_seam.{_snake(name)}.v1" for name in REQUIRED_OBJECTS
}


def build_public_manifest_blueprint(
    *,
    public_cases: list[dict[str, Any]],
    route_identity_sha256: str,
    adapter_identity_sha256: str,
) -> dict[str, Any]:
    """Acyclic blueprint (no suite_identity) for manifest commitment."""
    cases = [
        {
            "public_case_id": c["public_case_id"],
            "public_prompt": c["public_prompt"],
            "commitment_sha256": c["commitment_sha256"],
            "schedule_slot": c["schedule_slot"],
            "synthetic": True,
        }
        for c in public_cases
    ]
    blueprint = {
        "public_cases": cases,
        "route_identity_sha256": route_identity_sha256,
        "adapter_identity_sha256": adapter_identity_sha256,
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "cache_enabled": False,
    }
    return {
        "blueprint": blueprint,
        "public_manifest_blueprint_commitment": canonical_json_sha256(blueprint),
    }


def build_hidden_suite_identity_envelope(
    *,
    public_suite_label: str,
    schedule_slots: list[str],
    synthetic_salt: str,
    suite_version: str = "1",
    generator_descriptor_identity_sha256: str = "",
    generator_artifact_bytes_sha256: str = "",
    evaluator_bundle_identity_sha256: str = "",
    evaluator_code_hash: str = "",
    scoring_calibration_contract_identity_sha256: str = "",
    public_manifest_blueprint_commitment: str = "",
    realized_manifest_binding: str = "",
    heldout_identity_sha256: str = "",
    training_identity_sha256: str = "",
    non_collision_attestation_identity_sha256: str = "",
    exposure_ledger_initial_head_contract: str = "0" * 64,
    exposure_subject_identity_sha256: str = "",
    exposure_ledger_sealed_head_contract: str = "0" * 64,
    lifecycle_status: str = "active",
    creator_identity: str = "syn_seam_author_v1",
    created_at_source: str = "synthetic_deterministic_clock_v1",
    rotation_registry_identity_sha256: str = "",
    rotation_registry_head_sha256: str = "0" * 64,
    revocation_status: str = "not_revoked",
    parent_suite_identity_sha256: str | None = None,
    subject_route_identity_sha256: str = "",
    run_envelope_identity_schema_version: str = "xinao.g4.hidden_capability_seam.immutable_run_envelope.v1",
    hash_profiles: list[str] | None = None,
    rotated_from: str | None = None,
) -> dict[str, Any]:
    """Full identity envelope: all identity-bearing facts, acyclic construction."""
    canonical_suite_commitment_body = build_hidden_suite_canonical_fields(
        public_suite_label=public_suite_label,
        schedule_slots=schedule_slots,
        synthetic_salt=synthetic_salt,
        suite_version=suite_version,
        generator_descriptor_identity_sha256=generator_descriptor_identity_sha256,
        generator_artifact_bytes_sha256=generator_artifact_bytes_sha256,
        evaluator_bundle_identity_sha256=evaluator_bundle_identity_sha256,
        evaluator_code_hash=evaluator_code_hash,
        scoring_calibration_contract_identity_sha256=scoring_calibration_contract_identity_sha256,
        public_manifest_blueprint_commitment=public_manifest_blueprint_commitment,
        heldout_identity_sha256=heldout_identity_sha256,
        training_identity_sha256=training_identity_sha256,
        non_collision_attestation_identity_sha256=non_collision_attestation_identity_sha256,
        exposure_ledger_initial_head_contract=exposure_ledger_initial_head_contract,
        lifecycle_status=lifecycle_status,
        creator_identity=creator_identity,
        created_at_source=created_at_source,
        rotation_registry_identity_sha256=rotation_registry_identity_sha256,
        rotation_registry_head_sha256=rotation_registry_head_sha256,
        revocation_status=revocation_status,
        parent_suite_identity_sha256=parent_suite_identity_sha256,
        subject_route_identity_sha256=subject_route_identity_sha256,
        run_envelope_identity_schema_version=run_envelope_identity_schema_version,
        hash_profiles=hash_profiles,
        rotated_from=rotated_from,
    )
    canonical_suite_commitment = canonical_json_sha256(canonical_suite_commitment_body)
    expected_exposure_subject = derive_exposure_subject_identity_sha256(
        canonical_suite_commitment=canonical_suite_commitment,
        realized_manifest_binding=realized_manifest_binding,
    )
    exposure_subject_identity_sha256 = exposure_subject_identity_sha256 or expected_exposure_subject

    fields = {
        **canonical_suite_commitment_body,
        "canonical_suite_commitment": canonical_suite_commitment,
        "realized_manifest_binding": realized_manifest_binding,
        "exposure_subject_identity_sha256": exposure_subject_identity_sha256,
        "exposure_ledger_sealed_head_contract": exposure_ledger_sealed_head_contract,
        "hash_profile": SUITE_HASH_PROFILE,
        "label": SYNTHETIC_LABEL,
        **SUITE_NON_AUTHORITY_FLAGS,
    }
    ident = identity_from_fields("HiddenSuiteIdentityEnvelope", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["HiddenSuiteIdentityEnvelope"],
        "object": "HiddenSuiteIdentityEnvelope",
        **fields,
        "suite_identity_sha256": ident["identity_sha256"],
    }


def mutate_suite_field(envelope: dict[str, Any], field: str, new_value: Any) -> dict[str, Any]:
    """Rebuild envelope with one field changed; used by mutation tests."""
    kwargs = {
        "public_suite_label": envelope["public_suite_label"],
        "schedule_slots": list(envelope["schedule_slots"]),
        "synthetic_salt": envelope.get("synthetic_salt", ""),
        "suite_version": envelope.get("suite_version", "1"),
        "generator_descriptor_identity_sha256": envelope.get(
            "generator_descriptor_identity_sha256", ""
        ),
        "generator_artifact_bytes_sha256": envelope.get("generator_artifact_bytes_sha256", ""),
        "evaluator_bundle_identity_sha256": envelope.get("evaluator_bundle_identity_sha256", ""),
        "evaluator_code_hash": envelope.get("evaluator_code_hash", ""),
        "scoring_calibration_contract_identity_sha256": envelope.get(
            "scoring_calibration_contract_identity_sha256", ""
        ),
        "public_manifest_blueprint_commitment": envelope.get(
            "public_manifest_blueprint_commitment", ""
        ),
        "realized_manifest_binding": envelope.get("realized_manifest_binding", ""),
        "heldout_identity_sha256": envelope.get("heldout_identity_sha256", ""),
        "training_identity_sha256": envelope.get("training_identity_sha256", ""),
        "non_collision_attestation_identity_sha256": envelope.get(
            "non_collision_attestation_identity_sha256", ""
        ),
        "exposure_ledger_initial_head_contract": envelope.get(
            "exposure_ledger_initial_head_contract", "0" * 64
        ),
        "exposure_subject_identity_sha256": envelope.get("exposure_subject_identity_sha256", ""),
        "exposure_ledger_sealed_head_contract": envelope.get(
            "exposure_ledger_sealed_head_contract", "0" * 64
        ),
        "lifecycle_status": envelope.get("lifecycle_status", "active"),
        "creator_identity": envelope.get("creator_identity", "syn_seam_author_v1"),
        "created_at_source": envelope.get("created_at_source", "synthetic_deterministic_clock_v1"),
        "rotation_registry_identity_sha256": envelope.get("rotation_registry_identity_sha256", ""),
        "rotation_registry_head_sha256": envelope.get("rotation_registry_head_sha256", "0" * 64),
        "revocation_status": envelope.get("revocation_status", "not_revoked"),
        "parent_suite_identity_sha256": envelope.get("parent_suite_identity_sha256"),
        "subject_route_identity_sha256": envelope.get("subject_route_identity_sha256", ""),
        "run_envelope_identity_schema_version": envelope.get(
            "run_envelope_identity_schema_version",
            "xinao.g4.hidden_capability_seam.immutable_run_envelope.v1",
        ),
        "hash_profiles": list(envelope.get("hash_profiles") or []),
        "rotated_from": envelope.get("rotated_from"),
    }
    if field == "canonical_suite_commitment":
        # Force drift via synthetic_salt which feeds commitment
        kwargs["synthetic_salt"] = str(kwargs["synthetic_salt"]) + "|mut"
    elif field == "synthetic_only":
        # synthetic_only is fixed True in builder; mutate via salt proxy + non_authority
        kwargs["synthetic_salt"] = str(kwargs["synthetic_salt"]) + "|syn_flag"
    elif field == "non_authority_constraints":
        kwargs["creator_identity"] = str(kwargs["creator_identity"]) + "|na"
    elif field in kwargs:
        kwargs[field] = new_value
    else:
        kwargs["synthetic_salt"] = str(kwargs["synthetic_salt"]) + f"|{field}"
    return build_hidden_suite_identity_envelope(**kwargs)


def build_generator_artifact_descriptor(
    *,
    generator_id: str,
    public_interface_version: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    fields = {
        "generator_id": generator_id,
        "public_interface_version": public_interface_version,
        "artifact_sha256": artifact_sha256,
        "synthetic_only": True,
        "final_semantics_exposed_to_subject": False,
    }
    ident = identity_from_fields("GeneratorArtifactDescriptor", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["GeneratorArtifactDescriptor"],
        "object": "GeneratorArtifactDescriptor",
        "generator_id": generator_id,
        "public_interface_version": public_interface_version,
        "artifact_sha256": artifact_sha256,
        "descriptor_identity_sha256": ident["identity_sha256"],
        "synthetic_only": True,
        "note": "descriptor only; final generator semantics not in subject path",
        "authority": False,
    }


def build_subject_public_manifest(
    *,
    suite_identity_sha256: str,
    public_cases: list[dict[str, Any]],
    route_identity_sha256: str,
    adapter_identity_sha256: str,
    public_manifest_blueprint_commitment: str | None = None,
) -> dict[str, Any]:
    cases = []
    for c in public_cases:
        cases.append(
            {
                "public_case_id": c["public_case_id"],
                "public_prompt": c["public_prompt"],
                "commitment_sha256": c["commitment_sha256"],
                "schedule_slot": c["schedule_slot"],
                "synthetic": True,
                "label": SYNTHETIC_LABEL,
            }
        )
    bp = public_manifest_blueprint_commitment
    if not bp:
        bp = build_public_manifest_blueprint(
            public_cases=public_cases,
            route_identity_sha256=route_identity_sha256,
            adapter_identity_sha256=adapter_identity_sha256,
        )["public_manifest_blueprint_commitment"]
    realized = canonical_json_sha256(
        {
            "suite_identity_sha256": suite_identity_sha256,
            "public_manifest_blueprint_commitment": bp,
        }
    )
    fields = {
        "suite_identity_sha256": suite_identity_sha256,
        "public_cases": cases,
        "route_identity_sha256": route_identity_sha256,
        "adapter_identity_sha256": adapter_identity_sha256,
        "public_manifest_blueprint_commitment": bp,
        "realized_manifest_binding": realized,
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
    }
    ident = identity_from_fields("SubjectPublicManifest", fields)
    manifest = {
        "schema_version": SCHEMA_VERSIONS["SubjectPublicManifest"],
        "object": "SubjectPublicManifest",
        "suite_identity_sha256": suite_identity_sha256,
        "public_cases": cases,
        "route_identity_sha256": route_identity_sha256,
        "adapter_identity_sha256": adapter_identity_sha256,
        "public_manifest_blueprint_commitment": bp,
        "realized_manifest_binding": realized,
        "manifest_identity_sha256": ident["identity_sha256"],
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "cache_enabled": False,
        "real_provider_calls": False,
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
        "not_admission": True,
        "not_discovery": True,
        "not_rejection_evidence": True,
        "authority": False,
    }
    leaks = scan_forbidden_public_payload(manifest)
    if leaks:
        raise ValueError(f"public_manifest_forbidden_keys:{leaks}")
    return manifest


def build_evaluator_bundle(
    *,
    evaluator_id: str,
    state_root: str,
    code_identity_sha256: str,
) -> dict[str, Any]:
    fields = {
        "evaluator_id": evaluator_id,
        "state_root": state_root,
        "code_identity_sha256": code_identity_sha256,
        "separate_process_required": True,
        "scoring_enabled_for_real_hidden": False,
        "synthetic_isolation_check_only": True,
    }
    ident = identity_from_fields("EvaluatorBundle", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["EvaluatorBundle"],
        "object": "EvaluatorBundle",
        "evaluator_id": evaluator_id,
        "state_root": state_root,
        "code_identity_sha256": code_identity_sha256,
        "bundle_identity_sha256": ident["identity_sha256"],
        "separate_process_required": True,
        "synthetic_isolation_check_only": True,
        "not_real_scoring": True,
        "authority": False,
    }


def build_route_descriptor(
    *,
    route_label: str,
    promptfoo_version: str,
    offline: bool,
    cache_enabled: bool,
    network_enabled: bool,
    execution_boundary: str = "docker_create_inspect_start",
    image_digest: str = ("sha256:6b9076def7ebe27c64d72432bd27e5019a348c92ccb47a71b774caa5b61c04ca"),
) -> dict[str, Any]:
    fields = {
        "route_label": route_label,
        "promptfoo_version": promptfoo_version,
        "offline": offline,
        "cache_enabled": cache_enabled,
        "network_enabled": network_enabled,
        "subject_kind": "offline_deterministic_synthetic",
        "scoring_enabled": False,
        "production_credentials": False,
        "execution_boundary": execution_boundary,
        "image_digest": image_digest,
    }
    ident = identity_from_fields("SubjectExecutionRouteDescriptor", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["SubjectExecutionRouteDescriptor"],
        "object": "SubjectExecutionRouteDescriptor",
        "route_label": route_label,
        "promptfoo_version": promptfoo_version,
        "offline": offline,
        "cache_enabled": cache_enabled,
        "network_enabled": network_enabled,
        "subject_kind": "offline_deterministic_synthetic",
        "scoring_enabled": False,
        "production_credentials": False,
        "execution_boundary": execution_boundary,
        "image_digest": image_digest,
        "route_identity_sha256": ident["identity_sha256"],
        "synthetic_only": True,
        "authority": False,
    }


def build_promptfoo_adapter_descriptor(
    *,
    adapter_module: str,
    adapter_source_sha256: str,
) -> dict[str, Any]:
    fields = {
        "adapter_module": adapter_module,
        "adapter_source_sha256": adapter_source_sha256,
        "vault_access": False,
        "scorer_enabled": False,
    }
    ident = identity_from_fields("PromptfooSubjectAdapter", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["PromptfooSubjectAdapter"],
        "object": "PromptfooSubjectAdapter",
        "adapter_module": adapter_module,
        "adapter_source_sha256": adapter_source_sha256,
        "adapter_identity_sha256": ident["identity_sha256"],
        "vault_access": False,
        "scorer_enabled": False,
        "synthetic_only": True,
        "authority": False,
    }


def build_immutable_run_envelope(
    *,
    run_id: str,
    attempt_id: str,
    suite_identity_sha256: str,
    route_identity_sha256: str,
    manifest_identity_sha256: str,
    raw_outputs: list[dict[str, Any]],
    telemetry: dict[str, Any],
    terminal_status: str,
    promoted_to_pass: bool = False,
) -> dict[str, Any]:
    fields = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "suite_identity_sha256": suite_identity_sha256,
        "route_identity_sha256": route_identity_sha256,
        "manifest_identity_sha256": manifest_identity_sha256,
        "raw_outputs": raw_outputs,
        "telemetry": telemetry,
        "terminal_status": terminal_status,
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "promoted_to_pass": promoted_to_pass,
        "immutable": True,
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
        "not_admission": True,
        "not_capability_result": True,
        "authority": False,
        "g4_closed": False,
        "g5_active": False,
    }
    ident = identity_from_fields("ImmutableRunEnvelope", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["ImmutableRunEnvelope"],
        "object": "ImmutableRunEnvelope",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "suite_identity_sha256": suite_identity_sha256,
        "route_identity_sha256": route_identity_sha256,
        "manifest_identity_sha256": manifest_identity_sha256,
        "raw_outputs": raw_outputs,
        "telemetry": telemetry,
        "terminal_status": terminal_status,
        "envelope_identity_sha256": ident["identity_sha256"],
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "promoted_to_pass": promoted_to_pass,
        "immutable": True,
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
        "not_admission": True,
        "not_capability_result": True,
        "authority": False,
        "g4_closed": False,
        "g5_active": False,
    }


def build_heldout_attestation(
    *,
    training_identity_sha256: str,
    heldout_identity_sha256: str,
) -> dict[str, Any]:
    collision = training_identity_sha256 == heldout_identity_sha256
    fields = {
        "training_identity_sha256": training_identity_sha256,
        "heldout_identity_sha256": heldout_identity_sha256,
        "collision": collision,
    }
    ident = identity_from_fields("HeldoutNonCollisionAttestation", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["HeldoutNonCollisionAttestation"],
        "object": "HeldoutNonCollisionAttestation",
        "training_identity_sha256": training_identity_sha256,
        "heldout_identity_sha256": heldout_identity_sha256,
        "collision": collision,
        "ok": not collision,
        "reason": "training_heldout_collision" if collision else None,
        "attestation_identity_sha256": ident["identity_sha256"],
        "synthetic_only": True,
        "not_real_heldout": True,
        "authority": False,
    }


def build_calibration_contract_shape() -> dict[str, Any]:
    """Shape only; does not run calibration package."""
    fields = {
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "bounds": {
            "max_requests": 0,
            "max_input_tokens": 0,
            "max_output_tokens": 0,
            "max_total_tokens": 0,
            "max_wall_clock_ms": 0,
            "max_concurrency": 0,
            "max_retries_per_request": 0,
            "max_total_retries": 0,
            "max_provider_errors": 0,
            "max_rate_limits": 0,
            "max_unlogged_requests": 0,
            "cost_when_trustworthy": None,
            "vault_abort": True,
            "truth_abort": True,
            "log_abort": True,
            "route_abort": True,
            "quota_abort": True,
            "kill_grace_ms": 0,
            "inflight_disposition": "abort_fail_closed",
        },
    }
    ident = identity_from_fields("CalibrationContract", fields)
    return {
        "schema_version": SCHEMA_VERSIONS["CalibrationContract"],
        "object": "CalibrationContract",
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "calibration_executed": False,
        "bounds": fields["bounds"],
        "contract_identity_sha256": ident["identity_sha256"],
        "note": "shape_only_not_calibration_package",
        "authority": False,
        "g4_closed": False,
    }


def validate_object(obj: dict[str, Any], expected_object: str) -> dict[str, Any]:
    if expected_object not in REQUIRED_OBJECTS:
        return {"ok": False, "reason": "unknown_object", "object": expected_object}
    if (
        obj.get("object") != expected_object
        or obj.get("schema_version") != SCHEMA_VERSIONS[expected_object]
    ):
        return {
            "ok": False,
            "reason": "object_or_schema_mismatch",
            "expected": expected_object,
            "expected_schema": SCHEMA_VERSIONS[expected_object],
            "got_object": obj.get("object"),
            "got_schema": obj.get("schema_version"),
        }
    if expected_object == "HiddenSuiteIdentityEnvelope":
        required_keys = list(SUITE_IDENTITY_FIELDS) + [
            "suite_identity_sha256",
            "object",
            "schema_version",
        ]
        missing = [k for k in required_keys if k not in obj]
        if missing:
            return {"ok": False, "reason": "envelope_underbound", "missing": missing}
        extra = sorted(set(obj) - set(required_keys))
        if extra:
            return {"ok": False, "reason": "envelope_unbound_extra_fields", "extra": extra}
        expected_commitment = recompute_canonical_suite_commitment(obj)
        if obj.get("canonical_suite_commitment") != expected_commitment:
            return {
                "ok": False,
                "reason": "canonical_suite_commitment_mismatch",
                "expected_canonical_suite_commitment": expected_commitment,
                "observed_canonical_suite_commitment": obj.get("canonical_suite_commitment"),
            }
        expected_exposure_subject = derive_exposure_subject_identity_sha256(
            canonical_suite_commitment=expected_commitment,
            realized_manifest_binding=str(obj.get("realized_manifest_binding") or ""),
        )
        if obj.get("exposure_subject_identity_sha256") != expected_exposure_subject:
            return {
                "ok": False,
                "reason": "exposure_subject_identity_mismatch",
                "expected_exposure_subject_identity_sha256": expected_exposure_subject,
                "observed_exposure_subject_identity_sha256": obj.get(
                    "exposure_subject_identity_sha256"
                ),
            }
        expected_suite_id = recompute_suite_identity_sha256(obj)
        if obj.get("suite_identity_sha256") != expected_suite_id:
            return {
                "ok": False,
                "reason": "suite_identity_sha256_mismatch",
                "expected_suite_identity_sha256": expected_suite_id,
                "observed_suite_identity_sha256": obj.get("suite_identity_sha256"),
            }
        # Reject empty realized binding placeholders that signal post-hash mutation
        if not obj.get("realized_manifest_binding"):
            return {
                "ok": False,
                "reason": "realized_manifest_binding_empty_posthash_risk",
            }
        for field in (
            "realized_manifest_binding",
            "exposure_subject_identity_sha256",
            "exposure_ledger_initial_head_contract",
            "exposure_ledger_sealed_head_contract",
            "suite_identity_sha256",
        ):
            value = obj.get(field)
            if not (
                isinstance(value, str)
                and len(value) == 64
                and all(char in "0123456789abcdef" for char in value)
            ):
                return {"ok": False, "reason": "invalid_lower_sha256", "field": field}
        if obj.get("non_authority_constraints") != SUITE_NON_AUTHORITY_CONSTRAINTS:
            return {"ok": False, "reason": "non_authority_constraints_drift"}
        for field, expected in SUITE_NON_AUTHORITY_FLAGS.items():
            if obj.get(field) is not expected:
                return {
                    "ok": False,
                    "reason": "non_authority_flag_drift",
                    "field": field,
                }
        if obj.get("label") != SYNTHETIC_LABEL:
            return {"ok": False, "reason": "synthetic_label_drift"}
        if obj.get("synthetic_only") is not True:
            return {"ok": False, "reason": "synthetic_only_must_be_true"}
        if obj.get("hash_profile") != SUITE_HASH_PROFILE:
            return {"ok": False, "reason": "suite_hash_profile_drift"}
    if expected_object in {
        "SubjectPublicManifest",
        "SubjectExecutionRouteDescriptor",
        "PromptfooSubjectAdapter",
        "ImmutableRunEnvelope",
    }:
        leaks = scan_forbidden_public_payload(obj)
        critical = [
            p
            for p in leaks
            if any(
                x in p
                for x in ("vault_locator", "seed", "truth", "answer", "family_identity", "scorer_")
            )
        ]
        if expected_object != "ImmutableRunEnvelope" and leaks:
            return {"ok": False, "reason": "forbidden_public_keys", "leaks": leaks}
        if expected_object == "ImmutableRunEnvelope" and critical:
            return {"ok": False, "reason": "forbidden_public_keys", "leaks": critical}
    if expected_object == "CalibrationContract":
        if obj.get("scoring_enabled") is not False:
            return {"ok": False, "reason": "scoring_must_be_false"}
        if obj.get("hidden_cases_consumed") is not False:
            return {"ok": False, "reason": "hidden_cases_consumed_must_be_false"}
    if expected_object == "ImmutableRunEnvelope":
        missing_identity_fields = [
            field for field in RUN_ENVELOPE_IDENTITY_FIELDS if field not in obj
        ]
        if missing_identity_fields:
            return {
                "ok": False,
                "reason": "immutable_run_envelope_underbound",
                "missing": missing_identity_fields,
            }
        identity_fields = {field: obj[field] for field in RUN_ENVELOPE_IDENTITY_FIELDS}
        expected_identity = identity_from_fields("ImmutableRunEnvelope", identity_fields)[
            "identity_sha256"
        ]
        if obj.get("envelope_identity_sha256") != expected_identity:
            return {
                "ok": False,
                "reason": "immutable_run_envelope_identity_mismatch",
                "expected_identity_sha256": expected_identity,
                "observed_identity_sha256": obj.get("envelope_identity_sha256"),
            }
    if expected_object == "HeldoutNonCollisionAttestation":
        if obj.get("collision") is True or obj.get("ok") is False:
            return {"ok": False, "reason": "training_heldout_collision"}
    return {
        "ok": True,
        "object": expected_object,
        "schema_version": obj.get("schema_version"),
        "object_sha256": canonical_json_sha256(obj),
    }


def validate_all_present(objects: dict[str, Any]) -> dict[str, Any]:
    missing = [n for n in REQUIRED_OBJECTS if n not in objects]
    results = {}
    for name, obj in objects.items():
        if name in REQUIRED_OBJECTS:
            results[name] = validate_object(obj, name)
    failed = [n for n, r in results.items() if not r.get("ok")]
    return {
        "ok": not missing and not failed,
        "missing": missing,
        "failed": failed,
        "results": results,
        "required_count": len(REQUIRED_OBJECTS),
    }
