from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from services.agent_runtime import foundation_continuous_workflow_v3 as subject


def _write_json(path: Path, value: dict[str, object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    raw = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _synthetic_closure_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    pack_root = tmp_path / "closure"
    blueprint = tmp_path / "blueprint.json"
    blueprint_ref = _write_json(blueprint, {"blueprint": "current"})
    authority = {"content_sha256": "a" * 64}
    authority_ref = _write_json(
        pack_root / "authority_snapshot" / "authority_manifest.json",
        authority,
    )
    receipts: dict[str, dict[str, object]] = {}
    for block_id in subject.FOUNDATION_BLOCK_IDS:
        receipt = {
            "schema_version": "xinao.fresh_assertion_bundle_receipt.v3",
            "protocol_version": "test",
            "block_id": block_id,
            "compiler_code_manifest_ref": authority_ref,
            "double_fresh_bytes_equal": True,
        }
        receipts[block_id] = _write_json(
            pack_root / "fresh_assertion_bundle_receipts" / f"{block_id}.json",
            receipt,
        )
    block_inputs = {
        block_id: {
            "artifact_hashes": {f"artifact:{block_id}": "1" * 64},
            "assertion_results": {f"assertion:{block_id}": {"result": "PASS"}},
        }
        for block_id in subject.FOUNDATION_BLOCK_IDS
    }
    report_input = {
        "blueprint_ref": blueprint_ref,
        "compiler_code_manifest_ref": authority_ref,
        "authority_snapshot_manifest_ref": authority_ref,
        "input_hashes": {"input-a": "2" * 64, "input-b": "3" * 64},
        "block_reports": block_inputs,
    }
    report_input_ref = _write_json(
        pack_root / "foundation_closure_report_input.json",
        report_input,
    )
    report_blocks = {
        block_id: {"status": "VERIFIED"} for block_id in subject.FOUNDATION_BLOCK_IDS
    }
    report = {
        "schema_version": "xinao.foundation_closure_report.v1",
        "blueprint_ref": blueprint_ref,
        "block_reports": report_blocks,
        "status": "VERIFIED",
        "bindings_complete": True,
        "canonical_bundle_replay_verified": True,
        "all_required_assertions_pass": True,
        "foundation_closed": True,
        "formal_research_allowed": True,
        "formal_research_gate": "OPEN",
        "legacy_a_g_gate_used": False,
        "manual_override_used": False,
        "artifact_hash": "4" * 64,
    }
    report_ref = _write_json(pack_root / "foundation_closure_report.json", report)
    verification = {
        "schema_version": "xinao.foundation_closure_verification.v1",
        "ok": True,
        "checks": {"all": True},
        "recorded_artifact_hash": "4" * 64,
        "recomputed_artifact_hash": "4" * 64,
        "foundation_closed": True,
    }
    verification_ref = _write_json(
        pack_root / "foundation_closure_verification.json",
        verification,
    )
    manifest_body = {
        "schema_version": "xinao.foundation_closure_pack.v4",
        "blueprint_ref": blueprint_ref,
        "compiler_code_manifest_ref": authority_ref,
        "authority_snapshot_manifest_ref": authority_ref,
        "report_input_ref": report_input_ref,
        "report_ref": report_ref,
        "verification_ref": verification_ref,
        "fresh_assertion_bundle_receipt_refs": receipts,
        "artifact_count": 4,
        "assertion_count": 4,
        "retained_input_material_count": 2,
        "retained_artifact_material_count": 4,
        "source_materials_self_contained": True,
        "foundation_closed": True,
        "fresh_process_verified": True,
        "fresh_assertion_bundle_verified": True,
    }
    manifest = {
        **manifest_body,
        "pack_sha256": subject.canonical_sha256(manifest_body),
    }
    manifest_ref = _write_json(pack_root / "foundation_closure_pack.json", manifest)
    monkeypatch.setattr(subject, "canonical_blueprint_path", lambda: blueprint.resolve())
    monkeypatch.setattr(
        subject,
        "validate_authority_snapshot",
        lambda path, *, require_live_match: authority,
    )
    monkeypatch.setattr(
        subject,
        "derive_foundation_closure_report",
        lambda value, *, blueprint_path: report,
    )
    monkeypatch.setattr(
        subject,
        "verify_foundation_closure_report",
        lambda value, *, blueprint_path: verification,
    )
    return pack_root, manifest_ref, manifest


def test_phase_gate_requires_proof_then_milestone_then_autonomous() -> None:
    construction = subject.evaluate_foundation_phase_gate_v3(
        execution_phase=subject.FOUNDATION_CONSTRUCTION,
        closure_pack_candidate=False,
        verified_proof=None,
        foundation_closed_projection=False,
        recorded_closure=None,
        wait_seconds=300,
    )
    assert construction["action"] == "ALLOW_CONSTRUCTION_CANARY"
    assert construction["formal_research_allowed"] is False

    verify = subject.evaluate_foundation_phase_gate_v3(
        execution_phase=subject.FOUNDATION_CONSTRUCTION,
        closure_pack_candidate=True,
        verified_proof=None,
        foundation_closed_projection=False,
        recorded_closure=None,
        wait_seconds=300,
    )
    assert verify["action"] == "VERIFY_CLOSURE_PROOF"

    proof = {
        "content_sha256": "1" * 64,
        "closure_pack_file_sha256": "2" * 64,
        "closure_pack_content_sha256": "3" * 64,
    }
    milestone = subject.evaluate_foundation_phase_gate_v3(
        execution_phase=subject.FOUNDATION_CONSTRUCTION,
        closure_pack_candidate=True,
        verified_proof=proof,
        foundation_closed_projection=False,
        recorded_closure=None,
        wait_seconds=300,
    )
    assert milestone["action"] == "MILESTONE"
    assert milestone["formal_research_allowed"] is False

    autonomous = subject.evaluate_foundation_phase_gate_v3(
        execution_phase=subject.AUTONOMOUS_RESEARCH,
        closure_pack_candidate=True,
        verified_proof=proof,
        foundation_closed_projection=True,
        recorded_closure={
            "foundation_closure_proof_content_sha256": proof["content_sha256"]
        },
        wait_seconds=300,
    )
    assert autonomous["action"] == "ALLOW_AUTONOMOUS_RESEARCH"
    assert autonomous["formal_research_allowed"] is True


@pytest.mark.parametrize(
    ("phase", "closed", "recorded", "reason"),
    [
        (
            subject.AUTONOMOUS_RESEARCH,
            False,
            None,
            "FOUNDATION_CLOSURE_PROOF_REQUIRED",
        ),
        (
            subject.AUTONOMOUS_RESEARCH,
            True,
            None,
            "FOUNDATION_CLOSED_PROJECTION_WITHOUT_VERIFIED_PROOF",
        ),
    ],
)
def test_bare_foundation_closed_never_authorizes_formal_research(
    phase: str,
    closed: bool,
    recorded: dict[str, object] | None,
    reason: str,
) -> None:
    decision = subject.evaluate_foundation_phase_gate_v3(
        execution_phase=phase,
        closure_pack_candidate=False,
        verified_proof=None,
        foundation_closed_projection=closed,
        recorded_closure=recorded,
        wait_seconds=300,
    )
    assert decision["action"] == "WAIT"
    assert decision["reason"] == reason
    assert decision["formal_research_allowed"] is False


def test_closure_pack_activity_builds_and_revalidates_content_bound_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack_root, manifest_ref, manifest = _synthetic_closure_pack(tmp_path, monkeypatch)
    result = subject.verify_foundation_closure_pack_v3(
        {
            "runtime_root": str(tmp_path),
            "operation_id": "gate-test",
            "foundation_closure_pack_ref": manifest_ref["path"],
            "foundation_closure_pack_sha256": manifest_ref["sha256"],
        }
    )
    proof = result["proof"]
    assert result["ok"] is True
    assert proof["status"] == "VERIFIED"
    assert proof["closure_pack_content_sha256"] == manifest["pack_sha256"]
    assert proof["foundation_block_ids"] == list(subject.FOUNDATION_BLOCK_IDS)
    frontier = {
        "foundation_closure_pack_ref": manifest_ref["path"],
        "foundation_closure_pack_sha256": manifest_ref["sha256"],
    }
    validated = subject.validate_foundation_closure_gate_proof_v3(
        runtime_root=tmp_path,
        proof_binding={
            "proof_ref": result["proof_ref"],
            "proof_sha256": result["proof_sha256"],
            "content_sha256": proof["content_sha256"],
        },
        frontier=frontier,
    )
    assert validated == proof

    receipt = pack_root / "fresh_assertion_bundle_receipts" / "F1_settlement_world.json"
    receipt.write_text(receipt.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory changed"):
        subject.validate_foundation_closure_gate_proof_v3(
            runtime_root=tmp_path,
            proof_binding={
                "proof_ref": result["proof_ref"],
                "proof_sha256": result["proof_sha256"],
                "content_sha256": proof["content_sha256"],
            },
            frontier=frontier,
        )


def test_gate_rejects_partial_or_scattered_proof_identity(
    tmp_path: Path,
) -> None:
    frontier_path = tmp_path / "frontier.json"
    frontier = {
        "execution_phase": subject.FOUNDATION_CONSTRUCTION,
        "foundation_closure_pack_ref": "missing.json",
    }
    frontier_path.write_text(json.dumps(frontier), encoding="utf-8")
    digest = hashlib.sha256(frontier_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="identity is partial"):
        subject.inspect_foundation_phase_gate_v3(
            {
                "runtime_root": str(tmp_path),
                "frontier_ref": str(frontier_path),
                "frontier_sha256": digest,
            }
        )

    frontier = {
        "execution_phase": subject.FOUNDATION_CONSTRUCTION,
        "foundation_closure_report_ref": "legacy-report.json",
    }
    frontier_path.write_text(json.dumps(frontier), encoding="utf-8")
    digest = hashlib.sha256(frontier_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="scattered closure proof"):
        subject.inspect_foundation_phase_gate_v3(
            {
                "runtime_root": str(tmp_path),
                "frontier_ref": str(frontier_path),
                "frontier_sha256": digest,
            }
        )
