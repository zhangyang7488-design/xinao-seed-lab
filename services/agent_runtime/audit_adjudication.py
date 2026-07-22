"""Fail-closed admission and Owner adjudication for high-value audits.

An evaluator produces candidate findings only.  Cognitive APIs may consume a
host-embedded, hash-bound evidence package without filesystem access; tool
workers may inspect the same frozen package directly.  Neither route grants
repair authority.  Only an Owner reproduction of a new, in-scope blocker
against the frozen bug bar can derive one bounded repair authorization.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

AUDIT_ASSESSMENT_SCHEMA = "xinao.audit_assessment.v1"
AUDIT_ADJUDICATION_SCHEMA = "xinao.audit_adjudication.v1"
AUDIT_CANDIDATE_SCHEMA = "xinao.audit_candidate_findings.v1"

EVIDENCE_VERIFIED = "VERIFIED"
EVIDENCE_UNVERIFIED = "UNVERIFIED"
EVIDENCE_INCOMPLETE = "INCOMPLETE"
EVIDENCE_ACCESS_STATES = frozenset({EVIDENCE_VERIFIED, EVIDENCE_UNVERIFIED, EVIDENCE_INCOMPLETE})
ACCESS_MODE_HOST_EMBEDDED = "HOST_EMBEDDED"
ACCESS_MODE_DIRECT_TOOL = "DIRECT_TOOL"
ACCESS_MODE_NONE = "NONE"
EVIDENCE_ACCESS_MODES = frozenset(
    {ACCESS_MODE_HOST_EMBEDDED, ACCESS_MODE_DIRECT_TOOL, ACCESS_MODE_NONE}
)

CANDIDATE_VERDICT_HOLD = "ACCEPT_HOLD_CANDIDATE"
CANDIDATE_VERDICT_FINDINGS = "CANDIDATE_FINDINGS"
CANDIDATE_VERDICT_INCOMPLETE = "EVIDENCE_INCOMPLETE"
CANDIDATE_VERDICTS = frozenset(
    {
        CANDIDATE_VERDICT_HOLD,
        CANDIDATE_VERDICT_FINDINGS,
        CANDIDATE_VERDICT_INCOMPLETE,
    }
)

DISPOSITION_ACCEPT_HOLD = "ACCEPT_HOLD"
DISPOSITION_ADDITIONAL = "ADDITIONAL"
DISPOSITION_OUT_OF_SCOPE = "OUT_OF_SCOPE"
DISPOSITION_DUPLICATE = "DUPLICATE_NO_NEW_PROOF"
DISPOSITION_INVALID = "INVALID_EVALUATION"
DISPOSITION_BLOCKED = "BLOCKED"
DISPOSITION_BLOCKING = "BLOCKING"
DISPOSITIONS = frozenset(
    {
        DISPOSITION_ACCEPT_HOLD,
        DISPOSITION_ADDITIONAL,
        DISPOSITION_OUT_OF_SCOPE,
        DISPOSITION_DUPLICATE,
        DISPOSITION_INVALID,
        DISPOSITION_BLOCKED,
        DISPOSITION_BLOCKING,
    }
)


def audit_assessment_schema_sha256() -> str:
    path = Path(__file__).resolve().parent / "schemas" / "audit_assessment.v1.schema.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_candidate_schema_sha256() -> str:
    path = Path(__file__).resolve().parent / "schemas" / "audit_candidate_findings.v1.schema.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuditAdjudicationError(ValueError):
    """Raised when an audit fact tries to cross the authority boundary."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditAdjudicationError(f"{label} must be an object")
    return copy.deepcopy(dict(value))


def _sequence(value: object, label: str, *, allow_empty: bool = False) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AuditAdjudicationError(f"{label} must be an array")
    result = copy.deepcopy(list(value))
    if not allow_empty and not result:
        raise AuditAdjudicationError(f"{label} must be non-empty")
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditAdjudicationError(f"{label} must be a non-empty string")
    return value.strip()


def _sha(value: object, label: str) -> str:
    text = _text(value, label).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise AuditAdjudicationError(f"{label} must be a lowercase sha256")
    return text


def _hash_ref(value: object, label: str) -> dict[str, str]:
    raw = _mapping(value, label)
    if set(raw) != {"path", "sha256"}:
        raise AuditAdjudicationError(f"{label} must contain only path and sha256")
    return {
        "path": _text(raw.get("path"), f"{label}.path"),
        "sha256": _sha(raw.get("sha256"), f"{label}.sha256"),
    }


def _hash_refs(value: object, label: str, *, allow_empty: bool = False) -> list[dict[str, str]]:
    refs = [
        _hash_ref(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, allow_empty=allow_empty))
    ]
    keys = [(item["path"], item["sha256"]) for item in refs]
    if len(keys) != len(set(keys)):
        raise AuditAdjudicationError(f"{label} must not contain duplicate refs")
    return refs


def _evidence_citation(value: object, label: str) -> dict[str, Any]:
    raw = _mapping(value, label)
    expected = {"path", "source_sha256", "line_start", "line_end", "content_sha256"}
    if set(raw) != expected:
        raise AuditAdjudicationError(
            f"{label} must bind path, source sha, line range, and content sha"
        )
    start = raw.get("line_start")
    end = raw.get("line_end")
    if isinstance(start, bool) or not isinstance(start, int) or start < 1:
        raise AuditAdjudicationError(f"{label}.line_start must be a positive integer")
    if isinstance(end, bool) or not isinstance(end, int) or end < start:
        raise AuditAdjudicationError(f"{label}.line_end must be >= line_start")
    return {
        "path": _text(raw.get("path"), f"{label}.path"),
        "source_sha256": _sha(raw.get("source_sha256"), f"{label}.source_sha256"),
        "line_start": start,
        "line_end": end,
        "content_sha256": _sha(raw.get("content_sha256"), f"{label}.content_sha256"),
    }


def _evidence_citations(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    citations = [
        _evidence_citation(item, f"{label}[{index}]")
        for index, item in enumerate(_sequence(value, label, allow_empty=allow_empty))
    ]
    keys = [canonical_sha256(item) for item in citations]
    if len(keys) != len(set(keys)):
        raise AuditAdjudicationError(f"{label} must not contain duplicate citations")
    return citations


def _scope_pins(value: object) -> dict[str, str]:
    raw = _mapping(value, "scope_pins")
    expected = {"object_sha256", "scope_sha256", "threat_model_sha256", "completion_bar_sha256"}
    if set(raw) != expected:
        raise AuditAdjudicationError("scope_pins must contain the four frozen audit pins")
    return {key: _sha(raw[key], f"scope_pins.{key}") for key in sorted(expected)}


def _assessment_plan(value: object) -> dict[str, Any]:
    raw = _mapping(value, "assessment_plan")
    methods = [
        _text(item, "assessment_plan.methods[]")
        for item in _sequence(raw.get("methods"), "assessment_plan.methods")
    ]
    objects = [
        _text(item, "assessment_plan.objects[]")
        for item in _sequence(raw.get("objects"), "assessment_plan.objects")
    ]
    blocking = [
        _text(item, "assessment_plan.blocking_severities[]").lower()
        for item in _sequence(raw.get("blocking_severities"), "assessment_plan.blocking_severities")
    ]
    if len(methods) != len(set(methods)) or len(objects) != len(set(objects)):
        raise AuditAdjudicationError("assessment plan methods and objects must be unique")
    if len(blocking) != len(set(blocking)):
        raise AuditAdjudicationError("assessment_plan.blocking_severities must be unique")
    return {
        "methods": methods,
        "objects": objects,
        "depth": _text(raw.get("depth"), "assessment_plan.depth"),
        "coverage": _text(raw.get("coverage"), "assessment_plan.coverage"),
        "blocking_severities": blocking,
        "in_scope": [
            _text(item, "assessment_plan.in_scope[]")
            for item in _sequence(raw.get("in_scope"), "assessment_plan.in_scope")
        ],
        "out_of_scope": [
            _text(item, "assessment_plan.out_of_scope[]")
            for item in _sequence(
                raw.get("out_of_scope", []),
                "assessment_plan.out_of_scope",
                allow_empty=True,
            )
        ],
    }


def _evidence_access(value: object, required_refs: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    raw = _mapping(value, "evidence_access")
    status = _text(raw.get("status"), "evidence_access.status").upper()
    if status not in EVIDENCE_ACCESS_STATES:
        raise AuditAdjudicationError("evidence_access.status is unsupported")
    mode = _text(raw.get("mode"), "evidence_access.mode").upper()
    if mode not in EVIDENCE_ACCESS_MODES:
        raise AuditAdjudicationError("evidence_access.mode is unsupported")
    package_ref_value = raw.get("package_ref")
    package_ref = (
        _hash_ref(package_ref_value, "evidence_access.package_ref")
        if package_ref_value is not None
        else None
    )
    accessed = _hash_refs(
        raw.get("accessed_evidence_refs", []),
        "evidence_access.accessed_evidence_refs",
        allow_empty=True,
    )
    limitations = [
        _text(item, "evidence_access.limitations[]")
        for item in _sequence(
            raw.get("limitations", []),
            "evidence_access.limitations",
            allow_empty=True,
        )
    ]
    required_keys = {(item["path"], item["sha256"]) for item in required_refs}
    accessed_keys = {(item["path"], item["sha256"]) for item in accessed}
    complete = bool(required_keys) and required_keys.issubset(accessed_keys)
    if status == EVIDENCE_VERIFIED and (
        mode == ACCESS_MODE_NONE or not complete or package_ref is None
    ):
        raise AuditAdjudicationError(
            "VERIFIED evidence access requires a hash-bound package and every required evidence ref"
        )
    if mode == ACCESS_MODE_NONE and (accessed or package_ref is not None):
        raise AuditAdjudicationError(
            "NONE evidence access cannot bind accessed evidence or a package"
        )
    if status != EVIDENCE_VERIFIED and not limitations:
        raise AuditAdjudicationError("non-verified evidence access requires limitations")
    return {
        "status": status,
        "mode": mode,
        "package_ref": package_ref,
        "accessed_evidence_refs": accessed,
        "required_evidence_complete": complete,
        "cannot_access_filesystem": mode != ACCESS_MODE_DIRECT_TOOL,
        "independent_validation_claim_allowed": bool(
            status == EVIDENCE_VERIFIED and complete and mode == ACCESS_MODE_DIRECT_TOOL
        ),
        "limitations": limitations,
    }


def _findings(value: object) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(_sequence(value, "findings", allow_empty=True)):
        raw = _mapping(item, f"findings[{index}]")
        forbidden = {"blocking", "repair_authorized", "authority", "completion_claim_allowed"}
        if forbidden & set(raw):
            raise AuditAdjudicationError("evaluator findings cannot carry authority fields")
        if raw.get("finding_kind", "CANDIDATE_FINDING") != "CANDIDATE_FINDING":
            raise AuditAdjudicationError("evaluator findings must remain CANDIDATE_FINDING")
        finding_id = _text(raw.get("finding_id"), f"findings[{index}].finding_id")
        if finding_id in ids:
            raise AuditAdjudicationError("finding_id must be unique")
        ids.add(finding_id)
        findings.append(
            {
                "finding_id": finding_id,
                "family": _text(raw.get("family"), f"findings[{index}].family"),
                "title": _text(raw.get("title"), f"findings[{index}].title"),
                "claim": _text(raw.get("claim"), f"findings[{index}].claim"),
                "severity_claim": _text(
                    raw.get("severity_claim"), f"findings[{index}].severity_claim"
                ).lower(),
                "evidence_citations": _evidence_citations(
                    raw.get("evidence_citations", []),
                    f"findings[{index}].evidence_citations",
                    allow_empty=True,
                ),
                "reproduction_conditions": [
                    _text(value, f"findings[{index}].reproduction_conditions[]")
                    for value in _sequence(
                        raw.get("reproduction_conditions", []),
                        f"findings[{index}].reproduction_conditions",
                        allow_empty=True,
                    )
                ],
                "finding_kind": "CANDIDATE_FINDING",
            }
        )
    return findings


def validate_audit_candidate_output(value: Mapping[str, object]) -> dict[str, Any]:
    """Validate a model output that has evidence value but no authority."""

    raw = _mapping(value, "candidate_output")
    expected = {
        "schema_version",
        "verdict",
        "summary",
        "findings",
        "limitations",
        "authority",
        "completion_claim_allowed",
        "repair_authorized",
    }
    if set(raw) != expected:
        raise AuditAdjudicationError("candidate_output fields do not match the fixed contract")
    if raw.get("schema_version") != AUDIT_CANDIDATE_SCHEMA:
        raise AuditAdjudicationError("audit candidate schema mismatch")
    verdict = _text(raw.get("verdict"), "candidate_output.verdict").upper()
    if verdict not in CANDIDATE_VERDICTS:
        raise AuditAdjudicationError("candidate_output.verdict is unsupported")
    if raw.get("authority") is not False:
        raise AuditAdjudicationError("candidate output cannot carry authority")
    if raw.get("completion_claim_allowed") is not False:
        raise AuditAdjudicationError("candidate output cannot claim completion")
    if raw.get("repair_authorized") is not False:
        raise AuditAdjudicationError("candidate output cannot authorize repair")
    findings = _findings(raw.get("findings"))
    limitations = [
        _text(item, "candidate_output.limitations[]")
        for item in _sequence(
            raw.get("limitations"),
            "candidate_output.limitations",
            allow_empty=True,
        )
    ]
    if verdict == CANDIDATE_VERDICT_FINDINGS and not findings:
        raise AuditAdjudicationError("CANDIDATE_FINDINGS requires at least one finding")
    if verdict == CANDIDATE_VERDICT_HOLD and findings:
        raise AuditAdjudicationError("ACCEPT_HOLD_CANDIDATE cannot contain findings")
    if verdict == CANDIDATE_VERDICT_INCOMPLETE and not limitations:
        raise AuditAdjudicationError("EVIDENCE_INCOMPLETE requires limitations")
    for finding in findings:
        if not finding["evidence_citations"] or not finding["reproduction_conditions"]:
            raise AuditAdjudicationError(
                "candidate findings require embedded evidence citations and reproduction conditions"
            )
    return {
        "schema_version": AUDIT_CANDIDATE_SCHEMA,
        "verdict": verdict,
        "summary": _text(raw.get("summary"), "candidate_output.summary"),
        "findings": findings,
        "limitations": limitations,
        "authority": False,
        "completion_claim_allowed": False,
        "repair_authorized": False,
    }


def build_audit_assessment(
    *,
    audit_id: str,
    work_key: str,
    assessor_identity: Mapping[str, object],
    assessment_plan: Mapping[str, object],
    scope_pins: Mapping[str, object],
    required_evidence_refs: Sequence[Mapping[str, object]],
    evidence_access: Mapping[str, object],
    candidate_output: Mapping[str, object],
) -> dict[str, Any]:
    """Build a non-authoritative audit result bound to a sufficient package."""

    required = _hash_refs(required_evidence_refs, "required_evidence_refs")
    assessor = _mapping(assessor_identity, "assessor_identity")
    normalized_assessor = {
        field: _text(assessor.get(field), f"assessor_identity.{field}")
        for field in ("provider_id", "profile_ref", "model_id", "transport_id")
    }
    access = _evidence_access(evidence_access, required)
    candidate = validate_audit_candidate_output(candidate_output)
    if (
        candidate["verdict"] == CANDIDATE_VERDICT_INCOMPLETE
        and access["status"] == EVIDENCE_VERIFIED
    ):
        raise AuditAdjudicationError(
            "EVIDENCE_INCOMPLETE candidate output requires incomplete or unverified access"
        )
    value: dict[str, Any] = {
        "schema_version": AUDIT_ASSESSMENT_SCHEMA,
        "audit_id": _text(audit_id, "audit_id"),
        "work_key": _text(work_key, "work_key"),
        "assessor_identity": normalized_assessor,
        "assessment_plan": _assessment_plan(assessment_plan),
        "scope_pins": _scope_pins(scope_pins),
        "required_evidence_refs": required,
        "evidence_access": access,
        "candidate_verdict": candidate["verdict"],
        "candidate_summary": candidate["summary"],
        "candidate_limitations": candidate["limitations"],
        "findings": candidate["findings"],
        "review_role": (
            "INDEPENDENT_VALIDATION"
            if access["independent_validation_claim_allowed"]
            else "COGNITIVE_REVIEW"
        ),
        "adjudication_eligibility": (
            "EVIDENCE_READY" if access["status"] == EVIDENCE_VERIFIED else "CANDIDATE_ONLY"
        ),
        "authority": False,
        "completion_claim_allowed": False,
        "repair_authorized": False,
    }
    value["assessment_sha256"] = canonical_sha256(value)
    return value


def validate_audit_assessment(value: Mapping[str, object]) -> dict[str, Any]:
    raw = _mapping(value, "assessment")
    if raw.get("schema_version") != AUDIT_ASSESSMENT_SCHEMA:
        raise AuditAdjudicationError("audit assessment schema mismatch")
    observed = _sha(raw.get("assessment_sha256"), "assessment_sha256")
    unsigned = copy.deepcopy(raw)
    unsigned.pop("assessment_sha256", None)
    if canonical_sha256(unsigned) != observed:
        raise AuditAdjudicationError("assessment_sha256 mismatch")
    raw.pop("assessment_sha256", None)
    rebuilt = build_audit_assessment(
        audit_id=raw.get("audit_id"),
        work_key=raw.get("work_key"),
        assessor_identity=raw.get("assessor_identity"),
        assessment_plan=raw.get("assessment_plan"),
        scope_pins=raw.get("scope_pins"),
        required_evidence_refs=raw.get("required_evidence_refs"),
        evidence_access=raw.get("evidence_access"),
        candidate_output={
            "schema_version": AUDIT_CANDIDATE_SCHEMA,
            "verdict": raw.get("candidate_verdict"),
            "summary": raw.get("candidate_summary"),
            "findings": raw.get("findings"),
            "limitations": raw.get("candidate_limitations"),
            "authority": False,
            "completion_claim_allowed": False,
            "repair_authorized": False,
        },
    )
    if rebuilt["assessment_sha256"] != observed:
        raise AuditAdjudicationError("assessment_sha256 mismatch")
    return rebuilt


def _owner_reproduction(value: object) -> dict[str, Any]:
    raw = _mapping(value, "owner_reproduction")
    status = _text(raw.get("status"), "owner_reproduction.status").upper()
    if status not in {"VERIFIED", "FAILED", "NOT_ATTEMPTED"}:
        raise AuditAdjudicationError("owner_reproduction.status is unsupported")
    refs = _hash_refs(
        raw.get("evidence_refs", []),
        "owner_reproduction.evidence_refs",
        allow_empty=True,
    )
    method = _text(raw.get("method"), "owner_reproduction.method")
    if status == "VERIFIED" and not refs:
        raise AuditAdjudicationError("verified Owner reproduction requires evidence_refs")
    return {"status": status, "method": method, "evidence_refs": refs}


def _validated_prior(value: object) -> list[dict[str, Any]]:
    priors: list[dict[str, Any]] = []
    for index, item in enumerate(_sequence(value, "prior_adjudications", allow_empty=True)):
        raw = _mapping(item, f"prior_adjudications[{index}]")
        if raw.get("schema_version") != AUDIT_ADJUDICATION_SCHEMA:
            raise AuditAdjudicationError("prior adjudication schema mismatch")
        digest = _sha(raw.get("adjudication_sha256"), "prior.adjudication_sha256")
        unsigned = copy.deepcopy(raw)
        unsigned.pop("adjudication_sha256", None)
        if canonical_sha256(unsigned) != digest:
            raise AuditAdjudicationError("prior adjudication sha256 mismatch")
        priors.append(raw)
    return priors


def build_owner_adjudication(
    *,
    assessment: Mapping[str, object],
    finding_id: str,
    owner_identity: str,
    disposition: str,
    severity: str,
    owner_reproduction: Mapping[str, object],
    prior_adjudications: Sequence[Mapping[str, object]] = (),
) -> dict[str, Any]:
    """Adjudicate one candidate and derive, never accept, repair authority."""

    audit = validate_audit_assessment(assessment)
    selected = next(
        (item for item in audit["findings"] if item["finding_id"] == finding_id),
        None,
    )
    if selected is None:
        raise AuditAdjudicationError("finding_id is not present in assessment")
    decision = _text(disposition, "disposition").upper()
    if decision not in DISPOSITIONS:
        raise AuditAdjudicationError("unsupported disposition")
    normalized_severity = _text(severity, "severity").lower()
    reproduction = _owner_reproduction(owner_reproduction)
    priors = _validated_prior(prior_adjudications)

    evidence_ready = audit["adjudication_eligibility"] == "EVIDENCE_READY"
    finding_has_evidence = bool(selected["evidence_citations"])
    reproduced = reproduction["status"] == "VERIFIED"
    meets_bar = normalized_severity in audit["assessment_plan"]["blocking_severities"]
    current_hashes = {item["sha256"] for item in reproduction["evidence_refs"]}
    prior_hashes: set[str] = set()
    for prior in priors:
        if (
            prior.get("finding_family") == selected["family"]
            and prior.get("scope_pins") == audit["scope_pins"]
        ):
            prior_hashes.update(
                str(ref.get("sha256"))
                for ref in prior.get("owner_reproduction", {}).get("evidence_refs", [])
                if isinstance(ref, Mapping)
            )
    novel_evidence = bool(current_hashes - prior_hashes)
    repair_authorized = bool(
        decision == DISPOSITION_BLOCKING
        and evidence_ready
        and finding_has_evidence
        and reproduced
        and meets_bar
        and novel_evidence
    )
    if decision == DISPOSITION_BLOCKING and not repair_authorized:
        raise AuditAdjudicationError(
            "BLOCKING requires finding evidence, verified evidence access, Owner reproduction, bug-bar severity, and novel evidence"
        )

    terminal_state = {
        DISPOSITION_INVALID: "INVALID_EVALUATION",
        DISPOSITION_BLOCKED: "BLOCKED",
        DISPOSITION_BLOCKING: "REPAIR_AUTHORIZED",
    }.get(decision, "ACCEPT_HOLD")
    value: dict[str, Any] = {
        "schema_version": AUDIT_ADJUDICATION_SCHEMA,
        "audit_id": audit["audit_id"],
        "assessment_sha256": audit["assessment_sha256"],
        "work_key": audit["work_key"],
        "finding_id": selected["finding_id"],
        "finding_family": selected["family"],
        "owner_identity": _text(owner_identity, "owner_identity"),
        "scope_pins": audit["scope_pins"],
        "disposition": decision,
        "severity": normalized_severity,
        "owner_reproduction": reproduction,
        "novel_evidence": novel_evidence,
        "repair_authorized": repair_authorized,
        "terminal_state": terminal_state,
        "authority": False,
        "completion_claim_allowed": False,
    }
    value["adjudication_sha256"] = canonical_sha256(value)
    return value


def validate_owner_adjudication(
    value: Mapping[str, object],
    *,
    assessment: Mapping[str, object],
    prior_adjudications: Sequence[Mapping[str, object]] = (),
) -> dict[str, Any]:
    raw = _mapping(value, "adjudication")
    if raw.get("schema_version") != AUDIT_ADJUDICATION_SCHEMA:
        raise AuditAdjudicationError("audit adjudication schema mismatch")
    observed = _sha(raw.get("adjudication_sha256"), "adjudication_sha256")
    unsigned = copy.deepcopy(raw)
    unsigned.pop("adjudication_sha256", None)
    if canonical_sha256(unsigned) != observed:
        raise AuditAdjudicationError("adjudication_sha256 mismatch")
    rebuilt = build_owner_adjudication(
        assessment=assessment,
        finding_id=raw.get("finding_id"),
        owner_identity=raw.get("owner_identity"),
        disposition=raw.get("disposition"),
        severity=raw.get("severity"),
        owner_reproduction=raw.get("owner_reproduction"),
        prior_adjudications=prior_adjudications,
    )
    if rebuilt["adjudication_sha256"] != observed:
        raise AuditAdjudicationError("adjudication_sha256 mismatch")
    return rebuilt


def require_repair_authorization(
    adjudication: Mapping[str, object],
    *,
    assessment: Mapping[str, object],
    expected_work_key: str,
    prior_adjudications: Sequence[Mapping[str, object]] = (),
) -> dict[str, Any]:
    """Fail closed unless a repair is bound to a valid Owner adjudication."""

    validated = validate_owner_adjudication(
        adjudication,
        assessment=assessment,
        prior_adjudications=prior_adjudications,
    )
    if validated["work_key"] != _text(expected_work_key, "expected_work_key"):
        raise AuditAdjudicationError("repair work_key does not bind adjudication")
    if validated["repair_authorized"] is not True:
        raise AuditAdjudicationError("repair is not authorized by Owner adjudication")
    return validated


def load_hash_bound_json_ref(
    ref: Mapping[str, object],
    *,
    label: str,
) -> dict[str, Any]:
    normalized = _hash_ref(ref, label)
    path = Path(normalized["path"])
    if not path.is_file():
        raise AuditAdjudicationError(f"{label} missing: {path}")
    raw = path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != normalized["sha256"]:
        raise AuditAdjudicationError(f"{label} sha256 mismatch")
    value = json.loads(raw.decode("utf-8-sig"))
    return _mapping(value, label)
