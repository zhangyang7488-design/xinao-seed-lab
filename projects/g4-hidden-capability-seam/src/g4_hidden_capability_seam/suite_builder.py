"""Build the complete synthetic hidden-capability isolation seam under an op root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import PACKAGE_ID, SYNTHETIC_LABEL
from .atomic_state import AtomicSeamState
from .audit_log import AuditRunLog
from .canonical import (
    canonical_json_sha256,
    identity_from_fields,
    raw_bytes_sha256_file,
    write_json,
)
from .exposure_ledger import ExposureLedger
from .materializer import materialize_public_cases
from .objects import (
    C_SLOTS,
    H_SLOTS,
    REQUIRED_OBJECTS,
    build_calibration_contract_shape,
    build_evaluator_bundle,
    build_generator_artifact_descriptor,
    build_heldout_attestation,
    build_hidden_suite_canonical_fields,
    build_hidden_suite_identity_envelope,
    build_immutable_run_envelope,
    build_promptfoo_adapter_descriptor,
    build_public_manifest_blueprint,
    build_route_descriptor,
    build_subject_public_manifest,
    derive_exposure_subject_identity_sha256,
    hidden_suite_registration_commitment_inputs,
    validate_all_present,
    validate_object,
)
from .rotation_revocation import RotationRevocationRegistry
from .run_idempotency import RunIdempotencyRegistry
from .security_model import role_catalog
from .vault import CUSTODIAN_CAP, SealedTruthVault


def build_synthetic_suite(op_root: str | Path) -> dict[str, Any]:
    op = Path(op_root).resolve()
    public_root = op / "public"
    vault_root = op / "vault"
    subject_root = op / "subject"
    promptfoo_root = op / "promptfoo"
    evaluator_root = op / "evaluator"
    ledger_root = op / "ledgers"
    for d in (public_root, vault_root, subject_root, promptfoo_root, evaluator_root, ledger_root):
        d.mkdir(parents=True, exist_ok=True)

    # Shared atomic state for suite lifecycle + run claims
    state_db = ledger_root / "seam_state.sqlite3"
    state = AtomicSeamState(state_db, max_attempts=64)
    audit = AuditRunLog(ledger_root / "audit_run_log.jsonl")
    audit.append_event("suite_build_start", {"package_id": PACKAGE_ID})

    exposure = ExposureLedger(ledger_root / "exposure_ledger.jsonl")
    rotation = RotationRevocationRegistry(ledger_root / "rotation_revocation.json", state=state)
    idem = RunIdempotencyRegistry(
        ledger_root / "run_idempotency.json", state=state, max_attempts=64
    )

    schedule_slots = H_SLOTS + C_SLOTS

    # --- Build identity-bearing components first (acyclic) ---
    gen_src = {
        "generator_id": "syn_structural_generator_v1",
        "note": "synthetic structural schedule only",
    }
    gen_sha = identity_from_fields("generator_src", gen_src)["identity_sha256"]
    generator = build_generator_artifact_descriptor(
        generator_id="syn_structural_generator_v1",
        public_interface_version="v1",
        artifact_sha256=gen_sha,
    )

    route = build_route_descriptor(
        route_label="offline_synthetic_promptfoo_0_121_18_docker",
        promptfoo_version="0.121.18",
        offline=True,
        cache_enabled=False,
        network_enabled=False,
        execution_boundary="docker_create_inspect_start",
    )

    adapter_path = Path(__file__).resolve().parents[2] / "adapters" / "promptfoo_subject_adapter.py"
    adapter_sha, _ = raw_bytes_sha256_file(adapter_path)
    adapter = build_promptfoo_adapter_descriptor(
        adapter_module="adapters/promptfoo_subject_adapter.py",
        adapter_source_sha256=adapter_sha,
    )

    from .evaluator import IndependentEvaluator

    vault = SealedTruthVault(vault_root)
    public_cases: list[dict[str, Any]] = []
    for slot in schedule_slots:
        cid = f"syn-{slot}-001"
        prompt = f"SYNTHETIC_STRUCTURAL_CASE {slot} — not real hidden content"
        dep = vault.deposit_synthetic(
            public_case_id=cid,
            public_prompt=prompt,
            truth={"expected_echo_token": f"TOK_{slot}", "note": "synthetic"},
            scoring_rule_private={"type": "synthetic_isolation_only", "slot": slot},
            family_slot=slot if slot.startswith("H") else f"CONTROL_{slot}",
            schedule_class="structural_schema_schedule_only",
            capability=CUSTODIAN_CAP,
        )
        assert dep["ok"], dep
        pc = dep["public_commitment"]
        public_cases.append(
            {
                "public_case_id": cid,
                "public_prompt": prompt,
                "commitment_sha256": pc["commitment_sha256"],
                "schedule_slot": slot,
            }
        )

    evaluator = IndependentEvaluator(state_root=evaluator_root, vault=vault)
    # Logical evaluator state root (not absolute path) so suite identity is
    # stable across independent op roots with identical synthetic inputs.
    ev_bundle = build_evaluator_bundle(
        evaluator_id="syn_independent_evaluator_v1",
        state_root="evaluator",
        code_identity_sha256=evaluator.code_identity(),
    )
    calibration = build_calibration_contract_shape()
    training_identity_sha256 = identity_from_fields(
        "training", {"suite": "train_syn", "salt": "t1"}
    )["identity_sha256"]
    heldout_identity_sha256 = identity_from_fields("heldout", {"suite": "hold_syn", "salt": "h1"})[
        "identity_sha256"
    ]
    heldout = build_heldout_attestation(
        training_identity_sha256=training_identity_sha256,
        heldout_identity_sha256=heldout_identity_sha256,
    )

    bp = build_public_manifest_blueprint(
        public_cases=public_cases,
        route_identity_sha256=route["route_identity_sha256"],
        adapter_identity_sha256=adapter["adapter_identity_sha256"],
    )
    rotation_registry_identity = identity_from_fields(
        "RotationRevocationRegistry",
        {"db": "seam_state.sqlite3", "schema": "v1"},
    )["identity_sha256"]

    # Initial exposure head contract (genesis).
    exposure_initial_head = "0" * 64

    # Acyclic realization commitment: excludes suite_identity_sha256.
    # Suite binds this; final manifest identity later binds suite identity.
    realized_manifest_binding = canonical_json_sha256(
        {
            "public_manifest_blueprint_commitment": bp["public_manifest_blueprint_commitment"],
            "route_identity_sha256": route["route_identity_sha256"],
            "adapter_identity_sha256": adapter["adapter_identity_sha256"],
            "case_count": len(public_cases),
            "schedule_slots": schedule_slots,
        }
    )

    suite_core_kwargs = {
        "public_suite_label": "syn_hidden_suite_structural_only_v1",
        "schedule_slots": schedule_slots,
        "synthetic_salt": "g4_hidden_capability_seam_v1_wave146_synthetic",
        "suite_version": "1",
        "generator_descriptor_identity_sha256": generator["descriptor_identity_sha256"],
        "generator_artifact_bytes_sha256": generator["artifact_sha256"],
        "evaluator_bundle_identity_sha256": ev_bundle["bundle_identity_sha256"],
        "evaluator_code_hash": ev_bundle["code_identity_sha256"],
        "scoring_calibration_contract_identity_sha256": calibration["contract_identity_sha256"],
        "public_manifest_blueprint_commitment": bp["public_manifest_blueprint_commitment"],
        "heldout_identity_sha256": heldout_identity_sha256,
        "training_identity_sha256": training_identity_sha256,
        "non_collision_attestation_identity_sha256": heldout["attestation_identity_sha256"],
        "exposure_ledger_initial_head_contract": exposure_initial_head,
        "lifecycle_status": "active",
        "creator_identity": "syn_seam_author_v1",
        "created_at_source": "synthetic_deterministic_clock_v1",
        "rotation_registry_identity_sha256": rotation_registry_identity,
        "rotation_registry_head_sha256": exposure_initial_head,
        "revocation_status": "not_revoked",
        "parent_suite_identity_sha256": None,
        "subject_route_identity_sha256": route["route_identity_sha256"],
    }
    canonical_suite_commitment = canonical_json_sha256(
        build_hidden_suite_canonical_fields(**suite_core_kwargs)
    )
    exposure_subject_identity_sha256 = derive_exposure_subject_identity_sha256(
        canonical_suite_commitment=canonical_suite_commitment,
        realized_manifest_binding=realized_manifest_binding,
    )

    # Record the complete pre-admission exposure snapshot against an acyclic
    # suite-bound subject key, then seal it before the final suite identity exists.
    exposure.record_exposure(
        principal_id="vault_custodian_syn",
        role="vault_custodian",
        exposure_subject_identity_sha256=exposure_subject_identity_sha256,
        exposure_kind="truth",
        object_ref="synthetic_truth_deposit",
        note="custodian_deposit",
    )
    exposure.record_exposure(
        principal_id="seam_author_syn",
        role="seam_author",
        exposure_subject_identity_sha256=exposure_subject_identity_sha256,
        exposure_kind="public_manifest",
        object_ref="public_manifest_blueprint",
    )
    exposure.record_exposure(
        principal_id="subject_candidate_syn",
        role="subject",
        exposure_subject_identity_sha256=exposure_subject_identity_sha256,
        exposure_kind="public_case_id",
        object_ref="public_case_schedule",
    )
    exp_seal = exposure.log.write_seal_receipt(ledger_root / "exposure_ledger.seal.v1.json")
    runtime_exposure_head = exp_seal["expected_head_sha256"]

    # Final identity is computed exactly once with the realized manifest binding,
    # exposure subject mapping, and actual sealed ledger head already present.
    suite = build_hidden_suite_identity_envelope(
        **suite_core_kwargs,
        realized_manifest_binding=realized_manifest_binding,
        exposure_subject_identity_sha256=exposure_subject_identity_sha256,
        exposure_ledger_sealed_head_contract=runtime_exposure_head,
    )
    suite_v = validate_object(suite, "HiddenSuiteIdentityEnvelope")
    if not suite_v.get("ok"):
        raise ValueError(f"suite_identity_invalid_at_build:{suite_v}")
    if suite["canonical_suite_commitment"] != canonical_suite_commitment:
        raise ValueError("suite_canonical_commitment_drifted_during_finalization")
    if suite["exposure_ledger_sealed_head_contract"] != runtime_exposure_head:
        raise ValueError("suite_exposure_head_not_bound_to_actual_seal")
    suite_identity_sha256 = suite["suite_identity_sha256"]

    # Register with full envelope recompute at admission (not caller hash trust)
    reg = rotation.register_identity(
        identity_kind="HiddenSuiteIdentityEnvelope",
        public_label=suite["public_suite_label"],
        commitment_inputs=hidden_suite_registration_commitment_inputs(suite),
        suite_identity_sha256=suite_identity_sha256,
        suite_envelope=suite,
        exposure_ledger_path=ledger_root / "exposure_ledger.jsonl",
        exposure_seal_path=ledger_root / "exposure_ledger.seal.v1.json",
    )
    assert reg.get("ok"), reg

    manifest = build_subject_public_manifest(
        suite_identity_sha256=suite_identity_sha256,
        public_cases=public_cases,
        route_identity_sha256=route["route_identity_sha256"],
        adapter_identity_sha256=adapter["adapter_identity_sha256"],
        public_manifest_blueprint_commitment=bp["public_manifest_blueprint_commitment"],
    )
    write_json(public_root / "subject_public_manifest.v1.json", manifest)

    mat = materialize_public_cases(manifest=manifest, output_dir=public_root / "materialized")
    assert mat["ok"], mat

    elig_ok = exposure.subject_eligibility(
        exposure_subject_identity_sha256=exposure_subject_identity_sha256,
        principal_id="subject_candidate_syn",
        suite_identity_sha256=suite_identity_sha256,
    )
    elig_bad = exposure.subject_eligibility(
        exposure_subject_identity_sha256=exposure_subject_identity_sha256,
        principal_id="vault_custodian_syn",
        suite_identity_sha256=suite_identity_sha256,
    )

    iso = vault.assert_path_isolation(
        subject_root=subject_root,
        promptfoo_root=promptfoo_root,
        evaluator_root=evaluator_root,
    )

    security = role_catalog()

    run_envelope = build_immutable_run_envelope(
        run_id="run_placeholder_pre_promptfoo",
        attempt_id="att_0",
        suite_identity_sha256=suite_identity_sha256,
        route_identity_sha256=route["route_identity_sha256"],
        manifest_identity_sha256=manifest["manifest_identity_sha256"],
        raw_outputs=[],
        telemetry={"phase": "pre_promptfoo"},
        terminal_status="not_started",
    )

    # Final immutability check: emitted envelope still validates
    suite_final_v = validate_object(suite, "HiddenSuiteIdentityEnvelope")
    if not suite_final_v.get("ok"):
        raise ValueError(f"suite_identity_drifted_after_build:{suite_final_v}")

    objects: dict[str, Any] = {
        "HiddenSuiteIdentityEnvelope": suite,
        "GeneratorArtifactDescriptor": generator,
        "SealedParameterCommitment": {
            "schema_version": "xinao.g4.hidden_capability_seam.sealed_parameter_commitment.v1",
            "object": "SealedParameterCommitment",
            "commitments": [
                {
                    "public_case_id": c["public_case_id"],
                    "commitment_sha256": c["commitment_sha256"],
                }
                for c in public_cases
            ],
            "synthetic_only": True,
            "label": SYNTHETIC_LABEL,
            "authority": False,
        },
        "SubjectPublicManifest": manifest,
        "SealedTruthVault": vault.status(expected_receipt=False),
        "EvaluatorBundle": ev_bundle,
        "SubjectExecutionRouteDescriptor": route,
        "PromptfooSubjectAdapter": adapter,
        "ImmutableRunEnvelope": run_envelope,
        "RunIdempotencyRegistry": {
            "schema_version": "xinao.g4.hidden_capability_seam.run_idempotency_registry.v1",
            "object": "RunIdempotencyRegistry",
            **idem.status(),
        },
        "ExposureLedger": {
            "schema_version": "xinao.g4.hidden_capability_seam.exposure_ledger.v1",
            "object": "ExposureLedger",
            **exposure.verify(),
            "seal": exp_seal,
            "subject_eligibility_ok": elig_ok,
            "subject_eligibility_custodian": elig_bad,
        },
        "RotationRevocationRegistry": {
            "schema_version": "xinao.g4.hidden_capability_seam.rotation_revocation_registry.v1",
            "object": "RotationRevocationRegistry",
            "active_count": 1,
            "suite_identity_sha256": suite_identity_sha256,
            "cas_backend": "sqlite3_delete_journal_begin_immediate",
            "authority": False,
        },
        "HeldoutNonCollisionAttestation": heldout,
        "CalibrationContract": calibration,
    }

    obj_dir = op / "objects"
    obj_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in objects.items():
        write_json(obj_dir / f"{name}.v1.json", obj)
    write_json(op / "security_model.v1.json", security)

    validation = validate_all_present(objects)
    audit_seal = audit.log.write_seal_receipt(ledger_root / "audit_run_log.seal.v1.json")
    audit.append_event(
        "suite_build_complete",
        {
            "validation_ok": validation["ok"],
            "case_count": len(public_cases),
            "suite_identity_sha256": suite_identity_sha256,
        },
    )
    # Refresh audit seal after final event
    audit_seal = audit.log.write_seal_receipt(ledger_root / "audit_run_log.seal.v1.json")

    # Host lockdown after evaluator still holds open path for later use:
    # applied at end of offline run; during build keep readable for deposits.
    summary = {
        "ok": validation["ok"]
        and iso.get("ok")
        and elig_ok.get("eligible")
        and not elig_bad.get("eligible"),
        "op_root": str(op),
        "suite_identity_sha256": suite_identity_sha256,
        "route_identity_sha256": route["route_identity_sha256"],
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "public_manifest_path": str(public_root / "subject_public_manifest.v1.json"),
        "materialized_cases_path": mat["cases_path"],
        "vault_root": str(vault_root),
        "promptfoo_root": str(promptfoo_root),
        "evaluator_root": str(evaluator_root),
        "subject_root": str(subject_root),
        "ledger_root": str(ledger_root),
        "state_db": str(state_db),
        "objects_validation": validation,
        "path_isolation": iso,
        "eligibility": {"subject_candidate": elig_ok, "custodian": elig_bad},
        "schedule_slots": schedule_slots,
        "exposure_seal": exp_seal,
        "runtime_exposure_head_sha256": runtime_exposure_head,
        "exposure_subject_identity_sha256": exposure_subject_identity_sha256,
        "suite_exposure_sealed_head_contract": suite["exposure_ledger_sealed_head_contract"],
        "audit_seal": audit_seal,
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
        "required_objects": list(REQUIRED_OBJECTS),
        "authority": False,
        "g4_closed": False,
        "g5_active": False,
    }
    write_json(op / "suite_build_summary.v1.json", summary)
    return summary
