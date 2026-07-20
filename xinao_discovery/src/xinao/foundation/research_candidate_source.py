"""Deterministic 13-family candidate-source compiler for the formal F4 canary.

The compiler has no caller-provided candidate or ready-frontier input.  It
derives one work item per canonical ACTIVE family from verified, hash-bound
foundation objects and emits runtime-compatible read-only lane templates.
"""

from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from xinao.canonical import canonical_sha256, parse_utc
from xinao.foundation.research_factory import (
    ResearchWorkItem,
    ResearchWorkItemV3,
    admit_work_item,
    admit_work_item_v3,
    canonical_work_key,
    canonical_work_key_v3,
    parse_research_work_item,
    source_origin_index,
    source_projection_hash,
    validate_method_registry,
)
from xinao.foundation.research_weight import verify_versioned_object
from xinao.foundation.selection_manifest import (
    EXPECTED_ACTIVE_FAMILY_COUNTS,
    IndependentExpectedSelectionDomainManifestVersion,
)

QUESTION_SCHEMA_VERSION = "xinao.f4_canary_research_question.v1"
SNAPSHOT_SCHEMA_VERSION = "xinao.f4_canary_candidate_source_snapshot.v1"
GENERATOR_ID = "xinao.f4-canary-active-family-source.v1"
QUESTION_SCHEMA_VERSION_V3 = "xinao.f4_canary_research_question.v2"
SNAPSHOT_SCHEMA_VERSION_V3 = "xinao.f4_canary_candidate_source_snapshot.v2"
GENERATOR_ID_V3 = "xinao.f4-canary-active-family-source.v2"
CANDIDATE_SNAPSHOT_SCHEMA_VERSION_V3 = "xinao.research_candidate_snapshot.v3"
EXPECTED_FAMILY_IDS = tuple(sorted(EXPECTED_ACTIVE_FAMILY_COUNTS))

_SURFACE_SCHEMA_VERSION = "xinao.research-weight-foundation-object.v1"
_SURFACE_SEMANTIC_ROLE = "RESEARCH_RESOURCE_SHARE"
_SURFACE_STATES = frozenset({"ACTIVE", "WATCH", "TAIL", "DORMANT"})
_READ_TOOLS = ["read_file"]


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_knowledge_cutoff(value: str) -> None:
    if value.endswith("Z") and "." not in value:
        parse_utc(f"{value[:-1]}.000Z")
        return
    parse_utc(value)


def _versioned(object_type: str, schema_version: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    core = {
        "object_type": object_type,
        "schema_version": schema_version,
        "semantic_role": "F4_CANARY_CANDIDATE_SOURCE",
        **dict(payload),
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"{object_type}@{digest[:16]}",
        "content_sha256": digest,
    }


def _method_registry(
    value: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], str]:
    if set(value) == {"registrations"}:
        raw = value.get("registrations")
        if not isinstance(raw, Mapping):
            raise TypeError("method registry registrations must be an object")
    else:
        raw = value
    registrations: dict[str, Mapping[str, Any]] = {}
    for method_id, admission in raw.items():
        if not isinstance(method_id, str) or not isinstance(admission, Mapping):
            raise TypeError("method registry entries must be named objects")
        registrations[method_id] = admission
    normalized = validate_method_registry(registrations)
    canonical_input = {
        "registrations": {
            method_id: dict(registrations[method_id]) for method_id in sorted(registrations)
        }
    }
    return normalized, canonical_sha256(canonical_input)


def _manifest_family_components(
    manifest: IndependentExpectedSelectionDomainManifestVersion,
) -> dict[str, tuple[str, ...]]:
    components: defaultdict[str, set[str]] = defaultdict(set)
    for specification in manifest.specifications:
        components[specification.family_id].update(specification.component_baseline_ids)
    result = {family_id: tuple(sorted(components[family_id])) for family_id in sorted(components)}
    if tuple(result) != EXPECTED_FAMILY_IDS:
        raise ValueError("selection manifest does not contain the canonical 13 families")
    return result


def _active_surface_family_components(
    value: Mapping[str, Any],
    *,
    manifest_components: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    if (
        not verify_versioned_object(value)
        or value.get("object_type") != "ActiveResearchSurfaceVersion"
        or value.get("schema_version") != _SURFACE_SCHEMA_VERSION
        or value.get("semantic_role") != _SURFACE_SEMANTIC_ROLE
    ):
        raise ValueError("active research surface is not the verified F3 surface")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise TypeError("active research surface rows must be a list")
    observed: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("active research surface row must be an object")
        family_id = str(row.get("family_id") or "")
        raw_components = row.get("active_component_ids")
        if not family_id or family_id in observed or not isinstance(raw_components, list):
            raise ValueError("active research surface family identity is invalid")
        component_ids = tuple(map(str, raw_components))
        if component_ids != tuple(sorted(set(component_ids))) or not component_ids:
            raise ValueError("active research surface components must be nonempty and canonical")
        if row.get("active_component_count") != len(component_ids):
            raise ValueError("active research surface component count drifted")
        if row.get("surface_state") not in _SURFACE_STATES:
            raise ValueError("active research surface state is invalid")
        observed[family_id] = component_ids
    if tuple(sorted(observed)) != EXPECTED_FAMILY_IDS:
        raise ValueError("active research surface coverage is not exactly 13/13")
    if observed != dict(manifest_components):
        raise ValueError("active research surface does not match the canonical manifest partition")
    summary = value.get("summary")
    if not isinstance(summary, Mapping) or summary.get("family_count") != len(EXPECTED_FAMILY_IDS):
        raise ValueError("active research surface summary does not prove 13-family coverage")
    return observed


def _generator_source_sha256() -> str:
    return canonical_sha256(
        {
            "module": compile_f4_canary_candidate_source.__module__,
            "qualname": compile_f4_canary_candidate_source.__qualname__,
            "source": inspect.getsource(compile_f4_canary_candidate_source),
        }
    )


def _lane_templates(family_id: str) -> dict[str, dict[str, Any]]:
    prefix = f"f4-canary:{family_id}"
    return {
        "PRODUCER": {
            "lane_id": f"{prefix}:producer",
            "mode": "audit",
            "write": False,
            "allowed_tools": list(_READ_TOOLS),
            "prompt": (
                "Closed-book transform: use only the controller-bound inputs. Return the "
                f"PRODUCER envelope for {{{{WORK_KEY}}}} with producer_id={prefix}:producer, "
                "status=VERIFIED and claim_refs=[claim:f4-live], plus every binding and "
                "derived field required by the appended runtime contract."
            ),
        },
        "CRITIQUE": {
            "lane_id": f"{prefix}:critic",
            "mode": "audit",
            "write": False,
            "allowed_tools": list(_READ_TOOLS),
            "prompt": (
                "Closed-book transform: return the CRITIQUE envelope for {{WORK_KEY}} with "
                f"critic_id={prefix}:critic, verdict=APPROVED and finding_refs=[], using "
                "producer artifact "
                "{{PRODUCER_ARTIFACT_REF}} with hash {{PRODUCER_ARTIFACT_HASH}}; "
                "include every binding and derived field required by the appended runtime "
                "contract."
            ),
        },
        "VERIFIER": {
            "lane_id": f"{prefix}:verifier",
            "mode": "audit",
            "write": False,
            "allowed_tools": list(_READ_TOOLS),
            "prompt": (
                "Closed-book transform: return the VERIFIER envelope for {{WORK_KEY}} with "
                f"verifier_id={prefix}:verifier, verdict=VERIFIED and "
                "evidence_refs=[evidence:f4-live], using producer artifact "
                "{{PRODUCER_ARTIFACT_REF}} with hash {{PRODUCER_ARTIFACT_HASH}} and critique "
                "{{CRITIQUE_ARTIFACT_REF}} with hash {{CRITIQUE_ARTIFACT_HASH}}; include "
                "every binding and derived field required by the appended runtime contract."
            ),
        },
    }


def compile_f4_canary_candidate_source(
    *,
    active_research_surface: Mapping[str, Any],
    selection_manifest: IndependentExpectedSelectionDomainManifestVersion | Mapping[str, Any],
    method_registry: Mapping[str, Any],
    method_id: str,
    source_dependency_graph: Mapping[str, Any],
    world_snapshot_hash: str,
    knowledge_cutoff: str,
) -> dict[str, dict[str, Any]]:
    """Compile the complete F4 canary question and its 13 derived candidates."""

    if not _is_sha256(world_snapshot_hash):
        raise ValueError("world_snapshot_hash must be a lowercase SHA-256")
    _validate_knowledge_cutoff(knowledge_cutoff)
    manifest = (
        selection_manifest
        if isinstance(selection_manifest, IndependentExpectedSelectionDomainManifestVersion)
        else IndependentExpectedSelectionDomainManifestVersion.model_validate(selection_manifest)
    )
    manifest_components = _manifest_family_components(manifest)
    surface_components = _active_surface_family_components(
        active_research_surface,
        manifest_components=manifest_components,
    )
    registry, registry_hash = _method_registry(method_registry)
    method = registry.get(method_id)
    if method is None:
        raise ValueError("method_id is not present in the validated method registry")
    raw_registry = method_registry.get("registrations", method_registry)
    if not isinstance(raw_registry, Mapping):
        raise TypeError("method registry registrations must be an object")
    method_admission = raw_registry[method_id]
    origins, graph_hash = source_origin_index(source_dependency_graph)
    source_refs = tuple(sorted(origins))
    if not source_refs:
        raise ValueError("source dependency graph has no bound sources")

    surface_hash = str(active_research_surface["content_sha256"])
    cutoff_hash = canonical_sha256({"knowledge_cutoff": knowledge_cutoff})
    generator_hash = _generator_source_sha256()
    input_hashes = {
        "active_research_surface_sha256": surface_hash,
        "selection_manifest_sha256": manifest.content_hash,
        "method_registry_sha256": registry_hash,
        "source_dependency_graph_sha256": graph_hash,
        "world_snapshot_sha256": world_snapshot_hash,
        "knowledge_cutoff_sha256": cutoff_hash,
    }
    question = _versioned(
        "ResearchQuestion",
        QUESTION_SCHEMA_VERSION,
        {
            "question_id": "f4-canary:one-active-component-per-family:v1",
            "scope_type": "CANONICAL_ACTIVE_FAMILY_CANARY",
            "candidate_generator_id": GENERATOR_ID,
            "candidate_generator_source_sha256": generator_hash,
            "family_generation_rule": "ONE_LEXICOGRAPHICALLY_MINIMUM_ACTIVE_COMPONENT_PER_FAMILY",
            "source_assignment_rule": "SORTED_SOURCE_ROUND_ROBIN_BY_SORTED_FAMILY_ID",
            "expected_family_ids": list(EXPECTED_FAMILY_IDS),
            "expected_candidate_count": len(EXPECTED_FAMILY_IDS),
            "method_id": method_id,
            "input_hashes": input_hashes,
        },
    )

    candidate_entries: list[dict[str, Any]] = []
    work_input_hashes = tuple(sorted(set(input_hashes.values())))
    for index, family_id in enumerate(EXPECTED_FAMILY_IDS):
        selected_component_id = surface_components[family_id][0]
        source_ref = source_refs[index % len(source_refs)]
        projection_hash = source_projection_hash(source_dependency_graph, (source_ref,))
        work_item = ResearchWorkItem(
            physical_role="ACTIVE_SETTLEMENT",
            kind="F4_CANARY_ACTIVE_FAMILY",
            source_ref=source_ref,
            source_dependency_refs=(),
            active_settlement_refs=(selected_component_id,),
            upstream_work_keys=(),
            intent_slice=f"f4-canary:{family_id}:{selected_component_id}",
            selection_manifest_hash=manifest.content_hash,
            method_id=method_id,
            method_registration_hash=str(method["registration_sha256"]),
            method_admission_hash=str(method["admission_sha256"]),
            world_snapshot_hash=world_snapshot_hash,
            input_snapshot_hashes=work_input_hashes,
            knowledge_cutoff=knowledge_cutoff,
            budget_ref="budget:f4-canary:one-per-active-family:v1",
            error_budget_ledger_ref=f"ledger:f4-canary:{family_id}:v1",
            output_schema_ref=str(method["registration"]["output_schema_ref"]),
            handoff_schema_ref="xinao.agent_handoff.v1",
            evidence_schema_ref="xinao.evidence_manifest.v1",
            correlation_id=f"f4-canary:{family_id}",
            expected_information_gain=f"verify executable F4 path for {family_id}",
            evidence_requirements=(
                "bound-source-lineage",
                "independent-critique",
                "independent-verification",
            ),
            authority_scope=("read:bound-evidence", "read:bound-sources"),
            write_boundary="READ_ONLY_WORKER",
        )
        admit_work_item(
            work_item,
            selection_manifest=manifest,
            method_registry={method_id: method_admission},
        )
        work_payload = work_item.model_dump(mode="json")
        work_key = canonical_work_key(
            work_item,
            source_origin_by_ref=origins,
            source_projection_hash=projection_hash,
        )
        lanes = _lane_templates(family_id)
        entry_core = {
            "candidate_id": f"f4-canary:{family_id}:{selected_component_id}",
            "family_id": family_id,
            "selected_component_id": selected_component_id,
            "source_ref": source_ref,
            "source_origin_cluster_id": origins[source_ref],
            "source_projection_sha256": projection_hash,
            "work_key": work_key,
            "work_item_sha256": canonical_sha256(work_payload),
            "work_item": work_payload,
            "lane_templates_sha256": canonical_sha256(lanes),
            "lane_templates": lanes,
        }
        candidate_entries.append({**entry_core, "entry_sha256": canonical_sha256(entry_core)})

    snapshot = _versioned(
        "ResearchCandidateSourceSnapshot",
        SNAPSHOT_SCHEMA_VERSION,
        {
            "research_question_ref": question["content_sha256"],
            "candidate_generator_id": GENERATOR_ID,
            "candidate_generator_source_sha256": generator_hash,
            "input_hashes": input_hashes,
            "coverage": {
                "expected_family_count": len(EXPECTED_FAMILY_IDS),
                "observed_family_count": len(candidate_entries),
                "expected_family_ids": list(EXPECTED_FAMILY_IDS),
                "observed_family_ids": [row["family_id"] for row in candidate_entries],
                "complete": len(candidate_entries) == len(EXPECTED_FAMILY_IDS),
            },
            "candidate_count": len(candidate_entries),
            "candidate_entries": candidate_entries,
        },
    )
    return {
        "research_question": question,
        "candidate_source_snapshot": snapshot,
    }


def compile_f4_canary_candidate_snapshot(
    *,
    research_question: Mapping[str, Any],
    candidate_source_snapshot: Mapping[str, Any],
    active_research_surface: Mapping[str, Any],
    selection_manifest: IndependentExpectedSelectionDomainManifestVersion | Mapping[str, Any],
    method_registry: Mapping[str, Any],
    method_id: str,
    source_dependency_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Admit the generated 13-family source into an allocation-ready snapshot."""

    if (
        not verify_versioned_object(research_question)
        or research_question.get("object_type") != "ResearchQuestion"
        or research_question.get("schema_version") != QUESTION_SCHEMA_VERSION
        or not verify_versioned_object(candidate_source_snapshot)
        or candidate_source_snapshot.get("object_type") != "ResearchCandidateSourceSnapshot"
        or candidate_source_snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
        or candidate_source_snapshot.get("research_question_ref")
        != research_question.get("content_sha256")
    ):
        raise ValueError("candidate snapshot requires its verified generated source")

    manifest = (
        selection_manifest
        if isinstance(
            selection_manifest,
            IndependentExpectedSelectionDomainManifestVersion,
        )
        else IndependentExpectedSelectionDomainManifestVersion.model_validate(selection_manifest)
    )
    manifest_components = _manifest_family_components(manifest)
    surface_components = _active_surface_family_components(
        active_research_surface,
        manifest_components=manifest_components,
    )
    registry, registry_hash = _method_registry(method_registry)
    method = registry.get(method_id)
    if method is None:
        raise ValueError("method_id is not present in the validated method registry")
    origins, graph_hash = source_origin_index(source_dependency_graph)

    input_hashes = candidate_source_snapshot.get("input_hashes")
    if not isinstance(input_hashes, Mapping):
        raise TypeError("candidate source input hashes must be an object")
    required_input_hashes = {
        "active_research_surface_sha256": str(active_research_surface["content_sha256"]),
        "selection_manifest_sha256": manifest.content_hash,
        "method_registry_sha256": registry_hash,
        "source_dependency_graph_sha256": graph_hash,
    }
    if any(input_hashes.get(key) != value for key, value in required_input_hashes.items()):
        raise ValueError("candidate source foundation binding drifted")
    if (
        research_question.get("input_hashes") != dict(input_hashes)
        or research_question.get("method_id") != method_id
        or research_question.get("expected_family_ids") != list(EXPECTED_FAMILY_IDS)
        or research_question.get("expected_candidate_count") != len(EXPECTED_FAMILY_IDS)
        or candidate_source_snapshot.get("candidate_generator_id") != GENERATOR_ID
        or candidate_source_snapshot.get("candidate_generator_source_sha256")
        != research_question.get("candidate_generator_source_sha256")
    ):
        raise ValueError("candidate source question binding drifted")
    world_snapshot_hash = input_hashes.get("world_snapshot_sha256")
    cutoff_hash = input_hashes.get("knowledge_cutoff_sha256")
    if not _is_sha256(world_snapshot_hash) or not _is_sha256(cutoff_hash):
        raise ValueError("candidate source world or cutoff binding is invalid")

    coverage = candidate_source_snapshot.get("coverage")
    raw_entries = candidate_source_snapshot.get("candidate_entries")
    if (
        coverage
        != {
            "expected_family_count": len(EXPECTED_FAMILY_IDS),
            "observed_family_count": len(EXPECTED_FAMILY_IDS),
            "expected_family_ids": list(EXPECTED_FAMILY_IDS),
            "observed_family_ids": list(EXPECTED_FAMILY_IDS),
            "complete": True,
        }
        or not isinstance(raw_entries, list)
        or candidate_source_snapshot.get("candidate_count") != len(raw_entries)
        or len(raw_entries) != len(EXPECTED_FAMILY_IDS)
    ):
        raise ValueError("candidate source does not prove exact 13-family coverage")

    candidate_rows: list[dict[str, Any]] = []
    seen_work_keys: set[str] = set()
    expected_work_input_hashes = tuple(sorted(map(str, input_hashes.values())))
    for expected_family_id, raw in zip(EXPECTED_FAMILY_IDS, raw_entries, strict=True):
        if not isinstance(raw, Mapping):
            raise TypeError("candidate source entry must be an object")
        entry_core = dict(raw)
        recorded_entry_hash = entry_core.pop("entry_sha256", None)
        family_id = str(raw.get("family_id") or "")
        selected_component_id = str(raw.get("selected_component_id") or "")
        source_ref = str(raw.get("source_ref") or "")
        if (
            family_id != expected_family_id
            or selected_component_id != surface_components[family_id][0]
            or source_ref not in origins
            or recorded_entry_hash != canonical_sha256(entry_core)
        ):
            raise ValueError("candidate source entry is not canonically derived")

        work_item = ResearchWorkItem.model_validate(raw.get("work_item"))
        admit_work_item(
            work_item,
            selection_manifest=manifest,
            method_registry={
                method_id: method_registry.get("registrations", method_registry)[method_id]
            },
        )
        if (
            work_item.source_ref != source_ref
            or work_item.source_dependency_refs
            or work_item.active_settlement_refs != (selected_component_id,)
            or work_item.selection_manifest_hash != manifest.content_hash
            or work_item.method_id != method_id
            or work_item.method_registration_hash != str(method["registration_sha256"])
            or work_item.method_admission_hash != str(method["admission_sha256"])
            or work_item.world_snapshot_hash != world_snapshot_hash
            or work_item.input_snapshot_hashes != expected_work_input_hashes
            or work_item.write_boundary != "READ_ONLY_WORKER"
            or canonical_sha256({"knowledge_cutoff": work_item.knowledge_cutoff}) != cutoff_hash
        ):
            raise ValueError("candidate source work item binding drifted")

        projection_hash = source_projection_hash(
            source_dependency_graph,
            (source_ref,),
        )
        work_key = canonical_work_key(
            work_item,
            source_origin_by_ref=origins,
            source_projection_hash=projection_hash,
        )
        lanes = raw.get("lane_templates")
        if (
            raw.get("source_origin_cluster_id") != origins[source_ref]
            or raw.get("source_projection_sha256") != projection_hash
            or raw.get("work_key") != work_key
            or raw.get("work_item_sha256") != canonical_sha256(work_item.model_dump(mode="json"))
            or not isinstance(lanes, Mapping)
            or set(lanes) != {"PRODUCER", "CRITIQUE", "VERIFIER"}
            or raw.get("lane_templates_sha256") != canonical_sha256(lanes)
            or any(
                not isinstance(lane, Mapping)
                or lane.get("write") is not False
                or lane.get("allowed_tools") != _READ_TOOLS
                for lane in lanes.values()
            )
        ):
            raise ValueError("candidate source runtime entry binding drifted")
        if work_key in seen_work_keys:
            raise ValueError("candidate source contains duplicate canonical work")
        seen_work_keys.add(work_key)

        runtime_entry = {
            "work_item": work_item.model_dump(mode="json"),
            "lane_templates": {stage: dict(lane) for stage, lane in lanes.items()},
            "work_key": work_key,
            "portfolio_lane": "EXPLOITATION",
        }
        candidate_rows.append(
            {
                "candidate_id": str(raw["candidate_id"]),
                "source_record_sha256": str(recorded_entry_hash),
                "entry": runtime_entry,
                "entry_sha256": canonical_sha256(runtime_entry),
                "work_key": work_key,
                "family_id": family_id,
                "portfolio_lane": "EXPLOITATION",
                "active_settlement_refs": [selected_component_id],
            }
        )

    compiler_source_sha256 = canonical_sha256(
        {
            "module": compile_f4_canary_candidate_snapshot.__module__,
            "qualname": compile_f4_canary_candidate_snapshot.__qualname__,
            "source": inspect.getsource(compile_f4_canary_candidate_snapshot),
        }
    )
    core = {
        "object_type": "ResearchCandidateSnapshot",
        "schema_version": "xinao.research_candidate_snapshot.v2",
        "candidate_source_snapshot_ref": candidate_source_snapshot["content_sha256"],
        "research_question_ref": research_question["content_sha256"],
        "candidate_generator_id": GENERATOR_ID,
        "candidate_generator_source_sha256": candidate_source_snapshot[
            "candidate_generator_source_sha256"
        ],
        "active_surface_ref": active_research_surface["content_sha256"],
        "selection_manifest_ref": manifest.content_hash,
        "method_registry_sha256": registry_hash,
        "source_dependency_graph_ref": graph_hash,
        "world_snapshot_sha256": str(world_snapshot_hash),
        "knowledge_cutoff_sha256": str(cutoff_hash),
        "compiler_source_sha256": compiler_source_sha256,
        "coverage": {
            "expected_source_ids": [row["candidate_id"] for row in candidate_rows],
            "compiled_source_ids": [row["candidate_id"] for row in candidate_rows],
            "omitted_source_ids": [],
            "exact": True,
        },
        "candidate_count": len(candidate_rows),
        "candidate_rows": candidate_rows,
        "candidate_universe_sha256": canonical_sha256(candidate_rows),
    }
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchCandidateSnapshot@{digest[:16]}",
        "content_sha256": digest,
    }


def _payload_without_version_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in {"object_type", "schema_version", "version_id", "content_sha256"}
    }


def compile_f4_canary_candidate_source_v3(
    *,
    active_research_surface: Mapping[str, Any],
    selection_manifest: IndependentExpectedSelectionDomainManifestVersion | Mapping[str, Any],
    method_registry: Mapping[str, Any],
    method_id: str,
    source_dependency_graph: Mapping[str, Any],
    world_snapshot_hash: str,
    knowledge_cutoff: str,
) -> dict[str, dict[str, Any]]:
    """Upgrade the exact v2 canary universe to phase-qualified construction work."""

    base = compile_f4_canary_candidate_source(
        active_research_surface=active_research_surface,
        selection_manifest=selection_manifest,
        method_registry=method_registry,
        method_id=method_id,
        source_dependency_graph=source_dependency_graph,
        world_snapshot_hash=world_snapshot_hash,
        knowledge_cutoff=knowledge_cutoff,
    )
    base_question = base["research_question"]
    base_snapshot = base["candidate_source_snapshot"]
    base_generator_sha256 = str(base_question["candidate_generator_source_sha256"])
    generator_sha256 = canonical_sha256(
        {
            "compiler": inspect.getsource(compile_f4_canary_candidate_source_v3),
            "base_compiler": inspect.getsource(compile_f4_canary_candidate_source),
            "adapter": inspect.getsource(_payload_without_version_identity),
            "v3_admission": inspect.getsource(admit_work_item_v3),
        }
    )
    origins, _ = source_origin_index(source_dependency_graph)
    raw_registry = method_registry.get("registrations", method_registry)
    if not isinstance(raw_registry, Mapping):
        raise TypeError("method registry registrations must be an object")

    upgraded_entries: list[dict[str, Any]] = []
    for raw in base_snapshot["candidate_entries"]:
        entry_core = dict(raw)
        entry_core.pop("entry_sha256")
        work_payload = dict(entry_core["work_item"])
        work_payload.update(
            {
                "schema_version": "xinao.research_work_item.v3",
                "execution_phase": "FOUNDATION_CONSTRUCTION",
            }
        )
        work_item = ResearchWorkItemV3.model_validate(work_payload)
        admit_work_item_v3(
            work_item,
            selection_manifest=selection_manifest,
            method_registry={method_id: raw_registry[method_id]},
        )
        projection_sha256 = source_projection_hash(
            source_dependency_graph,
            (work_item.source_ref, *work_item.source_dependency_refs),
        )
        work_key = canonical_work_key_v3(
            work_item,
            source_origin_by_ref=origins,
            source_projection_hash=projection_sha256,
        )
        entry_core.update(
            {
                "source_projection_sha256": projection_sha256,
                "work_key": work_key,
                "work_item_sha256": canonical_sha256(work_payload),
                "work_item": work_payload,
            }
        )
        upgraded_entries.append(
            {**entry_core, "entry_sha256": canonical_sha256(entry_core)}
        )

    question_payload = _payload_without_version_identity(base_question)
    question_payload.update(
        {
            "candidate_generator_id": GENERATOR_ID_V3,
            "candidate_generator_source_sha256": generator_sha256,
            "base_candidate_generator_source_sha256": base_generator_sha256,
            "execution_phase": "FOUNDATION_CONSTRUCTION",
        }
    )
    question = _versioned(
        "ResearchQuestion",
        QUESTION_SCHEMA_VERSION_V3,
        question_payload,
    )
    snapshot_payload = _payload_without_version_identity(base_snapshot)
    snapshot_payload.update(
        {
            "research_question_ref": question["content_sha256"],
            "candidate_generator_id": GENERATOR_ID_V3,
            "candidate_generator_source_sha256": generator_sha256,
            "base_candidate_generator_source_sha256": base_generator_sha256,
            "execution_phase": "FOUNDATION_CONSTRUCTION",
            "candidate_entries": upgraded_entries,
            "candidate_count": len(upgraded_entries),
        }
    )
    snapshot = _versioned(
        "ResearchCandidateSourceSnapshot",
        SNAPSHOT_SCHEMA_VERSION_V3,
        snapshot_payload,
    )
    return {
        "research_question": question,
        "candidate_source_snapshot": snapshot,
    }


def compile_f4_canary_candidate_snapshot_v3(
    *,
    research_question: Mapping[str, Any],
    candidate_source_snapshot: Mapping[str, Any],
    active_research_surface: Mapping[str, Any],
    selection_manifest: IndependentExpectedSelectionDomainManifestVersion | Mapping[str, Any],
    method_registry: Mapping[str, Any],
    method_id: str,
    source_dependency_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Admit only the phase-qualified construction canary into a v3 snapshot."""

    if (
        not verify_versioned_object(research_question)
        or research_question.get("object_type") != "ResearchQuestion"
        or research_question.get("schema_version") != QUESTION_SCHEMA_VERSION_V3
        or research_question.get("execution_phase") != "FOUNDATION_CONSTRUCTION"
        or not verify_versioned_object(candidate_source_snapshot)
        or candidate_source_snapshot.get("object_type")
        != "ResearchCandidateSourceSnapshot"
        or candidate_source_snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION_V3
        or candidate_source_snapshot.get("execution_phase") != "FOUNDATION_CONSTRUCTION"
        or candidate_source_snapshot.get("research_question_ref")
        != research_question.get("content_sha256")
    ):
        raise ValueError("v3 candidate snapshot requires its verified construction source")
    base_generator_sha256 = research_question.get("base_candidate_generator_source_sha256")
    if (
        not _is_sha256(base_generator_sha256)
        or candidate_source_snapshot.get("base_candidate_generator_source_sha256")
        != base_generator_sha256
        or candidate_source_snapshot.get("candidate_generator_id") != GENERATOR_ID_V3
        or research_question.get("candidate_generator_id") != GENERATOR_ID_V3
        or candidate_source_snapshot.get("candidate_generator_source_sha256")
        != research_question.get("candidate_generator_source_sha256")
    ):
        raise ValueError("v3 candidate generator binding drifted")
    entries = candidate_source_snapshot.get("candidate_entries")
    if not isinstance(entries, list) or not entries:
        raise TypeError("v3 candidate source entries must be a list")
    parsed_items: list[ResearchWorkItemV3] = []
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise TypeError("v3 candidate source entry must be an object")
        work_item = parse_research_work_item(raw.get("work_item"))
        if (
            not isinstance(work_item, ResearchWorkItemV3)
            or work_item.execution_phase != "FOUNDATION_CONSTRUCTION"
        ):
            raise ValueError("v3 canary source contains non-construction work")
        parsed_items.append(work_item)

    expected_source = compile_f4_canary_candidate_source_v3(
        active_research_surface=active_research_surface,
        selection_manifest=selection_manifest,
        method_registry=method_registry,
        method_id=method_id,
        source_dependency_graph=source_dependency_graph,
        world_snapshot_hash=parsed_items[0].world_snapshot_hash,
        knowledge_cutoff=parsed_items[0].knowledge_cutoff,
    )
    if (
        dict(research_question) != expected_source["research_question"]
        or dict(candidate_source_snapshot) != expected_source["candidate_source_snapshot"]
    ):
        raise ValueError("v3 candidate source does not match the current exact generator")

    origins, _ = source_origin_index(source_dependency_graph)
    compatibility_entries: list[dict[str, Any]] = []
    for raw, work_item in zip(entries, parsed_items, strict=True):
        compatibility_work_payload = work_item.model_dump(mode="json")
        compatibility_work_payload.pop("execution_phase")
        compatibility_work_payload["schema_version"] = "xinao.research_work_item.v2"
        compatibility_work = ResearchWorkItem.model_validate(compatibility_work_payload)
        compatibility_work_key = canonical_work_key(
            compatibility_work,
            source_origin_by_ref=origins,
            source_projection_hash=str(raw["source_projection_sha256"]),
        )
        compatibility_entry_core = dict(raw)
        compatibility_entry_core.pop("entry_sha256")
        compatibility_entry_core.update(
            {
                "work_key": compatibility_work_key,
                "work_item_sha256": canonical_sha256(compatibility_work_payload),
                "work_item": compatibility_work_payload,
            }
        )
        compatibility_entries.append(
            {
                **compatibility_entry_core,
                "entry_sha256": canonical_sha256(compatibility_entry_core),
            }
        )

    compatibility_question_payload = _payload_without_version_identity(research_question)
    compatibility_question_payload.pop("base_candidate_generator_source_sha256")
    compatibility_question_payload.pop("execution_phase")
    compatibility_question_payload.update(
        {
            "candidate_generator_id": GENERATOR_ID,
            "candidate_generator_source_sha256": base_generator_sha256,
        }
    )
    compatibility_question = _versioned(
        "ResearchQuestion",
        QUESTION_SCHEMA_VERSION,
        compatibility_question_payload,
    )
    compatibility_source_payload = _payload_without_version_identity(candidate_source_snapshot)
    compatibility_source_payload.pop("base_candidate_generator_source_sha256")
    compatibility_source_payload.pop("execution_phase")
    compatibility_source_payload.update(
        {
            "research_question_ref": compatibility_question["content_sha256"],
            "candidate_generator_id": GENERATOR_ID,
            "candidate_generator_source_sha256": base_generator_sha256,
            "candidate_entries": compatibility_entries,
        }
    )
    compatibility_source = _versioned(
        "ResearchCandidateSourceSnapshot",
        SNAPSHOT_SCHEMA_VERSION,
        compatibility_source_payload,
    )
    compiled = compile_f4_canary_candidate_snapshot(
        research_question=compatibility_question,
        candidate_source_snapshot=compatibility_source,
        active_research_surface=active_research_surface,
        selection_manifest=selection_manifest,
        method_registry=method_registry,
        method_id=method_id,
        source_dependency_graph=source_dependency_graph,
    )
    entries_by_candidate = {str(raw["candidate_id"]): raw for raw in entries}
    candidate_rows: list[dict[str, Any]] = []
    for compiled_row in compiled["candidate_rows"]:
        raw = entries_by_candidate.pop(str(compiled_row["candidate_id"]), None)
        if raw is None or (
            compiled_row["family_id"] != raw["family_id"]
            or compiled_row["active_settlement_refs"]
            != list(raw["work_item"]["active_settlement_refs"])
            or compiled_row["portfolio_lane"] != "EXPLOITATION"
        ):
            raise ValueError("v3 candidate row cannot be projected from its v2 validation")
        runtime_entry = {
            "work_item": dict(raw["work_item"]),
            "lane_templates": {
                stage: dict(lane) for stage, lane in raw["lane_templates"].items()
            },
            "work_key": str(raw["work_key"]),
            "portfolio_lane": "EXPLOITATION",
        }
        candidate_rows.append(
            {
                **compiled_row,
                "source_record_sha256": str(raw["entry_sha256"]),
                "entry": runtime_entry,
                "entry_sha256": canonical_sha256(runtime_entry),
                "work_key": str(raw["work_key"]),
            }
        )
    if entries_by_candidate:
        raise ValueError("v3 candidate projection omitted a construction entry")
    compiler_source_sha256 = canonical_sha256(
        {
            "compiler": inspect.getsource(compile_f4_canary_candidate_snapshot_v3),
            "base_compiler": inspect.getsource(compile_f4_canary_candidate_snapshot),
            "adapter": inspect.getsource(_payload_without_version_identity),
        }
    )
    core = {
        key: value
        for key, value in compiled.items()
        if key not in {"schema_version", "version_id", "content_sha256"}
    }
    core.update(
        {
            "schema_version": CANDIDATE_SNAPSHOT_SCHEMA_VERSION_V3,
            "candidate_source_snapshot_ref": candidate_source_snapshot["content_sha256"],
            "research_question_ref": research_question["content_sha256"],
            "candidate_generator_id": GENERATOR_ID_V3,
            "candidate_generator_source_sha256": research_question[
                "candidate_generator_source_sha256"
            ],
            "compiler_source_sha256": compiler_source_sha256,
            "execution_phase": "FOUNDATION_CONSTRUCTION",
            "candidate_rows": candidate_rows,
            "candidate_universe_sha256": canonical_sha256(candidate_rows),
        }
    )
    digest = canonical_sha256(core)
    return {
        **core,
        "version_id": f"ResearchCandidateSnapshot@{digest[:16]}",
        "content_sha256": digest,
    }


__all__ = [
    "CANDIDATE_SNAPSHOT_SCHEMA_VERSION_V3",
    "EXPECTED_FAMILY_IDS",
    "GENERATOR_ID",
    "GENERATOR_ID_V3",
    "QUESTION_SCHEMA_VERSION",
    "QUESTION_SCHEMA_VERSION_V3",
    "SNAPSHOT_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION_V3",
    "compile_f4_canary_candidate_snapshot",
    "compile_f4_canary_candidate_snapshot_v3",
    "compile_f4_canary_candidate_source",
    "compile_f4_canary_candidate_source_v3",
]
