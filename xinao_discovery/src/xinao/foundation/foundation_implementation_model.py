"""Versioned implementation model for the current F1-F4 closure profile.

The formal human contract remains authoritative.  This module only freezes the
executable artifact, assertion, input, schema, and exclusion inventory that the
runtime can verify.  The D-drive blueprint may fingerprint this model; it may
not redefine or selectively override it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from xinao.canonical import canonical_sha256
from xinao.foundation import f2_assertions, f3_assertions
from xinao.foundation import f4_current_evidence_verifier as f4_verifier
from xinao.foundation.assertion_verifier_registry import CANONICAL_PROJECTION_PATH
from xinao.foundation.assertion_verifiers import common
from xinao.foundation.assertion_verifiers import f1_assertion_actuals as f1_actuals
from xinao.foundation.assertion_verifiers import f2_assertion_actuals as f2_actuals
from xinao.foundation.assertion_verifiers import f3_assertion_actuals as f3_actuals
from xinao.foundation.assertion_verifiers import f4_assertion_actuals as f4_actuals
from xinao.foundation.authority_generation import (
    AuthorityGenerationError,
    load_generation_binding_from_projection,
)

IMPLEMENTATION_MODEL_SCHEMA_VERSION = "xinao.foundation_closure_implementation_model.v2"
IMPLEMENTATION_MODEL_VERSION = "foundation-closure-authority-generation.v2"
FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION = "xinao.foundation_closure_report.v2"

_AUTHORITY_BINDING_KEYS = {
    "generation_manifest_sha256",
    "generation_content_sha256",
    "human_spec_snapshot_sha256",
    "formal_contract_snapshot_sha256",
    "implementation_model_core_sha256",
    "publication_manifest_sha256",
    "owner_verdict_sha256",
}

KNOWN_INPUT_HASHES = {
    "active_quote_projection_sha256": (
        "4827a01f52423363e922caf7420f1af99e1442ea02bbb509b126100974798798"
    ),
    "baseline_sha256": ("634c50219fb4450332d79b232275854adf648d4c5614eaabf5a961eb9f7bfbf1"),
    "compiler_config_sha256": ("40bcf82e9cad508d085236b1e787e180b061c8bf5cc906f95c5fff07a51131d5"),
    "dataset_sha256": ("57f9fc68f48416fd38610da1cf0bba3476537318514f0093fcb86af3a94ab2c6"),
    "f3_external_synthesis_sha256": (
        "35a47ab7cfbc7f78e3e87f38e8777dfbc88308985f5f17c1a5515a03e2505996"
    ),
    "f3_prior_draft_sha256": ("9177e2788286aa7aeef82d315ad4788088b27612653b8a57aa846b0ac7d1b819"),
    "f3_service_graph_sha256": ("b288837827b6b1b616494510a5f86c912a3540ae845a21d460d9762b48fa2555"),
    "play_catalog_sha256": ("1debfcf4fc3761f4527aa80798fef051f381b63975c28c3116bae7d0507ca2f0"),
    "rule_semantic_map_sha256": (
        "b5d2322acce980067cd9108ff973cfa1747469173ae6a02d728611e6bd372b0e"
    ),
}

F1_REQUIRED_ASSERTIONS: dict[str, Any] = {
    "catalog_total_eq": 433,
    "family_total_eq": 13,
    "catalog_identity_mapped_eq": 433,
    "semantic_rule_mapped_eq": 416,
    "active_settlement_compiled_eq": 416,
    "active_settlement_not_compiled_eq": 0,
    "unclassified_eq": 0,
    "draw_total_eq": 913,
    "distinct_active_world_cells_eq": 379_808,
    "actual_event_key_set_equals_expected": True,
    "expected_selection_set_derived_independently_from_catalog_and_baseline": True,
    "rule_semantic_map_selection_set_equals_independent_expected_selection_set": True,
    "atomic_ticket_binding_count_eq": 37,
    "active_atomic_selection_count_eq": 21_652_542_248,
    "atomic_ticket_count_eq": 21_652_539_822,
    "atomic_ticket_domain_lazy_not_materialized": True,
    "missing_event_keys_eq": 0,
    "unexpected_event_keys_eq": 0,
    "duplicate_event_keys_eq": 0,
    "every_semantic_family_has_positive_negative_boundary_property_tests_and_replay": True,
    "required_rule_fields_complete": list(f1_actuals.REQUIRED_RULE_FIELDS),
    "fresh_process_world_hash_equals_recorded": True,
    "reordered_input_world_hash_equals_recorded": True,
}

FOUNDATION_EXCLUSIONS = (
    "archived_blueprint_translation",
    "bare_or_manually_written_readiness_boolean",
    "candidate_business_or_weekly_evidence_compensation",
    "formal_autonomous_domain_research_or_g0_g8_compensation",
    "formal_research_allowed",
    "frozen_agent_route_quote",
    "full_research_space_or_measured_attention_claim",
    "partial_slice_canary_or_local_report",
)


def _block(
    artifact_types: object,
    assertion_ids: object,
    expectations: dict[str, Any],
) -> dict[str, Any]:
    artifacts = sorted(str(item) for item in artifact_types)  # type: ignore[arg-type]
    assertions = list(str(item) for item in assertion_ids)  # type: ignore[arg-type]
    if set(assertions) != set(expectations):
        raise RuntimeError("foundation implementation assertion inventory drifted")
    return {
        "required_artifact_types": artifacts,
        "required_assertion_ids": assertions,
        "required_assertions": deepcopy(expectations),
    }


def _implementation_model_core() -> dict[str, Any]:
    f2_expectations = dict(f2_assertions.F2_REQUIRED_ASSERTIONS)
    f3_expectations = dict(f3_assertions.F3_REQUIRED_ASSERTION_EXPECTATIONS)
    f4_expectations = {assertion_id: True for assertion_id in f4_verifier.ASSERTION_IDS}
    return {
        "schema_version": IMPLEMENTATION_MODEL_SCHEMA_VERSION,
        "model_version": IMPLEMENTATION_MODEL_VERSION,
        "blocks": {
            "F1_settlement_world": _block(
                f1_actuals.ARTIFACT_TYPES,
                f1_actuals.ASSERTION_IDS,
                F1_REQUIRED_ASSERTIONS,
            ),
            "F2_issuer_settlement_cost_space": _block(
                f2_actuals.ARTIFACT_TYPES,
                f2_actuals.ASSERTION_IDS,
                f2_expectations,
            ),
            "F3_research_weight": _block(
                f3_actuals.ARTIFACT_TYPES,
                f3_actuals.ASSERTION_IDS,
                f3_expectations,
            ),
            "F4_research_factory": _block(
                f4_actuals._ARTIFACT_TYPES,
                f4_verifier.ASSERTION_IDS,
                f4_expectations,
            ),
        },
        "input_hash_inventory": {
            "required_input_hash_keys": sorted(common.INPUT_KEYS),
            "known_input_hashes": dict(sorted(KNOWN_INPUT_HASHES.items())),
            "config_hash": KNOWN_INPUT_HASHES["compiler_config_sha256"],
        },
        "required_report_schema_version": FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        "foundation_exclusions": list(FOUNDATION_EXCLUSIONS),
        "does_not_imply_formal_research": True,
    }


def implementation_model_core_sha256() -> str:
    """Return the authority-independent identity reviewed by the owner gate."""

    return canonical_sha256(_implementation_model_core())


def _authority_binding(value: Mapping[str, Any] | None) -> dict[str, str]:
    if value is None:
        try:
            projection = json.loads(CANONICAL_PROJECTION_PATH.read_text(encoding="utf-8-sig"))
            if not isinstance(projection, dict):
                raise AuthorityGenerationError("current projection must be an object")
            value, _ = load_generation_binding_from_projection(projection)
        except (OSError, UnicodeError, json.JSONDecodeError, AuthorityGenerationError) as exc:
            raise RuntimeError("current Foundation authority generation is unavailable") from exc
    binding = dict(value)
    if set(binding) != _AUTHORITY_BINDING_KEYS or not all(
        isinstance(item, str) and len(item) == 64 for item in binding.values()
    ):
        raise RuntimeError("Foundation authority generation binding is invalid")
    if binding["implementation_model_core_sha256"] != implementation_model_core_sha256():
        raise RuntimeError("Foundation implementation model core is not owner-reviewed")
    return dict(sorted(binding.items()))


def foundation_implementation_model(
    authority_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the content-addressed current implementation model."""

    sealed_binding = _authority_binding(authority_binding)
    core: dict[str, Any] = {
        **_implementation_model_core(),
        "authority_binding": sealed_binding,
    }
    return {**core, "content_sha256": canonical_sha256(core)}


def foundation_profile(
    authority_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize the exact profile shape consumed by closure derivation."""

    model = foundation_implementation_model(authority_binding)
    inventory = model["input_hash_inventory"]
    return {
        "blocks": deepcopy(model["blocks"]),
        "_closure_meta": {
            "required_input_hash_keys": list(inventory["required_input_hash_keys"]),
            "known_input_hashes": dict(inventory["known_input_hashes"]),
            "config_hash": inventory["config_hash"],
            "required_report_schema_version": model["required_report_schema_version"],
            "implementation_model_schema_version": model["schema_version"],
            "implementation_model_version": model["model_version"],
            "implementation_model_sha256": model["content_sha256"],
        },
        "foundation_exclusions": list(model["foundation_exclusions"]),
    }


def implementation_model_projection(
    authority_binding: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return the only fields the non-authoritative blueprint may project."""

    model = foundation_implementation_model(authority_binding)
    return {
        "implementation_model_schema_version": str(model["schema_version"]),
        "implementation_model_version": str(model["model_version"]),
        "implementation_model_sha256": str(model["content_sha256"]),
    }


__all__ = [
    "FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION",
    "IMPLEMENTATION_MODEL_SCHEMA_VERSION",
    "IMPLEMENTATION_MODEL_VERSION",
    "foundation_implementation_model",
    "foundation_profile",
    "implementation_model_core_sha256",
    "implementation_model_projection",
]
