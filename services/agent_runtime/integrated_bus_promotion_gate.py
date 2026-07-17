"""Replay → PromotionGate → MemoryCandidate (evidence only on fail)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.execution_contract import (
    ATTEMPT_RECEIPT_VERSION,
    LOGICAL_CONTRACT_VERSION,
)
from services.agent_runtime.thin_glue_l5_verify import run_l5_pytest_verify
from services.agent_runtime.thin_glue_stack import write_json

SCHEMA_VERSION = "xinao.integrated_bus.promotion_gate.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_PROMOTION_GATE"
PROMOTION_TEST_PATHS = [
    "tests/test_integrated_bus_hot_path.py::test_integrated_bus_promotion_slice_contract",
]
FANIN_SCHEMA_VERSION = "xinao.integrated_bus.fanin_slice.v1"
AAQ_SCHEMA_VERSION = "xinao.integrated_bus.aaq_claim.v1"
PROMOTION_LEDGER_SCHEMA_VERSION = "xinao.integrated_bus.promotion_ledger.v1"
PROVIDER_VALIDATORS = {
    "grok_acpx_headless": "xinao.grok.shared_execution_contract.v1",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_replay_case(state: dict[str, Any], *, workflow_id: str = "") -> dict[str, Any]:
    """Replay = structured execution trace from graph state (not prompt recall)."""
    return {
        "schema_version": "xinao.integrated_bus.replay_case.v1",
        "replay_source": "temporal_langgraph_plugin_state",
        "workflow_id": workflow_id or state.get("workflow_id") or "",
        "intake_adapter": state.get("adapter"),
        "content_md_chars": len(str(state.get("content_md") or "")),
        "execution_backend": state.get("execution_backend"),
        "gateway_trace_ok": state.get("gateway_trace_ok"),
        "langfuse_callback_wired": state.get("langfuse_callback_wired"),
        "captured_at": _now_iso(),
    }


def _resolve_runtime_ref(runtime_root: Path, raw: object, *, expected_root: Path) -> Path | None:
    ref = str(raw or "").strip().replace("\\", "/")
    if not ref:
        return None
    if ref.startswith("/evidence/"):
        path = runtime_root / ref[len("/evidence/") :]
    else:
        path = Path(ref)
    try:
        resolved = path.resolve()
        resolved.relative_to(expected_root.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() and resolved.stat().st_size <= 2_000_000 else None


def _read_bound_json(
    runtime_root: Path,
    raw: object,
    *,
    expected_root: Path,
    schema_version: str,
) -> dict[str, Any]:
    path = _resolve_runtime_ref(runtime_root, raw, expected_root=expected_root)
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        return {}
    return value


def evaluate_current_promotion(
    state: dict[str, Any],
    *,
    workflow_id: str,
    fanin_ledger: dict[str, Any],
    aaq_claim: dict[str, Any],
    fanin_sha256: str = "",
    aaq_sha256: str = "",
) -> dict[str, bool]:
    """Evaluate only current accepted execution facts; no path/string-only green."""

    provider = str(state.get("worker_lane_provider") or "")
    validator_id = PROVIDER_VALIDATORS.get(provider, "")
    provider_state_ok = bool(
        validator_id
        and state.get("grok_fanin_ok") is True
        and state.get("provider_fanin_ok") is True
        and state.get("worker_lane_cross_seam_receipt_ok") is True
        and state.get("worker_lane_cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
        and state.get("worker_lane_cross_seam_receipt_version") == ATTEMPT_RECEIPT_VERSION
        and len(str(state.get("worker_lane_cross_seam_receipt_set_sha256") or "")) == 64
    )
    provider_ledger_ok = bool(
        validator_id
        and fanin_ledger.get("grok_fanin_ok") is True
        and fanin_ledger.get("provider_fanin_ok") is True
        and fanin_ledger.get("provider_validator_id") == validator_id
        and fanin_ledger.get("provider_evidence_bound") is True
        and bool(str(fanin_ledger.get("provider_evidence_sha256") or ""))
        and fanin_ledger.get("cross_seam_receipt_ok") is True
        and fanin_ledger.get("cross_seam_contract_version") == LOGICAL_CONTRACT_VERSION
        and fanin_ledger.get("cross_seam_receipt_version") == ATTEMPT_RECEIPT_VERSION
        and fanin_ledger.get("cross_seam_receipt_set_sha256")
        == state.get("worker_lane_cross_seam_receipt_set_sha256")
    )
    fanin_ref = str(state.get("fanin_evidence_ref") or "")
    return {
        "current_provider_validator_known": bool(validator_id),
        "current_validate_ok": state.get("validate_ok") is True,
        "current_worker_lane_ok": state.get("worker_lane_ok") is True,
        "current_provider_fanin_ok": provider_state_ok,
        "current_cross_seam_receipt_ok": bool(provider_state_ok and provider_ledger_ok),
        "current_substantive_fanin_ok": state.get("fanin_ok") is True,
        "fanin_ledger_bound": bool(
            fanin_ledger
            and fanin_ledger.get("workflow_id") == workflow_id
            and fanin_ledger.get("worker_lane_provider") == provider
            and fanin_ledger.get("validate_ok") is True
            and fanin_ledger.get("worker_lane_ok") is True
            and fanin_ledger.get("substantive_lane_ok") is True
            and fanin_ledger.get("fanin_ok") is True
            and provider_ledger_ok
            and bool(fanin_sha256)
            and state.get("fanin_evidence_sha256") == fanin_sha256
        ),
        "aaq_claim_bound": bool(
            aaq_claim
            and aaq_claim.get("workflow_id") == workflow_id
            and aaq_claim.get("fanin_evidence_ref") == fanin_ref
            and aaq_claim.get("fanin_evidence_sha256") == fanin_sha256
            and aaq_claim.get("fanin_bound") is True
            and aaq_claim.get("fanin_ok") is True
            and aaq_claim.get("completion_claim_allowed") is False
            and bool(aaq_sha256)
            and state.get("aaq_claim_sha256") == aaq_sha256
        ),
    }


def run_promotion_gate(
    state: dict[str, Any],
    *,
    runtime_root: Path,
    repo_root: Path,
    workflow_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    replay = build_replay_case(state, workflow_id=workflow_id)
    pytest_ev = run_l5_pytest_verify(
        repo=repo_root,
        runtime=runtime_root,
        run_id=run_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
        test_paths=PROMOTION_TEST_PATHS,
    )

    gateway_ok = state.get("gateway_trace_ok") is True or (
        str(state.get("litellm_completion_via") or "") == "litellm.completion"
        and state.get("litellm_completion_ok") is True
    )
    sandbox_ok = bool(str(state.get("execution_stdout") or "").strip())
    intake_ok = bool(str(state.get("content_md") or "").strip())
    pytest_ok = pytest_ev.get("passed") is True
    lineage_wf = str(workflow_id or state.get("workflow_id") or "")
    fanin_ref = str(state.get("fanin_evidence_ref") or "")
    aaq_ref = str(state.get("aaq_claim_ref") or "")
    fanin_ledger = _read_bound_json(
        runtime_root,
        fanin_ref,
        expected_root=runtime_root / "state" / "source_ledger" / "integrated_bus",
        schema_version=FANIN_SCHEMA_VERSION,
    )
    aaq_claim = _read_bound_json(
        runtime_root,
        aaq_ref,
        expected_root=runtime_root / "state" / "aaq" / "integrated_bus",
        schema_version=AAQ_SCHEMA_VERSION,
    )
    fanin_path = _resolve_runtime_ref(
        runtime_root,
        fanin_ref,
        expected_root=runtime_root / "state" / "source_ledger" / "integrated_bus",
    )
    aaq_path = _resolve_runtime_ref(
        runtime_root,
        aaq_ref,
        expected_root=runtime_root / "state" / "aaq" / "integrated_bus",
    )
    fanin_sha256 = hashlib.sha256(fanin_path.read_bytes()).hexdigest() if fanin_path else ""
    aaq_sha256 = hashlib.sha256(aaq_path.read_bytes()).hexdigest() if aaq_path else ""
    execution_checks = evaluate_current_promotion(
        state,
        workflow_id=lineage_wf,
        fanin_ledger=fanin_ledger,
        aaq_claim=aaq_claim,
        fanin_sha256=fanin_sha256,
        aaq_sha256=aaq_sha256,
    )

    checks = {
        "replay_case_built": bool(replay.get("replay_source")),
        "intake_from_trace": intake_ok,
        "sandbox_from_trace": sandbox_ok,
        "gateway_trace_ok": gateway_ok,
        "pytest_promotion_slice": pytest_ok,
        "workflow_id_lineage_fanin_aaq": bool(
            lineage_wf
            and lineage_wf == str(state.get("workflow_id") or workflow_id)
            and execution_checks["fanin_ledger_bound"]
            and execution_checks["aaq_claim_bound"]
        ),
        "no_llm_oral_memory": True,
        **execution_checks,
    }
    passed = all(checks.values())

    promotion_id = f"promotion-{uuid.uuid4().hex[:12]}"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "sentinel": SENTINEL,
        "promotion_id": promotion_id,
        "replay_case": replay,
        "pytest": pytest_ev,
        "source_ledger_ref": None,
        "memory_candidate_id": None,
        "memory_promoted": False,
        "validation": {"passed": passed, "checks": checks, "validated_at": _now_iso()},
        "rule_cn": "先 replay 真实轨迹 → PromotionGate(pytest+trace) → 通过才晋升 MemoryCandidate",
    }

    ledger_dir = runtime_root / "state" / "source_ledger" / "integrated_bus"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_entry = {
        "schema_version": PROMOTION_LEDGER_SCHEMA_VERSION,
        "entry_id": promotion_id,
        "promotion_id": promotion_id,
        "role": "integrated_bus_promotion_gate",
        "replay_case": replay,
        "promotion_passed": passed,
        "workflow_id": lineage_wf,
        "worker_lane_provider": str(state.get("worker_lane_provider") or ""),
        "fanin_evidence_ref": fanin_ref,
        "fanin_evidence_sha256": fanin_sha256,
        "aaq_claim_ref": aaq_ref,
        "aaq_claim_sha256": aaq_sha256,
        "lineage": {
            "workflow_id": lineage_wf,
            "fanin_evidence_ref": fanin_ref,
            "aaq_claim_ref": aaq_ref,
            "stage": "promotion_gate_after_aaq",
        },
        "timestamp": _now_iso(),
    }
    ledger_path = ledger_dir / f"{promotion_id}.json"
    write_json(ledger_path, ledger_entry)
    ledger_sha256 = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    payload["source_ledger_ref"] = str(ledger_path)
    payload["source_ledger_sha256"] = ledger_sha256

    if passed:
        mem_id = f"memcand-{uuid.uuid4().hex[:12]}"
        mem = {
            "schema_version": "xinao.integrated_bus.memory_candidate.v1",
            "memory_candidate_id": mem_id,
            "promoted_from": promotion_id,
            "workflow_id": lineage_wf,
            "replay_case_ref": str(ledger_path),
            "promotion_ledger_ref": str(ledger_path),
            "promotion_ledger_sha256": ledger_sha256,
            "fanin_evidence_ref": fanin_ref,
            "fanin_evidence_sha256": fanin_sha256,
            "aaq_claim_ref": aaq_ref,
            "aaq_claim_sha256": aaq_sha256,
            "summary_cn": (
                f"integrated_bus 波内轨迹：{replay.get('intake_adapter')} → "
                f"{replay.get('execution_backend')}；gateway={state.get('gateway_trace_ok')}"
            ),
            "promoted_at": _now_iso(),
            "not_llm_oral": True,
        }
        mem_dir = runtime_root / "state" / "memory_candidates"
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_path = mem_dir / f"{mem_id}.json"
        write_json(mem_path, mem)
        mem_sha256 = hashlib.sha256(mem_path.read_bytes()).hexdigest()
        payload["memory_candidate_id"] = mem_id
        payload["memory_candidate_ref"] = str(mem_path)
        payload["memory_candidate_sha256"] = mem_sha256
        payload["memory_promoted"] = True
    else:
        payload["named_blocker"] = "PROMOTION_GATE_BLOCKED"
        payload["evidence_only"] = True

    evidence = runtime_root / "readback" / f"integrated_bus_promotion_{promotion_id}.json"
    write_json(evidence, payload)
    payload["promotion_evidence_ref"] = str(evidence)
    return payload
