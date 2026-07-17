"""Independent F1 assertion actuals recomputation.

The fixed runner calls :func:`build_assertion_actuals_v1`.  The callable emits
only canonical actual values; it never emits PASS, expected values, identities,
or evidence seals.
"""

from __future__ import annotations

from collections import Counter as _Counter
from collections.abc import Mapping as _Mapping
from typing import Any as _Any

from xinao.canonical import ordered_json_stream_sha256 as _ordered_json_stream_sha256
from xinao.foundation.assertion_verifiers import common as _common
from xinao.foundation.f1_property_suite import (
    F1PropertySuiteEvidence as _F1PropertySuiteEvidence,
)
from xinao.foundation.f1_property_suite import (
    current_property_source_hashes as _current_property_source_hashes,
)
from xinao.foundation.f1_replay import (
    F1RepresentativeReplayEvidence as _F1RepresentativeReplayEvidence,
)
from xinao.foundation.selection_manifest import (
    ACTIVE_SETTLEMENT_BASELINE_IDS,
)
from xinao.foundation.selection_manifest import (
    AtomicTicketBindingVersion as _AtomicTicketBindingVersion,
)
from xinao.foundation.selection_manifest import (
    assert_registry_manifest_matches as _assert_registry_manifest_matches,
)
from xinao.foundation.selection_manifest import (
    classify_catalog_physical_roles as _classify_catalog_physical_roles,
)
from xinao.foundation.selection_manifest import (
    compile_atomic_ticket_bindings as _compile_atomic_ticket_bindings,
)
from xinao.foundation.selection_manifest import (
    compile_independent_selection_manifest as _compile_independent_selection_manifest,
)
from xinao.foundation.semantics_registry import (
    ExpectedSelectionDomainManifestVersion as _ExpectedSelectionDomainManifestVersion,
)
from xinao.foundation.semantics_registry import (
    RuleSemanticMapVersion as _RuleSemanticMapVersion,
)
from xinao.foundation.semantics_registry import (
    RuleSetVersion as _RuleSetVersion,
)
from xinao.foundation.semantics_registry import (
    SettlementFunctionSetVersion as _SettlementFunctionSetVersion,
)
from xinao.foundation.world_compile import (
    EventMatrixSnapshot as _EventMatrixSnapshot,
)
from xinao.foundation.world_compile import (
    WorldSnapshot as _WorldSnapshot,
)

BLOCK_ID = "F1_settlement_world"
ARTIFACT_TYPES = frozenset(
    {
        "RuleSemanticMapVersion",
        "ExpectedSelectionDomainManifestVersion",
        "AtomicTicketBindingVersion",
        "RuleSetVersion",
        "SettlementFunctionSetVersion",
        "EventMatrixSnapshot",
        "WorldSnapshot",
    }
)
ASSERTION_IDS = (
    "catalog_total_eq",
    "family_total_eq",
    "catalog_identity_mapped_eq",
    "semantic_rule_mapped_eq",
    "active_settlement_compiled_eq",
    "active_settlement_not_compiled_eq",
    "unclassified_eq",
    "draw_total_eq",
    "distinct_active_world_cells_eq",
    "actual_event_key_set_equals_expected",
    "expected_selection_set_derived_independently_from_catalog_and_baseline",
    "rule_semantic_map_selection_set_equals_independent_expected_selection_set",
    "atomic_ticket_binding_count_eq",
    "active_atomic_selection_count_eq",
    "atomic_ticket_count_eq",
    "atomic_ticket_domain_lazy_not_materialized",
    "missing_event_keys_eq",
    "unexpected_event_keys_eq",
    "duplicate_event_keys_eq",
    "every_semantic_family_has_positive_negative_boundary_property_tests_and_replay",
    "required_rule_fields_complete",
    "fresh_process_world_hash_equals_recorded",
    "reordered_input_world_hash_equals_recorded",
)
REQUIRED_RULE_FIELDS = (
    "semantic_evidence_status",
    "selection_space",
    "settlement_tiers",
    "snapshot_payout_binding",
    "principal_refund_on_normal_settlement",
    "void_policy",
    "rounding_policy",
    "boundary_policy",
    "effective_interval",
)

ARTIFACT_MODELS = {
    "RuleSemanticMapVersion": _RuleSemanticMapVersion,
    "ExpectedSelectionDomainManifestVersion": _ExpectedSelectionDomainManifestVersion,
    "AtomicTicketBindingVersion": _AtomicTicketBindingVersion,
    "RuleSetVersion": _RuleSetVersion,
    "SettlementFunctionSetVersion": _SettlementFunctionSetVersion,
    "EventMatrixSnapshot": _EventMatrixSnapshot,
    "WorldSnapshot": _WorldSnapshot,
}


def build_assertion_actuals_v1(request: _Mapping[str, _Any]) -> dict[str, _Any]:
    """Recompute the exact F1 actual inventory from bound source bytes."""

    prepared = _common.prepare_request(
        request,
        expected_block_id=BLOCK_ID,
        expected_artifact_types=ARTIFACT_TYPES,
        expected_assertion_ids=ASSERTION_IDS,
    )
    retained = _common.load_artifact_payloads(prepared)
    catalog, registry = _common.compile_registry_input(prepared)
    isolated = _common.run_f1_isolated_recomputation(prepared)

    final = isolated["final"]
    event_snapshot_payload = final.get("event_matrix_snapshot")
    world_snapshot_payload = final.get("world_snapshot")
    replay_payload = final.get("replay")
    property_suite_payload = final.get("property_suite")
    if not all(
        isinstance(item, dict)
        for item in (
            event_snapshot_payload,
            world_snapshot_payload,
            replay_payload,
            property_suite_payload,
        )
    ):
        raise _common.AssertionActualsError("isolated F1 final output is incomplete")
    event_snapshot = _EventMatrixSnapshot.model_validate(event_snapshot_payload)
    world_snapshot = _WorldSnapshot.model_validate(world_snapshot_payload)
    replay = _F1RepresentativeReplayEvidence.model_validate(replay_payload)
    property_suite = _F1PropertySuiteEvidence.model_validate(property_suite_payload)
    reordered_matches = isolated["reordered"].get("matches") is True

    independent = _compile_independent_selection_manifest(catalog)
    comparison = _assert_registry_manifest_matches(independent, registry.expected_selection_domain)
    atomic = _compile_atomic_ticket_bindings(catalog, independent)

    recomputed = {
        "RuleSemanticMapVersion": registry.rule_semantic_map.model_dump(mode="json"),
        "ExpectedSelectionDomainManifestVersion": (
            registry.expected_selection_domain.model_dump(mode="json")
        ),
        "AtomicTicketBindingVersion": atomic.model_dump(mode="json"),
        "RuleSetVersion": registry.rule_set.model_dump(mode="json"),
        "SettlementFunctionSetVersion": registry.settlement_function_set.model_dump(mode="json"),
        "EventMatrixSnapshot": event_snapshot.model_dump(mode="json"),
        "WorldSnapshot": world_snapshot.model_dump(mode="json"),
    }
    _common.assert_recomputed_artifacts(retained, recomputed)

    roles = _classify_catalog_physical_roles(catalog)
    role_counts = _Counter(roles.values())
    event_keys = isolated["event_keys"]
    keys_equal = event_keys.get("keys_equal") is True
    missing_keys = event_keys.get("missing_keys")
    unexpected_keys = event_keys.get("unexpected_keys")
    duplicate_keys = event_keys.get("duplicate_keys")
    if not all(
        type(item) is int and item >= 0 for item in (missing_keys, unexpected_keys, duplicate_keys)
    ):
        raise _common.AssertionActualsError("isolated F1 event-key output is invalid")
    family_replay_complete = (
        replay.result_status == "VERIFIED"
        and replay.family_count == 13
        and replay.case_count == 39
        and all(
            item.status == "VERIFIED"
            for item in replay.representative_replay_summary.family_coverage
        )
    )
    expected_baseline_ids = tuple(
        sorted(record.baseline_id for record in registry.rule_semantic_map.records)
    )
    expected_semantic_refs = tuple(
        sorted({record.semantic_family_ref for record in registry.rule_semantic_map.records})
    )
    expected_function_refs = tuple(
        sorted({record.settlement_function_ref for record in registry.rule_semantic_map.records})
    )
    expected_binding_ids = tuple(sorted(binding.binding_id for binding in atomic.bindings))
    property_suite_complete = (
        property_suite.result_status == "VERIFIED"
        and property_suite.property_check_count == 39
        and property_suite.active_catalog_projection_hash
        == registry.rule_semantic_map.active_catalog_projection_hash
        and property_suite.active_semantics_hash == registry.active_physical_semantics_hash
        and property_suite.rule_semantic_map_hash == registry.rule_semantic_map.content_hash
        and property_suite.settlement_function_set_hash
        == registry.settlement_function_set.content_hash
        and property_suite.registry_selection_manifest_hash
        == registry.expected_selection_domain.content_hash
        and property_suite.independent_selection_manifest_hash == independent.content_hash
        and property_suite.atomic_ticket_binding_hash == atomic.content_hash
        and property_suite.dataset_semantic_hash == world_snapshot.dataset_semantic_hash
        and property_suite.ordered_draw_input_digest
        == _ordered_json_stream_sha256(draw.content_hash for draw in world_snapshot.draw_inputs)
        and property_suite.representative_replay_hash == replay.content_hash
        and property_suite.source_hashes == _current_property_source_hashes()
        and property_suite.covered_baseline_ids == expected_baseline_ids
        and property_suite.covered_semantic_family_refs == expected_semantic_refs
        and property_suite.covered_settlement_function_refs == expected_function_refs
        and property_suite.covered_atomic_binding_ids == expected_binding_ids
        and all(
            check.result_status == "VERIFIED"
            and check.generated_draw_example_count >= 64
            and check.failure_count == 0
            for check in property_suite.checks
        )
    )
    fresh_world_matches = _common.content_equal(
        retained["EventMatrixSnapshot"], recomputed["EventMatrixSnapshot"]
    ) and _common.content_equal(retained["WorldSnapshot"], recomputed["WorldSnapshot"])
    # Pydantic validation of these very large retained objects is deliberately
    # after every 379,808-cell stream.  Keeping those pydantic-core objects live
    # while entering the Windows hot loop can terminate the interpreter; exact
    # recomputation above already fails closed before this final schema check.
    _common.validate_model_payloads(retained, ARTIFACT_MODELS, block_label="F1")
    lazy_proof = world_snapshot.lazy_domain_proof
    actuals = {
        "catalog_total_eq": len(roles),
        "family_total_eq": len(registry.rule_semantic_map.family_counts),
        "catalog_identity_mapped_eq": len(roles),
        "semantic_rule_mapped_eq": len(registry.rule_semantic_map.records),
        "active_settlement_compiled_eq": len(registry.settlement_function_set.bindings),
        "active_settlement_not_compiled_eq": (
            len(ACTIVE_SETTLEMENT_BASELINE_IDS) - len(registry.settlement_function_set.bindings)
        ),
        "unclassified_eq": len(roles) - sum(role_counts.values()),
        "draw_total_eq": final.get("draw_total"),
        "distinct_active_world_cells_eq": (event_snapshot.coverage.actual_functional_cell_count),
        "actual_event_key_set_equals_expected": keys_equal,
        "expected_selection_set_derived_independently_from_catalog_and_baseline": (
            comparison.exact_match
        ),
        "rule_semantic_map_selection_set_equals_independent_expected_selection_set": (
            comparison.exact_match
        ),
        "atomic_ticket_binding_count_eq": atomic.binding_count,
        "active_atomic_selection_count_eq": independent.exact_atomic_selection_count,
        "atomic_ticket_count_eq": atomic.exact_atomic_ticket_count,
        "atomic_ticket_domain_lazy_not_materialized": (
            atomic.materialized_atomic_ticket_count == 0
            and lazy_proof.materialized_atomic_ticket_key_count == 0
            and world_snapshot.expanded_atomic_ticket_keys_materialized is False
        ),
        "missing_event_keys_eq": missing_keys,
        "unexpected_event_keys_eq": unexpected_keys,
        "duplicate_event_keys_eq": duplicate_keys,
        "every_semantic_family_has_positive_negative_boundary_property_tests_and_replay": (
            family_replay_complete and property_suite_complete
        ),
        "required_rule_fields_complete": _common.required_rule_fields_actual(
            registry, REQUIRED_RULE_FIELDS
        ),
        "fresh_process_world_hash_equals_recorded": fresh_world_matches,
        "reordered_input_world_hash_equals_recorded": reordered_matches,
    }
    return _common.ensure_exact_actuals(actuals, expected_assertion_ids=ASSERTION_IDS)


__all__ = ["build_assertion_actuals_v1"]
