from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from services.agent_runtime import foundation_continuous_workflow_v2 as workflow_v2
from xinao.foundation import closure as closure_module
from xinao.foundation.closure import FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION


def _write_bound(root: Path, name: str, value: dict[str, Any]) -> tuple[str, str]:
    path = root / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def _readiness_materials(
    root: Path,
    *,
    report_overrides: dict[str, Any] | None = None,
    verification_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    report = {
        "schema_version": FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        "status": "VERIFIED",
        "foundation_execution_ready": True,
        "foundation_closed": False,
        "formal_research_allowed": False,
        "formal_research_gate": "CLOSED",
        "legacy_a_g_gate_used": False,
        "manual_override_used": False,
        "independent_verifier_id": "test-independent-verifier.v1",
    }
    report.update(report_overrides or {})
    report["artifact_hash"] = workflow_v2._canonical_hash(report)
    verification = {
        "schema_version": "xinao.foundation_closure_verification.v1",
        "ok": True,
        "checks": {"test_replay": True},
        "recorded_artifact_hash": report["artifact_hash"],
        "recomputed_artifact_hash": report["artifact_hash"],
        "foundation_execution_ready": True,
        "foundation_closed": False,
    }
    verification.update(verification_overrides or {})
    report_ref, report_sha256 = _write_bound(root, "report.json", report)
    verification_ref, verification_sha256 = _write_bound(root, "verification.json", verification)
    blueprint_ref, blueprint_sha256 = _write_bound(
        root,
        "blueprint.json",
        {"schema_version": "test-blueprint.v1"},
    )
    frontier = {
        "foundation_closure_report_ref": report_ref,
        "foundation_closure_report_sha256": report_sha256,
        "foundation_closure_verification_ref": verification_ref,
        "foundation_closure_verification_sha256": verification_sha256,
        "blueprint_snapshot_ref": blueprint_ref,
        "blueprint_snapshot_sha256": blueprint_sha256,
        "wait_seconds": 17,
    }
    return frontier, report, verification


def test_current_ready_report_records_a_milestone_while_formal_research_stays_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontier, report, verification = _readiness_materials(tmp_path)
    monkeypatch.setattr(
        closure_module,
        "verify_foundation_closure_report",
        lambda _report, *, blueprint_path: deepcopy(verification),
    )

    milestone = workflow_v2._closure_milestone(tmp_path, frontier)

    assert milestone is not None
    assert milestone["action"] == "MILESTONE"
    assert milestone["reason"] == ("independently_verified_foundation_execution_ready_report")
    assert milestone["foundation_closure_artifact_hash"] == report["artifact_hash"]
    assert milestone["foundation_closure_verifier_id"] == ("test-independent-verifier.v1")
    assert all(milestone["checks"].values())


@pytest.mark.parametrize(
    ("surface", "field", "value"),
    (
        ("report", "status", "NOT_PERFORMED"),
        ("report", "foundation_execution_ready", False),
        ("report", "foundation_closed", True),
        ("report", "formal_research_allowed", True),
        ("report", "formal_research_gate", "OPEN"),
        ("report", "legacy_a_g_gate_used", True),
        ("report", "manual_override_used", True),
        ("report", "independent_verifier_id", ""),
        ("verification", "schema_version", "wrong-verification.v1"),
        ("verification", "ok", False),
        ("verification", "foundation_execution_ready", False),
        ("verification", "foundation_closed", True),
        ("verification", "recorded_artifact_hash", "f" * 64),
    ),
)
def test_incompatible_or_formal_open_readiness_proofs_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    field: str,
    value: Any,
) -> None:
    frontier, _, verification = _readiness_materials(
        tmp_path,
        report_overrides={field: value} if surface == "report" else None,
        verification_overrides={field: value} if surface == "verification" else None,
    )
    monkeypatch.setattr(
        closure_module,
        "verify_foundation_closure_report",
        lambda _report, *, blueprint_path: deepcopy(verification),
    )

    with pytest.raises(ValueError, match="foundation closure proof rejected"):
        workflow_v2._closure_milestone(tmp_path, frontier)


def test_verification_file_must_equal_the_current_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontier, _, verification = _readiness_materials(tmp_path)
    replay = {**verification, "checks": {"test_replay": False}}
    monkeypatch.setattr(
        closure_module,
        "verify_foundation_closure_report",
        lambda _report, *, blueprint_path: deepcopy(replay),
    )

    with pytest.raises(ValueError, match="verification_replays"):
        workflow_v2._closure_milestone(tmp_path, frontier)


def test_every_readiness_file_is_sha256_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frontier, _, verification = _readiness_materials(tmp_path)
    frontier["foundation_closure_verification_sha256"] = "0" * 64
    monkeypatch.setattr(
        closure_module,
        "verify_foundation_closure_report",
        lambda _report, *, blueprint_path: deepcopy(verification),
    )

    with pytest.raises(ValueError, match="bound object hash mismatch"):
        workflow_v2._closure_milestone(tmp_path, frontier)


def test_bare_new_and_legacy_flags_are_never_treated_as_proof() -> None:
    assert (
        workflow_v2._reconcile_wait_reason(
            {"foundation_execution_ready": True},
            milestone=None,
            ready_keys=[],
            width=1,
        )
        == "BARE_FOUNDATION_EXECUTION_READY_REJECTED"
    )
    assert (
        workflow_v2._reconcile_wait_reason(
            {"foundation_closed": True},
            milestone=None,
            ready_keys=[],
            width=1,
        )
        == "DEPRECATED_BARE_FOUNDATION_CLOSED_REJECTED"
    )


def test_legacy_resume_state_requires_a_current_readiness_report() -> None:
    initial = {
        "operation_id": "readiness-migration-test",
        "frontier_ref": "frontier.json",
        "frontier_sha256": "a" * 64,
        "roll_forward_manifest_ref": "roll-forward.json",
        "roll_forward_manifest_sha256": "b" * 64,
        "owner_generation": 1,
    }
    current = workflow_v2._initial_state_v2(initial)
    assert current["foundation_execution_ready"] is False
    assert "foundation_closed" not in current

    proven = deepcopy(current)
    proven["foundation_execution_ready"] = True
    resumed_proven = workflow_v2._initial_state_v2({"resume_state": proven})
    assert resumed_proven["foundation_execution_ready"] is True

    legacy = deepcopy(current)
    legacy.pop("foundation_execution_ready")
    legacy["foundation_closed"] = True
    legacy["foundation_closure"] = {"legacy": True}
    resumed_legacy = workflow_v2._initial_state_v2({"resume_state": legacy})
    assert resumed_legacy["foundation_execution_ready"] is False
    assert "foundation_closed" not in resumed_legacy
    assert resumed_legacy["foundation_closure"] == {}
    assert resumed_legacy["readiness_migration"] == {
        "reason": "DEPRECATED_FOUNDATION_CLOSED_REQUIRES_CURRENT_REPROOF",
        "requires_current_report": True,
    }
