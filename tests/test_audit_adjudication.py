from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from services.agent_runtime.audit_adjudication import (
    AuditAdjudicationError,
    build_audit_assessment,
    build_owner_adjudication,
    require_repair_authorization,
    validate_audit_assessment,
    validate_audit_candidate_output,
    validate_owner_adjudication,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _ref(label: str) -> dict[str, str]:
    return {"path": f"D:/evidence/{label}.json", "sha256": _sha(label)}


def _citation(label: str = "candidate") -> dict[str, object]:
    return {
        "path": f"src/{label}.py",
        "source_sha256": _sha(f"source:{label}"),
        "line_start": 10,
        "line_end": 14,
        "content_sha256": _sha(f"content:{label}"),
    }


def _candidate_output(*, verdict: str = "CANDIDATE_FINDINGS") -> dict[str, object]:
    findings: list[dict[str, object]] = []
    if verdict == "CANDIDATE_FINDINGS":
        findings = [
            {
                "finding_id": "finding-1",
                "family": "identity-binding",
                "title": "candidate bypass",
                "claim": "the frozen identity can be replaced before use",
                "severity_claim": "high",
                "evidence_citations": [_citation()],
                "reproduction_conditions": ["replace the frozen object before gate use"],
                "finding_kind": "CANDIDATE_FINDING",
            }
        ]
    return {
        "schema_version": "xinao.audit_candidate_findings.v1",
        "verdict": verdict,
        "summary": "candidate-only review of the frozen evidence package",
        "findings": findings,
        "limitations": ["required evidence was not supplied"]
        if verdict == "EVIDENCE_INCOMPLETE"
        else [],
        "authority": False,
        "completion_claim_allowed": False,
        "repair_authorized": False,
    }


def _assessment(
    *,
    evidence_status: str = "VERIFIED",
    access_mode: str = "DIRECT_TOOL",
) -> dict[str, object]:
    required = [_ref("scope"), _ref("tests"), _ref("runtime")]
    verified = evidence_status == "VERIFIED"
    candidate = _candidate_output(
        verdict="EVIDENCE_INCOMPLETE" if evidence_status == "INCOMPLETE" else "CANDIDATE_FINDINGS"
    )
    return build_audit_assessment(
        audit_id="audit-1",
        work_key="work-1",
        assessor_identity={
            "provider_id": "replaceable-auditor",
            "profile_ref": "profile:review",
            "model_id": "model:strong",
            "transport_id": "worker-pool",
        },
        assessment_plan={
            "methods": ["inspect", "test"],
            "objects": ["source", "contracts", "evidence"],
            "depth": "targeted threat-model depth",
            "coverage": "all verdict-changing objects in the frozen package",
            "blocking_severities": ["critical", "high"],
            "in_scope": ["frozen object", "frozen threat model"],
            "out_of_scope": ["new platform", "expanded threat model"],
        },
        scope_pins={
            "object_sha256": _sha("object"),
            "scope_sha256": _sha("scope-pin"),
            "threat_model_sha256": _sha("threat"),
            "completion_bar_sha256": _sha("bar"),
        },
        required_evidence_refs=required,
        evidence_access={
            "status": evidence_status,
            "mode": access_mode,
            "package_ref": _ref("package") if access_mode != "NONE" else None,
            "accessed_evidence_refs": required if verified else ([] if access_mode == "NONE" else required[:1]),
            "limitations": [] if verified else ["complete bounded evidence was not available"],
        },
        candidate_output=candidate,
    )


def _reproduction(label: str = "reproduction") -> dict[str, object]:
    return {
        "status": "VERIFIED",
        "method": "Owner local isolated replay",
        "evidence_refs": [_ref(label)],
    }


def test_verified_access_and_owner_reproduction_authorize_one_bounded_repair() -> None:
    assessment = _assessment()
    adjudication = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="BLOCKING",
        severity="high",
        owner_reproduction=_reproduction(),
    )

    assert assessment["findings"][0]["finding_kind"] == "CANDIDATE_FINDING"
    assert assessment["authority"] is False
    assert assessment["repair_authorized"] is False
    assert adjudication["terminal_state"] == "REPAIR_AUTHORIZED"
    assert adjudication["repair_authorized"] is True
    assert require_repair_authorization(
        adjudication,
        assessment=assessment,
        expected_work_key="work-1",
    ) == adjudication


def test_host_embedded_cognitive_review_has_no_independent_v_claim_but_owner_can_adjudicate() -> None:
    assessment = _assessment(access_mode="HOST_EMBEDDED")
    assert assessment["review_role"] == "COGNITIVE_REVIEW"
    assert assessment["evidence_access"]["cannot_access_filesystem"] is True
    assert assessment["evidence_access"]["independent_validation_claim_allowed"] is False
    assert assessment["adjudication_eligibility"] == "EVIDENCE_READY"

    adjudication = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="BLOCKING",
        severity="high",
        owner_reproduction=_reproduction("owner-hard-evidence"),
    )
    assert adjudication["repair_authorized"] is True


def test_no_evidence_access_can_only_produce_a_candidate() -> None:
    assessment = _assessment(evidence_status="UNVERIFIED", access_mode="NONE")

    assert assessment["adjudication_eligibility"] == "CANDIDATE_ONLY"
    with pytest.raises(AuditAdjudicationError, match="BLOCKING requires"):
        build_owner_adjudication(
            assessment=assessment,
            finding_id="finding-1",
            owner_identity="codex-main",
            disposition="BLOCKING",
            severity="high",
            owner_reproduction=_reproduction(),
        )

    disclosure = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="ADDITIONAL",
        severity="high",
        owner_reproduction={
            "status": "NOT_ATTEMPTED",
            "method": "not eligible for blocking adjudication",
            "evidence_refs": [],
        },
    )
    assert disclosure["terminal_state"] == "ACCEPT_HOLD"
    assert disclosure["repair_authorized"] is False


def test_verified_label_cannot_hide_an_incomplete_evidence_package() -> None:
    required = [_ref("one"), _ref("two")]
    with pytest.raises(AuditAdjudicationError, match="every required evidence ref"):
        build_audit_assessment(
            audit_id="audit-1",
            work_key="work-1",
            assessor_identity={
                "provider_id": "provider-a",
                "profile_ref": "profile",
                "model_id": "model",
                "transport_id": "transport",
            },
            assessment_plan={
                "methods": ["inspect"],
                "objects": ["source"],
                "depth": "bounded",
                "coverage": "sufficient",
                "blocking_severities": ["high"],
                "in_scope": ["source"],
                "out_of_scope": [],
            },
            scope_pins={
                "object_sha256": _sha("object"),
                "scope_sha256": _sha("scope"),
                "threat_model_sha256": _sha("threat"),
                "completion_bar_sha256": _sha("bar"),
            },
            required_evidence_refs=required,
            evidence_access={
                "status": "VERIFIED",
                "mode": "HOST_EMBEDDED",
                "package_ref": _ref("package"),
                "accessed_evidence_refs": required[:1],
                "limitations": [],
            },
            candidate_output=_candidate_output(verdict="ACCEPT_HOLD_CANDIDATE"),
        )


def test_same_family_without_novel_owner_evidence_cannot_start_repair_two() -> None:
    assessment = _assessment()
    first = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="BLOCKING",
        severity="high",
        owner_reproduction=_reproduction("same-proof"),
    )

    with pytest.raises(AuditAdjudicationError, match="novel evidence"):
        build_owner_adjudication(
            assessment=assessment,
            finding_id="finding-1",
            owner_identity="codex-main",
            disposition="BLOCKING",
            severity="high",
            owner_reproduction=_reproduction("same-proof"),
            prior_adjudications=[first],
        )


def test_assessment_and_adjudication_hashes_fail_closed_on_drift() -> None:
    assessment = _assessment()
    drifted_assessment = copy.deepcopy(assessment)
    drifted_assessment["assessment_plan"]["coverage"] = "expanded after verdict"
    with pytest.raises(AuditAdjudicationError, match="assessment_sha256 mismatch"):
        validate_audit_assessment(drifted_assessment)

    adjudication = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="BLOCKING",
        severity="high",
        owner_reproduction=_reproduction(),
    )
    drifted_adjudication = copy.deepcopy(adjudication)
    drifted_adjudication["repair_authorized"] = False
    with pytest.raises(AuditAdjudicationError, match="adjudication_sha256 mismatch"):
        validate_owner_adjudication(drifted_adjudication, assessment=assessment)


def test_published_json_schemas_accept_canonical_objects() -> None:
    root = Path(__file__).resolve().parents[1] / "services" / "agent_runtime" / "schemas"
    assessment = _assessment()
    adjudication = build_owner_adjudication(
        assessment=assessment,
        finding_id="finding-1",
        owner_identity="codex-main",
        disposition="BLOCKING",
        severity="high",
        owner_reproduction=_reproduction(),
    )
    assessment_schema = json.loads((root / "audit_assessment.v1.schema.json").read_text())
    adjudication_schema = json.loads((root / "audit_adjudication.v1.schema.json").read_text())
    candidate_schema = json.loads(
        (root / "audit_candidate_findings.v1.schema.json").read_text()
    )

    Draft202012Validator(candidate_schema).validate(_candidate_output())
    assert validate_audit_candidate_output(_candidate_output())["authority"] is False
    Draft202012Validator(assessment_schema).validate(assessment)
    Draft202012Validator(adjudication_schema).validate(adjudication)
