"""Derived F1-F4 foundation execution-readiness report.

The human specification and formal admission contract are authoritative.  The
current D-drive JSON is only a hash-bound machine projection.  Until a
versioned F1-F4 implementation model is admitted, this module must return
``NOT_PERFORMED`` and must never reopen the deprecated formal-research gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from xinao.canonical import canonical_dumps, canonical_sha256
from xinao.foundation.assertion_bundle_runner import (
    BUNDLE_SCHEMA_VERSION,
    PROTOCOL_VERSION,
    REQUEST_SCHEMA_VERSION,
    AssertionBundleRunnerError,
    build_assertion_request_v2,
    run_canonical_bundle_fresh,
)
from xinao.foundation.assertion_verifier_registry import (
    AUTHORITY_MANIFEST_SCHEMA_VERSION,
    CURRENT_FORMAL_CONTRACT_PATH,
    CURRENT_HUMAN_SPEC_PATH,
    FOUNDATION_BLOCK_IDS,
    CanonicalVerifierError,
    canonical_projection_path,
    canonical_verifier,
    validate_authority_snapshot,
)
from xinao.foundation.foundation_implementation_model import (
    FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
    foundation_implementation_model,
    foundation_profile,
    implementation_model_projection,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CURRENT_PROJECTION_SCHEMA_VERSION = "xinao.current-domain-research-blueprint.v1"
FOUNDATION_PROFILE_RESOLUTION_SCHEMA_VERSION = "xinao.foundation_profile_resolution.v1"
CURRENT_FOUNDATION_IDS = ("F1", "F2", "F3", "F4")
CURRENT_FOUNDATION_CANONICAL_NAMES = {
    "F1": "SettlementWorldFoundation",
    "F2": "IssuerSettlementCostSpaceFoundation",
    "F3": "ResearchWeightFoundation",
    "F4": "ResearchFactoryFoundation",
}
MISSING_IMPLEMENTATION_REQUIREMENTS = (
    "versioned_foundation_closure_implementation_model",
    "f1_f4_block_artifact_and_assertion_requirements",
    "current_foundation_input_hash_inventory",
    "foundation_closure_report_schema",
    "foundation_exclusions",
)

F1_ACTIVE_ARTIFACT_TYPES = frozenset(
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
F1_ACTIVE_BASELINE_IDS = frozenset(
    f"BO{number:04d}" for number in range(1, 434) if number not in {*range(13, 25), *range(30, 35)}
)
F1_FROZEN_ROUTE_QUOTE_IDS = frozenset(
    f"BO{number:04d}" for number in (*range(13, 25), *range(30, 35))
)
F1_ACTIVE_COMPONENT_COUNT = 416
F1_SELECTION_DOMAIN_SPEC_COUNT = 233
F1_DRAW_COUNT = 913
F1_ACTIVE_WORLD_CELL_COUNT = 379_808
F1_ACTIVE_ATOMIC_SELECTION_COUNT = 21_652_542_248
F1_ATOMIC_TICKET_BINDING_COUNT = 37
F1_ATOMIC_TICKET_COUNT = 21_652_539_822


class FoundationProfileUnavailable(ValueError):
    """Raised when current authority is bound but the runtime profile is not admitted."""

    def __init__(self, resolution: dict[str, Any]) -> None:
        self.resolution = resolution
        blockers = resolution.get("blockers")
        summary = ", ".join(str(item) for item in blockers) if isinstance(blockers, list) else ""
        super().__init__(f"NOT_PERFORMED: {summary or 'foundation profile unavailable'}")


def _resolved_declared_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def resolve_foundation_profile(projection_path: Path) -> dict[str, Any]:
    """Resolve the sealed code-owned profile through the current projection.

    The D-drive blueprint can only fingerprint the implementation model.  It
    cannot define inventories, set readiness, or reopen formal research.
    """

    blockers: list[str] = []
    try:
        canonical = canonical_projection_path(projection_path)
    except CanonicalVerifierError as exc:
        return {
            "schema_version": FOUNDATION_PROFILE_RESOLUTION_SCHEMA_VERSION,
            "status": "NOT_PERFORMED",
            "authority_binding_valid": False,
            "projection_ref": {},
            "human_spec_ref": {},
            "formal_contract_ref": {},
            "runtime_cutover": {},
            "missing_implementation_requirements": list(MISSING_IMPLEMENTATION_REQUIREMENTS),
            "blockers": [f"authority_projection_not_canonical:{exc}"],
        }

    try:
        value = json.loads(canonical.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        blockers.append(f"authority_projection_unreadable:{type(exc).__name__}")
        value = {}
    if not isinstance(value, dict):
        blockers.append("authority_projection_not_object")
        value = {}

    authority = value.get("authority")
    foundation = value.get("foundation")
    gates = value.get("gates")
    runtime_cutover = value.get("runtime_cutover")
    if not isinstance(authority, dict):
        blockers.append("authority_binding_missing")
        authority = {}
    if not isinstance(foundation, dict):
        blockers.append("foundation_projection_missing")
        foundation = {}
    if not isinstance(gates, dict):
        blockers.append("gate_projection_missing")
        gates = {}
    if not isinstance(runtime_cutover, dict):
        blockers.append("runtime_cutover_projection_missing")
        runtime_cutover = {}

    if value.get("schema_version") != CURRENT_PROJECTION_SCHEMA_VERSION:
        blockers.append("projection_schema_version_mismatch")
    if authority.get("projection_is_not_authority") is not True:
        blockers.append("projection_authority_boundary_missing")
    if authority.get("binding_role") != "non_authoritative_source_fingerprints":
        blockers.append("projection_binding_role_mismatch")

    spec_path = CURRENT_HUMAN_SPEC_PATH.resolve()
    contract_path = CURRENT_FORMAL_CONTRACT_PATH.resolve()
    if _resolved_declared_path(authority.get("human_spec")) != spec_path:
        blockers.append("human_spec_path_mismatch")
    if _resolved_declared_path(authority.get("formal_admission_contract")) != contract_path:
        blockers.append("formal_contract_path_mismatch")

    spec_ref: dict[str, Any] = {}
    contract_ref: dict[str, Any] = {}
    if not spec_path.is_file():
        blockers.append("human_spec_unavailable")
    else:
        spec_ref = evidence_ref(spec_path)
        if authority.get("human_spec_sha256") != spec_ref["sha256"]:
            blockers.append("human_spec_sha256_mismatch")
    if not contract_path.is_file():
        blockers.append("formal_contract_unavailable")
    else:
        contract_ref = evidence_ref(contract_path)
        if authority.get("formal_admission_contract_sha256") != contract_ref["sha256"]:
            blockers.append("formal_contract_sha256_mismatch")
        if gates.get("normative_contract_sha256") != contract_ref["sha256"]:
            blockers.append("gate_contract_sha256_mismatch")

    if foundation.get("ids") != list(CURRENT_FOUNDATION_IDS):
        blockers.append("foundation_id_set_mismatch")
    if foundation.get("canonical_names") != CURRENT_FOUNDATION_CANONICAL_NAMES:
        blockers.append("foundation_canonical_names_mismatch")
    if foundation.get("derived_state") != "FOUNDATION_EXECUTION_READY":
        blockers.append("foundation_derived_state_mismatch")
    if foundation.get("does_not_imply_formal_research") is not True:
        blockers.append("foundation_formal_research_boundary_missing")
    if gates.get("formal_autonomous_domain_research_decision_input") != (
        "valid DomainResearchAdmissionReport"
    ):
        blockers.append("formal_research_admission_input_mismatch")
    deprecated = gates.get("deprecated_gate_projection_read_only")
    if (
        not isinstance(deprecated, list)
        or not all(isinstance(item, str) for item in deprecated)
        or not {
            "FORMAL_RESEARCH_GATE",
            "formal_research_allowed",
        }.issubset(set(deprecated))
    ):
        blockers.append("deprecated_gate_read_only_projection_missing")

    authority_binding_valid = not blockers
    model = foundation_implementation_model()
    recorded_model_hash = model.get("content_sha256")
    model_body = dict(model)
    model_body.pop("content_sha256", None)
    if not _valid_sha256(recorded_model_hash) or canonical_sha256(model_body) != (
        recorded_model_hash
    ):
        blockers.append("implementation_model_content_hash_invalid")

    authority_binding = model.get("authority_binding")
    if not isinstance(authority_binding, dict):
        blockers.append("implementation_model_authority_binding_missing")
    else:
        if authority_binding.get("human_spec_sha256") != spec_ref.get("sha256"):
            blockers.append("implementation_model_human_spec_hash_mismatch")
        if authority_binding.get("formal_contract_sha256") != contract_ref.get("sha256"):
            blockers.append("implementation_model_formal_contract_hash_mismatch")

    model_blocks = model.get("blocks")
    if not isinstance(model_blocks, dict) or set(model_blocks) != set(FOUNDATION_BLOCK_IDS):
        blockers.append("implementation_model_block_inventory_invalid")
    else:
        for block_id in FOUNDATION_BLOCK_IDS:
            block = model_blocks.get(block_id)
            if not isinstance(block, dict) or set(block) != {
                "required_artifact_types",
                "required_assertion_ids",
                "required_assertions",
            }:
                blockers.append(f"implementation_model_block_shape_invalid:{block_id}")
                continue
            artifacts = block.get("required_artifact_types")
            assertions = block.get("required_assertion_ids")
            expectations = block.get("required_assertions")
            if (
                not isinstance(artifacts, list)
                or not artifacts
                or len(artifacts) != len(set(artifacts))
                or not all(isinstance(item, str) and item for item in artifacts)
                or not isinstance(assertions, list)
                or not assertions
                or len(assertions) != len(set(assertions))
                or not all(isinstance(item, str) and item for item in assertions)
                or not isinstance(expectations, dict)
                or set(expectations) != set(assertions)
            ):
                blockers.append(f"implementation_model_block_requirements_invalid:{block_id}")

    inventory = model.get("input_hash_inventory")
    if not isinstance(inventory, dict):
        blockers.append("implementation_model_input_hash_inventory_missing")
    else:
        required_keys = inventory.get("required_input_hash_keys")
        known_hashes = inventory.get("known_input_hashes")
        config_hash = inventory.get("config_hash")
        if (
            not isinstance(required_keys, list)
            or len(required_keys) != len(set(required_keys))
            or "compiler_code_sha256" not in required_keys
            or "compiler_config_sha256" not in required_keys
            or not isinstance(known_hashes, dict)
            or set(known_hashes) != set(required_keys) - {"compiler_code_sha256"}
            or not _valid_hash_map(known_hashes)
            or config_hash != known_hashes.get("compiler_config_sha256")
        ):
            blockers.append("implementation_model_input_hash_inventory_invalid")

    exclusions = model.get("foundation_exclusions")
    if (
        not isinstance(exclusions, list)
        or not exclusions
        or len(exclusions) != len(set(exclusions))
        or "formal_research_allowed" not in exclusions
        or "frozen_agent_route_quote" not in exclusions
        or "partial_slice_canary_or_local_report" not in exclusions
    ):
        blockers.append("implementation_model_exclusions_invalid")
    if model.get("required_report_schema_version") != (FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION):
        blockers.append("implementation_model_report_schema_mismatch")
    if model.get("does_not_imply_formal_research") is not True:
        blockers.append("implementation_model_formal_research_boundary_missing")

    expected_projection = implementation_model_projection()
    if runtime_cutover != expected_projection:
        blockers.append("implementation_model_projection_fingerprint_mismatch")

    status = "READY" if not blockers else "NOT_PERFORMED"

    return {
        "schema_version": FOUNDATION_PROFILE_RESOLUTION_SCHEMA_VERSION,
        "status": status,
        "authority_binding_valid": authority_binding_valid,
        "projection_ref": evidence_ref(canonical),
        "human_spec_ref": spec_ref,
        "formal_contract_ref": contract_ref,
        "foundation_projection": {
            "ids": foundation.get("ids"),
            "canonical_names": foundation.get("canonical_names"),
            "derived_state": foundation.get("derived_state"),
            "does_not_imply_formal_research": foundation.get("does_not_imply_formal_research"),
        },
        "runtime_cutover": dict(runtime_cutover),
        "implementation_model_ref": expected_projection,
        "missing_implementation_requirements": (
            [] if status == "READY" else list(MISSING_IMPLEMENTATION_REQUIREMENTS)
        ),
        "blockers": sorted(set(blockers)),
    }


def load_foundation_profile(blueprint_path: Path) -> dict[str, Any]:
    """Load the code-owned profile only through an exact current fingerprint."""

    resolution = resolve_foundation_profile(blueprint_path)
    if resolution.get("status") != "READY":
        raise FoundationProfileUnavailable(resolution)
    profile = foundation_profile()
    metadata = profile.get("_closure_meta")
    if (
        not isinstance(metadata, dict)
        or metadata.get("implementation_model_sha256")
        != resolution["implementation_model_ref"]["implementation_model_sha256"]
    ):
        raise FoundationProfileUnavailable(
            {
                **resolution,
                "status": "NOT_PERFORMED",
                "blockers": ["loaded_implementation_model_fingerprint_mismatch"],
            }
        )
    return profile


def evidence_ref(
    path: Path,
    *,
    artifact_type: str | None = None,
    assertion_id: str | None = None,
    input_hash_key: str | None = None,
) -> dict[str, Any]:
    """Create a content-bound evidence reference for one existing file."""

    resolved = path.resolve()
    raw = resolved.read_bytes()
    result: dict[str, Any] = {
        "path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    if artifact_type:
        result["artifact_type"] = artifact_type
    if assertion_id:
        result["assertion_id"] = assertion_id
    if input_hash_key:
        result["input_hash_key"] = input_hash_key
    return result


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _valid_hash_map(value: object, *, nonempty: bool = True) -> bool:
    if not isinstance(value, dict) or (nonempty and not value):
        return False
    return all(isinstance(key, str) and key and _valid_sha256(item) for key, item in value.items())


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_evidence_ref(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    raw_path = value.get("path")
    expected_hash = value.get("sha256")
    expected_size = value.get("size_bytes")
    if not isinstance(raw_path, str) or not _valid_sha256(expected_hash):
        return False
    path = Path(raw_path)
    if not path.is_file():
        return False
    raw = path.read_bytes()
    return (
        hashlib.sha256(raw).hexdigest() == expected_hash
        and isinstance(expected_size, int)
        and expected_size == len(raw)
    )


def _valid_evidence_refs(value: object) -> bool:
    return (
        isinstance(value, list) and bool(value) and all(_valid_evidence_ref(item) for item in value)
    )


def _load_evidence_object(value: dict[str, Any]) -> dict[str, Any] | None:
    try:
        loaded = json.loads(Path(value["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _valid_identity_list(value: object) -> tuple[bool, set[str]]:
    if not isinstance(value, list) or not value:
        return False, set()
    if not all(isinstance(item, str) and item for item in value):
        return False, set()
    identities = set(value)
    return len(identities) == len(value), identities


def _content_hash_is_bound(payload: dict[str, Any]) -> bool:
    recorded = payload.get("content_hash")
    if not _valid_sha256(recorded):
        return False
    body = dict(payload)
    body.pop("content_hash", None)
    return canonical_sha256(body) == recorded


def _contains_frozen_route_quote(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"physical_role", "catalog_role", "route_role"} and item == (
                "FROZEN_AGENT_ROUTE_QUOTE"
            ):
                return True
            if key == "baseline_id" and item in F1_FROZEN_ROUTE_QUOTE_IDS:
                return True
            if _contains_frozen_route_quote(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_frozen_route_quote(item) for item in value)
    return False


def _active_record_ids(value: object) -> set[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return None
    ids = [item.get("baseline_id") for item in value]
    if not all(isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
        return None
    return set(ids)


def _f1_artifact_facts(
    payloads: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Validate the ACTIVE-only F1 material and derive replayable count facts."""

    reasons: list[str] = []
    facts: dict[str, Any] = {}
    if set(payloads) != F1_ACTIVE_ARTIFACT_TYPES:
        return ["f1_active_artifact_payload_set_mismatch"], facts

    for artifact_type, payload in payloads.items():
        if not _content_hash_is_bound(payload):
            reasons.append(f"f1_artifact_content_hash_invalid:{artifact_type}")
        if _contains_frozen_route_quote(payload):
            reasons.append(f"f1_frozen_route_quote_entered_gate:{artifact_type}")

    semantic_map = payloads["RuleSemanticMapVersion"]
    semantic_records = semantic_map.get("records")
    semantic_ids = _active_record_ids(semantic_records)
    semantic_count = semantic_map.get("semantic_record_count")
    family_counts = semantic_map.get("family_counts")
    if (
        semantic_count != F1_ACTIVE_COMPONENT_COUNT
        or not isinstance(semantic_records, list)
        or len(semantic_records) != F1_ACTIVE_COMPONENT_COUNT
        or semantic_ids != F1_ACTIVE_BASELINE_IDS
        or any(item.get("physical_role") != "ACTIVE_SETTLEMENT" for item in semantic_records)
    ):
        reasons.append("f1_rule_semantic_map_not_exact_active_416")
    if (
        not isinstance(family_counts, dict)
        or len(family_counts) != 13
        or sum(item for item in family_counts.values() if isinstance(item, int))
        != F1_ACTIVE_COMPONENT_COUNT
        or not all(isinstance(item, int) and item > 0 for item in family_counts.values())
    ):
        reasons.append("f1_rule_semantic_map_family_partition_invalid")
    facts["semantic_rule_mapped_eq"] = semantic_count
    facts["family_total_eq"] = len(family_counts) if isinstance(family_counts, dict) else None

    rule_set = payloads["RuleSetVersion"]
    rules = rule_set.get("rules")
    rule_ids = _active_record_ids(rules)
    if (
        rule_set.get("rule_count") != F1_ACTIVE_COMPONENT_COUNT
        or not isinstance(rules, list)
        or len(rules) != F1_ACTIVE_COMPONENT_COUNT
        or rule_ids != F1_ACTIVE_BASELINE_IDS
        or any(item.get("physical_role") != "ACTIVE_SETTLEMENT" for item in rules)
        or rule_set.get("semantic_map_content_hash") != semantic_map.get("content_hash")
    ):
        reasons.append("f1_rule_set_not_bound_to_exact_active_416")

    function_set = payloads["SettlementFunctionSetVersion"]
    bindings = function_set.get("bindings")
    binding_ids = _active_record_ids(bindings)
    function_count = function_set.get("function_count")
    if (
        function_count != F1_ACTIVE_COMPONENT_COUNT
        or not isinstance(bindings, list)
        or len(bindings) != F1_ACTIVE_COMPONENT_COUNT
        or binding_ids != F1_ACTIVE_BASELINE_IDS
        or function_set.get("rule_set_content_hash") != rule_set.get("content_hash")
    ):
        reasons.append("f1_settlement_function_set_not_exact_active_416")
    facts["active_settlement_compiled_eq"] = function_count
    facts["active_settlement_not_compiled_eq"] = (
        F1_ACTIVE_COMPONENT_COUNT - function_count if isinstance(function_count, int) else None
    )

    manifest = payloads["ExpectedSelectionDomainManifestVersion"]
    specifications = manifest.get("specifications")
    component_ids: list[str] = []
    if isinstance(specifications, list):
        for specification in specifications:
            if not isinstance(specification, dict) or not isinstance(
                specification.get("component_baseline_ids"), list
            ):
                component_ids = []
                break
            component_ids.extend(specification["component_baseline_ids"])
    manifest_materialized_count = manifest.get(
        "canonical_materialized_atomic_selection_count",
        manifest.get("materialized_atomic_selection_count"),
    )
    if (
        manifest.get("component_catalog_row_count") != F1_ACTIVE_COMPONENT_COUNT
        or manifest.get("selection_domain_spec_count") != F1_SELECTION_DOMAIN_SPEC_COUNT
        or not isinstance(specifications, list)
        or len(specifications) != F1_SELECTION_DOMAIN_SPEC_COUNT
        or set(component_ids) != F1_ACTIVE_BASELINE_IDS
        or len(component_ids) != F1_ACTIVE_COMPONENT_COUNT
        or manifest.get("exact_atomic_selection_count") != F1_ACTIVE_ATOMIC_SELECTION_COUNT
        or manifest_materialized_count != 0
    ):
        reasons.append("f1_selection_manifest_not_exact_active_lazy_domain")
    facts["active_atomic_selection_count_eq"] = manifest.get("exact_atomic_selection_count")

    atomic = payloads["AtomicTicketBindingVersion"]
    atomic_bindings = atomic.get("bindings")
    if (
        atomic.get("binding_count") != F1_ATOMIC_TICKET_BINDING_COUNT
        or not isinstance(atomic_bindings, list)
        or len(atomic_bindings) != F1_ATOMIC_TICKET_BINDING_COUNT
        or atomic.get("exact_atomic_ticket_count") != F1_ATOMIC_TICKET_COUNT
        or atomic.get("materialized_atomic_ticket_count") != 0
    ):
        reasons.append("f1_atomic_ticket_binding_not_exact_active_lazy_domain")
    facts["atomic_ticket_binding_count_eq"] = atomic.get("binding_count")
    facts["atomic_ticket_count_eq"] = atomic.get("exact_atomic_ticket_count")

    event_matrix = payloads["EventMatrixSnapshot"]
    coverage = event_matrix.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    draw_count = coverage.get("draw_count")
    expected_cells = coverage.get("expected_functional_cell_count")
    actual_cells = coverage.get("actual_functional_cell_count")
    family_cell_counts = event_matrix.get("family_cell_counts")
    if (
        draw_count != F1_DRAW_COUNT
        or coverage.get("active_settlement_component_count") != F1_ACTIVE_COMPONENT_COUNT
        or expected_cells != F1_ACTIVE_WORLD_CELL_COUNT
        or actual_cells != F1_ACTIVE_WORLD_CELL_COUNT
        or not isinstance(family_cell_counts, dict)
        or sum(item for item in family_cell_counts.values() if isinstance(item, int))
        != F1_ACTIVE_WORLD_CELL_COUNT
    ):
        reasons.append("f1_event_matrix_not_exact_913_x_416_active_surface")
    facts["draw_total_eq"] = draw_count
    facts["distinct_active_world_cells_eq"] = actual_cells
    facts["actual_event_key_set_equals_expected"] = actual_cells == expected_cells

    world = payloads["WorldSnapshot"]
    draw_inputs = world.get("draw_inputs")
    lazy_proof = world.get("lazy_domain_proof")
    if not isinstance(lazy_proof, dict):
        lazy_proof = {}
    lazy_not_materialized = (
        world.get("expanded_atomic_ticket_keys_materialized") is False
        and lazy_proof.get("expanded_atomic_ticket_keys_materialized") is False
        and lazy_proof.get("materialized_atomic_ticket_key_count") == 0
        and lazy_proof.get("exact_conceptual_atomic_selection_count")
        == F1_ACTIVE_ATOMIC_SELECTION_COUNT
        and lazy_proof.get("composite_exact_atomic_ticket_count") == F1_ATOMIC_TICKET_COUNT
        and lazy_proof.get("atomic_ticket_binding_count") == F1_ATOMIC_TICKET_BINDING_COUNT
        and lazy_proof.get("component_baseline_count") == F1_ACTIVE_COMPONENT_COUNT
    )
    if (
        not isinstance(draw_inputs, list)
        or len(draw_inputs) != F1_DRAW_COUNT
        or world.get("event_matrix_snapshot_hash") != event_matrix.get("content_hash")
        or not lazy_not_materialized
    ):
        reasons.append("f1_world_not_bound_to_exact_active_lazy_surface")
    facts["atomic_ticket_domain_lazy_not_materialized"] = lazy_not_materialized

    return sorted(set(reasons)), facts


def _input_evidence_is_bound(
    evidence_refs: object,
    *,
    input_hashes: dict[str, str],
) -> bool:
    if not _valid_evidence_refs(evidence_refs):
        return False
    refs_by_key: dict[str, list[dict[str, Any]]] = {}
    for item in evidence_refs:
        key = item.get("input_hash_key")
        if not isinstance(key, str) or not key:
            return False
        refs_by_key.setdefault(key, []).append(item)
    if set(refs_by_key) != set(input_hashes):
        return False
    identities = [(str(item.get("path")), str(item.get("sha256"))) for item in evidence_refs]
    if len(set(identities)) != len(identities):
        return False
    return all(
        len(refs_by_key[key]) == 1 and refs_by_key[key][0]["sha256"] == expected_hash
        for key, expected_hash in input_hashes.items()
    )


def _same_evidence_ref(left: object, right: object) -> bool:
    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("path") == right.get("path")
        and left.get("sha256") == right.get("sha256")
        and left.get("size_bytes") == right.get("size_bytes")
    )


def _snapshot_entrypoint_identity(
    *,
    compiler_code_manifest_ref: object,
    compiler_code_entries: dict[str, dict[str, Any]],
    block_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not isinstance(compiler_code_manifest_ref, dict):
        return None
    try:
        canonical_entry = canonical_verifier(block_id)
        relative_path = f"xinao_discovery/src/{canonical_entry.relative_source}"
        manifest_entry = compiler_code_entries[f"source:{relative_path}"]
        snapshot_path = (
            Path(compiler_code_manifest_ref["path"]).parent
            / "sources"
            / Path(*relative_path.split("/"))
        )
        snapshot_ref = evidence_ref(snapshot_path)
    except (CanonicalVerifierError, KeyError, OSError, TypeError):
        return None
    if (
        manifest_entry.get("relative_path") != relative_path
        or manifest_entry.get("sha256") != canonical_entry.source_sha256
        or snapshot_ref.get("sha256") != manifest_entry.get("sha256")
        or snapshot_ref.get("size_bytes") != manifest_entry.get("size")
    ):
        return None
    metadata = {
        "module_name": canonical_entry.module_name,
        "live_source_path": str(canonical_entry.source_path),
        "authority_relative_path": relative_path,
        "source_sha256": canonical_entry.source_sha256,
        "checker_id": canonical_entry.checker_id,
        "checker_version": canonical_entry.checker_version,
    }
    return snapshot_ref, metadata


def _compiler_code_manifest(
    value: object,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    if not _valid_evidence_ref(value):
        return None, {}
    try:
        manifest_path = Path(value["path"])  # type: ignore[index]
        manifest = validate_authority_snapshot(manifest_path, require_live_match=True)
    except (CanonicalVerifierError, OSError, KeyError, TypeError):
        return None, {}
    if manifest.get("schema_version") != AUTHORITY_MANIFEST_SCHEMA_VERSION:
        return None, {}
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return None, {}
    by_role: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "role",
            "relative_path",
            "sha256",
            "size",
        }:
            return None, {}
        role = entry.get("role")
        relative_path = entry.get("relative_path")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("size")
        if (
            not isinstance(role, str)
            or not role
            or role in by_role
            or not isinstance(relative_path, str)
            or not relative_path
            or not _valid_sha256(expected_hash)
            or not isinstance(expected_size, int)
            or expected_size <= 0
        ):
            return None, {}
        path = manifest_path.parent / "sources" / Path(*relative_path.split("/"))
        if not path.is_file():
            return None, {}
        raw = path.read_bytes()
        if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_hash:
            return None, {}
        by_role[role] = entry
    return manifest, by_role


def _assertion_passes(
    assertion_id: str,
    value: object,
    *,
    block_id: str,
    expected_value: Any,
    report_input_hashes: dict[str, str],
    report_config_hash: str,
    artifact_source_hashes: dict[str, str],
    compiler_code_manifest_ref: object,
    compiler_code_entries: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    if not isinstance(value, dict):
        return False, f"assertion_not_object:{assertion_id}"
    if value.get("assertion_id") != assertion_id:
        return False, f"assertion_id_mismatch:{assertion_id}"
    if value.get("result") != "PASS":
        return False, f"assertion_not_pass:{assertion_id}"
    checker_id = value.get("checker_id")
    verifier_id = value.get("verifier_id")
    producer_ids = value.get("producer_ids")
    if not isinstance(checker_id, str) or not checker_id:
        return False, f"assertion_checker_missing:{assertion_id}"
    if not isinstance(verifier_id, str) or not verifier_id or verifier_id == checker_id:
        return False, f"assertion_verifier_not_independent:{assertion_id}"
    producers_valid, producer_set = _valid_identity_list(producer_ids)
    if not producers_valid:
        return False, f"assertion_producer_missing:{assertion_id}"
    if {checker_id, verifier_id} & producer_set:
        return False, f"assertion_roles_not_disjoint:{assertion_id}"
    checker_version = value.get("checker_version")
    checker_code_hash = value.get("checker_code_hash")
    try:
        canonical_entry = canonical_verifier(block_id)
    except CanonicalVerifierError:
        return False, f"assertion_canonical_checker_missing:{assertion_id}"
    if not isinstance(checker_version, str) or not checker_version:
        return False, f"assertion_checker_version_missing:{assertion_id}"
    if (
        checker_id != canonical_entry.checker_id
        or checker_version != canonical_entry.checker_version
        or checker_code_hash != canonical_entry.source_sha256
    ):
        return False, f"assertion_checker_not_canonical:{assertion_id}"
    if value.get("config_hash") != report_config_hash:
        return False, f"assertion_not_bound_to_config_hash:{assertion_id}"
    if value.get("input_hashes") != report_input_hashes:
        return False, f"assertion_input_hash_mismatch:{assertion_id}"
    assertion_evidence = value.get("evidence_refs")
    if not _valid_evidence_refs(assertion_evidence):
        return False, f"assertion_evidence_invalid:{assertion_id}"
    if len(assertion_evidence) != 1 or assertion_evidence[0].get("assertion_id") != assertion_id:
        return False, f"assertion_evidence_not_labeled:{assertion_id}"
    if value.get("output_hash") != assertion_evidence[0].get("sha256"):
        return False, f"assertion_output_not_bound_to_evidence:{assertion_id}"
    if value.get("artifact_source_hashes") != artifact_source_hashes:
        return False, f"assertion_artifact_source_hash_mismatch:{assertion_id}"
    if not _valid_timestamp(value.get("executed_at")):
        return False, f"assertion_timestamp_invalid:{assertion_id}"
    evidence_payload = _load_evidence_object(assertion_evidence[0])
    if (
        not isinstance(evidence_payload, dict)
        or evidence_payload.get("schema_version") != "xinao.closure_assertion_evidence.v3"
    ):
        return False, f"assertion_evidence_schema_mismatch:{assertion_id}"
    scalar_fields = {
        "assertion_id": assertion_id,
        "result": "PASS",
        "checker_id": checker_id,
        "checker_version": checker_version,
        "checker_code_hash": checker_code_hash,
        "config_hash": report_config_hash,
        "producer_ids": producer_ids,
        "verifier_id": verifier_id,
        "input_hashes": report_input_hashes,
        "artifact_source_hashes": artifact_source_hashes,
        "executed_at": value.get("executed_at"),
    }
    if any(evidence_payload.get(key) != item for key, item in scalar_fields.items()):
        return False, f"assertion_evidence_payload_mismatch:{assertion_id}"
    actual = evidence_payload.get("actual")
    if actual != evidence_payload.get("expected") or actual != expected_value:
        return False, f"assertion_actual_expected_mismatch:{assertion_id}"
    actual_content_hash = canonical_sha256({"assertion_id": assertion_id, "actual": actual})
    if (
        value.get("actual_content_sha256") != actual_content_hash
        or evidence_payload.get("actual_content_sha256") != actual_content_hash
    ):
        return False, f"assertion_actual_content_hash_mismatch:{assertion_id}"
    bundle_ref = evidence_payload.get("assertion_bundle_ref")
    fresh_bundle_ref = evidence_payload.get("fresh_assertion_bundle_ref")
    receipt_ref = evidence_payload.get("fresh_receipt_ref")
    manifest_ref = evidence_payload.get("compiler_code_manifest_ref")
    if not all(
        _valid_evidence_ref(item)
        for item in (bundle_ref, fresh_bundle_ref, receipt_ref, manifest_ref)
    ):
        return False, f"assertion_fresh_refs_invalid:{assertion_id}"
    if not _same_evidence_ref(manifest_ref, compiler_code_manifest_ref):
        return False, f"assertion_code_manifest_ref_mismatch:{assertion_id}"
    try:
        stored_bytes = Path(bundle_ref["path"]).read_bytes()
        fresh_bytes = Path(fresh_bundle_ref["path"]).read_bytes()
    except (OSError, KeyError, TypeError):
        return False, f"assertion_bundle_unreadable:{assertion_id}"
    if stored_bytes != fresh_bytes:
        return False, f"assertion_bundle_fresh_mismatch:{assertion_id}"
    bundle = _load_evidence_object(bundle_ref)
    if not isinstance(bundle, dict):
        return False, f"assertion_bundle_invalid:{assertion_id}"
    bundle_core = {key: item for key, item in bundle.items() if key != "content_sha256"}
    bundle_content_hash = bundle.get("content_sha256")
    actuals = bundle.get("assertion_actuals")
    actual_hashes = bundle.get("assertion_actual_content_sha256")
    entrypoint = bundle.get("entrypoint")
    if (
        bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION
        or bundle.get("protocol_version") != PROTOCOL_VERSION
        or bundle.get("block_id") != block_id
        or not _valid_sha256(bundle_content_hash)
        or canonical_sha256(bundle_core) != bundle_content_hash
        or evidence_payload.get("assertion_bundle_content_sha256") != bundle_content_hash
        or value.get("assertion_bundle_content_sha256") != bundle_content_hash
        or not isinstance(actuals, dict)
        or actuals.get(assertion_id) != actual
        or not isinstance(actual_hashes, dict)
        or actual_hashes.get(assertion_id) != actual_content_hash
        or not isinstance(entrypoint, dict)
        or entrypoint.get("module_name") != canonical_entry.module_name
        or entrypoint.get("source_path") != str(canonical_entry.source_path)
        or entrypoint.get("source_sha256") != checker_code_hash
        or entrypoint.get("checker_id") != checker_id
        or entrypoint.get("checker_version") != checker_version
    ):
        return False, f"assertion_bundle_payload_mismatch:{assertion_id}"
    receipt = _load_evidence_object(receipt_ref)
    snapshot_entrypoint = _snapshot_entrypoint_identity(
        compiler_code_manifest_ref=compiler_code_manifest_ref,
        compiler_code_entries=compiler_code_entries,
        block_id=block_id,
    )
    if snapshot_entrypoint is None:
        return False, f"assertion_snapshot_entrypoint_missing:{assertion_id}"
    snapshot_source_ref, canonical_entrypoint = snapshot_entrypoint
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != "xinao.fresh_assertion_bundle_receipt.v3"
        or receipt.get("protocol_version") != PROTOCOL_VERSION
        or receipt.get("block_id") != block_id
        or receipt.get("double_fresh_bytes_equal") is not True
        or not _same_evidence_ref(receipt.get("first_bundle_ref"), bundle_ref)
        or not _same_evidence_ref(receipt.get("second_bundle_ref"), fresh_bundle_ref)
        or not _same_evidence_ref(
            receipt.get("compiler_code_manifest_ref"), compiler_code_manifest_ref
        )
        or not _valid_evidence_ref(receipt.get("request_ref"))
        or not _valid_evidence_ref(receipt.get("entrypoint_source_ref"))
        or not _same_evidence_ref(receipt.get("entrypoint_source_ref"), snapshot_source_ref)
        or receipt.get("canonical_entrypoint") != canonical_entrypoint
    ):
        return False, f"assertion_fresh_receipt_mismatch:{assertion_id}"
    request = _load_evidence_object(receipt["request_ref"])
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != REQUEST_SCHEMA_VERSION
        or request.get("protocol_version") != PROTOCOL_VERSION
        or request.get("block_id") != block_id
        or "expected" in request
        or "required_assertions" in request
        or bundle.get("request_sha256") != canonical_sha256(request)
    ):
        return False, f"assertion_request_mismatch:{assertion_id}"
    return True, ""


def _canonical_projection_binding(report_input: dict[str, Any], *, blueprint_path: Path) -> bool:
    try:
        canonical = canonical_projection_path(blueprint_path)
    except CanonicalVerifierError:
        return False
    projection_ref = report_input.get("authority_projection_ref")
    if not _valid_evidence_ref(projection_ref):
        return False
    return _same_evidence_ref(projection_ref, evidence_ref(canonical))


def _input_refs_by_key(
    value: object, *, input_hashes: dict[str, str]
) -> dict[str, dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    result: dict[str, dict[str, Any]] = {}
    for ref in value:
        if not isinstance(ref, dict) or not _valid_evidence_ref(ref):
            return None
        key = ref.get("input_hash_key")
        if not isinstance(key, str) or key in result or key not in input_hashes:
            return None
        if ref.get("sha256") != input_hashes[key]:
            return None
        result[key] = ref
    return result if set(result) == set(input_hashes) else None


def _source_materials_are_pack_local(
    *,
    authority_manifest_ref: object,
    input_refs: dict[str, dict[str, Any]] | None,
    raw_blocks: dict[str, Any],
) -> bool:
    if not isinstance(authority_manifest_ref, dict) or input_refs is None:
        return False
    try:
        manifest_path = Path(authority_manifest_ref["path"])
        if not manifest_path.is_absolute():
            return False
        manifest_path = manifest_path.resolve(strict=True)
        if manifest_path.parent.name != "authority_snapshot":
            return False
        pack_root = manifest_path.parent.parent
        source_root = pack_root / "source_materials"
        input_root = source_root / "inputs"
        artifact_root = source_root / "artifacts"
        if not input_root.is_dir() or not artifact_root.is_dir():
            return False
        expected_paths: set[Path] = set()
        for key, ref in input_refs.items():
            if key == "compiler_code_sha256":
                if not _same_evidence_ref(ref, authority_manifest_ref):
                    return False
                continue
            raw_path = ref.get("path")
            if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                return False
            path = Path(raw_path).resolve(strict=True)
            if path.parent != input_root.resolve(strict=True):
                return False
            expected_paths.add(path)
        for block_id in FOUNDATION_BLOCK_IDS:
            raw_block = raw_blocks.get(block_id)
            if not isinstance(raw_block, dict):
                return False
            refs = raw_block.get("evidence_refs")
            if not isinstance(refs, list):
                return False
            expected_parent = (artifact_root / block_id).resolve(strict=True)
            for ref in refs:
                envelope = _load_evidence_object(ref) if isinstance(ref, dict) else None
                source_ref = envelope.get("source_ref") if isinstance(envelope, dict) else None
                if not _valid_evidence_ref(source_ref):
                    return False
                raw_path = source_ref.get("path")
                if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                    return False
                path = Path(raw_path).resolve(strict=True)
                if path.parent != expected_parent:
                    return False
                expected_paths.add(path)
        actual_paths = {
            path.resolve(strict=True) for path in source_root.rglob("*") if path.is_file()
        }
        if actual_paths != expected_paths:
            return False
        identities = {str(path).casefold() for path in actual_paths}
        return len(identities) == len(actual_paths)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _canonical_replay_block(
    block_id: str,
    raw_block: object,
    *,
    profile_block: dict[str, Any],
    input_refs: dict[str, dict[str, Any]],
    input_hashes: dict[str, str],
    code_hash: str,
    config_hash: str,
    authority_manifest_ref: object,
) -> tuple[bool, str]:
    if not isinstance(raw_block, dict):
        return False, "canonical_replay_block_missing"
    if not _valid_evidence_ref(authority_manifest_ref):
        return False, "canonical_replay_authority_snapshot_missing"
    authority_manifest_path = Path(authority_manifest_ref["path"])
    artifact_refs = raw_block.get("evidence_refs")
    assertion_results = raw_block.get("assertion_results")
    if not isinstance(artifact_refs, list) or not isinstance(assertion_results, dict):
        return False, "canonical_replay_evidence_missing"
    materials: dict[str, dict[str, Any]] = {}
    for ref in artifact_refs:
        if not isinstance(ref, dict) or not _valid_evidence_ref(ref):
            return False, "canonical_replay_artifact_ref_invalid"
        artifact_type = ref.get("artifact_type")
        envelope = _load_evidence_object(ref)
        if (
            not isinstance(artifact_type, str)
            or not isinstance(envelope, dict)
            or envelope.get("artifact_type") != artifact_type
            or not isinstance(envelope.get("version"), str)
            or not isinstance(envelope.get("payload"), dict)
            or not isinstance(envelope.get("source_ref"), dict)
        ):
            return False, "canonical_replay_artifact_envelope_invalid"
        materials[artifact_type] = {
            "version": envelope["version"],
            "payload": envelope["payload"],
            "source_ref": envelope["source_ref"],
        }
    required_artifacts = set(profile_block.get("required_artifact_types") or [])
    required_assertions = sorted(profile_block.get("required_assertion_ids") or [])
    if set(materials) != required_artifacts or set(assertion_results) != set(required_assertions):
        return False, "canonical_replay_inventory_mismatch"
    request = build_assertion_request_v2(
        block_id=block_id,
        assertion_ids=required_assertions,
        input_refs=input_refs,
        input_hashes=input_hashes,
        materials=materials,
        compiler_code_sha256=code_hash,
        compiler_config_sha256=config_hash,
    )
    bundle_pairs: set[tuple[str, str, str, str]] = set()
    request_refs: set[tuple[str, str, int]] = set()
    for assertion in assertion_results.values():
        if not isinstance(assertion, dict):
            return False, "canonical_replay_assertion_invalid"
        refs = assertion.get("evidence_refs")
        if not isinstance(refs, list) or len(refs) != 1:
            return False, "canonical_replay_assertion_evidence_invalid"
        payload = _load_evidence_object(refs[0]) if isinstance(refs[0], dict) else None
        if not isinstance(payload, dict):
            return False, "canonical_replay_assertion_payload_invalid"
        first_ref = payload.get("assertion_bundle_ref")
        second_ref = payload.get("fresh_assertion_bundle_ref")
        receipt_ref = payload.get("fresh_receipt_ref")
        if not all(_valid_evidence_ref(item) for item in (first_ref, second_ref, receipt_ref)):
            return False, "canonical_replay_bundle_refs_invalid"
        receipt = _load_evidence_object(receipt_ref)  # type: ignore[arg-type]
        if not isinstance(receipt, dict) or not _valid_evidence_ref(receipt.get("request_ref")):
            return False, "canonical_replay_receipt_invalid"
        request_ref = receipt["request_ref"]
        request_refs.add(
            (str(request_ref["path"]), str(request_ref["sha256"]), int(request_ref["size_bytes"]))
        )
        bundle_pairs.add(
            (
                str(first_ref["path"]),
                str(first_ref["sha256"]),
                str(second_ref["path"]),
                str(second_ref["sha256"]),
            )
        )
    if len(bundle_pairs) != 1 or len(request_refs) != 1:
        return False, "canonical_replay_refs_not_block_unique"
    stored_request = _load_evidence_object(
        {
            "path": next(iter(request_refs))[0],
            "sha256": next(iter(request_refs))[1],
            "size_bytes": next(iter(request_refs))[2],
        }
    )
    if stored_request != request:
        return False, "canonical_replay_request_not_reconstructed"
    pair = next(iter(bundle_pairs))
    first_bytes = Path(pair[0]).read_bytes()
    second_bytes = Path(pair[2]).read_bytes()
    if first_bytes != second_bytes:
        return False, "canonical_replay_retained_bundles_differ"
    temp_root = Path(r"D:\XINAO_RESEARCH_RUNTIME\tmp\foundation-closure-replay")
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=temp_root) as raw_temp:
            temp = Path(raw_temp)
            request_path = temp / f"{block_id}.request.json"
            output_path = temp / f"{block_id}.bundle.json"
            request_path.write_bytes(canonical_dumps(request))
            validate_authority_snapshot(authority_manifest_path, require_live_match=True)
            try:
                run_canonical_bundle_fresh(
                    request_path=request_path,
                    block_id=block_id,
                    output_path=output_path,
                    timeout=600,
                )
            finally:
                validate_authority_snapshot(authority_manifest_path, require_live_match=True)
            replay_bytes = output_path.read_bytes()
    except (AssertionBundleRunnerError, CanonicalVerifierError, OSError) as exc:
        return False, f"canonical_replay_execution_failed:{type(exc).__name__}"
    if replay_bytes != first_bytes:
        return False, "canonical_replay_fresh_bundle_mismatch"
    return True, ""


def _derive_block(
    block_id: str,
    raw: object,
    *,
    profile_block: dict[str, Any],
    report_input_hashes: dict[str, str],
    report_code_hash: str,
    report_config_hash: str,
    compiler_code_manifest_ref: object,
    compiler_code_entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    artifact_versions = source.get("artifact_versions")
    artifact_hashes = source.get("artifact_hashes")
    assertion_results = source.get("assertion_results")
    producer_ids = source.get("producer_ids")
    verifier_id = source.get("verifier_id")
    evidence_refs = source.get("evidence_refs")
    reasons: list[str] = []

    if source.get("block_id") != block_id:
        reasons.append("block_id_mismatch")

    required_artifacts = set(profile_block.get("required_artifact_types") or [])
    required_assertions = set(profile_block.get("required_assertion_ids") or [])
    required_assertion_values = profile_block.get("required_assertions")
    if not isinstance(required_assertion_values, dict) or set(required_assertion_values) != (
        required_assertions
    ):
        reasons.append("required_assertion_expectations_invalid")
        required_assertion_values = {}
    version_keys = set(artifact_versions) if isinstance(artifact_versions, dict) else set()
    hash_keys = set(artifact_hashes) if isinstance(artifact_hashes, dict) else set()
    if not required_artifacts or required_artifacts != version_keys:
        reasons.append("required_artifact_set_mismatch")
    if block_id == "F1_settlement_world" and required_artifacts != F1_ACTIVE_ARTIFACT_TYPES:
        reasons.append("f1_required_artifact_inventory_not_active_canonical")
    if not isinstance(artifact_versions, dict) or not all(
        isinstance(item, str) and item for item in artifact_versions.values()
    ):
        reasons.append("artifact_versions_invalid")
    if hash_keys != version_keys or not _valid_hash_map(artifact_hashes):
        reasons.append("artifact_hashes_invalid_or_unbound")
    if source.get("input_hashes") != report_input_hashes:
        reasons.append("block_input_hash_mismatch")
    if not _valid_evidence_refs(evidence_refs):
        reasons.append("block_evidence_invalid")
        evidence_by_artifact: dict[str, list[dict[str, Any]]] = {}
    else:
        evidence_by_artifact = {}
        for item in evidence_refs:
            artifact_type = item.get("artifact_type")
            if not isinstance(artifact_type, str) or not artifact_type:
                reasons.append("block_evidence_not_artifact_labeled")
                continue
            evidence_by_artifact.setdefault(artifact_type, []).append(item)
        if set(evidence_by_artifact) != version_keys:
            reasons.append("block_evidence_artifact_set_mismatch")
        content_identities = {
            (str(item.get("path")), str(item.get("sha256"))) for item in evidence_refs
        }
        if len(content_identities) != len(evidence_refs):
            reasons.append("block_artifact_evidence_reused")
    artifact_payloads: dict[str, dict[str, Any]] = {}
    artifact_source_hashes: dict[str, str] = {}
    artifact_source_identities: list[tuple[str, str]] = []
    for artifact_type in version_keys:
        refs = evidence_by_artifact.get(artifact_type, [])
        expected_hash = (
            artifact_hashes.get(artifact_type) if isinstance(artifact_hashes, dict) else None
        )
        if len(refs) != 1 or refs[0].get("sha256") != expected_hash:
            reasons.append(f"artifact_not_bound_to_evidence:{artifact_type}")
            continue
        artifact_payload = _load_evidence_object(refs[0])
        if artifact_payload is None:
            reasons.append(f"artifact_evidence_payload_mismatch:{artifact_type}")
            continue
        metadata_matches = all(
            (
                artifact_payload.get("artifact_type") == artifact_type,
                artifact_payload.get("version") == artifact_versions[artifact_type],
                artifact_payload.get("input_hashes") == report_input_hashes,
                artifact_payload.get("code_hash") == report_code_hash,
                artifact_payload.get("config_hash") == report_config_hash,
            )
        )
        payload = artifact_payload.get("payload")
        payload_sha256 = artifact_payload.get("payload_sha256")
        payload_is_bound = (
            isinstance(payload, dict)
            and bool(payload)
            and _valid_sha256(payload_sha256)
            and canonical_sha256(payload) == payload_sha256
        )
        source_ref = artifact_payload.get("source_ref")
        source_ref_valid = (
            _valid_evidence_ref(source_ref)
            and isinstance(source_ref, dict)
            and source_ref.get("artifact_type") == artifact_type
            and source_ref.get("path") != refs[0].get("path")
        )
        source_payload = _load_evidence_object(source_ref) if source_ref_valid else None
        source_is_bound = source_payload == payload
        if not metadata_matches or not payload_is_bound or not source_is_bound:
            reasons.append(f"artifact_evidence_payload_mismatch:{artifact_type}")
            continue
        artifact_payloads[artifact_type] = payload
        artifact_source_hashes[artifact_type] = str(source_ref["sha256"])
        artifact_source_identities.append(
            (str(source_ref.get("path")), str(source_ref.get("sha256")))
        )
    if len(set(artifact_source_identities)) != len(artifact_source_identities):
        reasons.append("block_artifact_source_evidence_reused")

    f1_facts: dict[str, Any] = {}
    if block_id == "F1_settlement_world":
        f1_reasons, f1_facts = _f1_artifact_facts(artifact_payloads)
        reasons.extend(f1_reasons)
    producers_valid, producer_set = _valid_identity_list(producer_ids)
    if not producers_valid:
        reasons.append("block_producer_missing")
    if not isinstance(verifier_id, str) or not verifier_id or verifier_id in producer_set:
        reasons.append("block_verifier_not_independent")

    assertion_map = assertion_results if isinstance(assertion_results, dict) else {}
    if set(assertion_map) != required_assertions or not required_assertions:
        reasons.append("required_assertion_set_mismatch")
    assertion_checkers: set[str] = set()
    for assertion_id in sorted(required_assertions):
        passed, reason = _assertion_passes(
            assertion_id,
            assertion_map.get(assertion_id),
            block_id=block_id,
            expected_value=required_assertion_values.get(assertion_id),
            report_input_hashes=report_input_hashes,
            report_config_hash=report_config_hash,
            artifact_source_hashes=artifact_source_hashes,
            compiler_code_manifest_ref=compiler_code_manifest_ref,
            compiler_code_entries=compiler_code_entries,
        )
        if not passed:
            reasons.append(reason)
        else:
            assertion_checkers.add(str(assertion_map[assertion_id]["checker_id"]))
            if assertion_map[assertion_id].get("producer_ids") != producer_ids:
                reasons.append(f"assertion_producer_not_block_producer:{assertion_id}")
            if assertion_map[assertion_id].get("verifier_id") != verifier_id:
                reasons.append(f"assertion_verifier_not_block_verifier:{assertion_id}")
        if assertion_id in f1_facts and canonical_sha256(
            f1_facts[assertion_id]
        ) != canonical_sha256(required_assertion_values.get(assertion_id)):
            reasons.append(f"f1_assertion_not_derived_from_artifacts:{assertion_id}")
    if isinstance(verifier_id, str) and verifier_id in assertion_checkers:
        reasons.append("block_verifier_reused_as_assertion_checker")

    return {
        "block_id": block_id,
        "status": "VERIFIED" if not reasons else "PARTIAL",
        "artifact_versions": artifact_versions if isinstance(artifact_versions, dict) else {},
        "artifact_hashes": artifact_hashes if isinstance(artifact_hashes, dict) else {},
        "input_hashes": source.get("input_hashes")
        if isinstance(source.get("input_hashes"), dict)
        else {},
        "assertion_results": assertion_map,
        "evidence_refs": evidence_refs if isinstance(evidence_refs, list) else [],
        "producer_ids": producer_ids if isinstance(producer_ids, list) else [],
        "verifier_id": verifier_id if isinstance(verifier_id, str) else "",
        "failure_reasons": sorted(set(reasons)),
    }


def _not_performed_closure_report(
    report_input: dict[str, Any], *, resolution: dict[str, Any]
) -> dict[str, Any]:
    block_reports = {
        block_id: {
            "block_id": block_id,
            "status": "NOT_PERFORMED",
            "artifact_versions": {},
            "artifact_hashes": {},
            "input_hashes": {},
            "assertion_results": {},
            "evidence_refs": [],
            "producer_ids": [],
            "verifier_id": "",
            "failure_reasons": ["foundation_implementation_profile_not_admitted"],
        }
        for block_id in FOUNDATION_BLOCK_IDS
    }
    report: dict[str, Any] = {
        "schema_version": FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        "report_id": report_input.get("report_id") or "",
        "version": report_input.get("version") or "",
        "created_at": report_input.get("created_at") or "",
        "authority_projection_ref": resolution.get("projection_ref") or {},
        "authority_profile_resolution": resolution,
        "status": "NOT_PERFORMED",
        "blockers": list(resolution.get("blockers") or []),
        "input_hashes": {},
        "code_hash": "",
        "config_hash": "",
        "compiler_code_manifest_ref": {},
        "authority_snapshot_manifest_ref": {},
        "block_reports": block_reports,
        "evidence_refs": [],
        "producer_ids": [],
        "independent_verifier_id": "",
        "bindings_complete": False,
        "canonical_projection_bound": resolution.get("authority_binding_valid") is True,
        "authority_snapshot_bound": False,
        "source_materials_self_contained": False,
        "canonical_bundle_replay_verified": False,
        "all_required_assertions_pass": False,
        "foundation_execution_ready": False,
        "foundation_closed": False,
        "formal_research_allowed": False,
        "formal_research_gate": "CLOSED",
        "legacy_a_g_gate_used": False,
        "manual_override_used": False,
    }
    report["artifact_hash"] = canonical_sha256(report)
    return report


def derive_foundation_closure_report(
    report_input: dict[str, Any],
    *,
    blueprint_path: Path,
) -> dict[str, Any]:
    """Derive F1-F4 execution readiness without opening formal research."""

    resolution = resolve_foundation_profile(blueprint_path)
    if resolution.get("status") != "READY":
        return _not_performed_closure_report(report_input, resolution=resolution)
    profile = load_foundation_profile(blueprint_path)
    profile_blocks = profile.get("blocks")
    if not isinstance(profile_blocks, dict) or set(profile_blocks) != set(FOUNDATION_BLOCK_IDS):
        raise ValueError("profile must define exactly the required F1-F4 blocks")
    closure_meta = profile.get("_closure_meta")
    if not isinstance(closure_meta, dict):
        raise ValueError("profile is missing blueprint-derived closure metadata")
    required_input_hash_keys = closure_meta.get("required_input_hash_keys")
    known_input_hashes = closure_meta.get("known_input_hashes")
    expected_config_hash = closure_meta.get("config_hash")
    if (
        not isinstance(required_input_hash_keys, list)
        or not all(isinstance(item, str) and item for item in required_input_hash_keys)
        or not isinstance(known_input_hashes, dict)
        or not _valid_sha256(expected_config_hash)
    ):
        raise ValueError("profile closure metadata is invalid")
    input_hashes = report_input.get("input_hashes")
    if not isinstance(input_hashes, dict):
        input_hashes = {}
    code_hash = report_input.get("code_hash")
    config_hash = report_input.get("config_hash")
    report_evidence = report_input.get("evidence_refs")
    canonical_projection_bound = _canonical_projection_binding(
        report_input, blueprint_path=blueprint_path
    )
    input_keys_exact = set(input_hashes) == set(required_input_hash_keys)
    known_inputs_match = all(
        input_hashes.get(key) == expected_hash for key, expected_hash in known_input_hashes.items()
    )
    code_hash_bound = (
        _valid_sha256(code_hash) and input_hashes.get("compiler_code_sha256") == code_hash
    )
    config_hash_bound = (
        _valid_sha256(config_hash)
        and config_hash == expected_config_hash
        and input_hashes.get("compiler_config_sha256") == config_hash
    )
    compiler_code_manifest_ref = report_input.get("compiler_code_manifest_ref")
    authority_snapshot_manifest_ref = report_input.get("authority_snapshot_manifest_ref")
    compiler_code_manifest, compiler_code_entries = _compiler_code_manifest(
        compiler_code_manifest_ref
    )
    compiler_code_manifest_bound = (
        compiler_code_manifest is not None
        and isinstance(compiler_code_manifest_ref, dict)
        and compiler_code_manifest_ref.get("sha256") == code_hash
    )
    authority_snapshot_bound = _same_evidence_ref(
        authority_snapshot_manifest_ref, compiler_code_manifest_ref
    )
    input_refs = _input_refs_by_key(report_evidence, input_hashes=input_hashes)
    code_manifest_input_bound = (
        input_refs is not None
        and isinstance(compiler_code_manifest_ref, dict)
        and _same_evidence_ref(input_refs.get("compiler_code_sha256"), compiler_code_manifest_ref)
    )
    raw_blocks = report_input.get("block_reports")
    if not isinstance(raw_blocks, dict):
        raw_blocks = {}
    source_materials_self_contained = _source_materials_are_pack_local(
        authority_manifest_ref=authority_snapshot_manifest_ref,
        input_refs=input_refs,
        raw_blocks=raw_blocks,
    )
    blocks = {
        block_id: _derive_block(
            block_id,
            raw_blocks.get(block_id),
            profile_block=profile_blocks[block_id],
            report_input_hashes=input_hashes,
            report_code_hash=code_hash if isinstance(code_hash, str) else "",
            report_config_hash=config_hash if isinstance(config_hash, str) else "",
            compiler_code_manifest_ref=compiler_code_manifest_ref,
            compiler_code_entries=compiler_code_entries,
        )
        for block_id in FOUNDATION_BLOCK_IDS
    }

    canonical_replay_results: dict[str, bool] = {
        block_id: False for block_id in FOUNDATION_BLOCK_IDS
    }
    replay_prerequisites = all(
        (
            canonical_projection_bound,
            input_refs is not None,
            code_hash_bound,
            config_hash_bound,
            compiler_code_manifest_bound,
            authority_snapshot_bound,
            code_manifest_input_bound,
            source_materials_self_contained,
            set(raw_blocks) == set(FOUNDATION_BLOCK_IDS),
        )
    )
    for block_id in FOUNDATION_BLOCK_IDS:
        if replay_prerequisites and not blocks[block_id]["failure_reasons"]:
            replay_ok, replay_reason = _canonical_replay_block(
                block_id,
                raw_blocks.get(block_id),
                profile_block=profile_blocks[block_id],
                input_refs=input_refs or {},
                input_hashes=input_hashes,
                code_hash=code_hash if isinstance(code_hash, str) else "",
                config_hash=config_hash if isinstance(config_hash, str) else "",
                authority_manifest_ref=authority_snapshot_manifest_ref,
            )
        else:
            replay_ok, replay_reason = False, "canonical_replay_prerequisites_failed"
        canonical_replay_results[block_id] = replay_ok
        if not replay_ok:
            blocks[block_id]["failure_reasons"] = sorted(
                set([*blocks[block_id]["failure_reasons"], replay_reason])
            )
            blocks[block_id]["status"] = "PARTIAL"

    producer_ids = report_input.get("producer_ids")
    report_producers_valid, producer_set = _valid_identity_list(producer_ids)
    independent_verifier = report_input.get("independent_verifier_id")
    all_producers = set(producer_set)
    all_checkers: set[str] = set()
    all_verifiers: set[str] = set()
    for raw_block in raw_blocks.values():
        if not isinstance(raw_block, dict):
            continue
        valid, identities = _valid_identity_list(raw_block.get("producer_ids"))
        if valid:
            all_producers.update(identities)
        block_verifier = raw_block.get("verifier_id")
        if isinstance(block_verifier, str) and block_verifier:
            all_verifiers.add(block_verifier)
        raw_assertions = raw_block.get("assertion_results")
        if not isinstance(raw_assertions, dict):
            continue
        for assertion in raw_assertions.values():
            if not isinstance(assertion, dict):
                continue
            valid, identities = _valid_identity_list(assertion.get("producer_ids"))
            if valid:
                all_producers.update(identities)
            checker_id = assertion.get("checker_id")
            verifier_id = assertion.get("verifier_id")
            if isinstance(checker_id, str) and checker_id:
                all_checkers.add(checker_id)
            if isinstance(verifier_id, str) and verifier_id:
                all_verifiers.add(verifier_id)
    non_report_verifiers = set(all_verifiers)
    if isinstance(independent_verifier, str) and independent_verifier:
        all_verifiers.add(independent_verifier)
    role_categories_disjoint = not (
        all_producers & all_checkers
        or all_producers & all_verifiers
        or all_checkers & all_verifiers
    )
    report_verifier_globally_independent = (
        isinstance(independent_verifier, str)
        and bool(independent_verifier)
        and independent_verifier not in all_producers
        and independent_verifier not in all_checkers
        and independent_verifier not in non_report_verifiers
    )
    closure_path = Path(__file__).resolve()
    closure_hash = hashlib.sha256(closure_path.read_bytes()).hexdigest()
    pack_path = closure_path.with_name("closure_pack.py")
    pack_hash = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    expected_report_verifier = f"xinao.canonical.report-fresh-verifier.{closure_hash}"
    expected_report_producers = [f"xinao.canonical.closure-pack-producer.{pack_hash}"]
    fixed_report_identities = (
        independent_verifier == expected_report_verifier
        and producer_ids == expected_report_producers
    )
    fixed_block_identities = True
    for block_id in FOUNDATION_BLOCK_IDS:
        raw_block = raw_blocks.get(block_id)
        if not isinstance(raw_block, dict):
            fixed_block_identities = False
            continue
        artifact_source_hashes: dict[str, str] = {}
        for ref in raw_block.get("evidence_refs", []):
            envelope = _load_evidence_object(ref) if isinstance(ref, dict) else None
            if isinstance(envelope, dict) and isinstance(envelope.get("source_ref"), dict):
                artifact_type = envelope.get("artifact_type")
                source_sha = envelope["source_ref"].get("sha256")
                if isinstance(artifact_type, str) and isinstance(source_sha, str):
                    artifact_source_hashes[artifact_type] = source_sha
        expected_block_producers = [
            "xinao.canonical.artifact-producer."
            f"{block_id}.{canonical_sha256(artifact_source_hashes)}"
        ]
        expected_block_verifier = f"xinao.canonical.block-deriver.{block_id}.{closure_hash}"
        if (
            raw_block.get("producer_ids") != expected_block_producers
            or raw_block.get("verifier_id") != expected_block_verifier
        ):
            fixed_block_identities = False
    every_block_binding_complete = all(not block["failure_reasons"] for block in blocks.values())
    canonical_replay_complete = all(canonical_replay_results.values())
    artifact_evidence_identities: list[tuple[str, str]] = []
    assertion_evidence_identities: list[tuple[str, str]] = []
    for block in blocks.values():
        artifact_evidence_identities.extend(
            (str(item.get("path")), str(item.get("sha256")))
            for item in block["evidence_refs"]
            if isinstance(item, dict)
        )
        for assertion in block["assertion_results"].values():
            if not isinstance(assertion, dict):
                continue
            assertion_evidence_identities.extend(
                (str(item.get("path")), str(item.get("sha256")))
                for item in assertion.get("evidence_refs", [])
                if isinstance(item, dict)
            )
    evidence_objects_are_unique = (
        len(set(artifact_evidence_identities)) == len(artifact_evidence_identities)
        and len(set(assertion_evidence_identities)) == len(assertion_evidence_identities)
        and not set(artifact_evidence_identities) & set(assertion_evidence_identities)
    )
    bindings_complete = all(
        (
            isinstance(report_input.get("report_id"), str) and bool(report_input["report_id"]),
            isinstance(report_input.get("version"), str) and bool(report_input["version"]),
            _valid_timestamp(report_input.get("created_at")),
            _valid_hash_map(input_hashes),
            canonical_projection_bound,
            input_keys_exact,
            known_inputs_match,
            code_hash_bound,
            config_hash_bound,
            compiler_code_manifest_bound,
            authority_snapshot_bound,
            code_manifest_input_bound,
            source_materials_self_contained,
            _input_evidence_is_bound(report_evidence, input_hashes=input_hashes),
            report_producers_valid,
            report_verifier_globally_independent,
            role_categories_disjoint,
            fixed_report_identities,
            fixed_block_identities,
            evidence_objects_are_unique,
            set(raw_blocks) == set(FOUNDATION_BLOCK_IDS),
            every_block_binding_complete,
            canonical_replay_complete,
        )
    )
    all_required_assertions_pass = all(block["status"] == "VERIFIED" for block in blocks.values())
    verified = bindings_complete and all_required_assertions_pass
    report: dict[str, Any] = {
        "schema_version": FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION,
        "report_id": report_input.get("report_id") or "",
        "version": report_input.get("version") or "",
        "created_at": report_input.get("created_at") or "",
        "authority_projection_ref": report_input.get("authority_projection_ref")
        if isinstance(report_input.get("authority_projection_ref"), dict)
        else {},
        "status": "VERIFIED" if verified else "PARTIAL",
        "input_hashes": input_hashes,
        "code_hash": code_hash or "",
        "config_hash": config_hash or "",
        "compiler_code_manifest_ref": compiler_code_manifest_ref
        if isinstance(compiler_code_manifest_ref, dict)
        else {},
        "authority_snapshot_manifest_ref": authority_snapshot_manifest_ref
        if isinstance(authority_snapshot_manifest_ref, dict)
        else {},
        "block_reports": blocks,
        "evidence_refs": report_evidence if isinstance(report_evidence, list) else [],
        "producer_ids": list(producer_ids) if isinstance(producer_ids, list) else [],
        "independent_verifier_id": independent_verifier or "",
        "bindings_complete": bindings_complete,
        "canonical_projection_bound": canonical_projection_bound,
        "authority_snapshot_bound": authority_snapshot_bound,
        "source_materials_self_contained": source_materials_self_contained,
        "canonical_bundle_replay_verified": canonical_replay_complete,
        "all_required_assertions_pass": all_required_assertions_pass,
        "foundation_execution_ready": verified,
        "foundation_closed": False,
        "formal_research_allowed": False,
        "formal_research_gate": "CLOSED",
        "legacy_a_g_gate_used": False,
        "manual_override_used": False,
    }
    report["artifact_hash"] = canonical_sha256(report)
    return report


def verify_foundation_closure_report(
    report: dict[str, Any],
    *,
    blueprint_path: Path,
) -> dict[str, Any]:
    """Independently replay all derived fields and the report content hash."""

    resolution = resolve_foundation_profile(blueprint_path)
    if resolution.get("status") != "READY":
        schema_ok = report.get("schema_version") == FOUNDATION_CLOSURE_REPORT_SCHEMA_VERSION
        recorded_hash = report.get("artifact_hash")
        hash_body = dict(report)
        hash_body.pop("artifact_hash", None)
        hash_ok = _valid_sha256(recorded_hash) and canonical_sha256(hash_body) == recorded_hash
        rebuilt = _not_performed_closure_report(report, resolution=resolution)
        derived_fields = (
            "status",
            "blockers",
            "authority_projection_ref",
            "authority_profile_resolution",
            "bindings_complete",
            "canonical_projection_bound",
            "authority_snapshot_bound",
            "source_materials_self_contained",
            "canonical_bundle_replay_verified",
            "all_required_assertions_pass",
            "foundation_execution_ready",
            "foundation_closed",
            "formal_research_allowed",
            "formal_research_gate",
            "legacy_a_g_gate_used",
            "manual_override_used",
        )
        fields_ok = all(report.get(field) == rebuilt.get(field) for field in derived_fields)
        blocks_ok = report.get("block_reports") == rebuilt.get("block_reports")
        exact_top_level_keys = set(report) == set(rebuilt)
        report_replays_exactly = report == rebuilt
        ok = schema_ok and hash_ok and report_replays_exactly
        return {
            "schema_version": "xinao.foundation_closure_verification.v2",
            "ok": ok,
            "status": "NOT_PERFORMED",
            "checks": {
                "schema_version_matches": schema_ok,
                "artifact_hash_replays": hash_ok,
                "derived_report_fields_match": fields_ok,
                "block_derivations_match": blocks_ok,
                "exact_top_level_keys": exact_top_level_keys,
                "report_replays_exactly": report_replays_exactly,
                "authority_binding_valid": resolution.get("authority_binding_valid") is True,
                "formal_research_remains_closed": report.get("formal_research_allowed") is False,
                "legacy_a_g_gate_unused": report.get("legacy_a_g_gate_used") is False,
                "manual_override_unused": report.get("manual_override_used") is False,
            },
            "recorded_artifact_hash": recorded_hash,
            "recomputed_artifact_hash": canonical_sha256(hash_body),
            "foundation_execution_ready": False,
            "foundation_closed": False,
            "blockers": resolution.get("blockers") or [],
        }

    profile = load_foundation_profile(blueprint_path)
    closure_meta = profile.get("_closure_meta")
    expected_schema = (
        closure_meta.get("required_report_schema_version")
        if isinstance(closure_meta, dict)
        else None
    )
    schema_ok = report.get("schema_version") == expected_schema
    recorded_hash = report.get("artifact_hash")
    hash_body = dict(report)
    hash_body.pop("artifact_hash", None)
    hash_ok = _valid_sha256(recorded_hash) and canonical_sha256(hash_body) == recorded_hash
    rebuilt = derive_foundation_closure_report(report, blueprint_path=blueprint_path)
    derived_fields = (
        "status",
        "bindings_complete",
        "canonical_projection_bound",
        "authority_snapshot_bound",
        "source_materials_self_contained",
        "canonical_bundle_replay_verified",
        "all_required_assertions_pass",
        "foundation_execution_ready",
        "foundation_closed",
        "formal_research_allowed",
        "formal_research_gate",
        "legacy_a_g_gate_used",
        "manual_override_used",
    )
    fields_ok = all(report.get(field) == rebuilt.get(field) for field in derived_fields)
    blocks_ok = report.get("block_reports") == rebuilt.get("block_reports")
    exact_top_level_keys = set(report) == set(rebuilt)
    report_replays_exactly = report == rebuilt
    ok = schema_ok and hash_ok and report_replays_exactly
    return {
        "schema_version": "xinao.foundation_closure_verification.v1",
        "ok": ok,
        "checks": {
            "schema_version_matches": schema_ok,
            "artifact_hash_replays": hash_ok,
            "derived_report_fields_match": fields_ok,
            "block_derivations_match": blocks_ok,
            "exact_top_level_keys": exact_top_level_keys,
            "report_replays_exactly": report_replays_exactly,
            "legacy_a_g_gate_unused": report.get("legacy_a_g_gate_used") is False,
            "manual_override_unused": report.get("manual_override_used") is False,
        },
        "recorded_artifact_hash": recorded_hash,
        "recomputed_artifact_hash": canonical_sha256(hash_body),
        "foundation_execution_ready": report.get("foundation_execution_ready") is True and ok,
        "foundation_closed": False,
    }


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
