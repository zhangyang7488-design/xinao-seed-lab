"""Machine-checkable actuals for the registered F3 research-weight surface.

F3 allocates research resources over the already registered initial surface.
It does not claim a complete research language, discovery space, settlement
truth, draw probability, player amount, or bookmaker exposure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from xinao.foundation.research_weight import SEMANTIC_ROLE, verify_versioned_object

F3_REQUIRED_ARTIFACT_TYPES = frozenset(
    {
        "ActiveResearchSurfaceVersion",
        "ContentServiceGraphVersion",
        "ResearchAttentionPriorVersion",
        "ResearchPortfolioPolicyVersion",
        "ResearchWeightBaselineVersion",
        "SourceDependencyGraphVersion",
    }
)

F3_REQUIRED_ASSERTION_EXPECTATIONS: dict[str, Any] = {
    "active_quote_version_count_eq": 1,
    "all_six_objects_bind_same_active_foundation": True,
    "all_versioned_objects_hash_bound_and_recomputable": True,
    "content_service_active_component_count_eq": 416,
    "does_not_modify_eq": [
        "BETTING_AMOUNT",
        "BOOKMAKER_EXPOSURE",
        "DRAW_PROBABILITY",
        "SETTLEMENT_TRUTH",
    ],
    "exploration_share_gt_zero": True,
    "full_research_space_claimed": False,
    "measured_attention_prior_claimed": False,
    "object_semantic_roles_eq": [SEMANTIC_ROLE],
    "policy_update_signals_eq": [
        "EXPECTED_INFORMATION_GAIN",
        "FALSIFICATION_VALUE",
        "FOUNDATION_GAP",
        "NOVELTY",
    ],
    "registered_active_component_count_eq": 416,
    "registered_active_family_count_eq": 13,
    "registered_surface_family_set_matches_prior_and_baseline": True,
    "required_versioned_object_types_eq": sorted(F3_REQUIRED_ARTIFACT_TYPES),
    "research_attention_prior_identity_eq": "QUALITATIVE_SEED",
    "research_resource_shares_sum_to_one": True,
}
F3_REQUIRED_ASSERTION_IDS = tuple(sorted(F3_REQUIRED_ASSERTION_EXPECTATIONS))

_FULL_RESEARCH_CLAIM_TOKENS = frozenset(
    {
        "DISCOVERY_LANGUAGE_READY",
        "DOMAIN_RESEARCH_ADMISSION_READY",
        "FULL_RESEARCH_SPACE",
        "RESEARCH_DSL_COMPLETE",
    }
)


def _rows(value: object, *, label: str) -> list[Mapping[str, Any]]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a sequence")
    rows = list(value)
    if not all(isinstance(item, Mapping) for item in rows):
        raise ValueError(f"{label} entries must be objects")
    return rows


def _contains_full_research_claim(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).upper() in _FULL_RESEARCH_CLAIM_TOKENS
            or _contains_full_research_claim(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_full_research_claim(item) for item in value)
    return isinstance(value, str) and value.upper() in _FULL_RESEARCH_CLAIM_TOKENS


def compile_f3_assertion_actuals(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Derive expectation-free F3 actual values from one recomputed bundle."""

    if not isinstance(bundle, Mapping):
        raise TypeError("bundle must be a mapping")
    raw_objects = bundle.get("objects")
    if not isinstance(raw_objects, Mapping):
        raise ValueError("F3 bundle objects must be a mapping")
    objects = dict(raw_objects)
    if set(objects) != F3_REQUIRED_ARTIFACT_TYPES:
        raise ValueError("F3 bundle object inventory is not the required six-object set")
    if not all(isinstance(value, Mapping) for value in objects.values()):
        raise ValueError("F3 bundle objects must be mappings")

    prior = objects["ResearchAttentionPriorVersion"]
    baseline = objects["ResearchWeightBaselineVersion"]
    surface = objects["ActiveResearchSurfaceVersion"]
    policy = objects["ResearchPortfolioPolicyVersion"]
    content = objects["ContentServiceGraphVersion"]

    prior_rows = _rows(prior.get("rows"), label="ResearchAttentionPriorVersion.rows")
    baseline_rows = _rows(
        baseline.get("family_rows"), label="ResearchWeightBaselineVersion.family_rows"
    )
    surface_rows = _rows(surface.get("rows"), label="ActiveResearchSurfaceVersion.rows")
    content_nodes = _rows(content.get("nodes"), label="ContentServiceGraphVersion.nodes")

    prior_families = {str(row.get("family_id")) for row in prior_rows}
    baseline_families = {str(row.get("family_id")) for row in baseline_rows}
    surface_families = {str(row.get("family_id")) for row in surface_rows}
    family_sets_match = (
        prior_families == baseline_families == surface_families
        and len(prior_families) == 13
    )

    try:
        exploration_share = Decimal(str(policy.get("exploration_share")))
        family_share_total = sum(
            (Decimal(str(row.get("research_resource_share"))) for row in baseline_rows),
            Decimal("0"),
        )
        allocation_total = family_share_total + Decimal(
            str(baseline.get("exploration", {}).get("research_resource_share"))
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("F3 research-resource shares are not finite decimals") from exc

    active_component_count = sum(
        int(row.get("active_component_count", -1)) for row in baseline_rows
    )
    active_content_nodes = [
        row for row in content_nodes if row.get("role") == "ACTIVE_SETTLEMENT_COMPONENT"
    ]
    active_foundation_ref = bundle.get("active_foundation_sha256")
    object_foundation_refs = {value.get("active_foundation_ref") for value in objects.values()}

    return {
        "active_quote_version_count_eq": bundle.get("active_quote_version_count"),
        "all_six_objects_bind_same_active_foundation": (
            isinstance(active_foundation_ref, str)
            and object_foundation_refs == {active_foundation_ref}
        ),
        "all_versioned_objects_hash_bound_and_recomputable": all(
            verify_versioned_object(value) for value in objects.values()
        ),
        "content_service_active_component_count_eq": len(active_content_nodes),
        "does_not_modify_eq": sorted(str(item) for item in bundle.get("does_not_modify", [])),
        "exploration_share_gt_zero": exploration_share > 0,
        "full_research_space_claimed": _contains_full_research_claim(bundle),
        "measured_attention_prior_claimed": bundle.get("measured_attention_claimed") is True,
        "object_semantic_roles_eq": sorted(
            {str(value.get("semantic_role")) for value in objects.values()}
        ),
        "policy_update_signals_eq": sorted(
            str(item) for item in policy.get("update_signals", [])
        ),
        "registered_active_component_count_eq": active_component_count,
        "registered_active_family_count_eq": len(baseline_families),
        "registered_surface_family_set_matches_prior_and_baseline": family_sets_match,
        "required_versioned_object_types_eq": sorted(objects),
        "research_attention_prior_identity_eq": prior.get("prior_identity"),
        "research_resource_shares_sum_to_one": allocation_total == Decimal("1"),
    }


__all__ = [
    "F3_REQUIRED_ARTIFACT_TYPES",
    "F3_REQUIRED_ASSERTION_EXPECTATIONS",
    "F3_REQUIRED_ASSERTION_IDS",
    "compile_f3_assertion_actuals",
]
