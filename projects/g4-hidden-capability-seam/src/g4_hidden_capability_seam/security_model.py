"""Security model and role eligibility for the hidden-capability isolation seam.

Same-suite subject eligibility depends on append-only exposure evidence.
Exposure to final generator semantics, hidden parameters, family identity,
truth, or per-case scoring rules makes a role ineligible as subject.
"""

from __future__ import annotations

from typing import Any, Iterable

ROLES = (
    "seam_author",
    "real_generator_author",
    "vault_custodian",
    "subject",
    "promptfoo_runner_operator",
    "independent_evaluator",
    "result_release_reviewer",
    "owner",
)

# Exposure classes that make same-suite subject ineligible.
SUBJECT_DISQUALIFYING_EXPOSURES = frozenset(
    {
        "final_generator_semantics",
        "hidden_parameter",
        "family_identity",
        "truth",
        "per_case_scoring_rule",
    }
)

PUBLIC_SAFE_EXPOSURES = frozenset(
    {
        "public_manifest",
        "public_case_id",
        "public_prompt_text",
        "commitment_digest",
        "route_public_descriptor",
        "raw_output_envelope_public_fields",
    }
)

SUBJECT_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "vault_locator",
        "vault_path",
        "seed",
        "hidden_parameters",
        "parameters",
        "truth",
        "answer",
        "sealed_answer",
        "family_identity",
        "rejection_label",
        "scorer_features",
        "scorer_credentials",
        "evaluator_token",
        "ground_truth",
        "answer_key",
        "scoring_rule",
        "heldout_truth",
    }
)


def role_catalog() -> dict[str, Any]:
    return {
        "schema_version": "xinao.g4.hidden_capability_seam.security_model.v1",
        "roles": list(ROLES),
        "role_duties": {
            "seam_author": "Build generic isolation machinery and synthetic fixtures only",
            "real_generator_author": "Future only; mints real hidden suites outside this package",
            "vault_custodian": "Holds sealed vault; never co-process with subject/Promptfoo",
            "subject": "Produces raw outputs from public cases only",
            "promptfoo_runner_operator": "Enumerates public cases offline; no scorer/vault access",
            "independent_evaluator": "Separate process/state root; may read vault under capability",
            "result_release_reviewer": "Reviews sealed envelopes before any release decision",
            "owner": "Codex owner; sole formal write/adopt/authority actor outside this package",
        },
        "subject_disqualifying_exposures": sorted(SUBJECT_DISQUALIFYING_EXPOSURES),
        "public_safe_exposures": sorted(PUBLIC_SAFE_EXPOSURES),
        "subject_forbidden_public_keys": sorted(SUBJECT_FORBIDDEN_PUBLIC_KEYS),
        "same_suite_subject_rule": (
            "Eligible only if ExposureLedger proves no disqualifying exposure "
            "for that principal on the suite-bound exposure_subject_identity."
        ),
        "this_package_may_mint_real_identity": False,
        "authority": False,
        "completion_claim_allowed": False,
        "synthetic_only": True,
    }


def is_subject_eligible(
    *,
    exposure_subject_identity_sha256: str,
    principal_id: str,
    exposure_records: Iterable[dict[str, Any]],
    suite_identity_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate same-suite subject eligibility from append-only exposure evidence."""
    hits: list[dict[str, Any]] = []
    for rec in exposure_records:
        if rec.get("exposure_subject_identity_sha256") != exposure_subject_identity_sha256:
            continue
        if rec.get("principal_id") != principal_id:
            continue
        kind = str(rec.get("exposure_kind") or "")
        if kind in SUBJECT_DISQUALIFYING_EXPOSURES:
            hits.append(
                {
                    "entry_index": rec.get("entry_index"),
                    "exposure_kind": kind,
                    "entry_sha256": rec.get("entry_sha256"),
                }
            )
    eligible = len(hits) == 0
    return {
        "ok": True,
        "eligible": eligible,
        "principal_id": principal_id,
        "exposure_subject_identity_sha256": exposure_subject_identity_sha256,
        "suite_identity_sha256": suite_identity_sha256,
        "disqualifying_hits": hits,
        "reason": None if eligible else "subject_ineligible_due_to_exposure",
        "authority": False,
    }


def scan_forbidden_public_payload(payload: Any, path: str = "$") -> list[str]:
    """Return dotted paths of forbidden keys found in a public payload tree."""
    found: list[str] = []
    if isinstance(payload, dict):
        for k, v in payload.items():
            p = f"{path}.{k}"
            if k in SUBJECT_FORBIDDEN_PUBLIC_KEYS:
                found.append(p)
            found.extend(scan_forbidden_public_payload(v, p))
    elif isinstance(payload, list):
        for i, v in enumerate(payload):
            found.extend(scan_forbidden_public_payload(v, f"{path}[{i}]"))
    return found
