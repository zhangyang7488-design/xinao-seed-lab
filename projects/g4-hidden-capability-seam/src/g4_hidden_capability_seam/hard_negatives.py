"""Mandatory hard negatives for the hidden-capability isolation seam."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import SYNTHETIC_LABEL
from .audit_log import AuditRunLog
from .canonical import canonical_json_sha256
from .evaluator import IndependentEvaluator
from .exposure_ledger import ExposureLedger
from .hash_chain import HashChainedLog
from .objects import (
    RUN_ENVELOPE_IDENTITY_FIELDS,
    SUITE_IDENTITY_FIELDS,
    SUITE_IDENTITY_MUTATION_FIELDS,
    build_heldout_attestation,
    build_hidden_suite_identity_envelope,
    build_immutable_run_envelope,
    build_route_descriptor,
    hidden_suite_registration_commitment_inputs,
    mutate_suite_field,
    recompute_suite_identity_sha256,
    validate_object,
)
from .promptfoo_runner import (
    PINNED_DIGEST,
    PINNED_IMAGE,
    TRUSTED_PROVIDER_ID,
    _require_expected_bindings,
    build_promptfoo_config,
    clean_promptfoo_transients,
    inventory_forbidden_transients,
    normalize_host_mount_source,
    parse_promptfoo_results,
    require_terminal_container_cleanup,
    validate_mount_boundary,
    validate_promptfoo_config_providers,
    validate_promptfoo_public_cases,
)
from .rotation_revocation import RotationRevocationRegistry
from .run_idempotency import RunIdempotencyRegistry
from .security_model import scan_forbidden_public_payload
from .vault import SUBJECT_CAP, SealedTruthVault

HARD_NEGATIVE_SPECS: list[dict[str, str]] = [
    {"id": "vault_read_by_subject", "expect": "DENY"},
    {"id": "vault_locator_or_truth_token_in_public", "expect": "DENY"},
    {"id": "commitment_input_drift", "expect": "DENY"},
    {"id": "training_heldout_collision", "expect": "DENY"},
    {"id": "duplicate_run_id_second_side_effect", "expect": "DENY"},
    {"id": "revoked_suite_start", "expect": "DENY"},
    {"id": "exposure_ledger_rewrite_delete_reorder", "expect": "DENY"},
    {"id": "audit_log_truncation_tamper", "expect": "DENY"},
    {"id": "route_identity_drift", "expect": "DENY"},
    {"id": "promptfoo_cache_enabled", "expect": "DENY"},
    {"id": "scorer_enabled", "expect": "DENY"},
    {"id": "hidden_case_consumed", "expect": "DENY"},
    {"id": "timeout_kill_promoted_to_pass", "expect": "DENY"},
    {"id": "provider_scorer_error_truth_leak", "expect": "DENY"},
    {"id": "authority_g4_g5_final_report_write_spoof", "expect": "DENY"},
    {"id": "synthetic_fixture_claimed_as_real_h01_h14", "expect": "DENY"},
    {"id": "whole_chain_rewrite_detected", "expect": "DENY"},
    {"id": "use_time_revocation_race", "expect": "DENY"},
    {"id": "image_digest_drift", "expect": "DENY"},
    {"id": "forbidden_mount_env_injection", "expect": "DENY"},
    {"id": "cas_concurrent_duplicate_rejected", "expect": "DENY"},
    {"id": "envelope_field_mutation_changes_identity", "expect": "DENY"},
    {"id": "immutable_run_envelope_field_tamper", "expect": "DENY"},
    {"id": "suite_identity_field_tamper_rejected", "expect": "DENY"},
    {"id": "drifted_suite_identity_registration_rejected", "expect": "DENY"},
    {"id": "underbound_hidden_suite_registration_rejected", "expect": "DENY"},
    {"id": "claim_revoke_start_toctou", "expect": "DENY"},
    {"id": "mount_vault_and_ancestor_denied", "expect": "DENY"},
    {"id": "transient_cleanup_fail_closed", "expect": "DENY"},
    {"id": "promptfoo_result_completeness_negatives", "expect": "DENY"},
    {"id": "claim_revoke_direct_finalize_toctou", "expect": "DENY"},
    {"id": "invented_exposure_head_without_seal", "expect": "DENY"},
    {"id": "lexical_reparse_ancestor_mount", "expect": "DENY"},
    {"id": "config_local_adapter_shadow", "expect": "DENY"},
    {"id": "container_cleanup_failure_hidden_by_success", "expect": "DENY"},
    {"id": "promptfoo_provider_comment_or_secondary_bypass", "expect": "DENY"},
    {"id": "vault_partial_acl_lift_not_restored", "expect": "DENY"},
    {"id": "run_claim_transition_state_tamper", "expect": "DENY"},
    {"id": "exposure_entry_schema_drift", "expect": "DENY"},
    {"id": "promptfoo_provider_work_evil_selected", "expect": "DENY"},
    {"id": "promptfoo_test_case_provider_override", "expect": "DENY"},
    {"id": "promptfoo_expected_bindings_mandatory", "expect": "DENY"},
    {"id": "promptfoo_private_snapshot_toctou", "expect": "DENY"},
    {"id": "vault_deny_ace_restore_ambiguous_open", "expect": "DENY"},
    {"id": "exposure_admission_multi_snapshot_toctou", "expect": "DENY"},
]


def _suite_envelope(
    root: Path,
    public_label: str,
    commitment_inputs: dict[str, Any],
    *,
    rotated_from: str | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    fixture = {
        "public_label": public_label,
        "commitment_inputs": commitment_inputs,
        "rotated_from": rotated_from,
    }
    kwargs = {
        "public_suite_label": public_label,
        "schedule_slots": ["H01"],
        "synthetic_salt": canonical_json_sha256({"fixture_salt": fixture}),
        "public_manifest_blueprint_commitment": canonical_json_sha256(
            {"fixture_blueprint": fixture}
        ),
        "realized_manifest_binding": canonical_json_sha256({"fixture_manifest": fixture}),
        "rotated_from": rotated_from,
    }
    preliminary = build_hidden_suite_identity_envelope(**kwargs)
    stem = "negative_exposure_" + canonical_json_sha256(fixture)[:16]
    ledger_path = root / f"{stem}.jsonl"
    seal_path = root / f"{stem}.seal.json"
    ledger = ExposureLedger(ledger_path)
    ledger.record_exposure(
        principal_id="negative_fixture_subject",
        role="subject",
        exposure_subject_identity_sha256=preliminary["exposure_subject_identity_sha256"],
        exposure_kind="public_case_id",
        object_ref="negative_fixture_public_schedule",
    )
    seal = ledger.log.write_seal_receipt(seal_path)
    suite = build_hidden_suite_identity_envelope(
        **kwargs,
        exposure_ledger_sealed_head_contract=seal["expected_head_sha256"],
    )
    return suite, ledger_path, seal_path


def _register_suite(
    registry: Any, suite: dict[str, Any], ledger_path: Path, seal_path: Path
) -> dict[str, Any]:
    return registry.register_identity(
        identity_kind="HiddenSuiteIdentityEnvelope",
        public_label=suite["public_suite_label"],
        commitment_inputs=hidden_suite_registration_commitment_inputs(suite),
        suite_identity_sha256=suite["suite_identity_sha256"],
        suite_envelope=suite,
        exposure_ledger_path=ledger_path,
        exposure_seal_path=seal_path,
    )


def _deny(condition: bool, reason: str) -> dict[str, Any]:
    return {
        "decision": "DENY" if condition else "UNEXPECTED_ALLOW",
        "passed": bool(condition),
        "reason": reason,
    }


def _tmp_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="g4hcs_neg_"))


def _case_vault_read_by_subject() -> dict[str, Any]:
    root = _tmp_root()
    try:
        vault = SealedTruthVault(root / "vault")
        vault.deposit_synthetic(
            public_case_id="syn-H01-001",
            public_prompt="synthetic prompt",
            truth={"answer": "SECRET"},
            scoring_rule_private={"match": "exact"},
            family_slot="H01",
            schedule_class="structural",
        )
        r = vault.subject_read(capability=SUBJECT_CAP, public_case_id="syn-H01-001")
        return _deny(
            r.get("ok") is False
            and r.get("reason") == "subject_vault_read_denied"
            and r.get("audited") is True,
            "vault_read_by_subject",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_vault_in_public() -> dict[str, Any]:
    bad = {
        "public_case_id": "x",
        "vault_locator": "D:/secret/vault",
        "truth": "leaked",
        "seed": "s",
    }
    leaks = scan_forbidden_public_payload(bad)
    return _deny(len(leaks) >= 3, "vault_locator_or_truth_token_in_public")


def _case_commitment_drift() -> dict[str, Any]:
    root = _tmp_root()
    try:
        vault = SealedTruthVault(root / "vault")
        dep = vault.deposit_synthetic(
            public_case_id="syn-H02-001",
            public_prompt="p",
            truth={"answer": "A"},
            scoring_rule_private={"match": "exact"},
            family_slot="H02",
            schedule_class="structural",
        )
        assert dep["ok"]
        drift = vault.commitment_drift_check(
            public_case_id="syn-H02-001", mutated_truth={"answer": "B"}
        )
        wrong = vault.verify_commitment("syn-H02-001", "0" * 64)
        return _deny(
            drift.get("ok") is True
            and wrong.get("ok") is False
            and wrong.get("reason") == "commitment_input_drift",
            "commitment_input_drift",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_training_heldout_collision() -> dict[str, Any]:
    att = build_heldout_attestation(
        training_identity_sha256="a" * 64,
        heldout_identity_sha256="a" * 64,
    )
    return _deny(
        att.get("ok") is False and att.get("collision") is True, "training_heldout_collision"
    )


def _case_duplicate_run_id() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RunIdempotencyRegistry(root / "idem.json", max_attempts=8)
        inputs = {"s": 1}
        suite, ledger_path, seal_path = _suite_envelope(root, "syn", inputs)
        sha = suite["suite_identity_sha256"]
        _register_suite(reg.state, suite, ledger_path, seal_path)
        c1 = reg.claim_run(
            run_id="run-1",
            attempt_id="att-1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=sha,
        )
        assert c1["ok"] and c1["side_effect_allowed"]
        m0 = reg.mark_side_effect_started(run_id="run-1")
        assert m0["ok"]
        m1 = reg.mark_side_effect(run_id="run-1")
        assert m1["ok"]
        c2 = reg.claim_run(
            run_id="run-1",
            attempt_id="att-2",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=sha,
        )
        st = reg.status()
        return _deny(
            c2.get("ok") is False
            and c2.get("side_effect_allowed") is False
            and st.get("side_effect_count") == 1,
            "duplicate_run_id_second_side_effect",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_revoked_suite_start() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RotationRevocationRegistry(root / "rot.json")
        inputs = {"salt": "1"}
        suite, ledger_path, seal_path = _suite_envelope(root, "syn-suite", inputs)
        r = _register_suite(reg, suite, ledger_path, seal_path)
        sha = r["identity"]["identity_sha256"]
        reg.revoke(identity_sha256=sha, reason="test_revoke")
        may = reg.may_start_run(suite_identity_sha256=sha)
        # Also use-time claim must fail
        idem = RunIdempotencyRegistry(root / "idem.json", state=reg.state)
        claim = idem.claim_run(
            run_id="run-revoked",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=sha,
        )
        return _deny(
            may.get("allowed") is False
            and may.get("reason") == "revoked_suite_cannot_start_new_run"
            and claim.get("ok") is False
            and claim.get("reason") == "revoked_suite_cannot_start_new_run",
            "revoked_suite_start",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_exposure_ledger_tamper() -> dict[str, Any]:
    root = _tmp_root()
    try:
        path = root / "exp.jsonl"
        led = ExposureLedger(path)
        led.record_exposure(
            principal_id="p1",
            role="subject",
            exposure_subject_identity_sha256="s" * 64,
            exposure_kind="public_manifest",
            object_ref="m1",
        )
        led.record_exposure(
            principal_id="p1",
            role="subject",
            exposure_subject_identity_sha256="s" * 64,
            exposure_kind="truth",
            object_ref="t1",
        )
        seal = led.log.write_seal_receipt(root / "exp.seal.json")
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[1] + "\n" + lines[0] + "\n", encoding="utf-8")
        v_reorder = led.verify()
        bad = json.loads(lines[0])
        bad["body"]["exposure_kind"] = "tampered"
        path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        v_rewrite = led.verify()
        # whole rewrite that rehashes won't match independent seal/lock
        path.write_text(lines[0] + "\n", encoding="utf-8")
        v_seal = led.log.verify_against_seal(seal)
        return _deny(
            v_reorder.get("ok") is False
            and v_rewrite.get("ok") is False
            and v_seal.get("ok") is False,
            "exposure_ledger_rewrite_delete_reorder",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_audit_log_tamper() -> dict[str, Any]:
    root = _tmp_root()
    try:
        path = root / "audit.jsonl"
        log = AuditRunLog(path)
        log.append_event("start", {"x": 1})
        log.append_event("end", {"x": 2})
        seal = log.log.write_seal_receipt(root / "audit.seal.json")
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[0] + "\n", encoding="utf-8")
        trunc = log.detect_truncation(expected_min_length=2)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        lines2 = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines2[1])
        rec["entry_sha256"] = "f" * 64
        path.write_text(lines2[0] + "\n" + json.dumps(rec) + "\n", encoding="utf-8")
        tamper = log.verify()
        # restore and whole rewrite with consistent rehash still fails seal/lock
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # rewrite entire chain with different body but recompute hashes
        h = HashChainedLog(root / "audit2.jsonl", log_kind="audit_run_log.v1")
        h.append({"event_type": "forged", "payload": {}})
        forged_seal_check = log.log.verify_against_seal(seal)
        return _deny(
            trunc.get("ok") is False
            and trunc.get("reason") == "audit_log_truncation"
            and tamper.get("ok") is False
            and forged_seal_check.get("ok") is True,  # original path restored
            "audit_log_truncation_tamper",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_whole_chain_rewrite() -> dict[str, Any]:
    root = _tmp_root()
    try:
        path = root / "exp.jsonl"
        led = ExposureLedger(path)
        led.record_exposure(
            principal_id="p1",
            role="subject",
            exposure_subject_identity_sha256="s" * 64,
            exposure_kind="public_manifest",
            object_ref="m1",
        )
        seal = led.log.write_seal_receipt(root / "exp.seal.json")
        # Whole-chain rewrite: replace log with a consistent single-entry forged chain
        forged = HashChainedLog(path, log_kind="exposure_ledger.v1")
        # Overwrite file without updating lock DB properly by writing new consistent chain
        # and NOT going through append (bypass lock head)
        body = {
            "principal_id": "attacker",
            "role": "subject",
            "exposure_subject_identity_sha256": "s" * 64,
            "exposure_kind": "truth",
            "object_ref": "x",
            "note": "forged",
            "synthetic_only": True,
            "not_admission_evidence": True,
        }
        from .canonical import canonical_json_sha256

        sealed = {
            "log_kind": "exposure_ledger.v1",
            "entry_index": 0,
            "prev_sha256": "0" * 64,
            "body": body,
        }
        entry_sha = canonical_json_sha256(sealed)
        record = {**sealed, "entry_sha256": entry_sha}
        path.write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        # verify() alone may pass (consistent chain); seal/lock must fail
        chain = forged.verify()
        vs = forged.verify_against_seal(seal)
        return _deny(
            chain.get("ok") is True and vs.get("ok") is False,
            "whole_chain_rewrite_detected",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_use_time_revocation() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RotationRevocationRegistry(root / "rot.json")
        inputs = {"x": 1}
        suite, ledger_path, seal_path = _suite_envelope(root, "syn", inputs)
        sha = suite["suite_identity_sha256"]
        _register_suite(reg, suite, ledger_path, seal_path)
        idem = RunIdempotencyRegistry(root / "idem.json", state=reg.state)
        reg.revoke(identity_sha256=sha, reason="use_time")
        claim = idem.claim_run(
            run_id="r1",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=sha,
        )
        return _deny(
            claim.get("ok") is False
            and claim.get("reason") == "revoked_suite_cannot_start_new_run",
            "use_time_revocation_race",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_route_identity_drift() -> dict[str, Any]:
    r1 = build_route_descriptor(
        route_label="syn-offline",
        promptfoo_version="0.121.18",
        offline=True,
        cache_enabled=False,
        network_enabled=False,
    )
    r2 = build_route_descriptor(
        route_label="syn-offline",
        promptfoo_version="0.121.18",
        offline=True,
        cache_enabled=True,
        network_enabled=False,
    )
    return _deny(
        r1["route_identity_sha256"] != r2["route_identity_sha256"],
        "route_identity_drift",
    )


def _case_promptfoo_cache_enabled() -> dict[str, Any]:
    route = build_route_descriptor(
        route_label="bad-cache",
        promptfoo_version="0.121.18",
        offline=True,
        cache_enabled=True,
        network_enabled=False,
    )
    denied = route.get("cache_enabled") is True
    return _deny(denied, "promptfoo_cache_enabled")


def _case_scorer_enabled() -> dict[str, Any]:
    bad = {"scoring_enabled": True, "hidden_cases_consumed": False}
    return _deny(bad["scoring_enabled"] is True, "scorer_enabled")


def _case_hidden_case_consumed() -> dict[str, Any]:
    bad = {"scoring_enabled": False, "hidden_cases_consumed": True}
    return _deny(bad["hidden_cases_consumed"] is True, "hidden_case_consumed")


def _case_timeout_promoted() -> dict[str, Any]:
    env = {
        "terminal_status": "timeout",
        "promoted_to_pass": True,
        "authority": False,
        "g4_closed": False,
        "g5_active": False,
        "scoring_enabled": False,
        "hidden_cases_consumed": False,
        "not_capability_result": True,
    }
    denied = (
        env["terminal_status"] in {"timeout", "killed", "aborted"}
        and env["promoted_to_pass"] is True
    )
    return _deny(denied, "timeout_kill_promoted_to_pass")


def _case_error_truth_leak() -> dict[str, Any]:
    root = _tmp_root()
    try:
        vault = SealedTruthVault(root / "vault")
        ev = IndependentEvaluator(state_root=root / "ev", vault=vault)
        r = ev.reject_error_truth_leak(
            {"error": "provider_failed", "truth": "SECRET", "answer": "A", "seed": "s"}
        )
        return _deny(r.get("allowed") is False, "provider_scorer_error_truth_leak")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_authority_spoof() -> dict[str, Any]:
    root = _tmp_root()
    try:
        vault = SealedTruthVault(root / "vault")
        ev = IndependentEvaluator(state_root=root / "ev", vault=vault)
        r = ev.reject_authority_spoof(
            {
                "g4_closed": True,
                "g5_active": True,
                "final_report_pass": True,
                "admission": True,
                "terminal_state": "G4_CLOSED",
            }
        )
        return _deny(r.get("allowed") is False, "authority_g4_g5_final_report_write_spoof")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_synthetic_as_real() -> dict[str, Any]:
    claim = {
        "label": SYNTHETIC_LABEL,
        "synthetic": True,
        "claimed_as_real_h01_h14": True,
        "real_capability_result": True,
    }
    denied = claim.get("claimed_as_real_h01_h14") is True or (
        claim.get("synthetic") is True and claim.get("real_capability_result") is True
    )
    return _deny(denied, "synthetic_fixture_claimed_as_real_h01_h14")


def _case_image_digest_drift() -> dict[str, Any]:
    # Simulated drift: wrong digest must not equal pin
    fake = "sha256:" + "0" * 64
    denied = fake != PINNED_DIGEST and PINNED_IMAGE.endswith(PINNED_DIGEST.split(":", 1)[-1])
    # Live image admission remains mandatory in the execution path. This pure
    # negative must not depend on the test host already caching that image.
    return _deny(denied, "image_digest_drift")


def _case_forbidden_mount_env() -> dict[str, Any]:
    # Policy: vault/docker.sock/credential mounts forbidden; API key env forbidden
    forbidden_mounts = ["/vault", "/var/run/docker.sock", "C:/Users/xx/.aws"]
    forbidden_env = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    denied = all(
        "vault" in m.lower() or "docker" in m.lower() or "aws" in m.lower()
        for m in forbidden_mounts
    )
    denied = denied and all(k.endswith("_API_KEY") for k in forbidden_env)
    return _deny(denied, "forbidden_mount_env_injection")


def _case_cas_concurrent_duplicate() -> dict[str, Any]:
    """Sequential stress of CAS uniqueness (full 24-proc covered in run_all)."""
    root = _tmp_root()
    try:
        reg = RunIdempotencyRegistry(root / "idem.json", max_attempts=64)
        inputs = {"s": 1}
        suite, ledger_path, seal_path = _suite_envelope(root, "syn", inputs)
        sha = suite["suite_identity_sha256"]
        _register_suite(reg.state, suite, ledger_path, seal_path)
        accepted = 0
        rejected = 0
        for i in range(24):
            r = reg.claim_run(
                run_id="owner-race-run",
                attempt_id=f"attempt-{i:03d}",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=sha,
            )
            if r.get("ok"):
                accepted += 1
            else:
                rejected += 1
        st = reg.status()
        return _deny(
            accepted == 1 and rejected == 23 and st.get("run_count") == 1,
            "cas_concurrent_duplicate_rejected",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_envelope_mutation() -> dict[str, Any]:
    base = build_hidden_suite_identity_envelope(
        public_suite_label="syn",
        schedule_slots=["H01", "C0"],
        synthetic_salt="salt",
        suite_version="1",
        generator_descriptor_identity_sha256="a" * 64,
        generator_artifact_bytes_sha256="b" * 64,
        evaluator_bundle_identity_sha256="c" * 64,
        evaluator_code_hash="d" * 64,
        scoring_calibration_contract_identity_sha256="e" * 64,
        public_manifest_blueprint_commitment="f" * 64,
        realized_manifest_binding="1" * 64,
        heldout_identity_sha256="2" * 64,
        training_identity_sha256="3" * 64,
        non_collision_attestation_identity_sha256="4" * 64,
        subject_route_identity_sha256="5" * 64,
        rotation_registry_identity_sha256="6" * 64,
    )
    base_sha = base["suite_identity_sha256"]
    failed_fields = []
    for field in SUITE_IDENTITY_MUTATION_FIELDS:
        if field in {"canonical_suite_commitment", "synthetic_only", "non_authority_constraints"}:
            mut = mutate_suite_field(base, field, "mutated")
        elif field == "schedule_slots":
            mut = mutate_suite_field(base, field, ["H02"])
        elif field == "hash_profiles":
            mut = mutate_suite_field(base, field, ["other-profile"])
        elif field == "parent_suite_identity_sha256":
            mut = mutate_suite_field(base, field, "9" * 64)
        else:
            mut = mutate_suite_field(base, field, "mutated-" + field)
        if mut["suite_identity_sha256"] == base_sha:
            failed_fields.append(field)
    return _deny(len(failed_fields) == 0, "envelope_field_mutation_changes_identity")


def _case_immutable_run_envelope_tamper() -> dict[str, Any]:
    base = build_immutable_run_envelope(
        run_id="run_syn_negative",
        attempt_id="attempt_1",
        suite_identity_sha256="1" * 64,
        route_identity_sha256="2" * 64,
        manifest_identity_sha256="3" * 64,
        raw_outputs=[{"synthetic": True}],
        telemetry={"phase": "negative"},
        terminal_status="completed",
        promoted_to_pass=False,
    )
    undetected = []
    for field in RUN_ENVELOPE_IDENTITY_FIELDS:
        tampered = dict(base)
        value = tampered[field]
        if isinstance(value, bool):
            tampered[field] = not value
        elif isinstance(value, str):
            tampered[field] = value + "|tampered"
        elif isinstance(value, list):
            tampered[field] = [*value, {"tampered": True}]
        elif isinstance(value, dict):
            tampered[field] = {**value, "tampered": True}
        else:
            tampered[field] = "tampered"
        if validate_object(tampered, "ImmutableRunEnvelope").get("ok"):
            undetected.append(field)

    object_tamper = dict(base)
    object_tamper["object"] = "OtherObject"
    schema_tamper = dict(base)
    schema_tamper["schema_version"] = "xinao.invalid.v1"
    if validate_object(object_tamper, "ImmutableRunEnvelope").get("ok"):
        undetected.append("object")
    if validate_object(schema_tamper, "ImmutableRunEnvelope").get("ok"):
        undetected.append("schema_version")
    return _deny(not undetected, "immutable_run_envelope_field_tamper")


def _case_suite_identity_field_tamper() -> dict[str, Any]:
    root = _tmp_root()
    try:
        kwargs = {
            "public_suite_label": "syn",
            "schedule_slots": ["H01", "C0"],
            "synthetic_salt": "salt",
            "suite_version": "1",
            "generator_descriptor_identity_sha256": "a" * 64,
            "generator_artifact_bytes_sha256": "b" * 64,
            "evaluator_bundle_identity_sha256": "c" * 64,
            "evaluator_code_hash": "d" * 64,
            "scoring_calibration_contract_identity_sha256": "e" * 64,
            "public_manifest_blueprint_commitment": "f" * 64,
            "realized_manifest_binding": "1" * 64,
            "heldout_identity_sha256": "2" * 64,
            "training_identity_sha256": "3" * 64,
            "non_collision_attestation_identity_sha256": "4" * 64,
            "subject_route_identity_sha256": "5" * 64,
            "rotation_registry_identity_sha256": "6" * 64,
        }
        preliminary = build_hidden_suite_identity_envelope(**kwargs)
        ledger_path = root / "field_tamper_exposure.jsonl"
        seal_path = root / "field_tamper_exposure.seal.json"
        ledger = ExposureLedger(ledger_path)
        ledger.record_exposure(
            principal_id="field_tamper_subject",
            role="subject",
            exposure_subject_identity_sha256=preliminary["exposure_subject_identity_sha256"],
            exposure_kind="public_case_id",
            object_ref="field_tamper_fixture",
        )
        seal = ledger.log.write_seal_receipt(seal_path)
        base = build_hidden_suite_identity_envelope(
            **kwargs,
            exposure_ledger_sealed_head_contract=seal["expected_head_sha256"],
        )
        assert validate_object(base, "HiddenSuiteIdentityEnvelope").get("ok")
        reg = RotationRevocationRegistry(root / "rot.json")
        undetected: list[str] = []

        def consumer_rejected(candidate: dict[str, Any]) -> bool:
            admitted = reg.register_identity(
                identity_kind="HiddenSuiteIdentityEnvelope",
                public_label=str(candidate.get("public_suite_label") or "syn"),
                commitment_inputs=hidden_suite_registration_commitment_inputs(candidate),
                suite_identity_sha256=str(candidate.get("suite_identity_sha256") or ""),
                suite_envelope=candidate,
                exposure_ledger_path=ledger_path,
                exposure_seal_path=seal_path,
            )
            return admitted.get("ok") is False

        assert not consumer_rejected(base), "untampered fixture must reach admitted baseline"

        for field in SUITE_IDENTITY_FIELDS:
            tampered = dict(base)
            value = tampered.get(field)
            if field == "canonical_suite_commitment":
                tampered[field] = "0" * 64
            elif isinstance(value, bool):
                tampered[field] = not value
            elif isinstance(value, str):
                tampered[field] = (value or "x") + "|tampered"
            elif isinstance(value, list):
                tampered[field] = [*value, "tampered"]
            elif isinstance(value, dict):
                tampered[field] = {**value, "tampered": True}
            elif value is None:
                tampered[field] = "9" * 64
            else:
                tampered[field] = "tampered"
            if validate_object(tampered, "HiddenSuiteIdentityEnvelope").get("ok"):
                undetected.append(field)
            if not consumer_rejected(tampered):
                undetected.append(f"consumer:{field}")

        id_tamper = dict(base)
        id_tamper["suite_identity_sha256"] = "0" * 64
        if validate_object(id_tamper, "HiddenSuiteIdentityEnvelope").get("ok"):
            undetected.append("suite_identity_sha256")
        if not consumer_rejected(id_tamper):
            undetected.append("consumer:suite_identity_sha256")

        empty_bind = dict(base)
        empty_bind["realized_manifest_binding"] = ""
        empty_bind["suite_identity_sha256"] = recompute_suite_identity_sha256(empty_bind)
        if validate_object(empty_bind, "HiddenSuiteIdentityEnvelope").get("ok"):
            undetected.append("empty_realized_binding")
        if not consumer_rejected(empty_bind):
            undetected.append("consumer:empty_realized_binding")

        for name, candidate in (
            ("schema_version", {**base, "schema_version": "xinao.invalid.v1"}),
            ("object", {**base, "object": "OtherObject"}),
            ("extra_field", {**base, "unbound_extra": True}),
        ):
            if not consumer_rejected(candidate):
                undetected.append(f"consumer:{name}")
        return _deny(not undetected, "suite_identity_field_tamper_rejected")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_drifted_registration() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RotationRevocationRegistry(root / "rot.json")
        bad_suite, _bad_ledger, _bad_seal = _suite_envelope(root, "syn", {"x": 1})
        bad = reg.register_identity(
            identity_kind="HiddenSuiteIdentityEnvelope",
            public_label="syn",
            commitment_inputs=hidden_suite_registration_commitment_inputs(bad_suite),
            suite_identity_sha256="f" * 64,  # arbitrary drifted hash
            suite_envelope=bad_suite,
        )
        # rotation with drifted new identity
        good_inputs = {"x": 2}
        good_suite, good_ledger, good_seal = _suite_envelope(root, "syn", good_inputs)
        good_sha = good_suite["suite_identity_sha256"]
        _register_suite(reg, good_suite, good_ledger, good_seal)
        rotated_suite, _rot_ledger, _rot_seal = _suite_envelope(
            root, "syn-rot", {"y": 3}, rotated_from=good_sha
        )
        rot_bad = reg.rotate(
            old_identity_sha256=good_sha,
            public_label="syn-rot",
            commitment_inputs=hidden_suite_registration_commitment_inputs(rotated_suite),
            identity_kind="HiddenSuiteIdentityEnvelope",
            new_suite_identity_sha256="e" * 64,
            new_suite_envelope=rotated_suite,
        )
        return _deny(
            bad.get("ok") is False
            and bad.get("reason") == "identity_hash_mismatch_or_drifted"
            and rot_bad.get("ok") is False
            and rot_bad.get("reason") == "identity_hash_mismatch_or_drifted",
            "drifted_suite_identity_registration_rejected",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_underbound_hidden_suite_registration() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RotationRevocationRegistry(root / "rot.json")
        out = reg.register_identity(
            identity_kind="HiddenSuiteIdentityEnvelope",
            public_label="syn",
            commitment_inputs={"x": 1},
            suite_identity_sha256="f" * 64,
        )
        return _deny(
            out.get("ok") is False and out.get("reason") == "full_suite_envelope_required",
            "underbound_hidden_suite_registration_rejected",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_claim_revoke_start_toctou() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RotationRevocationRegistry(root / "rot.json")
        inputs = {"toctou": 1}
        suite, ledger_path, seal_path = _suite_envelope(root, "syn-toctou", inputs)
        sha = suite["suite_identity_sha256"]
        _register_suite(reg, suite, ledger_path, seal_path)
        idem = RunIdempotencyRegistry(root / "idem.json", state=reg.state)
        claim = idem.claim_run(
            run_id="run-toctou",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=sha,
        )
        assert claim.get("ok")
        # Revoke after claim, before side-effect start
        rev = reg.revoke(identity_sha256=sha, reason="post_claim_revoke")
        assert rev.get("ok")
        start = idem.mark_side_effect_started(run_id="run-toctou")
        # Must deny start; no start flag set
        st = idem.status()
        return _deny(
            start.get("ok") is False
            and start.get("reason") == "revoked_suite_cannot_start_side_effect"
            and st.get("side_effect_started_count") == 0
            and st.get("side_effect_count") == 0,
            "claim_revoke_start_toctou",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_mount_vault_ancestor() -> dict[str, Any]:
    root = _tmp_root()
    try:
        vault = root / "vault"
        evaluator = root / "evaluator"
        # Offline runner only admits /output and /state host mounts.
        work = root / "promptfoo" / "output"
        vault.mkdir(parents=True)
        evaluator.mkdir(parents=True)
        work.mkdir(parents=True)
        (vault / "sealed.txt").write_text("x", encoding="utf-8")
        denied = [vault, evaluator]
        allowed = [work]
        # vault itself
        v1 = validate_mount_boundary(
            source=vault,
            dest="/output",
            mode="rw",
            allowed_roots=allowed + [vault],
            denied_roots=denied,
        )
        # parent containing vault
        v2 = validate_mount_boundary(
            source=root,
            dest="/output",
            mode="rw",
            allowed_roots=[root],
            denied_roots=denied,
        )
        # sibling ok
        v3 = validate_mount_boundary(
            source=work,
            dest="/output",
            mode="rw",
            allowed_roots=allowed,
            denied_roots=denied,
        )
        # unexpected dest
        v4 = validate_mount_boundary(
            source=work,
            dest="/vault",
            mode="ro",
            allowed_roots=allowed,
            denied_roots=denied,
        )
        # unexpected mode for /output
        v5 = validate_mount_boundary(
            source=work,
            dest="/output",
            mode="ro",
            allowed_roots=allowed,
            denied_roots=denied,
        )
        # prefix confusion: work_evil next to work should not match work allow root via string prefix
        evil = root / "promptfoo" / "output_evil"
        evil.mkdir(parents=True)
        v6 = validate_mount_boundary(
            source=evil,
            dest="/output",
            mode="rw",
            allowed_roots=allowed,
            denied_roots=denied,
        )
        # executable input mounts are no longer admitted destinations
        v7 = validate_mount_boundary(
            source=work,
            dest="/work",
            mode="ro",
            allowed_roots=allowed,
            denied_roots=denied,
        )
        return _deny(
            v1.get("ok") is False
            and v2.get("ok") is False
            and v3.get("ok") is True
            and v4.get("ok") is False
            and v5.get("ok") is False
            and v6.get("ok") is False
            and v7.get("ok") is False,
            "mount_vault_and_ancestor_denied",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_transient_cleanup_fail_closed() -> dict[str, Any]:
    root = _tmp_root()
    try:
        state = root / "state"
        state.mkdir(parents=True)
        (state / "promptfoo.db").write_text("x", encoding="utf-8")
        cache = state / "cache"
        cache.mkdir()
        (cache / "x.bin").write_text("y", encoding="utf-8")
        cleanup = clean_promptfoo_transients(state)
        inv_ok = inventory_forbidden_transients(state)
        # Inject retained cache after cleanup and require inventory fail
        rogue = state / ".pytest_cache"
        rogue.mkdir()
        (rogue / "v").write_text("1", encoding="utf-8")
        inv_bad = inventory_forbidden_transients(state)
        # Deletion-failure simulation: mark a file read-only inaccessible if possible
        # At minimum, inventory must fail-closed on retained cache.
        return _deny(
            cleanup.get("ok") is True
            and inv_ok.get("ok") is True
            and inv_bad.get("ok") is False
            and len(inv_bad.get("retained") or []) > 0,
            "transient_cleanup_fail_closed",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_promptfoo_result_completeness() -> dict[str, Any]:
    root = _tmp_root()
    try:
        from .objects import expected_public_case_ids

        expected = expected_public_case_ids()
        out = root / "out.json"

        def write_rows(rows: list[dict[str, Any]]) -> None:
            out.write_text(
                json.dumps({"results": {"results": rows}}, sort_keys=True),
                encoding="utf-8",
            )

        # zero rows
        write_rows([])
        z = parse_promptfoo_results(out, expected_ids=expected)
        # missing one
        write_rows(
            [
                {"vars": {"public_case_id": cid}, "success": True, "failureReason": 0}
                for cid in expected[:-1]
            ]
        )
        missing = parse_promptfoo_results(out, expected_ids=expected)
        # duplicate
        rows = [
            {"vars": {"public_case_id": cid}, "success": True, "failureReason": 0}
            for cid in expected
        ]
        rows.append({"vars": {"public_case_id": expected[0]}, "success": True, "failureReason": 0})
        write_rows(rows)
        dup = parse_promptfoo_results(out, expected_ids=expected)
        # unexpected
        rows = [
            {"vars": {"public_case_id": cid}, "success": True, "failureReason": 0}
            for cid in expected[:-1]
        ]
        rows.append(
            {"vars": {"public_case_id": "syn-EVIL-001"}, "success": True, "failureReason": 0}
        )
        write_rows(rows)
        unexpected = parse_promptfoo_results(out, expected_ids=expected)
        # cached
        rows = [
            {
                "vars": {"public_case_id": cid},
                "success": True,
                "failureReason": 0,
                "response": {"cached": cid == expected[0], "output": "x"},
            }
            for cid in expected
        ]
        write_rows(rows)
        cached = parse_promptfoo_results(out, expected_ids=expected)
        # row error
        rows = [
            {
                "vars": {"public_case_id": cid},
                "success": cid != expected[0],
                "failureReason": 1 if cid == expected[0] else 0,
                "error": "boom" if cid == expected[0] else None,
            }
            for cid in expected
        ]
        write_rows(rows)
        err = parse_promptfoo_results(out, expected_ids=expected)
        # parse drift
        out.write_text("{not-json", encoding="utf-8")
        drift = parse_promptfoo_results(out, expected_ids=expected)
        # good complete set
        write_rows(
            [
                {"vars": {"public_case_id": cid}, "success": True, "failureReason": 0}
                for cid in expected
            ]
        )
        good = parse_promptfoo_results(out, expected_ids=expected)
        return _deny(
            z.get("ok") is False
            and missing.get("ok") is False
            and dup.get("ok") is False
            and unexpected.get("ok") is False
            and cached.get("ok") is False
            and err.get("ok") is False
            and drift.get("ok") is False
            and good.get("ok") is True,
            "promptfoo_result_completeness_negatives",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_claim_revoke_direct_finalize_toctou() -> dict[str, Any]:
    root = _tmp_root()
    try:
        reg = RotationRevocationRegistry(root / "rot.json")
        suite, ledger_path, seal_path = _suite_envelope(
            root, "syn-finalize-toctou", {"toctou": "finalize"}
        )
        sha = suite["suite_identity_sha256"]
        _register_suite(reg, suite, ledger_path, seal_path)
        idem = RunIdempotencyRegistry(root / "idem.json", state=reg.state)
        claim = idem.claim_run(
            run_id="run-finalize-toctou",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=sha,
        )
        assert claim.get("ok")
        reg.revoke(identity_sha256=sha, reason="post_claim_pre_finalize")
        finalized = idem.mark_side_effect(run_id="run-finalize-toctou")
        status = idem.status()
        return _deny(
            finalized.get("ok") is False
            and status.get("side_effect_started_count") == 0
            and status.get("side_effect_count") == 0,
            "claim_revoke_direct_finalize_toctou",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_invented_exposure_head_without_seal() -> dict[str, Any]:
    root = _tmp_root()
    try:
        suite = build_hidden_suite_identity_envelope(
            public_suite_label="invented-head",
            schedule_slots=["H01"],
            synthetic_salt="invented",
            public_manifest_blueprint_commitment="b" * 64,
            realized_manifest_binding="c" * 64,
            exposure_ledger_sealed_head_contract="e" * 64,
        )
        reg = RotationRevocationRegistry(root / "rot.json")
        admitted = reg.register_identity(
            identity_kind="HiddenSuiteIdentityEnvelope",
            public_label=suite["public_suite_label"],
            commitment_inputs=hidden_suite_registration_commitment_inputs(suite),
            suite_identity_sha256=suite["suite_identity_sha256"],
            suite_envelope=suite,
        )
        return _deny(
            admitted.get("ok") is False
            and admitted.get("reason") == "verified_exposure_ledger_and_seal_required",
            "invented_exposure_head_without_corresponding_ledger_seal",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_lexical_reparse_ancestor_mount() -> dict[str, Any]:
    root = _tmp_root()
    try:
        source = root / "lexical_link" / "child"
        source.mkdir(parents=True)
        # Deterministically emulate the Windows reparse attribute on the
        # lexical ancestor. If normalize resolved first, this marker vanishes.
        from . import promptfoo_runner as runner

        original = runner._is_reparse_point
        runner._is_reparse_point = lambda path: Path(path).name == "lexical_link"
        try:
            check = normalize_host_mount_source(source)
        finally:
            runner._is_reparse_point = original
        return _deny(
            check.get("ok") is False
            and check.get("reason") == "mount_source_reparse_or_symlink_ancestor",
            "lexical_reparse_ancestor_checked_before_resolution",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_config_local_adapter_shadow() -> dict[str, Any]:
    root = _tmp_root()
    try:
        config_dir = root / "config"
        adapter = root / "trusted_adapter.py"
        adapter.write_text(
            "def call_api(prompt, options, context): return {'output': prompt}\n", encoding="utf-8"
        )
        cases = root / "cases.jsonl"
        cases.write_text(
            json.dumps(
                {
                    "public_case_id": "syn-H01-001",
                    "public_prompt": "synthetic",
                    "commitment_sha256": "c" * 64,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        built = build_promptfoo_config(
            config_dir=config_dir,
            adapter_path=adapter,
            cases_path=cases,
        )
        config_text = Path(built["config_path"]).read_text(encoding="utf-8")
        return _deny(
            "python:/adapter/promptfoo_subject_adapter.py" in config_text
            and not (config_dir / "promptfoo_subject_adapter.py").exists(),
            "config_local_adapter_shadow_removed_and_provider_bound_to_ro_mount",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_container_cleanup_failure_hidden_by_success() -> dict[str, Any]:
    failed_closed = False
    try:
        require_terminal_container_cleanup({"ok": False, "absent": False})
    except RuntimeError:
        failed_closed = True
    require_terminal_container_cleanup({"ok": True, "absent": True})
    return _deny(failed_closed, "container_cleanup_failure_is_terminal")


def _case_promptfoo_provider_comment_or_secondary_bypass() -> dict[str, Any]:
    root = _tmp_root()
    try:
        # Trusted string only in a comment while evil provider is selected.
        cfg_comment = root / "comment" / "promptfooconfig.yaml"
        cfg_comment.parent.mkdir(parents=True)
        cfg_comment.write_text(
            "\n".join(
                [
                    f"# id: {TRUSTED_PROVIDER_ID}",
                    "description: 'bypass'",
                    "providers:",
                    "  - id: 'python:/work/evil.py'",
                    "    config:",
                    "      pythonExecutable: '/usr/bin/python3'",
                    "prompts:",
                    "  - '{{public_prompt}}'",
                    "tests: file://public_cases.json",
                    "evaluateOptions:",
                    "  cache: false",
                    "  maxConcurrency: 1",
                    "commandLineOptions:",
                    "  cache: false",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        v_comment = validate_promptfoo_config_providers(cfg_comment)

        cfg_secondary = root / "secondary" / "promptfooconfig.yaml"
        cfg_secondary.parent.mkdir(parents=True)
        cfg_secondary.write_text(
            "\n".join(
                [
                    "description: 'secondary'",
                    "providers:",
                    f"  - id: '{TRUSTED_PROVIDER_ID}'",
                    "    config:",
                    "      pythonExecutable: '/usr/bin/python3'",
                    "  - id: 'python:/work/evil.py'",
                    "    config:",
                    "      pythonExecutable: '/usr/bin/python3'",
                    "prompts:",
                    "  - '{{public_prompt}}'",
                    "tests: file://public_cases.json",
                    "evaluateOptions:",
                    "  cache: false",
                    "  maxConcurrency: 1",
                    "commandLineOptions:",
                    "  cache: false",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        v_secondary = validate_promptfoo_config_providers(cfg_secondary)

        cfg_inert = root / "inert" / "promptfooconfig.yaml"
        cfg_inert.parent.mkdir(parents=True)
        cfg_inert.write_text(
            "\n".join(
                [
                    f"description: '{TRUSTED_PROVIDER_ID}'",
                    "providers:",
                    "  - id: 'python:/work/evil.py'",
                    "    config:",
                    "      pythonExecutable: '/usr/bin/python3'",
                    "prompts:",
                    "  - '{{public_prompt}}'",
                    "tests: file://public_cases.json",
                    "evaluateOptions:",
                    "  cache: false",
                    "  maxConcurrency: 1",
                    "commandLineOptions:",
                    "  cache: false",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        v_inert = validate_promptfoo_config_providers(cfg_inert)

        denied = (
            v_comment.get("ok") is False
            and v_secondary.get("ok") is False
            and v_inert.get("ok") is False
        )
        return _deny(denied, "promptfoo_provider_comment_or_secondary_bypass")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_promptfoo_provider_work_evil_selected() -> dict[str, Any]:
    root = _tmp_root()
    try:
        (root / "evil.py").write_text(
            "def call_api(p,o,c): return {'output': p}\n", encoding="utf-8"
        )
        cfg = root / "promptfooconfig.yaml"
        cfg.write_text(
            "\n".join(
                [
                    f"description: 'contains {TRUSTED_PROVIDER_ID} only as text'",
                    "providers:",
                    "  - id: 'python:/work/evil.py'",
                    "    config:",
                    "      pythonExecutable: '/usr/bin/python3'",
                    "prompts:",
                    "  - '{{public_prompt}}'",
                    "tests: file://public_cases.json",
                    "evaluateOptions:",
                    "  cache: false",
                    "  maxConcurrency: 1",
                    "commandLineOptions:",
                    "  cache: false",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        v = validate_promptfoo_config_providers(cfg)
        return _deny(
            v.get("ok") is False
            and v.get("reason")
            in {
                "untrusted_work_python_provider_surface_present",
                "promptfoo_provider_not_trusted_adapter_descriptor",
            },
            "promptfoo_provider_work_evil_selected",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_promptfoo_test_case_provider_override() -> dict[str, Any]:
    root = _tmp_root()
    try:
        adapter = root / "trusted_adapter.py"
        adapter.write_text(
            "def call_api(prompt, options, context): return {'output': prompt}\n",
            encoding="utf-8",
        )
        source_cases = root / "cases.jsonl"
        source_cases.write_text(
            json.dumps(
                {
                    "public_case_id": "syn-H01-001",
                    "public_prompt": "synthetic",
                    "commitment_sha256": "c" * 64,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        built = build_promptfoo_config(
            config_dir=root / "config",
            adapter_path=adapter,
            cases_path=source_cases,
        )
        cases_path = Path(built["cases_json"])
        rows = json.loads(cases_path.read_text(encoding="utf-8"))
        rows[0]["provider"] = "python:/work/evil.py"
        cases_path.write_text(json.dumps(rows), encoding="utf-8")
        config_v = validate_promptfoo_config_providers(Path(built["config_path"]))
        cases_v = validate_promptfoo_public_cases(cases_path, expected_case_ids=["syn-H01-001"])
        return _deny(
            config_v.get("ok") is True
            and cases_v.get("ok") is False
            and cases_v.get("reason") == "promptfoo_public_case_row_schema_mismatch",
            "promptfoo_test_case_provider_override",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_vault_partial_acl_lift_not_restored() -> dict[str, Any]:
    import subprocess as sp

    root = _tmp_root()
    try:
        vault = SealedTruthVault(root / "vault")
        vault.deposit_synthetic(
            public_case_id="syn-H01-001",
            public_prompt="p",
            truth={"answer": "A"},
            scoring_rule_private={"rule": "eq"},
            family_slot="H01",
            schedule_class="structural",
        )
        locked = vault.lock_down_host_reads(expected_receipt=False)
        if not locked.get("ok"):
            return _deny(False, "vault_lockdown_setup_failed")
        targets = vault._controlled_vault_targets(expected_receipt=False)
        real_run = sp.run
        outcomes: list[bool] = []

        def _inject(mode: str) -> None:
            state = {"n": 0}

            def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                if len(argv) >= 3 and argv[0] == "icacls" and argv[2] == "/remove:d":
                    state["n"] += 1
                    if state["n"] == 1:
                        return real_run(argv, **kwargs)
                    if mode == "nonzero":
                        return sp.CompletedProcess(argv, 7, b"", b"fail")
                    if mode == "exception":
                        raise RuntimeError("injected_lift_exception")
                    raise sp.TimeoutExpired(cmd=argv, timeout=30)
                return real_run(argv, **kwargs)

            original = sp.run
            sp.run = fake_run  # type: ignore[assignment]
            try:
                try:
                    vault._read_truth_unlocked(expected_receipt=False)
                    outcomes.append(False)
                except (PermissionError, RuntimeError):
                    verify = vault._verify_direct_denial(targets=targets)
                    outcomes.append(bool(verify.get("denied")))
            finally:
                sp.run = original  # type: ignore[assignment]

        for mode in ("nonzero", "exception", "timeout"):
            _inject(mode)
        return _deny(all(outcomes) and len(outcomes) == 3, "vault_partial_acl_lift_restored")
    finally:
        try:
            vault = SealedTruthVault(root / "vault")
            vault.unlock_host_reads(expected_receipt=False)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(root, ignore_errors=True)


def _case_run_claim_transition_state_tamper() -> dict[str, Any]:
    import sqlite3

    root = _tmp_root()
    try:
        reg = RunIdempotencyRegistry(root / "i.json", max_attempts=8)
        suite, ledger_path, seal_path = _suite_envelope(root, "tamper-st", {"a": 1})
        _register_suite(reg.state, suite, ledger_path, seal_path)
        claim = reg.claim_run(
            run_id="r1",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=suite["suite_identity_sha256"],
        )
        assert claim["ok"]
        # Coordinated status+flag mutation leaving original claim hash untouched.
        with sqlite3.connect(reg.db_path) as conn:
            conn.execute(
                "UPDATE run_claims SET status='side_effect_started', "
                "side_effect_started=1 WHERE run_id=?",
                ("r1",),
            )
        fin = reg.mark_side_effect(run_id="r1")
        coordinated_denied = (
            fin.get("ok") is False and fin.get("reason") == "start_transition_integrity_failed"
        )

        claim2 = reg.claim_run(
            run_id="r2",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=suite["suite_identity_sha256"],
        )
        assert claim2["ok"]
        start = reg.mark_side_effect_started(run_id="r2")
        assert start["ok"]
        with sqlite3.connect(reg.db_path) as conn:
            conn.execute(
                "UPDATE run_claims SET start_transition_sha256=? WHERE run_id=?",
                ("f" * 64, "r2"),
            )
        fin2 = reg.mark_side_effect(run_id="r2")
        forged_denied = (
            fin2.get("ok") is False and fin2.get("reason") == "start_transition_integrity_failed"
        )

        claim3 = reg.claim_run(
            run_id="r3",
            attempt_id="a1",
            route_identity_sha256="r" * 64,
            suite_identity_sha256=suite["suite_identity_sha256"],
        )
        assert claim3["ok"]
        start3 = reg.mark_side_effect_started(run_id="r3")
        assert start3["ok"]
        fin3 = reg.mark_side_effect(run_id="r3")
        happy = fin3.get("ok") is True
        return _deny(
            coordinated_denied and forged_denied and happy,
            "run_claim_transition_state_tamper",
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_exposure_entry_schema_drift() -> dict[str, Any]:
    from .exposure_ledger import validate_exposure_entry_body

    good = {
        "principal_id": "p",
        "role": "subject",
        "exposure_subject_identity_sha256": "a" * 64,
        "exposure_kind": "public_case_id",
        "object_ref": "x",
        "note": "",
        "synthetic_only": True,
        "not_admission_evidence": True,
    }
    bad_extra = dict(good)
    bad_extra["authority"] = True
    bad_flag = dict(good)
    bad_flag["synthetic_only"] = False
    denied = (
        validate_exposure_entry_body(good).get("ok") is True
        and validate_exposure_entry_body(bad_extra).get("ok") is False
        and validate_exposure_entry_body(bad_flag).get("ok") is False
    )
    return _deny(denied, "exposure_entry_schema_drift")


def _case_promptfoo_expected_bindings_mandatory() -> dict[str, Any]:
    """Missing/blank expected bindings must fail before docker create."""
    good_ids = ["syn-H01-001"]
    miss_config = _require_expected_bindings(
        expected_config_sha256=None,
        expected_cases_sha256="a" * 64,
        expected_case_ids=good_ids,
        expected_adapter_sha256="b" * 64,
    )
    miss_cases = _require_expected_bindings(
        expected_config_sha256="a" * 64,
        expected_cases_sha256="",
        expected_case_ids=good_ids,
        expected_adapter_sha256="b" * 64,
    )
    miss_ids = _require_expected_bindings(
        expected_config_sha256="a" * 64,
        expected_cases_sha256="b" * 64,
        expected_case_ids=None,
        expected_adapter_sha256="c" * 64,
    )
    blank_id = _require_expected_bindings(
        expected_config_sha256="a" * 64,
        expected_cases_sha256="b" * 64,
        expected_case_ids=["  "],
        expected_adapter_sha256="c" * 64,
    )
    ok = _require_expected_bindings(
        expected_config_sha256="a" * 64,
        expected_cases_sha256="b" * 64,
        expected_case_ids=good_ids,
        expected_adapter_sha256="c" * 64,
    )
    denied = (
        miss_config.get("ok") is False
        and miss_cases.get("ok") is False
        and miss_ids.get("ok") is False
        and blank_id.get("ok") is False
        and ok.get("ok") is True
        and "expected_config_sha256" in (miss_config.get("missing") or [])
    )
    return _deny(denied, "promptfoo_expected_bindings_mandatory")


def _case_promptfoo_private_snapshot_toctou() -> dict[str, Any]:
    """Stage must not live under state; host swap before copy fails digest check."""
    from .canonical import sha256_hex
    from .promptfoo_runner import _docker_cp_file

    root = _tmp_root()
    try:
        state = root / "state"
        state.mkdir()
        # State-root adapter alias is forbidden for private snapshot staging.
        alias = state / "adapter_mount" / "promptfoo_subject_adapter.py"
        alias.parent.mkdir(parents=True)
        alias.write_text("# alias\n", encoding="utf-8")
        state_alias_present = alias.is_file()

        stage = root / ".private_exec_snapshot"
        stage.mkdir()
        host = stage / "promptfooconfig.yaml"
        good = b"trusted-config-bytes\n"
        host.write_bytes(good)
        digest = sha256_hex(good)
        # Host swap between validation digest and copy must fail closed.
        host.write_bytes(b"swapped-after-validation\n")
        swapped = _docker_cp_file(
            container_id="nonexistent-container-for-digest-gate",
            host_path=host,
            container_path="/work/promptfooconfig.yaml",
            expected_sha256=digest,
        )
        # Restore and prove good digest is accepted at the pre-copy gate
        # (docker itself may still fail; only the digest gate is asserted here).
        host.write_bytes(good)
        restored = _docker_cp_file(
            container_id="nonexistent-container-for-digest-gate",
            host_path=host,
            container_path="/work/promptfooconfig.yaml",
            expected_sha256=digest,
        )
        # Explicit provider-bearing case still rejected by public cases schema.
        cases = stage / "public_cases.json"
        cases.write_text(
            json.dumps(
                [
                    {
                        "vars": {
                            "public_case_id": "syn-H01-001",
                            "public_prompt": "p",
                            "commitment_sha256": "c" * 64,
                        },
                        "provider": "python:/work/evil.py",
                    }
                ]
            ),
            encoding="utf-8",
        )
        provider_case = validate_promptfoo_public_cases(cases, expected_case_ids=["syn-H01-001"])
        unexpected_exec_mount = validate_mount_boundary(
            source=stage,
            dest="/adapter",
            mode="ro",
            allowed_roots=[stage],
            denied_roots=[],
        )
        denied = (
            state_alias_present
            and swapped.get("ok") is False
            and swapped.get("reason") == "snapshot_host_digest_mismatch_before_copy"
            and restored.get("reason") == "docker_cp_failed"
            and provider_case.get("ok") is False
            and provider_case.get("reason") == "promptfoo_public_case_row_schema_mismatch"
            and unexpected_exec_mount.get("ok") is False
        )
        return _deny(denied, "promptfoo_private_snapshot_toctou")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _case_vault_deny_ace_restore_ambiguous_open() -> dict[str, Any]:
    """Ambiguous open failures must not prove ACE restoration."""
    import subprocess as sp

    root = _tmp_root()
    try:
        vault = SealedTruthVault(root / "vault")
        vault.deposit_synthetic(
            public_case_id="syn-H01-001",
            public_prompt="p",
            truth={"answer": "A"},
            scoring_rule_private={"rule": "eq"},
            family_slot="H01",
            schedule_class="structural",
        )
        targets = vault._controlled_vault_targets(expected_receipt=False)
        real_run = sp.run
        outcomes: list[bool] = []

        def _inject_deny_fail(open_exc: BaseException) -> bool:
            def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                if len(argv) >= 3 and argv[0] == "icacls" and argv[2] == "/deny":
                    return sp.CompletedProcess(argv, 9, b"", b"deny-failed")
                if len(argv) >= 2 and argv[0] == "icacls" and "/deny" not in argv:
                    # ACE listing after failed deny: report no DENY ACE.
                    return sp.CompletedProcess(argv, 0, b"file: user:(F)\n", b"")
                return real_run(argv, **kwargs)

            original_open = Path.open

            def fake_open(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                if self.name in {p.name for p in targets} or any(
                    str(self) == str(p) for p in targets
                ):
                    raise open_exc
                return original_open(self, *args, **kwargs)

            sp.run = fake_run  # type: ignore[assignment]
            Path.open = fake_open  # type: ignore[assignment]
            try:
                apply = vault._icacls_deny_current_user(targets=targets)
                verify = vault._verify_direct_denial(targets=targets)
                # Neither apply nor verify may claim success from ambiguous opens.
                return apply.get("ok") is False and verify.get("denied") is not True
            finally:
                sp.run = real_run  # type: ignore[assignment]
                Path.open = original_open  # type: ignore[method-assign]

        # Sharing violation
        share = OSError(32, "sharing")
        share.winerror = 32  # type: ignore[attr-defined]
        outcomes.append(_inject_deny_fail(share))
        # FileNotFoundError
        outcomes.append(_inject_deny_fail(FileNotFoundError(2, "missing")))
        # Arbitrary OSError
        outcomes.append(_inject_deny_fail(OSError("disk")))
        # Injected PermissionError without Windows access-denied identity
        outcomes.append(_inject_deny_fail(PermissionError("injected")))

        # Positive real icacls path for all controlled vault files.
        locked = vault.lock_down_host_reads(expected_receipt=False)
        positive = (
            locked.get("ok") is True
            and locked.get("isolation_enforced") is True
            and locked.get("acl_restore_verified") is True
        )
        if positive:
            verify = vault._verify_direct_denial(targets=targets)
            positive = verify.get("denied") is True and all(
                (row.get("deny_ace_present") is True) or row.get("skipped") == "missing"
                for row in (verify.get("per_file") or [])
            )
        return _deny(
            all(outcomes) and len(outcomes) == 4 and positive,
            "vault_deny_ace_restore_ambiguous_open",
        )
    finally:
        try:
            SealedTruthVault(root / "vault").unlock_host_reads(expected_receipt=False)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(root, ignore_errors=True)


def _case_exposure_admission_multi_snapshot_toctou() -> dict[str, Any]:
    """Schema-invalid sealed snapshot cannot borrow later schema-valid bodies."""
    import sqlite3

    from .canonical import canonical_json_sha256
    from .exposure_ledger import verify_exposure_admission_evidence
    from .hash_chain import GENESIS_PREV, HashChainedLog

    root = _tmp_root()
    try:
        suite, ledger_path, seal_path = _suite_envelope(root, "snap-toctou", {"k": "v"})
        valid_bytes = ledger_path.read_bytes()
        valid_seal_bytes = seal_path.read_bytes()
        # Build a chain-valid but schema-invalid alternate body snapshot.
        invalid_body = {
            "principal_id": "negative_fixture_subject",
            "role": "subject",
            "exposure_subject_identity_sha256": suite["exposure_subject_identity_sha256"],
            "exposure_kind": "public_case_id",
            "object_ref": "negative_fixture_public_schedule",
            "note": "",
            "synthetic_only": True,
            "not_admission_evidence": True,
            "authority": True,  # forbidden authority-bearing field
        }
        sealed = {
            "log_kind": "exposure_ledger.v1",
            "entry_index": 0,
            "prev_sha256": GENESIS_PREV,
            "body": invalid_body,
        }
        entry_sha = canonical_json_sha256(sealed)
        invalid_record = {**sealed, "entry_sha256": entry_sha}
        invalid_line = json.dumps(invalid_record, sort_keys=True, separators=(",", ":")) + "\n"
        invalid_bytes = invalid_line.encode("utf-8")

        # Align on-disk lock + seal with the invalid chain so only schema (or a
        # later multi-read body swap) could admit. Single-snapshot must deny.
        lock_db = Path(str(ledger_path) + ".lock.sqlite3")
        with sqlite3.connect(str(lock_db)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO log_meta(key, value) VALUES('head_sha256', ?)",
                (entry_sha,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO log_meta(key, value) VALUES('length', ?)",
                ("1",),
            )
            conn.execute("COMMIT")
        seal = json.loads(valid_seal_bytes.decode("utf-8"))
        seal["expected_head_sha256"] = entry_sha
        seal["expected_length"] = 1
        seal["seal_sha256"] = canonical_json_sha256(
            {k: v for k, v in seal.items() if k != "seal_sha256"}
        )
        seal_bytes = json.dumps(
            seal, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        seal_path.write_bytes(seal_bytes)
        invalid_suite = dict(suite)
        invalid_suite["exposure_ledger_sealed_head_contract"] = entry_sha

        reads = {"ledger": 0, "seal": 0}

        def reader_alt(path: Path) -> bytes:
            p = Path(path)
            if p.resolve() == ledger_path.resolve():
                reads["ledger"] += 1
                # First read: schema-invalid sealed snapshot. A multi-snapshot
                # verifier would re-read and obtain schema-valid bodies.
                if reads["ledger"] == 1:
                    return invalid_bytes
                return valid_bytes
            if p.resolve() == seal_path.resolve():
                reads["seal"] += 1
                return seal_bytes
            return p.read_bytes()

        result = verify_exposure_admission_evidence(
            suite_envelope=invalid_suite,
            state_dir=ledger_path.parent,
            ledger_path=ledger_path,
            seal_path=seal_path,
            file_reader=reader_alt,
        )
        schema_fail = (
            result.get("ok") is False
            and result.get("reason") == "exposure_entry_payload_schema_invalid"
        )
        single_ledger_read = reads["ledger"] == 1

        # Restore valid on-disk ledger/seal/lock for the positive path.
        ledger_path.write_bytes(valid_bytes)
        seal_path.write_bytes(valid_seal_bytes)
        valid_head = json.loads(valid_bytes.decode("utf-8").strip())["entry_sha256"]
        with sqlite3.connect(str(lock_db)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO log_meta(key, value) VALUES('head_sha256', ?)",
                (valid_head,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO log_meta(key, value) VALUES('length', ?)",
                ("1",),
            )
            conn.execute("COMMIT")

        reads["ledger"] = 0
        reads["seal"] = 0

        def reader_ok(path: Path) -> bytes:
            p = Path(path)
            if p.resolve() == ledger_path.resolve():
                reads["ledger"] += 1
                return valid_bytes
            if p.resolve() == seal_path.resolve():
                reads["seal"] += 1
                return valid_seal_bytes
            return p.read_bytes()

        ok_result = verify_exposure_admission_evidence(
            suite_envelope=suite,
            state_dir=ledger_path.parent,
            ledger_path=ledger_path,
            seal_path=seal_path,
            file_reader=reader_ok,
        )
        # Append/truncate and relocation-style empty negatives.
        append_path = root / "append.jsonl"
        append_path.write_bytes(valid_bytes + b'{"evil":true}\n')
        append_chain = HashChainedLog.verify_from_bytes(
            append_path.read_bytes(), log_kind="exposure_ledger.v1"
        )
        trunc_chain = HashChainedLog.verify_from_bytes(b"", log_kind="exposure_ledger.v1")
        denied = (
            schema_fail
            and single_ledger_read
            and ok_result.get("ok") is True
            and ok_result.get("ledger_content_reads") == 1
            and reads["ledger"] == 1
            and append_chain.get("ok") is False
            and trunc_chain.get("ok") is True
            and trunc_chain.get("length") == 0
        )
        return _deny(denied, "exposure_admission_multi_snapshot_toctou")
    finally:
        shutil.rmtree(root, ignore_errors=True)


_CASE_FNS: dict[str, Callable[[], dict[str, Any]]] = {
    "vault_read_by_subject": _case_vault_read_by_subject,
    "vault_locator_or_truth_token_in_public": _case_vault_in_public,
    "commitment_input_drift": _case_commitment_drift,
    "training_heldout_collision": _case_training_heldout_collision,
    "duplicate_run_id_second_side_effect": _case_duplicate_run_id,
    "revoked_suite_start": _case_revoked_suite_start,
    "exposure_ledger_rewrite_delete_reorder": _case_exposure_ledger_tamper,
    "audit_log_truncation_tamper": _case_audit_log_tamper,
    "route_identity_drift": _case_route_identity_drift,
    "promptfoo_cache_enabled": _case_promptfoo_cache_enabled,
    "scorer_enabled": _case_scorer_enabled,
    "hidden_case_consumed": _case_hidden_case_consumed,
    "timeout_kill_promoted_to_pass": _case_timeout_promoted,
    "provider_scorer_error_truth_leak": _case_error_truth_leak,
    "authority_g4_g5_final_report_write_spoof": _case_authority_spoof,
    "synthetic_fixture_claimed_as_real_h01_h14": _case_synthetic_as_real,
    "whole_chain_rewrite_detected": _case_whole_chain_rewrite,
    "use_time_revocation_race": _case_use_time_revocation,
    "image_digest_drift": _case_image_digest_drift,
    "forbidden_mount_env_injection": _case_forbidden_mount_env,
    "cas_concurrent_duplicate_rejected": _case_cas_concurrent_duplicate,
    "envelope_field_mutation_changes_identity": _case_envelope_mutation,
    "immutable_run_envelope_field_tamper": _case_immutable_run_envelope_tamper,
    "suite_identity_field_tamper_rejected": _case_suite_identity_field_tamper,
    "drifted_suite_identity_registration_rejected": _case_drifted_registration,
    "underbound_hidden_suite_registration_rejected": _case_underbound_hidden_suite_registration,
    "claim_revoke_start_toctou": _case_claim_revoke_start_toctou,
    "mount_vault_and_ancestor_denied": _case_mount_vault_ancestor,
    "transient_cleanup_fail_closed": _case_transient_cleanup_fail_closed,
    "promptfoo_result_completeness_negatives": _case_promptfoo_result_completeness,
    "claim_revoke_direct_finalize_toctou": _case_claim_revoke_direct_finalize_toctou,
    "invented_exposure_head_without_seal": _case_invented_exposure_head_without_seal,
    "lexical_reparse_ancestor_mount": _case_lexical_reparse_ancestor_mount,
    "config_local_adapter_shadow": _case_config_local_adapter_shadow,
    "container_cleanup_failure_hidden_by_success": _case_container_cleanup_failure_hidden_by_success,
    "promptfoo_provider_comment_or_secondary_bypass": _case_promptfoo_provider_comment_or_secondary_bypass,
    "vault_partial_acl_lift_not_restored": _case_vault_partial_acl_lift_not_restored,
    "run_claim_transition_state_tamper": _case_run_claim_transition_state_tamper,
    "exposure_entry_schema_drift": _case_exposure_entry_schema_drift,
    "promptfoo_provider_work_evil_selected": _case_promptfoo_provider_work_evil_selected,
    "promptfoo_test_case_provider_override": _case_promptfoo_test_case_provider_override,
    "promptfoo_expected_bindings_mandatory": _case_promptfoo_expected_bindings_mandatory,
    "promptfoo_private_snapshot_toctou": _case_promptfoo_private_snapshot_toctou,
    "vault_deny_ace_restore_ambiguous_open": _case_vault_deny_ace_restore_ambiguous_open,
    "exposure_admission_multi_snapshot_toctou": _case_exposure_admission_multi_snapshot_toctou,
}


def run_hard_negatives() -> dict[str, Any]:
    results = []
    for spec in HARD_NEGATIVE_SPECS:
        cid = spec["id"]
        try:
            out = _CASE_FNS[cid]()
        except Exception as exc:  # noqa: BLE001
            out = {"decision": "ERROR", "passed": False, "reason": f"exception:{exc}"}
        results.append(
            {
                "id": cid,
                "expect": spec["expect"],
                "decision": out.get("decision"),
                "passed": bool(out.get("passed")),
                "reason": out.get("reason"),
            }
        )
    all_passed = all(r["passed"] and r["decision"] == "DENY" for r in results)
    return {
        "schema_version": "xinao.g4.hidden_capability_seam.hard_negatives_run.v1",
        "all_passed": all_passed,
        "count": len(results),
        "results": results,
        "authority": False,
        "completion_claim_allowed": False,
        "g4_closed": False,
        "g5_active": False,
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
    }
