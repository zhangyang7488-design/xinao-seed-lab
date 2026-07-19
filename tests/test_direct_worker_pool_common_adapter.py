"""Tests for the direct WorkerPool to common receipt adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from services.agent_runtime import direct_worker_pool_common_adapter as adapter
from services.agent_runtime.execution_contract import (
    artifact_json_bytes,
    classify_identical_work_disposition,
    logical_contract_sha256,
    validate_attempt_receipt,
)
from services.agent_runtime.grok_execution_contract_adapter import (
    GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    build_direct_worker_pool_logical_contract,
    direct_worker_pool_capability_binding,
)

SUBJECT = "b" * 64
RULES = "c" * 64
FROZEN_CONTEXT = "d" * 64
OUTPUT_CONTRACT = "e" * 64
INPUT_SHA = "a" * 64
CAP_BINDING = direct_worker_pool_capability_binding(
    selection_decision_sha256="f" * 64,
    output_contract_sha256=OUTPUT_CONTRACT,
)


def _contract() -> dict[str, Any]:
    return build_direct_worker_pool_logical_contract(
        work_key="wk:MEDIUM:WORKERPOOL_COMMON_RECEIPT_ADAPTER_IMPL:20260720",
        operation_id="op-direct-pool-adapter-1",
        task_contract_ref="task-direct-pool-1",
        parent_operation_id="parent-composer25-mainline",
        correlation_id="corr-direct-pool-1",
        provider_id="grok_acpx_headless",
        profile_ref="grok.com.cached_profile",
        model_id="grok-4.5",
        frozen_input_sha256=INPUT_SHA,
        frozen_context_sha256=FROZEN_CONTEXT,
        subject_manifest_sha256=SUBJECT,
        rules_sha256=RULES,
        output_contract_sha256=OUTPUT_CONTRACT,
        capability_binding=CAP_BINDING,
        write=False,
        deadline_seconds=600,
    )


def _common_preflight() -> dict[str, Any]:
    contract = _contract()
    return {
        "validated": True,
        "logical_contract_sha256": logical_contract_sha256(contract),
        "frozen_context_sha256": FROZEN_CONTEXT,
        "subject_manifest_sha256": SUBJECT,
        "input_sha256": contract["input_sha256"],
        "context_sha256": contract["context_sha256"],
        "rules_sha256": contract["rules_sha256"],
        "output_contract_sha256": contract["output_contract_sha256"],
        "capability_binding_sha256": contract["selection"][
            "capability_binding_sha256"
        ],
    }


def _result_text_sha() -> str:
    return "4545a75a86a54fe5c38c2e89c1480a29a6d28843fbe63993c7dcc40b113fa56b"


def _lane_meta(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "xinao.grok_composer25_worker.v2",
        "execution_contract_version": "xinao.grok.shared_execution_contract.v1",
        "run_id": "c25_20260720T055205_74ed0dc5",
        "requested_model": "grok-4.5",
        "cli_version": "0.2.103",
        "short_execution_contract_sha256": RULES,
        "observed_rules_sha256": RULES,
        "observed_capability_binding_sha256": _contract()["selection"][
            "capability_binding_sha256"
        ],
        "common_contract_preflight": _common_preflight(),
        "status": "accepted",
        "outcome": "accepted",
        "effective_output_accepted": True,
        "session_model": "grok-4.5",
        "backend_model_identity_ok": True,
        "session_model_identity_ok": True,
        "session_turn_model_identity_ok": True,
        "session_evidence_ok": True,
        "model_identity_ok": True,
        "usage_accounting_complete": True,
        "usage_is_incomplete": False,
        "stop_reason": "EndTurn",
        "result_text_sha256": _result_text_sha(),
        "result_text_chars": 10225,
        "structured_output_present": False,
        "json_schema_requested": False,
        "schema_instance_valid": None,
        "session_id": "019f7c5d-737b-7323-be1d-0f4bc8ac20bc",
        "session_evidence_dir": (
            r"C:\Users\xx363\.grok-bg-workers\sessions\cwd\019f7c5d-737b-7323-be1d-0f4bc8ac20bc"
        ),
        "usage": {
            "input_tokens": 78536,
            "cache_read_input_tokens": 564480,
            "output_tokens": 10933,
            "reasoning_tokens": 7376,
            "total_tokens": 653949,
        },
        "argv_transport": "process_start_info_argument_list",
        "drain": "synchronous_process",
        "hot_path_cn": "Codex->Grok headless worker (not visible TUI inject; not Docker desktop .lnk)",
        "create_no_window": True,
        "completion_claim_allowed": False,
        "canonical_worker_pool": True,
    }
    base.update(overrides)
    return base


def _pool_summary(
    tmp_path: Path,
    *,
    lane_meta: dict[str, Any] | None = None,
    lane_index: int = 0,
    **summary_overrides: Any,
) -> tuple[dict[str, Any], Path, Path]:
    lane_dir = tmp_path / f"lane_{lane_index:02d}"
    lane_dir.mkdir(parents=True, exist_ok=True)
    meta = lane_meta if lane_meta is not None else _lane_meta()
    meta_path = lane_dir / "latest.json"
    meta_path.write_bytes(artifact_json_bytes(meta))
    evidence_sha = hashlib.sha256(meta_path.read_bytes()).hexdigest()

    summary: dict[str, Any] = {
        "schema_version": "xinao.grok_worker_pool.v2",
        "execution_contract_version": "xinao.grok.shared_execution_contract.v1",
        "pool_id": "gwp_20260720T055202_836af573",
        "n": 1,
        "model": "grok-4.5",
        "selected_provider_id": "grok_acpx_headless",
        "selected_profile_ref": "grok.com.cached_profile",
        "selected_transport_id": "direct-grok-worker-pool",
        "all_ok": True,
        "ok_count": 1,
        "fail_count": 0,
        "usage_accounting_complete": True,
        "completion_claim_allowed": False,
        "results": [
            {
                "lane": lane_index,
                "evidence_dir": str(lane_dir),
                "meta_path": str(meta_path),
                "run_id": meta["run_id"],
                "status": "accepted",
                "outcome": "accepted",
                "effective_output_accepted": True,
                "requested_model": "grok-4.5",
                "session_model": "grok-4.5",
                "backend_model_identity_ok": True,
                "session_model_identity_ok": True,
                "session_turn_model_identity_ok": True,
                "session_evidence_ok": True,
                "model_identity_ok": True,
                "stop_reason": "EndTurn",
                "usage": dict(meta["usage"]),
                "usage_is_incomplete": False,
                "usage_accounting_complete": True,
                "provider_id": "grok_acpx_headless",
                "profile_ref": "grok.com.cached_profile",
                "transport_id": "direct-grok-worker-pool",
                "model": "grok-4.5",
            }
        ],
    }
    summary.update(summary_overrides)
    summary_path = tmp_path / "pool_summary.json"
    summary_path.write_bytes(artifact_json_bytes(summary))
    return summary, summary_path, meta_path


def test_accepted_real_shape_emits_common_receipt_and_prospective_reuse(tmp_path: Path) -> None:
    contract = _contract()
    contract_path = tmp_path / "logical_contract.json"
    contract_path.write_bytes(artifact_json_bytes(contract))
    summary, summary_path, meta_path = _pool_summary(tmp_path)
    out = tmp_path / "common_out"

    result = adapter.adapt_from_paths(
        logical_contract_path=contract_path,
        subject_manifest_sha256=SUBJECT,
        phase="EXPLORE",
        write_domains=["evidence/wave81_workerpool_common_adapter"],
        depends_on=[],
        pool_summary_path=summary_path,
        lane_index=0,
        output_root=out,
        write_artifacts=True,
    )

    receipt = result["attempt_receipt"]
    verdict = validate_attempt_receipt(
        contract,
        receipt,
        expected_consumer_id=GROK_DIRECT_WORKER_POOL_CONSUMER_ID,
    )
    assert verdict.accepted is True
    assert receipt["consumer_id"] == "direct_grok_worker_pool"
    assert receipt["observed"]["transport_id"] == "direct-grok-worker-pool"
    assert receipt["usage"]["accepted_tokens"] == 653949
    assert receipt["provider_evidence_sha256"] == hashlib.sha256(meta_path.read_bytes()).hexdigest()

    disposition = result["prospective_disposition"]
    assert disposition["disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert disposition["authority"] is False
    assert disposition["completion_claim_allowed"] is False
    assert disposition["skip_execution"] is True

    adapter_receipt = result["adapter_receipt"]
    assert adapter_receipt["authority"] is False
    assert adapter_receipt["completion_claim_allowed"] is False
    assert (out / "common_logical_contract.json").is_file()
    assert (out / "common_attempt_receipt.json").is_file()
    assert (out / "common_prospective_identical_disposition.json").is_file()
    assert (out / "common_adapter_receipt.json").is_file()
    # Pool all_ok alone is recorded in summary but never treated as authority.
    assert summary["all_ok"] is True
    assert adapter_receipt["authority"] is False


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("session_model", "grok-composer-2.5-fast", "session model"),
        ("model_identity_ok", False, "identity"),
        ("usage_accounting_complete", False, "usage accounting"),
        ("effective_output_accepted", False, "provider-native"),
        ("observed_rules_sha256", "1" * 64, "rules"),
        ("result_text_sha256", "0" * 64, "rules|provider-native|session|identity|usage|substantive|"),
        ("usage", {"total_tokens": 0}, "token"),
    ],
)
def test_provider_session_rules_usage_output_drift_fails_closed(
    tmp_path: Path, field: str, value: object, match: str
) -> None:
    contract = _contract()
    meta = _lane_meta(**{field: value})
    if field == "observed_rules_sha256":
        meta["short_execution_contract_sha256"] = value  # keep pair consistent
    if field == "result_text_sha256":
        # content hash drift with empty substantive failure path via chars=0
        meta["result_text_chars"] = 0
        match = "substantive|NON_SUBSTANTIVE|positive|token|chars"
    summary, _, _ = _pool_summary(tmp_path, lane_meta=meta)

    with pytest.raises((adapter.DirectWorkerPoolCommonAdapterError, ValueError), match=match):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=["evidence/x"],
            depends_on=[],
            pool_summary=summary,
            lane_index=0,
            lane_meta=meta,
            provider_evidence_ref=str(tmp_path / "lane_00" / "latest.json"),
            provider_evidence_sha256="9" * 64,
            output_root=tmp_path / "out",
            write_artifacts=False,
        )


def test_wrong_lane_index_fails(tmp_path: Path) -> None:
    contract = _contract()
    summary, _, _ = _pool_summary(tmp_path, lane_index=0)
    with pytest.raises(adapter.DirectWorkerPoolCommonAdapterError, match="no lane index"):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
            pool_summary=summary,
            lane_index=7,
            lane_meta=_lane_meta(),
            provider_evidence_ref="virtual",
            provider_evidence_sha256="9" * 64,
            write_artifacts=False,
            output_root=tmp_path / "out",
        )


def test_subject_mismatch_does_not_infer_reuse(tmp_path: Path) -> None:
    contract = _contract()
    summary, _, _ = _pool_summary(tmp_path)
    accepted = adapter.adapt_accepted_lane_to_common(
        logical_contract=contract,
        subject_manifest_sha256=SUBJECT,
        phase="EXPLORE",
        write_domains=["evidence/x"],
        depends_on=[],
        pool_summary=summary,
        lane_index=0,
        lane_meta=_lane_meta(),
        provider_evidence_ref="virtual-meta",
        provider_evidence_sha256="8" * 64,
        write_artifacts=False,
        output_root=tmp_path / "out",
    )
    other_subject = "1" * 64
    # Prior accepted under SUBJECT must not REUSE for a different subject pin.
    classification = classify_identical_work_disposition(
        contract,
        subject_manifest_sha256=other_subject,
        prior_accepted=[
            {
                "logical_contract": contract,
                "subject_manifest_sha256": SUBJECT,
                "attempt_receipt": accepted["attempt_receipt"],
            }
        ],
    )
    assert classification is None
    # Self-loop REUSE for other_subject is a different pin, not a reuse of SUBJECT.
    other_disp = adapter.derive_prospective_identical_reuse(
        contract=contract,
        subject_manifest_sha256=other_subject,
        attempt_receipt=accepted["attempt_receipt"],
        phase="EXPLORE",
        write_domains=["evidence/x"],
        depends_on=[],
    )
    assert other_disp["disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert (
        other_disp["identical_work_pin_sha256"]
        != accepted["prospective_disposition"]["identical_work_pin_sha256"]
    )


def test_explicit_prior_precheck_skips_without_provider_execution(tmp_path: Path) -> None:
    contract = _contract()
    summary, _, _ = _pool_summary(tmp_path)
    accepted = adapter.adapt_accepted_lane_to_common(
        logical_contract=contract,
        subject_manifest_sha256=SUBJECT,
        frozen_context_sha256=FROZEN_CONTEXT,
        phase="EXPLORE",
        write_domains=["evidence/x"],
        depends_on=[],
        pool_summary=summary,
        lane_index=0,
        lane_meta=_lane_meta(),
        provider_evidence_ref="virtual-meta",
        provider_evidence_sha256="8" * 64,
        write_artifacts=False,
        output_root=tmp_path / "out",
    )
    disposition = adapter.classify_prior_attempt_for_dispatch(
        contract=contract,
        subject_manifest_sha256=SUBJECT,
        frozen_context_sha256=FROZEN_CONTEXT,
        prior_attempt_receipt=accepted["attempt_receipt"],
        phase="EXPLORE",
        write_domains=["evidence/x"],
        depends_on=[],
    )
    assert disposition["disposition"] == "ACCEPTED_IDENTICAL_REUSE"
    assert disposition["skip_execution"] is True
    assert disposition["authority"] is False


def test_explicit_prior_precheck_rejects_context_preimage_drift(tmp_path: Path) -> None:
    contract = _contract()
    summary, _, _ = _pool_summary(tmp_path)
    accepted = adapter.adapt_accepted_lane_to_common(
        logical_contract=contract,
        subject_manifest_sha256=SUBJECT,
        phase="EXPLORE",
        write_domains=[],
        depends_on=[],
        pool_summary=summary,
        lane_index=0,
        lane_meta=_lane_meta(),
        provider_evidence_ref="virtual-meta",
        provider_evidence_sha256="8" * 64,
        write_artifacts=False,
        output_root=tmp_path / "out",
    )
    with pytest.raises(
        adapter.DirectWorkerPoolCommonAdapterError,
        match="do not match logical contract",
    ):
        adapter.classify_prior_attempt_for_dispatch(
            contract=contract,
            subject_manifest_sha256=SUBJECT,
            frozen_context_sha256="1" * 64,
            prior_attempt_receipt=accepted["attempt_receipt"],
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
        )


def test_no_common_completion_authority(tmp_path: Path) -> None:
    contract = _contract()
    summary, _, _ = _pool_summary(tmp_path)
    result = adapter.adapt_accepted_lane_to_common(
        logical_contract=contract,
        subject_manifest_sha256=SUBJECT,
        phase="VERIFY",
        write_domains=["evidence/x"],
        depends_on=["unit-a"],
        pool_summary=summary,
        lane_index=0,
        lane_meta=_lane_meta(),
        provider_evidence_ref="virtual-meta",
        provider_evidence_sha256="7" * 64,
        write_artifacts=True,
        output_root=tmp_path / "out",
    )
    ar = result["adapter_receipt"]
    disp = result["prospective_disposition"]
    assert ar["authority"] is False
    assert ar["completion_claim_allowed"] is False
    assert disp["authority"] is False
    assert disp["completion_claim_allowed"] is False
    assert "all_ok" not in ar
    assert ar["false_green_deny"]
    # Explicit: summary all_ok true still does not flip authority.
    assert summary.get("all_ok") is True
    assert ar["authority"] is False


def test_rules_short_contract_hash_must_match_logical_contract(tmp_path: Path) -> None:
    contract = _contract()
    meta = _lane_meta(
        observed_rules_sha256="2" * 64,
        short_execution_contract_sha256="2" * 64,
    )
    summary, _, _ = _pool_summary(tmp_path, lane_meta=meta)
    with pytest.raises(adapter.DirectWorkerPoolCommonAdapterError, match="rules"):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
            pool_summary=summary,
            lane_index=0,
            lane_meta=meta,
            provider_evidence_ref="virtual",
            provider_evidence_sha256="6" * 64,
            write_artifacts=False,
            output_root=tmp_path / "out",
        )


def test_missing_observed_capability_binding_fails_closed(tmp_path: Path) -> None:
    contract = _contract()
    meta = _lane_meta(observed_capability_binding_sha256="")
    summary, _, _ = _pool_summary(tmp_path, lane_meta=meta)
    with pytest.raises(
        adapter.DirectWorkerPoolCommonAdapterError,
        match="observed_capability_binding",
    ):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
            pool_summary=summary,
            lane_index=0,
            lane_meta=meta,
            provider_evidence_ref="virtual",
            provider_evidence_sha256="6" * 64,
            write_artifacts=False,
            output_root=tmp_path / "out",
        )


def test_tampered_common_preflight_fails_closed(tmp_path: Path) -> None:
    contract = _contract()
    preflight = _common_preflight()
    preflight["subject_manifest_sha256"] = "1" * 64
    meta = _lane_meta(common_contract_preflight=preflight)
    summary, _, _ = _pool_summary(tmp_path, lane_meta=meta)
    with pytest.raises(
        adapter.DirectWorkerPoolCommonAdapterError,
        match="common_contract_preflight mismatch",
    ):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
            pool_summary=summary,
            lane_index=0,
            lane_meta=meta,
            provider_evidence_ref="virtual",
            provider_evidence_sha256="6" * 64,
            write_artifacts=False,
            output_root=tmp_path / "out",
        )


def test_all_ok_alone_cannot_bypass_native_rejection(tmp_path: Path) -> None:
    contract = _contract()
    meta = _lane_meta(effective_output_accepted=False, status="rejected", outcome="rejected")
    summary, _, _ = _pool_summary(tmp_path, lane_meta=meta, all_ok=True)
    assert summary["all_ok"] is True
    with pytest.raises((adapter.DirectWorkerPoolCommonAdapterError, ValueError)):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
            pool_summary=summary,
            lane_index=0,
            lane_meta=meta,
            provider_evidence_ref="virtual",
            provider_evidence_sha256="5" * 64,
            write_artifacts=False,
            output_root=tmp_path / "out",
        )


def test_wrong_summary_identity_fails(tmp_path: Path) -> None:
    contract = _contract()
    summary, _, _ = _pool_summary(
        tmp_path,
        selected_provider_id="not-the-selected-provider",
    )
    with pytest.raises(adapter.DirectWorkerPoolCommonAdapterError, match="identity mismatch"):
        adapter.adapt_accepted_lane_to_common(
            logical_contract=contract,
            subject_manifest_sha256=SUBJECT,
            phase="EXPLORE",
            write_domains=[],
            depends_on=[],
            pool_summary=summary,
            lane_index=0,
            lane_meta=_lane_meta(),
            provider_evidence_ref="virtual",
            provider_evidence_sha256="9" * 64,
            write_artifacts=False,
            output_root=tmp_path / "out",
        )
