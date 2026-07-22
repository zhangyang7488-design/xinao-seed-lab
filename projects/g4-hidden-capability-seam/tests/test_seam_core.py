"""Core unit tests for g4_hidden_capability_seam (stdlib unittest)."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g4_hidden_capability_seam.canonical import (  # noqa: E402
    canonical_json_sha256,
    identity_from_fields,
    read_json,
)
from g4_hidden_capability_seam.exposure_ledger import ExposureLedger  # noqa: E402
from g4_hidden_capability_seam.hard_negatives import run_hard_negatives  # noqa: E402
from g4_hidden_capability_seam.objects import (  # noqa: E402
    H_SLOTS,
    RUN_ENVELOPE_IDENTITY_FIELDS,
    SUITE_IDENTITY_FIELDS,
    SUITE_IDENTITY_MUTATION_FIELDS,
    build_calibration_contract_shape,
    build_heldout_attestation,
    build_hidden_suite_identity_envelope,
    build_immutable_run_envelope,
    build_route_descriptor,
    build_subject_public_manifest,
    hidden_suite_registration_commitment_inputs,
    mutate_suite_field,
    recompute_suite_identity_sha256,
    validate_object,
)


def _suite_envelope(
    root: Path, label: str, inputs: dict, rotated_from: str | None = None
) -> tuple[dict, Path, Path]:
    fixture = {"label": label, "inputs": inputs, "rotated_from": rotated_from}
    kwargs = {
        "public_suite_label": label,
        "schedule_slots": ["H01"],
        "synthetic_salt": canonical_json_sha256({"fixture_salt": fixture}),
        "public_manifest_blueprint_commitment": canonical_json_sha256(
            {"fixture_blueprint": fixture}
        ),
        "realized_manifest_binding": canonical_json_sha256({"fixture_manifest": fixture}),
        "rotated_from": rotated_from,
    }
    preliminary = build_hidden_suite_identity_envelope(**kwargs)
    stem = "fixture_exposure_" + canonical_json_sha256(fixture)[:16]
    ledger_path = root / f"{stem}.jsonl"
    seal_path = root / f"{stem}.seal.json"
    ledger = ExposureLedger(ledger_path)
    ledger.record_exposure(
        principal_id="fixture_subject",
        role="subject",
        exposure_subject_identity_sha256=preliminary["exposure_subject_identity_sha256"],
        exposure_kind="public_case_id",
        object_ref="fixture_public_schedule",
    )
    seal = ledger.log.write_seal_receipt(seal_path)
    suite = build_hidden_suite_identity_envelope(
        **kwargs,
        exposure_ledger_sealed_head_contract=seal["expected_head_sha256"],
    )
    return suite, ledger_path, seal_path


def _register_suite(registry: object, suite: dict, ledger_path: Path, seal_path: Path) -> dict:
    return registry.register_identity(
        identity_kind="HiddenSuiteIdentityEnvelope",
        public_label=suite["public_suite_label"],
        commitment_inputs=hidden_suite_registration_commitment_inputs(suite),
        suite_identity_sha256=suite["suite_identity_sha256"],
        suite_envelope=suite,
        exposure_ledger_path=ledger_path,
        exposure_seal_path=seal_path,
    )


from g4_hidden_capability_seam.rotation_revocation import RotationRevocationRegistry  # noqa: E402
from g4_hidden_capability_seam.run_idempotency import RunIdempotencyRegistry  # noqa: E402
from g4_hidden_capability_seam.security_model import (  # noqa: E402
    ROLES,
    role_catalog,
    scan_forbidden_public_payload,
)
from g4_hidden_capability_seam.suite_builder import build_synthetic_suite  # noqa: E402
from g4_hidden_capability_seam.vault import SUBJECT_CAP, SealedTruthVault  # noqa: E402


class TestSecurityModel(unittest.TestCase):
    def test_roles_present(self) -> None:
        cat = role_catalog()
        for r in ROLES:
            self.assertIn(r, cat["roles"])

    def test_forbidden_scan(self) -> None:
        leaks = scan_forbidden_public_payload({"vault_locator": "x", "ok": True})
        self.assertTrue(any("vault_locator" in x for x in leaks))


class TestIdentities(unittest.TestCase):
    def test_identity_changes_with_fields(self) -> None:
        a = identity_from_fields("t", {"x": 1})
        b = identity_from_fields("t", {"x": 2})
        self.assertNotEqual(a["identity_sha256"], b["identity_sha256"])
        self.assertEqual(
            identity_from_fields("t", {"x": 1})["identity_sha256"],
            a["identity_sha256"],
        )

    def test_immutable_run_envelope_binds_every_declared_field(self) -> None:
        base = build_immutable_run_envelope(
            run_id="run_test",
            attempt_id="attempt_1",
            suite_identity_sha256="1" * 64,
            route_identity_sha256="2" * 64,
            manifest_identity_sha256="3" * 64,
            raw_outputs=[{"synthetic": True}],
            telemetry={"phase": "test"},
            terminal_status="completed",
        )
        self.assertTrue(validate_object(base, "ImmutableRunEnvelope")["ok"])
        for field in RUN_ENVELOPE_IDENTITY_FIELDS:
            tampered = dict(base)
            value = tampered[field]
            if isinstance(value, bool):
                tampered[field] = not value
            elif isinstance(value, str):
                tampered[field] = value + "|tampered"
            elif isinstance(value, list):
                tampered[field] = [*value, {"tampered": True}]
            else:
                tampered[field] = {**value, "tampered": True}
            self.assertFalse(validate_object(tampered, "ImmutableRunEnvelope")["ok"], field)

    def test_object_and_schema_are_each_fail_closed(self) -> None:
        base = build_immutable_run_envelope(
            run_id="run_test",
            attempt_id="attempt_1",
            suite_identity_sha256="1" * 64,
            route_identity_sha256="2" * 64,
            manifest_identity_sha256="3" * 64,
            raw_outputs=[],
            telemetry={},
            terminal_status="not_started",
        )
        wrong_object = dict(base)
        wrong_object["object"] = "OtherObject"
        wrong_schema = dict(base)
        wrong_schema["schema_version"] = "xinao.invalid.v1"
        self.assertFalse(validate_object(wrong_object, "ImmutableRunEnvelope")["ok"])
        self.assertFalse(validate_object(wrong_schema, "ImmutableRunEnvelope")["ok"])

    def test_suite_schedule_includes_h_and_c(self) -> None:
        suite = build_hidden_suite_identity_envelope(
            public_suite_label="t",
            schedule_slots=H_SLOTS + [f"C{i}" for i in range(7)],
            synthetic_salt="s",
        )
        self.assertEqual(len(suite["schedule_slots"]), 21)
        self.assertIn("canonical_suite_commitment", suite)
        self.assertIn("suite_version", suite)

    def test_suite_mutation_fields(self) -> None:
        base = build_hidden_suite_identity_envelope(
            public_suite_label="syn",
            schedule_slots=["H01"],
            synthetic_salt="salt",
            generator_descriptor_identity_sha256="a" * 64,
            evaluator_bundle_identity_sha256="b" * 64,
            scoring_calibration_contract_identity_sha256="c" * 64,
            public_manifest_blueprint_commitment="d" * 64,
            heldout_identity_sha256="e" * 64,
            training_identity_sha256="f" * 64,
            subject_route_identity_sha256="1" * 64,
        )
        base_sha = base["suite_identity_sha256"]
        for field in ("suite_version", "lifecycle_status", "revocation_status", "creator_identity"):
            mut = mutate_suite_field(base, field, "mut-" + field)
            self.assertNotEqual(mut["suite_identity_sha256"], base_sha, field)
        self.assertGreater(len(SUITE_IDENTITY_MUTATION_FIELDS), 10)


class TestPackageFlowSecurityGate(unittest.TestCase):
    def test_lockdown_failure_starts_no_later_subject_probe(self) -> None:
        import g4_hidden_capability_seam.package_flow as package_flow

        original_adversarial = package_flow.run_adversarial_isolation
        original_timeout = package_flow.run_timeout_child_probe
        calls = {"adversarial": 0, "timeout": 0}

        def fail_adversarial(**kwargs):  # type: ignore[no-untyped-def]
            calls["adversarial"] += 1
            raise AssertionError("adversarial probe crossed failed lockdown gate")

        def fail_timeout(**kwargs):  # type: ignore[no-untyped-def]
            calls["timeout"] += 1
            raise AssertionError("timeout probe crossed failed lockdown gate")

        package_flow.run_adversarial_isolation = fail_adversarial
        package_flow.run_timeout_child_probe = fail_timeout
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
                vault = SealedTruthVault(Path(td) / "vault")
                for lockdown, receipt in (
                    ({"ok": False}, {"ok": True}),
                    ({"ok": True}, {"ok": False}),
                    ({"ok": True}, {"ok": True}),
                ):
                    with self.subTest(lockdown=lockdown, receipt=receipt):
                        result = package_flow._run_post_lockdown_subject_probes(
                            vault=vault,
                            lockdown=lockdown,
                            lockdown_receipt=receipt,
                            pf_state=Path("unused-failed-lockdown-gate"),
                            run_adversarial=True,
                            run_timeout_probe=True,
                        )
                        self.assertFalse(result["ok"], result)
                        self.assertFalse(result["gate_ok"], result)
                        self.assertFalse(result["subject_like_work_started"], result)
                        self.assertIsNone(result["adversarial_isolation"])
                        self.assertIsNone(result["timeout_child_probe"])
        finally:
            package_flow.run_adversarial_isolation = original_adversarial
            package_flow.run_timeout_child_probe = original_timeout
        self.assertEqual(calls, {"adversarial": 0, "timeout": 0})

    def test_fabricated_partial_receipts_start_no_subject_probe(self) -> None:
        import g4_hidden_capability_seam.package_flow as package_flow
        from g4_hidden_capability_seam.vault import (
            FINAL_TARGET_NAMES,
            PRE_RECEIPT_TARGET_NAMES,
        )

        calls = {"adversarial": 0, "timeout": 0}
        original_adversarial = package_flow.run_adversarial_isolation
        original_timeout = package_flow.run_timeout_child_probe

        def forbidden_adversarial(**kwargs):  # type: ignore[no-untyped-def]
            calls["adversarial"] += 1
            raise AssertionError("fabricated receipts crossed lockdown gate")

        def forbidden_timeout(**kwargs):  # type: ignore[no-untyped-def]
            calls["timeout"] += 1
            raise AssertionError("fabricated receipts crossed lockdown gate")

        fabricated_initial = {
            "ok": True,
            "target_set_exact": True,
            "expected_target_names": list(PRE_RECEIPT_TARGET_NAMES),
            "attempted_targets": list(PRE_RECEIPT_TARGET_NAMES),
            "pre_target_set": {"ok": True},
            "post_target_set": {"ok": True},
            "acl_apply": {"ok": True},
            "direct_verify": {"denied": True},
            "identity_binding": {"ok": True},
            "identity_verify": {"ok": True},
        }
        fabricated_final = {
            "ok": True,
            "target_set_exact": True,
            "expected_target_names": list(FINAL_TARGET_NAMES),
            "attempted_targets": list(FINAL_TARGET_NAMES),
            "pre_publication_target_set": {"ok": True},
            "pre_seal_target_set": {"ok": True},
            "post_seal_target_set": {"ok": True},
            "acl_apply": {"ok": True},
            "final_verify": {"denied": True},
            "identity_binding": {"ok": True},
            "identity_verify": {"ok": True},
        }
        package_flow.run_adversarial_isolation = forbidden_adversarial
        package_flow.run_timeout_child_probe = forbidden_timeout
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
                vault = SealedTruthVault(Path(td) / "vault")
                result = package_flow._run_post_lockdown_subject_probes(
                    vault=vault,
                    lockdown=fabricated_initial,
                    lockdown_receipt=fabricated_final,
                    pf_state=Path(td) / "unused",
                    run_adversarial=True,
                    run_timeout_probe=True,
                )
        finally:
            package_flow.run_adversarial_isolation = original_adversarial
            package_flow.run_timeout_child_probe = original_timeout
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["gate_ok"], result)
        self.assertFalse(result["receipt_evidence_complete"], result)
        self.assertFalse(result["subject_like_work_started"], result)
        self.assertEqual(calls, {"adversarial": 0, "timeout": 0})

    def test_live_gate_holds_final_identities_through_subject_probe(self) -> None:
        import g4_hidden_capability_seam.package_flow as package_flow

        original_adversarial = package_flow.run_adversarial_isolation
        replacement_state = {"blocked": False, "replaced": False}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            vault = SealedTruthVault(root / "vault")
            lockdown = vault.lock_down_host_reads(expected_receipt=False)
            self.assertTrue(lockdown["ok"], lockdown)
            publication = vault.publish_lockdown_receipt(lockdown)
            self.assertTrue(publication["ok"], publication)
            replacement = root / "replacement.json"
            replacement.write_text("{}\n", encoding="utf-8")

            def replace_after_live_verification(**kwargs):  # type: ignore[no-untyped-def]
                try:
                    os.replace(replacement, vault.truth_path)
                    replacement_state["replaced"] = True
                    return {"ok": False, "reason": "replacement_unexpectedly_succeeded"}
                except OSError:
                    replacement_state["blocked"] = True
                    return {"ok": True, "replacement_blocked": True}

            package_flow.run_adversarial_isolation = replace_after_live_verification
            try:
                result = package_flow._run_post_lockdown_subject_probes(
                    vault=vault,
                    lockdown=lockdown,
                    lockdown_receipt=publication,
                    pf_state=root / "probe-state",
                    run_adversarial=True,
                    run_timeout_probe=False,
                )
            finally:
                package_flow.run_adversarial_isolation = original_adversarial
                unlocked = vault.unlock_host_reads(expected_receipt=True)
                self.assertTrue(unlocked["ok"], unlocked)

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["gate_ok"], result)
        self.assertTrue(replacement_state["blocked"], replacement_state)
        self.assertFalse(replacement_state["replaced"], replacement_state)

    def test_omission_and_discovery_error_start_no_subject_probe(self) -> None:
        import g4_hidden_capability_seam.package_flow as package_flow
        from g4_hidden_capability_seam.vault import FINAL_TARGET_NAMES

        original_adversarial = package_flow.run_adversarial_isolation
        original_timeout = package_flow.run_timeout_child_probe
        calls = {"adversarial": 0, "timeout": 0}

        def forbidden_adversarial(**kwargs):  # type: ignore[no-untyped-def]
            calls["adversarial"] += 1
            raise AssertionError("adversarial probe crossed inexact target gate")

        def forbidden_timeout(**kwargs):  # type: ignore[no-untyped-def]
            calls["timeout"] += 1
            raise AssertionError("timeout probe crossed inexact target gate")

        valid_final_claim = {
            "ok": True,
            "target_set_exact": True,
            "expected_target_names": list(FINAL_TARGET_NAMES),
            "pre_publication_target_set": {"ok": True},
            "pre_seal_target_set": {"ok": True},
            "post_seal_target_set": {"ok": True},
        }
        package_flow.run_adversarial_isolation = forbidden_adversarial
        package_flow.run_timeout_child_probe = forbidden_timeout
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
                omitted = SealedTruthVault(Path(td) / "omitted")
                (omitted.vault_root / ".subject_denied").unlink()
                omission_lockdown = omitted.lock_down_host_reads(expected_receipt=False)
                self.assertFalse(omission_lockdown["ok"], omission_lockdown)
                omission_gate = package_flow._run_post_lockdown_subject_probes(
                    vault=omitted,
                    lockdown=omission_lockdown,
                    lockdown_receipt=valid_final_claim,
                    pf_state=Path(td) / "unused-omission",
                    run_adversarial=True,
                    run_timeout_probe=True,
                )
                self.assertFalse(omission_gate["gate_ok"], omission_gate)

                discovery = SealedTruthVault(Path(td) / "discovery")
                original_list = discovery._list_vault_entries

                def fail_enumeration():  # type: ignore[no-untyped-def]
                    raise PermissionError("injected discovery error")

                discovery._list_vault_entries = fail_enumeration  # type: ignore[method-assign]
                try:
                    discovery_lockdown = discovery.lock_down_host_reads(expected_receipt=False)
                finally:
                    discovery._list_vault_entries = original_list  # type: ignore[method-assign]
                self.assertFalse(discovery_lockdown["ok"], discovery_lockdown)
                discovery_gate = package_flow._run_post_lockdown_subject_probes(
                    vault=discovery,
                    lockdown=discovery_lockdown,
                    lockdown_receipt=valid_final_claim,
                    pf_state=Path(td) / "unused-discovery",
                    run_adversarial=True,
                    run_timeout_probe=True,
                )
                self.assertFalse(discovery_gate["gate_ok"], discovery_gate)
        finally:
            package_flow.run_adversarial_isolation = original_adversarial
            package_flow.run_timeout_child_probe = original_timeout
        self.assertEqual(calls, {"adversarial": 0, "timeout": 0})


class TestVault(unittest.TestCase):
    def test_normal_builder_does_not_reconstruct_missing_marker(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            op = Path(td) / "op"
            vault = SealedTruthVault(op / "vault")
            marker = vault.vault_root / ".subject_denied"
            marker.unlink()
            with self.assertRaises(RuntimeError):
                build_synthetic_suite(op)
            self.assertFalse(marker.exists())

    def test_receipt_loss_reentry_cannot_infer_pre_receipt_phase(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td) / "vault"
            vault = SealedTruthVault(root)
            lockdown = vault.lock_down_host_reads(expected_receipt=False)
            self.assertTrue(lockdown["ok"], lockdown)
            publication = vault.publish_lockdown_receipt(lockdown)
            self.assertTrue(publication["ok"], publication)
            unlocked = vault.unlock_host_reads(expected_receipt=True)
            self.assertTrue(unlocked["ok"], unlocked)
            receipt = root / "host_lockdown.v1.json"
            receipt.unlink()

            reentered = SealedTruthVault(root)
            self.assertFalse(receipt.exists())
            with self.assertRaises(TypeError):
                reentered.unlock_host_reads()  # type: ignore[call-arg]
            with self.assertRaises(TypeError):
                reentered._read_truth_unlocked()  # type: ignore[call-arg]
            with self.assertRaises(RuntimeError):
                reentered.unlock_host_reads(expected_receipt=True)
            relock = reentered.lock_down_host_reads(expected_receipt=True)
            self.assertFalse(relock["ok"], relock)

    def test_exact_target_inventory_rejects_missing_nonfile_and_extra(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)

            missing = SealedTruthVault(root / "missing")
            (missing.vault_root / ".subject_denied").unlink()
            _targets, missing_result = missing._exact_controlled_vault_targets(
                expected_receipt=False
            )
            self.assertFalse(missing_result["ok"], missing_result)
            self.assertIn(".subject_denied", missing_result["missing"])

            nonfile = SealedTruthVault(root / "nonfile")
            marker = nonfile.vault_root / ".subject_denied"
            marker.unlink()
            marker.mkdir()
            _targets, nonfile_result = nonfile._exact_controlled_vault_targets(
                expected_receipt=False
            )
            self.assertFalse(nonfile_result["ok"], nonfile_result)
            self.assertTrue(
                any(
                    problem.startswith("target_not_regular_file:.subject_denied")
                    for problem in nonfile_result["problems"]
                ),
                nonfile_result,
            )

            extra = SealedTruthVault(root / "extra")
            (extra.vault_root / "unexpected.json").write_text("{}\n", encoding="utf-8")
            _targets, extra_result = extra._exact_controlled_vault_targets(expected_receipt=False)
            self.assertFalse(extra_result["ok"], extra_result)
            self.assertIn("unexpected.json", extra_result["extra"])

    def test_subject_denied(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            v = SealedTruthVault(Path(td) / "vault")
            v.deposit_synthetic(
                public_case_id="c1",
                public_prompt="p",
                truth={"a": 1},
                scoring_rule_private={"r": 1},
                family_slot="H01",
                schedule_class="structural",
            )
            r = v.subject_read(capability=SUBJECT_CAP, public_case_id="c1")
            self.assertFalse(r["ok"])
            pub = v.public_case_view("c1")
            self.assertTrue(pub["ok"])
            self.assertNotIn("truth", pub)

    def test_host_lockdown(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            v = SealedTruthVault(Path(td) / "vault")
            v.deposit_synthetic(
                public_case_id="c1",
                public_prompt="p",
                truth={"a": 1},
                scoring_rule_private={"r": 1},
                family_slot="H01",
                schedule_class="structural",
            )
            lock = v.lock_down_host_reads(expected_receipt=False)
            self.assertTrue(lock.get("ok"), lock)
            self.assertTrue(lock.get("isolation_enforced"))
            v.unlock_host_reads(expected_receipt=False)

    def test_lockdown_receipt_replacement_is_resealed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            v = SealedTruthVault(root / "vault")
            v.deposit_synthetic(
                public_case_id="c1",
                public_prompt="p",
                truth={"a": 1},
                scoring_rule_private={"r": 1},
                family_slot="H01",
                schedule_class="structural",
            )
            isolated = v.assert_path_isolation(
                subject_root=root / "subject",
                promptfoo_root=root / "promptfoo",
                evaluator_root=root / "evaluator",
            )
            self.assertTrue(isolated["ok"], isolated)
            lock = v.lock_down_host_reads(expected_receipt=False)
            self.assertTrue(lock["ok"], lock)
            try:
                publication = v.publish_lockdown_receipt(lock)
                self.assertTrue(publication["ok"], publication)
                targets = v._controlled_vault_targets(expected_receipt=True)
                self.assertEqual(
                    {path.name for path in targets},
                    {
                        "sealed_truth.v1.json",
                        "vault_meta.v1.json",
                        "host_lockdown.v1.json",
                        ".subject_denied",
                    },
                )
                verify = v._verify_direct_denial(targets=targets)
                self.assertTrue(verify["denied"], verify)
                self.assertTrue(
                    all(item.get("denied") for item in verify["per_file"]),
                    verify,
                )
            finally:
                unlocked = v.unlock_host_reads(expected_receipt=True)
                self.assertTrue(unlocked["ok"], unlocked)


class TestLedgers(unittest.TestCase):
    def test_exposure_chain_and_seal(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            path = Path(td) / "e.jsonl"
            led = ExposureLedger(path)
            led.record_exposure(
                principal_id="p",
                role="subject",
                exposure_subject_identity_sha256="s" * 64,
                exposure_kind="public_manifest",
                object_ref="m",
            )
            v = led.verify()
            self.assertTrue(v["ok"])
            seal = led.log.write_seal_receipt(Path(td) / "seal.json")
            vs = led.log.verify_against_seal(seal)
            self.assertTrue(vs["ok"], vs)

    def test_invalid_exposure_chain_cannot_be_sealed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            path = Path(td) / "e.jsonl"
            led = ExposureLedger(path)
            led.record_exposure(
                principal_id="p",
                role="subject",
                exposure_subject_identity_sha256="s" * 64,
                exposure_kind="public_manifest",
                object_ref="m",
            )
            record = json.loads(path.read_text(encoding="utf-8"))
            record["body"]["object_ref"] = "tampered"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                led.log.write_seal_receipt(Path(td) / "invalid.seal.json")

    def test_exposure_proof_drift_rejected_at_use_time(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            reg = RotationRevocationRegistry(root / "r.json")
            suite, ledger_path, seal_path = _suite_envelope(root, "proof-drift", {"a": 1})
            admitted = _register_suite(reg, suite, ledger_path, seal_path)
            self.assertTrue(admitted["ok"], admitted)
            ledger = ExposureLedger(ledger_path)
            ledger.record_exposure(
                principal_id="late",
                role="subject",
                exposure_subject_identity_sha256=suite["exposure_subject_identity_sha256"],
                exposure_kind="public_case_id",
                object_ref="late_append_after_seal",
            )
            may = reg.may_start_run(suite_identity_sha256=suite["suite_identity_sha256"])
            self.assertFalse(may["ok"])
            self.assertEqual(may["reason"], "suite_identity_admission_failed")

    def test_idempotency_cas(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RunIdempotencyRegistry(Path(td) / "i.json", max_attempts=8)
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "x", {"a": 1})
            sha = suite["suite_identity_sha256"]
            _register_suite(reg.state, suite, ledger_path, seal_path)
            c1 = reg.claim_run(
                run_id="r1",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=sha,
            )
            self.assertTrue(c1["ok"])
            reg.mark_side_effect_started(run_id="r1")
            reg.mark_side_effect(run_id="r1")
            c2 = reg.claim_run(
                run_id="r1",
                attempt_id="a2",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=sha,
            )
            self.assertFalse(c2["ok"])
            self.assertEqual(reg.status()["side_effect_count"], 1)

    def test_claim_revoke_start_toctou(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RotationRevocationRegistry(Path(td) / "r.json")
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "toctou", {"t": 1})
            sha = suite["suite_identity_sha256"]
            _register_suite(reg, suite, ledger_path, seal_path)
            idem = RunIdempotencyRegistry(Path(td) / "i.json", state=reg.state)
            claim = idem.claim_run(
                run_id="r1",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=sha,
            )
            self.assertTrue(claim["ok"])
            reg.revoke(identity_sha256=sha, reason="after_claim")
            start = idem.mark_side_effect_started(run_id="r1")
            self.assertFalse(start["ok"])
            self.assertEqual(start["reason"], "revoked_suite_cannot_start_side_effect")
            self.assertEqual(idem.status()["side_effect_started_count"], 0)

    def test_claim_record_hash_drift_rejected_at_start(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            reg = RotationRevocationRegistry(root / "r.json")
            suite, ledger_path, seal_path = _suite_envelope(root, "claim-hash", {"a": 1})
            _register_suite(reg, suite, ledger_path, seal_path)
            idem = RunIdempotencyRegistry(root / "i.json", state=reg.state)
            claim = idem.claim_run(
                run_id="r1",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=suite["suite_identity_sha256"],
            )
            self.assertTrue(claim["ok"])
            with sqlite3.connect(reg.db_path) as conn:
                conn.execute(
                    "UPDATE run_claims SET record_sha256=? WHERE run_id=?",
                    ("0" * 64, "r1"),
                )
            start = idem.mark_side_effect_started(run_id="r1")
            self.assertFalse(start["ok"])
            self.assertEqual(start["reason"], "run_claim_integrity_failed")

    def test_drifted_identity_rejected(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RotationRevocationRegistry(Path(td) / "r.json")
            suite, _ledger_path, _seal_path = _suite_envelope(Path(td), "x", {"a": 1})
            bad = reg.register_identity(
                identity_kind="HiddenSuiteIdentityEnvelope",
                public_label="x",
                commitment_inputs=hidden_suite_registration_commitment_inputs(suite),
                suite_identity_sha256="0" * 64,
                suite_envelope=suite,
            )
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["reason"], "identity_hash_mismatch_or_drifted")

    def test_bare_hidden_suite_identity_rejected(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RotationRevocationRegistry(Path(td) / "r.json")
            bad = reg.register_identity(
                identity_kind="HiddenSuiteIdentityEnvelope",
                public_label="x",
                commitment_inputs={"a": 1},
                suite_identity_sha256="0" * 64,
            )
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["reason"], "full_suite_envelope_required")

    def test_stored_suite_tamper_rejected_by_all_use_time_consumers(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RotationRevocationRegistry(Path(td) / "r.json")
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "consume", {"a": 1})
            sha = suite["suite_identity_sha256"]
            self.assertTrue(_register_suite(reg, suite, ledger_path, seal_path)["ok"])
            idem = RunIdempotencyRegistry(Path(td) / "i.json", state=reg.state)
            first = idem.claim_run(
                run_id="claimed-before-tamper",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=sha,
            )
            self.assertTrue(first["ok"])

            with sqlite3.connect(reg.db_path) as conn:
                raw = conn.execute(
                    "SELECT payload_json FROM suite_identities WHERE suite_identity_sha256=?",
                    (sha,),
                ).fetchone()[0]
                payload = json.loads(raw)
                payload["suite_envelope"]["authority"] = True
                conn.execute(
                    "UPDATE suite_identities SET payload_json=? WHERE suite_identity_sha256=?",
                    (json.dumps(payload, sort_keys=True, separators=(",", ":")), sha),
                )

            may = reg.may_start_run(suite_identity_sha256=sha)
            claim = idem.claim_run(
                run_id="claim-after-tamper",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=sha,
            )
            start = idem.mark_side_effect_started(run_id="claimed-before-tamper")
            self.assertEqual(may["reason"], "suite_identity_admission_failed")
            self.assertEqual(claim["reason"], "suite_identity_admission_failed")
            self.assertEqual(start["reason"], "suite_identity_admission_failed")

    def test_suite_envelope_validate_rejects_posthash_tamper(self) -> None:
        base = build_hidden_suite_identity_envelope(
            public_suite_label="syn",
            schedule_slots=["H01"],
            synthetic_salt="salt",
            realized_manifest_binding="a" * 64,
            public_manifest_blueprint_commitment="b" * 64,
            generator_descriptor_identity_sha256="c" * 64,
            evaluator_bundle_identity_sha256="d" * 64,
            scoring_calibration_contract_identity_sha256="e" * 64,
            heldout_identity_sha256="f" * 64,
            training_identity_sha256="1" * 64,
            subject_route_identity_sha256="2" * 64,
        )
        self.assertTrue(validate_object(base, "HiddenSuiteIdentityEnvelope")["ok"])
        for field in (
            "realized_manifest_binding",
            "exposure_ledger_sealed_head_contract",
            "lifecycle_status",
            "canonical_suite_commitment",
            "suite_identity_sha256",
        ):
            tampered = dict(base)
            if field == "suite_identity_sha256":
                tampered[field] = "0" * 64
            elif field == "canonical_suite_commitment":
                tampered[field] = "0" * 64
            else:
                tampered[field] = str(tampered.get(field) or "x") + "|x"
            self.assertFalse(validate_object(tampered, "HiddenSuiteIdentityEnvelope")["ok"], field)
        self.assertGreater(len(SUITE_IDENTITY_FIELDS), 20)
        self.assertEqual(recompute_suite_identity_sha256(base), base["suite_identity_sha256"])

    def test_concurrent_claims_exactly_one(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            td_path = Path(td)
            reg_path = td_path / "race.json"
            # Pre-create registry with suite
            reg = RunIdempotencyRegistry(reg_path, max_attempts=64)
            suite, ledger_path, seal_path = _suite_envelope(td_path, "race", {"k": 1})
            suite_sha = suite["suite_identity_sha256"]
            _register_suite(reg.state, suite, ledger_path, seal_path)
            reg.state.export_json_snapshot(reg_path)
            gate = td_path / "go"
            worker = r"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, os.environ["CANDIDATE_SRC"])
from g4_hidden_capability_seam.run_idempotency import RunIdempotencyRegistry
gate = Path(os.environ["RACE_GATE"])
deadline = time.monotonic() + 15
while not gate.exists():
    if time.monotonic() > deadline:
        raise RuntimeError("gate timeout")
    time.sleep(0.001)
reg = RunIdempotencyRegistry(Path(os.environ["REGISTRY_PATH"]), max_attempts=64)
try:
    result = reg.claim_run(
        run_id="owner-race-run",
        attempt_id=os.environ["ATTEMPT_ID"],
        route_identity_sha256="r" * 64,
        suite_identity_sha256=os.environ["SUITE_SHA"],
    )
    print(json.dumps({"ok": bool(result.get("ok")), "reason": result.get("reason")}))
except Exception as exc:
    print(json.dumps({"ok": False, "exception": type(exc).__name__}))
    raise
"""
            env_base = os.environ.copy()
            env_base.update(
                {
                    "CANDIDATE_SRC": str(ROOT / "src"),
                    "RACE_GATE": str(gate),
                    "REGISTRY_PATH": str(reg_path),
                    "SUITE_SHA": suite_sha,
                }
            )
            reader_stop = threading.Event()
            reader_errors: list[str] = []
            reader_reads = 0
            raw_reader_errors: list[str] = []

            def reader() -> None:
                nonlocal reader_reads
                while not reader_stop.is_set():
                    try:
                        read_json(reg_path)
                        reader_reads += 1
                    except Exception as exc:  # noqa: BLE001
                        reader_errors.append(type(exc).__name__)
                    time.sleep(0.0005)

            def raw_reader() -> None:
                while not reader_stop.is_set():
                    try:
                        json.loads(reg_path.read_text(encoding="utf-8"))
                    except Exception as exc:  # noqa: BLE001
                        raw_reader_errors.append(type(exc).__name__)
                    time.sleep(0.0005)

            reader_thread = threading.Thread(target=reader, daemon=True)
            raw_reader_thread = threading.Thread(target=raw_reader, daemon=True)
            reader_thread.start()
            raw_reader_thread.start()
            procs = []
            for i in range(24):
                env = dict(env_base)
                env["ATTEMPT_ID"] = f"attempt-{i:03d}"
                procs.append(
                    subprocess.Popen(
                        [sys.executable, "-B", "-I", "-c", worker],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=env,
                        cwd=str(td_path),
                    )
                )
            time.sleep(0.3)
            gate.write_text("go\n", encoding="utf-8")
            accepted = 0
            exceptions = 0
            for p in procs:
                out, err = p.communicate(timeout=30)
                try:
                    payload = json.loads(out.strip().splitlines()[-1])
                except Exception:  # noqa: BLE001
                    payload = {"ok": False, "parse_error": True}
                if payload.get("ok") is True:
                    accepted += 1
                if payload.get("exception") or p.returncode != 0:
                    exceptions += 1
            reader_stop.set()
            reader_thread.join(timeout=5)
            raw_reader_thread.join(timeout=5)
            self.assertEqual(accepted, 1, f"accepted={accepted}")
            self.assertEqual(exceptions, 0)
            self.assertGreater(reader_reads, 0)
            self.assertEqual(reader_errors, [])
            self.assertNotIn("JSONDecodeError", raw_reader_errors)
            self.assertEqual(reg.status()["run_count"], 1)

    def test_revocation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RotationRevocationRegistry(Path(td) / "r.json")
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "x", {"a": 1})
            r = _register_suite(reg, suite, ledger_path, seal_path)
            sha = r["identity"]["identity_sha256"]
            reg.revoke(identity_sha256=sha, reason="t")
            may = reg.may_start_run(suite_identity_sha256=sha)
            self.assertFalse(may["allowed"])

    def test_start_transition_hash_bound_and_finalize_success(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RunIdempotencyRegistry(Path(td) / "i.json", max_attempts=8)
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "st", {"a": 1})
            _register_suite(reg.state, suite, ledger_path, seal_path)
            claim = reg.claim_run(
                run_id="r-st",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=suite["suite_identity_sha256"],
            )
            self.assertTrue(claim["ok"], claim)
            start = reg.mark_side_effect_started(run_id="r-st")
            self.assertTrue(start["ok"], start)
            self.assertTrue(start.get("start_transition_sha256"))
            with sqlite3.connect(reg.db_path) as conn:
                row = conn.execute(
                    "SELECT start_transition_sha256, start_transition_nonce, "
                    "start_transition_at_unix, status, side_effect_started "
                    "FROM run_claims WHERE run_id=?",
                    ("r-st",),
                ).fetchone()
            self.assertEqual(row[3], "side_effect_started")
            self.assertEqual(int(row[4]), 1)
            self.assertEqual(row[0], start["start_transition_sha256"])
            self.assertTrue(row[1])
            self.assertIsNotNone(row[2])
            fin = reg.mark_side_effect(run_id="r-st")
            self.assertTrue(fin["ok"], fin)
            self.assertEqual(reg.status()["side_effect_count"], 1)

    def test_coordinated_status_flag_mutation_fails_finalize(self) -> None:
        """status+side_effect_started mutation with original claim hash must fail."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RunIdempotencyRegistry(Path(td) / "i.json", max_attempts=8)
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "coord", {"a": 1})
            _register_suite(reg.state, suite, ledger_path, seal_path)
            claim = reg.claim_run(
                run_id="r-coord",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=suite["suite_identity_sha256"],
            )
            self.assertTrue(claim["ok"])
            # Leave record_sha256 as the original claimed/false/false hash while
            # forging the transition flags without a valid start-transition hash.
            with sqlite3.connect(reg.db_path) as conn:
                conn.execute(
                    "UPDATE run_claims SET status=?, side_effect_started=1, "
                    "start_transition_sha256=NULL, start_transition_nonce=NULL, "
                    "start_transition_at_unix=NULL WHERE run_id=?",
                    ("side_effect_started", "r-coord"),
                )
            fin = reg.mark_side_effect(run_id="r-coord")
            self.assertFalse(fin["ok"])
            self.assertEqual(fin["reason"], "start_transition_integrity_failed")
            self.assertEqual(fin["detail"]["reason"], "start_transition_hash_missing")

    def test_forged_blank_and_drifted_transition_hash_fail(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            reg = RunIdempotencyRegistry(Path(td) / "i.json", max_attempts=8)
            suite, ledger_path, seal_path = _suite_envelope(Path(td), "forge", {"a": 1})
            _register_suite(reg.state, suite, ledger_path, seal_path)
            claim = reg.claim_run(
                run_id="r-forge",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=suite["suite_identity_sha256"],
            )
            self.assertTrue(claim["ok"])
            start = reg.mark_side_effect_started(run_id="r-forge")
            self.assertTrue(start["ok"], start)

            with sqlite3.connect(reg.db_path) as conn:
                conn.execute(
                    "UPDATE run_claims SET start_transition_sha256=? WHERE run_id=?",
                    ("0" * 64, "r-forge"),
                )
            fin_forged = reg.mark_side_effect(run_id="r-forge")
            self.assertFalse(fin_forged["ok"])
            self.assertEqual(fin_forged["reason"], "start_transition_integrity_failed")

            # Restore valid start then blank the hash.
            start2_claim = reg.claim_run(
                run_id="r-blank",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=suite["suite_identity_sha256"],
            )
            self.assertTrue(start2_claim["ok"])
            self.assertTrue(reg.mark_side_effect_started(run_id="r-blank")["ok"])
            with sqlite3.connect(reg.db_path) as conn:
                conn.execute(
                    "UPDATE run_claims SET start_transition_sha256='' WHERE run_id=?",
                    ("r-blank",),
                )
            fin_blank = reg.mark_side_effect(run_id="r-blank")
            self.assertFalse(fin_blank["ok"])
            self.assertEqual(fin_blank["detail"]["reason"], "start_transition_hash_missing")

            # Field drift: mutate nonce while keeping old hash.
            claim3 = reg.claim_run(
                run_id="r-drift",
                attempt_id="a1",
                route_identity_sha256="r" * 64,
                suite_identity_sha256=suite["suite_identity_sha256"],
            )
            self.assertTrue(claim3["ok"])
            self.assertTrue(reg.mark_side_effect_started(run_id="r-drift")["ok"])
            with sqlite3.connect(reg.db_path) as conn:
                conn.execute(
                    "UPDATE run_claims SET start_transition_nonce=? WHERE run_id=?",
                    ("deadbeefdeadbeefdeadbeefdeadbeef", "r-drift"),
                )
            fin_drift = reg.mark_side_effect(run_id="r-drift")
            self.assertFalse(fin_drift["ok"])
            self.assertEqual(fin_drift["detail"]["reason"], "start_transition_sha256_mismatch")


class TestPromptfooProviderExclusivity(unittest.TestCase):
    def test_canonical_config_validates_positive(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            TRUSTED_PROVIDER_ID,
            build_promptfoo_config,
            validate_promptfoo_config_providers,
            validate_promptfoo_public_cases,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            adapter = root / "trusted_adapter.py"
            adapter.write_text(
                "def call_api(prompt, options, context):\n    return {'output': prompt}\n",
                encoding="utf-8",
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
                config_dir=root / "config",
                adapter_path=adapter,
                cases_path=cases,
            )
            self.assertTrue(built["ok"])
            v = validate_promptfoo_config_providers(
                Path(built["config_path"]),
                expected_config_sha256=built["config_sha256"],
            )
            self.assertTrue(v["ok"], v)
            self.assertEqual(v["provider_id"], TRUSTED_PROVIDER_ID)
            cases_v = validate_promptfoo_public_cases(
                Path(built["cases_json"]),
                expected_case_ids=["syn-H01-001"],
                expected_cases_sha256=built["cases_sha256"],
            )
            self.assertTrue(cases_v["ok"], cases_v)

    def test_per_test_provider_override_rejected(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            render_canonical_promptfoo_config_yaml,
            validate_promptfoo_config_providers,
            validate_promptfoo_public_cases,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            cfg = root / "promptfooconfig.yaml"
            cfg.write_text(
                render_canonical_promptfoo_config_yaml(),
                encoding="utf-8",
                newline="\n",
            )
            cases = root / "public_cases.json"
            cases.write_text(
                json.dumps(
                    [
                        {
                            "vars": {
                                "public_case_id": "syn-H01-001",
                                "public_prompt": "synthetic",
                                "commitment_sha256": "c" * 64,
                            },
                            "provider": "python:/work/evil.py",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            config_v = validate_promptfoo_config_providers(cfg)
            self.assertTrue(config_v["ok"], config_v)
            cases_v = validate_promptfoo_public_cases(cases, expected_case_ids=["syn-H01-001"])
            self.assertFalse(cases_v["ok"])
            self.assertEqual(cases_v["reason"], "promptfoo_public_case_row_schema_mismatch")

    def test_comment_only_trusted_provider_rejected(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            validate_promptfoo_config_providers,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            cfg = Path(td) / "promptfooconfig.yaml"
            cfg.write_text(
                "\n".join(
                    [
                        "# providers: python:/adapter/promptfoo_subject_adapter.py",
                        "description: 'evil'",
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
            self.assertFalse(v["ok"])
            self.assertEqual(v["reason"], "promptfoo_provider_not_trusted_adapter_descriptor")

    def test_secondary_provider_and_work_evil_rejected(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            validate_promptfoo_config_providers,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            (root / "evil.py").write_text("# evil\n", encoding="utf-8")
            cfg = root / "promptfooconfig.yaml"
            cfg.write_text(
                "\n".join(
                    [
                        "description: 'dual'",
                        "providers:",
                        "  - id: 'python:/adapter/promptfoo_subject_adapter.py'",
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
            v = validate_promptfoo_config_providers(cfg)
            self.assertFalse(v["ok"])
            # work .py surface fails before schema depth when present
            self.assertIn(
                v["reason"],
                {
                    "untrusted_work_python_provider_surface_present",
                    "promptfoo_config_requires_exactly_one_provider",
                },
            )

    def test_inert_field_trusted_string_with_evil_selected_rejected(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            validate_promptfoo_config_providers,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            cfg = Path(td) / "promptfooconfig.yaml"
            cfg.write_text(
                "\n".join(
                    [
                        "description: 'python:/adapter/promptfoo_subject_adapter.py'",
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
            self.assertFalse(v["ok"])
            self.assertEqual(v["reason"], "promptfoo_provider_not_trusted_adapter_descriptor")


class TestPromptfooPrivateSnapshotBoundary(unittest.TestCase):
    def test_expected_bindings_fail_before_identity_docker_boundary(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        called = {"identity": 0}
        original = runner.verify_promptfoo_identity

        def fake_identity():  # type: ignore[no-untyped-def]
            called["identity"] += 1
            raise AssertionError("identity Docker boundary must not run")

        runner.verify_promptfoo_identity = fake_identity
        try:
            result = runner.run_promptfoo_offline(
                config_path=Path("missing-config"),
                state_root=Path("missing-state"),
                output_path=Path("promptfoo_results.json"),
            )
        finally:
            runner.verify_promptfoo_identity = original
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "expected_bindings")
        self.assertEqual(called["identity"], 0)

    def test_output_basename_injection_rejected_before_identity(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        called = {"identity": 0}
        original = runner.verify_promptfoo_identity

        def fake_identity():  # type: ignore[no-untyped-def]
            called["identity"] += 1
            raise AssertionError("identity Docker boundary must not run")

        runner.verify_promptfoo_identity = fake_identity
        try:
            result = runner.run_promptfoo_offline(
                config_path=Path("config"),
                state_root=Path("state"),
                output_path=Path("result.json;echo_INJECTED"),
                expected_adapter_sha256="a" * 64,
                expected_case_ids=["syn-H01-001"],
                expected_config_sha256="b" * 64,
                expected_cases_sha256="c" * 64,
            )
        finally:
            runner.verify_promptfoo_identity = original
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "promptfoo_output_basename_not_exact")
        self.assertEqual(called["identity"], 0)

    def test_missing_policy_cannot_create_or_delete_host_paths(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            state = root / "must-not-be-created-state"
            output_root = root / "must-not-be-created-output"
            result = runner.run_promptfoo_offline(
                config_path=root / "missing-config.yaml",
                state_root=state,
                output_path=output_root / "promptfoo_results.json",
                expected_adapter_sha256="a" * 64,
                expected_case_ids=["syn-H01-001"],
                expected_config_sha256="b" * 64,
                expected_cases_sha256="c" * 64,
            )
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["phase"], "mount_boundary")
            self.assertFalse(state.exists())
            self.assertFalse(output_root.exists())

    def test_output_state_alias_rejected_before_host_mutation(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            package = Path(td) / "package"
            op_root = package / "ops" / "op_alias_negative"
            config_dir = op_root / "promptfoo" / "config"
            adapter_dir = package / "adapters"
            config_dir.mkdir(parents=True)
            adapter_dir.mkdir(parents=True)
            config_path = config_dir / "promptfooconfig.yaml"
            cases_path = config_dir / "public_cases.json"
            adapter_path = adapter_dir / "promptfoo_subject_adapter.py"
            config_path.write_text("description: test\n", encoding="utf-8")
            cases_path.write_text("[]\n", encoding="utf-8")
            adapter_path.write_text("# adapter\n", encoding="utf-8")
            aliased = op_root / "promptfoo" / "aliased-rw"
            result = runner.run_promptfoo_offline(
                config_path=config_path,
                state_root=aliased,
                output_path=aliased / "promptfoo_results.json",
                adapter_host_path=adapter_path,
                op_root=op_root,
                allowed_roots=[config_dir, aliased, aliased],
                denied_roots=[],
                expected_adapter_sha256=hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
                expected_case_ids=["syn-H01-001"],
                expected_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                expected_cases_sha256=hashlib.sha256(cases_path.read_bytes()).hexdigest(),
            )
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["check"]["reason"], "mount_sources_overlap")
            self.assertFalse(aliased.exists())

    def test_mount_source_cannot_contain_executable_config(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            package = Path(td) / "package"
            op_root = package / "ops" / "op_config_alias_negative"
            config_dir = op_root / "promptfoo" / "config"
            output_root = op_root / "promptfoo" / "output"
            adapter_dir = package / "adapters"
            config_dir.mkdir(parents=True)
            adapter_dir.mkdir(parents=True)
            config_path = config_dir / "promptfooconfig.yaml"
            cases_path = config_dir / "public_cases.json"
            adapter_path = adapter_dir / "promptfoo_subject_adapter.py"
            config_path.write_text("description: test\n", encoding="utf-8")
            cases_path.write_text("[]\n", encoding="utf-8")
            adapter_path.write_text("# adapter\n", encoding="utf-8")
            result = runner._preflight_promptfoo_host_paths(
                config_path=config_path,
                state_root=config_dir,
                output_root=output_root,
                adapter_src=adapter_path,
                op_root=op_root,
                allowed_roots=[config_dir, config_dir, output_root],
                denied_roots=[],
            )
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["reason"], "mount_source_overlaps_executable_source")
            self.assertFalse(output_root.exists())

    def test_cleanup_exception_does_not_short_circuit_later_probes(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        original = runner._run
        calls: list[tuple[str, ...]] = []
        captured_id = "c" * 64

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(tuple(argv))
            if argv[:3] == ["docker", "rm", "-f"] and argv[-1] == captured_id:
                raise subprocess.TimeoutExpired(cmd=argv, timeout=60)
            if argv[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(argv, 1, "", "absent")
            if argv[:4] == ["docker", "container", "ls", "-a"]:
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner._run = fake_run
        try:
            cleanup = runner._docker_rm_exact("owned-name", captured_id)
        finally:
            runner._run = original
        self.assertTrue(cleanup["ok"], cleanup)
        self.assertEqual(cleanup["removal_returncodes"][0]["error_class"], "TimeoutExpired")
        self.assertIn(("docker", "rm", "-f", "owned-name"), calls)
        self.assertIn(("docker", "inspect", "owned-name"), calls)
        self.assertIn(("docker", "inspect", captured_id), calls)
        self.assertTrue(any(call[:4] == ("docker", "container", "ls", "-a") for call in calls))

    def test_container_cleanup_daemon_error_is_not_absence_proof(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        original = runner._run

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            if argv[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
            if argv[:4] == ["docker", "container", "ls", "-a"]:
                return subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner._run = fake_run
        try:
            cleanup = runner._docker_rm_exact("owned-name", "a" * 64)
        finally:
            runner._run = original
        self.assertFalse(cleanup["ok"], cleanup)
        self.assertFalse(cleanup["inventory_complete"], cleanup)

    def test_container_cleanup_captured_id_survives_rename(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        original = runner._run
        captured_id = "a" * 64

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            if argv[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            if argv[:4] == ["docker", "container", "ls", "-a"]:
                return subprocess.CompletedProcess(
                    argv, 0, f"{captured_id}|renamed-owned-container\n", ""
                )
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner._run = fake_run
        try:
            cleanup = runner._docker_rm_exact("original-name", captured_id)
        finally:
            runner._run = original
        self.assertFalse(cleanup["ok"], cleanup)
        self.assertTrue(cleanup["exact_name_absent"], cleanup)
        self.assertFalse(cleanup["exact_id_absent"], cleanup)

    def test_create_stdout_requires_exact_lowercase_full_id_line(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        container_id = "a" * 64
        self.assertEqual(
            runner._container_id_from_create_stdout(container_id + "\n"),
            container_id,
        )
        self.assertEqual(
            runner._container_id_from_create_stdout(container_id + "\r\n"),
            container_id,
        )
        rejected = (
            container_id,
            " " + container_id + "\n",
            container_id + " \n",
            container_id + "\n\n",
            container_id.upper() + "\n",
            "a" * 12 + "\n",
            "",
            None,
        )
        for value in rejected:
            with self.subTest(value=value):
                self.assertIsNone(runner._container_id_from_create_stdout(value))
        self.assertFalse(runner._is_canonical_container_id(container_id.upper()))

    def test_truncated_container_id_plus_rename_never_proves_absence(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        original = runner._run
        truncated_id = "a" * 12
        full_id = "a" * 64

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            if argv[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(argv, 1, "", "not found")
            if argv[:4] == ["docker", "container", "ls", "-a"]:
                return subprocess.CompletedProcess(
                    argv, 0, f"{full_id}|renamed-owned-container\n", ""
                )
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner._run = fake_run
        try:
            cleanup = runner._docker_rm_exact("original-name", truncated_id)
        finally:
            runner._run = original
        self.assertFalse(cleanup["ok"], cleanup)
        self.assertFalse(cleanup["container_id_canonical_full"], cleanup)
        self.assertFalse(cleanup["exact_id_absent"], cleanup)

    def test_image_cleanup_daemon_error_is_not_absence_proof(self) -> None:
        import g4_hidden_capability_seam.promptfoo_runner as runner

        original = runner._run

        def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
            if argv[:4] == ["docker", "image", "ls", "-a"]:
                return subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
            if argv[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(argv, 1, "", "daemon unavailable")
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner._run = fake_run
        try:
            cleanup = runner._docker_rmi_exact("sha256:" + "a" * 64)
        finally:
            runner._run = original
        self.assertFalse(cleanup["ok"], cleanup)
        self.assertFalse(cleanup["inventory_complete"], cleanup)

    def test_pre_start_requires_exact_derived_image_ref_and_id(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            ADMITTED_ENV_VALUES,
            _norm_win_path,
            _verify_pre_start,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            root = Path(td)
            output = root / "output"
            state = root / "state"
            output.mkdir()
            state.mkdir()
            # _verify_pre_start intentionally rejects AppData mount sources;
            # use package-local lexical sources for this pure inspect fixture.
            output = Path.cwd() / "ops" / "unit_pre_start" / "output"
            state = Path.cwd() / "ops" / "unit_pre_start" / "state"
            image_id = "sha256:" + "a" * 64
            expected_mounts = [
                {"dest": "/output", "mode": "rw", "source_norm": _norm_win_path(output)},
                {"dest": "/state", "mode": "rw", "source_norm": _norm_win_path(state)},
            ]
            inspect = {
                "Image": image_id,
                "HostConfig": {
                    "NetworkMode": "none",
                    "ReadonlyRootfs": True,
                    "Privileged": False,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidsLimit": 128,
                    "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=268435456"},
                },
                "Config": {
                    "User": "promptfoo",
                    "Image": image_id,
                    "Env": [f"{key}={value}" for key, value in ADMITTED_ENV_VALUES.items()],
                },
                "Mounts": [
                    {"Destination": "/output", "Source": str(output), "RW": True},
                    {"Destination": "/state", "Source": str(state), "RW": True},
                ],
            }
            good = _verify_pre_start(
                inspect,
                expected_mounts=expected_mounts,
                allowed_mount_targets={"/output", "/state"},
                expected_image_ref=image_id,
                expected_image_id=image_id,
            )
            self.assertTrue(good["ok"], good)
            bad_ref = _verify_pre_start(
                inspect,
                expected_mounts=expected_mounts,
                allowed_mount_targets={"/output", "/state"},
                expected_image_ref="sha256:" + "b" * 64,
                expected_image_id=image_id,
            )
            self.assertFalse(bad_ref["ok"])
            self.assertIn("image_ref_not_expected", bad_ref["problems"])
            bad_id = _verify_pre_start(
                inspect,
                expected_mounts=expected_mounts,
                allowed_mount_targets={"/output", "/state"},
                expected_image_ref=image_id,
                expected_image_id="sha256:" + "c" * 64,
            )
            self.assertFalse(bad_id["ok"])
            self.assertIn("image_id_not_expected", bad_id["problems"])

    def test_private_snapshot_host_cleanup_is_proven(self) -> None:
        from g4_hidden_capability_seam.promptfoo_runner import (
            _remove_private_snapshot_stage,
        )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            stage = Path(td) / ".private_exec_snapshot"
            (stage / "work").mkdir(parents=True)
            (stage / "work" / "input.txt").write_text("x", encoding="utf-8")
            cleanup = _remove_private_snapshot_stage(stage)
            self.assertTrue(cleanup["ok"], cleanup)
            self.assertTrue(cleanup["absent"], cleanup)
            self.assertFalse(stage.exists())


class TestVaultAclRestore(unittest.TestCase):
    def test_inventoried_missing_target_is_not_restored(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            missing = Path(td) / "was-present-before-lift.json"
            verify = vault._verify_direct_denial(targets=[missing], user="EXAMPLE\\exact-user")
            self.assertFalse(verify["denied"], verify)
            self.assertEqual(verify["error_kind"], "inventoried_target_missing")
            self.assertFalse(verify["per_file"][0]["denied"])

    def test_icacls_fallback_requires_exact_rd_not_r(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            target = Path(td) / "target.json"
            target.write_text("{}", encoding="utf-8")
            user = "EXAMPLE\\exact-user"
            original_win32 = vault._deny_read_ace_present_win32
            real_run = sp.run

            def no_win32(path, identity):  # type: ignore[no-untyped-def]
                return {
                    "present": False,
                    "ok": False,
                    "query_ok": False,
                    "method": "win32",
                }

            vault._deny_read_ace_present_win32 = no_win32  # type: ignore[method-assign]
            try:

                def broad_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                    if argv[:1] == ["icacls"]:
                        return sp.CompletedProcess(argv, 0, f"{target} {user}:(DENY)(R)\n", "")
                    return real_run(argv, **kwargs)

                sp.run = broad_run  # type: ignore[assignment]
                broad = vault._deny_read_ace_present(target, user)
                self.assertFalse(broad["present"], broad)

                def exact_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                    if argv[:1] == ["icacls"]:
                        return sp.CompletedProcess(argv, 0, f"{target} {user}:(DENY)(RD)\n", "")
                    return real_run(argv, **kwargs)

                sp.run = exact_run  # type: ignore[assignment]
                exact = vault._deny_read_ace_present(target, user)
                self.assertTrue(exact["present"], exact)
            finally:
                sp.run = real_run  # type: ignore[assignment]
                vault._deny_read_ace_present_win32 = original_win32  # type: ignore[method-assign]

    def test_icacls_fallback_rejects_two_deny_occurrences_on_one_line(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            target = Path(td) / "target.json"
            target.write_text("{}", encoding="utf-8")
            user = "EXAMPLE\\exact-user"
            original_win32 = vault._deny_read_ace_present_win32
            real_run = sp.run

            def no_win32(path, identity):  # type: ignore[no-untyped-def]
                return {
                    "present": False,
                    "ok": False,
                    "query_ok": False,
                    "method": "win32",
                }

            def duplicate_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                if argv[:1] == ["icacls"]:
                    return sp.CompletedProcess(
                        argv,
                        0,
                        f"{target} {user}:(DENY)(RD) {user}:(DENY)(R)\n",
                        "",
                    )
                return real_run(argv, **kwargs)

            vault._deny_read_ace_present_win32 = no_win32  # type: ignore[method-assign]
            sp.run = duplicate_run  # type: ignore[assignment]
            try:
                result = vault._deny_read_ace_present(target, user)
            finally:
                sp.run = real_run  # type: ignore[assignment]
                vault._deny_read_ace_present_win32 = original_win32  # type: ignore[method-assign]
            self.assertFalse(result["present"], result)
            self.assertEqual(result["occurrence_count"], 2)

    def test_incomplete_win32_enumeration_cannot_fall_back_to_text(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            target = Path(td) / "target.json"
            target.write_text("{}", encoding="utf-8")
            user = "EXAMPLE\\exact-user"
            original_win32 = vault._deny_read_ace_present_win32
            real_run = sp.run
            called = {"icacls": 0}

            def incomplete(path, identity):  # type: ignore[no-untyped-def]
                return {
                    "present": False,
                    "ok": False,
                    "query_ok": False,
                    "enumeration_complete": False,
                    "terminal_enumeration_failure": True,
                    "enumeration_failure": "get_ace_failed",
                    "method": "win32",
                }

            def track_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                if argv[:1] == ["icacls"]:
                    called["icacls"] += 1
                return real_run(argv, **kwargs)

            vault._deny_read_ace_present_win32 = incomplete  # type: ignore[method-assign]
            sp.run = track_run  # type: ignore[assignment]
            try:
                result = vault._deny_read_ace_present(target, user)
            finally:
                sp.run = real_run  # type: ignore[assignment]
                vault._deny_read_ace_present_win32 = original_win32  # type: ignore[method-assign]
            self.assertFalse(result["present"], result)
            self.assertTrue(result["terminal_enumeration_failure"], result)
            self.assertEqual(called["icacls"], 0)

    def test_exact_win32_deny_rejects_inherited_or_propagation_flags(self) -> None:
        self.assertTrue(SealedTruthVault._exact_explicit_deny_rd_aces([(0x0001, 0)]))
        self.assertFalse(SealedTruthVault._exact_explicit_deny_rd_aces([(0x0001, 0x10)]))
        self.assertFalse(SealedTruthVault._exact_explicit_deny_rd_aces([(0x0001, 0x01)]))
        self.assertFalse(SealedTruthVault._exact_explicit_deny_rd_aces([(0x0001, 0), (0x0001, 0)]))

    def test_broad_prelift_acl_is_rejected_before_remove(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            vault.deposit_synthetic(
                public_case_id="syn-H01-001",
                public_prompt="p",
                truth={"answer": "A"},
                scoring_rule_private={"rule": "eq"},
                family_slot="H01",
                schedule_class="structural",
            )
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            user = vault._current_user()
            remove = sp.run(
                ["icacls", str(vault.truth_path), "/remove:d", user],
                capture_output=True,
                check=False,
            )
            broad = sp.run(
                ["icacls", str(vault.truth_path), "/deny", f"{user}:(R)"],
                capture_output=True,
                check=False,
            )
            self.assertEqual(remove.returncode, 0)
            self.assertEqual(broad.returncode, 0)
            original_lift = vault._icacls_remove_deny
            called = {"lift": 0}

            def track_lift(*args, **kwargs):  # type: ignore[no-untyped-def]
                called["lift"] += 1
                return original_lift(*args, **kwargs)

            vault._icacls_remove_deny = track_lift  # type: ignore[method-assign]
            try:
                with self.assertRaises((RuntimeError, OSError)):
                    vault._read_truth_unlocked(expected_receipt=False)
            finally:
                vault._icacls_remove_deny = original_lift  # type: ignore[method-assign]
                sp.run(
                    ["icacls", str(vault.truth_path), "/remove:d", user],
                    capture_output=True,
                    check=False,
                )
                sp.run(
                    ["icacls", str(vault.truth_path), "/deny", f"{user}:(RD)"],
                    capture_output=True,
                    check=False,
                )
            self.assertEqual(called["lift"], 0)

    def test_prelift_identity_handle_restores_original_dacl_after_drift(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            vault.deposit_synthetic(
                public_case_id="syn-H01-001",
                public_prompt="p",
                truth={"answer": "A"},
                scoring_rule_private={"rule": "eq"},
                family_slot="H01",
                schedule_class="structural",
            )
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            user = vault._current_user()
            identity_hold = vault._hold_target_identities([vault.truth_path])
            try:
                lift = vault._icacls_remove_deny(targets=[vault.truth_path], user=user)
                self.assertTrue(lift["ok"], lift)
                broad = subprocess.run(
                    ["icacls", str(vault.truth_path), "/deny", f"{user}:(R)"],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(broad.returncode, 0)
                broad_verify = vault._verify_direct_denial(
                    targets=[vault.truth_path],
                    user=user,
                    expected_identities=identity_hold["identities"],
                )
                self.assertFalse(broad_verify["denied"], broad_verify)

                handle_restore = vault._restore_handle_security_descriptors(identity_hold["holds"])
                self.assertTrue(handle_restore["ok"], handle_restore)
                original_verify = vault._verify_direct_denial(
                    targets=[vault.truth_path],
                    user=user,
                    expected_identities=identity_hold["identities"],
                )
                self.assertTrue(original_verify["denied"], original_verify)
            finally:
                vault._restore_handle_security_descriptors(identity_hold["holds"])
                vault._icacls_deny_current_user(targets=[vault.truth_path], user=user)
                vault._close_stable_identity_handles(identity_hold["holds"])

    def test_postrestore_identity_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            identity_hold = vault._hold_target_identities([vault.truth_path])
            expected = dict(identity_hold["identities"])
            key = vault._identity_key(vault.truth_path)
            volume, file_id = expected[key]
            expected[key] = (volume, bytes([file_id[0] ^ 1]) + file_id[1:])
            try:
                verify = vault._verify_direct_denial(
                    targets=[vault.truth_path], expected_identities=expected
                )
            finally:
                vault._close_stable_identity_handles(identity_hold["holds"])
            self.assertFalse(verify["denied"], verify)
            self.assertEqual(
                verify["per_file"][0]["error_kind"],
                "prelift_file_identity_replaced",
            )

    def test_account_query_failure_occurs_before_any_acl_lift(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            vault.deposit_synthetic(
                public_case_id="syn-H01-001",
                public_prompt="p",
                truth={"answer": "A"},
                scoring_rule_private={"rule": "eq"},
                family_slot="H01",
                schedule_class="structural",
            )
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            user = vault._current_user()
            original_user = vault._current_user
            original_lift = vault._icacls_remove_deny
            called = {"lift": 0}

            def fail_user():  # type: ignore[no-untyped-def]
                raise subprocess.TimeoutExpired(cmd=["whoami"], timeout=30)

            def track_lift(*args, **kwargs):  # type: ignore[no-untyped-def]
                called["lift"] += 1
                return original_lift(*args, **kwargs)

            vault._current_user = fail_user  # type: ignore[method-assign]
            vault._icacls_remove_deny = track_lift  # type: ignore[method-assign]
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    vault._read_truth_unlocked(expected_receipt=False)
            finally:
                vault._current_user = original_user  # type: ignore[method-assign]
                vault._icacls_remove_deny = original_lift  # type: ignore[method-assign]
            self.assertEqual(called["lift"], 0)
            verify = vault._verify_direct_denial(user=user, expected_receipt=False)
            self.assertTrue(verify["denied"], verify)

    def test_partial_lift_nonzero_then_restore(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            vault.deposit_synthetic(
                public_case_id="syn-H01-001",
                public_prompt="p",
                truth={"answer": "A"},
                scoring_rule_private={"rule": "eq"},
                family_slot="H01",
                schedule_class="structural",
            )
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            targets = vault._controlled_vault_targets(expected_receipt=False)
            self.assertGreaterEqual(len(targets), 2)

            real_run = sp.run
            call_state = {"n": 0}

            def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                # Intercept only remove:d (lift). First file succeeds, second nonzero.
                if len(argv) >= 3 and argv[0] == "icacls" and argv[2] == "/remove:d":
                    call_state["n"] += 1
                    if call_state["n"] == 1:
                        return real_run(argv, **kwargs)
                    return sp.CompletedProcess(argv, 1, b"", b"partial fail")
                return real_run(argv, **kwargs)

            original = sp.run
            sp.run = fake_run  # type: ignore[assignment]
            try:
                with self.assertRaises(PermissionError):
                    vault._read_truth_unlocked(expected_receipt=False)
            finally:
                sp.run = original  # type: ignore[assignment]

            verify = vault._verify_direct_denial(targets=targets)
            self.assertTrue(verify.get("denied"), verify)
            for item in verify.get("per_file") or []:
                if item.get("skipped") == "missing":
                    continue
                self.assertTrue(item.get("denied"), item)

    def test_partial_lift_exception_then_restore(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            vault.deposit_synthetic(
                public_case_id="syn-H01-001",
                public_prompt="p",
                truth={"answer": "A"},
                scoring_rule_private={"rule": "eq"},
                family_slot="H01",
                schedule_class="structural",
            )
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            targets = vault._controlled_vault_targets(expected_receipt=False)
            real_run = sp.run
            call_state = {"n": 0}

            def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                if len(argv) >= 3 and argv[0] == "icacls" and argv[2] == "/remove:d":
                    call_state["n"] += 1
                    if call_state["n"] == 1:
                        return real_run(argv, **kwargs)
                    raise sp.SubprocessError("injected_subprocess_exception")
                return real_run(argv, **kwargs)

            original = sp.run
            sp.run = fake_run  # type: ignore[assignment]
            try:
                with self.assertRaises(PermissionError):
                    vault._read_truth_unlocked(expected_receipt=False)
            finally:
                sp.run = original  # type: ignore[assignment]
            verify = vault._verify_direct_denial(targets=targets)
            self.assertTrue(verify.get("denied"), verify)

    def test_partial_lift_timeout_then_restore(self) -> None:
        import subprocess as sp

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            vault = SealedTruthVault(Path(td) / "vault")
            vault.deposit_synthetic(
                public_case_id="syn-H01-001",
                public_prompt="p",
                truth={"answer": "A"},
                scoring_rule_private={"rule": "eq"},
                family_slot="H01",
                schedule_class="structural",
            )
            self.assertTrue(vault.lock_down_host_reads(expected_receipt=False)["ok"])
            targets = vault._controlled_vault_targets(expected_receipt=False)
            real_run = sp.run
            call_state = {"n": 0}

            def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
                if len(argv) >= 3 and argv[0] == "icacls" and argv[2] == "/remove:d":
                    call_state["n"] += 1
                    if call_state["n"] == 1:
                        return real_run(argv, **kwargs)
                    raise sp.TimeoutExpired(cmd=argv, timeout=30)
                return real_run(argv, **kwargs)

            original = sp.run
            sp.run = fake_run  # type: ignore[assignment]
            try:
                with self.assertRaises(PermissionError):
                    vault._read_truth_unlocked(expected_receipt=False)
            finally:
                sp.run = original  # type: ignore[assignment]
            verify = vault._verify_direct_denial(targets=targets)
            self.assertTrue(verify.get("denied"), verify)
            for item in verify.get("per_file") or []:
                if item.get("skipped") == "missing":
                    continue
                self.assertTrue(item.get("denied"), item)


class TestObjects(unittest.TestCase):
    def test_calibration_shape(self) -> None:
        c = build_calibration_contract_shape()
        self.assertFalse(c["scoring_enabled"])
        self.assertFalse(c["hidden_cases_consumed"])
        self.assertFalse(c["calibration_executed"])

    def test_heldout_collision(self) -> None:
        bad = build_heldout_attestation(
            training_identity_sha256="a" * 64,
            heldout_identity_sha256="a" * 64,
        )
        self.assertFalse(bad["ok"])

    def test_manifest_rejects_forbidden(self) -> None:
        route = build_route_descriptor(
            route_label="r",
            promptfoo_version="0.121.18",
            offline=True,
            cache_enabled=False,
            network_enabled=False,
        )
        m = build_subject_public_manifest(
            suite_identity_sha256="s" * 64,
            public_cases=[
                {
                    "public_case_id": "c",
                    "public_prompt": "p",
                    "commitment_sha256": "c" * 64,
                    "schedule_slot": "H01",
                }
            ],
            route_identity_sha256=route["route_identity_sha256"],
            adapter_identity_sha256="a" * 64,
        )
        self.assertIn("manifest_identity_sha256", m)
        self.assertIn("public_manifest_blueprint_commitment", m)
        self.assertEqual(len(scan_forbidden_public_payload(m)), 0)


class TestSuiteBuilder(unittest.TestCase):
    def test_build_suite(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            s = build_synthetic_suite(td)
            self.assertTrue(s["ok"], s)
            self.assertEqual(len(s["schedule_slots"]), 21)
            self.assertTrue(s["objects_validation"]["ok"], s["objects_validation"])
            env = json.loads(
                (Path(td) / "objects" / "HiddenSuiteIdentityEnvelope.v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("canonical_suite_commitment", env)
            self.assertIn("evaluator_code_hash", env)
            # No post-hash empty binding
            self.assertTrue(env.get("realized_manifest_binding"))
            self.assertNotEqual(env["exposure_ledger_sealed_head_contract"], "0" * 64)
            self.assertEqual(
                env["exposure_ledger_sealed_head_contract"],
                s["runtime_exposure_head_sha256"],
            )
            self.assertTrue(validate_object(env, "HiddenSuiteIdentityEnvelope")["ok"])


class TestHardNegatives(unittest.TestCase):
    def test_all_hard_negatives(self) -> None:
        r = run_hard_negatives()
        self.assertTrue(r["all_passed"], r)
        self.assertEqual(r["count"], 45)


if __name__ == "__main__":
    unittest.main()
