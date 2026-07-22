"""End-to-end non-authority package flow: build -> docker promptfoo -> envelope -> evaluator."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import PACKAGE_ID, SYNTHETIC_LABEL
from .atomic_state import AtomicSeamState
from .audit_log import AuditRunLog
from .canonical import raw_bytes_sha256_file, read_json, write_json
from .evaluator import IndependentEvaluator
from .objects import build_immutable_run_envelope, validate_object
from .objects import expected_case_set_identity_sha256, expected_public_case_ids
from .promptfoo_runner import (
    assert_no_inspect_ai,
    build_promptfoo_config,
    clean_promptfoo_transients,
    default_denied_roots,
    inventory_forbidden_transients,
    run_adversarial_isolation,
    run_promptfoo_offline,
    run_timeout_child_probe,
)
from .run_idempotency import RunIdempotencyRegistry
from .suite_builder import build_synthetic_suite
from .vault import FINAL_TARGET_NAMES, PRE_RECEIPT_TARGET_NAMES, SealedTruthVault


def _exact_string_set(value: Any, expected: tuple[str, ...]) -> bool:
    return bool(
        isinstance(value, list)
        and len(value) == len(expected)
        and all(isinstance(item, str) for item in value)
        and set(value) == set(expected)
    )


def _complete_discovery_receipt(
    receipt: Any, *, expected_names: tuple[str, ...], expected_receipt: bool
) -> bool:
    if not isinstance(receipt, dict):
        return False
    expected_identities = receipt.get("expected_normalized_identities")
    observed_identities = receipt.get("observed_normalized_identities")
    return bool(
        receipt.get("ok") is True
        and receipt.get("expected_receipt") is expected_receipt
        and receipt.get("enumeration_complete") is True
        and _exact_string_set(receipt.get("expected_target_names"), expected_names)
        and _exact_string_set(receipt.get("observed_target_names"), expected_names)
        and isinstance(expected_identities, list)
        and isinstance(observed_identities, list)
        and len(expected_identities) == len(expected_names)
        and len(observed_identities) == len(expected_names)
        and all(isinstance(item, str) for item in expected_identities)
        and all(isinstance(item, str) for item in observed_identities)
        and len(set(expected_identities)) == len(expected_names)
        and set(expected_identities) == set(observed_identities)
        and receipt.get("missing") == []
        and receipt.get("extra") == []
        and receipt.get("problems") == []
        and receipt.get("content_recorded") is False
    )


def _complete_identity_proof(result: Any, *, expected_names: tuple[str, ...]) -> bool:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return False
    rows = result.get("results")
    return bool(
        isinstance(rows, list)
        and len(rows) == len(expected_names)
        and _exact_string_set(
            [row.get("path") for row in rows if isinstance(row, dict)],
            expected_names,
        )
        and all(
            isinstance(row, dict)
            and row.get("matches") is True
            and row.get("content_recorded") is False
            for row in rows
        )
    )


def _complete_direct_denial_proof(result: Any, *, expected_names: tuple[str, ...]) -> bool:
    if not isinstance(result, dict):
        return False
    rows = result.get("per_file")
    return bool(
        result.get("denied") is True
        and result.get("readable") is False
        and result.get("content_recorded") is False
        and isinstance(rows, list)
        and len(rows) == len(expected_names)
        and _exact_string_set(
            [row.get("path") for row in rows if isinstance(row, dict)],
            expected_names,
        )
        and all(
            isinstance(row, dict)
            and row.get("denied") is True
            and row.get("readable") is False
            and row.get("deny_ace_present") is True
            and row.get("file_identity_matches") is True
            and row.get("content_recorded") is False
            for row in rows
        )
    )


def _complete_acl_apply_proof(result: Any, *, expected_names: tuple[str, ...]) -> bool:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return False
    rows = result.get("results")
    return bool(
        _exact_string_set(result.get("attempted_targets"), expected_names)
        and isinstance(rows, list)
        and len(rows) == len(expected_names)
        and _exact_string_set(
            [row.get("path") for row in rows if isinstance(row, dict)],
            expected_names,
        )
        and all(
            isinstance(row, dict)
            and row.get("attempted") is True
            and row.get("ok") is True
            and row.get("deny_ace_present") is True
            and row.get("access_denied") is True
            for row in rows
        )
    )


def _complete_lockdown_proof(
    result: Any,
    *,
    expected_names: tuple[str, ...],
    direct_verify_key: str,
    hold_flag: str,
) -> bool:
    if not isinstance(result, dict):
        return False
    binding = result.get("identity_binding")
    return bool(
        result.get("ok") is True
        and result.get("target_set_exact") is True
        and _exact_string_set(result.get("expected_target_names"), expected_names)
        and _exact_string_set(result.get("attempted_targets"), expected_names)
        and isinstance(binding, dict)
        and binding.get("ok") is True
        and binding.get("target_count") == len(expected_names)
        and _exact_string_set(binding.get("target_names"), expected_names)
        and binding.get(hold_flag) is True
        and _complete_acl_apply_proof(result.get("acl_apply"), expected_names=expected_names)
        and _complete_direct_denial_proof(
            result.get(direct_verify_key), expected_names=expected_names
        )
        and _complete_identity_proof(result.get("identity_verify"), expected_names=expected_names)
    )


def _complete_live_verification(result: Any, *, expected_names: tuple[str, ...]) -> bool:
    if not isinstance(result, dict):
        return False
    binding = result.get("identity_binding")
    return bool(
        result.get("ok") is True
        and result.get("target_set_exact") is True
        and result.get("expected_receipt") is True
        and _exact_string_set(result.get("expected_target_names"), expected_names)
        and _exact_string_set(result.get("attempted_targets"), expected_names)
        and _complete_discovery_receipt(
            result.get("pre_target_set"),
            expected_names=expected_names,
            expected_receipt=True,
        )
        and _complete_discovery_receipt(
            result.get("post_target_set"),
            expected_names=expected_names,
            expected_receipt=True,
        )
        and isinstance(binding, dict)
        and binding.get("ok") is True
        and binding.get("target_count") == len(expected_names)
        and _exact_string_set(binding.get("target_names"), expected_names)
        and binding.get("non_delete_shared_handles_held_until_gate_exit") is True
        and _complete_direct_denial_proof(
            result.get("direct_verify"), expected_names=expected_names
        )
        and _complete_identity_proof(result.get("identity_verify"), expected_names=expected_names)
    )


def _run_post_lockdown_subject_probes(
    *,
    vault: SealedTruthVault,
    lockdown: dict[str, Any],
    lockdown_receipt: dict[str, Any],
    pf_state: Path,
    run_adversarial: bool,
    run_timeout_probe: bool,
) -> dict[str, Any]:
    """Start no later subject-like work until all Vault targets are sealed."""
    initial_exact = bool(
        _complete_discovery_receipt(
            lockdown.get("pre_target_set"),
            expected_names=PRE_RECEIPT_TARGET_NAMES,
            expected_receipt=False,
        )
        and _complete_discovery_receipt(
            lockdown.get("post_target_set"),
            expected_names=PRE_RECEIPT_TARGET_NAMES,
            expected_receipt=False,
        )
    )
    initial_denial = _complete_lockdown_proof(
        lockdown,
        expected_names=PRE_RECEIPT_TARGET_NAMES,
        direct_verify_key="direct_verify",
        hold_flag="non_delete_shared_handles_held_through_final_check",
    )
    final_exact = bool(
        _complete_discovery_receipt(
            lockdown_receipt.get("pre_publication_target_set"),
            expected_names=PRE_RECEIPT_TARGET_NAMES,
            expected_receipt=False,
        )
        and _complete_discovery_receipt(
            lockdown_receipt.get("pre_seal_target_set"),
            expected_names=FINAL_TARGET_NAMES,
            expected_receipt=True,
        )
        and _complete_discovery_receipt(
            lockdown_receipt.get("post_seal_target_set"),
            expected_names=FINAL_TARGET_NAMES,
            expected_receipt=True,
        )
    )
    final_denial = bool(
        _complete_lockdown_proof(
            lockdown_receipt,
            expected_names=FINAL_TARGET_NAMES,
            direct_verify_key="final_verify",
            hold_flag="non_delete_shared_handles_held_through_final_check",
        )
        and (lockdown_receipt.get("identity_binding") or {}).get(
            "pre_receipt_targets_held_across_publication"
        )
        is True
    )
    receipt_evidence_complete = bool(
        initial_exact and initial_denial and final_exact and final_denial
    )
    if not receipt_evidence_complete:
        return {
            "ok": False,
            "phase": "vault_lockdown_gate",
            "gate_ok": False,
            "initial_target_set_exact": initial_exact,
            "initial_denial_evidence_complete": initial_denial,
            "final_target_set_exact": final_exact,
            "final_denial_evidence_complete": final_denial,
            "receipt_evidence_complete": False,
            "actual_final_vault": None,
            "subject_like_work_started": False,
            "adversarial_isolation": None,
            "timeout_child_probe": None,
        }

    with vault.hold_verified_locked_phase(expected_receipt=True) as actual_final:
        actual_final_ok = _complete_live_verification(
            actual_final, expected_names=FINAL_TARGET_NAMES
        )
        if not actual_final_ok:
            return {
                "ok": False,
                "phase": "vault_lockdown_gate",
                "gate_ok": False,
                "initial_target_set_exact": initial_exact,
                "initial_denial_evidence_complete": initial_denial,
                "final_target_set_exact": final_exact,
                "final_denial_evidence_complete": final_denial,
                "receipt_evidence_complete": True,
                "actual_final_vault": actual_final,
                "subject_like_work_started": False,
                "adversarial_isolation": None,
                "timeout_child_probe": None,
            }

        adversarial = (
            run_adversarial_isolation(state_root=pf_state / "adversarial")
            if run_adversarial
            else None
        )
        timeout_probe = (
            run_timeout_child_probe(state_root=pf_state / "timeout_probe")
            if run_timeout_probe
            else None
        )
    ok = bool(
        (adversarial is None or adversarial.get("ok"))
        and (timeout_probe is None or timeout_probe.get("ok"))
    )
    return {
        "ok": ok,
        "phase": "post_lockdown_subject_probes",
        "gate_ok": True,
        "initial_target_set_exact": True,
        "initial_denial_evidence_complete": True,
        "final_target_set_exact": True,
        "final_denial_evidence_complete": True,
        "receipt_evidence_complete": True,
        "actual_final_vault": actual_final,
        "subject_like_work_started": bool(run_adversarial or run_timeout_probe),
        "adversarial_isolation": adversarial,
        "timeout_child_probe": timeout_probe,
    }


def execute_offline_run(
    *,
    package_root: str | Path,
    op_name: str = "op_main",
    run_id: str = "run_syn_offline_001",
    attempt_id: str = "attempt_1",
    clean_op_root: bool = True,
    run_adversarial: bool = True,
    run_timeout_probe: bool = True,
) -> dict[str, Any]:
    root = Path(package_root).resolve()
    op = root / "ops" / op_name
    if clean_op_root and op.exists():
        vault_dir = op / "vault"
        vault_for_cleanup: SealedTruthVault | None = None
        if vault_dir.is_dir():
            vault_for_cleanup = SealedTruthVault(vault_dir)
            unlocked = vault_for_cleanup.unlock_host_reads(expected_receipt=True)
            if unlocked.get("ok") is not True:
                restored = vault_for_cleanup.lock_down_host_reads(expected_receipt=True)
                return {
                    "ok": False,
                    "phase": "clean_op_root",
                    "cleanup": unlocked,
                    "restore_after_partial_unlock": restored,
                }
        try:
            shutil.rmtree(op)
        except OSError as exc:
            restored = None
            if vault_for_cleanup is not None and vault_dir.is_dir():
                restored = vault_for_cleanup.lock_down_host_reads(expected_receipt=True)
            return {
                "ok": False,
                "phase": "clean_op_root",
                "cleanup": {
                    "ok": False,
                    "error_class": type(exc).__name__,
                    "vault_relock": restored,
                },
            }
    op.mkdir(parents=True, exist_ok=True)
    summary = build_synthetic_suite(op)
    if not summary.get("ok"):
        return {"ok": False, "phase": "suite_build", "summary": summary}

    ledger_root = Path(summary["ledger_root"])
    state = AtomicSeamState(summary["state_db"], max_attempts=64)
    audit = AuditRunLog(ledger_root / "audit_run_log.jsonl")
    idem = RunIdempotencyRegistry(
        ledger_root / "run_idempotency.json",
        state=state,
        max_attempts=64,
    )

    adapter_path = root / "adapters" / "promptfoo_subject_adapter.py"
    adapter_descriptor = read_json(op / "objects" / "PromptfooSubjectAdapter.v1.json")
    public_manifest = read_json(op / "public" / "subject_public_manifest.v1.json")
    adapter_validation = validate_object(adapter_descriptor, "PromptfooSubjectAdapter")
    manifest_validation = validate_object(public_manifest, "SubjectPublicManifest")
    adapter_sha256, _adapter_size = raw_bytes_sha256_file(adapter_path)
    if not (
        adapter_validation.get("ok")
        and manifest_validation.get("ok")
        and adapter_sha256 == adapter_descriptor.get("adapter_source_sha256")
        and public_manifest.get("adapter_identity_sha256")
        == adapter_descriptor.get("adapter_identity_sha256")
    ):
        return {
            "ok": False,
            "phase": "adapter_descriptor_binding",
            "adapter_validation": adapter_validation,
            "manifest_validation": manifest_validation,
        }

    # Use-time atomic claim: suite active + unique run_id
    claim = idem.claim_run(
        run_id=run_id,
        attempt_id=attempt_id,
        route_identity_sha256=summary["route_identity_sha256"],
        suite_identity_sha256=summary["suite_identity_sha256"],
    )
    if not claim.get("ok"):
        return {"ok": False, "phase": "idempotency_claim", "claim": claim}

    pf_root = Path(summary["promptfoo_root"])
    cfg = build_promptfoo_config(
        config_dir=pf_root / "config",
        adapter_path=adapter_path,
        cases_path=Path(summary["materialized_cases_path"]),
    )
    audit.append_event("promptfoo_config_built", {"config_path": cfg["config_path"]})

    pf_state = pf_root / "state"
    pf_out = pf_root / "output" / "promptfoo_results.json"
    inspect = assert_no_inspect_ai()
    trusted_allowed_roots = [
        Path(cfg["config_path"]).parent,
        pf_state,
        pf_out.parent,
    ]
    trusted_denied_roots = default_denied_roots(
        vault_root=Path(summary["vault_root"]),
        evaluator_root=Path(summary["evaluator_root"]),
        op_root=op,
    )

    # Durable side-effect start BEFORE container start
    se_start = idem.mark_side_effect_started(run_id=run_id)
    if not se_start.get("ok"):
        return {"ok": False, "phase": "side_effect_start", "result": se_start}

    pf = run_promptfoo_offline(
        config_path=Path(cfg["config_path"]),
        state_root=pf_state,
        output_path=pf_out,
        adapter_host_path=adapter_path,
        expected_adapter_sha256=adapter_sha256,
        run_id=run_id,
        op_root=op,
        vault_root=Path(summary["vault_root"]),
        evaluator_root=Path(summary["evaluator_root"]),
        allowed_roots=trusted_allowed_roots,
        denied_roots=trusted_denied_roots,
        expected_case_ids=expected_public_case_ids(),
        expected_config_sha256=cfg["config_sha256"],
        expected_cases_sha256=cfg["cases_sha256"],
    )
    pf_ident = pf.get("promptfoo_identity") or {}
    se = idem.mark_side_effect(run_id=run_id)
    if not se.get("ok"):
        return {"ok": False, "phase": "side_effect_mark", "result": se, "promptfoo": pf}

    audit.append_event(
        "promptfoo_run",
        {
            "ok": pf.get("ok"),
            "terminal_status": pf.get("terminal_status"),
            "returncode": pf.get("returncode"),
            "network_mode": pf.get("network_mode"),
            "offline_enforced": pf.get("offline_enforced"),
        },
    )

    raw_outputs: list[dict[str, Any]] = []
    if pf_out.exists():
        try:
            data = json.loads(pf_out.read_text(encoding="utf-8"))
            results = data.get("results") or data
            if isinstance(results, dict):
                rows = results.get("results") or []
            else:
                rows = results if isinstance(results, list) else []
            for row in rows:
                raw_outputs.append(
                    {
                        "synthetic": True,
                        "label": SYNTHETIC_LABEL,
                        "row_keys": sorted(list(row.keys())) if isinstance(row, dict) else [],
                        "output_excerpt": (
                            str(row)[:500]
                            if not isinstance(row, dict)
                            else str(row.get("response") or row.get("output") or "")[:500]
                        ),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            raw_outputs.append({"parse_error": type(exc).__name__, "synthetic": True})

    terminal = pf.get("terminal_status") or "failed"
    if not pf.get("ok"):
        terminal = terminal if terminal != "completed" else "failed"

    envelope = build_immutable_run_envelope(
        run_id=run_id,
        attempt_id=attempt_id,
        suite_identity_sha256=summary["suite_identity_sha256"],
        route_identity_sha256=summary["route_identity_sha256"],
        manifest_identity_sha256=summary["manifest_identity_sha256"],
        raw_outputs=raw_outputs,
        telemetry={
            "promptfoo": {
                "ok": pf.get("ok"),
                "returncode": pf.get("returncode"),
                "cache_enabled": False,
                "version": (pf.get("promptfoo_identity") or {}).get("version"),
                "network_mode": pf.get("network_mode"),
                "offline_enforced": pf.get("offline_enforced"),
                "execution_boundary": pf.get("execution_boundary"),
                "host_promptfoo_executed": pf.get("host_promptfoo_executed"),
                "case_set_identity_sha256": pf.get("case_set_identity_sha256")
                or expected_case_set_identity_sha256(),
                "result_parse_ok": (pf.get("result_parse") or {}).get("ok"),
            },
            "inspect_ai": inspect,
            "side_effect_count": se.get("side_effect_count"),
            "side_effect_started": True,
            "case_set_identity_sha256": expected_case_set_identity_sha256(),
        },
        terminal_status=terminal
        if pf.get("ok")
        else ("failed" if terminal == "completed" else terminal),
        promoted_to_pass=False,
    )

    env_path = op / "public" / "immutable_run_envelope.v1.json"
    write_json(env_path, envelope)
    write_json(op / "objects" / "ImmutableRunEnvelope.v1.json", envelope)

    manifest = json.loads(
        (op / "public" / "subject_public_manifest.v1.json").read_text(encoding="utf-8")
    )
    vault = SealedTruthVault(summary["vault_root"])
    evaluator = IndependentEvaluator(state_root=summary["evaluator_root"], vault=vault)
    pf_config_dict = cfg.get("config_public") or {
        "cache": False,
        "tests": "file://public_cases.json",
        "description": "synthetic offline",
        "evaluateOptions": {"cache": False},
    }
    ev = evaluator.verify_isolation_interface(
        run_envelope=envelope,
        public_manifest=manifest,
        promptfoo_config=pf_config_dict,
    )
    audit.append_event("evaluator_complete", {"ok": ev.get("ok")})

    # Lock down vault host readability after evaluator finished
    lockdown = vault.lock_down_host_reads(expected_receipt=False)
    lockdown_receipt = (
        vault.publish_lockdown_receipt(lockdown)
        if lockdown.get("ok")
        else {
            "ok": False,
            "reason": "initial_vault_lockdown_failed",
            "target_set_exact": False,
            "content_recorded": False,
            "authority": False,
        }
    )

    # Duplicate run_id must fail without second side effect
    dup = idem.claim_run(
        run_id=run_id,
        attempt_id="attempt_2_should_block",
        route_identity_sha256=summary["route_identity_sha256"],
        suite_identity_sha256=summary["suite_identity_sha256"],
    )
    st = idem.status()

    post_lockdown = _run_post_lockdown_subject_probes(
        vault=vault,
        lockdown=lockdown,
        lockdown_receipt=lockdown_receipt,
        pf_state=pf_state,
        run_adversarial=run_adversarial,
        run_timeout_probe=run_timeout_probe,
    )
    adv = post_lockdown["adversarial_isolation"]
    if adv is not None:
        write_json(op / "evaluator" / "latest_isolation_result.v1.json", adv)
        audit.append_event("adversarial_isolation", {"ok": adv.get("ok")})

    timeout_probe = post_lockdown["timeout_child_probe"]
    if timeout_probe is not None:
        write_json(op / "evaluator" / "timeout_child_probe.v1.json", timeout_probe)
        audit.append_event("timeout_child_probe", {"ok": timeout_probe.get("ok")})

    # Final seals
    audit_seal = audit.log.write_seal_receipt(ledger_root / "audit_run_log.seal.v1.json")
    from .exposure_ledger import ExposureLedger

    exp = ExposureLedger(ledger_root / "exposure_ledger.jsonl")
    exp_seal = exp.log.write_seal_receipt(ledger_root / "exposure_ledger.seal.v1.json")

    # Clean promptfoo transients before success — structured fail-closed
    cleanup = clean_promptfoo_transients(pf_state)
    removed = list(cleanup.get("removed") or [])
    cleanup_extra_failures: list[dict[str, str]] = list(cleanup.get("failures") or [])
    for sub in (pf_state / "adversarial", pf_state / "timeout_probe"):
        if sub.exists():
            for p in sub.rglob("*"):
                if p.is_file() and p.suffix in {".py", ".db", ".log"}:
                    try:
                        p.unlink()
                        removed.append(str(p))
                    except OSError as exc:
                        cleanup_extra_failures.append(
                            {
                                "path": str(p),
                                "error_class": type(exc).__name__,
                                "action": "unlink",
                            }
                        )
    # Exhaustive post-cleanup inventory across the whole operation root
    inventory = inventory_forbidden_transients(op)
    cleanup_ok = (
        cleanup.get("ok") is True
        and len(cleanup_extra_failures) == 0
        and inventory.get("ok") is True
    )

    ok = bool(
        pf.get("ok")
        and ev.get("ok")
        and pf_ident.get("ok")
        and inspect.get("ok")
        and not dup.get("ok")
        and st.get("side_effect_count") == 1
        and st.get("side_effect_started_count") == 1
        and (adv is None or adv.get("ok"))
        and (timeout_probe is None or timeout_probe.get("ok"))
        and lockdown.get("ok")
        and lockdown_receipt.get("ok")
        and post_lockdown.get("ok")
        and cleanup_ok
        and (pf.get("result_parse") or {}).get("ok") is True
    )

    out = {
        "ok": ok,
        "package_id": PACKAGE_ID,
        "suite_summary": {
            k: summary[k]
            for k in (
                "ok",
                "suite_identity_sha256",
                "route_identity_sha256",
                "manifest_identity_sha256",
                "schedule_slots",
                "state_db",
            )
            if k in summary
        },
        "promptfoo": {
            k: pf.get(k)
            for k in (
                "ok",
                "phase",
                "reason",
                "terminal_status",
                "returncode",
                "network_mode",
                "offline_enforced",
                "offline_probe",
                "cache_enabled",
                "scoring_enabled",
                "execution_boundary",
                "host_promptfoo_executed",
                "container_name",
                "pre_start",
                "promptfoo_identity",
                "private_snapshot_copy",
                "result_parse",
            )
        },
        "promptfoo_identity": pf_ident,
        "inspect_ai": inspect,
        "envelope": {
            "run_id": envelope["run_id"],
            "terminal_status": envelope["terminal_status"],
            "envelope_identity_sha256": envelope["envelope_identity_sha256"],
            "scoring_enabled": envelope["scoring_enabled"],
            "hidden_cases_consumed": envelope["hidden_cases_consumed"],
            "promoted_to_pass": envelope.get("promoted_to_pass"),
        },
        "evaluator": ev,
        "adversarial_isolation": adv,
        "timeout_child_probe": timeout_probe,
        "vault_host_lockdown": lockdown,
        "vault_lockdown_receipt": lockdown_receipt,
        "post_lockdown_subject_gate": post_lockdown,
        "duplicate_run_blocked": not dup.get("ok"),
        "side_effect_count": st.get("side_effect_count"),
        "side_effect_started_count": st.get("side_effect_started_count"),
        "audit_seal": audit_seal,
        "exposure_seal": exp_seal,
        "transients_removed": removed,
        "transient_cleanup": {
            "ok": cleanup_ok,
            "cleanup": cleanup,
            "extra_failures": cleanup_extra_failures,
            "inventory": inventory,
        },
        "case_set_identity_sha256": expected_case_set_identity_sha256(),
        "synthetic_only": True,
        "label": SYNTHETIC_LABEL,
        "authority": False,
        "g4_closed": False,
        "g5_active": False,
        "completion_claim_allowed": False,
        "admission": False,
        "parent_complete": False,
    }
    write_json(op / "offline_run_result.v1.json", out)
    return out
