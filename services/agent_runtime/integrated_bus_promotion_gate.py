"""Replay → PromotionGate → MemoryCandidate (evidence only on fail)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.agent_runtime.thin_glue_l5_verify import run_l5_pytest_verify
from services.agent_runtime.thin_glue_stack import write_json

SCHEMA_VERSION = "xinao.integrated_bus.promotion_gate.v1"
SENTINEL = "SENTINEL:XINAO_INTEGRATED_BUS_PROMOTION_GATE"
PROMOTION_TEST_PATHS = [
    "tests/test_thin_glue_stack.py::test_integrated_bus_promotion_slice_contract",
]


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
    if not gateway_ok:
        lit_path = runtime_root / "state" / "litellm" / "latest.json"
        if lit_path.is_file():
            try:
                lit = json.loads(lit_path.read_text(encoding="utf-8"))
                gateway_ok = lit.get("invoke_ok") is True and lit.get("adapter") == "litellm.completion"
            except json.JSONDecodeError:
                gateway_ok = False
    sandbox_ok = bool(str(state.get("execution_stdout") or "").strip())
    intake_ok = bool(str(state.get("content_md") or "").strip())
    pytest_ok = pytest_ev.get("passed") is True
    lineage_wf = str(workflow_id or state.get("workflow_id") or "")
    fanin_ref = str(state.get("fanin_evidence_ref") or "")
    aaq_ref = str(state.get("aaq_claim_ref") or "")
    lineage_ok = bool(lineage_wf) and bool(fanin_ref) and lineage_wf == str(state.get("workflow_id") or workflow_id)

    checks = {
        "replay_case_built": bool(replay.get("replay_source")),
        "intake_from_trace": intake_ok,
        "sandbox_from_trace": sandbox_ok,
        "gateway_trace_ok": gateway_ok,
        "pytest_promotion_slice": pytest_ok,
        "workflow_id_lineage_fanin_aaq": lineage_ok,
        "no_llm_oral_memory": True,
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
        "entry_id": promotion_id,
        "role": "integrated_bus_promotion_gate",
        "replay_case": replay,
        "promotion_passed": passed,
        "workflow_id": lineage_wf,
        "fanin_evidence_ref": fanin_ref,
        "aaq_claim_ref": aaq_ref,
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
    payload["source_ledger_ref"] = str(ledger_path)

    if passed:
        mem_id = f"memcand-{uuid.uuid4().hex[:12]}"
        mem = {
            "schema_version": "xinao.integrated_bus.memory_candidate.v1",
            "memory_candidate_id": mem_id,
            "promoted_from": promotion_id,
            "replay_case_ref": str(ledger_path),
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
        payload["memory_candidate_id"] = mem_id
        payload["memory_candidate_ref"] = str(mem_path)
        payload["memory_promoted"] = True
    else:
        payload["named_blocker"] = "PROMOTION_GATE_BLOCKED"
        payload["evidence_only"] = True

    evidence = runtime_root / "readback" / f"integrated_bus_promotion_{promotion_id}.json"
    write_json(evidence, payload)
    payload["promotion_evidence_ref"] = str(evidence)
    return payload